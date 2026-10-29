""" Oversight Analyst (spec Sections 8 and 8.1): the narrative, in plain English

The split between code and AI (v1):
- Code writes all the findings: finding 1 (the Mandate and Performance ratings with their reasons) and one
  finding per data note (the "below the surface" insights, fixed facts with fixed wording), and the actions
  (the candidate actions, word for word).
- The AI writes only the market context, from the numbered sources. Code checks it (no figures, sentences,
  wording, citations, ratings), then the Evaluator Agent checks its quality (spec 8.4). Each has its own
  rewrites (config); every rewrite gets all the issues found so far. If it still fails, the market context is
  left out and the run is flagged.
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
from fund_performance.number_guard import check_labels, check_ratings, numbers_in

MIN_ACTIONS, MAX_ACTIONS = 2, 3
MAX_CONTEXT_SENTENCES = 3
CHECKS_FAILED = "AI text failed checks"
QUALITY_FAILED = "AI text failed quality check"
QUALITY_NOT_DONE = "AI text not quality-checked"
AI_TEXT_UNAVAILABLE = "AI text unavailable"
LEFT_OUT = "market context left out"

STYLE_EXAMPLE = ("US shares rose over the period, led by large technology companies [1]. Worries about interest "
                 "rates held markets back in the spring [2].")

INSTRUCTIONS = f"""
You write the market context for an investment oversight review: a short paragraph on what drove the fund's
market in the review period, for an oversight director. Write so that both experts and people new to the
industry can follow.

Code has already written the findings and the actions; they are shown to you. Do not repeat them.

Rules:
- Base it only on the numbered sources given. Cite them as [1], [2]; never write a web address.
- Direction only: no figures at all (no %, pp or numbers from the sources or the facts), e.g. "US shares
  rose, led by technology [1]".
- Describe only what the cited sources cover: if they cover only part of the review period, say which part.
- At most 3 sentences, each under 20 words. Plain English: everyday market words (technology shares, interest
  rates, inflation, volatility) are fine; explain a glossary term in brackets if you use one.
- Never mention, change or comment on a rating or the verdict.
- If no sources are given, return null.

Glossary (use these definitions if you use a term):
{chr(10).join("- " + line for line in glossary_lines())}

Example of the target style (from another review):
"{STYLE_EXAMPLE}"

Code checks figures, sentences, wording and citations; a separate reviewer checks quality.
"""


class AnalystDraft(BaseModel):
    """ What the AI writes: the market context only """
    model_config = ConfigDict(extra="forbid")
    market_context: str | None = Field(description="Short market context from the numbered sources, or null")

    def text(self) -> str:
        return self.market_context or ""


class ChosenAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate: str
    text: str


class AnalystOutput(BaseModel):
    """ The narrative in the report: the findings and the actions from code, the market context from the AI """
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
    source: Literal["ai", "template", "code"]       # market context by AI; AI text failed or skipped; none needed
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)     # [n] -> query, url, date, for the report's sources list


def analyst_agent():
    return build_agent("Oversight Analyst", INSTRUCTIONS, AnalystDraft, "analyst")


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
                         f"year {side} its index over {n} years, a tracking difference of {td['value']:+.2f} pp a "
                         f"year{te_text}.")
        else:
            parts.append(f"{_rating_phrase('Performance', perf['rating'])}: {_plain(perf['reason'])}.")
    return " ".join(parts)


def candidates_for(facts: dict) -> list[dict]:
    """ The candidate actions code wrote into the facts (built here when the facts have none, e.g. in tests) """
    return facts.get("candidate_actions") or candidate_actions(facts)


def code_actions(facts: dict) -> list[ChosenAction]:
    """ The actions, exactly as code writes them: the required candidates first, then the rest in order """
    return [ChosenAction(candidate=i, text=t) for i, t in default_actions(candidates_for(facts), MIN_ACTIONS, MAX_ACTIONS)]


_PP = re.compile(r"\bpp\b")


def define_first(findings: list[str], term: re.Pattern, definition: str) -> list[str]:
    """ Add "(definition)" after the first use of a term across the findings, e.g. "pp (percentage points)" """
    out, done = [], False
    for f in findings:
        if not done and (m := term.search(f)):
            f, done = f[:m.end()] + f" ({definition})" + f[m.end():], True
        out.append(f)
    return out


def code_findings(facts: dict) -> list[str]:
    """ All the findings, written by code: finding 1 (ratings with reasons), then one per data note (fixed
    wording); if there are fewer than 2 data-note findings, the other ratings. "pp" is defined at first use """
    years = facts.get("fund", {}).get("time_horizon_years", 5)
    pillars = {p["name"]: p for p in facts["scorecard"]["pillars"]}
    notes = [s for n in facts.get("data_notes", []) if (s := _note_sentence(n, years))]
    if len(notes) < 2:
        notes.append(_other_ratings_sentence(pillars))
    return define_first([ratings_finding(facts)] + notes, _PP, "percentage points")


def assemble(facts: dict, market_context: str | None) -> AnalystOutput:
    return AnalystOutput(key_findings=code_findings(facts), actions=code_actions(facts), market_context=market_context)


# --- Code's checks on the AI's text ----------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s)\]]+|\bwww\.[^\s)\]]+")
_MINUS_AFTER = re.compile(r"\b(behind|below)\b(\s+\w+){0,3}?\s*[-−–]\s?\d", re.IGNORECASE)
_CITATION = re.compile(r"\[(\d+)\]")
_SHORT_PERIOD = re.compile(r"\b\d+\s?(y|yr|yrs|m)\b")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"'(\[]|\s*$)")      # not a decimal point or "e.g. the"


def sentences(text: str) -> int:
    return max(1, len(_SENTENCE_END.findall(text.strip())))


def style_problems(out: AnalystDraft, sources: int) -> list[str]:
    """ Wording rules checked by code on the market context: no figures, no minus after "behind"/"below", no web
    addresses, citations only to sources that exist, periods in words, at most 3 sentences """
    text = out.text()
    found = [f"style: minus sign after '{m.group(1)}' in '{m.group(0)}'; write 'behind by 0.10%'"
             for m in _MINUS_AFTER.finditer(text)]
    found += [f"citation: web address in the text ({u}); cite the source as [n] instead" for u in _URL.findall(text)]
    found += [f"citation: [{n}] does not match a source" for n in _CITATION.findall(text) if not 1 <= int(n) <= sources]
    found += [f"style: write periods in words, not '{m.group(0)}'" for m in _SHORT_PERIOD.finditer(text)]
    if text and (n := sentences(text)) > MAX_CONTEXT_SENTENCES:
        found.append(f"style: the market context has {n} sentences; use at most {MAX_CONTEXT_SENTENCES}")
    return found


CHECK_KINDS = (("number", "number"), ("number", "label:"), ("rating", "rating:"), ("rating", "verdict:"),
               ("wording", "style:"), ("wording", "citation:"))


def failed_checks(issues: list[str]) -> list[str]:
    """ Which checks a draft failed, in a fixed order: number, rating, wording """
    kinds = {kind for kind, prefix in CHECK_KINDS for i in issues if i.startswith(prefix)}
    return [k for k in ("number", "rating", "wording") if k in kinds]


def problems(out: AnalystDraft, facts: dict, sources: int = 0) -> list[str]:
    """ Everything wrong with the market context: any figure (direction only), figures not in the facts or under
    the wrong label, a rating or verdict, and the wording rules. Web addresses are taken out first (they are
    reported as citation problems) """
    text = _URL.sub("[source]", out.text())
    figures = [n.text.strip() for n in numbers_in(_CITATION.sub(" ", text))]
    return ([f"number in the market context: {f}; describe direction only, with no figures" for f in figures]
            + check_labels(text, facts) + check_ratings(text, facts["scorecard"]) + style_problems(out, sources))


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
            + "\n\nWritten by code (do not repeat):\nFindings:\n" + "\n".join(f"- {f}" for f in code_findings(facts))
            + "\nActions:\n" + "\n".join(f"- {a.text}" for a in code_actions(facts)))


KEEP_RULES = ("Fix every problem listed. Keep every rule your previous draft already passed: no figures (direction "
              "only); only the numbered sources, cited as [n]; at most 3 short sentences; plain English; no ratings "
              "or verdict. Do not bring back any earlier problem.")


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


def template(facts: dict) -> AnalystOutput:
    """ The narrative with no market context: used offline, with no sources, or when the AI text fails """
    return assemble(facts, None)


# --- The flow --------------------------------------------------------------------------------------------------

QualityFn = Callable[[dict, list[dict], dict], Awaitable[Review]]


def _template(facts: dict, message: str, log: list[str]) -> Narrative:
    return Narrative(template(facts), "template", [DataFlag(check="analyst", level="warning", message=message)], log)


def evaluator_view(facts: dict, draft: AnalystDraft) -> dict:
    """ What the Evaluator sees: the AI's market context to judge, and code's text for context only """
    return {"findings_written_by_code_not_judged": code_findings(facts),
            "market_context_to_judge": draft.market_context,
            "actions_written_by_code_not_judged": [a.text for a in code_actions(facts)]}


async def write_narrative(facts: dict, search_summaries: list[dict] | None = None, max_rewrites: int = 2,
                          run: RunFn | None = None, quality_check: QualityFn | None = None,
                          max_evaluator_rewrites: int = 1) -> Narrative:
    """ Code writes the findings and actions. The AI writes the market context from the sources: code's checks
    (spec 8.3) run first, with max_rewrites rewrites; the Evaluator (8.4) sees only drafts that pass them, with its
    own max_evaluator_rewrites. Every rewrite gets all the issues found so far. When a draft fails and no rewrite
    of that kind is left, the market context is left out and the run is flagged """
    sources = numbered_sources(search_summaries)
    if not sources:
        return Narrative(template(facts), "code", [], ["No market context: no usable web sources, so no AI text"])
    agent = analyst_agent()
    first = prompt(facts, search_summaries)
    request, log, so_far = first, [], []
    check_rewrites = evaluator_rewrites = draft_no = 0

    def rewrite(draft: AnalystDraft, current: list[str]) -> str:
        earlier = [i for i in so_far if i not in current]
        so_far.extend(i for i in current if i not in so_far)
        return rewrite_prompt(first, draft, current, earlier)

    while True:
        result = await run_structured(agent, request, AnalystDraft, run=run)
        if not result.ok:
            log.append(f"Analyst gave no valid output: {'; '.join(result.errors)}")
            return _template(facts, f"{AI_TEXT_UNAVAILABLE}: {LEFT_OUT}", log)
        draft_no += 1
        draft = result.output
        if not draft.market_context:
            log.append(f"Analyst draft {draft_no}: no market context from the sources")
            return Narrative(template(facts), "ai", [], log, [])
        issues = problems(draft, facts, len(sources))
        if issues:
            log.append(f"Analyst draft {draft_no} rejected by code's checks ({' / '.join(failed_checks(issues))}): "
                       + "; ".join(issues))
            if check_rewrites < max_rewrites:
                check_rewrites += 1
                request = rewrite(draft, issues)
                continue
            return _template(facts, f"{CHECKS_FAILED}: {' / '.join(failed_checks(issues))}; {LEFT_OUT}", log)
        log.append(f"Analyst draft {draft_no} passed the figure, rating and wording checks")
        if quality_check is not None:
            verdict = await quality_check(facts, sources, evaluator_view(facts, draft))
            if verdict.error:
                log.append(f"Evaluator gave no valid result: {verdict.error}")
                why = "could not be reached" if verdict.unreachable else "gave no valid answer after one retry"
                return _template(facts, f"{QUALITY_NOT_DONE}: the Evaluator {why}; {LEFT_OUT}", log)
            if not verdict.passed:
                log.append(f"Evaluator rejected draft {draft_no}: " + "; ".join(verdict.problems()))
                if evaluator_rewrites < max_evaluator_rewrites:
                    evaluator_rewrites += 1
                    request = rewrite(draft, verdict.problems())
                    continue
                return _template(facts, f"{QUALITY_FAILED}: the Evaluator rejected the draft "
                                        f"({', '.join(verdict.failed_checks)}); {LEFT_OUT}", log)
            log.append(f"Evaluator passed draft {draft_no}")
        return Narrative(assemble(facts, draft.market_context), "ai", [], log, sources)
