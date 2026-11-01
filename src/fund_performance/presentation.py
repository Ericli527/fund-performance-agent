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


# A rating can wait ("CHECK DATA") for two different reasons: a data check found a problem (a blocking flag), or the
# documents do not give a figure the rating needs. The second is missing evidence, not bad data, and is said so.
MISSING_WORDS = (
    ("R²", "R² and beta are not in the documents provided, and there is no index price series to calculate them"),
    ("tracking error not available", "tracking error is not in the documents provided, and there is no index price "
                                     "series to calculate it"),
    ("return not available", "a return needed for the comparison is not in the documents provided"),
    ("performance fee not available", "the documents provided do not say whether the fund charges a performance "
                                      "fee, so the fee cannot be rated Green"))


def missing_evidence(facts: dict) -> dict[str, str]:
    """ {rating name: what is missing, in plain words} for ratings waiting for evidence the documents do not give """
    blocking = [f["message"] for f in facts.get("data_flags", []) if f["level"] == "blocking"]
    out = {}
    for p in facts.get("scorecard", {}).get("pillars", []):
        reason = p.get("reason") or ""
        if p["rating"] != "CHECK DATA" or "not available" not in reason or any(m in reason for m in blocking):
            continue
        out[p["name"]] = "; ".join(w for key, w in MISSING_WORDS if key in reason) or \
            reason.replace("CHECK DATA: ", "")
    return out


def evidence_quality(data: dict) -> EvidenceQuality:
    """ From code's data checks and the run's flags only. "clear" means no check raised an issue; it is not a
    verification of the source documents """
    facts = data["facts"]
    flags = data.get("flags", [])
    blocking = list(dict.fromkeys(f["message"] for f in flags if f["level"] == "blocking"))
    warnings = list(dict.fromkeys(f["message"] for f in flags if f["level"] == "warning"))
    checks = [p["name"] for p in facts.get("scorecard", {}).get("pillars", []) if p["rating"] == "CHECK DATA"]
    ai_read = any(f.get("source") == "ai_extracted" for f in facts.get("figures", []))
    missing = missing_evidence(facts)
    if missing and not blocking and set(missing) == set(checks):
        return EvidenceQuality("check", "Evidence missing",
                               f"{_and(list(missing))} cannot be rated: figures they need are not in the documents "
                               "provided", blocking, warnings, ai_read)
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


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


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
    n = (fund.get("time_horizon_years") or fund.get("analysis_period_years", 5))
    as_of = _date(fund.get("as_of_date"))
    td = figs.get(f"comparison.td.{n}y")
    series = (td or {}).get("basis") or "fund_nav"
    price = "market-close price (PNAV)" if series == "fund_pnav" else "fund price (NAV)"
    fund_ret, index_ret = figs.get(f"{series}.ann.{n}y"), figs.get(f"index.ann.{n}y")
    period = f"{n} years to {as_of}"
    index_fund = fund.get("objective_type") == "index_tracker"
    other = "index" if index_fund else "benchmark"
    gap_label = f"Gap to {other}" + (" (tracking difference)" if index_fund else "")
    if comparison_invalid(facts):
        gap = Metric(gap_label, UNRELIABLE, period, UNRELIABLE_SOURCE, UNRELIABLE_WHY)
    else:
        gap = Metric(gap_label, _shown(td) + (" a year" if td else ""), period,
                     _source(td) + (" from the factsheet" if td and td.get("source") == "calculated" else ""),
                     f"{other.capitalize()} {_shown(index_ret)} a year" if index_ret else "")
    metrics = [
        Metric("Fund return", _shown(fund_ret) + (" a year" if fund_ret else ""), f"{period}, {price}",
               _source(fund_ret)),
        gap,
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


def summary_parts(concl: dict) -> tuple[str, list[str]] | None:
    """ (answer, supporting evidence) for an AI summary written as an answer to the reviewer's question; None for
    code's own conclusion (one paragraph) or an executive fallback """
    if concl.get("source") != "ai" or concl.get("executive_fallback") or not concl.get("answer"):
        return None
    return concl["answer"], list(concl.get("evidence") or [])


GENERIC_ACTIONS = {"record_decision", "read_sources"}


def signoff_checks(facts: dict) -> str | None:
    """ A shared sign-off action when both extracted figures and repeated-price warnings need checking. """
    ai_read = any(f.get("source") == "ai_extracted" for f in facts.get("figures", []))
    price_warning = any(f.get("check") == "repeated_prices" and f.get("level") == "warning"
                        for f in facts.get("data_flags", []))
    if ai_read and price_warning:
        return "Verify the AI-extracted figures against the documents and check the flagged historical prices before sign-off."


def next_step(facts: dict) -> str | None:
    """ The recommended next step: mandatory sign-off checks, then the AI's or code's action. """
    concl = facts.get("suggested_conclusion") or {}
    if checks := signoff_checks(facts):
        return checks
    if concl.get("source") == "ai" and concl.get("next_step"):
        return concl["next_step"]
    actions = facts.get("candidate_actions") or []
    chosen = (next((a for a in actions if a.get("required")), None)
              or next((a for a in actions if a.get("id") not in GENERIC_ACTIONS), None)
              or (actions[0] if actions else None))
    return chosen.get("action") if chosen else None


def executive_commentary(concl: dict) -> list[str]:
    """ The Executive commentary paragraphs (AI, checked by code), or [] """
    return list(concl.get("executive") or []) if concl.get("source") == "ai" else []


def conclusion_origin(concl: dict) -> str:
    """ Who wrote the suggested conclusion """
    if concl.get("executive_fallback"):
        return ("Written by code from the scorecard: the AI draft did not fit on this page and is kept in full in "
                "the Detailed Report")
    if concl.get("source") == "ai" and concl.get("revised"):
        return (f"AI draft for the {ANGLE_WORDS.get(concl.get('angle'), concl.get('angle'))}, revised once after the "
                "Judge's review and checked by code; the revision was not reviewed again by the Judge")
    if concl.get("source") == "ai":
        return (f"AI draft for the {ANGLE_WORDS.get(concl.get('angle'), concl.get('angle'))}, chosen by the Judge and "
                "checked by code")
    return "Written by code from the scorecard"


def assessment_caveat(quality: EvidenceQuality) -> str:
    """ What the suggested verdict needs before it can be relied on """
    if quality.label == "Evidence missing":
        return "Not final: the missing evidence is needed first."
    return {"check": "Not final: resolve the data check first.",
            "warnings": "Not final: review the data warnings first."}.get(quality.level, "")


MISSING_MEANING = "Obtain the missing evidence before deciding"


def assessment_meaning(code: str, quality: EvidenceQuality, meaning: str) -> str:
    """ What the suggested verdict means; a wait for missing evidence is not called a data check """
    return MISSING_MEANING if code.startswith("Pending") and quality.label == "Evidence missing" else meaning


def issue_groups(facts: dict, reasons: dict) -> tuple[list[str], list[str]]:
    """ (insufficient evidence, performance concerns): a question that could not be judged (data check, no peer) is
    not the same as one the fund did badly on """
    gaps, concerns = [], []
    for p in facts.get("scorecard", {}).get("pillars", []):
        why = reasons.get(p["name"]) or p["reason"]
        if p["rating"] == "CHECK DATA" and p["name"] in missing_evidence(facts):
            gaps.append(f"{p['name']}: not rated, because {missing_evidence(facts)[p['name']]}")
        elif p["rating"] == "CHECK DATA":
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
    n = (facts.get("fund", {}).get("time_horizon_years") or facts.get("fund", {}).get("analysis_period_years", 5))
    wanted = [(f"Tracking error, {n} years", f"relative.tracking_error.{n}y"), ("Tracking error, 3 years",
              "risk.pnav.tracking_error.3y"), (f"R², {n} years", f"relative.r2.{n}y"), ("R², 3 years", "risk.pnav.r2.3y"),
              (f"Beta, {n} years", f"relative.beta.{n}y"), ("Beta, 3 years", "risk.pnav.beta.3y"),
              (f"Volatility, {n} years (fund)", f"fund_nav.vol.{n}y"), ("Volatility, 3 years (fund)", "risk.pnav.fund_vol.3y"),
              (f"Largest fall, {n} years (fund)", f"fund_nav.mdd.{n}y"), ("12-month windows within the fee + margin",
                                                                          "comparison.hit_rate")]
    if comparison_invalid(facts):         # summaries replace fund-vs-index figures by one row; Detailed keeps them
        rows = [(label, _shown(figs[name]), _source(figs[name])) for label, name in wanted
                if name in figs and not is_comparative(name)]
        replaced = list(dict.fromkeys(label.split(",")[0] for label, name in wanted
                                      if name in figs and is_comparative(name)))
        return rows + ([(", ".join(replaced), UNRELIABLE, UNRELIABLE_SOURCE)] if replaced else [])
    return [(label, _shown(figs[name]), _source(figs[name])) for label, name in wanted if name in figs]


# --- File names people see (downloads and email); the run folder keeps report.pdf and report_executive.pdf -------

REPORT_KINDS = {"report.pdf": "Detailed", "report_executive.pdf": "Executive"}


def report_filename(fund_name: str, kind: str, as_of) -> str:
    """ {Fund_Name}_{Executive|Detailed}_Report_{YYYY-MM-DD}.pdf, dated at the end of the review period """
    import re
    name = re.sub(r"[^A-Za-z0-9]+", "_", fund_name or "Fund").strip("_") or "Fund"
    return f"{name}_{kind}_Report_{as_of:%Y-%m-%d}.pdf"


def download_copy(pdf, fund_name: str, as_of):
    """ A copy of report.pdf or report_executive.pdf under its readable name, in a 'download' folder next to it (the
    browser saves a file under its own name); the original stays where the run log and tests expect it """
    import shutil
    from pathlib import Path
    pdf = Path(pdf)
    target = pdf.parent / "download" / report_filename(fund_name, REPORT_KINDS.get(pdf.name, "Detailed"), as_of)
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(pdf, target)
    return target


# --- A mismatch that makes the fund-vs-index comparison unreliable ------------------------------------------------

# Blocking data checks that mean the fund and its index (or benchmark) are not on the same footing: a chart of the
# gap between them would mislead until the check is resolved
COMPARISON_CHECKS = ("currency_match", "implausible_tracker_gap")


def comparison_problems(flags) -> list[str]:
    """ The blocking messages that invalidate the fund-vs-index comparison (empty when there are none) """
    return [f["message"] for f in flag_dicts(flags) if f["level"] == "blocking" and f["check"] in COMPARISON_CHECKS]


def comparison_invalid(facts: dict | None) -> bool:
    """ True while such a check is open: no fund-vs-index figure is then presented as a finding """
    return bool(comparison_problems((facts or {}).get("data_flags", [])))


# While the comparison is invalid, figures that compare the fund with its index (or describe the index next to it)
# are shown as not reliable: replaced in the summaries (dashboard, Executive Report), kept and marked in the Detailed
# Report for audit. The calculations themselves are unchanged.
UNRELIABLE = "Not reliable"
UNRELIABLE_SOURCE = "Data check needed"
UNRELIABLE_MARK = "not reliable: data check"
UNRELIABLE_WHY = ("Currency or benchmark mismatch: not reliable until the data check is resolved (see the data "
                  "issues)")
COMPARISON_FINDING = ("The figures that compare the fund with its index (the gap to the index, tracking and the notes "
                      "built on them) are not reliable until the data check is resolved, so no finding is drawn from "
                      "them.")
_RELATIVE_RISK = ("tracking_error", "r2", "beta", "alpha", "information_ratio", "relative")


def is_comparative(name: str) -> bool:
    """ A figure that compares the fund with its index, or the index's own figure shown beside the fund's """
    return (name.startswith(("comparison.", "relative.", "index.")) or
            (name.startswith("risk.") and any(f".{k}" in name for k in _RELATIVE_RISK)))


CHART_LEFT_OUT = ("A data check found a currency or benchmark mismatch between the fund and its index (see the data "
                  "issues on page 2), so a chart of the gap between them would mislead. Resolve the data check first. "
                  "The original charts are kept in the Detailed Report (Appendix A), marked as not reliable.")
NOT_RELIABLE = ("Not reliable until the data check is resolved: a currency or benchmark mismatch means the fund and "
                "its index are not on the same footing. The fund-versus-index charts, figures and notes here are kept "
                "as the original evidence for audit only, marked \"not reliable\"; they are not findings.")


def merge_same_ending(items: list[str], ending: str, joiner: str = "and") -> list[str]:
    """ "Mandate: X" and "Performance: X" -> "Mandate and Performance: X" (same wording, said once) """
    same = [i for i in items if i.endswith(ending)]
    if len(same) < 2:
        return items
    names = [i[: -len(ending)] for i in same]
    merged = (", ".join(names[:-1]) + f" {joiner} " + names[-1]) + ending
    out, done = [], False
    for i in items:
        if i in same:
            if not done:
                out.append(merged)
                done = True
        else:
            out.append(i)
    return out


def report_action(text: str) -> str:
    """ An action as the PDFs show it: the old page reference points to the Detailed Report's appendices """
    return text.replace("on pages 2 to 4", "in the Detailed Report (Appendices A to D)")
