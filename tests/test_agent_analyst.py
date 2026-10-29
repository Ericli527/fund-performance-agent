""" Oversight Analyst: mocked pass / one rewrite / fallback; one live test on Test 1 that prints the text """
import asyncio
import pytest
from fund_performance.agents.analyst import (failed_checks, AI_TEXT_UNAVAILABLE, CHECKS_FAILED, AnalystOutput, analyst_agent,
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
        "actions": [{"candidate": "add_peer", "text": "Add a comparable peer fund before the next quarterly review."},
                    {"candidate": "record_decision",
                     "text": "Record the decision and its reasons in the approval box at this review."}],
        "market_context": None}


def draft(**changes):
    return GOOD | changes


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_ANALYST", raising=False)
    agent = analyst_agent()
    assert agent.model == "gpt-5.4" and agent.model_settings.reasoning.effort == "low"
    assert agent.model_settings.temperature is None


def test_prompt_carries_the_style_rules_and_glossary():
    from fund_performance.agents.analyst import INSTRUCTIONS, STYLE_EXAMPLE
    for rule in ("Draft verdict", "Plain meaning first", "under 20 words", "ongoing charge (OCF)",
                 "below the surface", "chosen ONLY from \"candidate_actions\"", "Never add a new\n  action",
                 "Never put a minus sign after", "Cite them as [1], [2]", STYLE_EXAMPLE):
        assert rule in INSTRUCTIONS


def test_a_good_draft_passes_first_time_without_search_summaries():
    fake = FakeRun(draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 1
    assert fake.prompts[0].endswith("Sources:\nnone")


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
    assert flag.level == "warning" and flag.message == f"{CHECKS_FAILED}: number; template narrative used"
    assert result.output == template(FACTS)


def test_a_draft_that_changes_a_rating_is_rejected():
    changed = draft(key_findings=GOOD["key_findings"][:2] + ["Fees are Green because the charge is low."])
    assert any(p.startswith("rating") for p in problems(AnalystOutput.model_validate(changed), FACTS))
    fake = FakeRun(changed, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and "calls Fees GREEN" in fake.prompts[1]


def test_a_draft_that_changes_the_verdict_is_rejected():
    changed = draft(actions=[{"candidate": "add_peer", "text": "Retain the fund; add a peer fund before the next quarterly review."},
                             GOOD["actions"][1]])
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
        print(f" - [{a.candidate}] {a.text}")
    print("Market context:", result.output.market_context)
    print("Log:", *result.log, sep="\n  ")
    print("Flags:", [f.message for f in result.flags])
    assert problems(result.output, facts) == []


# Wording rules checked by code
def _out(**changes):
    return AnalystOutput.model_validate(GOOD | changes)


def test_no_minus_sign_after_behind_or_below():
    bad = _out(key_findings=["The fund was behind by -0.10% a year.", "It sat below the index by \u22120.10 pp.", "c"])
    found = [p for p in problems(bad, FACTS) if p.startswith("style")]
    assert len(found) == 2
    assert not [p for p in problems(_out(key_findings=["The fund was behind by 0.10% a year.", "b", "c"]), FACTS)
                if p.startswith("style")]


def test_minus_rule_triggers_one_rewrite():
    bad = draft(key_findings=["The fund was behind its index by -0.10 pp a year."] + GOOD["key_findings"][1:])
    fake = FakeRun(bad, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and "minus sign after 'behind'" in fake.prompts[1]


def test_template_actions_each_say_when():
    for action in template(FACTS).action_texts:
        assert "before" in action or "at this review" in action or "at the next" in action


# Part 1 fixes: required insights, periods in words, which checks failed
NOTES = [{"kind": "pricing", "note": "Noon pricing.", "figures": [
             {"label": "Gap at noon prices (NAV vs index), 5y", "value": -3.3, "unit": "pp", "display": "-3.3 pp", "key": True},
             {"label": "Fair gap (PNAV vs index), 5y", "value": -0.7, "unit": "pp", "display": "-0.7 pp"}]},
         {"kind": "fee", "note": "Most of the yearly gap to the index is the fee.", "figures": [
             {"label": "Tracking difference, a year, 5y", "value": -0.1, "unit": "pp", "display": "-0.10 pp"},
             {"label": "Fund behind its index, in plain terms (% a year), 5y", "value": -0.1, "unit": "%", "display": "-0.10%"},
             {"label": "Ongoing charge (OCF), a year", "value": 0.06, "unit": "%", "display": "0.06%", "key": True}]}]
FACTS_NOTES = FACTS | {"data_notes": NOTES}
COVERED = ["The fund tracks its index closely. Its noon price makes it look 3.3 pp behind over 5 years.",
           "At market close (PNAV) the gap is 0.7 pp, and most of it is the 0.06% yearly fee.",
           "Value and fees cannot be judged until a peer fund is added."]


def test_findings_that_cover_every_data_note_pass():
    assert problems(_out(key_findings=COVERED), FACTS_NOTES) == []


def test_a_missing_data_note_triggers_the_rewrite():
    without_fee = ["The fund tracks its index closely. Its noon price makes it look 3.3 pp behind over 5 years.",
                   "At market close (PNAV) the gap is 0.7 pp.", "Value and fees need a peer fund."]
    issues = problems(_out(key_findings=without_fee), FACTS_NOTES)
    assert len(issues) == 1 and issues[0].startswith("insight: the findings do not cover this data note (use 0.06%)")
    fake = FakeRun(draft(key_findings=without_fee), draft(key_findings=COVERED))
    result = asyncio.run(write_narrative(FACTS_NOTES, run=fake))
    assert result.source == "ai" and "insight:" in fake.prompts[1]


def test_periods_are_written_in_words():
    issues = problems(_out(key_findings=["The fund returned 13.8% a year over 5y.", "b", "c"]), FACTS)
    assert issues == ["style: write periods in words, not '5y'"]


def test_the_flag_lists_which_checks_failed():
    bad = draft(key_findings=["Fees are Green; the fund returned 14.2% over 5y.", "b", "c"])
    result = asyncio.run(write_narrative(FACTS_NOTES, run=FakeRun(bad, bad)))
    assert result.flags[0].message == "AI text failed checks: number / rating / wording / insights; template narrative used"


def test_the_plain_template_covers_every_data_note_and_passes():
    facts = FACTS_NOTES | {"fund": {"time_horizon_years": 5}}
    t = template(facts)
    assert problems(t, facts) == []
    assert "behind it by 0.10% a year over 5 years (tracking difference -0.10 pp)" in t.key_findings[1]
    assert "3.3 pp behind its index over 5 years" in t.key_findings[2]


# Fixes from the full Test 1 run: sentence limit, bracketed definitions, actions that do something
def test_at_most_two_sentences_per_finding():
    four = "The fund tracks its index. It costs 0.06% a year. Its noon price differs. That explains the gap."
    issues = problems(_out(key_findings=[four, "R² 1.00 (how closely fund and index move together), e.g. a tracker.",
                                         "One sentence. Two sentences."]), FACTS)
    assert issues == ["style: finding 1 has 4 sentences; use at most 2"]


def test_too_many_sentences_trigger_the_rewrite():
    long = draft(key_findings=["One point. Two points. Three points."] + GOOD["key_findings"][1:])
    fake = FakeRun(long, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and "finding 1 has 3 sentences" in fake.prompts[1]


@pytest.mark.parametrize("action", ["Note that a peer fund is needed before the next quarterly review.",
                                    "It remains understood that a peer is needed, before signing off this review.",
                                    "Be aware that a peer fund is needed at the next quarterly review."])
def test_actions_that_only_ask_people_to_notice_are_rejected(action):
    issues = problems(_out(actions=[{"candidate": "add_peer", "text": action}, GOOD["actions"][1]]), FACTS)
    assert len(issues) == 1 and issues[0].startswith("style: action 1 only asks people to")


def test_prompt_asks_for_bracketed_definitions_and_specific_actions():
    from fund_performance.agents.analyst import INSTRUCTIONS
    assert '"R² 1.00 (how closely fund and index move together)"' in INSTRUCTIONS
    assert "Never add a new\n  action" in INSTRUCTIONS and '"note that"' in INSTRUCTIONS
    facts = FACTS_NOTES | {"fund": {"time_horizon_years": 5}}
    assert problems(template(facts), facts) == []


def test_a_mislabelled_figure_triggers_the_rewrite_and_counts_as_a_number_problem():
    from test_number_guard import LABEL_FACTS
    facts = FACTS_NOTES | {"fund": {"ocf_pct": 0.06, "time_horizon_years": 5},
                           "figures": FACTS_NOTES.get("figures", []) + LABEL_FACTS["figures"]}
    bad = ["The fund tracks its index. Over 5 years its tracking difference was -3.3 pp at noon prices.",
           "At market close (PNAV) the gap is 0.7 pp, and most of it is the 0.06% yearly fee.",
           "Value and fees cannot be judged until a peer fund is added."]
    issues = problems(_out(key_findings=bad), facts)
    assert any(i.startswith("label: '-3.3 pp' next to 'tracking difference'") for i in issues)
    assert "number" in failed_checks([i for i in issues if i.startswith("label:")])
