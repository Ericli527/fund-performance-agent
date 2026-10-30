""" The facts JSON (spec 8.3): everything code has decided, in one place, for the Oversight Analyst to
explain and for the number guard to check against. The Analyst may quote only numbers that appear here.
"""
from fund_performance.actions import candidate_actions
from fund_performance.conclusion import HEADING, judgement_points, manager_questions, suggested_conclusion
from fund_performance.models import DataFlag, Figure, FundProfile
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import Scorecard

SERIES = {"fund_nav": "Fund NAV", "fund_pnav": "Fund PNAV (market-close)", "index": "Index",
          "comparison": "Fund vs index", "relative": "Fund vs index (calculated)", "risk": "Factsheet risk"}
KINDS = {"cum": "cumulative return", "ann": "annualised return", "discrete_12m": "12-month return",
         "calendar": "calendar-year return", "since_launch": "since launch", "vol": "volatility",
         "mdd": "maximum drawdown", "sharpe": "Sharpe ratio", "excess_cum": "cumulative excess return",
         "td": "tracking difference", "td_ex_cost": "tracking difference after adding back the fee",
         "hit_rate": "hit rate", "tracking_error": "tracking error", "beta": "beta", "r2": "R²",
         "info_ratio": "information ratio", "alpha": "alpha", "relative_vol": "relative volatility",
         "fund_vol": "fund volatility", "index_vol": "index volatility", "sharpe_fund": "fund Sharpe ratio",
         "sharpe_index": "index Sharpe ratio"}
# Shown to 2 d.p., as on the factsheet (owner decision)
TWO_DP = {"td", "td_ex_cost", "tracking_error", "alpha", "beta", "r2", "info_ratio"}


def label(name: str) -> str:
    """ A plain-English name for a figure, e.g. 'fund_pnav.ann.5y' -> 'Fund PNAV (market-close) annualised return, 5y' """
    parts = name.split(".")
    series = SERIES.get(parts[0], parts[0])
    if parts[0] == "risk":                       # risk.<basis>.<measure>.3y
        return f"{series} ({parts[1].upper()} basis): {KINDS.get(parts[2], parts[2])}, {parts[3]}"
    kind = KINDS.get(parts[1], parts[1]) if len(parts) > 1 else ""
    rest = ", ".join(parts[2:])
    return f"{series} {kind}" + (f", {rest}" if rest else "")


def _figure(name: str, f: Figure) -> dict:
    two_dp = any(part in TWO_DP for part in name.split("."))
    return {"name": name, "label": label(name),
            "value": round(f.exact if f.exact is not None else f.value, 2), "unit": f.unit,
            "display": f.display(percent_decimals=2 if two_dp else 1), "source": f.source, "period": f.period, "basis": f.basis,
            **({"note": "please verify"} if f.source == "ai_extracted" else {})}


def _note_figure(label_text: str, value: float, unit: str, decimals: int = 1, key: bool = False) -> dict:
    """ Returns and cumulative gaps to 1 d.p.; yearly tracking differences and the fee to 2 d.p. """
    value = round(value, 2) + 0.0
    shown = f"{value:+.{decimals}f} pp" if unit == "pp" else f"{value:.{decimals}f}%"
    return {"label": label_text, "value": value, "unit": unit, "display": shown, **({"key": True} if key else {})}


def data_notes(profile: FundProfile, reported: ReportedFigures, flags: list[DataFlag]) -> list[dict]:
    """ Short notes, with their figures, for findings that change how the results should be read. Written by
    code from the flags and figures, so every number in them is one the number guard accepts. "explains" says
    which figure each note explains (and which it does not), e.g. the fee explains the yearly tracking
    difference, not the noon-price gap """
    notes = []
    n = profile.time_horizon_years
    value = reported.value
    pricing = next((f for f in flags if f.check == "pricing_point"), None)

    # The fund is priced at noon and the index at market close: the noon comparison looks worse than it is
    nav, pnav, index = value(f"fund_nav.cum.{n}y"), value(f"fund_pnav.cum.{n}y"), value(f"index.cum.{n}y")
    if pricing is not None and pricing.level == "info" and None not in (nav, pnav, index):
        noon = _note_figure("x", nav - index, "pp")["display"]
        fair = _note_figure("x", pnav - index, "pp")["display"]
        notes.append({
            "kind": "pricing",
            "explains": (f"the {n}-year cumulative gap at noon prices ({noon}), against {fair} at market close. "
                         "Timing, not cost: it does not explain the yearly tracking difference"),
            "note": (f"The fund is priced at noon and the index at market close. Compared at noon prices, the fund "
                     f"looks further behind its index over {n} years than it really is. The fair comparison uses "
                     f"the fund's market-close price (PNAV)."),
            "figures": [_note_figure(f"Fund noon price (NAV), cumulative return, {n}y", nav, "%"),
                        _note_figure(f"Index, cumulative return, {n}y", index, "%"),
                        _note_figure(f"Gap at noon prices (NAV vs index), {n}y", nav - index, "pp", key=True),
                        _note_figure(f"Fund market-close price (PNAV), cumulative return, {n}y", pnav, "%"),
                        _note_figure(f"Fair gap (PNAV vs index), {n}y", pnav - index, "pp")]})
    elif pricing is not None and pricing.level == "warning":
        notes.append({"kind": "timing",
                      "explains": "part of the gap to the index, which may be timing, not cost",
                      "note": "The fund and the index are priced at different times and no market-close price (PNAV) "
                              "is available, so part of the gap to the index may be timing, not performance.",
                      "figures": []})

    # Index funds: how much of the yearly gap the fee explains
    td, td_ex = value(f"comparison.td.{n}y"), value(f"comparison.td_ex_cost.{n}y")
    if profile.objective_type == "index_tracker" and td is not None and td_ex is not None:
        share = "Most of the yearly gap to the index is the fee." if abs(td_ex) <= abs(td) / 2 \
            else "The fee explains only part of the yearly gap to the index."
        notes.append({
            "kind": "fee",
            "explains": (f"the yearly tracking difference ({_note_figure('x', td, 'pp', 2)['display']} a year over "
                         f"{n} years). It does not explain the noon-price gap"),
            "note": f"{share} Adding the ongoing charge back leaves the cost-adjusted gap.",
            "figures": [_note_figure(f"Tracking difference, a year, {n}y", td, "pp", 2),
                        _note_figure(f"Fund behind its index, in plain terms (% a year), {n}y", td, "%", 2),
                        _note_figure("Ongoing charge (OCF), a year", profile.ocf_pct, "%", 2, key=True),
                        _note_figure(f"Cost-adjusted tracking difference, a year, {n}y", td_ex, "pp", 2),
                        _note_figure(f"Cost-adjusted gap, in plain terms (% a year), {n}y", td_ex, "%", 2)]})
    return notes


def peer_rows(comparison) -> list[dict]:
    """ Each peer as compared (B2): what was used and on which basis """
    if comparison is None:
        return []
    return [{"name": r.peer.name, "isin": r.peer.isin, "share_class": r.peer.share_class, "currency": r.peer.currency,
             "ocf_pct": r.peer.ocf_pct, "investor_type": r.peer.investor_type,
             "minimum_investment": r.peer.minimum_investment, "distribution": r.peer.distribution,
             "pricing_point": r.peer.pricing_point, "origin": r.peer.origin, "basis": r.basis,
             "used_for_returns": r.used_for_returns, "excluded": r.excluded or "", "notes": r.notes,
             "returns_pct_a_year": {f"{n}y": None if v is None else round(v, 2) for n, v in r.returns.items()}}
            for r in comparison.rows]


def build_facts(profile: FundProfile, reported: ReportedFigures, card: Scorecard, flags: list[DataFlag],
                promises: list[str] | None = None, peer_comparison=None, evidence=None) -> dict:
    """ The facts JSON. Numbers keep their units so the number guard can tell 0.10 pp from 0.10%. The suggested
    conclusion, points for judgement and questions for the manager are written by code from the rest """
    facts = {
        "fund": {"fund_name": profile.fund_name, "isin": profile.isin, "share_class": profile.share_class,
                 "currency": profile.currency, "benchmark_name": profile.benchmark_name,
                 "objective_text": profile.objective_text, "objective_type": profile.objective_type,
                 "time_horizon_years": profile.time_horizon_years, "ocf_pct": profile.ocf_pct,
                 "performance_fee": profile.performance_fee, "transaction_cost_pct": profile.transaction_cost_pct,
                 "as_of_date": profile.as_of_date.isoformat(),
                 "promises": promises or []},
        "scorecard": {
            "verdict": card.verdict, "verdict_reason": card.verdict_reason,
            "pillars": [{"name": p.name, "rating": p.rating, "reason": p.reason, "summary": p.summary,
                         "sub_ratings": [{"name": s.name, "rating": s.rating, "reason": s.reason} for s in p.sub_ratings],
                         "notes": p.notes, "values": p.values} for p in card.pillars.values()]},
        "decision_path": card.path.steps,
        "data_notes": data_notes(profile, reported, flags),
        "data_flags": [{"check": f.check, "level": f.level, "message": f.message} for f in flags
                       if f.level in ("warning", "blocking")],
        "figures": [_figure(name, f) for name, f in reported.figures.items()],
    }
    facts["peers"] = peer_rows(peer_comparison)
    facts["evidence"] = evidence.to_dict() if evidence is not None else None
    facts["candidate_actions"] = candidate_actions(facts)     # the only actions the Analyst may choose (code)
    conclusion, left_out = suggested_conclusion(facts)
    facts["suggested_conclusion"] = {"heading": HEADING, "text": conclusion, "code_text": conclusion, "source": "code",
                                     "left_out": left_out}
    facts["judgement_points"] = judgement_points(facts)
    facts["manager_questions"] = manager_questions(facts)
    return facts
