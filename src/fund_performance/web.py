""" The Gradio front end (step 11): upload the files, ask the question, download the PDF

Plain code around the workflow controller: it copies the uploaded files into a fresh folder, runs the review and
shows the draft verdict, the ratings with their one-line reasons and the findings, with the PDF and the run log to
download. Public data only: the page says so before anything is uploaded.

Protecting the API key on a public link: AI runs need a login when APP_USERNAME and APP_PASSWORD are set. Without
a login, only the offline demo can be run. On a server with no login set up (PORT is set but no credentials), AI
runs are switched off; on your own computer (no PORT), they are allowed.
"""
from dataclasses import dataclass
import asyncio
import hashlib
import hmac
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import traceback
import gradio as gr
from fund_performance.controller import DEFAULT_QUESTION, RunResult, RunStopped, run_review

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DEMO = ROOT / "demo" / "sample_index_fund"
FILE_TYPES = [".json", ".csv", ".xlsx", ".xls", ".pdf", ".docx", ".txt"]
MAX_FILES = 10
MAX_LOGIN_TRIES = 5                     # per visitor (page session)
MAX_FAILURES_SERVER = 20                # all visitors together, within FAILURE_WINDOW_SECONDS
FAILURE_WINDOW_SECONDS = 600
NAVY = "#1f3a5f"
RATING_WORDS = {"GREEN": "🟢 Green", "AMBER": "🟠 Amber", "RED": "🔴 Red", "CHECK DATA": "🟣 Check data",
                "MANUAL CHECK": "⚪ Manual check"}

PUBLIC_DATA = ("**Public data only.** Files and figures may be sent to OpenAI, which has data sharing on for this "
               "service. Never upload confidential or client data.")
HOW_TO = ("Upload `fund_profile.json`, a price file (CSV or Excel), and `factsheet_performance.json` or the factsheet "
          "and KID PDFs; add `peer.json` to judge value and fees. A review takes about 1 to 2 minutes.")
NEED_LOGIN = "AI runs need a login. Log in above, or tick **Offline** and use the demo files."
DEMO_ONLY = "Without a login, only the offline demo can be run. Click **Use the demo files**, or log in."
AI_OFF = ("AI runs are switched off on this server, because no login is set up (APP_USERNAME and APP_PASSWORD). "
          "The offline demo still works.")


@dataclass
class Outcome:
    message: str                     # Markdown for the page
    pdf: str | None = None
    log: str | None = None


# --- Who may run what --------------------------------------------------------------------------------------------

def credentials() -> tuple[str, str] | None:
    username, password = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    return (username, password) if username and password else None


def on_server() -> bool:
    """ Hosts such as Render set PORT """
    return "PORT" in os.environ


def ai_allowed(logged_in: bool) -> bool:
    """ With a login set up, AI runs need it. Without one, AI runs only on your own computer, never on a server """
    if credentials():
        return logged_in
    return not on_server()


_failures: list[float] = []            # times of failed logins, for the server-wide limit


def logins_paused(now: float | None = None) -> bool:
    """ After too many failed logins from anyone, logins pause for a while (slows down guessing) """
    now = time.monotonic() if now is None else now
    _failures[:] = [t for t in _failures if now - t < FAILURE_WINDOW_SECONDS]
    return len(_failures) >= MAX_FAILURES_SERVER


def check_login(username: str, password: str) -> bool:
    expected = credentials()
    if not expected or logins_paused():
        return False
    # Compare in constant time, so the answer's timing gives nothing away
    ok = (hmac.compare_digest((username or "").encode(), expected[0].encode())
          & hmac.compare_digest((password or "").encode(), expected[1].encode()))
    if not ok:
        _failures.append(time.monotonic())
    return bool(ok)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_demo(files: list[str]) -> bool:
    """ True if every uploaded file is one of the demo files, byte for byte """
    demo = {_digest(Path(p)) for p in demo_files()}
    paths = [Path(p) for p in files if Path(p).is_file()]
    return bool(paths) and all(_digest(p) in demo for p in paths)


def gate(offline: bool, files: list[str], logged_in: bool) -> str | None:
    """ Why this run may not go ahead, or None. Checked on the server for every run """
    if ai_allowed(logged_in):
        return None
    if not offline:
        return AI_OFF if not credentials() else NEED_LOGIN
    if not is_demo(files):
        return DEMO_ONLY
    return None


# --- The review ------------------------------------------------------------------------------------------------

def _safe_name(name: str) -> str:
    """ A plain file name: no folders, only letters, digits, dot, dash and underscore """
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    return cleaned[:120]


def prepare_inputs(paths: list[str], dest: Path) -> list[str]:
    """ Copy the uploaded files into dest, keeping their names (made safe); returns the names used """
    dest.mkdir(parents=True, exist_ok=True)
    used: list[str] = []
    for p in paths[:MAX_FILES]:
        src = Path(p)
        if not src.is_file():
            continue
        name = _safe_name(src.name)
        stem, suffix = Path(name).stem, Path(name).suffix
        n = 2
        while name in used:
            name, n = f"{stem}_{n}{suffix}", n + 1
        shutil.copy(src, dest / name)
        used.append(name)
    return used


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def summary_markdown(result: RunResult) -> str:
    """ The draft verdict, the ratings with their one-line reasons, the findings and actions, and what to check """
    facts = result.facts or {}
    card = facts.get("scorecard", {})
    fund = facts.get("fund", {})
    reasons = getattr(result, "reasons", {}) or {}
    lines = [f"### {fund.get('fund_name', 'Fund')}", f"Figures to {fund.get('as_of_date', '')}", "",
             f"**Draft verdict: {card.get('verdict', '')}**", "", "| Question | Rating | Why |", "|---|---|---|"]
    lines += [f"| {p['name']} | {RATING_WORDS.get(p['rating'], p['rating'])} | {_cell(reasons.get(p['name'], ''))} |"
              for p in card.get("pillars", [])]
    if result.narrative:
        lines += ["", "**Key findings**"] + [f"- {f}" for f in result.narrative.output.key_findings]
        lines += ["", "**Recommended actions**"] + [f"- {a}" for a in result.narrative.output.action_texts]
    flags = facts.get("data_flags", [])
    blocking = [f for f in flags if f["level"] == "blocking"]
    if blocking:
        lines += ["", "**Data checks to resolve**"] + [f"- {f['message']}" for f in blocking]
    elif flags:
        lines += ["", f"{len(flags)} data warning(s): see the appendix of the PDF."]
    lines += ["", "_Draft for oversight review: the verdict is final only when signed by the reviewer._"]
    return "\n".join(lines)


async def review(question: str, files: list[str] | None, offline: bool = False, out_root: Path = RUNS,
                 runner=run_review, logged_in: bool = True) -> Outcome:
    """ One review from the page. Never raises: a problem comes back as a message """
    if not files:
        return Outcome("Please upload the fund's files first (or click **Use the demo files**).")
    refused = gate(offline, files, logged_in)
    if refused:
        return Outcome(refused)
    folder = Path(tempfile.mkdtemp(prefix="fund-review-"))
    names: list[str] = []
    try:
        names = prepare_inputs(files, folder)
        result = await runner(folder, (question or "").strip() or DEFAULT_QUESTION, out_root, offline)
    except RunStopped as e:
        return Outcome(f"**{e}**\n\nFiles received: {', '.join(names) or 'none'}.")
    except Exception as e:                       # noqa: BLE001 - shown on the page, details in the server log
        traceback.print_exc()
        return Outcome(f"**Something went wrong** ({type(e).__name__}). Please try again, or run it offline.")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    log = result.run_dir / "log.json"
    return Outcome(summary_markdown(result), str(result.pdf), str(log) if log.exists() else None)


def demo_files() -> list[str]:
    return [str(p) for p in sorted(DEMO.iterdir()) if p.is_file()]


# --- The page --------------------------------------------------------------------------------------------------

CSS = f"""
.fp-header h1 {{ color: {NAVY}; margin-bottom: 0; }}
.fp-header p {{ color: #4c5966; margin-top: 4px; }}
.fp-notice {{ background: #fff6e0; border-left: 4px solid #d18f00; padding: 8px 12px; border-radius: 4px; }}
"""


def access_note(logged_in: bool) -> str:
    if ai_allowed(logged_in):
        return "AI runs are on." if credentials() else "AI runs are on (your own computer: no login set up)."
    return AI_OFF if not credentials() else "Not logged in: only the offline demo can be run."


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Fund Performance Review") as ui:
        logged_in = gr.State(False)            # kept on the server for each visitor; the browser cannot set it
        tries = gr.State(0)
        gr.HTML("<div class='fp-header'><h1>Fund performance review</h1><p>Code does the maths and the ratings, AI "
                "reads and writes, and a person makes the call.</p></div>")
        gr.Markdown(PUBLIC_DATA, elem_classes="fp-notice")
        gr.Markdown(HOW_TO)
        access = gr.Markdown(access_note(False))
        with gr.Accordion("Log in for AI runs", open=False, visible=credentials() is not None):
            with gr.Row():
                username = gr.Textbox(label="Username")
                password = gr.Textbox(label="Password", type="password")
            login_button = gr.Button("Log in", size="sm")
        question = gr.Textbox(label="Question", value=DEFAULT_QUESTION, lines=2)
        files = gr.File(label="Fund files", file_count="multiple", file_types=FILE_TYPES, type="filepath")
        with gr.Row():
            offline = gr.Checkbox(label="Offline: no AI calls (template text, no web research)",
                                  value=not ai_allowed(False))
            use_demo = gr.Button("Use the demo files (made-up fund)", size="sm")
        run = gr.Button("Run the review", variant="primary")
        status = gr.Markdown()
        with gr.Row():
            pdf = gr.File(label="PDF report", interactive=False)
            log = gr.File(label="Run log (log.json)", interactive=False)

        async def on_login(u, p, n):
            if n >= MAX_LOGIN_TRIES or logins_paused():
                return False, n, "Too many tries: please try again later."
            if check_login(u, p):
                return True, 0, access_note(True)
            await asyncio.sleep(1)               # slows down guessing
            return False, n + 1, "Wrong username or password. " + access_note(False)

        async def on_run(q, f, off, ok):
            yield "Running the review… this takes about 1 to 2 minutes.", None, None
            outcome = await review(q, f, off, logged_in=ok)
            yield outcome.message, outcome.pdf, outcome.log

        # Not callable through Gradio's API: the page is the only way in, with its login and limits
        login_button.click(on_login, inputs=[username, password, tries], outputs=[logged_in, tries, access],
                           api_visibility="private")
        use_demo.click(lambda: (demo_files(), True), outputs=[files, offline], api_visibility="private")
        run.click(on_run, inputs=[question, files, offline, logged_in], outputs=[status, pdf, log],
                  api_visibility="private")
    return ui


def launch(ui: gr.Blocks | None = None) -> None:
    """ Hosts such as Render set PORT and need the app to listen on all interfaces. The login for AI runs is on
    the page (not Gradio's own login), so anyone can open it and run the offline demo """
    ui = ui or build_ui()
    on_host = on_server()
    ui.queue(default_concurrency_limit=int(os.getenv("MAX_CONCURRENT_RUNS", "2")))
    ui.launch(css=CSS, theme=gr.themes.Soft(), server_name="0.0.0.0" if on_host else None,
              server_port=int(os.environ["PORT"]) if on_host else None, max_file_size="20mb")
