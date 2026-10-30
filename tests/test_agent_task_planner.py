""" Task Planner Agent: menu choices only, checked by code; the default plan when it fails """
import asyncio
import json
from fund_performance.agents.task_planner import QUESTIONS, TaskPlan, plan_tasks
from fund_performance.models import FundProfile
from conftest import FIXTURES, FakeRun

PROFILE = FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()))
FEE_PLAN = {"report_type": "fee_question", "focus": ["Fees", "Fees", "Value for investors"], "market_context": False,
            "manager_questions": True, "angles": ["board"], "reason": "The request asks whether the fee is justified."}


def test_a_fee_question_puts_fees_first_but_keeps_every_rating():
    plan, flags = asyncio.run(plan_tasks("Is the fee justified?", PROFILE, FakeRun(FEE_PLAN)))
    assert flags == [] and plan.source == "planner" and plan.report_type == "fee_question"
    assert plan.focus == ["Fees", "Value for investors", "Mandate", "Performance"]       # all four, named first
    assert sorted(plan.focus) == sorted(QUESTIONS) and plan.angles == ["board"] and not plan.market_context
    assert not any("market context" in t for t in plan.tasks) and "Judge the drafts" in plan.tasks[4]


def test_the_planner_sees_public_details_only():
    run = FakeRun(FEE_PLAN)
    asyncio.run(plan_tasks("Is the fee justified?", PROFILE, run))
    assert "ocf_pct" not in run.prompts[0] and PROFILE.fund_name in run.prompts[0]


def test_no_angle_means_all_angles():
    plan, _ = asyncio.run(plan_tasks("q", PROFILE, FakeRun(FEE_PLAN | {"angles": []})))
    assert plan.angles == ["board", "analyst", "manager_meeting"]


def test_an_invalid_answer_twice_gives_the_default_plan_and_an_info_flag():
    plan, flags = asyncio.run(plan_tasks("q", PROFILE, FakeRun({"bad": 1}, {"bad": 2})))
    assert plan == TaskPlan(reason=plan.reason) and plan.source == "default"
    assert flags[0].level == "info" and "default plan" in flags[0].message
