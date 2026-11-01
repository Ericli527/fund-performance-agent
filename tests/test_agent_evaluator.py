""" Evaluator Agent (step 10): rubric output, and its place in the Analyst's flow. It judges only the AI's text, the
market context; the findings and the actions are code's and shown for context """
import asyncio
from functools import partial
import pytest
from agents.exceptions import AgentsException
from fund_performance.agents.analyst import INSTRUCTIONS as ANALYST_INSTRUCTIONS
from fund_performance.agents.analyst import (LEFT_OUT, QUALITY_FAILED, QUALITY_NOT_DONE, AnalystDraft, evaluator_view,
                                             template, write_narrative)
from fund_performance.agents.evaluator import EvaluatorOutput, evaluator_agent, evaluator_input, review
from conftest import FakeRun, requires_test1
from test_agent_analyst import FACTS, GOOD, SOURCES, draft

PASS = {"pass": True, "issues": []}
FAIL = {"pass": False, "issues": [{"check": "supported_claims",
                                   "detail": "'all year' but source [1] covers only the summer"}]}
NUMBERED = [{"number": i, **s} for i, s in enumerate(SOURCES, start=1)]
BAD_NUMBER = draft("US shares rose 25.3% [1].")
VIEW = evaluator_view(FACTS, AnalystDraft.model_validate(GOOD))


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_EVALUATOR", raising=False)
    agent = evaluator_agent()
    assert agent.model == "gpt-6.1-terra" and agent.model_settings.reasoning.effort == "low"
    assert agent.instructions != ANALYST_INSTRUCTIONS                      # its own prompt, so no self-grading
    for check in ("no_rating_change", "supported_claims", "sources_cited", "check_data_handled", "plain_english"):
        assert check in agent.instructions


def test_it_judges_only_the_market_context():
    text = " ".join(evaluator_agent().instructions.split())
    assert 'only the part marked "to_judge", the market context' in text and "Never raise an issue about them" in text
    assert list(VIEW) == ["findings_written_by_code_not_judged", "market_context_to_judge",
                          "actions_written_by_code_not_judged"]


def test_output_is_pass_and_issues_only():
    """ It never edits the text: its output has no text field """
    assert list(EvaluatorOutput.model_json_schema(by_alias=True)["properties"]) == ["pass", "issues"]
    with pytest.raises(ValueError):
        EvaluatorOutput.model_validate({"pass": True, "issues": [], "rewritten": "text"})
    with pytest.raises(ValueError):
        EvaluatorOutput.model_validate({"pass": False, "issues": [{"check": "rating_explained", "detail": "x"}]})


def test_input_holds_facts_numbered_sources_without_urls_and_the_draft():
    text = evaluator_input(FACTS, NUMBERED, VIEW)
    assert '"verdict": "Monitor until a peer is added"' in text and '"source": "[1]"' in text
    assert "https://" not in text and GOOD["market_context"] in text


@pytest.mark.parametrize("answer, passed, checks", [
    (PASS, True, []),
    (FAIL, False, ["supported_claims"]),
    ({"pass": True, "issues": FAIL["issues"]}, False, ["supported_claims"]),      # a named issue is never ignored
])
def test_review_results(answer, passed, checks):
    result = asyncio.run(review(FACTS, [], VIEW, run=FakeRun(answer)))
    assert result.passed is passed and result.failed_checks == checks and result.error is None


def test_invalid_output_is_retried_once_then_reported():
    fake = FakeRun({"pass": False, "issues": []}, {"pass": False, "issues": []})
    result = asyncio.run(review(FACTS, [], VIEW, run=fake))
    assert len(fake.prompts) == 2 and not result.passed and "no issues are given" in result.error


# In the Analyst's flow
def evaluate(*answers):
    fake = FakeRun(*answers)
    return fake, partial(review, run=fake)


def narrate(analyst, check):
    return asyncio.run(write_narrative(FACTS, SOURCES, run=analyst, quality_check=check))


def test_a_draft_that_passes_both_checks_is_used():
    evaluator, check = evaluate(PASS)
    result = narrate(FakeRun(draft()), check)
    assert result.source == "ai" and result.log[-1] == "Evaluator passed draft 1" and len(evaluator.prompts) == 1
    assert "market_context_to_judge" in evaluator.prompts[0]


def test_evaluator_issues_go_back_for_its_rewrite():
    analyst = FakeRun(draft(), draft())
    _, check = evaluate(FAIL, PASS)
    result = narrate(analyst, check)
    assert result.source == "ai" and "quality (supported_claims)" in analyst.prompts[1]
    assert result.log[-1] == "Evaluator passed draft 2"


def test_failing_the_evaluator_twice_leaves_the_market_context_out():
    _, check = evaluate(FAIL, FAIL)
    result = narrate(FakeRun(draft(), draft()), check)
    assert result.source == "template" and result.output == template(FACTS)
    assert result.flags[0].message == (f"{QUALITY_FAILED}: the Evaluator rejected the draft (supported_claims); "
                                       f"{LEFT_OUT}")


def test_code_and_evaluator_issues_add_up_across_rewrites():
    evaluator, check = evaluate(FAIL, PASS)
    analyst = FakeRun(BAD_NUMBER, draft(), draft())
    result = narrate(analyst, check)
    assert result.source == "ai" and len(analyst.prompts) == 3 and len(evaluator.prompts) == 2
    third = analyst.prompts[2]
    assert "quality (supported_claims)" in third.split("Earlier drafts")[0]
    assert "number in the market context: 25.3%" in third.split("Earlier drafts")[1]


def test_the_evaluator_only_sees_drafts_that_pass_code_checks():
    evaluator, check = evaluate(FAIL, PASS)
    analyst = FakeRun(draft(), BAD_NUMBER, draft())
    result = narrate(analyst, check)
    assert result.source == "ai" and len(evaluator.prompts) == 2 and len(analyst.prompts) == 3


def test_at_most_three_rewrites_two_for_code_one_for_the_evaluator():
    evaluator, check = evaluate(FAIL, FAIL)
    analyst = FakeRun(BAD_NUMBER, BAD_NUMBER, draft(), draft())
    result = narrate(analyst, check)
    assert len(analyst.prompts) == 4 and len(evaluator.prompts) == 2 and result.source == "template"


def test_no_valid_evaluator_result_leaves_the_market_context_out_and_says_so():
    _, check = evaluate({"bad": 1}, {"bad": 1})
    result = narrate(FakeRun(draft()), check)
    assert result.source == "template"
    assert result.flags[0].message == f"{QUALITY_NOT_DONE}: the Evaluator gave no valid answer after one retry; {LEFT_OUT}"


def test_an_unreachable_evaluator_leaves_the_market_context_out_and_says_so():
    evaluator, check = evaluate(AgentsException("connection error"))
    result = narrate(FakeRun(draft()), check)
    assert result.source == "template" and len(evaluator.prompts) == 1          # a failed call is not retried
    assert result.flags[0].message == f"{QUALITY_NOT_DONE}: the Evaluator could not be reached; {LEFT_OUT}"


def test_the_evaluator_is_not_called_when_code_checks_keep_failing():
    evaluator, check = evaluate()
    result = narrate(FakeRun(BAD_NUMBER, BAD_NUMBER, BAD_NUMBER), check)
    assert evaluator.prompts == [] and result.flags[0].message.startswith("AI text failed checks: number")


# Spec Section 11, step 10: a draft with a changed rating or an unsupported claim is rejected
def test_a_draft_with_a_changed_rating_is_rejected():
    changed = draft("Fees are Green as US shares rose [1].")
    evaluator, check = evaluate()
    result = narrate(FakeRun(changed, changed, changed), check)
    assert result.source == "template" and "rating" in result.flags[0].message
    assert evaluator.prompts == []                 # code's rating guard catches it before the Evaluator


def test_a_draft_with_an_unsupported_claim_is_rejected():
    claim = draft("The Federal Reserve will cut rates next year [1].")
    unsupported = {"pass": False, "issues": [{"check": "supported_claims",
                                              "detail": "'will cut rates next year' is not in source [1]"}]}
    analyst = FakeRun(claim, claim)
    _, check = evaluate(unsupported, unsupported)
    result = narrate(analyst, check)
    assert "quality (supported_claims)" in analyst.prompts[1] and result.source == "template"
    assert result.flags[0].message == f"{QUALITY_FAILED}: the Evaluator rejected the draft (supported_claims); {LEFT_OUT}"


def test_plain_english_rule_is_calibrated_to_the_glossary():
    from fund_performance.glossary import glossary_lines
    text = evaluator_agent().instructions
    for line in glossary_lines():
        assert line in text
    assert "Only glossary terms need a definition" in text
    for word in ("AI", "large-cap", "Treasury yields", "volatility"):
        assert word in text.split("Everyday market words")[1].split("Glossary")[0]


@pytest.mark.live
@requires_test1
def test_live_test1_evaluator():
    from test_agent_analyst import _test1_facts
    facts = _test1_facts()
    result = asyncio.run(review(facts, NUMBERED, evaluator_view(facts, AnalystDraft.model_validate(GOOD))))
    print("\nEvaluator:", "pass" if result.passed else "fail", *[f"{i.check}: {i.detail}" for i in result.issues],
          result.error or "", sep="\n  ")
    assert result.error is None
