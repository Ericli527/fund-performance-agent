""" Decision tree (spec 5.1): the path taken is recorded for the report """
import json
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, FundProfile
from conftest import FIXTURES


def profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()) | changes)


def test_index_fund_path():
    path = decision_path(profile(), short_history=False, flags=[])
    assert path.objectives == ["index_tracker"] and path.main_period_years == 5 and path.blocking == []
    assert path.steps[0].startswith("1. Objective type: index_tracker, so judge tracking")
    assert path.steps[1:] == ["2. Dual objective: no", "3. Short history: no",
                              "4. Main test period: 5 years; 1y and 3y shown as trend context",
                              "5. Data checks: no blocking flag"]


def test_dual_objective_path():
    path = decision_path(profile(objective_type="active_target", secondary_objective="income_target"), False, [])
    assert path.objectives == ["active_target", "income_target"]
    assert "Performance is the weaker of the two" in path.steps[1]
    unknown = decision_path(profile(secondary_objective="grow income"), False, [])
    assert "cannot be rated by code" in unknown.steps[1]


def test_short_history_path():
    path = decision_path(profile(time_horizon_years=5), short_history=True, flags=[])
    assert "since-launch figures are used" in path.steps[2] and "never Red on history alone" in path.steps[2]


def test_blocking_flags_are_recorded():
    flag = DataFlag(check="currency_match", level="blocking", message="CHECK DATA: currency mismatch")
    info = DataFlag(check="pre_launch", level="info", message="pre-launch")
    path = decision_path(profile(), False, [flag, info])
    assert path.blocking == [flag] and path.steps[4] == "5. Data checks: CHECK DATA: currency mismatch, so CHECK DATA"
