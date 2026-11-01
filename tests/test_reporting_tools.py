""" Agentic Tools V2.1: the Reporting Agent's read-only tools, its run context and its bounds. The tool calls run
through the real OpenAI Agents SDK loop with a fake model built from the SDK's own classes (no API call) """
import asyncio
import json
from pathlib import Path
import pytest
from agents.items import ModelResponse
from agents.models.interface import Model, ModelProvider
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
from fund_performance.agents import base
from fund_performance.agents.base import run_with_fresh_client as REAL_RUN    # before conftest replaces it
from fund_performance.agents.reporter import reporter_input, verdict_sentence, write_draft
from fund_performance.agents.reporting_tools import (LIMIT_REACHED, NOT_IN_FACTS, NOT_RELIABLE, TOOLS, ReviewContext,
                                                     fund_performance, oversight_scorecard, peer_comparison)
from fund_performance.agents.planning_tools import PlanningContext, fund_mandate, portfolio_exposures
from fund_performance.agents.task_planner import plan_tasks
from fund_performance.models import DataFlag, FundProfile

FACTS = json.loads((Path(__file__).parent / "golden" / "demo_facts.json").read_text())   # the made-up fund


def figure(name):
    return next(f for f in FACTS["figures"] if f["name"] == name)


# 1. What each tool returns: code's stored figures, never recalculated, and plain reasons for what is missing
def test_fund_performance_returns_the_stored_figures_for_the_period():
    out = fund_performance(FACTS, "5y")
    assert out["fund_return_a_year"]["display"] == figure("fund_nav.ann.5y")["display"]
    assert out["benchmark_return_cumulative"]["value"] == figure("index.cum.5y")["value"]
    assert out["tracking_difference"]["display"] == figure("comparison.td.5y")["display"]
    assert out["tracking_error"]["display"] == figure("relative.tracking_error.5y")["display"]
    assert out["unavailable"] == {} and out["as_of_date"] == "2026-09-30"


def test_benchmark_comparison_uses_pnav_when_tracking_difference_says_pnav():
    facts = json.loads(json.dumps(FACTS))
    td = next(f for f in facts["figures"] if f["name"] == "comparison.td.5y")
    td["basis"] = "fund_pnav"
    for kind in ("cum", "ann"):
        nav = next(f for f in facts["figures"] if f["name"] == f"fund_nav.{kind}.5y")
        facts["figures"].append(nav | {"name": f"fund_pnav.{kind}.5y", "display": "42.0%"})
    out = fund_performance(facts, "5y")
    assert out["fund_benchmark_basis"] == "fund_pnav"
    assert out["fund_return_a_year"]["display"] == "42.0%"
    assert out["tracking_difference"]["display"] == td["display"]


def test_missing_values_are_named_never_estimated():
    out = fund_performance(FACTS, "1y")
    assert out["tracking_error"] is None and out["unavailable"]["tracking_error"] == NOT_IN_FACTS
    since = fund_performance(FACTS, "since_launch")
    assert since["fund_return_cumulative"]["display"] == figure("fund_nav.since_launch.cum")["display"]
    assert since["tracking_difference"] is None and "1, 3 and 5 years only" in since["unavailable"]["tracking_difference"]


def test_an_invalid_fund_vs_index_comparison_is_never_returned_as_reliable():
    facts = json.loads(json.dumps(FACTS))
    facts["data_flags"] = [{"check": "currency_match", "level": "blocking", "message": "CHECK DATA: currencies differ"}]
    out = fund_performance(facts, "5y")
    assert out["fund_return_a_year"] is not None and out["benchmark_return_a_year"] is None
    assert out["unavailable"]["tracking_difference"] == NOT_RELIABLE


def test_the_scorecard_and_peer_tools():
    card = oversight_scorecard(FACTS)
    assert card["verdict_code"] == "Retain" and card["verdict_sentence"] == verdict_sentence(FACTS)
    assert [r["question"] for r in card["ratings"]] == ["Mandate", "Performance", "Value for investors", "Fees"]
    assert card["material_data_warnings"] == [] and card["findings"][0]["note"]
    peers = peer_comparison(FACTS)
    assert peers["peers"][0]["name"] == "Sample World Index Tracker B" and "missing" not in peers
    assert peers["fees"]["rating"] and peers["fund_ongoing_charge_pct"] == FACTS["fund"]["ocf_pct"]
    assert "no peer fund" in peer_comparison(FACTS | {"peers": []})["missing"]


# 2. The run context: this review's facts only, a private copy, and a call budget
def test_the_context_is_a_private_copy_with_a_call_budget():
    ctx = ReviewContext.of(FACTS, max_calls=2)
    ctx.facts["scorecard"]["verdict"] = "changed"
    assert FACTS["scorecard"]["verdict"] == "Retain"                     # the review's facts cannot be changed
    assert ctx.allow("a") and ctx.allow("b") and not ctx.allow("c") and ctx.calls == ["a", "b"]


def test_with_tools_the_agent_gets_a_brief_not_the_whole_payload():
    plan = {"report_type": "fee_question", "focus": ["Fees"], "tasks": ["Compare fees"]}
    prompt = reporter_input(FACTS, "board", ["Fees"], tools=True, plan=plan)
    assert "Review brief (fetch the evidence with your tools)" in prompt and '"report_type": "fee_question"' in prompt
    assert '"figures"' not in prompt and figure("fund_nav.ann.5y")["display"] not in prompt
    assert f"Verdict sentence to end with: {verdict_sentence(FACTS)}" in prompt
    assert '"figures"' in reporter_input(FACTS, "board", ["Fees"])          # tools off: the payload, as before


# 3. The real SDK loop with a fake model: the agent calls the tools, gets code's figures and writes from them
class ScriptedModel(Model):
    """ A model that answers turn by turn from a script of tool calls, then a final JSON answer """
    def __init__(self, turns):
        self.turns, self.inputs = list(turns), []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, **_):
        self.inputs.append(input)
        step = self.turns.pop(0) if self.turns else self.loop_forever
        if isinstance(step, list):
            return ModelResponse(output=[ResponseFunctionToolCall(
                type="function_call", id=f"fc{i}", call_id=f"call{len(self.inputs)}_{i}", name=name,
                arguments=json.dumps(args), status="completed") for i, (name, args) in enumerate(step)],
                usage=Usage(), response_id=None)
        return ModelResponse(output=[ResponseOutputMessage(
            id="msg", type="message", role="assistant", status="completed",
            content=[ResponseOutputText(type="output_text", text=json.dumps(step), annotations=[])])],
            usage=Usage(), response_id=None)

    loop_forever = [("get_oversight_scorecard", {})]

    def stream_response(self, *a, **k):
        raise NotImplementedError


@pytest.fixture
def sdk_with(monkeypatch):
    """ The production run path (base.run_with_fresh_client -> Runner.run) with a scripted model instead of OpenAI """
    def install(model):
        class Provider(ModelProvider):
            def __init__(self, openai_client=None):
                pass

            def get_model(self, model_name):
                return model

        class Client:
            async def close(self):
                pass
        monkeypatch.setattr(base, "run_with_fresh_client", REAL_RUN)
        monkeypatch.setattr(base, "OpenAIProvider", Provider)
        monkeypatch.setattr(base, "AsyncOpenAI", Client)
        return model
    return install


def test_the_reporting_agent_calls_the_tools_and_writes_from_their_figures(sdk_with):
    fund_5y = figure("fund_nav.ann.5y")["display"]
    text = (f"The evidence suggests the fund tracked its index closely, returning {fund_5y} a year over 5 years. "
            + verdict_sentence(FACTS))
    model = sdk_with(ScriptedModel([[("get_oversight_scorecard", {}), ("get_fund_performance", {"period": "5y"})],
                                    {"text": text, "market_context": None}]))
    draft = asyncio.run(write_draft(FACTS, "board", ["Performance"], tools=True, max_turns=4))
    assert draft.tools_used == ["get_oversight_scorecard", "get_fund_performance(5y)"]
    assert draft.text == text and draft.figures_match                   # code's checks pass on the tools' figures
    tool_outputs = [item for item in model.inputs[1] if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert len(tool_outputs) == 2 and fund_5y in tool_outputs[1]["output"]
    assert len(model.inputs) == 2                                        # one tool round, then the answer


def test_a_model_that_keeps_calling_tools_is_stopped_by_the_turn_and_call_bounds(sdk_with):
    model = sdk_with(ScriptedModel([]))                                 # calls a tool on every turn, for ever
    draft = asyncio.run(write_draft(FACTS, "board", ["Performance"], tools=True, max_turns=3))
    assert len(model.inputs) == 3 and draft.error and "MaxTurnsExceeded" in draft.error
    assert len(draft.tools_used) <= 6 and not draft.figures_match         # the review falls back, nothing invented


def test_the_tool_budget_refuses_extra_calls(sdk_with):
    calls = [("get_fund_performance", {"period": p}) for p in ("1y", "3y", "5y", "since_launch")] * 2
    model = sdk_with(ScriptedModel([calls, {"text": "x. " + verdict_sentence(FACTS)}]))
    draft = asyncio.run(write_draft(FACTS, "board", ["Performance"], tools=True, max_turns=4))
    outputs = [i["output"] for i in model.inputs[1] if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert len(draft.tools_used) == 6 and sum(LIMIT_REACHED in o for o in outputs) == 2


def test_the_tools_are_read_only_function_tools_with_strict_arguments():
    assert [t.name for t in TOOLS] == ["get_fund_performance", "get_oversight_scorecard", "get_peer_comparison"]
    schema = TOOLS[0].params_json_schema
    assert schema["properties"]["period"]["enum"] == ["1y", "3y", "5y", "since_launch"] and schema["additionalProperties"] is False
    assert all(t.strict_json_schema for t in TOOLS)


def test_planning_evidence_is_isolated_and_missing_exposures_are_explicit():
    profile = FundProfile.model_validate(json.loads((Path(__file__).parent / "fixtures" / "fund_profile_sample.json").read_text()))
    first, second = PlanningContext.of(profile), PlanningContext.of(profile)
    first.profile.objective_text = "changed"
    assert fund_mandate(second.profile)["values"]["objective_text"] == profile.objective_text
    assert all(portfolio_exposures()[key] is None for key in ("holdings", "sectors", "regions", "currencies"))
    assert all(first.allow("tool") for _ in range(6)) and not first.allow("tool")


def test_planning_context_keeps_only_mandate_flags():
    profile = FundProfile.model_validate(json.loads((Path(__file__).parent / "fixtures" / "fund_profile_sample.json").read_text()))
    flags = [DataFlag(check="mandate_agent", level="warning", message="Objective conflicts"),
             DataFlag(check="other", level="warning", message="Unrelated")]
    context = PlanningContext.of(profile, flags)
    assert context.mandate_flags == [{"level": "warning", "message": "Objective conflicts"}]


def test_planner_calls_scoped_evidence_tools_through_sdk(sdk_with):
    profile = FundProfile.model_validate(json.loads((Path(__file__).parent / "fixtures" / "fund_profile_sample.json").read_text()))
    answer = {"report_type": "quarterly_review", "focus": ["Mandate"], "market_context": True,
              "manager_questions": True, "angles": ["board"], "searches": [], "reason": "Review mandate."}
    model = sdk_with(ScriptedModel([[('get_fund_mandate', {}), ('get_portfolio_exposures', {})], answer]))
    calls = []
    mandate_flags = [DataFlag(check="mandate_agent", level="warning", message="Objective conflict")]
    plan, flags = asyncio.run(plan_tasks("Review the mandate", profile, tool_calls=calls, mandate_flags=mandate_flags))
    outputs = [item["output"] for item in model.inputs[1] if isinstance(item, dict) and item.get("type") == "function_call_output"]
    assert calls == ["get_fund_mandate", "get_portfolio_exposures"] and not flags
    assert profile.objective_text in outputs[0] and "Objective conflict" in outputs[0]
    assert "not available" in outputs[1]
    assert len(plan.focus) == 4
