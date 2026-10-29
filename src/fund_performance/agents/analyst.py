""" Oversight Analyst (spec Sections 8 and 8.1): explains, in plain English, what code has decided

The split between code and AI:
- Code writes finding 1 (the Mandate and Performance ratings with their reasons) and the actions (the
  candidate actions, word for word).
- The AI writes only findings 2 and 3 (the "below the surface" insights from the data notes) and the market
  context. Code checks that text (numbers, labels and periods, ratings, sentences, wording, insights), then the
  Evaluator Agent checks its quality (spec 8.4). Each has its own rewrites (config); every rewrite gets all the
  issues found so far. If a draft still fails, a template narrative written by code is used and the run is
  flagged.
"""
from dataclasses import dataclass, field
import json
import re
from typing import Awaitable, Callable, Literal
from pydantic import BaseModel, ConfigDict, Field
from fund_performance.actions import candidate_actions, default_actions
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.agents.evaluator import Review
from fund_performance.glossary import glossary_lines
from fund_performance.models import DataFlag
from fund_performance.number_guard import check_labels, check_numbers, check_ratings, mentions

AI_FINDINGS = 2                         # findings 2 and 3; finding 1 is written by code
MIN_ACTIONS, MAX_ACTIONS = 2, 3
MAX_SENTENCES = 2                       # per finding
CHECKS_FAILED = "AI text failed checks"
QUALITY_FAILED = "AI text failed quality check"
QUALITY_NOT_DONE = "AI text not quality-checked"
AI_TEXT_UNAVAILABLE = "AI text unavailable"

STYLE_EXAMPLE = (
    "Its noon price makes it look 3.3 pp behind its index over 5 years. At its market-close price, PNAV (the "
    "fund's price worked out at market close), the gap is only 0.7 pp.")

INSTRUCTIONS = f"""
You are an investment oversight analyst writing for an oversight director. Write so that both experts and
people new to the industry can follow.

What you write: findings 2 and 3, and the market context. Code has already written finding 1 (the Mandate and
Performance ratings with their reasons) and the actions; they are shown to you. Do not repeat them.

Findings 2 and 3 are the "below the surface" points:
- One finding for each data note in the facts, using its key figure (marked "key": true). If there are fewer
  than 2 data notes, use the other finding for another point from the facts that finding 1 does not make.
- Each data note says what it "explains". Keep that link: the fee explains the yearly tracking difference,
  not the noon-price gap. The noon-price gap is a timing effect, not a cost.

Ratings and verdict:
- Never change, soften or override a rating or the verdict.
- Do not use the words Retain, Monitor, Review or "Pending data check" except to state the given verdict word
  for word.

Numbers:
- Only use numbers that appear in the facts. Do not calculate new numbers (no differences, sums, averages or
  conversions). Write each number with the same unit as in the facts: "%" or "pp". You may round to 1 or 2
  decimal places.
- Call a figure by what it is in the facts. A number next to "tracking difference", "tracking error" or
  "ongoing charge" must be that figure, for that period. A tracking difference is yearly: write "a year", its
  sign and its period, e.g. "tracking difference -0.10 pp a year over 5 years".
- If a figure has the note "please verify", write "(please verify)" next to it.

Style:
- Plain meaning first, technical term second, in brackets.
- Never put a minus sign after "behind" or "below": say "behind by 0.10%", not "behind by -0.10%".
- At the first use in your findings of a term from the glossary below, put its definition in brackets right
  after the term and its figure, e.g. "R² 1.00 (how closely fund and index move together)". Never explain a
  term in a separate sentence. After that, use the term alone.
- No unexplained abbreviations: write "ongoing charge (OCF)", not "OCF".
- Short sentences: under 20 words each. At most 2 sentences per finding.
- Write periods in words: "5 years", "12 months", never "5y" or "12m".
- If an item is CHECK DATA, say what needs checking instead of drawing a conclusion.

Glossary (use these definitions):
{chr(10).join("- " + line for line in glossary_lines())}

Example of the target style (from another review; never copy its numbers):
"{STYLE_EXAMPLE}"

Output:
- findings: exactly 2 findings (findings 2 and 3).
- market_context: a short paragraph on what drove the market in the review period, based only on the
  numbered sources given. Cite them as [1], [2]; never write a web address. Use no figures from the sources;
  describe direction only (e.g. "US shares rose, led by technology [1]"). Describe only what the cited sources
  cover: if they cover only part of the review period, say which part. If no sources are given, return null.

Code checks numbers, labels and periods, ratings, sentences and wording; a separate reviewer checks quality.
"""


class AnalystDraft(BaseModel):
    """ What the AI writes """
    model_config = ConfigDict(extra="forbid")
    findings: list[str] = Field(description="Exactly 2 findings: findings 2 and 3, the insights from the data notes")
    market_context: str | None = Field(description="Short market context from the search summaries, or null")

    def text(self) -> str:
        return "\n".join(self.findings + ([self.market_context] if self.market_context else []))


class ChosenAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate: str
    text: str


class AnalystOutput(BaseModel):
    """ The narrative in the report: finding 1 and the actions from code, findings 2 and 3 and the market
    context from the AI (or the template) """
    model_config = ConfigDict(extra="forbid")
    key_findings: list[str]
    actions: list[ChosenAction]
    market_context: str | None

    @property
    def action_texts(self) -> list[str]:
        return [a.text for a in self.actions]


@dataclass
class Narrative:
    output: AnalystOutput
    source: Literal["ai", "template"]
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)     # [n] -> query, url, date, for the report's sources list


def analyst_agent():
    return build_agent("Oversight Analyst", INSTRUCTIONS, AnalystDraft, "analyst")


def _check_shape(out: AnalystDraft) -> AnalystDraft:
    """ Counts are checked in code (strict JSON schemas cannot hold them); a wrong count is invalid output """
    if len(out.findings) != AI_FINDINGS:
        raise ValueError(f"expected {AI_FINDINGS} findings (findings 2 and 3), got {len(out.findings)}")
    return out


# --- What code writes: finding 1 and the actions ------------------------------------------------------------

RATING_IN_WORDS = {"GREEN": "Green", "AMBER": "Amber", "RED": "Red"}
NEEDS = {"CHECK DATA": "needs a data check", "MANUAL CHECK": "needs a manual check"}


def _rating_phrase(name: str, rating: str) -> str:
    """ "Mandate is Green", or "Performance needs a data check" """
    return f"{name} is {RATING_IN_WORDS[rating]}" if rating in RATING_IN_WORDS else f"{name} {NEEDS.get(rating, rating)}"


def _fact(facts: dict, *names: str) -> dict | None:
    by_name = {f.get("name"): f for f in facts.get("figures", [])}
    return next((by_name[n] for n in names if n in by_name), None)


def _where(f: dict) -> str:
    """ "over 3 years, factsheet" from a figure's name and source """
    period = f["name"].rsplit(".", 1)[-1]
    years = period[:-1] if period.endswith("y") and period[:-1].isdigit() else None
    source = {"factsheet": "factsheet", "calculated": "calculated", "ai_extracted": "factsheet, please verify"}
    return (f"over {years} year{'' if years == '1' else 's'}, " if years else "") + source.get(f.get("source"), "")


def _plain(text: str) -> str:
    text = re.sub(r"\b(\d+)y\b", lambda m: f"{m.group(1)} year{'' if m.group(1) == '1' else 's'}", text)
    return text.replace("TD_ex_cost", "cost-adjusted tracking difference").replace("TD", "tracking difference") \
        .replace("TE", "tracking error").replace("fund_pnav", "PNAV").replace("fund_nav", "NAV").rstrip(".")


def ratings_finding(facts: dict) -> str:
    """ Finding 1, written by code: the Mandate and Performance ratings with their reasons, in plain English """
    pillars = {p["name"]: p for p in facts["scorecard"]["pillars"]}
    n = facts.get("fund", {}).get("time_horizon_years", 5)
    index_fund = facts.get("fund", {}).get("objective_type") == "index_tracker"
    parts = []
    mandate = pillars.get("Mandate")
    if mandate:
        r2 = _fact(facts, f"relative.r2.{n}y", "risk.pnav.r2.3y")
        beta = _fact(facts, f"relative.beta.{n}y", "risk.pnav.beta.3y")
        if index_fund and mandate["rating"] in RATING_IN_WORDS and r2 and beta:
            moves = "moves in line with its index" if mandate["rating"] == "GREEN" else "does not fully move with its index"
            parts.append(f"{_rating_phrase('Mandate', mandate['rating'])}: the fund {moves} "
                         f"(R² {r2['value']:.2f} and beta {beta['value']:.2f} {_where(r2)}).")
        else:
            parts.append(f"{_rating_phrase('Mandate', mandate['rating'])}: {_plain(mandate['reason'])}.")
    perf = pillars.get("Performance")
    if perf:
        td = _fact(facts, f"comparison.td.{n}y")
        te = _fact(facts, f"relative.tracking_error.{n}y", "risk.pnav.tracking_error.3y")
        if index_fund and perf["rating"] in RATING_IN_WORDS and td:
            side = "behind" if td["value"] < 0 else "ahead of"
            te_text = f"; tracking error is {te['value']:.2f}% ({_where(te)})" if te else ""
            parts.append(f"{_rating_phrase('Performance', perf['rating'])}: the fund is {abs(td['value']):.2f}% a "
                         f"year {side} its index over {n} years (tracking difference {td['value']:+.2f} pp a year)"
                         f"{te_text}.")
        else:
            parts.append(f"{_rating_phrase('Performance', perf['rating'])}: {_plain(perf['reason'])}.")
    return " ".join(parts)


def candidates_for(facts: dict) -> list[dict]:
    """ The candidate actions code wrote into the facts (built here when the facts have none, e.g. in tests) """
    return facts.get("candidate_actions") or candidate_actions(facts)


def code_actions(facts: dict) -> list[ChosenAction]:
    """ The actions, exactly as code writes them: the required candidates first, then the rest in order """
    return [ChosenAction(candidate=i, text=t) for i, t in default_actions(candidates_for(facts), MIN_ACTIONS, MAX_ACTIONS)]


def assemble(facts: dict, draft: AnalystDraft) -> AnalystOutput:
    return AnalystOutput(key_findings=[ratings_finding(facts)] + draft.findings, actions=code_actions(facts),
                         market_context=draft.market_context)


# --- Code's checks on the AI's text ----------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s)\]]+|\bwww\.[^\s)\]]+")
_MINUS_AFTER = re.compile(r"\b(behind|below)\b(\s+\w+){0,3}?\s*[-−–]\s?\d", re.IGNORECASE)
_CITATION = re.compile(r"\[(\d+)\]")
_SHORT_PERIOD = re.compile(r"\b\d+\s?(y|yr|yrs|m)\b")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"'(\[]|\s*$)")      # not a decimal point or "e.g. the"


def sentences(text: str) -> int:
    return max(1, len(_SENTENCE_END.findall(text.strip())))


def style_problems(out: AnalystDraft, sources: int) -> list[str]:
    """ Wording rules checked by code: no minus after "behind"/"below", no web addresses in the text, citations
    only to sources that exist, periods in words, and at most 2 sentences per finding """
    text = out.text()
    found = [f"style: minus sign after '{m.group(1)}' in '{m.group(0)}'; write 'behind by 0.10%'"
             for m in _MINUS_AFTER.finditer(text)]
    found += [f"citation: web address in the text ({u}); cite the source as [n] instead" for u in _URL.findall(text)]
    found += [f"citation: [{n}] does not match a source" for n in _CITATION.findall(text) if not 1 <= int(n) <= sources]
    found += [f"style: write periods in words, not '{m.group(0)}'" for m in _SHORT_PERIOD.finditer(text)]
    found += [f"style: finding {i} has {n} sentences; use at most {MAX_SENTENCES}"
              for i, f in enumerate(out.findings, start=2) if (n := sentences(f)) > MAX_SENTENCES]
    return found


def missing_insights(out: AnalystDraft, facts: dict) -> list[str]:
    """ Each data note must be covered in findings 2 and 3: at least one of its key figures appears there """
    findings = " ".join(out.findings)
    missing = []
    for note in facts.get("data_notes", []):
        keys = [f for f in note["figures"] if f.get("key")]
        if keys and not any(mentions(findings, f["value"], f["unit"]) for f in keys):
            missing.append(f"insight: findings 2 and 3 do not cover this data note (use {keys[0]['display']}): "
                           f"{note['note']}")
    return missing


CHECK_KINDS = (("number", "number not in the facts"), ("number", "label:"), ("rating", "rating:"),
               ("rating", "verdict:"), ("wording", "style:"), ("wording", "citation:"), ("insights", "insight:"))


def failed_checks(issues: list[str]) -> list[str]:
    """ Which checks a draft failed, in a fixed order: number, rating, wording, insights """
    kinds = {kind for kind, prefix in CHECK_KINDS for i in issues if i.startswith(prefix)}
    return [k for k in ("number", "rating", "wording", "insights") if k in kinds]


def problems(out: AnalystDraft, facts: dict, sources: int = 0) -> list[str]:
    """ Everything wrong with the AI's text (findings 2 and 3, market context): numbers not in the facts or under
    the wrong label or period, changed ratings or verdict, the wording rules and missing insights. Web addresses
    are taken out before the number check (they are reported as citation problems) """
    text = _URL.sub("[source]", out.text())
    bad = check_numbers(text, facts)
    return ([f"number not in the facts: {n}" for n in bad] + check_labels(text, facts)
            + check_ratings(text, facts["scorecard"]) + style_problems(out, sources) + missing_insights(out, facts))


# --- Prompts ----------------------------------------------------------------------------------------------------

def numbered_sources(search_summaries: list[dict] | None) -> list[dict]:
    """ Sources numbered [1], [2] ... for citing; the report lists each number with its URL """
    return [{"number": i, **s} for i, s in enumerate(search_summaries or [], start=1)]


def prompt(facts: dict, search_summaries: list[dict] | None = None) -> str:
    # The Analyst sees each source's number, query, date and summary, but not its URL, so it cites [n] only
    sources = [{"source": f"[{s['number']}]", "query": s["query"], "date": s["date"],
                "date_basis": s.get("date_basis") or "published", "summary": s["summary"]}
               for s in numbered_sources(search_summaries)]
    return ("Facts (decided by code; quote only these numbers):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
            + "\n\nSources:\n" + (json.dumps(sources, indent=1, ensure_ascii=False) if sources else "none")
            + "\n\nWritten by code (do not repeat):\nFinding 1: " + ratings_finding(facts)
            + "\nActions:\n" + "\n".join(f"- {a.text}" for a in code_actions(facts)))


KEEP_RULES = ("Fix every problem listed. Keep every rule your previous draft already passed: numbers only from the "
              "facts, with the same units; labels, 'a year' and periods next to each figure; at most 2 sentences per "
              "finding; glossary definitions in brackets at first use; the ratings and verdict exactly as given. "
              "Do not bring back any earlier problem.")


def rewrite_prompt(original: str, draft: AnalystDraft, current: list[str], earlier: list[str]) -> str:
    """ Each rewrite gets every issue found so far: this draft's, and the earlier drafts' (code and Evaluator) """
    text = (original + "\n\nYour previous draft:\n" + draft.model_dump_json(indent=1)
            + "\n\nIt was rejected for these reasons:\n- " + "\n- ".join(current))
    if earlier:
        text += "\n\nEarlier drafts were rejected for these reasons; do not bring any of them back:\n- " + "\n- ".join(earlier)
    return text + "\n\n" + KEEP_RULES


# --- The template narrative (code) -------------------------------------------------------------------------------

def _note(facts: dict, kind: str) -> dict | None:
    return next((n for n in facts.get("data_notes", []) if n.get("kind") == kind), None)


def _fig(note: dict, label_start: str, unit: str) -> float | None:
    return next((f["value"] for f in note["figures"] if f["label"].startswith(label_start) and f["unit"] == unit), None)


def _note_sentence(note: dict, years: int) -> str | None:
    """ One plain-English finding per data note, with its key figure """
    if note.get("kind") == "pricing":
        noon, fair = _fig(note, "Gap at noon prices", "pp"), _fig(note, "Fair gap", "pp")
        return (f"Its noon price makes it look {abs(noon):.1f} pp behind its index over {years} years. "
                f"At market close (PNAV) the gap is only {abs(fair):.1f} pp.")
    if note.get("kind") == "timing":
        return "Part of the gap to the index may be timing, because no market-close price (PNAV) is available."
    if note.get("kind") == "fee":
        ocf, ex = _fig(note, "Ongoing charge", "%"), _fig(note, "Cost-adjusted gap, in plain terms", "%")
        if ocf is None or ex is None:
            return None
        share = "Most of the yearly gap is the fee" if note["note"].startswith("Most") else \
            "The fee explains only part of the yearly gap"
        where = "would match its index" if ex == 0 else \
            f"is {abs(ex):.2f}% a year {'behind' if ex < 0 else 'ahead of'} its index over {years} years"
        return f"{share}, the {ocf:.2f}% yearly ongoing charge (OCF). With the fee added back, the fund {where}."
    return None


def _other_ratings_sentence(pillars: dict) -> str:
    parts = []
    for name, p in pillars.items():
        if name in ("Mandate", "Performance"):
            continue
        parts.append(f"{name} needs a peer fund to be judged" if p.get("summary") == "Add peer"
                     else _rating_phrase(name, p["rating"]))
    text = "; ".join(parts)
    return (text[:1].upper() + text[1:] + ".") if text else "The figures and their sources are on pages 2 and 3."


def template_draft(facts: dict) -> AnalystDraft:
    """ Findings 2 and 3 written by code, in plain English, from the data notes (so they pass the number guard and
    cover every required insight) """
    years = facts.get("fund", {}).get("time_horizon_years", 5)
    pillars = {p["name"]: p for p in facts["scorecard"]["pillars"]}
    findings = [s for n in facts.get("data_notes", []) if (s := _note_sentence(n, years))][:AI_FINDINGS]
    for extra in (_other_ratings_sentence(pillars), "The figures and their sources are on pages 2 and 3."):
        if len(findings) < AI_FINDINGS and extra not in findings:
            findings.append(extra)
    return AnalystDraft(findings=findings, market_context=None)


def template(facts: dict) -> AnalystOutput:
    """ The whole narrative written by code, used offline or when the AI text fails its checks """
    return assemble(facts, template_draft(facts))


# --- The flow --------------------------------------------------------------------------------------------------

QualityFn = Callable[[dict, list[dict], dict], Awaitable[Review]]


def _template(facts: dict, message: str, log: list[str]) -> Narrative:
    return Narrative(template(facts), "template", [DataFlag(check="analyst", level="warning", message=message)], log)


def evaluator_view(facts: dict, draft: AnalystDraft) -> dict:
    """ What the Evaluator sees: the AI's text to judge, and code's text for context only """
    return {"finding_1_written_by_code_not_judged": ratings_finding(facts),
            "findings_2_and_3_to_judge": draft.findings,
            "market_context_to_judge": draft.market_context,
            "actions_written_by_code_not_judged": [a.text for a in code_actions(facts)]}


async def write_narrative(facts: dict, search_summaries: list[dict] | None = None, max_rewrites: int = 2,
                          run: RunFn | None = None, quality_check: QualityFn | None = None,
                          max_evaluator_rewrites: int = 1) -> Narrative:
    """ The AI drafts findings 2 and 3 and the market context. Code's checks (spec 8.3) run first, with
    max_rewrites rewrites; the Evaluator (8.4) sees only drafts that pass them, with its own
    max_evaluator_rewrites. Every rewrite gets all the issues found so far. When a draft fails and no rewrite of
    that kind is left, the template narrative is used with a flag naming what failed """
    agent = analyst_agent()
    first = prompt(facts, search_summaries)
    request, log, so_far = first, [], []
    check_rewrites = evaluator_rewrites = draft_no = 0
    sources = numbered_sources(search_summaries)

    def rewrite(draft: AnalystDraft, current: list[str]) -> str:
        earlier = [i for i in so_far if i not in current]
        so_far.extend(i for i in current if i not in so_far)
        return rewrite_prompt(first, draft, current, earlier)

    while True:
        result = await run_structured(agent, request, AnalystDraft, convert=_check_shape, run=run)
        if not result.ok:
            log.append(f"Analyst gave no valid output: {'; '.join(result.errors)}")
            return _template(facts, f"{AI_TEXT_UNAVAILABLE}: template narrative used", log)
        draft_no += 1
        draft = result.output
        if not search_summaries and draft.market_context:
            # Market context must come from cited search summaries (spec 8.2); without them it is dropped
            draft.market_context = None
            log.append("Market context dropped: no search summaries were given")
        issues = problems(draft, facts, len(sources))
        if issues:
            log.append(f"Analyst draft {draft_no} rejected by code's checks ({' / '.join(failed_checks(issues))}): "
                       + "; ".join(issues))
            if check_rewrites < max_rewrites:
                check_rewrites += 1
                request = rewrite(draft, issues)
                continue
            return _template(facts, f"{CHECKS_FAILED}: {' / '.join(failed_checks(issues))}; template narrative used", log)
        log.append(f"Analyst draft {draft_no} passed the number, rating and wording checks")
        if quality_check is not None:
            verdict = await quality_check(facts, sources, evaluator_view(facts, draft))
            if verdict.error:
                log.append(f"Evaluator gave no valid result: {verdict.error}")
                why = "could not be reached" if verdict.unreachable else "gave no valid answer after one retry"
                return _template(facts, f"{QUALITY_NOT_DONE}: the Evaluator {why}; template narrative used", log)
            if not verdict.passed:
                log.append(f"Evaluator rejected draft {draft_no}: " + "; ".join(verdict.problems()))
                if evaluator_rewrites < max_evaluator_rewrites:
                    evaluator_rewrites += 1
                    request = rewrite(draft, verdict.problems())
                    continue
                return _template(facts, f"{QUALITY_FAILED}: the Evaluator rejected the draft "
                                        f"({', '.join(verdict.failed_checks)}); template narrative used", log)
            log.append(f"Evaluator passed draft {draft_no}")
        return Narrative(assemble(facts, draft), "ai", [], log, sources if draft.market_context else [])
