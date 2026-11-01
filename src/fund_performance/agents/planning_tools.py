"""Read-only, per-review planning evidence; no files or network access."""
from dataclasses import dataclass, field

from agents import RunContextWrapper, function_tool

from fund_performance.models import DataFlag, FundProfile


def fund_mandate(profile: FundProfile) -> dict:
    """Return the supplied objective and its classification with provenance, not a verification claim."""
    fields = ("objective_text", "objective_type", "benchmark_name", "benchmark_role",
              "time_horizon_years", "secondary_objective")
    return {"values": {name: getattr(profile, name) for name in fields},
            "sources": {name: profile.field_sources.get(name, "fund profile") for name in fields},
            "qualification": "Document-derived fields may still require verification; follow data-quality flags."}


def portfolio_exposures() -> dict:
    """No structured portfolio evidence is currently collected by the intake pipeline."""
    return {"holdings": None, "sectors": None, "regions": None, "currencies": None,
            "concentration": None, "unavailable": "Portfolio exposures are not available in the current input model."}


@dataclass
class PlanningContext:
    profile: FundProfile
    mandate_flags: list[dict] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, profile: FundProfile, flags: list[DataFlag] | None = None) -> "PlanningContext":
        return cls(profile.model_copy(deep=True),
                   [{"level": f.level, "message": f.message} for f in flags or []
                    if f.check in ("mandate_agent", "fund_horizon", "ongoing_charge")])

    def allow(self, name: str) -> bool:
        if len(self.calls) >= 6:
            return False
        self.calls.append(name)
        return True


@function_tool
def get_fund_mandate(ctx: RunContextWrapper[PlanningContext]) -> dict:
    """Get this review's fund objective, benchmark role and field provenance."""
    if not ctx.context.allow("get_fund_mandate"):
        return {"error": "planning tool call limit reached"}
    return fund_mandate(ctx.context.profile) | {"mandate_checks": list(ctx.context.mandate_flags)}


@function_tool
def get_portfolio_exposures(ctx: RunContextWrapper[PlanningContext]) -> dict:
    """Get portfolio exposures or explicit reasons they are unavailable."""
    if not ctx.context.allow("get_portfolio_exposures"):
        return {"error": "planning tool call limit reached"}
    return portfolio_exposures()


TOOLS = [get_fund_mandate, get_portfolio_exposures]
