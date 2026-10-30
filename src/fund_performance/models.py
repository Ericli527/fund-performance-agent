""" Data shapes shared by every step (spec Sections 1 and 2), validated with Pydantic """
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Source = Literal["factsheet", "calculated", "ai_extracted", "user", "web"]   # "user": corrected on the page
ObjectiveType = Literal["index_tracker", "active_target", "active_comparator", "active_constraint",
                        "income_target", "absolute_return"]
BenchmarkRole = Literal["target", "comparator", "constraint", "none"]
PricingPoint = Literal["midday", "market_close"]
Basis = Literal["cumulative", "annualised"]
RiskBasis = Literal["nav", "pnav"]


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
    performance_fee_justification: str | None = None   # written by a person only, never by an AI agent
    fund_size_gbp_m: float | None = None
    risk_indicator: int | None = Field(default=None, ge=1, le=7)
    pricing_point: PricingPoint
    as_of_date: date
    asset_class: str = "equity"
    # Documents route (step 11 update): who gave each field, e.g. {"ocf_pct": "user", "isin": "ai_extracted"}
    field_sources: dict[str, Literal["ai_extracted", "user", "code"]] = Field(default_factory=dict)


class SeriesReturns(_Strict):
    """ Returns for one series, in percent. JSON keys are '1y', '3y' and '5y' as in the spec """
    y1: float | None = Field(default=None, alias="1y")
    y3: float | None = Field(default=None, alias="3y")
    y5: float | None = Field(default=None, alias="5y")
    since_launch: float | None = None
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
    alpha: float | None = None
    basis: RiskBasis | None = None


class FactsheetPerformance(_Strict):
    """ factsheet_performance.json (spec 2.2). entered_by records who typed the figures """
    as_of_date: date
    currency: str = Field(min_length=3, max_length=3)
    series: dict[str, SeriesReturns]
    calendar_years: dict[str, dict[str, float]] = Field(default_factory=dict)
    risk_3y: Risk3y | None = None
    source: Literal["factsheet", "ai_extracted"]
    entered_by: Literal["manual", "extractor"] | None = None
    # Optional extras (spec 2.2): official annualised figures, discrete 12-month windows, NAV-basis risk
    series_annualised: dict[str, SeriesReturns] = Field(default_factory=dict)
    discrete_12m: dict[str, dict[date, float]] = Field(default_factory=dict)
    risk_3y_nav: Risk3y | None = None
    # Figures a person corrected on the page before the run, e.g. ["index.5y"] (reported as "Entered by user")
    user_entered: list[str] = Field(default_factory=list)

    @field_validator("series_annualised")
    @classmethod
    def _annualised_basis(cls, value: dict[str, SeriesReturns]) -> dict[str, SeriesReturns]:
        wrong = [name for name, s in value.items() if s.basis != "annualised"]
        if wrong:
            raise ValueError(f"series_annualised must have basis 'annualised': {wrong}")
        return value

    @model_validator(mode="after")
    def _risk_bases_never_mixed(self) -> "FactsheetPerformance":
        if self.risk_3y_nav is not None:
            if self.risk_3y_nav.basis != "nav":
                raise ValueError("risk_3y_nav must have basis 'nav'")
            if self.risk_3y is not None and self.risk_3y.basis != "pnav":
                raise ValueError("when risk_3y_nav is given, risk_3y must have basis 'pnav'")
        return self

    def risk(self, basis: RiskBasis) -> Risk3y | None:
        """ The 3-year risk figures on one basis only, so NAV and PNAV figures are never mixed """
        if self.risk_3y_nav is not None and basis == "nav":
            return self.risk_3y_nav
        if self.risk_3y is not None and self.risk_3y.basis == basis:
            return self.risk_3y
        return None

    @field_validator("calendar_years")
    @classmethod
    def _years_are_years(cls, value: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        for series, years in value.items():
            bad = [y for y in years if not (len(y) == 4 and y.isdigit())]
            if bad:
                raise ValueError(f"calendar_years.{series}: not a year: {bad}")
        return value


class Peer(_Strict):
    """ peer.json (spec Section 2): name, OCF, 1/3/5y returns, currency, share class. The optional fields are for
    the peer checks (B2): pricing time, share class type and minimum investment, income or accumulation, and the
    official annualised returns (preferred over annualising the cumulative ones) """
    name: str
    ocf_pct: float
    returns: SeriesReturns
    currency: str = Field(min_length=3, max_length=3)
    share_class: str
    isin: str | None = None
    returns_annualised: SeriesReturns | None = None
    pricing_point: PricingPoint | None = None
    distribution: Literal["accumulation", "income"] | None = None
    investor_type: Literal["retail", "institutional"] | None = None
    minimum_investment: str | None = None
    vol_3y: float | None = None             # 3-year volatility from the peer's factsheet, for the dashboard
    # The index the peer follows, as its factsheet names it (e.g. "S&P 500 Index (GBP)"): disclosed when it is a
    # different variant from the fund's benchmark; information only, it never changes a comparison or a rating
    benchmark_name: str | None = None
    origin: Literal["typed", "uploaded", "approved"] = "typed"   # peer.json, an uploaded factsheet, config/peers.yaml


class Figure(BaseModel):
    """ One number in the report, always with its source (spec principle 4).
    value is stored to 2 d.p. (spec 4); exact keeps full precision so the 1 d.p. display is rounded once,
    not twice (10.5499 shows as 10.5, not 10.55 -> 10.6) """
    value: float
    exact: float | None = None
    unit: str
    source: Source
    period: str | None = None
    basis: str | None = None            # e.g. "pnav" or "nav" for factsheet risk figures

    def display(self, percent_decimals: int = 1, ratio_decimals: int = 2) -> str:
        """ Percentages to 1 d.p. (spec 4), ratios such as beta to 2 d.p. """
        number = self.value if self.exact is None else self.exact
        if self.unit.startswith("of "):                     # a count, e.g. hit rate "5 of 5"
            return f"{int(number)} {self.unit}"
        if self.unit in ("%", "pp"):
            return f"{round(number, percent_decimals) + 0.0:.{percent_decimals}f}{'%' if self.unit == '%' else ' pp'}"
        return f"{round(number, ratio_decimals) + 0.0:.{ratio_decimals}f}"

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
