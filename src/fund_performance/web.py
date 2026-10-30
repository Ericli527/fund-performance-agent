""" The Gradio front end (step 11): upload the fund's documents, check what the agent read, download the PDF

Plain code around the intake (intake.py) and the workflow controller. The main route: a price file and the
factsheet (optionally the KID or prospectus and peer funds' factsheets; without them the approved peers in
config/peers.yaml are used). The Extractor and Mandate agents read the
documents, the page shows what they read in an editable table, and the person confirms it before anything is
scored. JSON files are an optional "Advanced" route that skips the reading step. Public data only: the page says
so first.

The login: when APP_USERNAME and APP_PASSWORD are set, the page asks for them before it opens (Gradio's own
login). On a server with no login set up (PORT is set but no credentials), AI runs are switched off and only the
offline demo works; on your own computer no login is needed. Limits in config/settings.yaml also protect the API
key: a daily number of AI reviews, and at most one AI review at a time. Offline runs (no AI) are not limited.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import traceback
from typing import Awaitable, Callable
import zipfile
import gradio as gr
from fund_performance.config import WebSettings, load_settings
from fund_performance.controller import DEFAULT_QUESTION, RunResult, RunStopped, run_review
from fund_performance.plain import verdict_meaning, verdict_name
from fund_performance.intake import COLUMNS, build_inputs, missing, read_documents, table, write_inputs

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DEMO = ROOT / "demo" / "sample_index_fund"
PRICE_TYPES = [".csv", ".xlsx", ".xls"]
DOC_TYPES = [".pdf", ".docx"]
NAVY = "#1f3a5f"
RATING_WORDS = {"GREEN": "🟢 Green", "AMBER": "🟠 Amber", "RED": "🔴 Red", "CHECK DATA": "🟣 Check data",
                "MANUAL CHECK": "⚪ Manual check"}

LIMIT_REACHED = "Today’s AI run limit is reached. You can still run the offline demo."
BUSY = "A review is already running, please try again in 2 minutes."
AI_OFF = ("AI runs are switched off on this server, because no login is set up (APP_USERNAME and APP_PASSWORD). "
          "You can still run the offline demo.")
NEEDS_AI = ("Reading the documents uses AI: untick **Offline**, or use the demo files (or JSON files under "
            "Advanced) for an offline run.")
NEED_FILES = "Please add the price file and the factsheet (both required), or click **Use the demo files**."

PUBLIC_DATA = ("**Public data only.** Files and figures may be sent to OpenAI, which has data sharing on for this "
               "service. Never upload confidential or client data.")
INSTRUCTIONS = """### How to use it
1. **Try the demo:** click **Use the demo files**, then **Run the review**. Free, takes seconds.
2. **Upload a real fund:** the price file and factsheet (KID and peer factsheets optional). Untick **Offline**.
3. **Check what the agent read:** review the table, correct anything, click **Confirm and run**. Takes 1–2 minutes.
4. **Read the evidence:** the suggested verdict, conclusion, ratings and charts; download the PDF.
5. **Make the judgement:** the verdict is a suggestion. The analyst decides and signs the approval box."""
FILES_TABLE = """### Which files do I need?
| File | Needed? | What it's used for |
|---|---|---|
| Price file (CSV or Excel) | Required | Monthly fund prices: risk and cross-checks |
| Factsheet (PDF or Word) | Required | Official returns vs the index, fees, benchmark |
| KID or prospectus (PDF or Word) | Optional | Objective, time horizon, risk |
| Peer fund factsheets (PDF or Word) | Optional (approved peers are built in) | Value for investors and fees |
| JSON files | Advanced, optional | Pre-typed data that skips AI reading |"""
TAGS = {"Code": "#1f3a5f", "AI": "#6d4c9f", "Person": "#2e7d32"}
HOW_STEPS = [
    (["Person"], "You provide public documents and a price file."),
    (["AI", "Person", "Code"], "<b>Read and check:</b> the Extractor reads the documents and you confirm the values; "
                               "code checks currency, pricing time (noon vs close), gaps, repeated prices and "
                               "factsheet cross-checks."),
    (["AI", "Code"], "<b>Understand the fund:</b> the Mandate Agent reads the objective; a decision tree chooses how "
                     "to judge it."),
    (["Code"], "<b>Measure:</b> returns, risk, gaps to the index and peers, and statistical tests."),
    (["Code"], "<b>Score:</b> four questions rated Green, Amber or Red → suggested verdict."),
    (["AI"], "<b>Research and explain:</b> approved pages plus up to 3 web searches; the AI writes the market context "
             "only, checked by code and a separate Evaluator."),
    (["Person"], "<b>Judge and decide:</b> the analyst reviews the evidence, adds comments and signs."),
]
HOW_END = ("Code decides every number and rating. AI reads documents and writes the market context, and everything "
           "it writes is checked twice. The analyst makes the final judgement.")


def how_it_works_html() -> str:
    def tag(name: str) -> str:
        return (f"<span style='background:{TAGS[name]};color:white;border-radius:4px;padding:1px 6px;"
                f"font-size:0.8em;margin-right:4px'>{name}</span>")
    items = "".join(f"<li style='margin-bottom:6px'>{''.join(tag(t) for t in tags)} {text}</li>" for tags, text in HOW_STEPS)
    return f"<ol>{items}</ol><p><b>{HOW_END}</b></p>"


# --- Login and limits on AI runs (config/settings.yaml, web) -----------------------------------------------------

def login() -> tuple[str, str] | None:
    """ The page's username and password from the environment (.env locally, Render's settings online) """
    username, password = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    return (username, password) if username and password else None


def on_server() -> bool:
    """ Hosts such as Render set PORT """
    return "PORT" in os.environ


def ai_switched_off() -> bool:
    """ On a server, AI runs need the login to be set up; on your own computer they never do """
    return on_server() and login() is None


class AiLimits:
    """ A daily count of AI reviews (kept in a small file, so a restart does not reset it) and how many run now """

    def __init__(self, settings: WebSettings, path: Path = RUNS / "ai_runs_today.json"):
        self.settings, self.path, self.active = settings, path, 0

    def used_today(self) -> int:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return 0
        return data.get("count", 0) if data.get("date") == date.today().isoformat() else 0

    def start(self, count: bool = True) -> str | None:
        """ Why an AI review cannot start now, or None (and it is counted and marked running) """
        if ai_switched_off():
            return AI_OFF
        if count and self.used_today() >= self.settings.max_ai_runs_per_day:
            return LIMIT_REACHED
        if self.active >= self.settings.max_ai_runs_at_once:
            return BUSY
        if count:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"date": date.today().isoformat(), "count": self.used_today() + 1}))
        self.active += 1
        return None

    def finish(self) -> None:
        self.active = max(0, self.active - 1)


# --- What was uploaded --------------------------------------------------------------------------------------------

def _safe_name(name: str) -> str:
    """ A plain file name: no folders, only letters, digits, dot, dash and underscore """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._") or "file"
    return cleaned[:120]


def prepare_inputs(paths: list[str], dest: Path) -> list[str]:
    """ Copy files into dest, keeping their names (made safe and unique); returns the names used """
    dest.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    for p in paths:
        src = Path(p)
        if not src.is_file():
            continue
        name = _safe_name(src.name)
        stem, suffix, n = Path(name).stem, Path(name).suffix, 2
        while name in used:
            name, n = f"{stem}_{n}{suffix}", n + 1
        shutil.copy(src, dest / name)
        used.append(name)
    return used


def _one(value) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value or None


def _many(value) -> list[str]:
    if not value:
        return []
    return [v for v in (value if isinstance(value, list) else [value]) if v]


def _wrong_type(path: str | None, allowed: list[str], what: str) -> str | None:
    if path and Path(path).suffix.lower() not in allowed:
        return f"The {what} must be {' or '.join(allowed)}; got {Path(path).name}."
    return None


# --- The review ---------------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    message: str                             # Markdown for the page
    pdf: str | None = None
    log: str | None = None
    state: dict = field(default_factory=dict)  # kept between the two clicks: the intake and the price file


def summary_markdown(result: RunResult) -> str:
    """ The suggested verdict and conclusion, the ratings with their one-line reasons, the points for judgement,
    the findings, actions and questions, and what to check """
    facts = result.facts or {}
    card = facts.get("scorecard", {})
    fund = facts.get("fund", {})
    reasons = getattr(result, "reasons", {}) or {}
    cell = lambda text: " ".join(str(text).split()).replace("|", "/")      # noqa: E731
    lines = [f"### {fund.get('fund_name', 'Fund')}", f"Figures to {fund.get('as_of_date', '')}", "",
             f"**Suggested verdict: {verdict_name(card.get('verdict', ''))}** ({verdict_meaning(card.get('verdict', ''))})"]
    conclusion = (facts.get("suggested_conclusion") or {}).get("text")
    if conclusion:
        lines += ["", f"**Suggested conclusion (draft for the analyst).** {conclusion}"]
    lines += ["", "| Question | Rating | Why |", "|---|---|---|"]
    lines += [f"| {p['name']} | {RATING_WORDS.get(p['rating'], p['rating'])} | {cell(reasons.get(p['name'], ''))} |"
              for p in card.get("pillars", [])]
    if result.narrative:
        lines += ["", "**Key findings**"] + [f"- {f}" for f in result.narrative.output.key_findings]
        lines += ["", "**Recommended actions**"] + [f"- {a}" for a in result.narrative.output.action_texts]
    if facts.get("judgement_points"):
        lines += ["", "**Points for your judgement**"] + [f"- {x}" for x in facts["judgement_points"]]
    if facts.get("manager_questions"):
        lines += ["", "**Questions to ask the manager**"] + [f"- {x}" for x in facts["manager_questions"]]
    flags = facts.get("data_flags", [])
    blocking = [f for f in flags if f["level"] == "blocking"]
    if blocking:
        lines += ["", "**Data checks to resolve**"] + [f"- {f['message']}" for f in blocking]
    elif flags:
        lines += ["", f"{len(flags)} data warning(s): see the appendix of the PDF."]
    lines += ["", "_The verdict is a suggestion: the analyst decides and signs the approval box in the PDF._"]
    return "\n".join(lines)


Progress = Callable[[str], None]


async def _run_controller(folder: Path, question: str, offline: bool, on_step: Progress | None, out_root: Path,
                          runner, intake: dict | None = None) -> Outcome:
    try:
        result = await runner(folder, (question or "").strip() or DEFAULT_QUESTION, out_root, offline,
                              intake=intake, on_step=on_step)
    except RunStopped as e:
        return Outcome(f"**{e}**")
    except Exception as e:                       # noqa: BLE001 - shown on the page, details in the server log
        traceback.print_exc()
        return Outcome(f"**Something went wrong** ({type(e).__name__}). Please try again, or run it offline.")
    log = result.run_dir / "log.json"
    return Outcome(summary_markdown(result), str(result.pdf), str(log) if log.exists() else None)


async def start_review(question: str, price, factsheet, kid, peer_factsheets, json_files, offline: bool,
                       limits: AiLimits, on_step: Progress | None = None, out_root: Path = RUNS,
                       runner=run_review, reader=read_documents) -> Outcome:
    """ "Run the review": JSON files run straight away; documents are read first and shown for confirmation """
    price, factsheet, kid = map(_one, (price, factsheet, kid))
    peers = _many(peer_factsheets)
    json_files = [p for p in (json_files or []) if p]
    for path, allowed, what in ((price, PRICE_TYPES, "price file"), (factsheet, DOC_TYPES, "factsheet"),
                                (kid, DOC_TYPES, "KID or prospectus"),
                                *((p, DOC_TYPES, "peer factsheet") for p in peers)):
        if (wrong := _wrong_type(path, allowed, what)):
            return Outcome(wrong)

    if json_files:                                         # Advanced route: pre-typed data, no reading step
        if not price:
            return Outcome("Please add the price file as well as the JSON files.")
        folder = Path(tempfile.mkdtemp(prefix="fund-review-"))
        try:
            prepare_inputs([price] + json_files, folder)
            if offline:
                return await _run_controller(folder, question, True, on_step, out_root, runner)
            if (refused := limits.start()):
                return Outcome(refused)
            try:
                return await _run_controller(folder, question, False, on_step, out_root, runner)
            finally:
                limits.finish()
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    if not (price and factsheet):
        return Outcome(NEED_FILES)
    if offline:
        return Outcome(NEEDS_AI)
    if (refused := limits.start()):
        return Outcome(refused)
    try:
        if on_step:
            on_step("Reading the documents…")
        intake = await reader(Path(factsheet), Path(kid) if kid else None, [Path(p) for p in peers])
    except Exception as e:                       # noqa: BLE001
        traceback.print_exc()
        return Outcome(f"**The documents could not be read** ({type(e).__name__}). Check they are PDF or Word files.")
    finally:
        limits.finish()
    message = ("**Check what the agent read.** Correct anything wrong in the **Value** column, then click "
               "**Confirm and run**.")
    failed = [f["message"] for f in intake.get("flags", []) if f.get("level") == "blocking"]
    if failed:
        message += ("\n\n**The Extractor Agent could not read the documents**, so the values below are empty. "
                    "Fill them in, or try again later. (" + "; ".join(failed)[:300] + ")")
    return Outcome(message, state={"intake": intake, "price": price, "paid": True})


async def confirm_review(question: str, rows: list[list[str]], state: dict, limits: AiLimits,
                         on_step: Progress | None = None, out_root: Path = RUNS, runner=run_review) -> Outcome:
    """ "Confirm and run": check the confirmed values, write the inputs and run the review """
    intake = (state or {}).get("intake")
    if not intake:
        return Outcome("Please click **Run the review** first, so the agent can read the documents.")
    values = [row[1] for row in rows]
    built = build_inputs(intake, values)
    if built.problems:
        return Outcome("**Please fix these values before the run:**\n" + "\n".join(f"- {p}" for p in built.problems),
                       state=state)
    paid = state.get("paid", False)
    if (refused := limits.start(count=not paid)):
        return Outcome(refused, state=state)
    folder = Path(tempfile.mkdtemp(prefix="fund-review-"))
    try:
        write_inputs(built, folder)
        prepare_inputs([state["price"]], folder)
        outcome = await _run_controller(folder, question, False, on_step, out_root, runner,
                                        intake=intake | {"rows": built.rows})
    finally:
        limits.finish()
        shutil.rmtree(folder, ignore_errors=True)
    outcome.state = state | {"paid": False}
    return outcome


async def with_progress(work: Callable[[Progress], Awaitable[Outcome]]):
    """ Run `work` and yield ("progress", message) as steps start, then ("done", outcome) """
    queue: asyncio.Queue[str] = asyncio.Queue()
    task = asyncio.create_task(work(queue.put_nowait))
    while not task.done():
        try:
            yield "progress", await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
    while not queue.empty():
        yield "progress", queue.get_nowait()
    yield "done", task.result()


# --- The page -------------------------------------------------------------------------------------------------------

def demo_files() -> dict[str, list[str] | str]:
    return {"price": str(DEMO / "prices.csv"), "factsheet": str(DEMO / "factsheet.pdf"),
            "peer": str(DEMO / "peer_factsheet.pdf"),
            "json": [str(DEMO / n) for n in ("fund_profile.json", "factsheet_performance.json", "peer.json")]}


def example_zip() -> str:
    """ The demo files in one zip, for "Download example files" """
    path = Path(tempfile.gettempdir()) / "fund_review_example_files.zip"
    with zipfile.ZipFile(path, "w") as z:
        for p in sorted(DEMO.iterdir()):
            if p.is_file():
                z.write(p, f"example_files/{p.name}")
    return str(path)


CSS = f"""
.fp-header h1 {{ color: {NAVY}; margin-bottom: 0; }}
.fp-header p {{ color: #4c5966; margin-top: 4px; }}
.fp-notice {{ background: #fff6e0; border-left: 4px solid #d18f00; padding: 8px 12px; border-radius: 4px; }}
.fp-progress {{ font-weight: bold; color: {NAVY}; }}
"""


def build_ui(limits: AiLimits | None = None) -> gr.Blocks:
    limits = limits or AiLimits(load_settings().web)
    with gr.Blocks(title="Fund Performance Review") as ui:
        state = gr.State({})
        gr.HTML("<div class='fp-header'><h1>Fund performance review</h1><p>Code does the maths and the ratings, AI "
                "reads and writes, and a person makes the call.</p></div>")
        gr.Markdown(PUBLIC_DATA, elem_classes="fp-notice")
        gr.Markdown(INSTRUCTIONS)
        gr.Markdown(FILES_TABLE)
        gr.DownloadButton("Download example files", value=example_zip(), size="sm")
        with gr.Accordion("How the agent works", open=True):
            gr.HTML(how_it_works_html())

        question = gr.Textbox(label="Question", value=DEFAULT_QUESTION, lines=2)
        with gr.Row():
            price = gr.File(label="Price file (CSV or Excel), required", file_types=PRICE_TYPES, type="filepath")
            factsheet = gr.File(label="Factsheet (PDF or Word), required", file_types=DOC_TYPES, type="filepath")
        with gr.Row():
            kid = gr.File(label="KID or prospectus (PDF or Word), optional", file_types=DOC_TYPES, type="filepath")
            peer = gr.File(label="Peer fund factsheets (PDF or Word), optional: approved peers are built in",
                           file_count="multiple", file_types=DOC_TYPES, type="filepath")
        with gr.Accordion("Advanced: JSON files (skip the AI reading step)", open=False) as advanced:
            json_files = gr.File(label="fund_profile.json, factsheet_performance.json, peer.json", file_count="multiple",
                                 file_types=[".json"], type="filepath")
        with gr.Row():
            offline = gr.Checkbox(label="Offline: no AI calls (works with the demo or JSON files)", value=True)
            use_demo = gr.Button("Use the demo files (made-up fund)", size="sm")
        run = gr.Button("Run the review", variant="primary")
        progress = gr.Markdown(elem_classes="fp-progress")
        with gr.Group(visible=False) as confirm_box:
            values = gr.Dataframe(headers=COLUMNS, datatype=["str"] * 4, interactive=True, static_columns=[0, 2, 3],
                                  wrap=True, column_widths=["28%", "24%", "20%", "28%"],
                                  label="What the agent read (edit the Value column)")
            confirm = gr.Button("Confirm and run", variant="primary")
        status = gr.Markdown()
        with gr.Row():
            pdf = gr.File(label="PDF report", interactive=False)
            log = gr.File(label="Run log (log.json)", interactive=False)

        async def on_run(q, p, f, k, pr, j, off, st):
            keep = gr.update()
            yield "Starting…", keep, gr.update(visible=False), keep, "", None, None, st
            async for kind, item in with_progress(lambda say: start_review(q, p, f, k, pr, j, off, limits, say)):
                if kind == "progress":
                    yield item, keep, keep, keep, keep, keep, keep, keep
                elif item.state.get("intake"):                     # documents read: show the table to confirm
                    gaps = missing(item.state["intake"])
                    note = f"⚠ Please fill in: {', '.join(gaps)}." if gaps else "All required values are filled in."
                    yield (note, table(item.state["intake"]), gr.update(visible=True), gr.update(interactive=not gaps),
                           item.message, None, None, item.state)
                else:
                    yield "", keep, gr.update(visible=False), keep, item.message, item.pdf, item.log, {}

        async def on_confirm(q, rows, st):
            rows = rows.values.tolist() if hasattr(rows, "values") else rows
            yield "Starting…", gr.update(), None, None, st
            async for kind, item in with_progress(lambda say: confirm_review(q, rows, st, limits, say)):
                if kind == "progress":
                    yield item, gr.update(), gr.update(), gr.update(), gr.update()
                else:
                    yield "", item.message, item.pdf, item.log, item.state

        def on_edit(rows, st):
            """ Keep "Confirm and run" off while a required value is empty """
            intake = (st or {}).get("intake")
            if not intake:
                return gr.update(), gr.update()
            rows = rows.values.tolist() if hasattr(rows, "values") else rows
            gaps = missing(intake, [r[1] for r in rows])
            note = f"⚠ Please fill in: {', '.join(gaps)}." if gaps else "All required values are filled in."
            return gr.update(interactive=not gaps), note

        def on_demo():
            d = demo_files()
            return d["price"], d["factsheet"], None, [d["peer"]], d["json"], True, gr.update(open=True)

        private = {"api_visibility": "private"}         # the page is the only way in, with its limits
        use_demo.click(on_demo, outputs=[price, factsheet, kid, peer, json_files, offline, advanced], **private)
        run.click(on_run, inputs=[question, price, factsheet, kid, peer, json_files, offline, state],
                  outputs=[progress, values, confirm_box, confirm, status, pdf, log, state], **private)
        values.change(on_edit, inputs=[values, state], outputs=[confirm, progress], **private)
        confirm.click(on_confirm, inputs=[question, values, state], outputs=[progress, status, pdf, log, state],
                      **private)
    return ui


def launch(ui: gr.Blocks | None = None) -> None:
    """ Hosts such as Render set PORT and need the app to listen on all interfaces. With APP_USERNAME and
    APP_PASSWORD set, the page asks for them before it opens """
    ui = ui or build_ui()
    on_host = on_server()
    ui.queue(default_concurrency_limit=int(os.getenv("MAX_CONCURRENT_RUNS", "2")))
    ui.launch(css=CSS, theme=gr.themes.Soft(), server_name="0.0.0.0" if on_host else None,
              server_port=int(os.environ["PORT"]) if on_host else None, auth=login(),
              auth_message="Fund performance review: please log in.", max_file_size="20mb")
