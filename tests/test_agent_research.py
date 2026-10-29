""" Planner and parallel Search agents: mocked tests, and one live test on Test 1 (with the Analyst) """
import asyncio
import json
import re
import pytest
from agents import WebSearchTool
from agents.exceptions import AgentsException
from fund_performance.agents.analyst import AnalystOutput, problems, prompt as analyst_prompt, write_narrative
from fund_performance.agents.research import (planner_agent, planner_input, research, search_agent, tidy_plan,
                                              SearchPlan)
from fund_performance.config import load_thresholds
from fund_performance.mandate import decision_path
from fund_performance.models import FundProfile
from fund_performance.scorecard import Pillar, Scorecard
from conftest import FIXTURES, FakeRun, FakeRunBy, TEST1_PROFILE, requires_test1

MAX = load_thresholds().limits.max_web_searches


def profile():
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()))


def card(prof=None):
    prof = prof or profile()
    pillars = {n: Pillar(n, r, "x") for n, r in (("Mandate", "GREEN"), ("Performance", "GREEN"),
                                                  ("Value for investors", "AMBER"), ("Fees", "AMBER"))}
    return Scorecard(pillars, "Monitor until a peer is added", "no peer", decision_path(prof, False, []))


def plan(n=5, **extra):
    return {"searches": [{"topic": ["fund_news", "manager_changes", "market_drivers"][i % 3],
                          "query": f"Sample World Index Fund question {chr(65 + i)}", "reason": "context"}
                         for i in range(n)] + extra.get("more", [])}


def summary_for(prompt_text):
    query = re.search(r"Search query: (.*)", prompt_text).group(1)
    return {"query": query, "summary": f"Sources say something about {query}.",
            "url": f"https://example.com/{query.split()[-1]}", "date": "2026-09-15"}


def test_limits_and_settings(monkeypatch):
    assert MAX == 5
    for agent in ("PLANNER", "SEARCH"):
        monkeypatch.delenv(f"FUND_MODEL_{agent}", raising=False)
    s = search_agent()
    assert s.model == "gpt-5.4-mini" and isinstance(s.tools[0], WebSearchTool) and s.model_settings.tool_choice == "required"
    assert planner_agent(MAX).model == "gpt-5.4-mini" and "up to 5" in planner_agent(MAX).instructions


def test_planner_sees_public_fund_details_only():
    prof = profile()
    text = planner_input(prof, card(prof))
    assert prof.fund_name in text and prof.benchmark_name in text and "Review period: 30 Sep 2025 to 30 Sep 2026" in text
    assert prof.objective_text not in text and "%" not in text          # no figures, no documents


def test_plan_is_capped_and_cleaned():
    raw = SearchPlan.model_validate(plan(7, more=[{"topic": "fund_news", "query": "Sample World Index Fund question A",
                                                   "reason": "repeat"}, {"topic": "fund_news", "query": "x" * 300,
                                                                         "reason": "too long"}]))
    kept, log = tidy_plan(raw, MAX)
    assert len(kept) == 5 and len(log) == 3


def test_searches_run_in_parallel_one_each():
    started, all_started = [], asyncio.Event()

    async def answer(prompt_text):
        started.append(prompt_text)
        if len(started) == MAX:
            all_started.set()
        await all_started.wait()                     # would wait for ever if searches ran one at a time
        return summary_for(prompt_text)

    async def go():
        return await asyncio.wait_for(research(profile(), card(), MAX, run_planner=FakeRun(plan(8)),
                                               run_search=FakeRunBy(answer)), timeout=5)
    out = asyncio.run(go())
    assert len(out.plan) == 5 and len(out.summaries) == 5 and len(started) == 5 and out.flags == []
    assert all(s["url"].startswith("https://") for s in out.summaries)


def test_search_prompt_holds_only_the_query_and_reason():
    fake = FakeRunBy(summary_for)
    asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun(plan(1)), run_search=fake))
    assert fake.prompts == ["Search query: Sample World Index Fund question A\nReason: context"]


def test_a_failed_search_is_not_retried_and_is_left_out():
    calls = {}

    def answer(prompt_text):
        calls[prompt_text] = calls.get(prompt_text, 0) + 1
        return AgentsException("timeout") if "question B" in prompt_text else summary_for(prompt_text)
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun(plan(5)), run_search=FakeRunBy(answer)))
    assert len(out.summaries) == 4 and set(calls.values()) == {1}
    assert out.flags[0].level == "info" and out.flags[0].message.startswith("1 of 5 web searches")


def test_a_summary_without_a_url_is_left_out_without_retry():
    def answer(prompt_text):
        s = summary_for(prompt_text)
        return s | {"url": "example.com"} if "question A" in prompt_text else s
    fake = FakeRunBy(answer)
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun(plan(2)), run_search=fake))
    assert len(out.summaries) == 1 and len(fake.prompts) == 2


def test_the_planned_query_is_kept_and_bad_dates_dropped():
    def answer(prompt_text):
        return summary_for(prompt_text) | {"query": "something else", "date": "September 2026"}
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun(plan(1)), run_search=FakeRunBy(answer)))
    assert out.summaries[0]["query"] == "Sample World Index Fund question A" and out.summaries[0]["date"] is None


def test_planner_failure_means_no_research_but_the_review_goes_on():
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun({"searches": "x"}, {"plan": []})))
    assert out.summaries == [] and out.flags[0].level == "warning" and "no market context" in out.flags[0].message


# The Analyst with search summaries
FACTS = {"scorecard": {"verdict": "Monitor until a peer is added", "verdict_reason": "x",
                       "pillars": [{"name": "Performance", "rating": "GREEN", "reason": "x", "summary": None,
                                    "sub_ratings": [], "notes": []}]},
         "figures": [{"value": 13.8, "unit": "%"}]}
SUMMARIES = [{"query": "US shares 2026", "summary": "US shares rose 25.3% in the year.",
              "url": "https://example.com/markets?page=3.5", "date": "2026-09-30"}]


def test_market_context_cites_urls_without_tripping_the_number_guard():
    out = AnalystOutput(key_findings=["a", "b", "c"], actions=["x", "y"],
                        market_context="US shares rose, led by technology (https://example.com/markets?page=3.5).")
    assert problems(out, FACTS) == []


def test_figures_from_search_summaries_are_not_allowed():
    out = AnalystOutput(key_findings=["a", "b", "c"], actions=["x", "y"],
                        market_context="US shares rose 25.3% (https://example.com/markets?page=3.5).")
    assert problems(out, FACTS) == ["number not in the facts: 25.3%"]


def test_summaries_reach_the_analyst_and_market_context_is_kept():
    good = {"key_findings": ["a", "b", "c"], "actions": ["x", "y"],
            "market_context": "US shares rose, led by technology (https://example.com/markets?page=3.5)."}
    fake = FakeRun(good)
    result = asyncio.run(write_narrative(FACTS, SUMMARIES, run=fake))
    assert result.source == "ai" and result.output.market_context.startswith("US shares rose")
    assert "https://example.com/markets?page=3.5" in fake.prompts[0] == analyst_prompt(FACTS, SUMMARIES)


@pytest.mark.live
@requires_test1
def test_live_test1_research_and_analyst():
    from test_agent_analyst import _test1_facts
    from fund_performance.io import read_json
    from fund_performance.calc import calculate
    from fund_performance.checks import check_prices
    from fund_performance.precedence import apply_precedence
    from fund_performance.scorecard import score
    from fund_performance.io import read_prices
    from conftest import TEST1_CSV, TEST1_FACTSHEET
    T = load_thresholds()
    prof, fs = read_json(TEST1_PROFILE), read_json(TEST1_FACTSHEET)
    checked = check_prices(read_prices(TEST1_CSV), prof, T, fs)
    reported = apply_precedence(calculate(checked.prices, prof, T, fs), checked.flags, prof, T, fs, checked.comparison)
    scorecard = score(reported, prof, T, decision_path(prof, checked.short_history, reported.flags), None,
                      checked.comparison.fund_series, checked.comparison.extra_tolerance_pp)

    found = asyncio.run(research(prof, scorecard, MAX))
    print("\n--- Planner ---")
    for item in found.plan:
        print(f" [{item.topic}] {item.query}  ({item.reason})")
    print("--- Search summaries ---")
    for s in found.summaries:
        print(f" - {s['query']}\n   {s['summary']}\n   {s['url']} ({s['date']})")
    print("Research log:", *found.log, sep="\n  ")

    facts = _test1_facts()
    narrative = asyncio.run(write_narrative(facts, found.summaries))
    print(f"\n--- Oversight Analyst ({narrative.source}) ---")
    for f in narrative.output.key_findings:
        print(" -", f)
    print("Actions:")
    for a in narrative.output.actions:
        print(" -", a)
    print("Market context:", narrative.output.market_context)
    print("Analyst log:", *narrative.log, sep="\n  ")

    assert 1 <= len(found.plan) <= MAX and found.summaries
    assert all(s["url"].startswith("http") for s in found.summaries)
    assert problems(narrative.output, facts) == []
