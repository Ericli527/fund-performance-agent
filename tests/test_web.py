""" The Gradio front end (step 11): uploads, the review from the page, messages, and the page itself. No server is
started and no AI is called (offline runs and a stand-in runner) """
import asyncio
import json
from pathlib import Path
import gradio as gr
from fund_performance.controller import RunStopped
import pytest
from fund_performance.web import (AI_OFF, DEMO, DEMO_ONLY, NEED_LOGIN, PUBLIC_DATA, ai_allowed, build_ui,
                                  check_login, demo_files, gate, is_demo, prepare_inputs, review, summary_markdown)


@pytest.fixture(autouse=True)
def no_login_settings(monkeypatch):
    """ Each test starts as on your own computer with no login set up; tests set what they need """
    for name in ("APP_USERNAME", "APP_PASSWORD", "PORT"):
        monkeypatch.delenv(name, raising=False)


def logins_on(monkeypatch, server=True):
    monkeypatch.setenv("APP_USERNAME", "reviewer")
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    if server:
        monkeypatch.setenv("PORT", "10000")


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
    assert "**Draft verdict: Retain**" in outcome.message and "| Question | Rating | Why |" in outcome.message
    assert "| Mandate | 🟢 Green | Moves in line with its index (R² 1.00, beta 1.00; 5 years, calculated). |" \
        in outcome.message
    assert ("| Value for investors | 🟢 Green | The peer, Sample World Index Tracker B, returned 1.17 pp a year less "
            "than the fund over 5 years, both after fees. |") in outcome.message
    assert "| Fees | 🟢 Green | The fund's 0.10% yearly ongoing charge (OCF) is 0.05 pp above the peer's 0.05%. |" \
        in outcome.message
    assert "**Key findings**" in outcome.message
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


# Protecting the API key on a public link (owner review of step 11)
def test_with_a_login_set_up_ai_runs_need_it(monkeypatch):
    logins_on(monkeypatch)
    assert not ai_allowed(False) and ai_allowed(True)
    assert check_login("reviewer", "s3cret") and not check_login("reviewer", "wrong") and not check_login("", "")


def test_without_a_login_only_the_offline_demo_runs(monkeypatch, tmp_path):
    logins_on(monkeypatch)
    demo = demo_files()
    own = tmp_path / "fund_profile.json"
    own.write_text("{}")
    assert gate(offline=False, files=demo, logged_in=False) == NEED_LOGIN
    assert gate(offline=True, files=[str(own)], logged_in=False) == DEMO_ONLY
    assert gate(offline=True, files=demo, logged_in=False) is None
    assert gate(offline=False, files=[str(own)], logged_in=True) is None


def test_a_renamed_or_changed_demo_file_is_not_the_demo(tmp_path):
    copy = tmp_path / "prices.csv"
    copy.write_bytes(Path(demo_files()[2]).read_bytes() + b"\n")
    assert is_demo(demo_files()) and not is_demo([str(copy)]) and not is_demo([])


def test_on_a_server_with_no_login_set_up_ai_runs_are_off(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    assert not ai_allowed(True)
    assert gate(offline=False, files=demo_files(), logged_in=True) == AI_OFF


def test_on_your_own_computer_with_no_login_ai_runs_are_on():
    assert ai_allowed(False)


def test_the_gate_is_checked_on_the_server_for_every_run(monkeypatch, tmp_path):
    logins_on(monkeypatch)
    called = []

    async def runner(*args):
        called.append(args)
        raise RunStopped("stop")
    outcome = asyncio.run(review("q", demo_files(), offline=False, out_root=tmp_path, runner=runner, logged_in=False))
    assert outcome.message == NEED_LOGIN and called == []
    asyncio.run(review("q", demo_files(), offline=True, out_root=tmp_path, runner=runner, logged_in=False))
    assert len(called) == 1 and called[0][3] is True                      # offline demo goes ahead


def test_the_page_shows_the_login_only_when_one_is_set_up(monkeypatch):
    def accordion_visible():
        return [c.visible for c in build_ui().blocks.values() if isinstance(c, gr.Accordion)]
    assert accordion_visible() == [False]
    logins_on(monkeypatch)
    assert accordion_visible() == [True]


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


def test_failed_logins_from_everyone_pause_logins(monkeypatch):
    import fund_performance.web as web
    logins_on(monkeypatch)
    monkeypatch.setattr(web, "_failures", [])
    for _ in range(web.MAX_FAILURES_SERVER):
        assert not check_login("reviewer", "guess")
    assert web.logins_paused() and not check_login("reviewer", "s3cret")       # even the right password waits
    assert not web.logins_paused(now=web.time.monotonic() + web.FAILURE_WINDOW_SECONDS + 1)


def test_the_page_events_are_not_in_the_public_api():
    ui = build_ui()
    assert all(d.api_visibility == "private" for d in ui.fns.values())
