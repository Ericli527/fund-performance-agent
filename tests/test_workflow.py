""" The Version 1 pilot workflow (hotfix): bounded AI calls, optional AI failures contained with their reason, a
critical failure named by its stage, one draft and one Judge pass, the AI-call record and the progress history """
import asyncio
import json
from pathlib import Path
import pytest
from fund_performance.config import load_settings
from fund_performance.controller import RunStopped, run_review
from conftest import FakeRunBy
from test_controller import TASK_PLAN, judge_answer, mocked, reporter_answer

SAMPLE = Path(__file__).resolve().parents[1] / "demo" / "sample_index_fund"


def run(tmp_path, runners, **kw):
    return asyncio.run(run_review(SAMPLE, out_root=tmp_path, runners=runners, **kw))


def calls_of(result) -> dict:
    return json.loads((result.run_dir / "log.json").read_text())["run"]["ai_calls"]


def test_the_pilot_defaults_switch_off_research_and_extra_drafts():
    s = load_settings()
    assert s.research.enabled is False and s.email.enabled is False
    assert (s.drafting.max_drafts, s.drafting.max_rewrites, s.drafting.rejudge_after_rewrite) == (1, 1, False)


def test_a_review_makes_a_bounded_set_of_ai_calls_and_records_them(tmp_path):
    """ JSON route: Task Planner, Mandate, one Reporting Agent draft, one Judge pass: 4 calls; no research """
    result = run(tmp_path, mocked())
    calls = calls_of(result)
    assert calls["total"] == 4 and calls["by_agent"] == {"Task Planner Agent": 1, "Mandate Agent": 1,
                                                         "Reporting Agent": 1, "Judge Agent": 1}
    assert all(c["outcome"] == "ok" and c["seconds"] >= 0 for c in calls["calls"])
    log = json.loads((result.run_dir / "log.json").read_text())
    assert log["run"]["run_id"] == result.run_dir.name
    assert log["run"]["trace_id"] is None                     # tracing is off without an API key (tests, offline)
    assert [d["angle"] for d in result.facts["drafts"]] == ["board"] and result.facts["suggested_conclusion"]["source"] == "ai"


def test_a_rejected_draft_gets_one_targeted_rewrite_and_no_second_judge_pass(tmp_path):
    from fund_performance.presentation import conclusion_origin
    runners = mocked()
    rejected = {"n": 0}

    def judge(prompt):
        rejected["n"] += 1
        answer = judge_answer(prompt)
        for d in answer["drafts"]:
            d["plain_english"], d["issues"] = False, ["shorter sentences"]
        return answer
    runners.judge = FakeRunBy(judge)
    result = run(tmp_path, runners)
    assert calls_of(result)["by_agent"]["Judge Agent"] == 1 and calls_of(result)["by_agent"]["Reporting Agent"] == 2
    concl = result.facts["suggested_conclusion"]
    assert concl["source"] == "ai" and concl["revised"] is True
    assert "revised once after the Judge's review and checked by code" in conclusion_origin(concl)
    assert "shorter sentences" in runners.reporter.prompts[1]          # the rewrite got the Judge's issues


@pytest.mark.parametrize("agent", ["task_planner", "reporter", "judge"])
def test_an_unexpected_error_in_an_optional_ai_step_never_destroys_the_review(tmp_path, agent):
    """ What failed on Render: an exception inside an AI step. The step falls back, says why, and the
    calculations, ratings and both PDFs are still produced """
    from fund_performance.report import page_texts
    runners = mocked()

    async def broken(agent_obj, prompt):
        raise ValueError("could not convert string to float: 'n/a'")
    setattr(runners, agent, broken)
    import fund_performance.agents.base as base

    def explode(*a, **k):
        raise ValueError("could not convert string to float: 'n/a'")
    if agent == "judge":                                       # an error in code that handles the Judge's answer
        import fund_performance.agents.judge as judge_mod
        orig = judge_mod.pick
        judge_mod.pick = explode
    try:
        result = run(tmp_path, runners if agent != "judge" else mocked())
    finally:
        if agent == "judge":
            judge_mod.pick = orig
    assert result.pdf.is_file() and len(page_texts(result.executive_pdf)) == 2
    assert result.facts["scorecard"]["verdict"] in ("Retain", "Monitor", "Monitor until a peer is added")
    log = json.loads((result.run_dir / "log.json").read_text())
    if agent == "judge":
        drafts = next(s for s in log["steps"] if s["step"] == "drafts")
        assert drafts["status"] == "failed" and "ValueError: could not convert string to float" in drafts["notes"][0]
        assert result.facts["suggested_conclusion"]["source"] == "code"
        assert any("AI drafts: the Reporting Agent or Judge failed (ValueError" in f.message for f in result.flags)


def test_a_failure_in_a_critical_step_stops_the_run_naming_the_stage(tmp_path, monkeypatch):
    import fund_performance.controller as controller

    def broken(*a, **k):
        raise ValueError("a bad figure")
    monkeypatch.setattr(controller, "score", broken)
    with pytest.raises(RunStopped) as stopped:
        run(tmp_path, mocked())
    message = str(stopped.value)
    assert message.startswith("Run stopped at Step 3 of 5 (Code: scorecard): ValueError: a bad figure.")
    assert "run ID" in message and "/" not in message.split("run ID")[0]
    log = json.loads(next(tmp_path.glob("*/log.json")).read_text())
    assert log["run"]["status"] == "stopped" and log["steps"][-1]["status"] == "failed"


def test_error_messages_hide_paths_and_key_like_strings():
    from fund_performance.controller import _short
    text = _short("open /home/app/data/secret.pdf failed with key sk-abcdefghijklmnop " + "x" * 300 + " THE REASON")
    assert "/home" not in text and "sk-abc" not in text and len(text) <= 245
    assert text.endswith("THE REASON")                                # the reason at the end is kept


def test_the_progress_area_replaces_a_running_step_with_its_outcome():
    from fund_performance.web import progress_history, progress_markdown, run_info
    h = progress_history([], "▶ Step 3 of 5 · Code: scorecard · Rating…")
    h = progress_history(h, "✓ Step 3 of 5 · Code: scorecard · done (0.1 s)")
    h = progress_history(h, "↷ Step 3 of 5 · Research Agents · skipped: web research is off")
    assert h == ["✓ Step 3 of 5 · Code: scorecard · done (0.1 s)", "↷ Step 3 of 5 · Research Agents · skipped: web research is off"]
    info = run_info({"run_id": "r1", "trace_id": "trace_x", "ai_calls": {"total": 2, "by_agent": {"Judge Agent": 1, "Reporting Agent": 1}}})
    assert info == "Run r1 · 2 AI call(s) (Judge Agent 1, Reporting Agent 1) · OpenAI trace trace_x"
    assert progress_markdown(h, info).endswith(info)


def test_every_agent_call_of_a_review_runs_inside_one_trace(tmp_path, monkeypatch):
    """ The page's reading agents and every agent the controller runs share one OpenAI trace ("Fund performance
    review"), so the SDK files all their spans under it. Checked with the SDK's own current trace inside each call;
    nothing is uploaded (the trace processors are replaced) """
    import functools
    from agents import get_current_trace
    from agents.tracing import set_trace_processors
    from fund_performance import web
    from fund_performance.config import WebSettings
    from fund_performance.intake import read_documents
    from test_intake import MANDATE, extractor_answer
    from agents import set_tracing_disabled
    from agents.tracing import get_trace_provider
    processors = list(getattr(get_trace_provider(), "_multi_processor")._processors)
    set_trace_processors([])                                        # no export
    set_tracing_disabled(False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENAI_AGENTS_DISABLE_TRACING", raising=False)
    seen: list[tuple[str, str | None, str | None]] = []

    def traced(name, answer):
        async def call(agent, prompt):
            t = get_current_trace()
            seen.append((name, t.trace_id if t else None, t.name if t else None))
            ans = answer(prompt) if callable(answer) else answer
            return type("R", (), {"final_output": ans})()
        return call
    runners = mocked()
    for name in ("task_planner", "mandate", "reporter", "judge"):
        setattr(runners, name, traced(name, getattr(__import__("test_controller"), {
            "task_planner": "TASK_PLAN", "reporter": "reporter_answer", "judge": "judge_answer"}.get(name, "TASK_PLAN"))
            if name != "mandate" else MANDATE))
    factsheet = SAMPLE / "factsheet.pdf"                            # the made-up fund's (the reading is mocked)
    reader = lambda f, k, p: read_documents(f, k, p, run_extractor=traced("extractor", extractor_answer()),
                                            run_mandate=traced("mandate (page)", MANDATE))
    limits = web.AiLimits(WebSettings(max_ai_runs_per_day=5, max_ai_runs_at_once=1), tmp_path / "count.json")
    out = asyncio.run(web.start_review("q", str(SAMPLE / "prices.csv"), str(factsheet), None, [], None, False, limits,
                                       out_root=tmp_path / "runs",
                                       runner=functools.partial(run_review, runners=runners), reader=reader))
    assert out.data is not None
    names = [n for n, _, _ in seen]
    assert names[:2] == ["extractor", "mandate (page)"] and {"task_planner", "reporter", "judge"} <= set(names)
    trace_ids = {t for _, t, _ in seen}
    assert len(trace_ids) == 1 and None not in trace_ids                  # one trace for the whole review
    assert {n for _, _, n in seen} == {"Fund performance review"}
    log = json.loads(next((tmp_path / "runs").glob("*/log.json")).read_text())
    assert log["run"]["trace_id"] == trace_ids.pop()                     # and the run log names it
    set_tracing_disabled(True)
    set_trace_processors(processors)
