""" Oversight Analyst: mocked pass / one rewrite / fallback; one live test on Test 1 that prints the text """
import asyncio
import pytest
from fund_performance.agents.analyst import (AI_TEXT_UNAVAILABLE, NUMBER_CHECK_FAILED, AnalystOutput, analyst_agent,
                                             problems, template, write_narrative)
from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import load_thresholds
from fund_performance.facts import build_facts
from fund_performance.io import read_json, read_prices
from fund_performance.mandate import decision_path
from fund_performance.precedence import apply_precedence
from fund_performance.scorecard import score
from conftest import TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, FakeRun, requires_test1

FACTS = {
    "fund": {"fund_name": "Sample Index Fund", "ocf_pct": 0.06},
    "scorecard": {"verdict": "Monitor until a peer is added",
                  "verdict_reason": "Value and fees cannot be judged without a peer",
                  "pillars": [
                      {"name": "Mandate", "rating": "GREEN", "reason": "R² 1.00 and beta 1.00, 3y (factsheet)",
                       "summary": None, "sub_ratings": [], "notes": []},
                      {"name": "Performance", "rating": "GREEN", "reason": "TD -0.10 pp a year (5y); TE 0.02%",
                       "summary": None, "sub_ratings": [], "notes": []},
                      {"name": "Value for investors", "rating": "AMBER", "reason": "no comparison available",
                       "summary": "Add peer", "sub_ratings": [], "notes": []},
                      {"name": "Fees", "rating": "AMBER", "reason": "no comparison available",
                       "summary": "Add peer", "sub_ratings": [], "notes": []}]},
    "decision_path": ["1. Objective type: index_tracker"],
    "data_flags": [],
    "figures": [{"name": "fund_pnav.ann.5y", "value": 13.8, "unit": "%"},
                {"name": "index.ann.5y", "value": 13.9, "unit": "%"},
                {"name": "comparison.td.5y", "value": -0.1, "unit": "pp"}]}

GOOD = {"key_findings": ["The fund tracked its index closely: 13.8% a year against 13.9% over 5 years.",
                         "The tracking difference, the gap between fund and index returns, was -0.10 pp a year.",
                         "Value and fees cannot be judged until a peer fund is added."],
        "actions": ["Add a comparable peer fund.", "Confirm the draft verdict in the approval section."],
        "market_context": None}


def draft(**changes):
    return GOOD | changes


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_ANALYST", raising=False)
    agent = analyst_agent()
    assert agent.model == "gpt-5.4" and agent.model_settings.reasoning.effort == "low"
    assert agent.model_settings.temperature is None


def test_a_good_draft_passes_first_time_without_search_summaries():
    fake = FakeRun(draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 1
    assert "Search summaries:\nnone" in fake.prompts[0]


def test_one_rewrite_with_the_list_of_bad_numbers():
    bad = draft(key_findings=["The fund returned 14.2% a year."] + GOOD["key_findings"][1:])
    fake = FakeRun(bad, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 2
    assert "number not in the facts: 14.2%" in fake.prompts[1]
    assert "after one rewrite" in result.log[-1]


def test_fallback_to_the_template_after_a_failed_rewrite():
    bad = draft(key_findings=["The fund returned 14.2% a year."] + GOOD["key_findings"][1:])
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(bad, bad)))
    assert result.source == "template"
    [flag] = result.flags
    assert flag.level == "warning" and flag.message.startswith(NUMBER_CHECK_FAILED)
    assert result.output == template(FACTS)


def test_a_draft_that_changes_a_rating_is_rejected():
    changed = draft(key_findings=GOOD["key_findings"][:2] + ["Fees are Green because the charge is low."])
    assert any(p.startswith("rating") for p in problems(AnalystOutput.model_validate(changed), FACTS))
    fake = FakeRun(changed, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and "calls Fees GREEN" in fake.prompts[1]


def test_a_draft_that_changes_the_verdict_is_rejected():
    changed = draft(actions=["Retain the fund.", "Add a comparable peer fund."])
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(changed, changed)))
    assert result.source == "template" and any("uses 'Retain'" in line for line in result.log)


def test_wrong_number_of_findings_is_invalid_output_and_retried():
    fake = FakeRun(draft(key_findings=GOOD["key_findings"][:2]), draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and len(fake.prompts) == 2


def test_invalid_output_twice_uses_the_template():
    result = asyncio.run(write_narrative(FACTS, run=FakeRun({"key_findings": "x"}, {"actions": []})))
    assert result.source == "template" and result.flags[0].message.startswith(AI_TEXT_UNAVAILABLE)


def test_market_context_without_search_summaries_is_dropped():
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft(market_context="Tech stocks led, up 25.0%."))))
    assert result.source == "ai" and result.output.market_context is None


def test_the_template_passes_both_guards():
    assert problems(template(FACTS), FACTS) == []


def _test1_facts():
    T = load_thresholds()
    prof, fs = read_json(TEST1_PROFILE), read_json(TEST1_FACTSHEET)
    checked = check_prices(read_prices(TEST1_CSV), prof, T, fs)
    reported = apply_precedence(calculate(checked.prices, prof, T, fs), checked.flags, prof, T, fs, checked.comparison)
    card = score(reported, prof, T, decision_path(prof, checked.short_history, reported.flags), None,
                 checked.comparison.fund_series, checked.comparison.extra_tolerance_pp)
    return build_facts(prof, reported, card, reported.flags,
                       ["Track the S&P 500 (NUK) index", "Grow investment over 5+ years"])


@requires_test1
def test_test1_template_passes_both_guards():
    facts = _test1_facts()
    assert problems(template(facts), facts) == []


@pytest.mark.live
@requires_test1
def test_live_test1_analyst():
    facts = _test1_facts()
    result = asyncio.run(write_narrative(facts))
    print(f"\n--- Oversight Analyst ({result.source}) ---")
    print("Key findings:")
    for f in result.output.key_findings:
        print(" -", f)
    print("Recommended actions:")
    for a in result.output.actions:
        print(" -", a)
    print("Market context:", result.output.market_context)
    print("Log:", *result.log, sep="\n  ")
    print("Flags:", [f.message for f in result.flags])
    assert problems(result.output, facts) == []
