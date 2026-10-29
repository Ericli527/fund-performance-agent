""" Oversight Analyst (spec Sections 8 and 8.1): explains the ratings that code has decided, in plain English

Its draft is checked by code before use: the number guard (every figure must be in the facts JSON) and
the rating guard (no other rating or verdict). A failing draft is sent back once with the list of
problems; if it fails again, a template narrative written by code is used and the run is flagged.
"""
from dataclasses import dataclass, field
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.glossary import glossary_lines
from fund_performance.models import DataFlag
from fund_performance.number_guard import check_numbers, check_ratings, mentions

FINDINGS = 3
MIN_ACTIONS, MAX_ACTIONS = 2, 3
CHECKS_FAILED = "AI text failed checks"
AI_TEXT_UNAVAILABLE = "AI text unavailable"

STYLE_EXAMPLE = (
    "The fund tracks its index closely. Its noon price makes it look 3.3 pp behind over 5 years, because the "
    "index is measured at market close. Using the fund's market-close price (PNAV), the gap is only 0.7 pp, and "
    "most of it is the 0.06% yearly fee.")

INSTRUCTIONS = f"""
You are an investment oversight analyst. You explain ratings that have already been decided, for an
oversight director. Write so that both experts and people new to the industry can follow.

Ratings and verdict:
- Never change, soften or override a rating or the verdict. Use them exactly as given.
- Call the verdict the "Draft verdict". Never say "code verdict" or describe how the system works.
- Do not use the words Retain, Monitor, Review or "Pending data check" except to state the given
  verdict word for word.

Numbers:
- Only use numbers that appear in the facts. Do not calculate new numbers (no differences, sums,
  averages or conversions). Write each number with the same unit as in the facts: "%" or "pp".
  You may round to 1 or 2 decimal places.
- If a figure has the note "please verify", write "(please verify)" next to it.

Style:
- Plain meaning first, technical term second, in brackets. For example: "The fund falls behind its
  index by about 0.10% a year (tracking difference -0.10 pp)."
- Never put a minus sign after "behind" or "below": say "behind by 0.10%", not "behind by -0.10%".
- Explain each technical term once, the first time you use it, in under 10 words, using the glossary
  below. After that, use the term alone.
- No unexplained abbreviations: write "ongoing charge (OCF)", not "OCF".
- Short sentences: under 20 words each. At most 2 sentences per finding.
- Every data note must be explained in the findings, using its key figure (marked "key": true). These are
  the "below the surface" points.
- Write periods in words: "5 years", "12 months", never "5y" or "12m".
- Do not repeat a point in both the findings and the actions.
- If an item is CHECK DATA, say what needs checking instead of drawing a conclusion. If an item is
  MANUAL CHECK, say what the reviewer must check. If a rating says "Add peer", say that a peer fund is
  needed to judge it.

Glossary (use these definitions):
{chr(10).join("- " + line for line in glossary_lines())}

Example of the target style (from another review; never copy its numbers):
"{STYLE_EXAMPLE}"

Output:
- key_findings: exactly 3 findings.
- actions: 2 or 3 actions. Each is a real task for the oversight team and says when to do it
  (e.g. "before signing off this review", "at the next quarterly review"). Never restate the verdict
  as an action, and never write an internal or technical note about the data or the system.
- market_context: a short paragraph on what drove the market in the review period, based only on the
  numbered sources given. Cite them as [1], [2]; never write a web address. Use no figures from the
  sources; describe direction only (e.g. "US shares rose, led by technology [1]"). Describe only what
  the cited sources cover: if they cover only part of the review period, say which part. If no sources
  are given, return null.
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
    sources: list[dict] = field(default_factory=list)     # [n] -> query, url, date, for the report's sources list


def analyst_agent():
    return build_agent("Oversight Analyst", INSTRUCTIONS, AnalystOutput, "analyst")


def _check_shape(out: AnalystOutput) -> AnalystOutput:
    """ Counts are checked in code (strict JSON schemas cannot hold them); a wrong count is invalid output """
    if len(out.key_findings) != FINDINGS:
        raise ValueError(f"expected {FINDINGS} key findings, got {len(out.key_findings)}")
    if not MIN_ACTIONS <= len(out.actions) <= MAX_ACTIONS:
        raise ValueError(f"expected {MIN_ACTIONS} to {MAX_ACTIONS} actions, got {len(out.actions)}")
    return out


_URL = re.compile(r"https?://[^\s)\]]+|\bwww\.[^\s)\]]+")
_MINUS_AFTER = re.compile(r"\b(behind|below)\b(\s+\w+){0,3}?\s*[-\u2212\u2013]\s?\d", re.IGNORECASE)
_CITATION = re.compile(r"\[(\d+)\]")
_SHORT_PERIOD = re.compile(r"\b\d+\s?(y|yr|yrs|m)\b")


def style_problems(out: AnalystOutput, sources: int) -> list[str]:
    """ Wording rules checked by code: no minus after "behind"/"below", no web addresses in the text, and
    citations only to sources that exist """
    text = out.text()
    found = [f"style: minus sign after '{m.group(1)}' in '{m.group(0)}'; write 'behind by 0.10%'"
             for m in _MINUS_AFTER.finditer(text)]
    found += [f"citation: web address in the text ({u}); cite the source as [n] instead" for u in _URL.findall(text)]
    found += [f"citation: [{n}] does not match a source" for n in _CITATION.findall(text) if not 1 <= int(n) <= sources]
    found += [f"style: write periods in words, not '{m.group(0)}'" for m in _SHORT_PERIOD.finditer(text)]
    return found


def missing_insights(out: AnalystOutput, facts: dict) -> list[str]:
    """ Each data note must be covered in the findings: at least one of its key figures appears there """
    findings = " ".join(out.key_findings)
    missing = []
    for note in facts.get("data_notes", []):
        keys = [f for f in note["figures"] if f.get("key")]
        if keys and not any(mentions(findings, f["value"], f["unit"]) for f in keys):
            missing.append(f"insight: the findings do not cover this data note (use {keys[0]['display']}): "
                           f"{note['note']}")
    return missing


CHECK_KINDS = (("number", "number not in the facts"), ("rating", "rating:"), ("rating", "verdict:"),
               ("wording", "style:"), ("wording", "citation:"), ("insights", "insight:"))


def failed_checks(issues: list[str]) -> list[str]:
    """ Which checks a draft failed, in a fixed order: number, rating, wording, insights """
    kinds = {kind for kind, prefix in CHECK_KINDS for i in issues if i.startswith(prefix)}
    return [k for k in ("number", "rating", "wording", "insights") if k in kinds]


def problems(out: AnalystOutput, facts: dict, sources: int = 0) -> list[str]:
    """ Everything wrong with a draft: numbers not in the facts, changed ratings or verdict, and the wording
    rules above. Web addresses are taken out before the number check (they are reported as citation problems) """
    text = _URL.sub("[source]", out.text())
    bad = check_numbers(text, facts)
    return ([f"number not in the facts: {n}" for n in bad]
            + check_ratings(text, facts["scorecard"]) + style_problems(out, sources) + missing_insights(out, facts))


def numbered_sources(search_summaries: list[dict] | None) -> list[dict]:
    """ Sources numbered [1], [2] ... for citing; the report lists each number with its URL """
    return [{"number": i, **s} for i, s in enumerate(search_summaries or [], start=1)]


def prompt(facts: dict, search_summaries: list[dict] | None = None) -> str:
    # The Analyst sees each source's number, query, date and summary, but not its URL, so it cites [n] only
    sources = [{"source": f"[{s['number']}]", "query": s["query"], "date": s["date"],
                "date_basis": s.get("date_basis") or "published", "summary": s["summary"]}
               for s in numbered_sources(search_summaries)]
    return ("Facts (decided by code; quote only these numbers):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
            + "\n\nSources:\n" + (json.dumps(sources, indent=1, ensure_ascii=False) if sources else "none"))


def rewrite_prompt(original: str, draft: AnalystOutput, issues: list[str]) -> str:
    return (original + "\n\nYour previous draft:\n" + draft.model_dump_json(indent=1)
            + "\n\nIt was rejected for these reasons:\n- " + "\n- ".join(issues)
            + "\n\nRewrite it. Use only numbers from the facts, with the same units, and the ratings and verdict "
              "exactly as given.")


RATING_WORDS = {"GREEN": "Green", "AMBER": "Amber", "RED": "Red", "CHECK DATA": "a data check",
                "MANUAL CHECK": "a manual check"}


def _note(facts: dict, kind: str) -> dict | None:
    return next((n for n in facts.get("data_notes", []) if n.get("kind") == kind), None)


def _fig(note: dict, label_start: str, unit: str) -> float | None:
    return next((f["value"] for f in note["figures"] if f["label"].startswith(label_start) and f["unit"] == unit), None)


def _pct(value: float, unit: str, decimals: int) -> str:
    return f"{abs(value):.{decimals}f}%" if unit == "%" else f"{abs(value):.{decimals}f} pp"


def _performance_sentence(facts: dict, perf: dict, years: int) -> str:
    """ Plain meaning first, the technical term second (in brackets); figures taken from the data notes """
    fee = _note(facts, "fee")
    td_pct = _fig(fee, "Fund behind its index, in plain terms", "%") if fee else None
    td_pp = _fig(fee, "Tracking difference", "pp") if fee else None
    ocf = _fig(fee, "Ongoing charge", "%") if fee else None
    if td_pct is None or td_pp is None:
        return f"Performance is rated {RATING_WORDS.get(perf['rating'], perf['rating'])}; the reasons are on page 2."
    side = "behind" if td_pct < 0 else "ahead of"
    close = "stays close to" if perf["rating"] == "GREEN" else "does not track"
    first = (f"The fund {close} its index: it is {side} it by {_pct(td_pct, '%', 2)} a year over {years} years "
             f"(tracking difference {td_pp:+.2f} pp).")
    if ocf is not None and fee["note"].startswith("Most"):
        return first + f" Most of this is the {ocf:.2f}% yearly ongoing charge (OCF)."
    return first


def _insight_sentence(facts: dict, years: int) -> str | None:
    pricing, timing = _note(facts, "pricing"), _note(facts, "timing")
    if pricing:
        noon = _fig(pricing, "Gap at noon prices", "pp")
        fair = _fig(pricing, "Fair gap", "pp")
        return (f"Its noon price makes it look {_pct(noon, 'pp', 1)} behind its index over {years} years. "
                f"At market close (PNAV) the gap is only {_pct(fair, 'pp', 1)}.")
    if timing:
        return "Part of the gap to the index may be timing, because no market-close price (PNAV) is available."
    return None


def _other_ratings_sentence(pillars: dict) -> str:
    parts = []
    for name, p in pillars.items():
        if name == "Performance":
            continue
        if p["summary"] == "Add peer":
            parts.append(f"{name} needs a peer fund to be judged")
        else:
            parts.append(f"{name} is {RATING_WORDS.get(p['rating'], p['rating'])}")
    return "; ".join(parts).capitalize()[:1] + "; ".join(parts)[1:] + "."


def template(facts: dict) -> AnalystOutput:
    """ A narrative written by code, in plain English, used when the AI text fails its checks. Its figures come
    from the data notes, so it passes the number guard and covers every required insight """
    card = facts["scorecard"]
    pillars = {p["name"]: p for p in card["pillars"]}
    years = facts.get("fund", {}).get("time_horizon_years", 5)
    reason = ("Value and fees cannot be judged until a comparable peer fund is added."
              if card["verdict"] == "Monitor until a peer is added" else f"{card['verdict_reason']}.")
    findings = [f"Draft verdict: {card['verdict']}. {reason}",
                _performance_sentence(facts, pillars["Performance"], years),
                _insight_sentence(facts, years) or _other_ratings_sentence(pillars)]
    actions = []
    if any(p["summary"] == "Add peer" for p in pillars.values()):
        actions.append("Choose a comparable peer fund before the next quarterly review, so value and fees can be judged.")
    if any(p["rating"] == "CHECK DATA" for p in pillars.values()):
        actions.append("Resolve the data checks listed in the appendix before signing off this review.")
    if any(p["rating"] == "MANUAL CHECK" for p in pillars.values()):
        actions.append("Check the fund's style and holdings against its policy before signing off this review.")
    if len(actions) < MIN_ACTIONS:
        actions.append("Read the figures and their sources on pages 2 and 3 before signing off this review.")
    if len(actions) < MIN_ACTIONS:
        actions.append("Record the decision and its reasons in the approval box at this review.")
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
        issues = problems(result.output, facts, len(search_summaries or []))
        if not issues:
            log.append("Analyst draft passed the number, rating and wording checks" + (" after one rewrite" if attempt else ""))
            sources = numbered_sources(search_summaries) if result.output.market_context else []
            return Narrative(result.output, "ai", [], log, sources)
        log.append(f"Analyst draft {attempt + 1} rejected ({' / '.join(failed_checks(issues))}): " + "; ".join(issues))
        request = rewrite_prompt(first, result.output, issues)
    failed = " / ".join(failed_checks(issues))
    return Narrative(template(facts), "template", [DataFlag(
        check="analyst", level="warning", message=f"{CHECKS_FAILED}: {failed}; template narrative used")], log)
