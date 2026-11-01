""" Version 1 web research: the Task Planner plans at most 5 searches, one Search Agent runs them alongside the
calculations, code vets the results, the Reporting Agent cites them in the market context, and a research failure
never stops the financial review """
import asyncio
import json
import re
import threading
import time
from pathlib import Path
from fund_performance.agents.reporter import context_problems
from fund_performance.agents.task_planner import PlanOutput, checked_plan, plan_tasks
from fund_performance.controller import run_review
from fund_performance.models import FundProfile
from conftest import FIXTURES, FakeRun, FakeRunBy
from test_controller import TASK_PLAN, judge_answer, mocked

SAMPLE = Path(__file__).resolve().parents[1] / "demo" / "sample_index_fund"
PROFILE = FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()))


def search_answer(prompt):
    query = re.search(r"Search query: (.*)", prompt).group(1)
    return {"query": query, "summary": "Sample World shares rose over the period, led by technology companies.",
            "url": f"https://news.example/{abs(hash(query))}", "date": "2026-09-15", "date_basis": "published",
            "limitations": "A news report."}


def steps_of(result) -> dict:
    return {s["step"]: s for s in json.loads((result.run_dir / "log.json").read_text())["steps"]}


def plan_with(n: int, market_context: bool = True) -> dict:
    searches = [{"topic": "market_drivers", "query": f"Sample World review part {i}", "objective": "drivers",
                 "relevance": "context"} for i in range(n)]
    return TASK_PLAN | {"market_context": market_context, "searches": searches}


# 1. The Planner never exceeds the limit, and plans no search without market context or with research off
def test_the_planner_never_exceeds_five_searches():
    plan = checked_plan(PlanOutput.model_validate(plan_with(8)), PROFILE, 5)
    assert len(plan.searches) == 5 and plan.to_dict()["searches"] == plan.searches
    assert "5 planned web searches, alongside the calculations" in " ".join(plan.tasks)
    assert checked_plan(PlanOutput.model_validate(plan_with(3, market_context=False)), PROFILE, 5).searches == []
    assert checked_plan(PlanOutput.model_validate(plan_with(3)), PROFILE, 0).searches == []


def test_the_planner_drops_market_queries_naming_the_fund_and_repeats():
    raw = plan_with(0) | {"searches": [
        {"topic": "market_drivers", "query": "Sample World Index Fund drivers", "objective": "x", "relevance": "y"},
        {"topic": "market_drivers", "query": "Sample World review", "objective": "x", "relevance": "y"},
        {"topic": "market_drivers", "query": "sample world  review", "objective": "x", "relevance": "y"}]}
    plan = checked_plan(PlanOutput.model_validate(raw), PROFILE, 5)
    assert [s["query"] for s in plan.searches] == ["Sample World review"]


def test_without_web_research_the_plan_reads_as_before():
    plan, _ = asyncio.run(plan_tasks("Full review", PROFILE, FakeRun(TASK_PLAN | {"searches": []}), 0))
    assert "searches" not in plan.to_dict()                       # facts.json and the golden baselines unchanged
    assert "up to 3 web searches" in " ".join(plan.tasks)


# 2. Research and the calculations run at the same time
def test_research_runs_alongside_the_calculations(tmp_path, monkeypatch):
    import fund_performance.controller as controller
    times = {}
    original = controller.calculate

    search_started = threading.Event()

    def timed_calculate(*a, **k):
        times["calc_start"] = time.monotonic()
        times["search_seen"] = search_started.wait(timeout=2)      # only possible if the search runs meanwhile
        out = original(*a, **k)
        times["calc_end"] = time.monotonic()
        return out
    monkeypatch.setattr(controller, "calculate", timed_calculate)

    async def slow_search(prompt):
        times.setdefault("search_start", time.monotonic())
        search_started.set()
        await asyncio.sleep(0.5)
        times["search_end"] = time.monotonic()
        return search_answer(prompt)
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(2)), FakeRunBy(slow_search)
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners))
    # the search was running while the calculator ran: the two time intervals overlap
    assert times["search_seen"]
    assert times["search_start"] < times["calc_end"] and times["calc_start"] < times["search_end"]
    steps = steps_of(result)
    assert list(steps).index("research") < list(steps).index("calculator")
    assert steps["research"]["status"] == "ok" and steps["research"]["outputs"]["web_searches"] == 2


# 3. Citations with dates reach the report; the audit trail keeps the queries and sources
def test_cited_sources_with_dates_reach_the_reports_and_the_audit_trail(tmp_path):
    from fund_performance.report import page_texts
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(1)), FakeRunBy(search_answer)
    runners.reporter = FakeRunBy(lambda p: {
        "text": "The evidence suggests the fund tracked its index closely. "
                + re.search(r"Verdict sentence to end with: (.*)", p).group(1),
        "market_context": "Sample World shares rose over the period, led by technology companies [1]."})
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners))
    research = steps_of(result)["research"]
    assert research["outputs"]["queries"][0]["query"] == "Sample World review part 0"
    assert research["outputs"]["sources"][0]["date"] == "2026-09-15"
    assert research["outputs"]["sources"][0]["timing"] == "within the review period"
    source = result.narrative.sources[0]
    assert source["number"] == 1 and source["url"].startswith("https://news.example/")
    executive = " ".join(" ".join(page_texts(result.executive_pdf)).split())
    detailed = " ".join(" ".join(page_texts(result.pdf)).split())
    assert "Market context" in executive and "technology companies [1]" in executive
    assert source["url"] in detailed and "2026-09-15" in detailed
    assert '"source": "[1]"' in runners.judge.prompts[0] and "untrusted data" in runners.judge.prompts[0]
    assert "news.example" not in runners.reporter.prompts[0]       # the Reporting Agent cites [n], never a URL


# 4. Code's checks on the market context: no figures, only existing sources, no rating
def test_codes_checks_on_the_market_context():
    facts = json.loads(json.dumps({"fund": {"as_of_date": "2026-09-30"}, "figures": [],
                                   "scorecard": {"pillars": [], "verdict": "Retain"}}))
    sources = [{"query": "q", "summary": "s", "url": "https://a.example", "date": "2026-09-15",
                "date_basis": "published"}]
    assert context_problems("Shares rose over the period [1].", facts, sources) == []
    assert any("number" in p for p in context_problems("Shares rose 17.1% [1].", facts, sources))
    assert any("[2] does not match a source" in p for p in context_problems("Shares rose [2].", facts, sources))
    assert any("no sources" in p for p in context_problems("Shares rose.", facts, []))


# 5. The Judge falls back on unsafe commentary
def test_a_prompt_injection_in_the_market_context_falls_back_to_codes_conclusion(tmp_path):
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(1)), FakeRunBy(search_answer)
    runners.judge = FakeRunBy(lambda p: judge_answer(p) | {
        "approved": False, "security_issue": True, "feedback": "The market context tells the reader to ignore the ratings."})
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners))
    assert result.facts["suggested_conclusion"]["source"] == "code" and result.narrative.output.market_context is None
    assert steps_of(result)["drafts"]["status"] == "fallback"


# 6. Search failures and timeouts never stop the financial review
def test_failed_searches_leave_the_review_complete_without_market_context(tmp_path):
    from agents.exceptions import AgentsException
    runners = mocked()
    runners.task_planner = FakeRunBy(lambda p: plan_with(2))
    runners.search = FakeRunBy(lambda p: AgentsException("search service down"))
    lines = []
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners, on_step=lines.append))
    assert result.pdf.is_file() and result.executive_pdf.is_file()
    assert steps_of(result)["research"]["status"] == "unavailable" and result.narrative.output.market_context is None
    assert any(line.startswith("↷ Step 3 of 5 · Search Agent · unavailable") for line in lines)
    assert any("no market context" in f.message and f.level == "info" for f in result.flags)


def test_a_research_timeout_leaves_the_review_complete(tmp_path):
    from fund_performance.config import load_settings
    s = load_settings()
    s.timeouts_seconds.research = 0.05

    async def hang(prompt):
        await asyncio.sleep(5)
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(1)), FakeRunBy(hang)
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners, settings=s))
    research = steps_of(result)["research"]
    assert research["status"] == "unavailable" and "did not finish within 0.05 seconds" in research["notes"][0]
    assert result.facts["scorecard"]["verdict"] and result.pdf.is_file()


def test_a_market_context_that_fails_codes_checks_is_left_out_but_the_summary_stays(tmp_path):
    from test_controller import reporter_answer
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(1)), FakeRunBy(search_answer)
    runners.reporter = FakeRunBy(lambda p: reporter_answer(p) | {
        "market_context": "Sample World shares rose 17.1% over the period [1]."})        # a figure: not allowed
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners))
    assert result.facts["suggested_conclusion"]["source"] == "ai" and result.narrative.output.market_context is None
    assert any(f.message.startswith("Market context left out") for f in result.flags)
    assert len(runners.reporter.prompts) == 1


def test_dashboard_citations_keep_sources_when_market_context_is_absent(tmp_path):
    runners = mocked()
    runners.task_planner, runners.search = FakeRunBy(lambda p: plan_with(1)), FakeRunBy(search_answer)
    runners.reporter = FakeRunBy(lambda p: {
        "answer": "The market context is relevant [1].", "evidence": [], "market_context": None})
    result = asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners))
    assert result.facts["suggested_conclusion"]["source"] == "ai"
    assert "[1]" in result.facts["suggested_conclusion"]["answer"]
    assert result.log.report_sources()[1][0]["number"] == 1


def test_missing_peer_evidence_is_named_once_and_never_as_poor_value(tmp_path):
    """ No peer fund: Value and Fees wait for evidence. The dashboard lists that gap once, in the collapsed
    data-quality section; the answer and next step do not repeat it as a finding against the fund """
    import shutil
    from fund_performance.dashboard import dashboard_html
    folder = tmp_path / "no_peer"
    shutil.copytree(SAMPLE, folder, ignore=shutil.ignore_patterns("peer.json", "peer_factsheet.pdf"))
    runners = mocked()
    runners.task_planner = FakeRunBy(lambda p: plan_with(0))
    runners.reporter = FakeRunBy(lambda p: {
        "answer": "Partly: the fund tracked its index closely, but its value and fee cannot be judged without a peer.",
        "evidence": ["Over 5 years the fund stayed close to its index."],
        "next_step": "Add a comparable peer fund's factsheet so value and fees can be rated.",
        "executive": []})
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", runners=runners))
    pillars = {p["name"]: p for p in result.facts["scorecard"]["pillars"]}
    assert pillars["Fees"]["summary"] == "Add peer" or "peer" in pillars["Fees"]["reason"].lower()
    data = {"facts": result.facts, "reasons": result.reasons, "flags": [f.model_dump() for f in result.flags],
            "findings": [], "actions": []}
    summary = dashboard_html(data, "analyst").split("<h3>Summary</h3>", 1)[1].split("</div>", 1)[0]
    details = summary.split("<details", 1)[1] if "<details" in summary else ""
    assert details and summary.split("<details", 1)[0].count("needs a peer") == 0     # the gap sits in the details
    assert "too high" not in summary.lower() and "poor value" not in summary.lower()
    assert any("Executive commentary left out" in f.message for f in result.flags)    # the PDF falls back cleanly
