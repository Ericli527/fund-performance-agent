""" Loads config/thresholds.yaml (every threshold the spec needs), config/models.yaml (the model
for each AI agent), config/sources.yaml (approved pages fetched by code), config/settings.yaml (run settings)
and config/peers.yaml (approved peer funds), and checks them """
from pathlib import Path
import os
from typing import Literal, get_args
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    max_evaluator_rewrites: int


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
AgentName = Literal["extractor", "mandate", "planner", "search", "analyst", "evaluator", "task_planner",
                    "reporter", "judge"]


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


class VettingSettings(_Section):
    market_grace_days: int          # market news may be dated this many days after the review period ends


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
    vetting: VettingSettings
    funds: dict[str, list[ApprovedSource]] = {}
    markets: dict[str, list[ApprovedSource]] = {}

    def for_fund(self, isin: str, market: str) -> list[ApprovedSource]:
        """ The fund's own pages (by ISIN) and its market's pages (by market name), fund pages first """
        markets = {k.lower(): v for k, v in self.markets.items()}
        return self.funds.get(isin.upper(), []) + markets.get(market.lower(), [])


def load_sources(path: str | Path = SOURCES_PATH) -> SourcesConfig:
    with open(path, encoding="utf-8") as f:
        return SourcesConfig.model_validate(yaml.safe_load(f))


# --- config/settings.yaml: timeouts and email (step 10) -------------------------------------------------

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


class Timeouts(_Section):
    extractor: float
    mandate: float
    research: float
    narrative: float
    task_planner: float = 60
    drafting: float = 300


class DraftingSettings(_Section):
    """ Reporting Agents and the Judge: how many times the drafts may be sent back """
    max_rewrites: int = Field(default=1, ge=0)
    # Version 1 pilot: one draft (the plan's first angle), one Judge pass, at most one targeted rewrite that is
    # accepted on code's checks without a second Judge pass (rejudge_after_rewrite: true restores it)
    max_drafts: int = Field(default=1, ge=1)
    rejudge_after_rewrite: bool = False
    # The longest summary a draft may have: it is Executive page 1's summary (measured to fit with room to spare)
    max_summary_chars: int = Field(default=700, ge=200)
    # Agentic Tools V2.1: the Reporting Agent fetches the evidence with read-only tools (reporting_tools.py) within
    # reporter_max_turns model turns; false gives it the whole facts payload, as before
    reporter_tools: bool = False
    reporter_max_turns: int = Field(default=4, ge=2, le=8)


class ResearchSettings(_Section):
    """ Web research for the market context (Research Agents, then the Oversight Analyst and the Evaluator). Off for
    the Version 1 pilot: the review is then the documents, code's calculations and the drafting agents """
    enabled: bool = False


class EmailSettings(_Section):
    """ Recipients are not here: they come from the EMAIL_TO environment variable, so they never reach the public
    repository """
    enabled: bool
    sender: str
    subject: str
    attachment: Literal["executive", "detailed"] = "executive"   # which PDF is attached (stage 3)


class WebSettings(_Section):
    max_ai_runs_per_day: int = Field(gt=0)
    max_ai_runs_at_once: int = Field(gt=0)
    keep_runs_hours: float = Field(default=24, gt=0)        # on a server, run folders older than this are deleted
    cache_cleanup_minutes: int = Field(default=60, gt=0)    # how often Gradio's file cache is cleaned (files older
                                                            # than keep_runs_hours go)


class StatisticsSettings(_Section):
    """ The evidence dashboard's significance test (a one-sample t-test) """
    significance_level: float = Field(gt=0, lt=1)
    min_points: int = Field(ge=3)


class RunSettings(_Section):
    timeouts_seconds: Timeouts
    web: WebSettings
    statistics: StatisticsSettings
    drafting: DraftingSettings = Field(default_factory=DraftingSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    email: EmailSettings


def load_settings(path: str | Path = SETTINGS_PATH) -> RunSettings:
    with open(path, encoding="utf-8") as f:
        return RunSettings.model_validate(yaml.safe_load(f))


# --- config/peers.yaml: approved peer funds per benchmark (B1) -----------------------------------------------

PEERS_PATH = Path(__file__).resolve().parents[2] / "config" / "peers.yaml"
PEER_FOLDER = Path(__file__).resolve().parents[2] / "data" / "peers"


class ApprovedPeer(_Section):
    name: str
    isin: str
    factsheet: str | None = None          # file name in data/peers/; else found by the ISIN


class SectorOcf(_Section):
    value_pct: float
    source: str
    date: str


class BenchmarkPeers(_Section):
    benchmark: str
    match: list[str]                      # the fund's benchmark name contains one of these (any case)
    peers: list[ApprovedPeer]
    sector_average_ocf: SectorOcf | None = None


class PeersConfig(_Section):
    benchmarks: list[BenchmarkPeers] = Field(default_factory=list)

    def for_benchmark(self, benchmark_name: str | None) -> BenchmarkPeers | None:
        name = " ".join((benchmark_name or "").lower().split())
        return next((b for b in self.benchmarks if any(m.lower() in name for m in b.match)), None)


def load_peers(path: str | Path = PEERS_PATH) -> PeersConfig:
    if not Path(path).exists():
        return PeersConfig()
    with open(path, encoding="utf-8") as f:
        return PeersConfig.model_validate(yaml.safe_load(f) or {})
