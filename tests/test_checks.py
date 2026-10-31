""" Data quality checks (spec 3.4), each with made-up data, then the Test 1 expected flags """
from datetime import date
import json
import pandas as pd
from fund_performance import checks
from fund_performance.config import load_thresholds
from fund_performance.io import read_json, read_prices
from fund_performance.models import FactsheetPerformance, FundProfile, SeriesReturns
from conftest import FIXTURES, TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1

T = load_thresholds()


def test_repeated_price_scope_uses_actual_five_year_start_and_keeps_warning():
    from fund_performance.models import DataFlag
    prices = pd.DataFrame({"date": pd.to_datetime(["2013-06-30", "2013-08-31", "2021-09-30", "2026-09-30"]),
                           "nav": [1, 1, 2, 3]})
    flag = DataFlag(check="repeated_prices", level="warning", message="Repeated prices on 2013 dates",
                    dates=[date(2013, 6, 30), date(2013, 8, 31)])
    scoped = checks.repeated_price_scope(flag, prices)
    assert scoped.level == "warning" and "outside the five-year price window 2021-09-30" in scoped.message
    assert "longer historical calculations and data checks remains to be reviewed" in scoped.message
    sparse = prices.iloc[[0, 1, 3]]
    assert "at least one flagged date falls within" in checks.repeated_price_scope(flag, sparse).message


def monthly(navs, start="2024-01-31", index=None):
    p = pd.DataFrame({"date": pd.date_range(start, periods=len(navs), freq="ME"), "nav": navs})
    if index is not None:
        p["index_level"] = index
    return p


def profile(**changes):
    data = json.loads((FIXTURES / "fund_profile_sample.json").read_text()) | changes
    return FundProfile.model_validate(data)


def factsheet(**changes):
    data = json.loads((FIXTURES / "factsheet_performance_sample.json").read_text()) | changes
    return FactsheetPerformance.model_validate(data)


# Currency match
def test_stated_currencies_that_differ_are_blocking():
    [flag] = checks.currency_match("EUR", "usd")
    assert flag.level == "blocking" and flag.message.startswith("CHECK DATA: currency mismatch")
    assert checks.currency_match("GBP", "GBP") == [] and checks.currency_match("GBP", None) == []


def test_index_in_another_currency_is_caught_against_the_factsheet():
    # File index: 2022 return -18.5% vs factsheet -13.2% (the Test 2 trap, made-up levels)
    prices = pd.DataFrame({"date": pd.to_datetime(["2021-12-31", "2022-12-31", "2023-12-31"]),
                           "nav": [1.0, 1.0, 1.0], "index_level": [100.0, 81.5, 101.0]})
    fs = factsheet(calendar_years={"index": {"2022": -13.2, "2023": 23.9}})
    [flag] = checks.index_currency_vs_factsheet(prices, fs, T.data_checks.currency_mismatch_calendar_year_pp)
    assert flag.level == "blocking" and "2022: file -18.5% vs factsheet -13.2%" in flag.message
    assert "2023" not in flag.message                       # 23.9 vs 23.9 is within 0.5 pp


def test_rounding_differences_within_half_a_point_are_not_flagged():
    prices = pd.DataFrame({"date": pd.to_datetime(["2023-12-31", "2024-12-31"]), "nav": [1.0, 1.0],
                           "index_level": [100.0, 112.4]})
    fs = factsheet(calendar_years={"index": {"2024": 12.0}})
    assert checks.index_currency_vs_factsheet(prices, fs, 0.5) == []


# End-date alignment
def test_end_dates_are_aligned_to_the_common_date():
    prices = monthly([1.0, 1.1, 1.2], index=[10.0, 11.0, None])
    kept, [flag] = checks.align_end_dates(prices)
    assert kept["date"].iloc[-1] == pd.Timestamp("2024-02-29") and len(kept) == 2
    assert flag.level == "info" and flag.dates == [date(2024, 2, 29)]


# Pricing point
def test_midday_fund_uses_pnav_when_available():
    fs = factsheet(series={"fund_nav": {"1y": 1, "basis": "cumulative", "pricing": "midday"},
                           "fund_pnav": {"1y": 1, "basis": "cumulative", "pricing": "market_close"},
                           "index": {"1y": 1, "basis": "cumulative", "pricing": "market_close"}})
    basis = checks.pricing_point(profile(pricing_point="midday"), fs, 0.20)
    assert basis.fund_series == "fund_pnav" and basis.extra_tolerance_pp == 0 and basis.flags[0].level == "info"


def test_midday_fund_without_pnav_widens_the_tolerance():
    fs = factsheet(series={"fund_nav": {"1y": 1, "basis": "cumulative", "pricing": "midday"},
                           "index": {"1y": 1, "basis": "cumulative", "pricing": "market_close"}})
    basis = checks.pricing_point(profile(pricing_point="midday"), fs, 0.20)
    assert basis.fund_series == "fund_nav" and basis.extra_tolerance_pp == 0.20
    assert basis.flags[0].level == "warning" and "Timing difference" in basis.flags[0].message


def test_same_pricing_point_needs_no_flag():
    basis = checks.pricing_point(profile(pricing_point="market_close"), factsheet(), 0.20)
    assert basis.fund_series == "fund_nav" and basis.flags == []


# Missing values and gaps
def test_missing_values_list_their_dates():
    flags = checks.missing_values(monthly([1.0, None, 1.2], index=[10.0, 11.0, None]))
    assert [(f.message.split(" value")[0], f.dates) for f in flags] == [
        ("1 missing NAV", [date(2024, 2, 29)]), ("1 missing index", [date(2024, 3, 31)])]


def test_monthly_gap_over_35_days():
    prices = pd.DataFrame({"date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-04-30", "2024-05-31"]),
                           "nav": [1.0, 1.1, 1.2, 1.3]})
    [flag] = checks.gaps(prices, 35, 5)
    assert flag.dates == [date(2024, 4, 30)]
    assert checks.gaps(monthly([1.0, 1.1, 1.2]), 35, 5) == []


def test_daily_gap_over_5_business_days():
    days = list(pd.bdate_range("2024-06-03", periods=10)) + [pd.Timestamp("2024-06-25")]
    prices = pd.DataFrame({"date": days, "nav": range(len(days))})
    [flag] = checks.gaps(prices, 35, 5)
    assert flag.dates == [date(2024, 6, 25)]
    ok = pd.DataFrame({"date": list(pd.bdate_range("2024-06-03", periods=10)) + [pd.Timestamp("2024-06-21")],
                       "nav": range(11)})
    assert checks.gaps(ok, 35, 5) == []                      # 14 Jun to 21 Jun is 5 business days


# Pre-launch prices
def test_prices_before_launch_are_info_and_left_out():
    prices = monthly([1.0, 1.1, 1.2, 1.3])
    [flag] = checks.pre_launch(prices, date(2024, 3, 3))
    assert flag.level == "info" and "pre-launch (likely simulated)" in flag.message
    assert flag.dates == [date(2024, 1, 31), date(2024, 2, 29)]
    assert checks.post_launch(prices, date(2024, 3, 3))["date"].iloc[0] == pd.Timestamp("2024-03-31")


# Repeated prices
def test_repeated_prices_within_three_periods():
    # 1.0 repeats 3 periods later and 1.3 repeats 3 periods later: both are flagged
    flags = checks.repeated_prices(monthly([1.0, 1.1, 1.2, 1.0, 1.3, 1.4, 1.5, 1.3]), window=3)
    assert [f.dates for f in flags] == [[date(2024, 1, 31), date(2024, 4, 30)], [date(2024, 5, 31), date(2024, 8, 31)]]
    assert all(f.level == "warning" for f in flags)


def test_repeated_price_four_periods_apart_is_not_flagged():
    assert checks.repeated_prices(monthly([1.0, 1.1, 1.2, 1.3, 1.0]), window=3) == []


def test_repeated_prices_before_launch_are_info():
    [flag] = checks.repeated_prices(monthly([1.0, 1.1, 1.0, 1.2]), window=3, launch_date=date(2024, 6, 1))
    assert flag.level == "info" and "pre-launch" in flag.message


def test_repeated_prices_only_for_equity_funds():
    assert checks.repeated_prices(monthly([1.0, 1.0]), window=3, asset_class="bond") == []


# History length
def test_short_history():
    short, [flag] = checks.history_length(monthly([1.0] * 25), 5)
    assert short and "24 months" in flag.message
    assert checks.history_length(monthly([1.0] * 61), 5) == (False, [])


# Cross-check and implausible tracker gap
def test_cross_check_tolerance():
    nav = SeriesReturns.model_validate({"1y": 17.5, "3y": 69.0, "5y": 88.3, "basis": "cumulative"})
    flags = checks.cross_check({"1y": 17.84, "3y": 69.25, "5y": 88.3}, nav, 0.3)
    assert len(flags) == 1 and flags[0].message.startswith("1y") and "factsheet figure is used" in flags[0].message


def test_implausible_tracker_gap():
    [flag] = checks.implausible_tracker_gap("index_tracker", True, -1.2, 1.0)
    assert flag.level == "blocking" and flag.message.startswith("CHECK DATA")
    assert checks.implausible_tracker_gap("index_tracker", False, -1.2, 1.0) == []   # factsheet-based
    assert checks.implausible_tracker_gap("active_target", True, -1.2, 1.0) == []
    assert checks.implausible_tracker_gap("index_tracker", True, -0.8, 1.0) == []


# Test 1 (real files, skipped when missing)
@requires_test1
def test_test1_expected_flags():
    result = checks.check_prices(read_prices(TEST1_CSV), read_json(TEST1_PROFILE), T, read_json(TEST1_FACTSHEET))
    found = [(f.check, f.level, [d.isoformat() for d in f.dates]) for f in result.flags if f.check == "repeated_prices"]
    assert found == [("repeated_prices", "info", ["2013-06-30", "2013-08-31"]),
                     ("repeated_prices", "info", ["2013-12-31", "2014-02-28"]),
                     ("repeated_prices", "warning", ["2024-07-31", "2024-09-30"])]
    [pre] = [f for f in result.flags if f.check == "pre_launch"]
    assert pre.level == "info" and len(pre.dates) == 16
    assert (pre.dates[0], pre.dates[-1]) == (date(2012, 11, 30), date(2014, 2, 28))
    assert result.comparison.fund_series == "fund_pnav"
    assert not result.short_history and result.blocking == []
    assert {f.check for f in result.flags} == {"pricing_point", "pre_launch", "repeated_prices"}
