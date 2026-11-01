""" Factsheet precedence and cross-check (spec principle 2 and Section 3.4; build step 4)

For every figure the factsheet's own number is reported when it exists; the calculated one is kept as
a cross-check. Calculated 1/3/5y returns more than 0.3 pp from the factsheet are flagged, and the
factsheet wins. The fund-vs-index comparison uses the series chosen by the pricing-point check (PNAV
for a midday-priced fund), never the midday NAV against a market-close index.
"""
from dataclasses import dataclass, field
from datetime import date
import pandas as pd
from fund_performance import checks
from fund_performance.calc import CALENDAR_YEARS_SHOWN, PERIODS, CalcResult, annualise, cumulate, hit_rate_index
from fund_performance.checks import ComparisonBasis
from fund_performance.config import Thresholds
from fund_performance.models import DataFlag, FactsheetPerformance, Figure, FundProfile

PRICE_SERIES = "fund_nav"          # a price file holds the fund's dealing NAV
CONSISTENT = "checked against factsheet: consistent"


@dataclass
class ReportedFigures:
    """ The figures to report (factsheet first), every flag, and a log of each choice for the run log """
    figures: dict[str, Figure] = field(default_factory=dict)
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def value(self, name: str) -> float | None:
        figure = self.figures.get(name)
        return None if figure is None else figure.value


def _factsheet(value: float, unit: str, period: str, basis: str | None = None) -> Figure:
    return Figure(value=round(value, 2), exact=value, unit=unit, source="factsheet", period=period, basis=basis)


def _derived(value: float, unit: str, period: str, basis: str | None = None) -> Figure:
    """ Calculated by code from factsheet figures (e.g. annualised from an official cumulative return) """
    return Figure(value=round(value, 2), exact=value, unit=unit, source="calculated", period=period, basis=basis)


def _years(period: str) -> int:
    return int(period.rstrip("y"))


def apply_precedence(calculated: CalcResult, price_flags: list[DataFlag], profile: FundProfile,
                     thresholds: Thresholds, factsheet: FactsheetPerformance | None = None,
                     comparison: ComparisonBasis | None = None,
                     currency_blocked: bool = False) -> ReportedFigures:
    out = ReportedFigures()
    t = thresholds.data_checks
    calc_series = {"fund": PRICE_SERIES} | ({} if currency_blocked else {"index": "index"})
    if currency_blocked:
        out.log.append("Price-file index not used: currency mismatch")

    _returns(out, calculated, calc_series, factsheet)
    _discrete_and_calendar(out, calculated, calc_series, factsheet)
    _since_launch(out, calculated, profile, factsheet, calc_series)
    _risk(out, calculated, factsheet, calc_series)
    if factsheet is not None and PRICE_SERIES in factsheet.series:
        out.flags += _cross_check(out, calculated, factsheet, t.cross_check_tolerance_pp)
    out.flags += [_review_repeated_price(f, calculated, factsheet, t.repeated_price_factsheet_match_pp)
                  for f in price_flags]
    out.flags += calculated.flags
    _comparison(out, calculated, profile, thresholds, factsheet, comparison)
    if factsheet is not None and factsheet.source == "ai_extracted":
        # Figures the Extractor Agent read keep that label, so the report shows them "(please verify)"
        out.figures = {k: f.model_copy(update={"source": "ai_extracted"}) if f.source == "factsheet" else f
                       for k, f in out.figures.items()}
    if factsheet is not None and factsheet.user_entered:
        # Figures a person corrected before the run ("index.5y" -> index.cum.5y): reported as entered by user
        corrected = {f"{key.split('.')[0]}.cum.{key.split('.')[1]}" for key in factsheet.user_entered if "." in key}
        out.figures = {k: f.model_copy(update={"source": "user"}) if k in corrected and f.source != "calculated" else f
                       for k, f in out.figures.items()}
    return out


def _returns(out: ReportedFigures, calculated: CalcResult, calc_series: dict[str, str],
             factsheet: FactsheetPerformance | None) -> None:
    """ 1/3/5y cumulative and annualised returns: factsheet first, then annualised from the factsheet's
    cumulative figure, then the calculated figure """
    names = set(factsheet.series if factsheet else []) | set(calc_series.values())
    for name in sorted(names):
        reported = factsheet.series.get(name) if factsheet else None
        annual = factsheet.series_annualised.get(name) if factsheet else None
        calc_prefix = next((k for k, v in calc_series.items() if v == name), None)
        annualised_input = reported is not None and reported.basis == "annualised"
        for n in PERIODS:
            period = f"{n}y"
            official = getattr(reported, f"y{n}") if reported else None
            if official is not None and annualised_input:
                # The input says these are a-year figures: kept as such; the cumulative one is derived by code
                if annual is None or getattr(annual, f"y{n}") is None:
                    out.figures[f"{name}.ann.{period}"] = _factsheet(official, "%", period)
                out.figures[f"{name}.cum.{period}"] = (_factsheet(official, "%", period) if n == 1 else
                                                      _derived(cumulate(official, n), "%", period))
                if n > 1:
                    out.log.append(f"{name} {period} cumulative derived from the factsheet's annualised {official}%")
                if annual is not None and getattr(annual, f"y{n}") is not None:
                    out.figures[f"{name}.ann.{period}"] = _factsheet(getattr(annual, f"y{n}"), "%", period)
                continue
            if official is not None:
                out.figures[f"{name}.cum.{period}"] = _factsheet(official, "%", period)
            elif calc_prefix and f"{calc_prefix}.cum.{period}" in calculated.figures:
                out.figures[f"{name}.cum.{period}"] = calculated.figures[f"{calc_prefix}.cum.{period}"]
            official_ann = getattr(annual, f"y{n}") if annual else None
            if official_ann is not None:
                out.figures[f"{name}.ann.{period}"] = _factsheet(official_ann, "%", period)
            elif official is not None:
                out.figures[f"{name}.ann.{period}"] = _derived(annualise(official, n), "%", period)
                out.log.append(f"{name} {period} annualised from the factsheet's cumulative {official}%")
            elif calc_prefix and f"{calc_prefix}.ann.{period}" in calculated.figures:
                out.figures[f"{name}.ann.{period}"] = calculated.figures[f"{calc_prefix}.ann.{period}"]


def _discrete_and_calendar(out: ReportedFigures, calculated: CalcResult, calc_series: dict[str, str],
                           factsheet: FactsheetPerformance | None) -> None:
    for kind, official_tables in (("discrete_12m", factsheet.discrete_12m if factsheet else {}),
                                  ("calendar", factsheet.calendar_years if factsheet else {})):
        for name, values in official_tables.items():
            keys = sorted(values, key=str)
            if kind == "calendar":
                keys = keys[-CALENDAR_YEARS_SHOWN:]
            for key in keys:
                label = key.isoformat() if isinstance(key, date) else key
                period = f"12m to {label}" if kind == "discrete_12m" else label
                out.figures[f"{name}.{kind}.{label}"] = _factsheet(values[key], "%", period)
        # Calculated figures fill only what the factsheet does not give
        for prefix, name in calc_series.items():
            for key, figure in calculated.figures.items():
                if key.startswith(f"{prefix}.{kind}."):
                    out.figures.setdefault(f"{name}.{kind}.{key.split('.', 2)[2]}", figure)


def _since_launch(out: ReportedFigures, calculated: CalcResult, profile: FundProfile,
                  factsheet: FactsheetPerformance | None, calc_series: dict[str, str]) -> None:
    """ Since-launch figures for every series: factsheet first, calculated otherwise. A gap between the
    calculated and factsheet fund figure is explained in the run log only (owner decision) """
    period = f"since {profile.launch_date:%Y-%m-%d}"
    names = set(factsheet.series if factsheet else []) | set(calc_series.values())
    for name in sorted(names):
        reported = factsheet.series.get(name) if factsheet else None
        annual = factsheet.series_annualised.get(name) if factsheet else None
        calc_prefix = next((k for k, v in calc_series.items() if v == name), None)
        calc_cum = calculated.figures.get(f"{calc_prefix}.since_launch.cum") if calc_prefix else None
        calc_ann = calculated.figures.get(f"{calc_prefix}.since_launch.ann") if calc_prefix else None
        if reported is not None and reported.since_launch is not None and reported.basis == "annualised":
            if annual is None or annual.since_launch is None:            # kept as a-year; never read as cumulative
                out.figures[f"{name}.since_launch.ann"] = _factsheet(reported.since_launch, "%", period)
            if calc_cum is not None:
                out.figures[f"{name}.since_launch.cum"] = calc_cum
            continue
        if reported is not None and reported.since_launch is not None:
            out.figures[f"{name}.since_launch.cum"] = _factsheet(reported.since_launch, "%", period)
            if calc_cum is not None and name == PRICE_SERIES:
                start = calc_cum.period.removeprefix("since ")
                reason = (f"the price file has no launch-day price, so the calculation starts at the first price "
                          f"after launch ({start})" if start != f"{profile.launch_date:%Y-%m-%d}" else "see the price file")
                out.log.append(f"Since-launch cumulative: calculated {calc_cum.exact:.1f}% vs factsheet "
                               f"{reported.since_launch:.1f}%; {reason}. The factsheet figure is used")
        elif calc_cum is not None:
            out.figures[f"{name}.since_launch.cum"] = calc_cum
        if annual is not None and annual.since_launch is not None:
            out.figures[f"{name}.since_launch.ann"] = _factsheet(annual.since_launch, "%", period)
        elif calc_ann is not None:
            out.figures[f"{name}.since_launch.ann"] = calc_ann


def _risk(out: ReportedFigures, calculated: CalcResult, factsheet: FactsheetPerformance | None,
          calc_series: dict[str, str]) -> None:
    """ Factsheet risk figures by basis (never mixed); calculated risk kept as a cross-check """
    ratios = {"beta", "r2", "info_ratio", "sharpe_fund", "sharpe_index"}
    sets = {basis: factsheet.risk(basis) for basis in ("pnav", "nav")} if factsheet else {}
    if factsheet and factsheet.risk_3y is not None and factsheet.risk_3y.basis is None:
        sets["unspecified"] = factsheet.risk_3y       # the factsheet did not say NAV or PNAV
    for basis, risk in sets.items():
        for name, value in (risk.model_dump(exclude={"basis"}) if risk else {}).items():
            if value is not None:
                out.figures[f"risk.{basis}.{name}.3y"] = _factsheet(value, "ratio" if name in ratios else "%", "3y", basis)
    for key, figure in calculated.figures.items():
        prefix, kind = key.split(".")[:2]
        if prefix in calc_series and kind in ("vol", "mdd", "sharpe"):
            out.figures[f"{calc_series[prefix]}.{key.split('.', 1)[1]}"] = figure
        elif prefix == "relative" and "index" in calc_series:      # needs a usable index series
            out.figures[key] = figure
    nav_risk = factsheet.risk("nav") if factsheet else None
    calc_vol = calculated.figures.get("fund.vol.3y")
    if nav_risk is not None and nav_risk.fund_vol is not None and calc_vol is not None:
        out.log.append(f"Cross-check 3y volatility (NAV): calculated {calc_vol.exact:.2f}% vs factsheet "
                       f"{nav_risk.fund_vol:.2f}%")


def _cross_check(out: ReportedFigures, calculated: CalcResult, factsheet: FactsheetPerformance,
                 tolerance_pp: float) -> list[DataFlag]:
    """ Calculated 1/3/5y NAV returns vs the factsheet NAV returns (spec 3.4); the factsheet wins """
    reported = factsheet.series[PRICE_SERIES]
    kind = "ann" if reported.basis == "annualised" else "cum"      # compare like with like: the input's own basis
    values = {f"{n}y": calculated.figures[f"fund.{kind}.{n}y"].exact for n in PERIODS
              if f"fund.{kind}.{n}y" in calculated.figures}
    for period, value in values.items():
        official = getattr(reported, f"y{_years(period)}")
        if official is not None:
            what = "NAV return a year" if kind == "ann" else "NAV return"
            out.log.append(f"Cross-check {period} {what}: calculated {value:.2f}% vs factsheet {official:.1f}% "
                           f"(difference {value - official:+.2f} pp)")
    return checks.cross_check(values, reported, tolerance_pp)


def _review_repeated_price(flag: DataFlag, calculated: CalcResult, factsheet: FactsheetPerformance | None,
                           tolerance_pp: float) -> DataFlag:
    """ A repeated-price warning becomes info when every factsheet 12-month window around those dates
    matches the calculated return within the tolerance (owner decision); otherwise it stays a warning """
    if flag.check != "repeated_prices" or flag.level != "warning":
        return flag
    official = factsheet.discrete_12m.get(PRICE_SERIES, {}) if factsheet else {}
    covering = [end for end in official
                if any(pd.Timestamp(end) - pd.DateOffset(years=1) <= pd.Timestamp(d) <= pd.Timestamp(end)
                       for d in flag.dates)]
    if not covering:
        return flag.model_copy(update={"message": flag.message + "; no factsheet 12-month figure covers these dates"})
    details, consistent = [], True
    for end in sorted(covering):
        calc_fig = calculated.figures.get(f"fund.discrete_12m.{end.isoformat()}")
        if calc_fig is None:
            consistent = False
            details.append(f"12 months to {end.isoformat()}: no calculated figure")
            continue
        gap = calc_fig.exact - official[end]
        consistent &= abs(gap) <= tolerance_pp
        details.append(f"12 months to {end.isoformat()}: calculated {calc_fig.exact:.2f}% vs factsheet {official[end]:.1f}%")
    if consistent:
        return flag.model_copy(update={"level": "info", "message": f"{flag.message}; {CONSISTENT} ({'; '.join(details)})"})
    return flag.model_copy(update={"message": f"{flag.message}; does not match the factsheet ({'; '.join(details)})"})


def _comparison(out: ReportedFigures, calculated: CalcResult, profile: FundProfile, thresholds: Thresholds,
                factsheet: FactsheetPerformance | None, comparison: ComparisonBasis | None) -> None:
    """ Fund vs index on a fair basis: excess, tracking difference (+ cost-adjusted) and the index-fund hit rate """
    fund = comparison.fund_series if comparison else PRICE_SERIES
    n_h = profile.analysis_period_years
    if "index.ann.1y" in out.figures or "index.ann.5y" in out.figures:
        out.log.append(f"Fund vs index comparison uses {fund}" +
                       (f" (tolerance widened by {comparison.extra_tolerance_pp:.2f} pp)"
                        if comparison and comparison.extra_tolerance_pp else ""))
    for n in PERIODS:
        f_cum, i_cum = out.figures.get(f"{fund}.cum.{n}y"), out.figures.get(f"index.cum.{n}y")
        f_ann, i_ann = out.figures.get(f"{fund}.ann.{n}y"), out.figures.get(f"index.ann.{n}y")
        if f_cum and i_cum:
            out.figures[f"comparison.excess_cum.{n}y"] = _derived(f_cum.exact - i_cum.exact, "pp", f"{n}y", fund)
        if f_ann and i_ann:
            td = f_ann.exact - i_ann.exact
            out.figures[f"comparison.td.{n}y"] = _derived(td, "pp", f"{n}y", fund)
            if profile.ocf_pct is not None:
                out.figures[f"comparison.td_ex_cost.{n}y"] = _derived(td + profile.ocf_pct, "pp", f"{n}y", fund)

    # Index fund on price data only: a large gap is more likely a data problem (spec 3.4)
    td = calculated.figures.get(f"relative.td.{n_h}y")
    if factsheet is None and td is not None:
        out.flags += checks.implausible_tracker_gap(profile.objective_type, True, td.exact,
                                                    thresholds.data_checks.implausible_tracker_gap_pct)

    # Hit rate (spec 4.4), index funds: windows where abs(TD) <= OCF + margin
    if profile.objective_type == "index_tracker" and profile.ocf_pct is not None:
        fund_12m = {k.rsplit(".", 1)[1]: f.exact for k, f in out.figures.items() if k.startswith(f"{fund}.discrete_12m.")}
        index_12m = {k.rsplit(".", 1)[1]: f.exact for k, f in out.figures.items() if k.startswith("index.discrete_12m.")}
        tolerance = profile.ocf_pct + thresholds.performance_index.hit_rate_td_margin_over_ocf_pp
        hits, windows = hit_rate_index(fund_12m, index_12m, tolerance)
        if windows:
            out.figures["comparison.hit_rate"] = Figure(value=hits, exact=hits, unit=f"of {windows}",
                                                        source="calculated", period="12-month windows", basis=fund)
            out.log.append(f"Hit rate: {hits} of {windows} 12-month windows within {tolerance:.2f} pp ({fund} vs index)")
