""" Read-only tools for the Reporting Agent (Agentic Tools V2.1)

The Reporting Agent asks for the verified evidence it needs instead of getting one large facts payload. Each tool
reads only the current review's facts, which code built before any AI wrote a word (ReviewContext, passed to the run
as the OpenAI Agents SDK run context: no global state, no files). The tools calculate nothing: they return the
figures exactly as code stored them (value, display text, unit, source) and say plainly what is not available and why.
A run may call the tools at most MAX_TOOL_CALLS times in all; after that each call returns a short refusal.
"""
import copy
from dataclasses import dataclass, field
from typing import Literal
from agents import RunContextWrapper, function_tool
from fund_performance.agents.reporter import verdict_sentence
from fund_performance.presentation import comparison_invalid, missing_evidence

MAX_TOOL_CALLS = 6
Period = Literal["1y", "3y", "5y", "since_launch"]
NOT_IN_FACTS = "not in the verified facts for this review"
NOT_RELIABLE = "not reliable: a currency or benchmark data check makes the fund-vs-index comparison invalid"
LIMIT_REACHED = "tool call limit reached: write the summary from the evidence you already have"


@dataclass
class ReviewContext:
    """ The run context: this review's verified facts (a private copy, read only) and the tool calls made so far """
    facts: dict
    max_calls: int = MAX_TOOL_CALLS
    calls: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, facts: dict, max_calls: int = MAX_TOOL_CALLS) -> "ReviewContext":
        return cls(copy.deepcopy(facts), max_calls)

    def allow(self, call: str) -> bool:
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(call)
        return True


def _figure(figures: dict, *names: str) -> dict | None:
    """ The first of these figures that code stored, as stored (never recalculated) """
    for name in names:
        if (f := figures.get(name)) is not None:
            return {"label": f.get("label"), "value": f.get("value"), "display": f.get("display"),
                    "unit": f.get("unit"), "source": f.get("source"), "period": f.get("period")}
    return None


def _tracking_error(figures: dict, period: str) -> dict | None:
    """ Tracking error for the period, calculated from an index series; else the factsheet's own (its period kept) """
    found = _figure(figures, f"relative.tracking_error.{period}")
    if found:
        return found
    factsheet = sorted(n for n in figures if n.startswith("risk.") and ".tracking_error." in n)
    return _figure(figures, *factsheet)


def fund_performance(facts: dict, period: str) -> dict:
    """ Fund and benchmark returns and tracking for one period, from the facts only """
    figures = {f["name"]: f for f in facts.get("figures", [])}
    key = "since_launch" if period == "since_launch" else period
    if key == "since_launch":
        fund_cum, fund_ann = _figure(figures, "fund_nav.since_launch.cum"), _figure(figures, "fund_nav.since_launch.ann")
        index_cum, index_ann = _figure(figures, "index.since_launch.cum"), _figure(figures, "index.since_launch.ann")
        td = te = None
    else:
        fund_cum, fund_ann = _figure(figures, f"fund_nav.cum.{key}"), _figure(figures, f"fund_nav.ann.{key}")
        index_cum, index_ann = _figure(figures, f"index.cum.{key}"), _figure(figures, f"index.ann.{key}")
        td = _figure(figures, f"comparison.td.{key}", f"relative.td.{key}")
        te = _tracking_error(figures, key)
    out = {"period": period, "as_of_date": (facts.get("fund") or {}).get("as_of_date"),
           "fund_return_cumulative": fund_cum, "fund_return_a_year": fund_ann,
           "benchmark_return_cumulative": index_cum, "benchmark_return_a_year": index_ann,
           "tracking_difference": td, "tracking_error": te}
    unavailable = {}
    if comparison_invalid(facts):
        for name in ("benchmark_return_cumulative", "benchmark_return_a_year", "tracking_difference", "tracking_error"):
            if out[name] is not None:
                out[name] = None
                unavailable[name] = NOT_RELIABLE
    if key == "since_launch":
        unavailable |= {"tracking_difference": "given for 1, 3 and 5 years only",
                        "tracking_error": "given for 1, 3 and 5 years only"}
    for name, value in list(out.items()):
        if value is None and name not in unavailable:
            unavailable[name] = NOT_IN_FACTS
    out["unavailable"] = unavailable
    return out


def oversight_scorecard(facts: dict) -> dict:
    """ Code's ratings, verdict and reasons, the data notes, points for judgement and material data warnings """
    card = facts.get("scorecard") or {}
    return {
        "verdict_code": card.get("verdict"), "verdict_sentence": verdict_sentence(facts),
        "verdict_reason": card.get("verdict_reason"),
        "ratings": [{"question": p["name"], "rating": p["rating"], "reason": p.get("reason"),
                     "sub_ratings": [{"name": s["name"], "rating": s["rating"], "reason": s.get("reason")}
                                     for s in p.get("sub_ratings") or []]} for p in card.get("pillars", [])],
        "findings": [{"note": n.get("note"), "explains": n.get("explains"),
                      "figures": [{"label": f["label"], "display": f.get("display")} for f in n.get("figures", [])]}
                     for n in facts.get("data_notes", [])],
        "points_for_judgement": list(facts.get("judgement_points") or []),
        "material_data_warnings": [f["message"] for f in facts.get("data_flags", [])
                                   if f.get("level") in ("warning", "blocking")],
        "missing_evidence": missing_evidence(facts) or {},
    }


def peer_comparison(facts: dict) -> dict:
    """ The peers code compared, their fees and returns, the comparability checks and what is missing """
    pillars = {p["name"]: p for p in (facts.get("scorecard") or {}).get("pillars", [])}
    peers = [{"name": p.get("name"), "isin": p.get("isin"), "share_class": p.get("share_class"),
              "currency": p.get("currency"), "ongoing_charge_pct": p.get("ocf_pct"),
              "returns_pct_a_year": p.get("returns_pct_a_year"), "used_for_returns": p.get("used_for_returns"),
              "returns_left_out_because": p.get("excluded") or None, "basis": p.get("basis"),
              "comparability_notes": list(p.get("notes") or [])} for p in facts.get("peers", [])]
    out = {"peers": peers,
           "value_for_investors": {k: pillars.get("Value for investors", {}).get(k) for k in ("rating", "reason")},
           "fees": {k: pillars.get("Fees", {}).get(k) for k in ("rating", "reason")},
           "fund_ongoing_charge_pct": (facts.get("fund") or {}).get("ocf_pct")}
    if not peers:
        out["missing"] = "no peer fund in this review, so value for investors and fees are not compared with a peer"
    elif not any(p["used_for_returns"] for p in peers):
        out["missing"] = "no peer with returns comparable with the fund's (see returns_left_out_because)"
    return out


def _refused() -> dict:
    return {"error": LIMIT_REACHED}


@function_tool
def get_fund_performance(ctx: RunContextWrapper[ReviewContext], period: Period) -> dict:
    """ Verified fund and benchmark returns, tracking difference and tracking error for one period.

    Args:
        period: "1y", "3y", "5y" or "since_launch".
    """
    if not ctx.context.allow(f"get_fund_performance({period})"):
        return _refused()
    return fund_performance(ctx.context.facts, period)


@function_tool
def get_oversight_scorecard(ctx: RunContextWrapper[ReviewContext]) -> dict:
    """ Code's four ratings with their reasons, the verdict and its sentence, the findings, points for judgement,
    material data warnings and missing evidence. """
    if not ctx.context.allow("get_oversight_scorecard"):
        return _refused()
    return oversight_scorecard(ctx.context.facts)


@function_tool
def get_peer_comparison(ctx: RunContextWrapper[ReviewContext]) -> dict:
    """ The peer funds code compared: fees, returns, comparability checks, the Value and Fees ratings and what is
    missing. """
    if not ctx.context.allow("get_peer_comparison"):
        return _refused()
    return peer_comparison(ctx.context.facts)


TOOLS = [get_fund_performance, get_oversight_scorecard, get_peer_comparison]
