""" The facts JSON (spec 8.3): everything code has decided, in one place, for the Oversight Analyst to
explain and for the number guard to check against. The Analyst may quote only numbers that appear here.
"""
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


def build_facts(profile: FundProfile, reported: ReportedFigures, card: Scorecard, flags: list[DataFlag],
                promises: list[str] | None = None) -> dict:
    """ The facts JSON. Numbers keep their units so the number guard can tell 0.10 pp from 0.10% """
    return {
        "fund": {"fund_name": profile.fund_name, "isin": profile.isin, "share_class": profile.share_class,
                 "currency": profile.currency, "benchmark_name": profile.benchmark_name,
                 "objective_text": profile.objective_text, "objective_type": profile.objective_type,
                 "time_horizon_years": profile.time_horizon_years, "ocf_pct": profile.ocf_pct,
                 "performance_fee": profile.performance_fee, "as_of_date": profile.as_of_date.isoformat(),
                 "promises": promises or []},
        "scorecard": {
            "verdict": card.verdict, "verdict_reason": card.verdict_reason,
            "pillars": [{"name": p.name, "rating": p.rating, "reason": p.reason, "summary": p.summary,
                         "sub_ratings": [{"name": s.name, "rating": s.rating, "reason": s.reason} for s in p.sub_ratings],
                         "notes": p.notes} for p in card.pillars.values()]},
        "decision_path": card.path.steps,
        "data_flags": [{"check": f.check, "level": f.level, "message": f.message} for f in flags
                       if f.level in ("warning", "blocking")],
        "figures": [_figure(name, f) for name, f in reported.figures.items()],
    }
