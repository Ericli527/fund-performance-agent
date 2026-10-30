""" Extractor Agent (spec Sections 3.2 and 8): reads factsheet/KID text and returns the factsheet figures
and a draft fund profile. Every value is labelled ai_extracted ("please verify").

Code converts and validates the answer. It also looks for each extracted number in the document text and
flags any it cannot find, since a number that is not in the document must have come from somewhere else.
The agent never sets objective_type, benchmark_role, the horizon, the secondary objective or a
performance-fee justification: those come from the Mandate Agent or from a person.
"""
from dataclasses import dataclass, field
from datetime import date
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.models import DataFlag, FactsheetPerformance, FundProfile

SeriesName = Literal["fund_nav", "fund_pnav", "index"]
NEVER_FROM_AI = {"objective_type", "benchmark_role", "time_horizon_years", "secondary_objective",
                 "performance_fee_justification", "asset_class"}

INSTRUCTIONS = """
You copy fund figures from factsheets and KIDs. Copy values exactly as printed. Never calculate,
estimate, round or guess. If something is not in the text, return null (or an empty list).

Series names: "fund_nav" = the fund's own NAV performance (e.g. "Fund NAV (midday)", "P USD Acc");
"fund_pnav" = a hypothetical market-close NAV used to compare with the index ("Fund PNAV");
"index" = the market index or benchmark. Use the main share class only.

series: one entry per series and basis. basis "cumulative" for cumulative growth rows,
"annualised" for annualised rows. y1, y3, y5 = 1, 3 and 5-year figures; since_launch = the
since-launch figure. pricing = "midday" or "market_close" if the document says so, else null.
calendar_years: one entry per series and calendar year (year as "2025").
discrete_12m: 12-month periods; end_date is the END of the period as YYYY-MM-DD. Periods are often printed as a
pair of dates ("30.09.2025 30.09.2026"): the end is the LATER date of the pair; the latest period usually ends on
the factsheet date.
risk: one entry per basis of the risk table ("nav" or "pnav" as labelled, else null).
All returns and percentages as plain numbers in percent (17.5 for 17.5%).
profile: the fund facts as printed. Dates as YYYY-MM-DD. ocf_pct as a number (0.06 for 0.06%).
minimum_investment: the minimum initial investment as printed (e.g. "GBP 10,000,000"), else null.
performance_fee: false only if the documents say there is none (e.g. "Performance fee: None", "N/A", "Nil",
"0%"); true only if they say one is charged; else null. "Excludes performance fees (where applicable)" says
neither.
transaction_cost_pct only if a transaction cost figure is printed. fund_size_gbp_m only if the size
is in GBP millions.
"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedSeries(_Strict):
    name: SeriesName
    basis: Literal["cumulative", "annualised"]
    pricing: Literal["midday", "market_close"] | None
    y1: float | None
    y3: float | None
    y5: float | None
    since_launch: float | None


class ExtractedYear(_Strict):
    series: SeriesName
    year: str
    value: float


class ExtractedWindow(_Strict):
    series: SeriesName
    end_date: str
    value: float


class ExtractedRisk(_Strict):
    basis: Literal["nav", "pnav"] | None
    fund_vol: float | None
    index_vol: float | None
    tracking_error: float | None
    beta: float | None
    r2: float | None
    sharpe_fund: float | None
    sharpe_index: float | None
    info_ratio: float | None
    alpha: float | None


class ExtractedProfile(_Strict):
    fund_name: str | None
    isin: str | None
    share_class: str | None
    currency: str | None
    distribution: Literal["accumulation", "income"] | None
    hedged: bool | None
    launch_date: str | None
    objective_text: str | None
    benchmark_name: str | None
    ocf_pct: float | None
    transaction_cost_pct: float | None
    performance_fee: bool | None
    fund_size_gbp_m: float | None
    risk_indicator: int | None
    pricing_point: Literal["midday", "market_close"] | None
    minimum_investment: str | None


class ExtractorOutput(_Strict):
    as_of_date: str | None
    currency: str | None
    series: list[ExtractedSeries]
    calendar_years: list[ExtractedYear]
    discrete_12m: list[ExtractedWindow]
    risk: list[ExtractedRisk]
    profile: ExtractedProfile


@dataclass
class ExtractionResult:
    factsheet: FactsheetPerformance | None
    profile_draft: dict = field(default_factory=dict)     # only what the documents state; a person confirms
    missing_profile_fields: list[str] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)


def extractor_agent():
    return build_agent("Extractor Agent", INSTRUCTIONS, ExtractorOutput, "extractor")


def start_labelled(out: ExtractorOutput) -> bool:
    """ The 12-month periods were labelled by their start dates: the latest one should end on the factsheet date,
    and every one ends exactly one year early (a pair of dates "30.09.2025 30.09.2026" read as its first date) """
    ends = {w.end_date for w in out.discrete_12m}
    if not ends or not out.as_of_date:
        return False
    try:
        as_of = date.fromisoformat(out.as_of_date)
        latest = max(date.fromisoformat(e) for e in ends)
    except ValueError:
        return False
    return latest != as_of and _one_year_later(latest) == as_of


def _one_year_later(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:                                   # 29 February
        return day.replace(year=day.year + 1, day=28)


def period_end(end_date: str, out: ExtractorOutput) -> str:
    """ The period's end date, moved one year on when the periods were labelled by their start dates (code) """
    if not start_labelled(out):
        return end_date
    return _one_year_later(date.fromisoformat(end_date)).isoformat()


def to_factsheet(out: ExtractorOutput) -> FactsheetPerformance:
    """ Convert the agent's lists into factsheet_performance.json; raises ValueError if it does not validate """
    series, annualised = {}, {}
    for s in out.series:
        target = series if s.basis == "cumulative" else annualised
        target[s.name] = {"1y": s.y1, "3y": s.y3, "5y": s.y5, "since_launch": s.since_launch,
                          "basis": s.basis, "pricing": s.pricing}
    years: dict[str, dict[str, float]] = {}
    for y in out.calendar_years:
        years.setdefault(y.series, {})[y.year] = y.value
    windows: dict[str, dict[str, float]] = {}
    for w in out.discrete_12m:
        windows.setdefault(w.series, {})[period_end(w.end_date, out)] = w.value
    risk = {r.basis: r.model_dump(exclude_none=True) for r in out.risk}
    data = {"as_of_date": out.as_of_date, "currency": out.currency, "series": series,
            "series_annualised": annualised, "calendar_years": years, "discrete_12m": windows,
            "source": "ai_extracted", "entered_by": "extractor"}
    if "nav" in risk and "pnav" in risk:
        data |= {"risk_3y": risk["pnav"], "risk_3y_nav": risk["nav"]}
    elif risk:
        data["risk_3y"] = next(iter(risk.values()))
    try:
        return FactsheetPerformance.model_validate(data)
    except ValueError as e:         # pydantic's ValidationError is a ValueError
        raise ValueError(f"extracted figures do not fit factsheet_performance.json: {e}") from e


def profile_draft(out: ExtractorOutput) -> tuple[dict, list[str]]:
    """ The fields the documents state, never the ones reserved for the Mandate Agent or a person """
    draft = {k: v for k, v in out.profile.model_dump().items() if v is not None and k not in NEVER_FROM_AI}
    required = [name for name, f in FundProfile.model_fields.items() if f.is_required()]
    return draft, [name for name in required if name not in draft]


def _numbers_in(text: str) -> set[float]:
    """ Every number printed in the text ('11,006' -> 11006; '-8.6' and '−8.6' -> -8.6) """
    text = text.replace("−", "-").replace("–", "-")
    tokens = re.findall(r"-?\d[\d,]*\.?\d*", text)
    numbers = set()
    for t in tokens:
        cleaned = t.replace(",", "").rstrip(".")
        try:
            numbers.add(round(float(cleaned), 6))
        except ValueError:
            continue
    return numbers | {abs(n) for n in numbers}


def unfound_numbers(out: ExtractorOutput, text: str) -> list[str]:
    """ Extracted numbers that do not appear anywhere in the document text """
    found = _numbers_in(text)
    missing = []
    def check(label: str, value, millions: bool = False):
        if value is None or isinstance(value, bool):
            return
        candidates = {round(float(value), 6), round(abs(float(value)), 6)}
        if millions:                                     # GBP millions, printed in full ("GBP 21,762,581,005")
            candidates.add(round(float(value) * 1_000_000, 0))
        if not candidates & found:
            missing.append(f"{label} = {value}")
    for s in out.series:
        for period in ("y1", "y3", "y5", "since_launch"):
            check(f"{s.name} {s.basis} {period}", getattr(s, period))
    for y in out.calendar_years:
        check(f"{y.series} {y.year}", y.value)
    for w in out.discrete_12m:
        check(f"{w.series} 12m to {w.end_date}", w.value)
    for r in out.risk:
        for name, value in r.model_dump(exclude={"basis"}).items():
            check(f"risk ({r.basis}) {name}", value)
    for name in ("ocf_pct", "transaction_cost_pct", "fund_size_gbp_m", "risk_indicator"):
        check(name, getattr(out.profile, name), millions=name == "fund_size_gbp_m")
    return missing


async def extract(document_text: str, run: RunFn | None = None) -> ExtractionResult:
    """ Ask the Extractor Agent, validate, retry once on invalid output, then CHECK DATA """
    holder: dict = {}

    def convert(out: ExtractorOutput) -> FactsheetPerformance:
        holder["raw"] = out
        return to_factsheet(out)

    result = await run_structured(extractor_agent(), document_text, ExtractorOutput, convert=convert, run=run)
    if not result.ok:
        return ExtractionResult(None, flags=[DataFlag(
            check="extractor_agent", level="blocking",
            message="CHECK DATA: Extractor Agent gave no valid answer after one retry (" + "; ".join(result.errors) + ")")])
    out = holder["raw"]
    draft, missing = profile_draft(out)
    flags = [DataFlag(check="extractor_agent", level="info",
                      message="Figures read by the Extractor Agent (ai_extracted): please verify against the documents")]
    if start_labelled(out):
        flags.append(DataFlag(check="extractor_agent", level="info", message=(
            "12-month periods: the Extractor Agent labelled them by their start dates; code moved each to its end "
            "date (the latest period ends on the factsheet date)")))
    unfound = unfound_numbers(out, document_text)
    if unfound:
        flags.append(DataFlag(check="extractor_agent", level="warning",
                              message="Extracted values not found in the document text: " + "; ".join(unfound)))
    return ExtractionResult(result.output, draft, missing, flags)
