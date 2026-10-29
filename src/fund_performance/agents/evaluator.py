""" Evaluator Agent (spec Section 8.4): a quality check on the Oversight Analyst's draft, after code's checks pass

It checks the draft against a fixed rubric and returns JSON only: {"pass": ..., "issues": [{check, detail}]}.
It never writes or edits the text and never changes a rating; its output has no text field to do so. It has its
own system prompt and its own model (config/models.yaml), so the Analyst's work is not graded by itself.

It judges only the AI's text, the market context; the findings and the actions are written by code and shown
for context. Only public data reaches it: the facts JSON (from public documents and calculations), the
numbered search summaries (without URLs) and the draft.
"""
from dataclasses import dataclass, field
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.glossary import glossary_lines

Check = Literal["no_rating_change", "supported_claims", "sources_cited", "check_data_handled", "plain_english"]

INSTRUCTIONS = f"""
You are a strict quality checker for a draft investment oversight review. You do not write or edit text,
and you never suggest a different rating or verdict. You check the draft against the rubric below and
return JSON only: "pass" (true only if every check passes) and "issues" (one entry per problem found,
empty when pass is true). Each issue names its check and gives a short, specific detail that the writer
can fix, quoting the words at fault.

What you judge: only the part marked "to_judge", the market context, written by an AI. The findings and the
actions are written by code from the scorecard and data notes; they are shown for context only. Never raise an
issue about them. Ratings and verdict were decided by code and are correct by definition. Judge the
draft only against the facts and sources given.

Rubric (each must pass):
1. no_rating_change: the text never states or suggests a rating or verdict, or a different one.
2. supported_claims: every statement is supported by a cited source; it describes direction only (no figures)
   and only the part of the review period the cited sources cover, saying which part.
3. sources_cited: every statement about markets or news cites a numbered source such as [1].
4. check_data_handled: the text does not draw a conclusion about any CHECK DATA item.
5. plain_english: short sentences. A term in the glossary below, or an abbreviation in it (pp, PNAV, NAV,
   OCF, R², AoV, AFM), has its short definition in brackets at its first use.
   Only glossary terms need a definition. Everyday market words need none: e.g. AI, large-cap, technology
   shares, Treasury yields, interest rates, inflation, volatility, earnings.

Glossary (the only terms that need a definition):
{chr(10).join("- " + line for line in glossary_lines())}

Do not raise an issue about style choices the rubric does not cover.
"""


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: Check
    detail: str


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    passed: bool = Field(alias="pass", description="True only if every rubric check passes")
    issues: list[Issue] = Field(description="One entry per problem; empty when pass is true")


@dataclass
class Review:
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    error: str | None = None                  # the Evaluator gave no valid result
    unreachable: bool = False                 # ... because the call failed (network, key, quota), not bad output

    @property
    def failed_checks(self) -> list[str]:
        return list(dict.fromkeys(i.check for i in self.issues))

    def problems(self) -> list[str]:
        """ The issues as a problem list for the Analyst's one rewrite """
        return [f"quality ({i.check}): {i.detail}" for i in self.issues]


def evaluator_agent():
    return build_agent("Evaluator Agent", INSTRUCTIONS, EvaluatorOutput, "evaluator")


def evaluator_input(facts: dict, sources: list[dict], draft: dict) -> str:
    """ The facts, the numbered sources (no URLs) and the draft """
    numbered = [{"source": f"[{s['number']}]", "query": s["query"], "date": s.get("date"),
                 "summary": s["summary"]} for s in sources]
    return ("Facts (decided by code):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
            + "\n\nSources:\n" + (json.dumps(numbered, indent=1, ensure_ascii=False) if numbered else "none")
            + "\n\nDraft to check:\n" + json.dumps(draft, indent=1, ensure_ascii=False))


def _consistent(out: EvaluatorOutput) -> EvaluatorOutput:
    if not out.passed and not out.issues:
        raise ValueError("pass is false but no issues are given")
    return out


async def review(facts: dict, sources: list[dict], draft: dict, run: RunFn | None = None) -> Review:
    """ Check one draft; invalid output is retried once. Issues with pass true still count as a fail, so a
    problem the Evaluator names is never ignored """
    result = await run_structured(evaluator_agent(), evaluator_input(facts, sources, draft), EvaluatorOutput,
                                  convert=_consistent, run=run)
    if not result.ok:
        return Review(False, error="; ".join(result.errors), unreachable=any("call failed" in e for e in result.errors))
    out = result.output
    return Review(out.passed and not out.issues, out.issues)
