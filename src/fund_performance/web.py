""" The Gradio front end (step 11): upload the files, ask the question, download the PDF

Plain code around the workflow controller: it copies the uploaded files into a fresh folder, runs the review and
shows the draft verdict, the ratings and the findings, with the PDF and the run log to download. Public data only:
the page says so before anything is uploaded.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import tempfile
import traceback
import gradio as gr
from fund_performance.controller import DEFAULT_QUESTION, RunResult, RunStopped, run_review

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DEMO = ROOT / "demo" / "sample_index_fund"
FILE_TYPES = [".json", ".csv", ".xlsx", ".xls", ".pdf", ".docx", ".txt"]
MAX_FILES = 10
NAVY = "#1f3a5f"
RATING_WORDS = {"GREEN": "🟢 Green", "AMBER": "🟠 Amber", "RED": "🔴 Red", "CHECK DATA": "🟣 Check data",
                "MANUAL CHECK": "⚪ Manual check"}

PUBLIC_DATA = ("**Public data only.** Files and figures may be sent to OpenAI, which has data sharing on for this "
               "service. Never upload confidential or client data.")
HOW_TO = ("Upload `fund_profile.json`, a price file (CSV or Excel), and `factsheet_performance.json` or the factsheet "
          "and KID PDFs; add `peer.json` to judge value and fees. A review takes about 1 to 2 minutes.")


@dataclass
class Outcome:
    message: str                     # Markdown for the page
    pdf: str | None = None
    log: str | None = None


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


def summary_markdown(result: RunResult) -> str:
    """ The draft verdict, the ratings, the findings and actions, and what to check, for the page """
    facts = result.facts or {}
    card = facts.get("scorecard", {})
    fund = facts.get("fund", {})
    lines = [f"### {fund.get('fund_name', 'Fund')}", f"Figures to {fund.get('as_of_date', '')}", "",
             f"**Draft verdict: {card.get('verdict', '')}**", "", "| Question | Rating |", "|---|---|"]
    lines += [f"| {p['name']} | {RATING_WORDS.get(p['rating'], p['rating'])} |" for p in card.get("pillars", [])]
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
                 runner=run_review) -> Outcome:
    """ One review from the page. Never raises: a problem comes back as a message """
    if not files:
        return Outcome("Please upload the fund's files first (or click **Use the demo files**).")
    folder = Path(tempfile.mkdtemp(prefix="fund-review-"))
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


CSS = f"""
.fp-header h1 {{ color: {NAVY}; margin-bottom: 0; }}
.fp-header p {{ color: #4c5966; margin-top: 4px; }}
.fp-notice {{ background: #fff6e0; border-left: 4px solid #d18f00; padding: 8px 12px; border-radius: 4px; }}
"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Fund Performance Review") as ui:
        gr.HTML("<div class='fp-header'><h1>Fund performance review</h1><p>Code does the maths and the ratings, AI "
                "reads and writes, and a person makes the call.</p></div>")
        gr.Markdown(PUBLIC_DATA, elem_classes="fp-notice")
        gr.Markdown(HOW_TO)
        question = gr.Textbox(label="Question", value=DEFAULT_QUESTION, lines=2)
        files = gr.File(label="Fund files", file_count="multiple", file_types=FILE_TYPES, type="filepath")
        with gr.Row():
            offline = gr.Checkbox(label="Offline: no AI calls (template text, no web research)", value=False)
            use_demo = gr.Button("Use the demo files (made-up fund)", size="sm")
        run = gr.Button("Run the review", variant="primary")
        status = gr.Markdown()
        with gr.Row():
            pdf = gr.File(label="PDF report", interactive=False)
            log = gr.File(label="Run log (log.json)", interactive=False)

        async def on_run(q, f, off):
            yield "Running the review… this takes about 1 to 2 minutes.", None, None
            outcome = await review(q, f, off)
            yield outcome.message, outcome.pdf, outcome.log

        use_demo.click(lambda: (demo_files(), True), outputs=[files, offline])
        run.click(on_run, inputs=[question, files, offline], outputs=[status, pdf, log])
    return ui


def login() -> tuple[str, str] | None:
    """ Optional password protection, so a public link cannot spend the API credit (as in the old app) """
    username, password = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    return (username, password) if username and password else None


def launch(ui: gr.Blocks | None = None) -> None:
    """ Hosts such as Render set PORT and need the app to listen on all interfaces """
    ui = ui or build_ui()
    on_host = "PORT" in os.environ
    ui.queue(default_concurrency_limit=int(os.getenv("MAX_CONCURRENT_RUNS", "2")))
    ui.launch(css=CSS, theme=gr.themes.Soft(), server_name="0.0.0.0" if on_host else None,
              server_port=int(os.environ["PORT"]) if on_host else None, auth=login(), max_file_size="20mb")
