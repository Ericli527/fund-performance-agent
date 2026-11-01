""" Workflow controller (step 10): stops, limits, timeouts, log.json, and a full Test 1 run with every AI call
mocked (no network) """
import asyncio
import json
import re
import shutil
from pathlib import Path
import pytest
from fund_performance.config import load_settings
from fund_performance.controller import OFFLINE_NOTE, RunStopped, Runners, run_review
from fund_performance.report import page_texts
from conftest import FIXTURES, TEST1, FakeRunBy, requires_test1

FAST = load_settings().model_copy(deep=True)


def settings(**timeouts):
    s = FAST.model_copy(deep=True)
    for k, v in timeouts.items():
        setattr(s.timeouts_seconds, k, v)
    return s


def full_settings(**timeouts):
    """ The features Version 1 switches off in settings.yaml, switched on: one draft per angle and the Judge after
    the rewrite. Their code is kept and tested """
    s = settings(**timeouts)
    s.research.enabled = True
    s.drafting.max_drafts, s.drafting.rejudge_after_rewrite = 3, True
    return s


def log_of(run_dir_parent):
    run_dir = next(run_dir_parent.iterdir())
    return json.loads((run_dir / "log.json").read_text())


# Stops: only when the run cannot be scored
def _folder(tmp_path, *names):
    folder = tmp_path / "in"
    folder.mkdir()
    for name in names:
        shutil.copy(FIXTURES / name, folder / name.replace("_sample", ""))
    return folder


@pytest.mark.parametrize("names, message", [
    ((), "no fund_profile.json"),
    (("fund_profile_sample.json",), "no price file"),
])
def test_missing_inputs_stop_the_run_with_a_clear_message(tmp_path, names, message):
    folder = _folder(tmp_path, *names)
    with pytest.raises(RunStopped, match=message):
        asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))
    log = log_of(tmp_path / "runs")
    assert log["run"]["status"] == "stopped" and message in log["run"]["message"]
    assert log["steps"][-1]["status"] == "stopped"


def test_a_missing_folder_or_an_invalid_profile_stops_the_run(tmp_path):
    with pytest.raises(RunStopped, match="does not exist"):
        asyncio.run(run_review(tmp_path / "nowhere", out_root=tmp_path / "runs1", offline=True))
    folder = _folder(tmp_path, "fund_profile_sample.json")
    profile = json.loads((folder / "fund_profile.json").read_text())
    profile["ocf_pct"] = "a lot"
    (folder / "fund_profile.json").write_text(json.dumps(profile))
    (folder / "prices.csv").write_text("Date,NAV\n2026-08-31,1.0\n2026-09-30,1.1\n")
    with pytest.raises(RunStopped, match="does not match its schema"):
        asyncio.run(run_review(folder, out_root=tmp_path / "runs2", offline=True))


# Test 1 offline: every step logged, sources list from the log
@requires_test1
def test_test1_offline_run_logs_every_step(tmp_path):
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, offline=True))
    log = json.loads((result.run_dir / "log.json").read_text())
    assert [(s["step"], s["status"]) for s in log["steps"]] == [
        ("read_files", "ok"), ("extractor", "skipped"), ("peers", "skipped"), ("data_checks", "ok"),
        ("mandate", "skipped"), ("plan", "skipped"), ("research", "skipped"), ("calculator", "ok"), ("scorecard", "ok"),
        ("investment_assessment", "skipped"), ("drafts", "skipped"), ("report", "ok"), ("email", "skipped")]
    assert log["run"]["status"] == "ok" and all(s["ended"] for s in log["steps"])
    assert log["steps"][8]["outputs"]["verdict"] == "Monitor until a peer is added"
    assert "fund_profile.json" in log["sources"]["input_files"] and log["sources"]["web"] == []
    texts = page_texts(result.pdf)
    appendix = " ".join(texts[next(i for i, x in enumerate(texts) if "Appendix D" in x):])
    assert all(name.split(" (")[0] in appendix for name in log["sources"]["input_files"])
    assert OFFLINE_NOTE in (result.run_dir / "run_log.txt").read_text()
    assert (result.run_dir / "facts.json").exists()


# Test 1 with every AI call, HTTP and nothing else mocked
FUND_PAGE = ("<html><head><title>Fidelity Index US Fund P Accumulation</title></head><body>"
             + "<p>Fidelity Index US Fund P Accumulation (GB00BJS8SH10). Ongoing charge 0.06%. As at 29/10/2026.</p>" * 8
             + "</body></html>")


def http_get(url, settings):
    return (403, "Forbidden") if "spglobal" in url else (200, FUND_PAGE)


def _facts_in(prompt):
    return json.loads(prompt.split("\n", 1)[1].split("\n\nSources:\n")[0])


def analyst_answer(prompt):
    """ A valid market context, citing the first source """
    return {"market_context": "The S&P 500 rose, led by technology shares [1]."}


def mocked(evaluator_answer=None, mandate_delay=0.0, planner_queries=5):
    async def mandate(prompt):
        await asyncio.sleep(mandate_delay)
        return {"objective_type": "index_tracker", "benchmark_role": "target", "time_horizon_years": 5,
                "secondary_objective": None, "secondary_objective_unclassified": None,
                "promises": ["Track the S&P 500 (NUK) Index before fees", "Grow the investment over 5 years or more"]}

    def page(prompt):
        return {"summary": "Fidelity Index US Fund P Accumulation has an ongoing charge of 0.06% a year.",
                "date": "2026-10-29", "date_basis": "as_at"}

    def planner(prompt):
        return {"searches": [{"topic": "market_drivers", "query": f"S&P 500 drivers {i}", "reason": "context"}
                             for i in range(planner_queries)]}

    def search(prompt):
        query = re.search(r"Search query: (.*)", prompt).group(1)
        return {"query": query, "summary": "The S&P 500 rose, led by technology shares.",
                "url": f"https://news.example/{len(query)}", "date": "2026-09-15", "date_basis": "published"}

    return Runners(mandate=FakeRunBy(mandate), page=FakeRunBy(page), planner=FakeRunBy(planner),
                   search=FakeRunBy(search), analyst=FakeRunBy(analyst_answer),
                   evaluator=FakeRunBy(lambda p: evaluator_answer or {"pass": True, "issues": []}), http_get=http_get,
                   task_planner=FakeRunBy(lambda p: TASK_PLAN), reporter=FakeRunBy(reporter_answer),
                   judge=FakeRunBy(judge_answer))


TASK_PLAN = {"report_type": "quarterly_review", "focus": ["Performance", "Fees"], "market_context": True,
             "manager_questions": True, "angles": ["board", "analyst"], "reason": "A full quarterly review.",
             "searches": [{"topic": "market_drivers", "query": "S&P 500 review Oct 2025 to Sep 2026",
                           "objective": "What drove US shares", "relevance": "Context for the fund's return"},
                          {"topic": "fund_news", "query": "Fidelity Index US Fund fee change 2026",
                           "objective": "Changes to the fund", "relevance": "Fees and index"}]}
CONTEXT = "US shares rose over the period, led by large technology companies [1]."


def reporter_answer(prompt):
    """ A draft that passes code's checks: plain words and code's verdict sentence at the end """
    ending = re.search(r"Verdict sentence to end with: (.*)", prompt).group(1)
    who = "the board" if "For the board" in prompt else "the analyst"
    has_sources = "Numbered sources (web research, vetted by code):\nnone" not in prompt
    return {"text": f"For {who}: the evidence suggests the fund tracked its index closely. {ending}",
            "market_context": CONTEXT if has_sources else None}


def judge_answer(prompt):
    """ The Judge approves the draft """
    return {"approved": True, "factual_issue": False, "security_issue": False, "conclusion_reasonable": True,
            "clear_for_analysts": True, "feedback": "Accurate, reasonable and clear."}


@requires_test1
def test_test1_full_run_mocked(tmp_path):
    runners = mocked()
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, runners=runners, settings=full_settings()))
    log = json.loads((result.run_dir / "log.json").read_text())
    status = {s["step"]: s["status"] for s in log["steps"]}
    assert status == {"read_files": "ok", "plan": "ok", "drafts": "ok", "extractor": "skipped", "peers": "skipped",
                      "data_checks": "ok", "mandate": "ok", "research": "ok",
                      "calculator": "ok", "scorecard": "ok", "report": "ok", "email": "skipped"}
    research = next(s for s in log["steps"] if s["step"] == "research")
    assert research["outputs"]["web_searches"] <= 5                        # the limit, fallback included
    assert any("spglobal" in i for i in research["inputs"])
    assert [q["query"] for q in research["outputs"]["queries"]][-2:] == [
        "S&P 500 review Oct 2025 to Sep 2026", "Fidelity Index US Fund fee change 2026"]   # the Planner's searches
    assert all(x["url"] and x["date"] for x in research["outputs"]["sources"])
    assert runners.analyst.prompts == [] and runners.evaluator.prompts == [] and runners.planner.prompts == []
    assert result.narrative.source == "ai" and result.narrative.output.market_context == CONTEXT
    web = log["sources"]["web"]
    assert web and web == result.narrative.sources and web[0]["number"] == 1
    assert result.facts["scorecard"]["verdict"] == "Monitor until a peer is added"
    assert len(page_texts(result.executive_pdf)) >= 2 and len(page_texts(result.pdf)) >= 6
    detailed = " ".join(" ".join(page_texts(result.pdf)).split())
    assert CONTEXT in detailed and web[0]["url"] in detailed


@requires_test1
def test_a_slow_ai_step_times_out_and_is_flagged(tmp_path):
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, runners=mocked(mandate_delay=1.0),
                                    settings=settings(mandate=0.05)))
    log = json.loads((result.run_dir / "log.json").read_text())
    assert next(s for s in log["steps"] if s["step"] == "mandate")["status"] == "timeout"
    # A blocking flag does not stop the run: the verdict waits for a data check, and the report says why
    assert result.facts["scorecard"]["verdict"] == "Pending data check" and result.pdf.exists()
    assert "Mandate Agent did not finish within 0.05 seconds" in (result.run_dir / "run_log.txt").read_text()


# The Extractor runs only when there is no factsheet_performance.json
def _test1_without_factsheet_json(tmp_path):
    folder = tmp_path / "test1"
    shutil.copytree(TEST1, folder, ignore=shutil.ignore_patterns("factsheet_performance.json", "answer_key*"))
    return folder


@requires_test1
def test_without_factsheet_figures_the_extractor_reads_the_documents(tmp_path):
    from test_agent_extractor import _test1_output
    folder = _test1_without_factsheet_json(tmp_path)
    runners = mocked()
    runners.extractor = FakeRunBy(lambda prompt: _test1_output())
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", runners=runners))
    log = json.loads((result.run_dir / "log.json").read_text())
    extractor = next(s for s in log["steps"] if s["step"] == "extractor")
    assert extractor["status"] == "ok" and "Monthly_FactSheet.pdf" in extractor["inputs"]
    assert "Key_Investor_Info.pdf" in log["sources"]["input_files"]                 # read, so listed plainly
    assert "please verify" in " ".join(page_texts(result.pdf))                      # ai_extracted figures
    assert len(runners.extractor.prompts) == 1


@requires_test1
def test_without_factsheet_figures_offline_uses_calculated_figures_and_says_so(tmp_path):
    folder = _test1_without_factsheet_json(tmp_path)
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))
    assert "No factsheet figures: no factsheet_performance.json, and the Extractor Agent was not run (offline run)" \
        in (result.run_dir / "run_log.txt").read_text()


@requires_test1
def test_email_when_switched_on_goes_through_resend_and_is_logged(tmp_path, monkeypatch):
    from test_emailer import FakePost
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    s = settings()
    monkeypatch.setenv("EMAIL_TO", "oversight@example.com")
    s.email = s.email.model_copy(update={"enabled": True})
    post = FakePost()
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, offline=True, settings=s,
                                    runners=Runners(email_post=post)))
    email = result.log.step("email")
    assert email.status == "ok" and email.notes == ["Email: sent to 1 recipient(s) from EMAIL_TO"]
    assert post.calls[0]["json"]["attachments"][0]["filename"] == \
        "Fidelity_Index_US_Fund_P_Accumulation_Executive_Report_2026-09-30.pdf"     # the default (stage 3), readable name
    s.email = s.email.model_copy(update={"attachment": "detailed"})                      # the option kept
    detailed = asyncio.run(run_review(TEST1, out_root=tmp_path, offline=True, settings=s,
                                      runners=Runners(email_post=post)))
    assert post.calls[1]["json"]["attachments"][0]["filename"] == \
        "Fidelity_Index_US_Fund_P_Accumulation_Detailed_Report_2026-09-30.pdf"
    assert (result.executive_pdf.name, detailed.pdf.name) == ("report_executive.pdf", "report.pdf")   # kept inside


# Task Planner, Reporting Agents and the Judge in the run
@requires_test1
def test_the_judged_ai_draft_becomes_the_suggested_conclusion(tmp_path):
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, runners=mocked(), settings=full_settings()))
    concl = result.facts["suggested_conclusion"]
    assert concl["source"] == "ai" and concl["angle"] == "board"              # the first approved, in plan order
    assert concl["text"].startswith("For the board:") and concl["code_text"] != concl["text"]
    assert [(d["angle"], d["decision"], d["chosen"]) for d in result.facts["drafts"]] == [
        ("board", "pass", True), ("analyst", "pass", False)]
    assert result.facts["plan"]["source"] == "planner" and result.facts["plan"]["focus"][:2] == ["Performance", "Fees"]
    p1 = " ".join(page_texts(result.pdf)[0].split())
    assert "AI draft for the board, chosen by the Judge and checked by code" in p1
    pages = page_texts(result.pdf)
    start = next(i for i, x in enumerate(pages) if "Appendix D: Data quality, sources and audit" in x)
    appendix = " ".join(" ".join(pages[start:]).split())
    assert "Plan (Task Planner Agent): quarterly oversight review; focus Performance, Fees" in appendix
    assert "Draft for the board: approved by the Judge; reason: Accurate, reasonable and clear; chosen." in appendix


@requires_test1
def test_a_fee_question_plan_skips_the_market_research(tmp_path):
    runners = mocked()
    runners.task_planner = FakeRunBy(lambda p: TASK_PLAN | {"report_type": "fee_question", "focus": ["Fees"],
                                                            "market_context": False, "manager_questions": False,
                                                            "angles": ["board"]})
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, runners=runners, settings=full_settings()))
    log = json.loads((result.run_dir / "log.json").read_text())
    research = next(s for s in log["steps"] if s["step"] == "research")
    assert research["status"] == "skipped" and research["notes"] == ["the plan needs no market context"]
    assert result.facts["manager_questions"] == [] and [d["angle"] for d in result.facts["drafts"]] == ["board"]
    assert {p["name"] for p in result.facts["scorecard"]["pillars"]} == {"Mandate", "Performance",
                                                                         "Value for investors", "Fees"}


@requires_test1
def test_without_the_new_agents_the_run_uses_the_default_plan_and_code_conclusion(tmp_path):
    runners = mocked()
    runners.task_planner = runners.reporter = runners.judge = None             # unit tests: these calls fail
    result = asyncio.run(run_review(TEST1, out_root=tmp_path, runners=runners))
    assert result.facts["plan"]["source"] == "default" and result.facts["suggested_conclusion"]["source"] == "code"
    assert result.facts["drafts"] and not any(d["chosen"] for d in result.facts["drafts"])


# Live progress, from the steps that actually run: "▶" when a step starts, then its outcome
def _stage(line: str) -> int:
    return int(line.lstrip("▶✓↷✗• ").split(" of 5")[0].removeprefix("Step "))


def test_progress_runs_through_the_five_steps_in_order_with_the_agents(tmp_path):
    from fund_performance.controller import STAGES, progress_line
    sample = Path(__file__).resolve().parents[1] / "demo" / "sample_index_fund"
    messages = []
    result = asyncio.run(run_review(sample, out_root=tmp_path, runners=mocked(), on_step=messages.append))
    assert result.pdf.is_file()
    started = [m for m in messages if m.startswith("▶")]
    assert [_stage(m) for m in started] == sorted(_stage(m) for m in started)     # 1 -> 5, never back
    assert {_stage(m) for m in started} == {1, 2, 3, 4, 5}
    for step in ("read_files", "plan", "data_checks", "mandate", "calculator", "scorecard", "drafts", "report"):
        assert progress_line(*STAGES[step]) in messages, step
    assert "▶ Step 2 of 5 · Task Planner Agent · Choosing what the review should focus on…" in messages
    assert "▶ Step 4 of 5 · Reporting Agent and Judge · Drafting the summary and checking it…" in messages
    assert any(m.startswith("▶ Step 3 of 5 · Search Agent · ") for m in messages)
    assert any(m.startswith("↷ Step 3 of 5 · Search Agent · unavailable") or m.startswith("✓ Step 3 of 5 · Search Agent · done")
               for m in messages)
    assert any(m.startswith("✓ Step 5 of 5 · Code: reports · done (") for m in messages)


def test_an_offline_run_starts_no_agent_and_says_which_steps_it_skipped(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "demo" / "sample_index_fund"
    messages = []
    asyncio.run(run_review(sample, out_root=tmp_path, offline=True, on_step=messages.append))
    assert all(" · Code: " in m for m in messages if m.startswith("▶"))
    assert "↷ Step 2 of 5 · Task Planner Agent · skipped: offline run: default plan" in messages
