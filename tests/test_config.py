""" config/thresholds.yaml loads, holds the spec's values, and rejects missing or misspelt keys """
import pytest
import yaml
from pydantic import ValidationError
from fund_performance.config import DEFAULT_PATH, load_thresholds


@pytest.fixture
def raw():
    with open(DEFAULT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_loads_and_is_marked_illustrative():
    t = load_thresholds()
    assert t.status == "illustrative"
    assert "illustrative" in t.note.lower()


def test_values_match_the_spec():
    t = load_thresholds()
    # Section 3.4
    assert t.data_checks.cross_check_tolerance_pp == 0.3
    assert t.data_checks.implausible_tracker_gap_pct == 1.0
    assert t.data_checks.max_gap_days_monthly == 35
    assert t.data_checks.max_gap_business_days_daily == 5
    assert t.data_checks.repeated_price_window_periods == 3
    # Owner decisions
    assert t.data_checks.currency_mismatch_calendar_year_pp == 0.5
    assert t.data_checks.timing_difference_extra_tolerance_pp == 0.20
    assert t.data_checks.repeated_price_factsheet_match_pp == 0.1
    assert t.performance_index.hit_rate_td_margin_over_ocf_pp == 0.10
    # Section 4
    assert (t.calculator.periods_per_year_monthly, t.calculator.periods_per_year_daily) == (12, 252)
    assert (t.calculator.decimals_internal, t.calculator.decimals_display) == (2, 1)
    # Section 6
    assert t.mandate_index.green_min_r2 == 0.98 and t.mandate_index.green_beta_range == (0.95, 1.05)
    assert t.mandate_index.amber_min_r2 == 0.95 and t.mandate_index.amber_beta_range == (0.90, 1.10)
    assert t.performance_index.green_td_margin_over_ocf_pp == 0.10 and t.performance_index.green_max_te_pct == 0.30
    assert t.performance_index.amber_td_margin_over_ocf_pp == 0.30 and t.performance_index.amber_max_te_pct == 1.00
    assert t.performance_active_target.red_below_excess_pct == -1.0 and t.performance_active_target.min_hit_rate == 3
    assert t.value.green_max_peer_outperformance_pp == 0.10 and t.value.amber_max_peer_outperformance_pp == 0.50
    assert t.fees_index.green_max_ocf_over_peer_pp == 0.05 and t.fees_index.amber_max_ocf_over_peer_pp == 0.20
    # Sections 1 and 8.5
    assert t.limits.max_web_searches == 3 and t.limits.max_analyst_rewrites == 1
    assert t.limits.max_evaluator_rewrites == 1


def test_no_risk_free_rate_means_zero_with_a_flag():
    assert load_thresholds().risk_free_rate_missing


def test_missing_key_is_rejected(raw, tmp_path):
    del raw["value"]["green_max_peer_outperformance_pp"]
    path = tmp_path / "t.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_thresholds(path)


def test_misspelt_key_is_rejected(raw, tmp_path):
    raw["fees_index"]["green_max_ocf_over_peer"] = raw["fees_index"].pop("green_max_ocf_over_peer_pp")
    path = tmp_path / "t.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_thresholds(path)
