""" Shared presentation helpers (UX redesign, stage 3): the web dashboard and both PDF reports take their headline
figures, statuses and wording from here, so they always show the same thing. Presentation only: nothing here
calculates a figure or sets a rating; a figure the facts do not hold is "Not available", never zero.
"""
from dataclasses import dataclass, field
from datetime import date

NAVY = "#1f3a5f"
RATING_STYLE = {"GREEN": ("Green", "#2e7d32"), "AMBER": ("Amber", "#b7791f"), "RED": ("Red", "#c62828"),
                "CHECK DATA": ("Check data", "#6d4c9f"), "MANUAL CHECK": ("Manual check", "#546e7a")}
VERDICT_STYLE = {"Retain": "#2e7d32", "Monitor": "#b7791f", "Review": "#c62828", "Pending": "#6d4c9f"}
QUESTIONS = {"Mandate": "Is the fund doing what it promised?", "Performance": "How did it do against its index?",
             "Value for investors": "Did investors get a fair outcome?", "Fees": "Is the fee justified?"}
SOURCE_WORDS = {"factsheet": "Factsheet", "calculated": "Calculated", "ai_extracted": "AI-read from the factsheet "
                "(verify)", "user": "Entered by user", "web": "Web"}
NOT_AVAILABLE = "Not available"


# --- Evidence quality (separate from the investment assessment) ------------------------------------------------

@dataclass
class EvidenceQuality:
    level: str                        # "check", "warnings" or "clear"
    label: str
    detail: str
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_read: bool = False


def evidence_quality(data: dict) -> EvidenceQuality:
    """ From code's data checks and the run's flags only. "clear" means no check raised an issue; it is not a
    verification of the source documents """
    facts = data["facts"]
    flags = data.get("flags", [])
    blocking = list(dict.fromkeys(f["message"] for f in flags if f["level"] == "blocking"))
    warnings = list(dict.fromkeys(f["message"] for f in flags if f["level"] == "warning"))
    checks = [p["name"] for p in facts.get("scorecard", {}).get("pillars", []) if p["rating"] == "CHECK DATA"]
    ai_read = any(f.get("source") == "ai_extracted" for f in facts.get("figures", []))
    if blocking or checks:
        n = len(blocking) or len(checks)
        return EvidenceQuality("check", "Data check needed",
                               f"{n} issue{'s' if n != 1 else ''} must be resolved before the ratings can be relied "
                               "on" + (f" ({', '.join(checks)})" if checks else ""), blocking, warnings, ai_read)
    if warnings:
        return EvidenceQuality("warnings", "Warnings to review",
                               f"{len(warnings)} data warning{'s' if len(warnings) != 1 else ''} to check before signing",
                               blocking, warnings, ai_read)
    detail = "Code's data checks raised no warnings"
    if ai_read:
        detail += "; figures were read from the documents by AI, so check them against the factsheet"
    return EvidenceQuality("clear", "No data issues raised", detail, blocking, warnings, ai_read)


# --- Figures ---------------------------------------------------------------------------------------------------------

def _figures(facts: dict) -> dict[str, dict]:
    return {f["name"]: f for f in facts.get("figures", [])}


def _shown(fig: dict | None) -> str:
    return NOT_AVAILABLE if fig is None else str(fig["display"]).replace("-", "−")


def _source(*figs: dict | None) -> str:
    words = sorted({SOURCE_WORDS.get(f.get("source"), f.get("source", "")) for f in figs if f})
    return ", ".join(words) or "–"


@dataclass
class Metric:
    label: str
    value: str
    period: str
    source: str
    note: str = ""


def headline_metrics(facts: dict) -> list[Metric]:
    """ Three headline figures from the facts, with their period, unit and source; missing ones say so """
    fund = facts.get("fund", {})
    figs = _figures(facts)
    n = fund.get("time_horizon_years", 5)
    as_of = _date(fund.get("as_of_date"))
    td = figs.get(f"comparison.td.{n}y")
    series = (td or {}).get("basis") or "fund_nav"
    price = "market-close price (PNAV)" if series == "fund_pnav" else "fund price (NAV)"
    fund_ret, index_ret = figs.get(f"{series}.ann.{n}y"), figs.get(f"index.ann.{n}y")
    period = f"{n} years to {as_of}"
    index_fund = fund.get("objective_type") == "index_tracker"
    other = "index" if index_fund else "benchmark"
    metrics = [
        Metric("Fund return", _shown(fund_ret) + (" a year" if fund_ret else ""), f"{period}, {price}",
               _source(fund_ret)),
        Metric(f"Gap to {other}" + (" (tracking difference)" if index_fund else ""),
               _shown(td) + (" a year" if td else ""), period, _source(td) + (" from the factsheet" if td and
                                                                               td.get("source") == "calculated" else ""),
               f"{other.capitalize()} {_shown(index_ret)} a year" if index_ret else ""),
    ]
    ocf = fund.get("ocf_pct")
    metrics.append(Metric("Ongoing charge (OCF)", NOT_AVAILABLE if ocf is None else f"{ocf:.2f}% a year",
                          f"as at {as_of}", "Fund documents"))
    return metrics


def _date(text: str | None) -> str:
    try:
        return f"{date.fromisoformat(text):%d %b %Y}"
    except (TypeError, ValueError):
        return text or "–"


# --- Shared wording -------------------------------------------------------------------------------------------------

def flag_dicts(flags) -> list[dict]:
    """ DataFlag objects or dicts, as plain dicts, once each """
    out = {}
    for f in flags or []:
        d = f if isinstance(f, dict) else {"check": f.check, "level": f.level, "message": f.message}
        out.setdefault((d["level"], d["message"]), {"check": d.get("check", ""), "level": d["level"],
                                                    "message": d["message"]})
    return list(out.values())


ANGLE_WORDS = {"board": "board", "analyst": "oversight analyst", "manager_meeting": "meeting with the manager"}


def conclusion_origin(concl: dict) -> str:
    """ Who wrote the suggested conclusion """
    if concl.get("source") == "ai":
        return (f"AI draft for the {ANGLE_WORDS.get(concl.get('angle'), concl.get('angle'))}, chosen by the Judge and "
                "checked by code")
    return "Written by code from the scorecard"


def assessment_caveat(quality: EvidenceQuality) -> str:
    """ What the suggested verdict needs before it can be relied on """
    return {"check": "Not final: resolve the data check first.",
            "warnings": "Not final: review the data warnings first."}.get(quality.level, "")


def issue_groups(facts: dict, reasons: dict) -> tuple[list[str], list[str]]:
    """ (insufficient evidence, performance concerns): a question that could not be judged (data check, no peer) is
    not the same as one the fund did badly on """
    gaps, concerns = [], []
    for p in facts.get("scorecard", {}).get("pillars", []):
        why = reasons.get(p["name"]) or p["reason"]
        if p["rating"] == "CHECK DATA":
            gaps.append(f"{p['name']}: not rated until the data check is resolved (see the data issues)")
        elif p.get("summary") == "Add peer":
            gaps.append(f"{p['name']}: {why}")
        elif p["rating"] in ("RED", "AMBER"):
            concerns.append(f"{p['name']} ({RATING_STYLE[p['rating']][0]}): {why}")
    return gaps, concerns


def point_to_data_issues(text: str, blocking: list[str]) -> str:
    """ An action that repeats a blocking data check in full points to it instead (it is shown in full once) """
    for message in blocking:
        text = text.replace(f": {message}", " (see the data issues)")
    return text


def chart_choice(facts: dict) -> str | None:
    """ The one chart that suits the fund's mandate and the data there is:
    "yearly_gap" (index fund, calendar-year gaps), "yearly_excess" (other funds, calendar-year gaps against the
    benchmark), "rolling_12m" (12-month returns, fund vs index or benchmark), or None """
    ev = facts.get("evidence") or {}
    if ev.get("gaps") and len(ev["gaps"]) >= 3:
        return "yearly_gap" if facts.get("fund", {}).get("objective_type") == "index_tracker" else "yearly_excess"
    names = {f["name"] for f in facts.get("figures", [])}
    windows = {n.rsplit(".", 1)[1] for n in names if ".discrete_12m." in n and not n.startswith("index")}
    if windows and any(n.startswith("index.discrete_12m.") for n in names):
        return "rolling_12m"
    return None


def risk_measures(facts: dict) -> list[tuple[str, str, str]]:
    """ (label, value, source) for the risk and tracking figures the facts hold, in a fixed order """
    figs = _figures(facts)
    n = facts.get("fund", {}).get("time_horizon_years", 5)
    wanted = [(f"Tracking error, {n} years", f"relative.tracking_error.{n}y"), ("Tracking error, 3 years",
              "risk.pnav.tracking_error.3y"), (f"R², {n} years", f"relative.r2.{n}y"), ("R², 3 years", "risk.pnav.r2.3y"),
              (f"Beta, {n} years", f"relative.beta.{n}y"), ("Beta, 3 years", "risk.pnav.beta.3y"),
              (f"Volatility, {n} years (fund)", f"fund_nav.vol.{n}y"), ("Volatility, 3 years (fund)", "risk.pnav.fund_vol.3y"),
              (f"Largest fall, {n} years (fund)", f"fund_nav.mdd.{n}y"), ("12-month windows within the fee + margin",
                                                                          "comparison.hit_rate")]
    return [(label, _shown(figs[name]), _source(figs[name])) for label, name in wanted if name in figs]
