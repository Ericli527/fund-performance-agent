""" Calculator formulas (spec Section 4)

Inputs are price levels indexed by date. Formulas work at full precision; results are stored as
Figures rounded to 2 d.p. (shown to 1 d.p.), each with source "calculated" (spec principle 4).
Missing prices are never filled in: any return that touches one is left out (spec 3.4).
"""
from dataclasses import dataclass, field
from datetime import date
import numpy as np
import pandas as pd
from fund_performance.config import Thresholds
from fund_performance.io import detect_frequency
from fund_performance.models import DataFlag, FactsheetPerformance, Figure, FundProfile

PERIODS = (1, 3, 5)
CALENDAR_YEARS_SHOWN = 10        # last 10 full calendar years, as on the factsheet (owner decision)
CROSS_CHECK_RISK_YEARS = 3       # factsheet risk figures are 3-year, so 3-year risk is calculated as a cross-check
NO_INDEX = "not available: no index price series"
RELATIVE_RISK = ("tracking_error", "beta", "r2", "info_ratio", "alpha")


# --- 4.1 Returns ----------------------------------------------------------------------------------------

def period_returns(levels: pd.Series) -> pd.Series:
    """ r_t = P_t / P_{t-1} - 1. A return next to a missing price is missing, never filled in """
    returns = levels / levels.shift(1) - 1
    return returns.iloc[1:]


def start_price(levels: pd.Series, years: int, end: pd.Timestamp | None = None) -> tuple[pd.Timestamp, float] | None:
    """ The last price on or before end_date - n years, or None if the data does not go back that far """
    levels = levels.dropna()
    end = levels.index[-1] if end is None else end
    earlier = levels[levels.index <= end - pd.DateOffset(years=years)]
    if earlier.empty:
        return None
    return earlier.index[-1], float(earlier.iloc[-1])


def cumulative_return(levels: pd.Series, years: int, end: pd.Timestamp | None = None) -> float | None:
    """ R_cum = P_end / P_start - 1, in percent """
    levels = levels.dropna()
    end = levels.index[-1] if end is None else end
    start = start_price(levels, years, end)
    if start is None:
        return None
    return (float(levels[levels.index <= end].iloc[-1]) / start[1] - 1) * 100


def annualise(cumulative_pct: float, years: float) -> float:
    """ R_ann = (1 + R_cum)^(1/n) - 1, in percent """
    return ((1 + cumulative_pct / 100) ** (1 / years) - 1) * 100


def discrete_12m(levels: pd.Series, as_of: pd.Timestamp, windows: int = 5) -> dict[date, float | None]:
    """ Cumulative return for each 12-month window ending on as_of, as_of - 1y, ... (spec 4.1).
    A window whose start or end price is missing is None """
    out = {}
    for k in range(windows):
        end = as_of - pd.DateOffset(years=k)
        end_price = levels[levels.index <= end]
        start = levels[levels.index <= end - pd.DateOffset(years=1)]
        if end_price.empty or start.empty or pd.isna(end_price.iloc[-1]) or pd.isna(start.iloc[-1]):
            out[end.date()] = None
        else:
            out[end.date()] = (end_price.iloc[-1] / start.iloc[-1] - 1) * 100
    return dict(sorted(out.items()))


def calendar_year_returns(prices: pd.DataFrame, column: str, launch_date: date | None = None,
                          max_years: int | None = None) -> dict[str, float]:
    """ Spec 4.1: P_Dec31(y) / P_Dec31(y-1) - 1 in percent, where P_Dec31 is the last price on or before
    31 December. The current, incomplete year is labelled "YTD".
    With launch_date, only full years after launch count (the year-start price is on or after launch);
    max_years keeps the most recent years only """
    series = prices.set_index("date")[column].dropna()
    year_end = series.groupby(series.index.year).last()
    last_date = series.groupby(series.index.year).apply(lambda s: s.index.max())
    # A year is complete if the data reaches the last week of December (the last business day may be before the 31st)
    full = [y for y in year_end.index if last_date[y].month == 12 and last_date[y].day >= 24]
    if launch_date is not None:
        full_after = [y for y in full if y - 1 in full and last_date[y - 1] >= pd.Timestamp(launch_date)]
    else:
        full_after = [y for y in full if y - 1 in full]
    if max_years is not None:
        full_after = full_after[-max_years:]
    out = {str(y): (year_end[y] / year_end[y - 1] - 1) * 100 for y in full_after}
    current = int(series.index[-1].year)
    if current not in full and current - 1 in full:
        out["YTD"] = (series.iloc[-1] / year_end[current - 1] - 1) * 100
    return out


def since_launch(levels: pd.Series, launch_date: date) -> tuple[float, float | None, pd.Timestamp] | None:
    """ Since launch from the first price on or after launch (pre-launch prices are left out).
    Returns (cumulative %, annualised % or None if under a year, start date) """
    levels = levels[levels.index >= pd.Timestamp(launch_date)].dropna()
    if len(levels) < 2:
        return None
    start, end = levels.index[0], levels.index[-1]
    cumulative = (levels.iloc[-1] / levels.iloc[0] - 1) * 100
    years = (end - start).days / 365.25
    return cumulative, annualise(cumulative, years) if years >= 1 else None, start


# --- 4.2 Relative performance --------------------------------------------------------------------------------

def excess_return(fund_cum_pct: float, bench_cum_pct: float) -> float:
    """ Cumulative excess, in percentage points """
    return fund_cum_pct - bench_cum_pct


def tracking_difference(fund_ann_pct: float, bench_ann_pct: float) -> float:
    """ TD = R_ann_fund - R_ann_bench, in percentage points a year """
    return fund_ann_pct - bench_ann_pct


def tracking_difference_ex_cost(td_pp: float, ocf_pct: float) -> float:
    """ TD + OCF: near 0 means the gap is explained by charges """
    return td_pp + ocf_pct


# --- 4.3 Risk ------------------------------------------------------------------------------------------------

def volatility(returns: pd.Series, periods_per_year: int) -> float:
    """ sigma = sample stdev(r_t) * sqrt(periods a year), in percent """
    return float(returns.dropna().std(ddof=1) * np.sqrt(periods_per_year) * 100)


def max_drawdown(levels: pd.Series) -> float:
    """ MDD = min(P_t / max_{s<=t} P_s - 1), in percent """
    levels = levels.dropna()
    return float((levels / levels.cummax() - 1).min() * 100)


def sharpe_ratio(ann_return_pct: float, vol_pct: float, rf_pct: float = 0.0) -> float:
    return (ann_return_pct - rf_pct) / vol_pct


def _paired(fund: pd.Series, bench: pd.Series) -> pd.DataFrame:
    """ Returns where both fund and index have a value """
    return pd.concat({"f": fund, "b": bench}, axis=1).dropna()


def tracking_error(fund_returns: pd.Series, bench_returns: pd.Series, periods_per_year: int) -> float:
    """ TE = stdev(r_fund - r_bench) * sqrt(periods a year), in percent """
    both = _paired(fund_returns, bench_returns)
    return float((both["f"] - both["b"]).std(ddof=1) * np.sqrt(periods_per_year) * 100)


def information_ratio(fund_ann_pct: float, bench_ann_pct: float, te_pct: float) -> float:
    return (fund_ann_pct - bench_ann_pct) / te_pct


def beta(fund_returns: pd.Series, bench_returns: pd.Series) -> float:
    both = _paired(fund_returns, bench_returns)
    return float(both["f"].cov(both["b"]) / both["b"].var())


def r_squared(fund_returns: pd.Series, bench_returns: pd.Series) -> float:
    both = _paired(fund_returns, bench_returns)
    return float(both["f"].corr(both["b"]) ** 2)


def alpha(fund_ann_pct: float, bench_ann_pct: float, beta_value: float, rf_pct: float = 0.0) -> float:
    """ Simple annualised alpha: R_fund - [rf + beta * (R_bench - rf)], in percent """
    return fund_ann_pct - (rf_pct + beta_value * (bench_ann_pct - rf_pct))


def relative_volatility(fund_vol_pct: float, bench_vol_pct: float) -> float:
    return fund_vol_pct / bench_vol_pct


# --- 4.4 Consistency -------------------------------------------------------------------------------------------

def hit_rate_index(fund_12m: dict, bench_12m: dict, tolerance_pp: float) -> tuple[int, int]:
    """ Index fund: windows where abs(fund - index) <= tolerance. Returns (hits, windows assessed) """
    pairs = [(fund_12m[k], bench_12m[k]) for k in fund_12m
             if k in bench_12m and fund_12m[k] is not None and bench_12m[k] is not None]
    return sum(abs(f - b) <= tolerance_pp for f, b in pairs), len(pairs)


def hit_rate_target(fund_12m: dict, target_12m: dict) -> tuple[int, int]:
    """ Active fund: windows where the fund return >= its target. Returns (hits, windows assessed) """
    pairs = [(fund_12m[k], target_12m[k]) for k in fund_12m
             if k in target_12m and fund_12m[k] is not None and target_12m[k] is not None]
    return sum(f >= t for f, t in pairs), len(pairs)


# --- 4.5 Attribution by sector -------------------------------------------------------------------------------

def brinson(sectors: pd.DataFrame) -> pd.DataFrame:
    """ Brinson effects by sector. Columns: sector, w_f, w_b (weights as fractions), r_f, r_b (returns in %).
    Effects are in percentage points; the last row holds the totals """
    df = sectors.copy()
    total_bench = (df["w_b"] * df["r_b"]).sum()
    active = df["w_f"] - df["w_b"]
    df["allocation"] = active * (df["r_b"] - total_bench)
    df["selection"] = df["w_b"] * (df["r_f"] - df["r_b"])
    df["interaction"] = active * (df["r_f"] - df["r_b"])
    df["total"] = df["allocation"] + df["selection"] + df["interaction"]
    totals = {"sector": "Total", "w_f": df["w_f"].sum(), "w_b": df["w_b"].sum(),
              "r_f": (df["w_f"] * df["r_f"]).sum(), "r_b": total_bench,
              **{c: df[c].sum() for c in ("allocation", "selection", "interaction", "total")}}
    return pd.concat([df, pd.DataFrame([totals])], ignore_index=True)


# --- 4.6 Peer comparison ----------------------------------------------------------------------------------------

def peer_return_gap(peer_ann_pct: float, fund_ann_pct: float) -> float:
    """ R_ann_peer - R_ann_fund: positive means the peer did better (both net of fees, same basis) """
    return peer_ann_pct - fund_ann_pct


def fee_gap(fund_ocf_pct: float, peer_ocf_pct: float) -> float:
    """ OCF_fund - OCF_peer, in percentage points """
    return fund_ocf_pct - peer_ocf_pct


# --- Putting it together --------------------------------------------------------------------------------------

@dataclass
class CalcResult:
    """ Every calculated figure by name, what could not be calculated and why, and any flags """
    figures: dict[str, Figure] = field(default_factory=dict)
    not_available: dict[str, str] = field(default_factory=dict)
    flags: list[DataFlag] = field(default_factory=list)

    def value(self, name: str) -> float | None:
        figure = self.figures.get(name)
        return None if figure is None else figure.value


def _figure(value: float, unit: str, period: str, decimals: int, source: str = "calculated",
            basis: str | None = None) -> Figure:
    return Figure(value=round(value, decimals), exact=value, unit=unit, source=source, period=period, basis=basis)


def calculate(prices: pd.DataFrame, profile: FundProfile, thresholds: Thresholds,
              factsheet: FactsheetPerformance | None = None) -> CalcResult:
    """ All Section 4 figures that the price data supports.

    Returns (1/3/5y, discrete, calendar) use the whole price file; risk statistics and since-launch
    figures use post-launch prices only. Benchmark-relative risk needs an index price series; without
    one it is marked not available and the factsheet figures are reported instead (owner decision) """
    c = thresholds.calculator
    d = c.decimals_internal
    result = CalcResult()
    levels = prices.set_index("date")["nav"]
    index = prices.set_index("date")["index_level"] if "index_level" in prices.columns else None
    as_of = levels.dropna().index[-1]
    launch = pd.Timestamp(profile.launch_date)
    ppy = c.periods_per_year_daily if detect_frequency(prices["date"]) == "daily" else c.periods_per_year_monthly
    rf = c.risk_free_rate_pct if c.risk_free_rate_pct is not None else 0.0
    if c.risk_free_rate_pct is None:
        result.flags.append(DataFlag(check="risk_free_rate", level="info",
                                     message="No risk-free rate supplied: Sharpe ratio and alpha use 0%"))

    series = {"fund": levels} | ({"index": index} if index is not None else {})
    for name, lv in series.items():
        # 4.1 returns over 1, 3 and 5 years
        for n in PERIODS:
            cum = cumulative_return(lv, n, as_of)
            if cum is None:
                result.not_available[f"{name}.cum.{n}y"] = "not available: price history shorter than the period"
                continue
            result.figures[f"{name}.cum.{n}y"] = _figure(cum, "%", f"{n}y", d)
            result.figures[f"{name}.ann.{n}y"] = _figure(annualise(cum, n), "%", f"{n}y", d)
        for end, value in discrete_12m(lv, as_of, c.discrete_12m_windows).items():
            key = f"{name}.discrete_12m.{end.isoformat()}"
            if value is None:
                result.not_available[key] = "not available: start or end price missing"
            else:
                result.figures[key] = _figure(value, "%", f"12m to {end.isoformat()}", d)
        for year, value in calendar_year_returns(lv.reset_index().rename(columns={lv.name: "v"}), "v",
                                                 profile.launch_date, CALENDAR_YEARS_SHOWN).items():
            result.figures[f"{name}.calendar.{year}"] = _figure(value, "%", year, d)
        launched = since_launch(lv, profile.launch_date)
        if launched:
            cum, ann, start = launched
            period = f"since {start:%Y-%m-%d}"
            result.figures[f"{name}.since_launch.cum"] = _figure(cum, "%", period, d)
            if ann is not None:
                result.figures[f"{name}.since_launch.ann"] = _figure(ann, "%", period, d)

        # 4.3 risk over the horizon, and over 3 years to cross-check the factsheet; post-launch prices only
        for years in sorted({CROSS_CHECK_RISK_YEARS, profile.time_horizon_years}):
            start = start_price(lv, years, as_of)
            if start is None:
                result.not_available[f"{name}.vol.{years}y"] = "not available: price history shorter than the period"
                continue
            window = lv[(lv.index >= max(start[0], launch)) & (lv.index <= as_of)]
            vol = volatility(period_returns(window), ppy)
            result.figures[f"{name}.vol.{years}y"] = _figure(vol, "%", f"{years}y", d)
            result.figures[f"{name}.mdd.{years}y"] = _figure(max_drawdown(window), "%", f"{years}y", d)
            ann = annualise(cumulative_return(lv, years, as_of), years)
            result.figures[f"{name}.sharpe.{years}y"] = _figure(sharpe_ratio(ann, vol, rf), "ratio", f"{years}y", d)

    _relative(result, levels, index, profile, ppy, rf, as_of, launch, factsheet, d)
    return result


def _relative(result: CalcResult, levels: pd.Series, index: pd.Series | None, profile: FundProfile,
              ppy: int, rf: float, as_of: pd.Timestamp, launch: pd.Timestamp,
              factsheet: FactsheetPerformance | None, d: int) -> None:
    """ 4.2 and the benchmark-relative part of 4.3 """
    n = profile.time_horizon_years
    if index is None:
        for key in [f"relative.{k}.{n}y" for k in ("excess_cum", "td", "td_ex_cost", *RELATIVE_RISK)] + \
                   [f"relative.relative_vol.{n}y"]:
            result.not_available[key] = NO_INDEX
        # Report the factsheet's own figures instead, never an approximation (owner decision)
        risk = None
        if factsheet is not None:
            # PNAV figures are the fair comparison with a market-close index; an unlabelled set is used as it is
            risk = factsheet.risk("pnav") or (factsheet.risk_3y if factsheet.risk_3y and factsheet.risk_3y.basis is None
                                              else None)
        if risk is not None:
            for name in RELATIVE_RISK:
                value = getattr(risk, name)
                if value is not None:
                    result.figures[f"factsheet.{name}.3y"] = _figure(value, "%" if name in ("tracking_error", "alpha")
                                                                     else "ratio", "3y", d, "factsheet", risk.basis)
        return
    for k in PERIODS:
        f, b = result.value(f"fund.cum.{k}y"), result.value(f"index.cum.{k}y")
        if f is None or b is None:
            continue
        f_ann = annualise(cumulative_return(levels, k, as_of), k)
        b_ann = annualise(cumulative_return(index, k, as_of), k)
        td = tracking_difference(f_ann, b_ann)
        result.figures[f"relative.excess_cum.{k}y"] = _figure(excess_return(
            cumulative_return(levels, k, as_of), cumulative_return(index, k, as_of)), "pp", f"{k}y", d)
        result.figures[f"relative.td.{k}y"] = _figure(td, "pp", f"{k}y", d)
        result.figures[f"relative.td_ex_cost.{k}y"] = _figure(tracking_difference_ex_cost(td, profile.ocf_pct), "pp", f"{k}y", d)
    start = start_price(levels, n, as_of)
    if start is None:
        return
    in_window = (levels.index >= max(start[0], launch)) & (levels.index <= as_of)
    fr, br = period_returns(levels[in_window]), period_returns(index[in_window])
    f_ann = annualise(cumulative_return(levels, n, as_of), n)
    b_ann = annualise(cumulative_return(index, n, as_of), n)
    te = tracking_error(fr, br, ppy)
    b = beta(fr, br)
    if te > 0:
        result.figures[f"relative.info_ratio.{n}y"] = _figure(information_ratio(f_ann, b_ann, te), "ratio", f"{n}y", d)
    else:
        result.not_available[f"relative.info_ratio.{n}y"] = "not available: tracking error is zero"
    for name, value, unit in (("tracking_error", te, "%"), ("beta", b, "ratio"), ("r2", r_squared(fr, br), "ratio"),
                              ("alpha", alpha(f_ann, b_ann, b, rf), "%"),
                              ("relative_vol", relative_volatility(volatility(fr, ppy), volatility(br, ppy)), "ratio")):
        result.figures[f"relative.{name}.{n}y"] = _figure(value, unit, f"{n}y", d)
