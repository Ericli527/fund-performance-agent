""" Oversight Analyst (v1): code writes all the findings and the actions; the AI writes only the market context,
which code checks. Mocked pass / rewrites / fallback; one live test on Test 1 that prints the text """
import asyncio
import pytest
from fund_performance.agents.analyst import (AI_TEXT_UNAVAILABLE, CHECKS_FAILED, LEFT_OUT, AnalystDraft, analyst_agent,
                                             code_actions, code_findings, failed_checks, problems, ratings_finding,
                                             template, write_narrative)
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
SOURCES = [{"query": "S&P 500 review", "summary": "US shares rose, led by technology.", "url": "https://example.com/a",
            "date": "2026-09-30", "date_basis": "published"},
           {"query": "S&P 500 drivers", "summary": "Rate worries weighed in spring.", "url": "https://example.com/b",
            "date": "2026-07-01", "date_basis": "published"}]
GOOD = {"market_context": "US shares rose, led by technology [1]. Worries about interest rates weighed in spring [2]."}


def draft(text=GOOD["market_context"]):
    return {"market_context": text}


def _out(text):
    return AnalystDraft(market_context=text)


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_ANALYST", raising=False)
    agent = analyst_agent()
    assert agent.model == "gpt-5.4" and agent.model_settings.reasoning.effort == "low"
    assert agent.model_settings.temperature is None


def test_the_ai_writes_only_the_market_context():
    assert list(AnalystDraft.model_fields) == ["market_context"]


def test_prompt_carries_the_market_context_rules():
    from fund_performance.agents.analyst import INSTRUCTIONS, STYLE_EXAMPLE
    text = " ".join(INSTRUCTIONS.split())
    for rule in ("Cite them as [1], [2]", "Direction only: no figures at all", "At most 3 sentences",
                 "say which part", "Do not repeat them", STYLE_EXAMPLE):
        assert rule in text, rule


# The findings and the actions: written by code
def test_finding_1_names_the_mandate_and_performance_ratings_with_their_reasons():
    assert ratings_finding(FACTS) == (
        "Mandate is Green: the fund moves in line with its index (R² 1.00 and beta 1.00 over 3 years, factsheet). "
        "Performance is Green: the fund is 0.10% a year behind its index over 5 years, a tracking difference of "
        "-0.10 pp a year; tracking error is 0.02% (over 3 years, factsheet).")


def test_finding_1_for_check_data_and_other_funds_uses_the_reason_in_plain_words():
    facts = FACTS | {"fund": FACTS["fund"] | {"objective_type": "active_target"},
                     "scorecard": FACTS["scorecard"] | {"pillars": [
                         p | {"rating": "CHECK DATA", "reason": "currency mismatch in 5y index"}
                         if p["name"] == "Performance" else p for p in FACTS["scorecard"]["pillars"]]}}
    text = ratings_finding(facts)
    assert "Mandate is Green: R² 1.00 and beta 1.00, 3 years (factsheet)." in text
    assert "Performance needs a data check: currency mismatch in 5 years index." in text


NOTES = [{"kind": "pricing", "note": "Noon pricing.", "explains": "the 5-year cumulative gap at noon prices",
          "figures": [
              {"label": "Gap at noon prices (NAV vs index), 5y", "value": -3.3, "unit": "pp", "display": "-3.3 pp", "key": True},
              {"label": "Fair gap (PNAV vs index), 5y", "value": -0.7, "unit": "pp", "display": "-0.7 pp"}]},
         {"kind": "fee", "note": "Most of the yearly gap to the index is the fee.",
          "explains": "the yearly tracking difference", "figures": [
              {"label": "Tracking difference, a year, 5y", "value": -0.1, "unit": "pp", "display": "-0.10 pp"},
              {"label": "Ongoing charge (OCF), a year", "value": 0.06, "unit": "%", "display": "0.06%", "key": True},
              {"label": "Cost-adjusted gap, in plain terms (% a year), 5y", "value": -0.04, "unit": "%", "display": "-0.04%"}]}]
FACTS_NOTES = FACTS | {"data_notes": NOTES}


def test_code_writes_one_finding_per_data_note_and_defines_pp_once():
    findings = code_findings(FACTS_NOTES)
    assert len(findings) == 3
    assert "a tracking difference of -0.10 pp (percentage points) a year" in findings[0]
    assert findings[1] == ("Its noon price makes it look 3.3 pp behind its index over 5 years. "
                           "At market close (PNAV) the gap is only 0.7 pp.")
    assert findings[2] == ("Most of the yearly gap is the fee, the 0.06% yearly ongoing charge (OCF). With the fee "
                           "added back, the fund is 0.04% a year behind its index over 5 years.")
    assert " ".join(findings).count("percentage points") == 1


def test_without_data_notes_the_other_ratings_fill_in():
    findings = code_findings(FACTS)
    assert findings[1] == "Value for investors needs a peer fund to be judged; Fees needs a peer fund to be judged."


def test_the_narrative_puts_code_and_ai_text_together():
    fake = FakeRun(draft())
    result = asyncio.run(write_narrative(FACTS_NOTES, SOURCES, run=fake))
    assert result.source == "ai" and result.flags == [] and len(fake.prompts) == 1
    assert result.output.key_findings == code_findings(FACTS_NOTES)
    assert result.output.actions == code_actions(FACTS_NOTES)
    assert result.output.market_context == GOOD["market_context"]
    assert "Written by code (do not repeat):\nFindings:\n- Mandate is Green" in fake.prompts[0]
    assert len(result.sources) == 2


def test_without_sources_the_ai_is_not_called():
    fake = FakeRun()
    result = asyncio.run(write_narrative(FACTS_NOTES, [], run=fake))
    assert fake.prompts == [] and result.source == "code" and result.output == template(FACTS_NOTES)
    assert result.output.market_context is None and result.flags == []


# Code's checks on the market context, and the rewrites
@pytest.mark.parametrize("text, problem", [
    ("US shares rose 25.3% [1].", "number in the market context: 25.3%"),
    ("US shares rose by 3.3 pp [1].", "number in the market context: 3.3 pp"),
    ("US shares rose (https://example.com/a).", "citation: web address in the text"),
    ("US shares rose [3].", "citation: [3] does not match a source"),
    ("Shares rose [1]. They fell [2]. They rose [1]. They fell [2].", "style: the market context has 4 sentences"),
    ("Over 12m shares rose [1].", "style: write periods in words"),
    ("Mandate is Red as shares rose [1].", "rating:"),
])
def test_market_context_checks(text, problem):
    found = problems(_out(text), FACTS, sources=2)
    assert any(p.startswith(problem) for p in found), found


def test_a_good_market_context_passes():
    assert problems(_out(GOOD["market_context"]), FACTS, sources=2) == []
    assert problems(_out("US shares rose in 2026, led by technology [1]."), FACTS, sources=2) == []   # a year is fine


def test_one_rewrite_with_the_problems():
    fake = FakeRun(draft("US shares rose 25.3% [1]."), draft())
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=fake))
    assert result.source == "ai" and len(fake.prompts) == 2 and "number in the market context: 25.3%" in fake.prompts[1]
    assert result.log[-1] == "Analyst draft 2 passed the figure, rating and wording checks"


def test_code_checks_get_two_rewrites_then_the_market_context_is_left_out():
    bad = draft("US shares rose 25.3% [1].")
    fake = FakeRun(bad, bad, bad)
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=fake))
    assert result.source == "template" and len(fake.prompts) == 3 and result.output == template(FACTS)
    assert result.flags[0].message == f"{CHECKS_FAILED}: number; {LEFT_OUT}"


def test_every_rewrite_gets_all_the_issues_so_far():
    fake = FakeRun(draft("US shares rose 25.3% [1]."), draft("US shares rose [3]."), draft())
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=fake))
    assert result.source == "ai"
    current, earlier = fake.prompts[2].split("It was rejected for these reasons:")[1].split("Earlier drafts were rejected")
    assert "[3] does not match a source" in current and "25.3%" in earlier
    assert "Keep every rule your previous draft already passed" in fake.prompts[2]


def test_rewrite_budget_comes_from_the_config():
    limits = load_thresholds().limits
    assert (limits.max_analyst_rewrites, limits.max_evaluator_rewrites) == (2, 1)


def test_the_flag_lists_which_checks_failed():
    bad = draft("Fees are Green; shares rose 14.2% over 5y [9].")
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=FakeRun(bad, bad, bad)))
    assert failed_checks(problems(_out(bad["market_context"]), FACTS, 2)) == ["number", "rating", "wording"]
    assert result.flags[0].message == f"{CHECKS_FAILED}: number / rating / wording; {LEFT_OUT}"


def test_invalid_output_twice_leaves_the_market_context_out():
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=FakeRun({"x": 1}, {"y": 2})))
    assert result.source == "template" and result.flags[0].message == f"{AI_TEXT_UNAVAILABLE}: {LEFT_OUT}"


def test_a_null_market_context_is_accepted():
    result = asyncio.run(write_narrative(FACTS, SOURCES, run=FakeRun(draft(None))))
    assert result.source == "ai" and result.output.market_context is None and result.sources == []


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
def test_test1_findings():
    findings = code_findings(_test1_facts())
    assert findings[0].startswith("Mandate is Green: the fund moves in line with its index (R² 1.00 and beta 1.00 "
                                  "over 3 years, factsheet). Performance is Green")
    assert "3.3 pp behind its index over 5 years" in findings[1] and "0.06% yearly ongoing charge" in findings[2]


@requires_test1
def test_test1_data_notes_say_what_they_explain():
    """ From the full run: the AI tied the fee to the 3.3 pp noon gap """
    notes = {n["kind"]: n for n in _test1_facts()["data_notes"]}
    assert notes["fee"]["explains"].startswith("the yearly tracking difference (-0.10 pp a year over 5 years)")
    assert "does not explain the noon-price gap" in notes["fee"]["explains"]
    assert notes["pricing"]["explains"].startswith("the 5-year cumulative gap at noon prices (-3.3 pp)")


@pytest.mark.live
@requires_test1
def test_live_test1_analyst():
    facts = _test1_facts()
    result = asyncio.run(write_narrative(facts, SOURCES))
    print(f"\n--- Oversight Analyst ({result.source}) ---")
    print("Market context:", result.output.market_context)
    print("Log:", *result.log, sep="\n  ")
    print("Flags:", [f.message for f in result.flags])
    assert result.source == "ai"
