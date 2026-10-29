""" Mandate Agent: AI calls are mocked (free, fast, repeatable); one live test runs with --run-live """
import asyncio
import json
import pytest
from agents.exceptions import AgentsException, ModelBehaviorError
from fund_performance.agents.mandate import MandateOutput, mandate_agent, read_mandate, reconcile
from fund_performance.config import load_thresholds
from fund_performance.io import read_json
from fund_performance.mandate import decision_path
from fund_performance.models import FundProfile
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import CHECK_DATA, performance_rating
from conftest import FIXTURES, TEST1_PROFILE, FakeRun, requires_test1

T = load_thresholds()


def profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()) | changes)


def answer(**changes):
    return MandateOutput.model_validate({"objective_type": "index_tracker", "benchmark_role": "target",
                                         "time_horizon_years": 5, "secondary_objective": None,
                                         "secondary_objective_unclassified": None,
                                         "promises": ["Track the index", "Grow the investment over 5+ years"]} | changes)


def run(prof, *responses):
    fake = FakeRun(*responses)
    return asyncio.run(read_mandate(prof, run=fake)), fake


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_MANDATE", raising=False)
    agent = mandate_agent()
    assert agent.model == "gpt-5.4-mini"                                   # from config/models.yaml
    assert agent.model_settings.temperature is None and agent.model_settings.reasoning.effort == "low"
    monkeypatch.setenv("FUND_MODEL_MANDATE", "gpt-5.4")                     # override one agent for testing
    assert mandate_agent().model == "gpt-5.4"


def test_agreeing_answer_gives_no_flags_and_only_the_objective_is_sent():
    prof = profile()
    result, fake = run(prof, answer())
    assert result.flags == [] and result.profile == prof
    assert result.promises == ["Track the index", "Grow the investment over 5+ years"]
    assert fake.prompts == [f"Objective text:\n{prof.objective_text}"]


@pytest.mark.parametrize("field,value", [("objective_type", "active_target"), ("benchmark_role", "comparator"),
                                         ("time_horizon_years", 3)])
def test_profile_wins_when_the_agent_disagrees(field, value):
    result, _ = run(profile(), answer(**{field: value}))
    [flag] = result.flags
    assert flag.level == "warning" and f"read {field} as '{value}'" in flag.message and "the profile is used" in flag.message
    assert getattr(result.profile, field) == getattr(profile(), field)


def test_secondary_found_by_the_agent_but_not_in_the_profile_is_flagged_not_used():
    result, _ = run(profile(), answer(secondary_objective="income_target"))
    assert result.profile.secondary_objective is None and "not in the profile" in result.flags[0].message


def test_typed_secondary_in_the_profile_wins():
    prof = profile(secondary_objective="income_target")
    result, _ = run(prof, answer(secondary_objective="absolute_return"))
    assert result.profile.secondary_objective == "income_target" and result.flags[0].level == "warning"


def test_free_text_secondary_is_classified_and_rated():
    prof = profile(objective_type="active_target", secondary_objective="to provide a yield above 4% a year")
    result, _ = run(prof, answer(objective_type="active_target", secondary_objective="income_target"))
    assert result.profile.secondary_objective == "income_target"
    assert result.flags[0].level == "info" and "classified as income_target" in result.flags[0].message
    assert decision_path(result.profile, False, []).objectives == ["active_target", "income_target"]


def test_free_text_secondary_that_cannot_be_classified_is_check_data():
    prof = profile(secondary_objective="to support local communities")
    result, _ = run(prof, answer(secondary_objective_unclassified="to support local communities"))
    assert "could not be classified" in result.flags[0].message
    pillar = performance_rating(ReportedFigures(), result.profile, decision_path(result.profile, False, []), T, "fund_nav")
    assert pillar.rating == CHECK_DATA


def test_invalid_output_is_retried_once():
    result, fake = run(profile(), {"objective_type": "tracker"}, answer())
    assert result.flags == [] and len(fake.prompts) == 2


def test_invalid_twice_is_check_data():
    result, fake = run(profile(), {"objective_type": "tracker"}, ModelBehaviorError("bad JSON"))
    [flag] = result.flags
    assert flag.level == "blocking" and flag.message.startswith("CHECK DATA: Mandate Agent gave no valid answer")
    assert len(fake.prompts) == 2 and result.promises == []


def test_a_failed_call_is_not_retried():
    result, fake = run(profile(), AgentsException("connection lost"), answer())
    assert result.flags[0].level == "blocking" and "call failed" in result.flags[0].message
    assert len(fake.prompts) == 1


def test_reconcile_never_changes_the_profile_fields_it_disagrees_on():
    prof = profile()
    out = reconcile(prof, answer(objective_type="absolute_return", time_horizon_years=10))
    assert out.profile.objective_type == "index_tracker" and out.profile.time_horizon_years == 5


@requires_test1
def test_test1_mocked_answer_matching_the_profile():
    prof = read_json(TEST1_PROFILE)
    result, _ = run(prof, answer(promises=["Track the S&P 500 (NUK) index", "Grow investment over 5+ years"]))
    assert result.flags == [] and result.profile == prof


@pytest.mark.live
@requires_test1
def test_live_test1_mandate_matches_the_profile():
    prof = read_json(TEST1_PROFILE)
    result = asyncio.run(read_mandate(prof))
    out = result.agent_output
    print("\nMandate Agent:", out.model_dump() if out else result.flags)
    assert out is not None
    assert (out.objective_type, out.benchmark_role, out.time_horizon_years, out.secondary_objective) == \
           (prof.objective_type, prof.benchmark_role, prof.time_horizon_years, prof.secondary_objective)
    assert result.flags == []
