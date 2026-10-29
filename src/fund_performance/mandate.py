""" Decision tree (spec Section 5.1): which tests apply to this fund, recorded step by step for the report

This is code, not AI. The Mandate Agent (step 6) only reads the objective text; the profile decides.
"""
from dataclasses import dataclass, field
from typing import get_args
from fund_performance.models import DataFlag, FundProfile, ObjectiveType

WHAT_IS_JUDGED = {
    "index_tracker": "tracking (TD, TD_ex_cost, TE, R2) vs benchmark",
    "active_target": "annualised excess return vs the target over the horizon",
    "active_comparator": "peer/sector ranking (quartile) and excess vs comparator",
    "active_constraint": "excess vs benchmark and staying within constraints",
    "income_target": "yield/income vs target and capital preservation",
    "absolute_return": "return vs stated target (e.g. cash + x%) and drawdown",
}
SHORT_HISTORY_REASON = "track record shorter than the fund's time horizon"


@dataclass
class DecisionPath:
    objective_type: str
    secondary_objective: str | None
    short_history: bool
    main_period_years: int
    blocking: list[DataFlag] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    @property
    def objectives(self) -> list[str]:
        """ The objective types to rate: the main one, and the secondary one for a dual objective """
        return [self.objective_type] + ([self.secondary_objective] if self.secondary_objective else [])


def decision_path(profile: FundProfile, short_history: bool, flags: list[DataFlag]) -> DecisionPath:
    """ Walk the five questions of spec 5.1 and record the answers """
    blocking = [f for f in flags if f.level == "blocking"]
    path = DecisionPath(profile.objective_type, profile.secondary_objective, short_history,
                        profile.time_horizon_years, blocking)
    path.steps.append(f"1. Objective type: {profile.objective_type}, so judge {WHAT_IS_JUDGED[profile.objective_type]}")
    if profile.secondary_objective:
        rated = profile.secondary_objective in get_args(ObjectiveType)
        path.steps.append(f"2. Dual objective: yes ({profile.secondary_objective}); each objective is rated "
                          "separately and Performance is the weaker of the two"
                          + ("" if rated else ". The secondary objective is not a known objective type, so it "
                                               "cannot be rated by code"))
    else:
        path.steps.append("2. Dual objective: no")
    path.steps.append("3. Short history: " + (f"yes, {SHORT_HISTORY_REASON}; since-launch figures are used and "
                                               "Performance is at least Amber, never Red on history alone"
                                               if short_history else "no"))
    path.steps.append(f"4. Main test period: {profile.time_horizon_years} years; 1y and 3y shown as trend context")
    path.steps.append("5. Data checks: " + ("; ".join(f.message for f in blocking) + ", so CHECK DATA"
                                             if blocking else "no blocking flag"))
    return path
