""" Data quality checks (spec Section 3.4). Each check returns DataFlag entries for data_flags[]

Levels: "info" is for the record, "warning" needs a look, "blocking" means the affected item is
shown as CHECK DATA instead of a rating.
"""
from dataclasses import dataclass, field
from datetime import date
import numpy as np
import pandas as pd
from fund_performance.calc import calendar_year_returns
from fund_performance.config import Thresholds
from fund_performance.io import PriceData, detect_frequency
from fund_performance.models import DataFlag, FactsheetPerformance, FundProfile, SeriesReturns

PRE_LAUNCH_LABEL = "pre-launch (likely simulated)"


def _dates(values) -> list[date]:
    return [pd.Timestamp(v).date() for v in values]


# --- Currency match ---------------------------------------------------------------------------------

def currency_match(fund_currency: str | None, index_currency: str | None) -> list[DataFlag]:
    """ Both series state a currency and they differ: flag directly (owner decision) """
    if fund_currency and index_currency and fund_currency.upper() != index_currency.upper():
        return [DataFlag(check="currency_match", level="blocking",
                         message=f"CHECK DATA: currency mismatch (fund {fund_currency.upper()}, "
                                 f"index {index_currency.upper()}); fund and index are not compared")]
    return []


def index_currency_vs_factsheet(prices: pd.DataFrame, factsheet: FactsheetPerformance,
                                tolerance_pp: float) -> list[DataFlag]:
    """ The price file's index has no currency, so compare its calendar-year returns with the factsheet's
    index. A gap above the tolerance in any year means the index is probably in another currency """
    if "index_level" not in prices.columns or "index" not in factsheet.calendar_years:
        return []
    file_years = calendar_year_returns(prices, "index_level")
    official = factsheet.calendar_years["index"]
    gaps = {y: file_years[y] - official[y] for y in file_years if y in official}
    bad = {y: g for y, g in gaps.items() if abs(g) > tolerance_pp}
    if not bad:
        return []
    detail = "; ".join(f"{y}: file {file_years[y]:.1f}% vs factsheet {official[y]:.1f}%" for y in sorted(bad))
    return [DataFlag(check="currency_match", level="blocking",
                     message=f"CHECK DATA: currency mismatch. The price file's index does not match the factsheet "
                             f"index ({detail}); the factsheet index figures are used instead")]


# --- End-date alignment -------------------------------------------------------------------------------

def align_end_dates(prices: pd.DataFrame) -> tuple[pd.DataFrame, list[DataFlag]]:
    """ Fund and index must end on the same date: truncate to the last date both have, and log it """
    if "index_level" not in prices.columns:
        return prices, []
    fund_end = prices.loc[prices["nav"].notna(), "date"].max()
    index_end = prices.loc[prices["index_level"].notna(), "date"].max()
    if fund_end == index_end:
        return prices, []
    common = min(fund_end, index_end)
    kept = prices[prices["date"] <= common].reset_index(drop=True)
    return kept, [DataFlag(check="end_date_alignment", level="info",
                           message=f"Fund ends {fund_end:%Y-%m-%d}, index ends {index_end:%Y-%m-%d}: "
                                   f"truncated to the common end date {common:%Y-%m-%d}",
                           dates=_dates([common]))]


# --- Pricing point -----------------------------------------------------------------------------------

@dataclass
class ComparisonBasis:
    """ Which factsheet fund series to compare with the index, and any extra tolerance for timing """
    fund_series: str
    extra_tolerance_pp: float = 0.0
    flags: list[DataFlag] = field(default_factory=list)


def pricing_point(profile: FundProfile, factsheet: FactsheetPerformance | None,
                  extra_tolerance_pp: float) -> ComparisonBasis:
    """ A midday-priced fund is compared with a market-close index using PNAV when available;
    otherwise the timing difference is noted and the tolerance widened """
    index = factsheet.series.get("index") if factsheet else None
    if profile.pricing_point != "midday" or index is None or index.pricing != "market_close":
        return ComparisonBasis("fund_nav")
    if "fund_pnav" in factsheet.series:
        return ComparisonBasis("fund_pnav", flags=[DataFlag(
            check="pricing_point", level="info",
            message="Fund priced at midday, index at market close: fund PNAV (market-close) is used "
                    "for the fund-vs-index comparison")])
    return ComparisonBasis("fund_nav", extra_tolerance_pp, flags=[DataFlag(
        check="pricing_point", level="warning",
        message=f"Timing difference: fund priced at midday, index at market close, and no PNAV available. "
                f"Tolerance widened by {extra_tolerance_pp:.2f} pp")])


# --- Missing values and gaps ----------------------------------------------------------------------------

def missing_values(prices: pd.DataFrame) -> list[DataFlag]:
    """ List the dates of any missing NAV or index value; they are left out of return-based statistics """
    flags = []
    for column, label in (("nav", "NAV"), ("index_level", "index")):
        if column in prices.columns and prices[column].isna().any():
            dates = prices.loc[prices[column].isna(), "date"]
            flags.append(DataFlag(check="missing_values", level="warning",
                                  message=f"{len(dates)} missing {label} value(s); excluded from return-based "
                                          "risk statistics, not filled in", dates=_dates(dates)))
    return flags


def gaps(prices: pd.DataFrame, max_days_monthly: int, max_business_days_daily: int) -> list[DataFlag]:
    """ A gap between observations longer than a month (monthly data) or a week (daily data) """
    dates = prices["date"]
    frequency = detect_frequency(dates)
    if frequency == "unknown":
        return [DataFlag(check="gaps", level="warning", message="Data frequency not recognised as daily or monthly")]
    if frequency == "monthly":
        too_long = dates.diff().dt.days > max_days_monthly
        rule = f"more than {max_days_monthly} days"
    else:
        business = np.busday_count(dates.shift().dropna().values.astype("datetime64[D]"),
                                   dates.iloc[1:].values.astype("datetime64[D]"))
        too_long = pd.Series([False] + list(business > max_business_days_daily), index=dates.index)
        rule = f"more than {max_business_days_daily} business days"
    if not too_long.any():
        return []
    ends = dates[too_long]
    return [DataFlag(check="gaps", level="warning",
                     message=f"{len(ends)} gap(s) of {rule} between observations (dates shown are the end of each gap)",
                     dates=_dates(ends))]


# --- Pre-launch prices -------------------------------------------------------------------------------------

def pre_launch(prices: pd.DataFrame, launch_date: date) -> list[DataFlag]:
    """ Prices before the share class launch are probably simulated (owner decision) """
    before = prices.loc[prices["date"] < pd.Timestamp(launch_date), "date"]
    if before.empty:
        return []
    return [DataFlag(check="pre_launch", level="info",
                     message=f"{len(before)} price(s) dated before the share class launch on {launch_date:%Y-%m-%d}: "
                             f"{PRE_LAUNCH_LABEL}. Left out of risk statistics and since-launch figures",
                     dates=_dates(before))]


def post_launch(prices: pd.DataFrame, launch_date: date) -> pd.DataFrame:
    """ Prices from the launch date onwards, for risk statistics and since-launch figures """
    return prices[prices["date"] >= pd.Timestamp(launch_date)].reset_index(drop=True)


# --- Repeated prices --------------------------------------------------------------------------------------

def repeated_prices(prices: pd.DataFrame, window: int, asset_class: str = "equity",
                    launch_date: date | None = None) -> list[DataFlag]:
    """ The same NAV on two dates up to `window` periods apart is suspicious for an equity fund.
    One flag per pair; pairs entirely before launch are info level (owner decision) """
    if asset_class.lower() != "equity":
        return []
    nav = prices[["date", "nav"]].dropna().reset_index(drop=True)
    flags = []
    for i in range(len(nav)):
        for j in range(i + 1, min(i + window, len(nav) - 1) + 1):
            if nav.at[i, "nav"] == nav.at[j, "nav"]:
                first, second = nav.at[i, "date"], nav.at[j, "date"]
                pre = launch_date is not None and second < pd.Timestamp(launch_date)
                flags.append(DataFlag(
                    check="repeated_prices", level="info" if pre else "warning",
                    message=f"Suspicious repeated price {nav.at[i, 'nav']:g} on {first:%Y-%m-%d} and {second:%Y-%m-%d}"
                            + (f", {PRE_LAUNCH_LABEL}" if pre else ""),
                    dates=_dates([first, second])))
    return flags


# --- History length -----------------------------------------------------------------------------------------

def history_length(prices: pd.DataFrame, time_horizon_years: int,
                   launch_date: date | None = None) -> tuple[bool, list[DataFlag]]:
    """ short_history is true when there are fewer months of (post-launch) data than the fund's horizon """
    data = post_launch(prices, launch_date) if launch_date else prices
    if len(data) < 2:
        return True, [DataFlag(check="history_length", level="warning", message="Fewer than two prices")]
    start, end = data["date"].iloc[0], data["date"].iloc[-1]
    months = (end.year - start.year) * 12 + end.month - start.month
    needed = time_horizon_years * 12
    if months >= needed:
        return False, []
    return True, [DataFlag(check="history_length", level="info",
                           message=f"Short history: {months} months of data, the fund's horizon is {needed} months; "
                                   "since-launch figures are used")]


# --- Cross-check and implausible tracker gap ---------------------------------------------------------------

def cross_check(calculated: dict[str, float], factsheet_nav: SeriesReturns, tolerance_pp: float) -> list[DataFlag]:
    """ Calculated 1/3/5y returns vs the factsheet NAV returns (same basis); the factsheet always wins """
    official = {"1y": factsheet_nav.y1, "3y": factsheet_nav.y3, "5y": factsheet_nav.y5}
    flags = []
    for period, value in calculated.items():
        reported = official.get(period)
        if reported is not None and abs(value - reported) > tolerance_pp:
            flags.append(DataFlag(check="cross_check", level="warning",
                                  message=f"{period}: calculated {value:.2f}% vs factsheet {reported:.1f}% "
                                          f"(gap above {tolerance_pp} pp); the factsheet figure is used"))
    return flags


def implausible_tracker_gap(objective_type: str, price_data_only: bool, annualised_gap_pct: float,
                            threshold_pct: float) -> list[DataFlag]:
    """ An index fund far from its index on price data alone is more likely a data problem: CHECK DATA, not Red """
    if objective_type == "index_tracker" and price_data_only and abs(annualised_gap_pct) > threshold_pct:
        return [DataFlag(check="implausible_tracker_gap", level="blocking",
                         message=f"CHECK DATA: index fund {annualised_gap_pct:+.2f}% a year from its index on price "
                                 f"data only (above {threshold_pct}%). Confirm with the factsheet before rating")]
    return []


# --- All price checks together ---------------------------------------------------------------------------

@dataclass
class PriceCheckResult:
    prices: pd.DataFrame                 # after end-date alignment
    flags: list[DataFlag]
    short_history: bool
    comparison: ComparisonBasis | None

    @property
    def blocking(self) -> list[DataFlag]:
        return [f for f in self.flags if f.level == "blocking"]


def check_prices(data: PriceData, profile: FundProfile, thresholds: Thresholds,
                 factsheet: FactsheetPerformance | None = None,
                 index_currency: str | None = None) -> PriceCheckResult:
    """ Run every price-file check in spec 3.4 that does not need calculated returns
    (the cross-check and the tracker-gap check run once the calculator has produced figures) """
    t = thresholds.data_checks
    flags = currency_match(profile.currency, index_currency)
    if factsheet is not None:
        flags += index_currency_vs_factsheet(data.prices, factsheet, t.currency_mismatch_calendar_year_pp)
    prices, aligned = align_end_dates(data.prices)
    flags += aligned
    comparison = pricing_point(profile, factsheet, t.timing_difference_extra_tolerance_pp) if factsheet else None
    if comparison:
        flags += comparison.flags
    flags += missing_values(prices)
    flags += gaps(prices, t.max_gap_days_monthly, t.max_gap_business_days_daily)
    flags += pre_launch(prices, profile.launch_date)
    flags += repeated_prices(prices, t.repeated_price_window_periods, profile.asset_class, profile.launch_date)
    short, history = history_length(prices, profile.time_horizon_years, profile.launch_date)
    flags += history
    return PriceCheckResult(prices=prices, flags=flags, short_history=short, comparison=comparison)
