""" The Gradio front end: the login and the limits, the documents route with its confirmation step, the Advanced
JSON route, the demo and example files, and the page's text. No server is started and no AI is called (offline
runs and stand-ins for the reader and the controller) """
import asyncio
import json
from pathlib import Path
import zipfile
import gradio as gr
import pytest
from fund_performance.config import WebSettings
from fund_performance.controller import RunStopped
from fund_performance.web import (AI_OFF, BUSY, FILES_TABLE, HOW_END, INSTRUCTIONS, LIMIT_REACHED, NEED_FILES, NEEDS_AI,
                                  PUBLIC_DATA, AiLimits, build_ui, confirm_review, demo_files, example_zip,
                                  prepare_inputs, start_review, summary_markdown, with_progress)
from test_intake import extractor_answer, MANDATE, peer_answer


@pytest.fixture
def limits(tmp_path):
    return AiLimits(WebSettings(max_ai_runs_per_day=20, max_ai_runs_at_once=1), tmp_path / "ai_runs.json")


def demo():
    return demo_files()


# The login (A1): the page asks for the username and password before it opens
class FakeUi:
    def queue(self, **kwargs):
        return self

    def launch(self, **kwargs):
        self.kwargs = kwargs


def test_the_page_asks_for_the_login_before_it_opens(monkeypatch):
    from fund_performance.web import launch, login
    monkeypatch.setenv("APP_USERNAME", "analyst")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    ui = FakeUi()
    launch(ui)
    assert ui.kwargs["auth"] == ("analyst", "secret") and login() == ("analyst", "secret")
    monkeypatch.delenv("APP_PASSWORD")
    launch(ui)
    assert ui.kwargs["auth"] is None                          # your own computer: no login set up


def test_on_a_server_without_a_login_ai_runs_are_off(monkeypatch, limits, tmp_path):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.setenv("PORT", "10000")
    assert limits.start() == AI_OFF
    d = demo()
    outcome = asyncio.run(start_review("q", d["price"], None, None, None, d["json"], True, limits, out_root=tmp_path))
    assert "**Suggested verdict: Satisfied**" in outcome.message          # the offline demo still works
    monkeypatch.setenv("APP_USERNAME", "a")
    monkeypatch.setenv("APP_PASSWORD", "b")
    assert limits.start() is None


def test_the_daily_limit_counts_ai_runs_and_survives_a_restart(tmp_path):
    settings = WebSettings(max_ai_runs_per_day=2, max_ai_runs_at_once=5)
    limits = AiLimits(settings, tmp_path / "count.json")
    assert limits.start() is None and limits.start() is None
    assert limits.start() == LIMIT_REACHED
    assert AiLimits(settings, tmp_path / "count.json").used_today() == 2          # kept in the file


def test_only_one_ai_run_at_a_time(limits):
    assert limits.start() is None
    assert limits.start() == BUSY
    limits.finish()
    assert limits.start() is None


def test_limits_come_from_the_config():
    from fund_performance.config import load_settings
    web = load_settings().web
    assert (web.max_ai_runs_per_day, web.max_ai_runs_at_once) == (20, 1)


def test_the_limit_message_is_shown_and_offline_still_works(tmp_path):
    full = AiLimits(WebSettings(max_ai_runs_per_day=1, max_ai_runs_at_once=1), tmp_path / "c.json")
    full.start()
    full.finish()
    d = demo()
    outcome = asyncio.run(start_review("q", d["price"], None, None, None, d["json"], False, full, out_root=tmp_path))
    assert outcome.message == LIMIT_REACHED
    outcome = asyncio.run(start_review("q", d["price"], None, None, None, d["json"], True, full, out_root=tmp_path))
    assert "**Suggested verdict: Satisfied**" in outcome.message


# The documents route
async def fake_reader(factsheet, kid, peers):
    from fund_performance.intake import read_documents
    from conftest import FakeRunBy
    return await read_documents(factsheet, kid, peers, run_extractor=FakeRunBy(lambda p: extractor_answer()),
                                run_mandate=FakeRunBy(lambda p: MANDATE), run_peer=FakeRunBy(lambda p: peer_answer()))


def documents(tmp_path):
    """ The made-up factsheet and peer factsheet as Word documents (the page takes PDF or Word) """
    from docx import Document
    from test_intake import FACTSHEET, PEER_SHEET
    paths = []
    for name, text in (("factsheet.docx", FACTSHEET), ("peer_factsheet.docx", PEER_SHEET)):
        doc = Document()
        for line in text.splitlines():
            doc.add_paragraph(line)
        doc.save(tmp_path / name)
        paths.append(str(tmp_path / name))
    return str(Path(demo()["price"])), paths[0], paths[1]


def test_documents_are_read_and_shown_for_confirmation(tmp_path, limits):
    price, factsheet, peer = documents(tmp_path)
    outcome = asyncio.run(start_review("q", price, factsheet, None, [peer, peer], [], False, limits, out_root=tmp_path,
                                       reader=fake_reader))
    assert len([r for r in outcome.state["intake"]["rows"] if r["key"].endswith(".ocf_pct")]) == 2   # 2 peers
    assert outcome.pdf is None and outcome.message.startswith("**Check what the agent read.**")
    assert outcome.state["paid"] is True and outcome.state["price"] == price
    assert limits.used_today() == 1 and limits.active == 0


def test_documents_need_ai(tmp_path, limits):
    price, factsheet, _ = documents(tmp_path)
    assert asyncio.run(start_review("q", price, factsheet, None, None, [], True, limits)).message == NEEDS_AI


def test_the_price_file_and_factsheet_are_required(tmp_path, limits):
    price, factsheet, _ = documents(tmp_path)
    assert asyncio.run(start_review("q", price, None, None, None, [], False, limits)).message == NEED_FILES
    assert asyncio.run(start_review("q", None, factsheet, None, None, [], False, limits)).message == NEED_FILES
    wrong = asyncio.run(start_review("q", factsheet, factsheet, None, None, [], False, limits))
    assert wrong.message.startswith("The price file must be .csv or .xlsx or .xls")
    txt = tmp_path / "factsheet.txt"
    txt.write_text("x")
    assert asyncio.run(start_review("q", price, str(txt), None, None, [], False, limits)).message.startswith(
        "The factsheet must be .pdf or .docx")


def test_confirm_and_run_uses_the_confirmed_values_and_is_not_counted_twice(tmp_path, limits):
    price, factsheet, peer = documents(tmp_path)
    started = asyncio.run(start_review("q", price, factsheet, None, peer, [], False, limits, out_root=tmp_path,
                                       reader=fake_reader))
    rows = [[r["label"], r["value"], r["status"], r["source"]] for r in started.state["intake"]["rows"]]
    rows[[r[0] for r in rows].index("Ongoing charge (OCF), % a year")][1] = "0.12"
    seen = {}

    async def runner(folder, question, out_root, offline, intake=None, on_step=None):
        seen["profile"] = json.loads((folder / "fund_profile.json").read_text())
        seen["files"] = sorted(p.name for p in folder.iterdir())
        seen["intake"], seen["offline"] = intake, offline
        raise RunStopped("stop here")
    outcome = asyncio.run(confirm_review("q", rows, started.state, limits, out_root=tmp_path, runner=runner))
    assert seen["profile"]["ocf_pct"] == 0.12 and seen["profile"]["field_sources"]["ocf_pct"] == "user"
    assert seen["files"] == ["factsheet_performance.json", "fund_profile.json", "peer.json", "prices.csv"]
    assert seen["offline"] is False and "Ongoing charge (OCF), % a year" in [
        r["label"] for r in seen["intake"]["rows"] if r["status"] == "Entered by user"]
    assert limits.used_today() == 1 and outcome.state["paid"] is False and outcome.message == "**stop here**"


def test_a_missing_required_value_stops_confirm_and_run(tmp_path, limits):
    price, factsheet, peer = documents(tmp_path)
    started = asyncio.run(start_review("q", price, factsheet, None, peer, [], False, limits, reader=fake_reader))
    rows = [[r["label"], r["value"], r["status"], r["source"]] for r in started.state["intake"]["rows"]]
    rows[[r[0] for r in rows].index("ISIN")][1] = ""
    outcome = asyncio.run(confirm_review("q", rows, started.state, limits))
    assert outcome.message.startswith("**Please fix these values before the run:**") and "ISIN: required" in outcome.message
    assert outcome.state == started.state                              # the table stays for the fix


# The Advanced JSON route and the demo
def test_the_demo_runs_offline_through_the_json_route(tmp_path, limits):
    d = demo()
    outcome = asyncio.run(start_review("Is this index fund meeting its mandate?", d["price"], d["factsheet"], None,
                                       d["peer"], d["json"], True, limits, out_root=tmp_path))
    assert outcome.pdf and Path(outcome.pdf).exists() and "**Suggested verdict: Satisfied**" in outcome.message
    assert "| Question | Rating | Why |" in outcome.message
    assert ("| Fees | 🟢 Green | The fund's 0.10% yearly ongoing charge (OCF) is 0.05 pp above the peer's 0.05%. |"
            in outcome.message)
    assert limits.used_today() == 0                                     # offline runs are not counted


def test_the_example_files_are_the_made_up_demo(tmp_path):
    with zipfile.ZipFile(example_zip()) as z:
        names = sorted(Path(n).name for n in z.namelist())
    assert names == ["factsheet.pdf", "factsheet_performance.json", "fund_profile.json", "peer.json",
                     "peer_factsheet.pdf", "prices.csv"]
    assert "Made-up" in json.loads(Path(demo()["json"][0]).read_text())["objective_text"]


def test_uploads_are_copied_with_safe_unique_names(tmp_path):
    src, other = tmp_path / "src", tmp_path / "other"
    src.mkdir()
    other.mkdir()
    (src / "fund profile (1).json").write_text("{}")
    (other / "fund profile (1).json").write_text("{}")
    names = prepare_inputs([str(src / "fund profile (1).json"), str(other / "fund profile (1).json"),
                            str(tmp_path / "missing.csv")], tmp_path / "dest")
    assert names == ["fund_profile_1_.json", "fund_profile_1__2.json"]


# Progress and the page's text
def test_progress_messages_come_before_the_result():
    async def work(say):
        say("Reading the documents…")
        await asyncio.sleep(0.01)
        say("Scoring…")
        return "result"

    async def collect():
        return [item async for item in with_progress(work)]
    assert asyncio.run(collect()) == [("progress", "Reading the documents…"), ("progress", "Scoring…"),
                                      ("done", "result")]


def test_the_page_has_the_instructions_files_table_and_how_it_works():
    ui = build_ui()
    texts = " ".join(str(getattr(c, "value", "") or "") for c in ui.blocks.values())
    assert PUBLIC_DATA in texts and INSTRUCTIONS in texts and FILES_TABLE in texts and HOW_END in texts
    for step in ("Try the demo", "Upload a real fund", "Check what the agent read", "Read the evidence",
                 "Make the judgement"):
        assert step in INSTRUCTIONS
    accordions = {c.label: c.open for c in ui.blocks.values() if isinstance(c, gr.Accordion)}
    assert accordions == {"How the agent works": True, "Advanced: JSON files (skip the AI reading step)": False}
    assert any(isinstance(c, gr.DownloadButton) and c.label == "Download example files" for c in ui.blocks.values())


def test_the_page_events_are_not_in_the_public_api():
    assert all(d.api_visibility == "private" for d in build_ui().fns.values())


def test_summary_lists_blocking_checks():
    from types import SimpleNamespace
    result = SimpleNamespace(facts={"fund": {"fund_name": "F", "as_of_date": "2026-09-30"},
                                    "scorecard": {"verdict": "Pending data check", "pillars": [
                                        {"name": "Performance", "rating": "CHECK DATA"}]},
                                    "data_flags": [{"level": "blocking", "message": "CHECK DATA: currency mismatch"}]},
                             narrative=None)
    text = summary_markdown(result)
    assert "**Suggested verdict: Pending data check**" in text and "| Performance | 🟣 Check data |" in text


def test_when_the_extractor_cannot_read_the_documents_the_page_says_so(tmp_path, limits):
    from agents.exceptions import AgentsException
    from fund_performance.intake import read_documents
    from conftest import FakeRun

    async def failing_reader(factsheet, kid, peers):
        return await read_documents(factsheet, kid, peers, run_extractor=FakeRun(AgentsException("no key")))
    price, factsheet, _ = documents(tmp_path)
    outcome = asyncio.run(start_review("q", price, factsheet, None, None, [], False, limits, reader=failing_reader))
    assert "**The Extractor Agent could not read the documents**" in outcome.message
    filled = {r["key"]: r["value"] for r in outcome.state["intake"]["rows"] if r["value"]}
    assert filled == {"hedged": "no"}                     # only what code derives: no hedging mentioned
