""" Oversight Analyst (spec Sections 8 and 8.1): explains the ratings that code has decided, in plain English

Its draft is checked by code before use: the number guard (every figure must be in the facts JSON) and
the rating guard (no other rating or verdict). A failing draft is sent back once with the list of
problems; if it fails again, a template narrative written by code is used and the run is flagged.
"""
from dataclasses import dataclass, field
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.models import DataFlag
from fund_performance.number_guard import check_numbers, check_ratings

FINDINGS = 3
MIN_ACTIONS, MAX_ACTIONS = 2, 3
NUMBER_CHECK_FAILED = "AI text failed number check"
AI_TEXT_UNAVAILABLE = "AI text unavailable"

INSTRUCTIONS = """
You are an investment oversight analyst. You explain ratings that have already been decided by code,
for an oversight director who is not a specialist.

Rules:
- Never change, soften or override a rating or the verdict. Use the ratings and the verdict exactly as
  given. Do not use the words Retain, Monitor, Review or "Pending data check" except to state the given
  verdict word for word.
- Only use numbers that appear in the facts. Do not calculate new numbers (no differences, sums, averages
  or conversions). Write each number with the same unit as in the facts: "%" for returns, "pp" for
  tracking differences and other gaps. You may round to 1 or 2 decimal places.
- If a figure has the note "please verify", write "(please verify)" next to it.
- If an item is CHECK DATA, explain what needs checking instead of drawing a conclusion. If an item is
  MANUAL CHECK, say what the reviewer must check. If a rating says "Add peer", say that a peer fund is
  needed to judge it.
- Plain English and short sentences. Explain any technical term in a few words the first time
  (e.g. "tracking difference, the gap between the fund's and the index's return").

Output:
- key_findings: exactly 3 findings, one or two sentences each.
- actions: 2 or 3 recommended actions for the oversight team, one sentence each.
- market_context: a short paragraph about what drove the market in the review period, based only on the
  search summaries given, citing their URLs. If no search summaries are given, return null.
"""


class AnalystOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_findings: list[str] = Field(description="Exactly 3 key findings")
    actions: list[str] = Field(description="2 or 3 recommended actions")
    market_context: str | None = Field(description="Short market context from the search summaries, or null")

    def text(self) -> str:
        return "\n".join(self.key_findings + self.actions + ([self.market_context] if self.market_context else []))


@dataclass
class Narrative:
    output: AnalystOutput
    source: Literal["ai", "template"]
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def analyst_agent():
    return build_agent("Oversight Analyst", INSTRUCTIONS, AnalystOutput, "analyst")


def _check_shape(out: AnalystOutput) -> AnalystOutput:
    """ Counts are checked in code (strict JSON schemas cannot hold them); a wrong count is invalid output """
    if len(out.key_findings) != FINDINGS:
        raise ValueError(f"expected {FINDINGS} key findings, got {len(out.key_findings)}")
    if not MIN_ACTIONS <= len(out.actions) <= MAX_ACTIONS:
        raise ValueError(f"expected {MIN_ACTIONS} to {MAX_ACTIONS} actions, got {len(out.actions)}")
    return out


def problems(out: AnalystOutput, facts: dict) -> list[str]:
    """ Everything wrong with a draft: numbers not in the facts, and changed ratings or verdict """
    bad = check_numbers(out.text(), facts)
    return ([f"number not in the facts: {n}" for n in bad]
            + check_ratings(out.text(), facts["scorecard"]))


def prompt(facts: dict, search_summaries: list[dict] | None = None) -> str:
    return ("Facts (decided by code; quote only these numbers):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
            + "\n\nSearch summaries:\n" + (json.dumps(search_summaries, indent=1, ensure_ascii=False)
                                           if search_summaries else "none"))


def rewrite_prompt(original: str, draft: AnalystOutput, issues: list[str]) -> str:
    return (original + "\n\nYour previous draft:\n" + draft.model_dump_json(indent=1)
            + "\n\nIt was rejected for these reasons:\n- " + "\n- ".join(issues)
            + "\n\nRewrite it. Use only numbers from the facts, with the same units, and the ratings and verdict "
              "exactly as given.")


def template(facts: dict) -> AnalystOutput:
    """ A narrative written by code from the scorecard alone, used when the AI text fails its checks """
    card = facts["scorecard"]
    pillars = {p["name"]: p for p in card["pillars"]}
    perf = pillars["Performance"]
    others = "; ".join(f"{name} {p['summary'] or p['rating']}" for name, p in pillars.items() if name != "Performance")
    findings = [f"Draft verdict: {card['verdict']}. {card['verdict_reason']}.",
                f"Performance is {perf['rating']}: {perf['reason']}.",
                f"Other questions: {others}."]
    actions = []
    if any(p["summary"] == "Add peer" for p in pillars.values()):
        actions.append("Add a comparable peer fund so that value and fees can be assessed.")
    if any(p["rating"] == "CHECK DATA" for p in pillars.values()):
        actions.append("Resolve the data checks listed in the report before relying on the verdict.")
    if any(p["rating"] == "MANUAL CHECK" for p in pillars.values()):
        actions.append("Complete the manual checks in the approval section.")
    actions.append("Confirm or change the draft verdict in the approval section.")
    if len(actions) < MIN_ACTIONS:
        actions.append("Check the figures and their sources on pages 2 and 3.")
    return AnalystOutput(key_findings=findings, actions=actions[:MAX_ACTIONS], market_context=None)


async def write_narrative(facts: dict, search_summaries: list[dict] | None = None, max_rewrites: int = 1,
                          run: RunFn | None = None) -> Narrative:
    """ Draft, check, send back once with the problems, then fall back to the template (spec 8.3) """
    agent = analyst_agent()
    first = prompt(facts, search_summaries)
    request, log = first, []
    for attempt in range(max_rewrites + 1):
        result = await run_structured(agent, request, AnalystOutput, convert=_check_shape, run=run)
        if not result.ok:
            log.append(f"Analyst gave no valid output: {'; '.join(result.errors)}")
            return Narrative(template(facts), "template", [DataFlag(
                check="analyst", level="warning", message=f"{AI_TEXT_UNAVAILABLE}: template narrative used")], log)
        if not search_summaries and result.output.market_context:
            # Market context must come from cited search summaries (spec 8.2); without them it is dropped
            result.output.market_context = None
            log.append("Market context dropped: no search summaries were given")
        issues = problems(result.output, facts)
        if not issues:
            log.append("Analyst draft passed the number and rating checks" + (" after one rewrite" if attempt else ""))
            return Narrative(result.output, "ai", [], log)
        log.append(f"Analyst draft {attempt + 1} rejected: " + "; ".join(issues))
        request = rewrite_prompt(first, result.output, issues)
    return Narrative(template(facts), "template", [DataFlag(
        check="analyst", level="warning", message=f"{NUMBER_CHECK_FAILED}: template narrative used")], log)
