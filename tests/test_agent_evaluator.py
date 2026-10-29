""" Evaluator Agent (step 10): rubric output, and its place in the Analyst's flow (one rewrite in total) """
import asyncio
from functools import partial
import pytest
from fund_performance.agents.analyst import INSTRUCTIONS as ANALYST_INSTRUCTIONS
from agents.exceptions import AgentsException
from fund_performance.agents.analyst import QUALITY_FAILED, QUALITY_NOT_DONE, template, write_narrative
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
    assert result.source == "ai" and result.log[-1] == "Evaluator passed draft 1" and len(evaluator.prompts) == 1


def test_evaluator_issues_go_back_for_the_one_rewrite():
    analyst = FakeRun(draft(), draft())
    _, check = evaluate(FAIL, PASS)
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert result.source == "ai" and "quality (rating_explained): Mandate is not mentioned" in analyst.prompts[1]
    assert result.log[-1] == "Evaluator passed draft 2"


def test_failing_the_evaluator_twice_uses_the_template():
    _, check = evaluate(FAIL, FAIL)
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft(), draft()), quality_check=check))
    assert result.source == "template" and result.output == template(FACTS)
    assert result.flags[0].message == (f"{QUALITY_FAILED}: the Evaluator rejected the draft (rating_explained); "
                                       "template narrative used")


def test_code_checks_and_the_evaluator_each_have_their_own_rewrite():
    """ A draft that used the code-check rewrite still gets the Evaluator's rewrite: 2 rewrites at most """
    bad = draft(key_findings=["The fund returned 99.9% a year."] + GOOD["key_findings"][1:])
    evaluator, check = evaluate(FAIL, PASS)
    analyst = FakeRun(bad, draft(), draft())
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert result.source == "ai" and len(analyst.prompts) == 3 and len(evaluator.prompts) == 2
    assert "number not in the facts" in analyst.prompts[1] and "quality (rating_explained)" in analyst.prompts[2]
    assert result.log[-1] == "Evaluator passed draft 3"


def test_the_evaluator_only_sees_drafts_that_pass_code_checks():
    """ The Evaluator's rewrite fails code's checks; code's own rewrite is still unused, so it is used """
    bad = draft(key_findings=["The fund returned 99.9% a year."] + GOOD["key_findings"][1:])
    evaluator, check = evaluate(FAIL, PASS)
    analyst = FakeRun(draft(), bad, draft())
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert result.source == "ai" and len(evaluator.prompts) == 2 and len(analyst.prompts) == 3


def test_no_third_rewrite():
    bad = draft(key_findings=["The fund returned 99.9% a year."] + GOOD["key_findings"][1:])
    evaluator, check = evaluate(FAIL)
    analyst = FakeRun(bad, draft(), bad)
    result = asyncio.run(write_narrative(FACTS, run=analyst, quality_check=check))
    assert len(analyst.prompts) == 3 and len(evaluator.prompts) == 1 and result.source == "template"
    assert result.flags[0].message.startswith("AI text failed checks: number")


def test_rewrite_limits_come_from_the_config():
    from fund_performance.config import load_thresholds
    limits = load_thresholds().limits
    assert (limits.max_analyst_rewrites, limits.max_evaluator_rewrites) == (1, 1)


def test_no_valid_evaluator_result_uses_the_template_and_says_so():
    _, check = evaluate({"bad": 1}, {"bad": 1})
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft()), quality_check=check))
    assert result.source == "template"
    assert result.flags[0].message == (f"{QUALITY_NOT_DONE}: the Evaluator gave no valid answer after one retry; "
                                       "template narrative used")


def test_an_unreachable_evaluator_uses_the_template_and_says_so():
    """ Not the same as a rejection: the draft was never judged """
    evaluator, check = evaluate(AgentsException("connection error"))
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft()), quality_check=check))
    assert result.source == "template" and len(evaluator.prompts) == 1          # a failed call is not retried
    assert result.flags[0].message == (f"{QUALITY_NOT_DONE}: the Evaluator could not be reached; "
                                       "template narrative used")
    assert "rejected" not in result.flags[0].message


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
    assert result.flags[0].message == (f"{QUALITY_FAILED}: the Evaluator rejected the draft (supported_claims); "
                                       "template narrative used")


def test_plain_english_rule_is_calibrated_to_the_glossary():
    """ From the full run: the Evaluator asked for definitions of everyday market words """
    from fund_performance.glossary import glossary_lines
    text = evaluator_agent().instructions
    for line in glossary_lines():
        assert line in text
    assert "Only glossary terms need a definition" in text
    for word in ("AI", "large-cap", "Treasury yields", "volatility"):
        assert word in text.split("Everyday market words")[1].split("Glossary")[0]
