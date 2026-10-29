""" The Gradio front end (step 11): uploads, the review from the page, messages, and the page itself. No server is
started and no AI is called (offline runs and a stand-in runner) """
import asyncio
import json
from pathlib import Path
import gradio as gr
from fund_performance.controller import RunStopped
from fund_performance.web import (DEMO, PUBLIC_DATA, build_ui, demo_files, login, prepare_inputs, review,
                                  summary_markdown)


def test_uploads_are_copied_with_safe_unique_names(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "fund profile (1).json").write_text("{}")
    (src / "sub").mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "fund profile (1).json").write_text("{}")
    names = prepare_inputs([str(src / "fund profile (1).json"), str(src / "sub"), str(other / "fund profile (1).json"),
                            str(tmp_path / "missing.csv")], tmp_path / "dest")
    assert names == ["fund_profile_1_.json", "fund_profile_1__2.json"]
    assert sorted(p.name for p in (tmp_path / "dest").iterdir()) == names


def test_the_demo_is_made_up_public_data():
    names = [Path(p).name for p in demo_files()]
    assert names == ["fund_profile.json", "peer.json", "prices.csv"]
    assert "Made-up" in json.loads((DEMO / "fund_profile.json").read_text())["objective_text"]


def test_offline_demo_review_from_the_page(tmp_path):
    outcome = asyncio.run(review("Is this index fund meeting its mandate?", demo_files(), offline=True,
                                 out_root=tmp_path))
    assert outcome.pdf and Path(outcome.pdf).exists() and outcome.log and Path(outcome.log).exists()
    assert "**Draft verdict: Retain**" in outcome.message
    assert "| Mandate | 🟢 Green |" in outcome.message and "**Key findings**" in outcome.message
    log = json.loads(Path(outcome.log).read_text())
    assert log["run"]["question"] == "Is this index fund meeting its mandate?" and log["run"]["offline"] is True


def test_no_files_gives_a_message_not_an_error(tmp_path):
    outcome = asyncio.run(review("q", [], out_root=tmp_path))
    assert outcome.pdf is None and "upload the fund's files" in outcome.message


def test_a_run_that_cannot_be_scored_says_why(tmp_path):
    only_prices = [p for p in demo_files() if p.endswith("prices.csv")]
    outcome = asyncio.run(review("q", only_prices, offline=True, out_root=tmp_path))
    assert outcome.pdf is None and "no fund_profile.json" in outcome.message and "prices.csv" in outcome.message


def test_an_unexpected_error_is_shown_plainly(tmp_path):
    async def broken(*args):
        raise KeyError("x")
    outcome = asyncio.run(review("q", demo_files(), out_root=tmp_path, runner=broken))
    assert outcome.pdf is None and outcome.message.startswith("**Something went wrong** (KeyError)")


def test_a_stopped_run_from_the_runner(tmp_path):
    async def stopped(*args):
        raise RunStopped("Run stopped: fewer than 2 usable prices")
    outcome = asyncio.run(review("q", demo_files(), out_root=tmp_path, runner=stopped))
    assert outcome.message.startswith("**Run stopped: fewer than 2 usable prices**")


def test_an_empty_question_uses_the_default(tmp_path):
    seen = {}

    async def capture(folder, question, out_root, offline):
        seen["q"] = question
        raise RunStopped("stop")
    asyncio.run(review("   ", demo_files(), out_root=tmp_path, runner=capture))
    assert seen["q"].startswith("Is this index fund meeting its mandate")


def test_the_page_builds_and_warns_about_public_data():
    ui = build_ui()
    assert isinstance(ui, gr.Blocks)
    texts = [getattr(c, "value", "") for c in ui.blocks.values()]
    assert PUBLIC_DATA in texts
    assert any(isinstance(c, gr.File) and c.label == "PDF report" for c in ui.blocks.values())


def test_login_only_when_both_settings_are_set(monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert login() is None
    monkeypatch.setenv("APP_USERNAME", "reviewer")
    assert login() is None
    monkeypatch.setenv("APP_PASSWORD", "x")
    assert login() == ("reviewer", "x")


def test_summary_lists_blocking_checks():
    from types import SimpleNamespace
    result = SimpleNamespace(facts={"fund": {"fund_name": "F", "as_of_date": "2026-09-30"},
                                    "scorecard": {"verdict": "Pending data check", "pillars": [
                                        {"name": "Performance", "rating": "CHECK DATA"}]},
                                    "data_flags": [{"level": "blocking", "message": "CHECK DATA: currency mismatch"}]},
                             narrative=None)
    text = summary_markdown(result)
    assert "**Draft verdict: Pending data check**" in text and "| Performance | 🟣 Check data |" in text
    assert "- CHECK DATA: currency mismatch" in text
