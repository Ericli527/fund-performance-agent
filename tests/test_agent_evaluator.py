""" Evaluator Agent (step 10): rubric output, and its place in the Analyst's flow (one rewrite in total) """
import asyncio
from functools import partial
import pytest
from fund_performance.agents.analyst import INSTRUCTIONS as ANALYST_INSTRUCTIONS
from fund_performance.agents.analyst import QUALITY_FAILED, template, write_narrative
from fund_performance.agents.evaluator import EvaluatorOutput, evaluator_agent, evaluator_input, review
from conftest import FakeRun, requires_test1
from test_agent_analyst import FACTS, GOOD, draft

PASS = {"pass": True, "issues": []}
FAIL = {"pass": False, "issues": [{"check": "rating_explained", "detail": "Mandate is not mentioned"}]}
SOURCES = [{"number": 1, "query": "S&P 500 review", "date": "2026-09-30", "summary": "US shares rose.",
            "url": "https://example.com/review"}]


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_EVALUATOR", raising=False)
    agent = evaluator_agent()
    assert agent.model == "gpt-6.1-sol" and agent.model_settings.reasoning.effort == "low"
    assert agent.instructions != ANALYST_INSTRUCTIONS                      # its own prompt, so no self-grading
    for check in ("rating_explained", "no_rating_change", "supported_claims", "sources_cited",
                  "check_data_handled", "plain_english"):
        assert check in agent.instructions


def test_output_is_pass_and_issues_only():
    """ It never edits the text: its output has no text field """
    assert list(EvaluatorOutput.model_json_schema(by_alias=True)["properties"]) == ["pass", "issues"]
    with pytest.raises(ValueError):
        EvaluatorOutput.model_validate({"pass": True, "issues": [], "rewritten": "text"})


def test_input_holds_facts_numbered_sources_without_urls_and_the_draft():
    text = evaluator_input(FACTS, SOURCES, GOOD)
    assert '"verdict": "Monitor until a peer is added"' in text and '"source": "[1]"' in text
    assert "https://" not in text and GOOD["key_findings"][0] in text


@pytest.mark.parametrize("answer, passed, checks", [
    (PASS, True, []),
    (FAIL, False, ["rating_explained"]),
    ({"pass": True, "issues": FAIL["issues"]}, False, ["rating_explained"]),      # a named issue is never ignored
])
def test_review_results(answer, passed, checks):
    result = asyncio.run(review(FACTS, [], GOOD, run=FakeRun(answer)))
    assert result.passed is passed and result.failed_checks == checks and result.error is None


def test_invalid_output_is_retried_once_then_reported():
    fake = FakeRun({"pass": False, "issues": []}, {"pass": False, "issues": []})
    result = asyncio.run(review(FACTS, [], GOOD, run=fake))
    assert len(fake.prompts) == 2 and not result.passed and "no issues are given" in result.error


# In the Analyst's flow
def evaluate(*answers):
    fake = FakeRun(*answers)
    return fake, partial(review, run=fake)


def test_a_draft_that_passes_both_checks_is_used():
    evaluator, check = evaluate(PASS)
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft()), quality_check=check))
    assert result.source == "ai" and result.log[-1] == "Evaluator passed the draft" and len(evaluator.prompts) == 1


def test_evaluator_issues_go_back_for_the_one_rewrite():
    analyst = FakeRun(draft(), draft())
    _, check = evaluate(FAIL, PASS)
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert result.source == "ai" and "quality (rating_explained): Mandate is not mentioned" in analyst.prompts[1]
    assert result.log[-1] == "Evaluator passed the draft after one rewrite"


def test_failing_the_evaluator_twice_uses_the_template():
    _, check = evaluate(FAIL, FAIL)
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft(), draft()), quality_check=check))
    assert result.source == "template" and result.output == template(FACTS)
    assert result.flags[0].message == f"{QUALITY_FAILED} (rating_explained); template narrative used"


def test_only_one_rewrite_in_total():
    """ A draft that fails code's checks uses the rewrite; if the Evaluator then fails it, the template is used """
    bad = draft(key_findings=["The fund returned 99.9% a year.", "b", "c"])
    evaluator, check = evaluate(FAIL)
    analyst = FakeRun(bad, draft())
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert len(analyst.prompts) == 2 and len(evaluator.prompts) == 1 and result.source == "template"
    assert QUALITY_FAILED in result.flags[0].message


def test_no_valid_evaluator_result_uses_the_template():
    _, check = evaluate({"bad": 1}, {"bad": 1})
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft()), quality_check=check))
    assert result.source == "template"
    assert result.flags[0].message == f"{QUALITY_FAILED}: the Evaluator gave no valid result; template narrative used"


def test_the_evaluator_is_not_called_when_code_checks_fail_twice():
    bad = draft(key_findings=["The fund returned 99.9% a year.", "b", "c"])
    evaluator, check = evaluate()
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(bad, bad), quality_check=check))
    assert evaluator.prompts == [] and result.flags[0].message.startswith("AI text failed checks: number")


@pytest.mark.live
@requires_test1
def test_live_test1_evaluator_on_the_template():
    from test_agent_analyst import _test1_facts
    facts = _test1_facts()
    result = asyncio.run(review(facts, [], template(facts).model_dump()))
    print("\nEvaluator:", "pass" if result.passed else "fail", *[f"{i.check}: {i.detail}" for i in result.issues],
          result.error or "", sep="\n  ")
    assert result.error is None


# Spec Section 11, step 10: a draft with a changed rating or an unsupported claim is rejected
def test_a_draft_with_a_changed_rating_is_rejected():
    changed = draft(key_findings=["Fees are Green: the fund is cheap.", "b", "Value and fees need a peer fund."])
    evaluator, check = evaluate()
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(changed, changed), quality_check=check))
    assert result.source == "template" and "rating" in result.flags[0].message
    assert evaluator.prompts == []                 # code's rating guard catches it before the Evaluator


def test_a_draft_with_an_unsupported_claim_is_rejected():
    claim = draft(key_findings=GOOD["key_findings"][:2] + ["The manager will cut the fee next year."])
    unsupported = {"pass": False, "issues": [{"check": "supported_claims",
                                              "detail": "'will cut the fee next year' is not in the facts or sources"}]}
    analyst = FakeRun(claim, claim)
    _, check = evaluate(unsupported, unsupported)
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert "quality (supported_claims)" in analyst.prompts[1]
    assert result.source == "template"
    assert result.flags[0].message == f"{QUALITY_FAILED} (supported_claims); template narrative used"
