""" Factsheet precedence and cross-check (build step 4): made-up cases, then Test 1 """
from datetime import date
import json
import numpy as np
import pandas as pd
import pytest
from fund_performance.calc import calculate
from fund_performance.checks import check_prices, ComparisonBasis
from fund_performance.config import load_thresholds
from fund_performance.io import read_json, read_prices
from fund_performance.models import DataFlag, FactsheetPerformance, FundProfile
from fund_performance.precedence import CONSISTENT, apply_precedence
from conftest import FIXTURES, TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1

T = load_thresholds()


def profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text())
                                      | {"launch_date": "2018-01-02"} | changes)


def prices(n=73, growth=0.008, index=False, index_drag=0.0, seed=3):
    """ Made-up month-end prices to 30 Sep 2026; optional index series """
    rng = np.random.default_rng(seed)
    r = np.r_[0, rng.normal(growth, 0.03, n - 1)]
    nav = 100 * np.cumprod(1 + r)
    df = pd.DataFrame({"date": pd.date_range(end="2026-09-30", periods=n, freq="ME"), "nav": nav})
    if index:
        df["index_level"] = nav * (1 + index_drag) ** (np.arange(n) / 12)
    return df


def factsheet_from(calc_result, shift=0.0, **extra):
    """ A made-up factsheet whose NAV returns equal the calculated ones (plus a shift) """
    cum = {f"{n}y": round(calc_result.figures[f"fund.cum.{n}y"].exact + shift, 1) for n in (1, 3, 5)}
    data = {"as_of_date": "2026-09-30", "currency": "GBP", "source": "factsheet", "entered_by": "manual",
            "series": {"fund_nav": cum | {"basis": "cumulative", "pricing": "market_close"}}} | extra
    return FactsheetPerformance.model_validate(data)


def run(df, prof, fs=None, comparison=None, flags=None, **kw):
    calc = calculate(df, prof, T, fs)
    return calc, apply_precedence(calc, flags or [], prof, T, fs, comparison, **kw)


def test_factsheet_figures_win_and_calculated_fill_gaps():
    df, prof = prices(), profile()
    calc = calculate(df, prof, T)
    fs = factsheet_from(calc, shift=0.2)                        # within 0.3 pp: no flag
    _, rep = run(df, prof, fs)
    assert rep.figures["fund_nav.cum.5y"].source == "factsheet"
    assert rep.figures["fund_nav.cum.5y"].value == round(calc.figures["fund.cum.5y"].exact + 0.2, 1)
    assert rep.figures["fund_nav.ann.5y"].source == "calculated"   # derived from the factsheet cumulative
    assert rep.figures["fund_nav.vol.5y"].source == "calculated"   # no factsheet figure: calculated is used
    assert not any(f.check == "cross_check" for f in rep.flags)
    assert sum(line.startswith("Cross-check") for line in rep.log) == 3


def test_cross_check_flags_a_gap_above_0_3_pp_and_the_factsheet_wins():
    df, prof = prices(), profile()
    fs = factsheet_from(calculate(df, prof, T), shift=0.5)
    _, rep = run(df, prof, fs)
    flags = [f for f in rep.flags if f.check == "cross_check"]
    assert len(flags) == 3 and all("factsheet figure is used" in f.message for f in flags)
    assert rep.figures["fund_nav.cum.1y"].source == "factsheet"


def test_without_a_factsheet_everything_is_calculated():
    _, rep = run(prices(index=True), profile())
    assert rep.figures["fund_nav.cum.5y"].source == "calculated" and rep.figures["index.cum.5y"].source == "calculated"
    assert "comparison.td.5y" in rep.figures


def test_index_fund_on_price_data_only_with_a_large_gap_is_check_data():
    _, rep = run(prices(index=True, index_drag=0.015), profile(objective_type="index_tracker"))
    [flag] = [f for f in rep.flags if f.check == "implausible_tracker_gap"]
    assert flag.level == "blocking" and flag.message.startswith("CHECK DATA")


def test_a_blocked_index_currency_means_price_file_index_is_not_used():
    _, rep = run(prices(index=True), profile(), currency_blocked=True)
    assert not any(k.startswith("index.") for k in rep.figures)
    assert "Price-file index not used: currency mismatch" in rep.log


def _repeated_flag(d1, d2):
    return DataFlag(check="repeated_prices", level="warning", message="Suspicious repeated price",
                    dates=[d1, d2])


def test_repeated_price_consistent_with_factsheet_becomes_info():
    df, prof = prices(), profile()
    calc = calculate(df, prof, T)
    windows = {k.rsplit(".", 1)[1]: round(f.exact, 1) for k, f in calc.figures.items() if ".discrete_12m." in k}
    fs = factsheet_from(calc, discrete_12m={"fund_nav": windows})
    _, rep = run(df, prof, fs, flags=[_repeated_flag(date(2024, 7, 31), date(2024, 9, 30))])
    [flag] = [f for f in rep.flags if f.check == "repeated_prices"]
    assert flag.level == "info" and CONSISTENT in flag.message
    assert "12 months to 2024-09-30" in flag.message and "12 months to 2025-09-30" in flag.message


def test_repeated_price_not_consistent_stays_a_warning():
    df, prof = prices(), profile()
    calc = calculate(df, prof, T)
    windows = {k.rsplit(".", 1)[1]: round(f.exact, 1) for k, f in calc.figures.items() if ".discrete_12m." in k}
    windows["2025-09-30"] += 0.2                               # one window off by more than 0.1 pp
    fs = factsheet_from(calc, discrete_12m={"fund_nav": windows})
    _, rep = run(df, prof, fs, flags=[_repeated_flag(date(2024, 7, 31), date(2024, 9, 30))])
    [flag] = [f for f in rep.flags if f.check == "repeated_prices"]
    assert flag.level == "warning" and "does not match the factsheet" in flag.message


def test_repeated_price_without_a_covering_window_stays_a_warning():
    df, prof = prices(), profile()
    fs = factsheet_from(calculate(df, prof, T))                 # no discrete 12-month figures
    _, rep = run(df, prof, fs, flags=[_repeated_flag(date(2024, 7, 31), date(2024, 9, 30))])
    [flag] = [f for f in rep.flags if f.check == "repeated_prices"]
    assert flag.level == "warning" and "no factsheet 12-month figure" in flag.message


def test_comparison_uses_the_chosen_series_and_cost_adjusts():
    fs = FactsheetPerformance.model_validate({
        "as_of_date": "2026-09-30", "currency": "GBP", "source": "factsheet",
        "series": {"fund_nav": {"5y": 88.3, "basis": "cumulative", "pricing": "midday"},
                   "fund_pnav": {"5y": 90.9, "basis": "cumulative", "pricing": "market_close"},
                   "index": {"5y": 91.6, "basis": "cumulative", "pricing": "market_close"}}})
    _, rep = run(prices(), profile(ocf_pct=0.06), fs, comparison=ComparisonBasis("fund_pnav"))
    assert rep.figures["comparison.excess_cum.5y"].exact == pytest.approx(-0.7)        # not -3.3 (midday NAV)
    td = rep.figures["comparison.td.5y"].exact
    assert td == pytest.approx(13.8 - 13.9, abs=0.02)
    assert rep.figures["comparison.td_ex_cost.5y"].exact == pytest.approx(td + 0.06)


# Test 1
@pytest.fixture(scope="module")
def test1():
    prof, fs = read_json(TEST1_PROFILE), read_json(TEST1_FACTSHEET)
    checked = check_prices(read_prices(TEST1_CSV), prof, T, fs)
    calc = calculate(checked.prices, prof, T, fs)
    return apply_precedence(calc, checked.flags, prof, T, fs, checked.comparison)


@requires_test1
def test_test1_reports_factsheet_figures(test1):
    shown = {k: (test1.figures[k].display(), test1.figures[k].source) for k in
             ("fund_nav.cum.1y", "fund_nav.cum.3y", "fund_nav.cum.5y", "fund_nav.ann.5y",
              "fund_pnav.cum.5y", "index.cum.5y", "fund_pnav.ann.5y", "index.ann.5y")}
    assert shown == {"fund_nav.cum.1y": ("17.5%", "factsheet"), "fund_nav.cum.3y": ("69.0%", "factsheet"),
                     "fund_nav.cum.5y": ("88.3%", "factsheet"), "fund_nav.ann.5y": ("13.5%", "factsheet"),
                     "fund_pnav.cum.5y": ("90.9%", "factsheet"), "index.cum.5y": ("91.6%", "factsheet"),
                     "fund_pnav.ann.5y": ("13.8%", "factsheet"), "index.ann.5y": ("13.9%", "factsheet")}


@requires_test1
def test_test1_fair_comparison_is_pnav_not_midday_nav(test1):
    assert test1.figures["comparison.excess_cum.5y"].basis == "fund_pnav"
    assert test1.figures["comparison.excess_cum.5y"].exact == pytest.approx(90.9 - 91.6)   # -0.7, not -3.3
    assert test1.figures["comparison.td.5y"].exact == pytest.approx(-0.1)
    assert test1.figures["comparison.td_ex_cost.5y"].exact == pytest.approx(-0.04)
    assert test1.figures["comparison.hit_rate"].display() == "5 of 5"


@requires_test1
def test_test1_cross_check_passes(test1):
    assert not any(f.check == "cross_check" for f in test1.flags)
    assert "Cross-check 5y NAV return: calculated 88.33% vs factsheet 88.3% (difference +0.03 pp)" in test1.log
    assert "Cross-check 3y volatility (NAV): calculated 13.92% vs factsheet 13.92%" in test1.log


@requires_test1
def test_test1_2024_repeated_price_is_info_after_the_factsheet_check(test1):
    repeated = [(f.level, [d.isoformat() for d in f.dates], CONSISTENT in f.message)
                for f in test1.flags if f.check == "repeated_prices"]
    assert repeated == [("info", ["2013-06-30", "2013-08-31"], False),
                        ("info", ["2013-12-31", "2014-02-28"], False),
                        ("info", ["2024-07-31", "2024-09-30"], True)]
    assert not any(f.level in ("warning", "blocking") for f in test1.flags)


@requires_test1
def test_test1_since_launch_uses_the_factsheet_and_logs_why(test1):
    assert test1.figures["fund_nav.since_launch.cum"].display() == "525.8%"
    assert test1.figures["fund_nav.since_launch.cum"].source == "factsheet"
    [line] = [l for l in test1.log if l.startswith("Since-launch")]
    assert "515.8%" in line and "no launch-day price" in line


@requires_test1
def test_test1_risk_sets_are_kept_apart(test1):
    assert test1.figures["risk.pnav.tracking_error.3y"].value == 0.02
    assert test1.figures["risk.pnav.fund_vol.3y"].value == 12.14
    assert test1.figures["risk.nav.fund_vol.3y"].value == 13.92
    assert test1.figures["risk.pnav.fund_vol.3y"].basis == "pnav" and test1.figures["risk.nav.fund_vol.3y"].basis == "nav"


@requires_test1
def test_test1_calendar_years_from_the_factsheet_last_10(test1):
    years = sorted(k.rsplit(".", 1)[1] for k in test1.figures if k.startswith("fund_nav.calendar.") and k[-1].isdigit())
    assert years == [str(y) for y in range(2016, 2026)]
    assert all(test1.figures[f"fund_nav.calendar.{y}"].source == "factsheet" for y in years)
