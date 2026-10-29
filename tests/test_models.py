""" The input file shapes from spec Section 2: valid files load, mistakes are rejected """
import json
import pytest
from pydantic import ValidationError
from fund_performance.models import FundProfile, FactsheetPerformance, Peer, Figure, DataFlag
from conftest import FIXTURES, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_fund_profile_sample_loads_with_defaults():
    p = FundProfile.model_validate(load(FIXTURES / "fund_profile_sample.json"))
    assert p.objective_type == "index_tracker"
    assert p.asset_class == "equity"           # optional, defaults to equity
    assert p.transaction_cost_pct is None


@pytest.mark.parametrize("key,bad", [("objective_type", "tracker"), ("benchmark_role", "target_index"),
                                     ("pricing_point", "noon"), ("risk_indicator", 8), ("currency", "POUND")])
def test_fund_profile_rejects_values_outside_the_allowed_list(key, bad):
    data = load(FIXTURES / "fund_profile_sample.json") | {key: bad}
    with pytest.raises(ValidationError):
        FundProfile.model_validate(data)


def test_fund_profile_rejects_unknown_keys():
    data = load(FIXTURES / "fund_profile_sample.json") | {"ocf": 0.1}
    with pytest.raises(ValidationError):
        FundProfile.model_validate(data)


def test_factsheet_sample_reads_period_keys():
    f = FactsheetPerformance.model_validate(load(FIXTURES / "factsheet_performance_sample.json"))
    assert (f.series["fund_nav"].y1, f.series["fund_nav"].y3, f.series["fund_nav"].y5) == (10.0, 30.0, 50.0)
    assert f.risk_3y.tracking_error == 0.05 and f.risk_3y.sharpe_fund is None


def test_factsheet_rejects_a_bad_calendar_year():
    data = load(FIXTURES / "factsheet_performance_sample.json")
    data["calendar_years"]["index"]["YTD"] = 3.0
    with pytest.raises(ValidationError):
        FactsheetPerformance.model_validate(data)


def test_peer_sample_loads():
    peer = Peer.model_validate(load(FIXTURES / "peer_sample.json"))
    assert peer.ocf_pct == 0.05 and peer.returns.basis == "annualised" and peer.returns.y5 == 8.6


def test_figure_labels_ai_extracted_values():
    assert Figure(value=17.5, unit="%", source="ai_extracted").label == "please verify"
    assert Figure(value=17.5, unit="%", source="factsheet").label == ""
    with pytest.raises(ValidationError):
        Figure(value=17.5, unit="%", source="guess")


def test_data_flag_levels():
    flag = DataFlag(check="repeated_prices", level="warning", message="Suspicious repeated price",
                    dates=["2024-07-31", "2024-09-30"])
    assert [d.isoformat() for d in flag.dates] == ["2024-07-31", "2024-09-30"]
    with pytest.raises(ValidationError):
        DataFlag(check="x", level="fatal", message="m")


@requires_test1
def test_test1_factsheet_file_matches_the_spec():
    f = FactsheetPerformance.model_validate(load(TEST1_FACTSHEET))
    assert f.source == "factsheet" and f.entered_by == "manual"
    nav, pnav, index = f.series["fund_nav"], f.series["fund_pnav"], f.series["index"]
    assert (nav.y1, nav.y3, nav.y5) == (17.5, 69.0, 88.3)
    assert (pnav.y1, pnav.y3, pnav.y5) == (17.0, 69.0, 90.9)
    assert (index.y1, index.y3, index.y5) == (17.1, 69.5, 91.6)
    assert nav.pricing == "midday" and index.pricing == "market_close"
    assert (f.risk_3y.tracking_error, f.risk_3y.beta, f.risk_3y.r2) == (0.02, 1.00, 1.00)
    assert f.calendar_years["index"]["2022"] == -8.0


@requires_test1
def test_test1_profile_file_loads():
    p = FundProfile.model_validate(load(TEST1_PROFILE))
    assert p.isin == "GB00BJS8SH10" and p.ocf_pct == 0.06 and p.pricing_point == "midday"
    assert p.objective_type == "index_tracker" and p.time_horizon_years == 5
