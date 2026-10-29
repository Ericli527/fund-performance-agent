""" Loads config/thresholds.yaml and checks it has every threshold the spec needs """
from pathlib import Path
import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "thresholds.yaml"


class _Section(BaseModel):
    # A missing or misspelt key fails loudly instead of silently using a default
    model_config = ConfigDict(extra="forbid")


class DataChecks(_Section):
    cross_check_tolerance_pp: float
    implausible_tracker_gap_pct: float
    max_gap_days_monthly: int
    max_gap_business_days_daily: int
    repeated_price_window_periods: int
    currency_mismatch_calendar_year_pp: float
    timing_difference_extra_tolerance_pp: float


class Calculator(_Section):
    periods_per_year_monthly: int
    periods_per_year_daily: int
    discrete_12m_windows: int
    risk_free_rate_pct: float | None
    decimals_internal: int
    decimals_display: int


class DecisionTree(_Section):
    default_time_horizon_years: int


class MandateIndex(_Section):
    green_min_r2: float
    green_beta_range: tuple[float, float]
    amber_min_r2: float
    amber_beta_range: tuple[float, float]


class PerformanceIndex(_Section):
    green_td_margin_over_ocf_pp: float
    green_max_te_pct: float
    amber_td_margin_over_ocf_pp: float
    amber_max_te_pct: float


class PerformanceActiveTarget(_Section):
    green_min_excess_pct: float
    red_below_excess_pct: float
    min_hit_rate: int
    hit_rate_windows: int


class PerformanceComparator(_Section):
    green_max_quartile: int
    amber_quartile: int
    red_quartile: int


class Value(_Section):
    green_max_peer_outperformance_pp: float
    amber_max_peer_outperformance_pp: float


class FeesIndex(_Section):
    green_max_ocf_over_peer_pp: float
    amber_max_ocf_over_peer_pp: float


class Limits(_Section):
    max_web_searches: int
    max_analyst_rewrites: int


class Thresholds(_Section):
    status: str
    note: str
    data_checks: DataChecks
    calculator: Calculator
    decision_tree: DecisionTree
    mandate_index: MandateIndex
    performance_index: PerformanceIndex
    performance_active_target: PerformanceActiveTarget
    performance_comparator: PerformanceComparator
    value: Value
    fees_index: FeesIndex
    limits: Limits

    @property
    def risk_free_rate_missing(self) -> bool:
        """ True when no rate is set, so the calculator uses 0 and raises a flag """
        return self.calculator.risk_free_rate_pct is None


def load_thresholds(path: str | Path = DEFAULT_PATH) -> Thresholds:
    with open(path, encoding="utf-8") as f:
        return Thresholds.model_validate(yaml.safe_load(f))
