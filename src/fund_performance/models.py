""" Data shapes shared by every step (spec Sections 1 and 2), validated with Pydantic """
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Source = Literal["factsheet", "calculated", "ai_extracted", "web"]
ObjectiveType = Literal["index_tracker", "active_target", "active_comparator", "active_constraint",
                        "income_target", "absolute_return"]
BenchmarkRole = Literal["target", "comparator", "constraint", "none"]
PricingPoint = Literal["midday", "market_close"]
Basis = Literal["cumulative", "annualised"]


class _Strict(BaseModel):
    # Input files are typed by people or extracted by AI, so unknown keys are rejected to catch typos
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FundProfile(_Strict):
    """ fund_profile.json (spec 2.1), plus the optional asset_class agreed with the project owner """
    fund_name: str
    isin: str
    share_class: str
    currency: str = Field(min_length=3, max_length=3)
    distribution: Literal["accumulation", "income"]
    hedged: bool
    launch_date: date
    objective_text: str
    objective_type: ObjectiveType
    benchmark_name: str
    benchmark_role: BenchmarkRole
    time_horizon_years: int = Field(gt=0)
    secondary_objective: str | None = None
    ocf_pct: float
    transaction_cost_pct: float | None = None
    performance_fee: bool
    fund_size_gbp_m: float | None = None
    risk_indicator: int | None = Field(default=None, ge=1, le=7)
    pricing_point: PricingPoint
    as_of_date: date
    asset_class: str = "equity"


class SeriesReturns(_Strict):
    """ Returns for one series, in percent. JSON keys are '1y', '3y' and '5y' as in the spec """
    y1: float | None = Field(default=None, alias="1y")
    y3: float | None = Field(default=None, alias="3y")
    y5: float | None = Field(default=None, alias="5y")
    basis: Basis
    pricing: PricingPoint | None = None


class Risk3y(_Strict):
    """ 3-year risk figures as printed on the factsheet """
    fund_vol: float | None = None
    index_vol: float | None = None
    tracking_error: float | None = None
    beta: float | None = None
    r2: float | None = None
    sharpe_fund: float | None = None
    sharpe_index: float | None = None
    info_ratio: float | None = None


class FactsheetPerformance(_Strict):
    """ factsheet_performance.json (spec 2.2). entered_by records who typed the figures """
    as_of_date: date
    currency: str = Field(min_length=3, max_length=3)
    series: dict[str, SeriesReturns]
    calendar_years: dict[str, dict[str, float]] = Field(default_factory=dict)
    risk_3y: Risk3y | None = None
    source: Literal["factsheet", "ai_extracted"]
    entered_by: Literal["manual", "extractor"] | None = None

    @field_validator("calendar_years")
    @classmethod
    def _years_are_years(cls, value: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        for series, years in value.items():
            bad = [y for y in years if not (len(y) == 4 and y.isdigit())]
            if bad:
                raise ValueError(f"calendar_years.{series}: not a year: {bad}")
        return value


class Peer(_Strict):
    """ peer.json (spec Section 2): name, OCF, 1/3/5y returns, currency, share class """
    name: str
    ocf_pct: float
    returns: SeriesReturns
    currency: str = Field(min_length=3, max_length=3)
    share_class: str


class Figure(BaseModel):
    """ One number in the report, always with its source (spec principle 4) """
    value: float
    unit: str
    source: Source
    period: str | None = None

    @property
    def needs_verification(self) -> bool:
        return self.source == "ai_extracted"

    @property
    def label(self) -> str:
        """ AI-extracted figures are shown with "please verify" """
        return "please verify" if self.needs_verification else ""


class DataFlag(BaseModel):
    """ One entry in data_flags[] (spec 3.4). A blocking flag turns the affected rating into CHECK DATA """
    check: str
    level: Literal["info", "warning", "blocking"]
    message: str
    dates: list[date] = Field(default_factory=list)
