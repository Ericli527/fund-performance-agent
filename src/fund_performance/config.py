""" Loads config/thresholds.yaml (every threshold the spec needs), config/models.yaml (the model
for each AI agent) and config/sources.yaml (approved pages fetched by code), and checks them """
from pathlib import Path
import os
from typing import Literal, get_args
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

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
    repeated_price_factsheet_match_pp: float


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
    hit_rate_td_margin_over_ocf_pp: float


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


# --- config/models.yaml: the model for each AI agent ----------------------------------------------------

MODELS_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
AgentName = Literal["extractor", "mandate", "planner", "search", "analyst", "evaluator"]


class ModelSpec(_Section):
    """ What a model accepts: a temperature, or (for reasoning models) a reasoning effort """
    supports_temperature: bool
    temperature: float | None = None
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _one_setting(self) -> "ModelSpec":
        if self.supports_temperature and self.temperature is None:
            raise ValueError("a model that supports temperature needs a temperature (e.g. 0)")
        if not self.supports_temperature and self.temperature is not None:
            raise ValueError("temperature given for a model that does not support it")
        if not self.supports_temperature and self.reasoning_effort is None:
            raise ValueError("a model without temperature needs a reasoning_effort (e.g. low)")
        return self


class ModelsConfig(_Section):
    agents: dict[AgentName, str]
    models: dict[str, ModelSpec]

    @model_validator(mode="after")
    def _every_agent_has_a_known_model(self) -> "ModelsConfig":
        missing = set(get_args(AgentName)) - set(self.agents)
        if missing:
            raise ValueError(f"no model set for: {sorted(missing)}")
        unknown = {a: m for a, m in self.agents.items() if m not in self.models}
        if unknown:
            raise ValueError(f"models not listed under 'models': {unknown}")
        return self

    def for_agent(self, agent: AgentName) -> tuple[str, ModelSpec]:
        """ The agent's model and its settings. FUND_MODEL_<AGENT> overrides one agent, for testing """
        model = os.getenv(f"FUND_MODEL_{agent.upper()}") or self.agents[agent]
        if model not in self.models:
            raise ValueError(f"FUND_MODEL_{agent.upper()}={model} is not listed under 'models' in models.yaml")
        return model, self.models[model]


def load_models(path: str | Path = MODELS_PATH) -> ModelsConfig:
    with open(path, encoding="utf-8") as f:
        return ModelsConfig.model_validate(yaml.safe_load(f))


# --- config/sources.yaml: approved pages that code fetches directly -------------------------------------

SOURCES_PATH = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"


class FetchSettings(_Section):
    timeout_seconds: float
    min_page_chars: int
    max_page_chars: int
    user_agent: str


class ApprovedSource(_Section):
    name: str
    url: str
    topic: Literal["fund_news", "market_drivers"]

    @model_validator(mode="after")
    def _https(self) -> "ApprovedSource":
        if not self.url.startswith("https://"):
            raise ValueError(f"approved source {self.name!r} must use https://")
        return self


class SourcesConfig(_Section):
    fetch: FetchSettings
    funds: dict[str, list[ApprovedSource]] = {}
    markets: dict[str, list[ApprovedSource]] = {}

    def for_fund(self, isin: str, market: str) -> list[ApprovedSource]:
        """ The fund's own pages (by ISIN) and its market's pages (by market name), fund pages first """
        markets = {k.lower(): v for k, v in self.markets.items()}
        return self.funds.get(isin.upper(), []) + markets.get(market.lower(), [])


def load_sources(path: str | Path = SOURCES_PATH) -> SourcesConfig:
    with open(path, encoding="utf-8") as f:
        return SourcesConfig.model_validate(yaml.safe_load(f))
