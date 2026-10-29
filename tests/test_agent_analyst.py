""" Oversight Analyst: code writes finding 1 and the actions; the AI writes findings 2 and 3 and the market context,
which code checks. Mocked pass / rewrites / fallback; one live test on Test 1 that prints the text """
import asyncio
import pytest
from fund_performance.agents.analyst import (AI_TEXT_UNAVAILABLE, CHECKS_FAILED, AnalystDraft, analyst_agent,
                                             code_actions, failed_checks, problems, ratings_finding, template,
                                             template_draft, write_narrative)
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
    "fund": {"fund_name": "Sample Index Fund", "ocf_pct": 0.06, "objective_type": "index_tracker",
             "time_horizon_years": 5},
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
    "figures": [{"name": "fund_pnav.ann.5y", "value": 13.8, "unit": "%", "source": "factsheet"},
                {"name": "index.ann.5y", "value": 13.9, "unit": "%", "source": "factsheet"},
                {"name": "comparison.td.5y", "value": -0.1, "unit": "pp", "source": "calculated"},
                {"name": "risk.pnav.r2.3y", "value": 1.0, "unit": "ratio", "source": "factsheet"},
                {"name": "risk.pnav.beta.3y", "value": 1.0, "unit": "ratio", "source": "factsheet"},
                {"name": "risk.pnav.tracking_error.3y", "value": 0.02, "unit": "%", "source": "factsheet"}]}

GOOD = {"findings": ["The fund returned 13.8% a year against 13.9% for its index over 5 years.",
                     "The tracking difference, the gap between fund and index returns, was -0.10 pp a year over 5 years."],
        "market_context": None}


def draft(**changes):
    return GOOD | changes


def _out(**changes):
    return AnalystDraft.model_validate(GOOD | changes)


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_ANALYST", raising=False)
    agent = analyst_agent()
    assert agent.model == "gpt-5.4" and agent.model_settings.reasoning.effort == "low"
    assert agent.model_settings.temperature is None


def test_the_ai_writes_only_findings_2_and_3_and_the_market_context():
    assert list(AnalystDraft.model_fields) == ["findings", "market_context"]


def test_prompt_carries_the_style_rules_and_glossary():
    from fund_performance.agents.analyst import INSTRUCTIONS, STYLE_EXAMPLE
    text = " ".join(INSTRUCTIONS.split())
    for rule in ("Plain meaning first", "under 20 words", "ongoing charge (OCF)", "below the surface",
                 "Never put a minus sign after", "Cite them as [1], [2]", " ".join(STYLE_EXAMPLE.split()),
                 "the fee explains the yearly tracking difference, not the noon-price gap",
                 '"R² 1.00 (how closely fund and index move together)"', "Do not repeat them"):
        assert rule in text, rule


# Finding 1 and the actions: written by code
def test_finding_1_names_the_mandate_and_performance_ratings_with_their_reasons():
    assert ratings_finding(FACTS) == (
        "Mandate is Green: the fund moves in line with its index (R² 1.00 and beta 1.00 over 3 years, factsheet). "
        "Performance is Green: the fund is 0.10% a year behind its index over 5 years (tracking difference -0.10 pp "
        "a year); tracking error is 0.02% (over 3 years, factsheet).")


def test_finding_1_for_check_data_and_other_funds_uses_the_reason_in_plain_words():
    facts = FACTS | {"fund": FACTS["fund"] | {"objective_type": "active_target"},
                     "scorecard": FACTS["scorecard"] | {"pillars": [
                         p | {"rating": "CHECK DATA", "reason": "currency mismatch in 5y index"}
                         if p["name"] == "Performance" else p for p in FACTS["scorecard"]["pillars"]]}}
    text = ratings_finding(facts)
    assert "Mandate is Green: R² 1.00 and beta 1.00, 3 years (factsheet)." in text
    assert "Performance needs a data check: currency mismatch in 5 years index." in text


def test_the_narrative_puts_code_and_ai_text_together():
    fake = FakeRun(draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 1
    assert result.output.key_findings == [ratings_finding(FACTS)] + GOOD["findings"]
    assert result.output.actions == code_actions(FACTS)
    assert "Written by code (do not repeat):\nFinding 1: Mandate is Green" in fake.prompts[0]
    assert "Sources:\nnone" in fake.prompts[0]


# Code's checks on the AI's text, and the rewrites
def test_one_rewrite_with_the_list_of_bad_numbers():
    bad = draft(findings=["The fund returned 14.2% a year over 5 years.", GOOD["findings"][1]])
    fake = FakeRun(bad, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 2
    assert "number not in the facts: 14.2%" in fake.prompts[1]
    assert result.log[-1] == "Analyst draft 2 passed the number, rating and wording checks"


def test_code_checks_get_two_rewrites_then_the_template():
    bad = draft(findings=["The fund returned 14.2% a year over 5 years.", GOOD["findings"][1]])
    fake = FakeRun(bad, bad, bad)
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "template" and len(fake.prompts) == 3
    [flag] = result.flags
    assert flag.level == "warning" and flag.message == f"{CHECKS_FAILED}: number; template narrative used"
    assert result.output == template(FACTS)


def test_every_rewrite_gets_all_the_issues_so_far():
    """ Draft 1 breaks the number rule, draft 2 the minus rule: the third request lists both """
    numbers = draft(findings=["The fund returned 14.2% a year over 5 years.", GOOD["findings"][1]])
    minus = draft(findings=["The fund was behind its index by -0.10% a year over 5 years.", GOOD["findings"][1]])
    fake = FakeRun(numbers, minus, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai"
    third = fake.prompts[2]
    current, earlier = third.split("It was rejected for these reasons:")[1].split("Earlier drafts were rejected")
    assert "minus sign after 'behind'" in current and "number not in the facts: 14.2%" in earlier
    assert "Keep every rule your previous draft already passed" in third and "Do not bring back" in third


def test_rewrite_budget_comes_from_the_config():
    limits = load_thresholds().limits
    assert (limits.max_analyst_rewrites, limits.max_evaluator_rewrites) == (2, 1)


def test_a_draft_that_changes_a_rating_is_rejected():
    changed = draft(findings=[GOOD["findings"][0], "Fees are Green because the charge is low."])
    assert any(p.startswith("rating") for p in problems(AnalystDraft.model_validate(changed), FACTS))
    fake = FakeRun(changed, draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and "calls Fees GREEN" in fake.prompts[1]


def test_a_draft_that_changes_the_verdict_is_rejected():
    changed = draft(findings=[GOOD["findings"][0], "Retain the fund."])
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(changed, changed, changed)))
    assert result.source == "template" and any("uses 'Retain'" in line for line in result.log)


def test_wrong_number_of_findings_is_invalid_output_and_retried():
    fake = FakeRun(draft(findings=GOOD["findings"] + ["A third."]), draft())
    result = asyncio.run(write_narrative(FACTS, run=fake))
    assert result.source == "ai" and len(fake.prompts) == 2


def test_invalid_output_twice_uses_the_template():
    result = asyncio.run(write_narrative(FACTS, run=FakeRun({"findings": "x"}, {"actions": []})))
    assert result.source == "template" and result.flags[0].message.startswith(AI_TEXT_UNAVAILABLE)


def test_market_context_without_search_summaries_is_dropped():
    result = asyncio.run(write_narrative(FACTS, run=FakeRun(draft(market_context="Tech stocks led, up 25.0%."))))
    assert result.source == "ai" and result.output.market_context is None


def test_no_minus_sign_after_behind_or_below():
    bad = _out(findings=["The fund was behind by -0.10% a year over 5 years.", "It sat below the index by −0.7 pp."])
    assert len([p for p in problems(bad, FACTS) if p.startswith("style")]) == 2


def test_periods_are_written_in_words():
    issues = problems(_out(findings=["The fund returned 13.8% a year over 5y.", GOOD["findings"][1]]), FACTS)
    assert issues == ["style: write periods in words, not '5y'"]


def test_at_most_two_sentences_per_finding():
    four = "The fund tracks its index. It returned 13.8% a year over 5 years. Its index did too. That is all."
    issues = problems(_out(findings=[four, GOOD["findings"][1]]), FACTS)
    assert issues == ["style: finding 2 has 4 sentences; use at most 2"]


# Data notes: insights, what each note explains, the template
NOTES = [{"kind": "pricing", "note": "Noon pricing.", "explains": "the 5-year cumulative gap at noon prices",
          "figures": [
              {"label": "Gap at noon prices (NAV vs index), 5y", "value": -3.3, "unit": "pp", "display": "-3.3 pp", "key": True},
              {"label": "Fair gap (PNAV vs index), 5y", "value": -0.7, "unit": "pp", "display": "-0.7 pp"}]},
         {"kind": "fee", "note": "Most of the yearly gap to the index is the fee.",
          "explains": "the yearly tracking difference", "figures": [
              {"label": "Tracking difference, a year, 5y", "value": -0.1, "unit": "pp", "display": "-0.10 pp"},
              {"label": "Fund behind its index, in plain terms (% a year), 5y", "value": -0.1, "unit": "%", "display": "-0.10%"},
              {"label": "Ongoing charge (OCF), a year", "value": 0.06, "unit": "%", "display": "0.06%", "key": True},
              {"label": "Cost-adjusted tracking difference, a year, 5y", "value": -0.04, "unit": "pp", "display": "-0.04 pp"},
              {"label": "Cost-adjusted gap, in plain terms (% a year), 5y", "value": -0.04, "unit": "%", "display": "-0.04%"}]}]
FACTS_NOTES = FACTS | {"data_notes": NOTES}
COVERED = ["Its noon price makes it look 3.3 pp behind over 5 years. At market close (PNAV) the gap is 0.7 pp.",
           "Most of the yearly gap is the 0.06% yearly fee."]


def test_findings_that_cover_every_data_note_pass():
    assert problems(_out(findings=COVERED), FACTS_NOTES) == []


def test_a_missing_data_note_triggers_the_rewrite():
    without_fee = [COVERED[0], "Value and fees need a peer fund."]
    issues = problems(_out(findings=without_fee), FACTS_NOTES)
    assert len(issues) == 1 and issues[0].startswith("insight: findings 2 and 3 do not cover this data note (use 0.06%)")
    fake = FakeRun(draft(findings=without_fee), draft(findings=COVERED))
    result = asyncio.run(write_narrative(FACTS_NOTES, run=fake))
    assert result.source == "ai" and "insight:" in fake.prompts[1]


def test_the_flag_lists_which_checks_failed():
    bad = draft(findings=["Fees are Green; the fund returned 14.2% over 5y.", "b"])
    result = asyncio.run(write_narrative(FACTS_NOTES, run=FakeRun(bad, bad, bad)))
    assert result.flags[0].message == "AI text failed checks: number / rating / wording / insights; template narrative used"


def test_the_template_covers_every_data_note_and_passes():
    t = template_draft(FACTS_NOTES)
    assert problems(t, FACTS_NOTES) == [] and problems(template_draft(FACTS), FACTS) == []
    assert t.findings[0] == ("Its noon price makes it look 3.3 pp behind its index over 5 years. "
                             "At market close (PNAV) the gap is only 0.7 pp.")
    assert t.findings[1] == ("Most of the yearly gap is the fee, the 0.06% yearly ongoing charge (OCF). With the fee "
                             "added back, the fund is 0.04% a year behind its index over 5 years.")
    assert template(FACTS_NOTES).key_findings[0] == ratings_finding(FACTS_NOTES)


def test_a_mislabelled_figure_counts_as_a_number_problem():
    from test_number_guard import LABEL_FACTS
    facts = FACTS_NOTES | {"figures": FACTS["figures"] + LABEL_FACTS["figures"]}
    bad = ["Over 5 years its tracking difference was -3.3 pp at noon prices.", COVERED[1]]
    issues = problems(_out(findings=bad), facts)
    assert any(i.startswith("label: '-3.3 pp' next to 'tracking difference'") for i in issues)
    assert "number" in failed_checks([i for i in issues if i.startswith("label:")])


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
def test_test1_template_and_finding_1():
    facts = _test1_facts()
    assert problems(template_draft(facts), facts) == []
    assert ratings_finding(facts).startswith("Mandate is Green: the fund moves in line with its index (R² 1.00 and "
                                             "beta 1.00 over 3 years, factsheet). Performance is Green")


@requires_test1
def test_test1_data_notes_say_what_they_explain():
    """ From the full run: the AI tied the fee to the 3.3 pp noon gap """
    notes = {n["kind"]: n for n in _test1_facts()["data_notes"]}
    assert notes["fee"]["explains"].startswith("the yearly tracking difference (-0.10 pp a year over 5 years)")
    assert "does not explain the noon-price gap" in notes["fee"]["explains"]
    assert notes["pricing"]["explains"].startswith("the 5-year cumulative gap at noon prices (-3.3 pp)")
    assert "does not explain the yearly tracking difference" in notes["pricing"]["explains"]


@pytest.mark.live
@requires_test1
def test_live_test1_analyst():
    facts = _test1_facts()
    result = asyncio.run(write_narrative(facts))
    print(f"\n--- Oversight Analyst ({result.source}) ---")
    for i, f in enumerate(result.output.key_findings, start=1):
        print(f" {i}. {f}")
    print("Actions (code):", *result.output.action_texts, sep="\n - ")
    print("Market context:", result.output.market_context)
    print("Log:", *result.log, sep="\n  ")
    print("Flags:", [f.message for f in result.flags])
    assert result.source == "ai"
