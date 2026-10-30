""" The Gradio front end: the login and the limits, the documents route (read, checked by code, run), the Advanced
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
                                  PUBLIC_DATA_HTML, AUDIENCE_HELP, REVIEW_TYPES, UI_QUESTION, AiLimits,
                                  build_ui, demo_files, example_zip, file_status, question_for, run_offline,
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


def test_documents_are_read_checked_by_code_and_run_in_one_click(tmp_path, limits):
    price, factsheet, peer = documents(tmp_path)
    seen = {}

    async def runner(folder, question, out_root, offline, intake=None, on_step=None):
        seen["profile"] = json.loads((folder / "fund_profile.json").read_text())
        seen["files"] = sorted(p.name for p in folder.iterdir())
        seen["intake"], seen["offline"] = intake, offline
        raise RunStopped("stop here")
    outcome = asyncio.run(start_review("q", price, factsheet, None, [peer, peer], [], False, limits, out_root=tmp_path,
                                       runner=runner, reader=fake_reader))
    assert outcome.message == "**stop here**" and seen["offline"] is False
    assert seen["files"] == ["factsheet_performance.json", "fund_profile.json", "peer.json", "prices.csv"]
    assert seen["profile"]["ocf_pct"] == 0.1 and seen["profile"]["field_sources"]["ocf_pct"] == "ai_extracted"
    checks = [f["message"] for f in seen["intake"]["flags"] if f["check"] == "self_check"]
    assert any(m.startswith("Code checked the values the Extractor Agent read:") for m in checks)
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


def test_a_value_nobody_could_read_stops_the_run_with_a_clear_message(tmp_path, limits):
    from fund_performance.intake import read_documents
    from conftest import FakeRunBy

    async def no_isin(factsheet, kid, peers):
        return await read_documents(factsheet, kid, peers, run_extractor=FakeRunBy(lambda p: extractor_answer(isin=None)),
                                    run_mandate=FakeRunBy(lambda p: MANDATE), run_peer=FakeRunBy(lambda p: peer_answer()))
    price, factsheet, _ = documents(tmp_path)
    outcome = asyncio.run(start_review("q", price, factsheet, None, None, [], False, limits, reader=no_isin))
    assert outcome.message.startswith("**The review could not run: these values were not found in the documents.**")
    assert "- ISIN: not found in the documents" in outcome.message and outcome.pdf is None


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
    assert PUBLIC_DATA_HTML in texts and INSTRUCTIONS in texts and FILES_TABLE in texts and HOW_END in texts
    for step in ("Try the demo", "Upload a real fund", "Let the agent check itself", "Read the evidence",
                 "Make the judgement"):
        assert step in INSTRUCTIONS
    accordions = {c.label: c.open for c in ui.blocks.values() if isinstance(c, gr.Accordion)}
    assert accordions == {"Additional options": False, "Help & methodology": False, "Technical details": False}
    assert any(isinstance(c, gr.DownloadButton) and c.label == "Download example files" for c in ui.blocks.values())


# The redesigned input page (UX stage 1)
def _blocks(kind):
    return [c for c in build_ui().blocks.values() if isinstance(c, kind)]


def test_the_page_follows_the_new_layout():
    ui = build_ui()
    texts = " ".join(str(getattr(c, "value", "") or "") for c in ui.blocks.values())
    assert "<h1>Fund Performance Review</h1>" in texts and "Clear insights for better investment oversight." in texts
    assert "What would you like to analyse?" in texts and "Fund documents" in texts
    buttons = {c.value: c.variant for c in _blocks(gr.Button) if not isinstance(c, gr.DownloadButton)}
    assert buttons == {"Run Fund Review": "primary", "Use Demo Files": "secondary"}
    files = [c.label for c in _blocks(gr.File)]
    for label in ("Fund price data · CSV or Excel · Required", "Fund factsheet · PDF or Word · Required"):
        assert label in files
    assert any(label.startswith("KID or prospectus") for label in files)
    assert any(label.startswith("Peer fund factsheets") for label in files)
    assert any(label.startswith("Advanced: JSON inputs") for label in files)
    question = next(c for c in _blocks(gr.Textbox) if c.label == "Review question")
    assert question.value == "Is this fund meeting its investment objective, and are its fees justified?"


def test_there_is_no_offline_switch_on_the_page():
    assert _blocks(gr.Checkbox) == []
    texts = " ".join(str(getattr(c, "value", "") or "") + str(getattr(c, "label", "") or "") for c in build_ui().blocks.values())
    assert "Offline" not in texts and "untick" not in texts.lower()


def test_review_type_cards_fill_in_the_question_and_keep_the_users_own():
    radio = next(c for c in _blocks(gr.Radio) if c.value == "overall")
    assert [v for _, v in radio.choices] == ["overall", "performance", "fees_value"]
    assert [label.split("\n")[0][3:] for label, _ in radio.choices] == ["Overall Review", "Performance", "Fees & Value"]
    assert question_for("fees_value", UI_QUESTION) == REVIEW_TYPES["fees_value"][2]
    assert question_for("performance", REVIEW_TYPES["fees_value"][2]) == REVIEW_TYPES["performance"][2]
    assert question_for("performance", "My own question?") == "My own question?"
    assert question_for("overall", "") == UI_QUESTION


def test_the_audience_changes_the_view_not_the_review(tmp_path, limits):
    radio = next(c for c in _blocks(gr.Radio) if c.value == "analyst")
    assert [label for label, _ in radio.choices] == ["Investment Analyst", "Management"]
    assert "The figures, ratings and PDF are the same for both." in AUDIENCE_HELP
    import inspect
    assert "audience" not in inspect.signature(start_review).parameters         # never reaches the review


# The results dashboard (UX stage 2)
def _fn(ui, name):
    return next(f for f in ui.fns.values() if f.name == name).fn


def test_results_are_hidden_until_a_review_finishes():
    ui = build_ui()
    results = next(c for c in ui.blocks.values() if isinstance(c, gr.Column) and
                   any(isinstance(x, gr.DownloadButton) and x.label == "Download PDF report"
                       for x in getattr(c, "children", [])))
    assert results.visible is False
    assert not any(isinstance(c, gr.File) and c.label == "PDF report" for c in ui.blocks.values())
    accordions = {c.label for c in ui.blocks.values() if isinstance(c, gr.Accordion)}
    assert "Technical details" in accordions


def test_a_finished_demo_fills_the_dashboard_and_the_audience_redraws_it(tmp_path, limits):
    d = demo()
    outcome = asyncio.run(start_review("q", d["price"], d["factsheet"], None, [d["peer"]], d["json"], True, limits,
                                       out_root=tmp_path))
    assert outcome.data and outcome.data["facts"]["scorecard"]["verdict"] == "Retain" and outcome.pdf
    ui = build_ui()
    redraw = _fn(ui, "on_audience")
    analyst, management = redraw(outcome.data, "analyst"), redraw(outcome.data, "management")
    assert "Investment Analyst view" in analyst and "Key decisions" in management
    assert isinstance(redraw(None, "management"), dict)                  # nothing to redraw before a run


def test_a_refused_run_shows_its_message_and_no_dashboard(tmp_path, limits):
    outcome = asyncio.run(start_review("q", None, None, None, None, [], False, limits))
    assert outcome.message == NEED_FILES and outcome.data is None


def test_each_upload_says_what_it_got():
    d = demo()
    assert file_status(d["price"], [".csv", ".xlsx", ".xls"], "CSV or Excel").startswith("<span class='fp-ok'>✓ prices.csv · ")
    bad = file_status(d["factsheet"], [".csv", ".xlsx", ".xls"], "CSV or Excel")
    assert "✗ factsheet.pdf: not a CSV or Excel file" in bad and "fp-bad" in bad
    assert file_status(None, [".pdf"], "PDF or Word") == ""
    two = file_status([d["factsheet"], d["peer"]], [".pdf", ".docx"], "PDF or Word")
    assert two.count("✓") == 2


def test_code_decides_offline_runs_not_the_user(monkeypatch, tmp_path):
    monkeypatch.delenv("FUND_REVIEW_OFFLINE", raising=False)
    d = demo()
    assert run_offline(d["price"], d["json"]) is True                    # the unchanged demo: deterministic, no AI
    changed = tmp_path / "fund_profile.json"
    changed.write_text(Path(d["json"][0]).read_text().replace("Sample", "Other"))
    assert run_offline(d["price"], [str(changed)] + d["json"][1:]) is False
    assert run_offline(d["price"], []) is False                          # documents: the AI workflow
    monkeypatch.setenv("FUND_REVIEW_OFFLINE", "1")                       # development and testing only
    assert run_offline(d["price"], []) is True


def test_the_demo_button_loads_the_files_and_opens_the_options():
    ui = build_ui()
    demo_fn = next(f for f in ui.fns.values() if f.name == "on_demo")
    price, factsheet, kid, peers, json_files, options = demo_fn.fn()
    assert (price, factsheet, kid) == (demo()["price"], demo()["factsheet"], None)
    assert peers == [demo()["peer"]] and json_files == demo()["json"] and options["open"] is True


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
    assert outcome.message.startswith("**The review could not run")
    assert "The Extractor Agent could not read the documents" in outcome.message and "- ISIN: not found" in outcome.message
