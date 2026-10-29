""" Planner and parallel Search agents: mocked tests, and one live test on Test 1 (with the Analyst) """
import asyncio
import json
import re
import pytest
from agents import WebSearchTool
from agents.exceptions import AgentsException
from fund_performance.agents.analyst import AnalystOutput, problems, prompt as analyst_prompt, write_narrative
from fund_performance.agents.research import (FIGURES_DIFFER, page_agent, planner_agent, planner_input, research,
                                              search_agent, tidy_plan, vet_summaries, SearchPlan)
from fund_performance.config import ApprovedSource, load_thresholds
from fund_performance.fetch import FetchedPage
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
    topics = ["fund_news", "manager_changes", "market_drivers"]
    return {"searches": [{"topic": topics[i % 3],
                          "query": (f"Global shares question {chr(65 + i)}" if topics[i % 3] == "market_drivers"
                                    else f"Sample World Index Fund question {chr(65 + i)}"), "reason": "context"}
                         for i in range(n)] + extra.get("more", [])}


def summary_for(prompt_text):
    query = re.search(r"Search query: (.*)", prompt_text).group(1)
    return {"query": query, "summary": f"Sources say something about {query}.",
            "url": f"https://example.com/{query.split()[-1]}", "date": "2026-09-15", "date_basis": "published"}


def test_limits_and_settings(monkeypatch):
    assert MAX == 3
    for agent in ("PLANNER", "SEARCH"):
        monkeypatch.delenv(f"FUND_MODEL_{agent}", raising=False)
    s = search_agent()
    assert s.model == "gpt-5.4-mini" and isinstance(s.tools[0], WebSearchTool) and s.model_settings.tool_choice == "required"
    assert planner_agent(MAX).model == "gpt-5.4-mini" and "up to 3" in planner_agent(MAX).instructions


def test_planner_sees_public_fund_details_only():
    prof = profile()
    text = planner_input(prof, card(prof))
    assert prof.fund_name in text and prof.benchmark_name in text
    assert "Review period: Oct 2025 to Sep 2026 (30 Sep 2025 to 30 Sep 2026" in text
    assert prof.objective_text not in text and "%" not in text          # no figures, no documents


def test_plan_is_capped_and_cleaned():
    raw = SearchPlan.model_validate(plan(7, more=[{"topic": "fund_news", "query": "Sample World Index Fund question A",
                                                   "reason": "repeat"}, {"topic": "fund_news", "query": "x" * 300,
                                                                         "reason": "too long"}]))
    kept, log = tidy_plan(raw, MAX)
    assert len(kept) == 3 and len(log) == 3


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
    assert len(out.plan) == 3 and len(out.summaries) == 3 and len(started) == 3 and out.flags == []
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
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun(plan(3)), run_search=FakeRunBy(answer)))
    assert len(out.summaries) == 2 and set(calls.values()) == {1}
    assert out.flags[0].level == "info" and out.flags[0].message.startswith("1 of 3 web searches")


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
    first = out.summaries[0]
    assert first["query"] == "Sample World Index Fund question A" and first["topic"] == "fund_news"
    assert first["date"] is None and first["date_basis"] is None


def test_planner_failure_means_no_research_but_the_review_goes_on():
    out = asyncio.run(research(profile(), card(), MAX, run_planner=FakeRun({"searches": "x"}, {"plan": []})))
    assert out.summaries == [] and [f.level for f in out.flags] == ["warning", "warning"]
    assert "Planner gave no valid plan" in out.flags[0].message and "no market context" in out.flags[1].message


# Approved sources (step 9b): code fetches the pages, the Search agent summarises them, failures fall back
FUND_SRC = ApprovedSource(name="Fund page", url="https://example.com/fund", topic="fund_news")
DOCS_SRC = ApprovedSource(name="Documents page", url="https://example.com/docs", topic="fund_news")
INDEX_SRC = ApprovedSource(name="Index page", url="https://example.com/index", topic="market_drivers")


def page(source, ok=True):
    return (FetchedPage(source, text=f"Text of the {source.name}.", title=source.name) if ok
            else FetchedPage(source, problem="nearly empty (12 characters of text; likely JavaScript-only or blocked)"))


def page_summary(prompt_text):
    name = re.search(r"Source: (.*)", prompt_text).group(1)
    return {"summary": f"Sample World Index Fund A Acc and the Sample World market, from the {name}.",
            "date": "2026-09-30", "date_basis": "as_at"}


def test_approved_pages_are_summarised_with_the_url_from_the_config():
    pages_run = FakeRunBy(page_summary)
    out = asyncio.run(research(profile(), card(), MAX, [page(FUND_SRC), page(INDEX_SRC)],
                               run_planner=FakeRun(plan(1)), run_search=FakeRunBy(summary_for), run_page=pages_run))
    first, second = out.summaries[:2]
    assert first["url"] == FUND_SRC.url and first["query"] == "Approved source: Fund page" and first["topic"] == "fund_news"
    assert second["url"] == INDEX_SRC.url and second["topic"] == "market_drivers" and second["date_basis"] == "as_at"
    assert len(out.summaries) == 3 and out.flags == []                     # 2 pages, then 1 planned search
    assert all("Page text:\nText of the" in p for p in pages_run.prompts)
    assert page_agent().tools == []                                        # reads the given text; no web tool


def test_an_agent_given_url_is_never_used():
    out = asyncio.run(research(profile(), card(), MAX, [page(FUND_SRC)], run_planner=FakeRun({"searches": []}),
                               run_page=FakeRunBy(lambda p: page_summary(p) | {"url": "https://elsewhere.com"})))
    assert out.summaries == [] and "could not be summarised" in out.flags[0].message


def test_an_empty_page_is_flagged_and_replaced_by_a_web_search_from_the_budget():
    planner = FakeRun(plan(8))
    search = FakeRunBy(summary_for)
    out = asyncio.run(research(profile(), card(), MAX, [page(FUND_SRC), page(INDEX_SRC, ok=False)],
                               run_planner=planner, run_search=search, run_page=FakeRunBy(page_summary)))
    assert out.flags[0].level == "info" and out.flags[0].message.startswith("Approved source Index page nearly empty")
    assert "web search used instead (https://example.com/index)" in out.flags[0].message
    assert len(out.plan) == MAX and out.plan[0].query == "Sample World review Oct 2025 to Sep 2026"
    assert "Sample World Index Fund" not in out.plan[0].query                # a market query never names the fund
    assert "Already read from approved sources: Fund page" in planner.prompts[0]
    assert len(search.prompts) == MAX and len(out.summaries) == 1 + MAX


def test_fallbacks_use_the_budget_first_and_the_planner_gets_what_is_left():
    planner = FakeRun()                                                    # must not be called
    out = asyncio.run(research(profile(), card(), 1, [page(FUND_SRC, False), page(DOCS_SRC, False), page(INDEX_SRC, False)],
                               run_planner=planner, run_search=FakeRunBy(summary_for)))
    assert [p.query for p in out.plan] == ["Sample World Index Fund A Acc XX0000000001 fund changes Oct 2025 to Sep 2026"]
    messages = [f.message for f in out.flags]
    assert "web search used instead" in messages[0]
    assert "covered by the same web search as another page" in messages[1]
    assert "no web search left to replace it" in messages[2]
    assert planner.prompts == [] and any("budget went to replacing approved pages" in line for line in out.log)


def test_approved_page_summaries_get_the_same_checks_as_web_results():
    prof = profile()
    good = {"query": "Approved source: Fund page", "topic": "fund_news", "url": FUND_SRC.url, "date": "2026-09-30",
            "date_basis": "as_at", "summary": "Sample World Index Fund A Acc charges 0.10% a year."}
    old = good | {"date": "2024-03-31"}
    other = good | {"summary": "Another Manager Global Fund changed its index."}
    market = good | {"topic": "market_drivers", "url": INDEX_SRC.url, "summary": "Bond yields rose."}
    kept, flags, _ = vet_summaries([good, old, other, market], prof, {"figures": []})
    assert kept == [good] and len(flags) == 3
    assert "as at 2024-03-31, outside the review period" in flags[0].message


# The Analyst with sources
FACTS = {"scorecard": {"verdict": "Monitor until a peer is added", "verdict_reason": "x",
                       "pillars": [{"name": "Performance", "rating": "GREEN", "reason": "x", "summary": None,
                                    "sub_ratings": [], "notes": []}]},
         "figures": [{"value": 13.8, "unit": "%"}]}
SUMMARIES = [{"query": "US shares 2026", "summary": "US shares rose 25.3% in the year.",
              "url": "https://example.com/markets?page=3.5", "date": "2026-09-30"}]


def _context(text):
    return AnalystOutput(key_findings=["a", "b", "c"], actions=["x", "y"], market_context=text)


def test_market_context_cites_numbered_sources():
    assert problems(_context("US shares rose, led by technology [1]."), FACTS, sources=1) == []


def test_web_addresses_in_the_text_are_rejected():
    found = problems(_context("US shares rose (https://example.com/markets?page=3.5)."), FACTS, sources=1)
    assert found == ["citation: web address in the text (https://example.com/markets?page=3.5); "
                     "cite the source as [n] instead"]


def test_a_citation_without_a_source_is_rejected():
    assert problems(_context("US shares rose [2]."), FACTS, sources=1) == ["citation: [2] does not match a source"]


def test_figures_from_sources_are_not_allowed():
    assert problems(_context("US shares rose 25.3% [1]."), FACTS, sources=1) == ["number not in the facts: 25.3%"]


def test_the_analyst_sees_numbered_sources_without_urls_and_the_report_gets_them():
    good = {"key_findings": ["a", "b", "c"], "actions": ["x", "y"], "market_context": "US shares rose, led by technology [1]."}
    fake = FakeRun(good)
    result = asyncio.run(write_narrative(FACTS, SUMMARIES, run=fake))
    assert result.source == "ai" and result.output.market_context.endswith("[1].")
    assert '"source": "[1]"' in fake.prompts[0] and "https://" not in fake.prompts[0]
    assert fake.prompts[0] == analyst_prompt(FACTS, SUMMARIES)
    assert result.sources == [{"number": 1, **SUMMARIES[0]}]


# Planner rules and vetting the summaries
def test_planner_and_search_rules():
    text = planner_agent(MAX).instructions
    assert "never the fund" in text and "S&P 500 performance drivers Oct 2025 to Sep 2026" in text
    assert "rather than fund data pages" in text
    assert "index-provider sources" in search_agent().instructions


def test_a_market_query_that_names_the_fund_is_dropped():
    prof = profile()
    raw = SearchPlan.model_validate({"searches": [
        {"topic": "market_drivers", "query": "Sample World Index Fund drivers 2026", "reason": "x"},
        {"topic": "market_drivers", "query": "XX0000000001 market news", "reason": "x"},
        {"topic": "market_drivers", "query": "Global shares drivers Oct 2025 to Sep 2026", "reason": "x"},
        {"topic": "fund_news", "query": "Sample World Index Fund fee change", "reason": "x"}]})
    kept, log = tidy_plan(raw, MAX, prof)
    assert [k.query for k in kept] == ["Global shares drivers Oct 2025 to Sep 2026", "Sample World Index Fund fee change"]
    assert len(log) == 2 and all("names the fund" in line for line in log)


def _s(summary, date="2026-06-30", url="https://news.example/a", topic="fund_news", basis="published"):
    return {"query": "q", "topic": topic, "summary": summary, "url": url, "date": date, "date_basis": basis}


VET_FACTS = {"fund": {"as_of_date": "2026-09-30"},
             "figures": [{"name": "fund_nav.cum.1y", "value": 17.5, "unit": "%"},
                         {"name": "fund_pnav.cum.1y", "value": 17.0, "unit": "%"},
                         {"name": "index.cum.1y", "value": 17.1, "unit": "%"},
                         {"name": "fund_nav.calendar.2025", "value": 9.6, "unit": "%"},
                         {"name": "index.ann.5y", "value": 13.9, "unit": "%"}]}


@pytest.mark.parametrize("summary,topic,kept", [
    ("Sample World Index Fund returned 11.99% over 1 year.", "fund_news", False),     # e.g. a USD data page
    ("Sample World Index Fund returned 17.3% over 1 year.", "fund_news", True),       # within 0.5 pp of 17.5
    ("Sample World Index Fund gained 9.4% in 2025.", "fund_news", True),
    ("Sample World Index Fund gained 12.0% in 2025.", "fund_news", False),
    ("The Sample World market rose 13.9% a year over 5 years.", "market_drivers", True),
    ("The Sample World market rose; one sector gained 40% in the year.", "market_drivers", True),  # a sector, not the index
])
def test_returns_that_differ_from_the_factsheet_exclude_the_summary(summary, topic, kept):
    out, flags, _ = vet_summaries([_s(summary, topic=topic)], profile(), VET_FACTS)
    assert bool(out) == kept
    if not kept:
        assert flags[0].level == "info" and flags[0].message.startswith(FIGURES_DIFFER)


@pytest.mark.parametrize("date,reason", [(None, "has no date"), ("2025-09-29", "outside the review period"),
                                          ("2026-10-01", "outside the review period")])
def test_undated_or_out_of_period_market_news_is_excluded(date, reason):
    out, flags, _ = vet_summaries([_s("Sample World shares rose.", date=date, topic="market_drivers")], profile(), VET_FACTS)
    assert out == [] and reason in flags[0].message and flags[0].level == "info"


def test_approved_sources_and_fund_facts_may_be_dated_after_the_period_end():
    """ Bug from the Test 1 run: both Fidelity pages were excluded for "as at 2026-10-29" (after 30 Sep 2026) """
    fund_page = _s("Sample World Index Fund A Acc charges 0.10% a year.", date="2026-10-29", basis="as_at",
                   url="https://example.com/fund") | {"query": "Approved source: Fund page", "approved": True}
    index_page = _s("Sample World shares rose.", date="2026-10-29", basis="as_at", topic="market_drivers",
                    url="https://example.com/index") | {"approved": True}
    manager = _s("Sample World Index Fund A Acc has a new manager.", date="2026-10-15", topic="manager_changes")
    market_news = _s("Sample World shares rose.", date="2026-10-15", topic="market_drivers")
    too_old = fund_page | {"date": "2025-09-29"}
    kept, flags, _ = vet_summaries([fund_page, index_page, manager, market_news, too_old], profile(), VET_FACTS)
    assert kept == [fund_page, index_page, manager]
    assert [f.message.split(", outside")[0] for f in flags] == ["web source dated 2026-10-15",
                                                                 "web source as at 2025-09-29"]


@requires_test1
def test_test1_morningstar_usd_figure_is_excluded():
    from test_agent_analyst import _test1_facts
    from fund_performance.io import read_json
    prof = read_json(TEST1_PROFILE)
    morningstar = _s("Fidelity Index US P Acc returned 11.99% over 1 year in USD.", "2026-09-30",
                     "https://www.morningstar.com/funds/x")
    index = _s("The S&P 500 returned 17.1% over 1 year in sterling terms.", "2026-09-30", topic="market_drivers")
    out, flags, _ = vet_summaries([morningstar, index], prof, _test1_facts())
    assert out == [index] and "11.99% (fund, 1y)" in flags[0].message


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
    facts = _test1_facts()
    vetted, vet_flags, vet_log = vet_summaries(found.summaries, prof, facts)
    print("\n--- Planner ---")
    for item in found.plan:
        print(f" [{item.topic}] {item.query}  ({item.reason})")
    print("--- Search summaries ---")
    for s in found.summaries:
        print(f" - {s['query']}\n   {s['summary']}\n   {s['url']} ({s['date']})")
    print("Research log:", *found.log, *vet_log, sep="\n  ")
    print("Excluded:", *[f.message for f in vet_flags], sep="\n  ")

    narrative = asyncio.run(write_narrative(facts, vetted))
    print(f"\n--- Oversight Analyst ({narrative.source}) ---")
    for f in narrative.output.key_findings:
        print(" -", f)
    print("Actions:")
    for a in narrative.output.actions:
        print(" -", a)
    print("Market context:", narrative.output.market_context)
    print("Sources:", *[f"[{s['number']}] {s['url']} ({s['date']})" for s in narrative.sources], sep="\n  ")
    print("Analyst log:", *narrative.log, sep="\n  ")

    assert 1 <= len(found.plan) <= MAX and found.summaries
    assert all(s["url"].startswith("http") for s in found.summaries)
    assert problems(narrative.output, facts, len(vetted)) == []


# Part 1 fixes: "as at" dates, relevance, whole-period market queries
def test_an_as_at_date_counts_and_only_no_date_at_all_is_excluded():
    kept, _, _ = vet_summaries([_s("Sample World Index Fund page.", date="2026-09-30", basis="as_at")], profile(), VET_FACTS)
    assert len(kept) == 1
    out, flags, _ = vet_summaries([_s("Sample World Index Fund page.", date=None, basis=None)], profile(), VET_FACTS)
    assert out == [] and "no date (published or as at)" in flags[0].message


def test_search_instructions_ask_for_as_at_dates():
    assert '"as_at"' in search_agent().instructions and '"updated" date' in search_agent().instructions


@pytest.mark.parametrize("summary,url,kept", [
    ("Sample World Index Fund cut its fee.", "https://news.example/a", True),
    ("XX0000000001 changed its index.", "https://news.example/a", True),                   # by ISIN
    ("Sample A Acc share class closed.", "https://news.example/a", True),                   # brand + share class
    ("Another Index Fund changed its manager.", "https://news.example/a", False),            # a different fund
    ("Sample World Index Fund annual report filed.", "https://www.sec.gov/Archives/x", False),  # US filing, non-US fund
])
def test_fund_news_must_be_about_this_fund_and_jurisdiction(summary, url, kept):
    out, flags, _ = vet_summaries([_s(summary, url=url)], profile(), VET_FACTS)
    assert bool(out) == kept
    if not kept:
        assert flags[0].message.startswith("web source about a different fund or jurisdiction: excluded")


def test_market_news_must_be_about_the_market():
    out, flags, _ = vet_summaries([_s("Bond yields rose in Japan.", topic="market_drivers")], profile(), VET_FACTS)
    assert out == [] and flags[0].message.startswith("web source not about the fund's market")


def test_market_queries_ask_for_the_whole_period_when_it_is_longer_than_3_months():
    text = planner_input(profile(), card())
    assert 'Market-driver queries must ask for a review of the whole period, e.g. "Sample World review Oct 2025 to Sep 2026"' in text


@requires_test1
def test_test1_sec_filing_is_excluded():
    from test_agent_analyst import _test1_facts
    from fund_performance.io import read_json
    sec = _s("Fidelity 500 Index Fund filed its annual report on Form N-CSR.", "2026-04-30",
             "https://www.sec.gov/Archives/edgar/data/x.htm")
    out, flags, _ = vet_summaries([sec], read_json(TEST1_PROFILE), _test1_facts())
    assert out == [] and flags[0].level == "info" and "different fund or jurisdiction" in flags[0].message
