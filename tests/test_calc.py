""" Calculator (spec 4): each formula with made-up numbers, then Test 1 from the real NAV CSV """
from datetime import date
import json
import numpy as np
import pandas as pd
import pytest
from fund_performance import calc
from fund_performance.config import load_thresholds
from fund_performance.io import read_json, read_prices
from fund_performance.models import FactsheetPerformance, FundProfile
from conftest import FIXTURES, TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1

T = load_thresholds()


def levels(values, start="2020-01-31"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="ME"), dtype=float)


def profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()) | changes)


# 4.1 Returns
def test_period_returns_never_fill_missing_prices():
    r = calc.period_returns(levels([100, 110, None, 121]))
    assert r.iloc[0] == pytest.approx(0.10) and r.iloc[1:].isna().all()


def test_cumulative_and_annualised_returns():
    lv = levels(np.linspace(100, 200, 61))                    # 5 years of month-ends
    assert calc.cumulative_return(lv, 5) == pytest.approx(100.0)
    assert calc.annualise(100.0, 5) == pytest.approx((2 ** 0.2 - 1) * 100)
    assert calc.cumulative_return(lv, 6) is None             # not enough history


def test_start_price_is_the_last_on_or_before():
    lv = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-09-29", "2021-10-29"]))
    assert calc.start_price(lv, 1, pd.Timestamp("2021-09-30")) == (pd.Timestamp("2020-09-29"), 1.0)


def test_discrete_12m_windows_and_missing_prices():
    lv = levels([100 + i for i in range(37)], start="2023-09-30")
    out = calc.discrete_12m(lv, pd.Timestamp("2026-09-30"), windows=3)
    assert list(out) == [date(2024, 9, 30), date(2025, 9, 30), date(2026, 9, 30)]
    assert out[date(2026, 9, 30)] == pytest.approx((136 / 124 - 1) * 100)
    lv[pd.Timestamp("2025-09-30")] = np.nan
    out = calc.discrete_12m(lv, pd.Timestamp("2026-09-30"), windows=3)
    assert out[date(2025, 9, 30)] is None and out[date(2026, 9, 30)] is None


def test_calendar_years_and_ytd():
    prices = pd.DataFrame({"date": pd.to_datetime(["2022-12-31", "2023-06-30", "2023-12-31", "2024-12-31", "2025-03-31"]),
                           "nav": [100.0, 105.0, 110.0, 121.0, 125.0]})
    years = calc.calendar_year_returns(prices, "nav")
    assert years == {"2023": pytest.approx(10.0), "2024": pytest.approx(10.0), "YTD": pytest.approx((125 / 121 - 1) * 100)}


def test_since_launch_leaves_out_pre_launch_prices():
    lv = levels([50, 60, 100, 110, 121], start="2020-01-31")
    cum, ann, start = calc.since_launch(lv, date(2020, 3, 3))
    assert start == pd.Timestamp("2020-03-31") and cum == pytest.approx(21.0) and ann is None   # under a year
    lv = levels([1.0] + [100 + i for i in range(25)])
    cum, ann, start = calc.since_launch(lv, date(2020, 2, 1))
    assert cum == pytest.approx(24.0) and ann == pytest.approx(calc.annualise(24.0, (lv.index[-1] - start).days / 365.25))


# 4.2 Relative performance
def test_relative_performance():
    assert calc.excess_return(88.3, 91.6) == pytest.approx(-3.3)
    assert calc.tracking_difference(13.8, 13.9) == pytest.approx(-0.1)
    assert calc.tracking_difference_ex_cost(-0.1, 0.06) == pytest.approx(-0.04)


# 4.3 Risk
def test_volatility_and_drawdown():
    assert calc.volatility(pd.Series([0.01, -0.01, 0.01, -0.01]), 12) == pytest.approx(4.0)
    assert calc.max_drawdown(pd.Series([100, 120, 90, 130.0])) == pytest.approx(-25.0)
    assert calc.sharpe_ratio(10.0, 20.0) == 0.5 and calc.sharpe_ratio(10.0, 20.0, rf_pct=2.0) == 0.4


def test_relative_risk_measures():
    bench = pd.Series([0.02, -0.01, 0.03, 0.01, -0.02])
    assert calc.tracking_error(bench, bench, 12) == pytest.approx(0.0)
    assert calc.beta(2 * bench, bench) == pytest.approx(2.0)
    assert calc.r_squared(2 * bench, bench) == pytest.approx(1.0)
    assert calc.information_ratio(8.0, 7.0, 2.0) == pytest.approx(0.5)
    assert calc.alpha(12.0, 10.0, 1.1, rf_pct=2.0) == pytest.approx(12.0 - (2.0 + 1.1 * 8.0))
    assert calc.relative_volatility(12.14, 12.15) == pytest.approx(0.99918, abs=1e-5)


# 4.4 Consistency
def test_hit_rates():
    fund = {1: 10.0, 2: 5.0, 3: None, 4: 8.0}
    bench = {1: 10.05, 2: 5.5, 3: 4.0, 4: 8.0}
    assert calc.hit_rate_index(fund, bench, tolerance_pp=0.16) == (2, 3)
    assert calc.hit_rate_target(fund, bench) == (1, 3)


# 4.5 Attribution
def test_brinson_effects_add_up_to_the_active_return():
    sectors = pd.DataFrame({"sector": ["A", "B"], "w_f": [0.6, 0.4], "w_b": [0.5, 0.5],
                            "r_f": [10.0, 2.0], "r_b": [8.0, 4.0]})
    total = calc.brinson(sectors).iloc[-1]
    assert (total["allocation"], total["selection"], total["interaction"]) == pytest.approx((0.4, 0.0, 0.4))
    assert total["total"] == pytest.approx(total["r_f"] - total["r_b"]) == pytest.approx(0.8)


# 4.6 Peer comparison
def test_peer_and_fee_gaps():
    assert calc.peer_return_gap(13.48, 13.30) == pytest.approx(0.18)
    assert calc.fee_gap(0.06, 0.03) == pytest.approx(0.03)


# calculate(): the whole set of figures
def test_calculate_with_an_index_series():
    rng = np.random.default_rng(1)
    index = 100 * np.cumprod(1 + np.r_[0, rng.normal(0.008, 0.04, 72)])
    fund = index * (1 - 0.001) ** (np.arange(73) / 12)        # 0.10% a year drag, no noise
    prices = pd.DataFrame({"date": pd.date_range("2020-09-30", periods=73, freq="ME"), "nav": fund, "index_level": index})
    r = calc.calculate(prices, profile(launch_date="2020-01-01", ocf_pct=0.10), T)
    assert r.value("relative.td.5y") == pytest.approx(-0.10, abs=0.01)
    assert r.value("relative.td_ex_cost.5y") == pytest.approx(0.0, abs=0.01)
    assert r.value("relative.beta.5y") == pytest.approx(1.0, abs=0.01) and r.value("relative.r2.5y") == pytest.approx(1.0)
    assert r.value("relative.tracking_error.5y") < 0.05
    assert all(f.source == "calculated" for f in r.figures.values())
    assert r.not_available == {}


def test_calculate_without_an_index_series_uses_the_factsheet_and_never_approximates():
    prices = pd.DataFrame({"date": pd.date_range("2020-09-30", periods=73, freq="ME"), "nav": np.linspace(100, 160, 73)})
    fs = FactsheetPerformance.model_validate(json.loads((FIXTURES / "factsheet_performance_sample.json").read_text()))
    r = calc.calculate(prices, profile(launch_date="2020-01-01"), T, fs)
    for name in ("tracking_error", "beta", "r2", "info_ratio", "alpha"):
        assert r.not_available[f"relative.{name}.5y"] == "not available: no index price series"
        assert f"relative.{name}.5y" not in r.figures
    assert r.figures["factsheet.tracking_error.3y"].source == "factsheet" and r.value("factsheet.r2.3y") == 0.99


def test_no_risk_free_rate_is_flagged():
    prices = pd.DataFrame({"date": pd.date_range("2020-09-30", periods=73, freq="ME"), "nav": np.linspace(100, 160, 73)})
    r = calc.calculate(prices, profile(launch_date="2020-01-01"), T)
    assert [f.check for f in r.flags] == ["risk_free_rate"] and "fund.sharpe.5y" in r.figures


def test_figures_are_stored_to_2dp_and_shown_rounded_once():
    figure = calc._figure(10.549879, "%", "2017", 2)
    assert figure.value == 10.55 and figure.display() == "10.5%"      # not 10.55 -> 10.6


# Test 1: Fidelity Index US Fund P Acc, from the real NAV CSV
@pytest.fixture(scope="module")
def test1():
    prices = read_prices(TEST1_CSV).prices
    profile1, factsheet1 = read_json(TEST1_PROFILE), read_json(TEST1_FACTSHEET)
    return prices, profile1, factsheet1, calc.calculate(prices, profile1, T, factsheet1)


@requires_test1
def test_test1_nav_returns_match_the_factsheet(test1):
    _, _, _, r = test1
    shown = {k: r.figures[k].display() for k in ("fund.cum.1y", "fund.cum.3y", "fund.cum.5y", "fund.ann.3y", "fund.ann.5y")}
    assert shown == {"fund.cum.1y": "17.5%", "fund.cum.3y": "69.0%", "fund.cum.5y": "88.3%",
                     "fund.ann.3y": "19.1%", "fund.ann.5y": "13.5%"}


@requires_test1
def test_test1_fair_comparison_annualised_from_the_factsheet(test1):
    _, _, fs, _ = test1
    assert round(calc.annualise(fs.series["fund_pnav"].y5, 5), 1) == 13.8
    assert round(calc.annualise(fs.series["index"].y5, 5), 1) == 13.9        # "about 13.9" (13.89)


@requires_test1
def test_test1_volatility_and_drawdown(test1):
    _, _, _, r = test1
    assert r.figures["fund.vol.5y"].display() == "13.7%"
    assert r.figures["fund.mdd.5y"].display() == "-15.1%"


@requires_test1
def test_test1_discrete_and_calendar_returns_match_the_factsheet(test1):
    _, _, fs, r = test1
    for end, value in fs.discrete_12m["fund_nav"].items():
        assert r.figures[f"fund.discrete_12m.{end.isoformat()}"].display() == f"{value:.1f}%"
    for year, value in fs.calendar_years["fund_nav"].items():
        assert r.figures[f"fund.calendar.{year}"].display() == f"{value:.1f}%"


@requires_test1
def test_test1_since_launch_leaves_out_pre_launch_prices(test1):
    _, _, fs, r = test1
    figure = r.figures["fund.since_launch.ann"]
    assert figure.period == "since 2014-03-31"
    assert figure.display() == f"{fs.series_annualised['fund_nav'].since_launch:.1f}%"      # 15.7%


@requires_test1
def test_test1_relative_risk_comes_from_the_factsheet(test1):
    _, _, _, r = test1
    expected = {"tracking_error": 0.02, "beta": 1.00, "r2": 1.00, "info_ratio": -5.27, "alpha": -0.09}
    for name, value in expected.items():
        figure = r.figures[f"factsheet.{name}.3y"]
        assert (figure.value, figure.source, figure.basis) == (value, "factsheet", "pnav")
        assert r.not_available[f"relative.{name}.5y"] == "not available: no index price series"
    assert [f.check for f in r.flags] == ["risk_free_rate"]


@requires_test1
def test_test1_effect_of_leaving_out_the_2024_09_30_price(test1):
    """ The 2024-07-31/2024-09-30 repeated price is kept. This shows what changes if 2024-09-30 is treated
    as missing (spec 3.4: returns next to a missing price are left out, never filled in) """
    prices, profile1, fs, kept = test1
    without = prices.copy()
    without.loc[without["date"] == "2024-09-30", "nav"] = np.nan
    dropped = calc.calculate(without, profile1, T, fs)

    changes = []
    for name in sorted(set(kept.figures) | set(dropped.figures)):
        a, b = kept.figures.get(name), dropped.figures.get(name)
        shown_a = a.display() if a else "not available"
        shown_b = b.display() if b else "not available"
        if shown_a != shown_b:
            changes.append((name, shown_a, shown_b))
    exact = (kept.figures["fund.vol.5y"].exact, dropped.figures["fund.vol.5y"].exact)
    print("\n2024-09-30 price left out: figures whose displayed value changes")
    print(f"  {'figure':32s} {'kept':>14s} {'left out':>14s}")
    for name, a, b in changes:
        print(f"  {name:32s} {a:>14s} {b:>14s}")
    print(f"  5-year volatility exactly: {exact[0]:.2f}% kept vs {exact[1]:.2f}% left out "
          f"({exact[1] - exact[0]:+.2f} pp)")

    assert [c[0] for c in changes] == ["fund.discrete_12m.2024-09-30", "fund.discrete_12m.2025-09-30",
                                       "fund.sharpe.5y", "fund.vol.5y"]
    assert (kept.figures["fund.vol.5y"].display(), dropped.figures["fund.vol.5y"].display()) == ("13.7%", "13.9%")
