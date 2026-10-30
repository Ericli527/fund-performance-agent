""" The Gradio front end (step 11): upload the fund's documents, run the review, download the PDF

Plain code around the intake (intake.py) and the workflow controller. The main route: a price file and the
factsheet (optionally the KID or prospectus and peer funds' factsheets; without them the approved peers in
config/peers.yaml are used). The Extractor and Mandate agents read the
documents and the review runs straight on: code checks every value against the documents (intake.self_check) and
flags what it cannot confirm; a required value it cannot find stops the run with a clear message. JSON files are an optional "Advanced" route that skips the reading step. Public data only: the page says
so first.

The login: when APP_USERNAME and APP_PASSWORD are set, the page asks for them before it opens (Gradio's own
login). On a server with no login set up (PORT is set but no credentials), AI runs are switched off and only the
offline demo works; on your own computer no login is needed. Limits in config/settings.yaml also protect the API
key: a daily number of AI reviews, and at most one AI review at a time. Offline runs (no AI) are not limited.

There is no Offline switch on the page. Code decides: the unchanged demo files always run offline (deterministic, no
AI); every other review uses the AI workflow. For development and testing, FUND_REVIEW_OFFLINE=1 in the environment
runs every review offline (the command line keeps --offline).

The input page (UX redesign, stage 1): what to analyse (three cards that fill in the review question; all four
ratings are always calculated), the review question, the two required documents with a check of each file, the
report audience (recorded only: both audiences get the same report in this version), additional options (KID, peer
factsheets, JSON files), one main action and the demo, the public-data note and a closed Help & methodology section.
"""
import asyncio
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import traceback
import uuid
from typing import Awaitable, Callable
import zipfile
from html import escape
import gradio as gr
from fund_performance.config import WebSettings, load_settings
from fund_performance.dashboard import dashboard_data, dashboard_html, technical_html
from fund_performance.controller import (DEFAULT_QUESTION, DOCUMENTS_STAGE, RunResult, RunStopped, progress_line,
                                         run_review)
from fund_performance.plain import verdict_meaning, verdict_name
from agents import trace
from fund_performance.agents.base import AI_CALLS, api_key_present
from fund_performance.presentation import MISSING_MEANING, download_copy, missing_evidence
from fund_performance.demos import Demo, find_demo, matching_demo, return_checks, shown_demos
from fund_performance.report import ANGLE_WORDS, REPORT_TYPE_WORDS
from fund_performance.intake import read_documents, self_check, write_inputs

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
AI_OFF = ("AI runs are switched off here (AI_RUNS_ENABLED, and on a server the login APP_USERNAME and APP_PASSWORD). "
          "You can still run the Quick Demo and other reviews that need no AI.")
NEEDS_AI = ("Reading the documents uses AI, which is switched off in this setup. Pick a Quick Demo under **Try a "
            "demo**, or add complete JSON inputs under **Additional options**.")
NEED_FILES = ("Please add the fund price data and the fund factsheet (the agents read it), or add complete JSON inputs "
              "under **Additional options**, or pick a demo under **Try a demo**.")
FACTSHEET_LABEL = "Fund factsheet · PDF or Word · Required for AI reading (not needed with complete JSON or a Quick Demo)"
JSON_NEEDED = {"fund_profile": "fund_profile.json", "factsheet_performance": "factsheet_performance.json"}
OFFLINE_ENV = "FUND_REVIEW_OFFLINE"         # development and testing only: every review runs without AI

PUBLIC_DATA = ("**Public data only.** Files and figures may be sent to OpenAI, which has data sharing on for this "
               "service. Never upload confidential client data or internal company documents: use published "
               "factsheets, KIDs and price histories only.")
PUBLIC_DATA_HTML = PUBLIC_DATA.replace("**Public data only.**", "<b>Public data only.</b>")
INSTRUCTIONS = """### How to use it
1. **Try a demo:** pick Fidelity or Vanguard under **Try a demo**, then **Run Fund Review**. The Quick Demo is free, takes seconds and uses no AI.
2. **Test a real fund:** download the fund's public price history (CSV or Excel), latest factsheet and KID from the provider's website. Upload the prices and the factsheet; add the KID (and any peer factsheets) under **Additional options**. The agents read them in 1–2 minutes and the page shows each step as it runs.
3. **Let the agent check itself:** code checks every value the AI read against the documents and the prices, and flags anything it cannot confirm. Takes 1–2 minutes.
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
    (["Person", "AI"], "You provide public documents, a price file and a question; the Task Planner turns the question "
                       "into tasks (which questions come first, what to research, who the summary is for)."),
    (["AI", "Code"], "<b>Read and check:</b> the Extractor reads the documents; code finds every value in the "
                     "documents and flags any it cannot, then checks currency, pricing time (noon vs close), gaps, "
                     "repeated prices and factsheet cross-checks."),
    (["AI", "Code"], "<b>Understand the fund:</b> the Mandate Agent reads the objective; a decision tree chooses how "
                     "to judge it."),
    (["Code"], "<b>Measure:</b> returns, risk, gaps to the index and peers, and statistical tests."),
    (["Code"], "<b>Score:</b> four questions rated Green, Amber or Red → suggested verdict."),
    (["AI"], "<b>Research and explain:</b> approved pages plus up to 3 web searches; the AI writes the market context "
             "only, checked by code and a separate Evaluator."),
    (["AI", "Code"], "<b>Draft and judge:</b> Reporting Agents draft the conclusion for different readers (board, "
                     "analyst, manager meeting); code checks every figure, the Judge marks each draft on a checklist, "
                     "and code picks the best or sends them back."),
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


# --- What to analyse, the audience and offline runs ----------------------------------------------------------------

REVIEW_TYPES = {      # value: (title, subtitle, the review question it fills in)
    "overall": ("Overall Review", "Complete fund analysis",
                "Is this fund meeting its investment objective, and are its fees justified?"),
    "performance": ("Performance", "Returns and benchmark tracking",
                    "How has this fund performed against its benchmark, and does it track it closely enough?"),
    "fees_value": ("Fees & Value", "Costs and peer comparison",
                   "Are this fund's fees justified, and does it give investors value compared with similar funds?"),
}
DEFAULT_REVIEW = "overall"
UI_QUESTION = REVIEW_TYPES[DEFAULT_REVIEW][2]
REVIEW_HELP = ("Fills in the review question below, which tells the agents what to focus on. All four ratings "
               "(mandate, performance, value and fees) are always calculated the same way.")
AUDIENCES = {"analyst": "Investment Analyst", "management": "Management"}
AUDIENCE_HELP = ("Changes what the on-screen results show first: Investment Analyst gives the full detail, Management "
                 "a summary and the decisions. The figures, ratings and PDF are the same for both.")


def question_for(review_type: str, current: str) -> str:
    """ The question a review-type card fills in. A question the user has written themselves is kept """
    current = (current or "").strip()
    if current and current not in {q for _, _, q in REVIEW_TYPES.values()}:
        return current
    return REVIEW_TYPES.get(review_type, REVIEW_TYPES[DEFAULT_REVIEW])[2]


def _same_bytes(path: str | None, reference: Path) -> bool:
    try:
        return bool(path) and Path(path).read_bytes() == reference.read_bytes()
    except OSError:
        return False


def uses_demo_files(price, json_files) -> bool:
    """ True when the price file and the JSON files are exactly the demo's (checked byte for byte) """
    json_files = [p for p in (json_files or []) if p]
    demo_json = [DEMO / n for n in ("fund_profile.json", "factsheet_performance.json", "peer.json")]
    return (_same_bytes(_one(price), DEMO / "prices.csv") and len(json_files) == len(demo_json)
            and all(any(_same_bytes(p, ref) for p in json_files) for ref in demo_json))


def run_offline(price, json_files) -> bool:
    """ Code decides, not the user: the demo runs offline (deterministic); FUND_REVIEW_OFFLINE=1 runs every review
    offline, for development and testing; every other review uses the AI workflow """
    if os.getenv(OFFLINE_ENV, "").strip().lower() in ("1", "true", "yes"):
        return True
    return uses_demo_files(price, json_files) or matching_demo(price, json_files) is not None


def _size(path: Path) -> str:
    n = path.stat().st_size
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def missing_json(json_files) -> list[str]:
    """ What complete JSON inputs still lack (a fund profile and the factsheet figures; peer.json is optional), so
    they can replace the factsheet document. An unreadable file counts as missing """
    from fund_performance.io import detect_file_type
    kinds = set()
    for p in [p for p in (json_files or []) if p]:
        try:
            kinds.add(detect_file_type(p))
        except (OSError, ValueError):
            continue
    return [name for kind, name in JSON_NEEDED.items() if kind not in kinds]


def factsheet_status(factsheet, json_files) -> str:
    """ The line under the factsheet field: the file, or whether it is needed given the JSON inputs """
    if _one(factsheet):
        return file_status(factsheet, DOC_TYPES, "PDF or Word")
    json_files = [p for p in (json_files or []) if p]
    if not json_files:
        return ""
    missing = missing_json(json_files)
    if not missing:
        return ("<span class='fp-ok'>✓ Not needed: the JSON inputs already hold the fund profile and the factsheet "
                "figures (no AI reading).</span>")
    return (f"<span class='fp-bad'>✗ The JSON inputs are incomplete (missing {', '.join(missing)}): add them, or "
            "remove the JSON files and add the factsheet.</span>")


def file_status(value, allowed: list[str], kinds: str) -> str:
    """ The line under an upload area: the file's name and size, or why it cannot be used """
    paths = _many(value)
    if not paths:
        return ""
    lines = []
    for p in paths:
        path = Path(p)
        if path.suffix.lower() not in allowed:
            lines.append(f"<span class='fp-bad'>✗ {path.name}: not a {kinds} file. Please upload {kinds}.</span>")
        else:
            lines.append(f"<span class='fp-ok'>✓ {path.name} · {_size(path)}</span>")
    return "<br>".join(lines)


# --- Login and limits on AI runs (config/settings.yaml, web) -----------------------------------------------------

def login() -> tuple[str, str] | None:
    """ The page's username and password from the environment (.env locally, Render's settings online) """
    username, password = os.getenv("APP_USERNAME"), os.getenv("APP_PASSWORD")
    return (username, password) if username and password else None


def on_server() -> bool:
    """ Hosts such as Render set PORT """
    return "PORT" in os.environ


AI_ENV = "AI_RUNS_ENABLED"


def ai_enabled_by_setting() -> bool:
    """ The independent AI switch: AI runs happen only when AI_RUNS_ENABLED is true (off when unset) """
    return os.getenv(AI_ENV, "").strip().lower() in ("1", "true", "yes")


def ai_switched_off() -> bool:
    """ AI runs need the switch on, and on a server also the login; offline reviews never need either """
    return not ai_enabled_by_setting() or (on_server() and login() is None)


def prune_runs(root: Path, keep_hours: float, now: float | None = None) -> list[str]:
    """ Delete review folders older than keep_hours (reports and logs are kept for downloading, not stored). Only
    folders named like a run are touched; the AI-run counter file stays """
    import re as _re
    import time as _time
    now = now or _time.time()
    gone = []
    for path in root.glob("*") if root.is_dir() else []:
        if path.is_dir() and _re.fullmatch(r"\d{8}-\d{6}(-[0-9a-f]{8})?", path.name) and \
                now - path.stat().st_mtime > keep_hours * 3600:
            shutil.rmtree(path, ignore_errors=True)
            gone.append(path.name)
    return gone


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
    message: str                             # Markdown for the page (a refusal or a stopped run; or the plain summary)
    pdf: str | None = None
    log: str | None = None
    data: dict | None = None                 # the finished run, for the dashboard (dashboard.dashboard_data)
    executive: str | None = None             # report_executive.pdf (stage 3); None if it could not fit
    run_info: str = ""                       # run ID, trace ID and AI calls, for the progress area


def summary_markdown(result: RunResult) -> str:
    """ The suggested verdict and conclusion, the ratings with their one-line reasons, the points for judgement,
    the findings, actions and questions, and what to check """
    facts = result.facts or {}
    card = facts.get("scorecard", {})
    fund = facts.get("fund", {})
    reasons = getattr(result, "reasons", {}) or {}
    cell = lambda text: " ".join(str(text).split()).replace("|", "/")      # noqa: E731
    lines = [f"### {fund.get('fund_name', 'Fund')}", f"Figures to {fund.get('as_of_date', '')}", "",
             f"**Suggested verdict: {verdict_name(card.get('verdict', ''))}** "
             f"({MISSING_MEANING if card.get('verdict', '').startswith('Pending') and missing_evidence(facts) else verdict_meaning(card.get('verdict', ''))})"]
    concl = facts.get("suggested_conclusion") or {}
    if concl.get("text"):
        who = (f"AI draft for the {ANGLE_WORDS.get(concl.get('angle'), concl.get('angle'))}, chosen by the Judge"
               if concl.get("source") == "ai" else "written by code")
        lines += ["", f"**Suggested conclusion ({who}; draft for the analyst).** {concl['text']}"]
    plan = facts.get("plan") or {}
    if plan:
        lines += ["", f"_Plan ({'Task Planner Agent' if plan.get('source') == 'planner' else plan.get('source')}): "
                      f"{REPORT_TYPE_WORDS.get(plan.get('report_type'), '')}, focus "
                      f"{', '.join(plan.get('focus', [])[:2])}._"]
    drafts = facts.get("drafts") or []
    if drafts:
        lines += ["", "**Drafts and the Judge's checklist**", "| Draft for | Checks passed | Chosen |", "|---|---|---|"]
        lines += [f"| {ANGLE_WORDS.get(d['angle'], d['angle'])} | {d['score']} of {d['max_score']} | "
                  f"{'✅' if d['chosen'] else ''} |" for d in drafts]
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
    if on_server():                                   # a server keeps reports for a day, not for ever
        prune_runs(out_root, load_settings().web.keep_runs_hours)
    try:
        result = await runner(folder, (question or "").strip() or DEFAULT_QUESTION, out_root, offline,
                              intake=intake, on_step=on_step)
    except RunStopped as e:
        return Outcome(f"**{e}**")
    except Exception as e:                       # noqa: BLE001 - shown on the page, details in the server log
        traceback.print_exc()
        return Outcome(f"**Something went wrong outside the review steps** ({type(e).__name__}). Please try again; "
                       "the server log has the details.")
    log = result.run_dir / "log.json"
    executive = getattr(result, "executive_pdf", None)
    return Outcome(summary_markdown(result), _download(result, result.pdf), str(log) if log.exists() else None,
                   dashboard_data(result), _download(result, executive) if executive else None,
                   run_info(result.log.run) if getattr(result, "log", None) else "")


def run_info(run: dict) -> str:
    """ "Run 20261030-…-ab12cd34 · 5 AI calls (Extractor Agent 1, …) · trace trace_…" for the progress area """
    calls = run.get("ai_calls") or {}
    by_agent = ", ".join(f"{k} {v}" for k, v in (calls.get("by_agent") or {}).items())
    parts = [f"Run {run.get('run_id', '–')}", f"{calls.get('total', 0)} AI call(s)" + (f" ({by_agent})" if by_agent else "")]
    if run.get("trace_id"):
        parts.append(f"OpenAI trace {run['trace_id']}")
    return " · ".join(parts)


def _download(result: RunResult, pdf: Path | None) -> str | None:
    """ The PDF under its readable name ({Fund_Name}_{Executive|Detailed}_Report_{YYYY-MM-DD}.pdf) for the
    download button; the run folder keeps report.pdf and report_executive.pdf """
    if pdf is None:
        return None
    fund = (result.facts or {}).get("fund", {})
    try:
        return str(download_copy(pdf, fund["fund_name"], date.fromisoformat(str(fund["as_of_date"]))))
    except (KeyError, TypeError, ValueError, OSError):
        return str(pdf)


async def start_review(question: str, price, factsheet, kid, peer_factsheets, json_files, offline: bool,
                       limits: AiLimits, on_step: Progress | None = None, out_root: Path = RUNS,
                       runner=run_review, reader=read_documents) -> Outcome:
    """ "Run the review": JSON files run straight away; documents are read, checked by code, then run """
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
        if (missing := missing_json(json_files)):           # complete JSON replaces the factsheet; partial does not
            return Outcome(f"**The JSON inputs are incomplete:** missing {', '.join(missing)}. Add them, or remove "
                           "the JSON files and add the fund factsheet so the agents can read it.")
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
    # One OpenAI trace for the whole review: the reading agents here and every agent the controller runs
    review_id = f"review-{uuid.uuid4().hex[:12]}"
    with trace("Fund performance review", group_id=review_id, metadata={"review": review_id},
               disabled=not api_key_present()):
        folder = Path(tempfile.mkdtemp(prefix="fund-review-"))
        try:
            if on_step:
                on_step(progress_line(*DOCUMENTS_STAGE))
            calls: list[dict] = []
            token = AI_CALLS.set(calls)             # the reading agents' calls count towards this review
            try:
                intake = await reader(Path(factsheet), Path(kid) if kid else None, [Path(p) for p in peers])
            except Exception as e:                   # noqa: BLE001
                traceback.print_exc()
                return Outcome(f"**Step 1 of 5 failed: the documents could not be read** ({type(e).__name__}). Check "
                               "they are PDF or Word files.")
            finally:
                AI_CALLS.reset(token)
            if on_step:
                on_step(f"✓ Step 1 of 5 · {DOCUMENTS_STAGE[1]} · done ({len(calls)} AI call(s))")
            intake = intake | {"ai_calls": calls}
            # No person checks the values: code checks each one against the documents and flags what it cannot confirm
            built = self_check(intake)
            if built.problems:
                failed = [f["message"] for f in intake.get("flags", []) if f.get("level") == "blocking"]
                why = (" The Extractor Agent could not read the documents (" + "; ".join(failed)[:300] + ")."
                       if failed else "")
                return Outcome("**The review could not run: these values were not found in the documents.**" + why
                               + "\n" + "\n".join(f"- {x}" for x in built.problems)
                               + "\n\nUpload the fund's factsheet (and its KID for the objective), or use the JSON files "
                                 "under Advanced.")
            write_inputs(built, folder)
            prepare_inputs([price], folder)
            return await _run_controller(folder, question, False, on_step, out_root, runner,
                                         intake=intake | {"rows": built.rows,
                                                          "flags": intake.get("flags", []) + built.flags})
        finally:
            limits.finish()
            shutil.rmtree(folder, ignore_errors=True)


def progress_history(history: list[str], line: str) -> list[str]:
    """ The steps so far: a step's outcome (✓ done, ↷ skipped, ✗ failed) replaces its "▶ running" line """
    key = line.lstrip("▶✓↷✗• ").split(" · ")[:2]
    if history and history[-1].startswith("▶") and history[-1].lstrip("▶ ").split(" · ")[:2] == key:
        return history[:-1] + [line]
    return history + [line]


def progress_markdown(history: list[str], run_info: str = "") -> str:
    """ The progress area: every step so far, one per line, and the run ID, trace and AI calls when it ends """
    lines = [f"- {x}" for x in history]
    return "\n".join(lines + ([f"\n{run_info}"] if run_info else []))


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


# --- The real-fund demos (Stage 4B) ---------------------------------------------------------------------------------

QUICK, LIVE = "quick", "live"
DEMO_MODES = {QUICK: "Quick Demo · prevalidated inputs, no AI (seconds)",
              LIVE: "Live AI Demo · the agents read the documents (1–2 minutes; counts towards today's AI limit)"}
EVIDENCE_WORDS = {QUICK: ("Prevalidated inputs: figures typed from the documents and checked by code (the price "
                          "returns below match the factsheet). No AI is used, so every run gives the same result."),
                  LIVE: ("AI-extracted evidence: the Extractor and Mandate agents read the documents; code checks "
                         "every value, and figures read by AI are marked as such in the reports.")}
NO_DEMOS = ("The real-fund demos need their private data files, which are not on this server (they are kept out of "
            "the public repository). You can still download example input files (a made-up fund) under Help & "
            "methodology.")


def live_demo_allowed() -> bool:
    """ The Live AI Demo is offered only where AI runs are on: a key, a login on servers, not forced offline """
    return (bool(os.getenv("OPENAI_API_KEY")) and not ai_switched_off()
            and os.getenv(OFFLINE_ENV, "").strip().lower() not in ("1", "true", "yes"))


def demo_card(demo: Demo) -> str:
    return f"{demo.title}\n{demo.subtitle}"


def demo_inputs(demo: Demo, mode: str) -> dict:
    """ What goes into the upload boxes: the quick inputs (price + JSON) or the documents (price + PDFs) """
    if mode == LIVE:
        f = demo.live_files
        return {"price": str(f["price"]), "factsheet": str(f["factsheet"]), "kid": str(f["kid"]) if f["kid"] else None,
                "peer": [str(p) for p in f["peers"]] or None, "json": None}
    f = demo.quick_files
    return {"price": str(f["price"]), "factsheet": None, "kid": None, "peer": None, "json": [str(p) for p in f["json"]]}


def demo_info_html(demo: Demo, mode: str) -> str:
    """ The demo's card: fund, dates, evidence type, the return check, disclosures, sources and the notice """
    rows = "".join(
        f"<tr><td>{c.period.replace('y', ' year' + ('s' if c.period != '1y' else ''))}</td>"
        f"<td>{c.calculated:.2f}%</td><td>{c.published:.2f}%</td><td>{c.difference:+.2f} pp</td>"
        f"<td>{'✓ within' if c.ok else '✗ outside'} {c.tolerance_pp:.2f} pp</td></tr>"
        for c in return_checks(demo) if c.calculated is not None and c.published is not None)
    basis = next((c.basis for c in return_checks(demo) if c.period == "5y"), "")
    sources = "".join(f"<li><b>{escape(x['publisher'])}</b>, {escape(x['title'])} ({escape(str(x['date']))}): "
                      f"{escape(x['used'])}</li>" for x in demo.sources)
    notes = "".join(f"<li>{escape(x)}</li>" for x in demo.disclosures)
    ticker = f" · {escape(demo.ticker)}" if demo.ticker else ""
    return f"""<div class='fp-card fp-demo-info'>
<div class='fp-kicker'>{'Live AI Demo' if mode == LIVE else 'Quick Demo'} · {'made-up data' if demo.fallback else 'historical data'}</div>
<h3>{escape(demo.fund_name)}</h3>
<p>{escape(demo.share_class)} · ISIN {escape(demo.isin)}{ticker} · Benchmark: {escape(demo.benchmark)}<br/>
Peer: {escape(demo.peer)}<br/>Review date: {demo.review_date:%d %b %Y}</p>
<p class='fp-evidence-type'><b>{'AI-extracted evidence' if mode == LIVE else 'Prevalidated inputs'}.</b>
{escape(EVIDENCE_WORDS[mode].split(': ', 1)[1][:1].upper() + EVIDENCE_WORDS[mode].split(': ', 1)[1][1:])}</p>
<details><summary>Return check: fund price returns vs the factsheet ({escape(basis)})</summary>
<table class='fp-table'><tr><th>Period</th><th>From prices</th><th>Factsheet</th><th>Difference</th><th>Check</th></tr>
{rows}</table></details>
<details><summary>Disclosures</summary><ul>{notes}</ul></details>
<details><summary>Sources</summary><ul>{sources}</ul></details>
<p class='fp-help'>{escape(demo.notice)}</p></div>"""


def demo_banner(price, json_files, picked: str | None, mode: str) -> dict | None:
    """ What the results say about a demo run: which demo, and whether its evidence was prevalidated or read by AI """
    if (demo := matching_demo(price, json_files)):
        return {"label": "Quick Demo", "fund": demo.fund_name, "evidence": EVIDENCE_WORDS[QUICK], "notice": demo.notice}
    demo = find_demo(picked) if picked else None
    if demo and mode == LIVE and demo.available and _one(price) and \
            Path(_one(price)).read_bytes() == demo.live_files["price"].read_bytes():
        return {"label": "Live AI Demo", "fund": demo.fund_name, "evidence": EVIDENCE_WORDS[LIVE], "notice": demo.notice}
    return None


def demo_tag(price, json_files, picked: str | None, mode: str) -> str:
    """ The same as one Markdown line, for the plain-text summary """
    b = demo_banner(price, json_files, picked, mode)
    return f"**{b['label']}: {b['fund']}.** {b['evidence']}" if b else ""


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


NAVY_TEXT, BLUE, BLUE_DARK, BORDER, MUTED = NAVY, "#3d6098", "#2f4c7a", "#dde3ea", "#5b6878"
ICONS = {"overall": "◎", "performance": "↗", "fees_value": "£"}

CSS = f"""
.gradio-container {{ max-width: 1040px !important; margin: 0 auto !important; font-size: 15.5px;
  font-variant-numeric: tabular-nums; }}
.fp-header h1 {{ color: {NAVY_TEXT}; font-size: 27px; font-weight: 600; margin: 8px 0 2px 0; }}
.fp-header p {{ color: {MUTED}; font-size: 15px; margin: 0 0 6px 0; }}
.fp-section-title h2, .fp-section-title {{ color: {NAVY_TEXT}; font-size: 18px; font-weight: 600; margin: 14px 0 2px 0; }}
.fp-help, .fp-help p {{ color: {MUTED}; font-size: 13.5px; }}
.fp-notice {{ background: #f6f8fb; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 14px;
  font-size: 13.5px; color: #3c4857; }}
.fp-progress {{ font-weight: 500; color: {NAVY_TEXT}; }}
.fp-ok {{ color: #2e6b3a; font-size: 13.5px; }}
.fp-bad {{ color: #a33a2f; font-size: 13.5px; font-weight: 500; }}

/* What would you like to analyse: radio buttons drawn as cards (still radio inputs, so keyboard accessible) */
.fp-cards .wrap {{ display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
.fp-demo-cards .wrap {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.fp-demo-info {{ margin-top: 10px; }} .fp-demo-info h3 {{ margin: 2px 0 4px 0; }}
.fp-demo-info p {{ margin: 4px 0; font-size: 14px; }} .fp-demo-info summary {{ cursor: pointer; color: {NAVY_TEXT}; font-weight: 600; margin-top: 6px; }}
.fp-demo-banner {{ background: #eef3fa; border: 1px solid {BORDER}; border-left: 4px solid {BLUE}; border-radius: 8px;
  padding: 10px 14px; margin-bottom: 10px; font-size: 14px; }}
.fp-evidence-type {{ background: #f6f8fb; border-left: 3px solid {BLUE}; padding: 6px 10px; border-radius: 4px; }}
.fp-cards label {{ display: flex !important; align-items: flex-start; gap: 10px; padding: 14px 16px !important;
  border: 1px solid {BORDER} !important; border-radius: 12px !important; background: #fff !important;
  box-shadow: none !important; cursor: pointer; min-height: 72px; }}
.fp-cards label span {{ white-space: pre-line; font-size: 13.5px; color: {MUTED}; line-height: 1.45; }}
.fp-cards label span::first-line {{ font-size: 15.5px; font-weight: 600; color: {NAVY_TEXT}; }}
.fp-cards label.selected, .fp-cards label:has(input:checked) {{ border-color: {BLUE} !important;
  background: #eef3fa !important; box-shadow: 0 0 0 1px {BLUE} inset !important; }}
.fp-cards label:focus-within {{ outline: 2px solid {BLUE}; outline-offset: 2px; }}
.fp-cards input[type=radio] {{ margin-top: 3px; accent-color: {BLUE}; }}

/* Report audience: a two-option segmented control */
.fp-segmented .wrap {{ display: inline-flex !important; flex-wrap: nowrap !important; gap: 0 !important; border: 1px solid {BORDER};
  border-radius: 10px; overflow: hidden; background: #fff; }}
.fp-segmented label {{ border: none !important; border-radius: 0 !important; padding: 8px 18px !important;
  background: #fff !important; box-shadow: none !important; margin: 0 !important; font-weight: 500; }}
.fp-segmented label + label {{ border-left: 1px solid {BORDER} !important; }}
.fp-segmented label.selected, .fp-segmented label:has(input:checked) {{ background: #eef3fa !important;
  color: {BLUE_DARK} !important; }}
.fp-segmented label:focus-within {{ outline: 2px solid {BLUE}; outline-offset: -2px; }}
.fp-segmented input[type=radio] {{ accent-color: {BLUE}; }}

.fp-run button, button.fp-run {{ width: 100%; font-size: 16px !important; font-weight: 600 !important;
  padding: 12px !important; }}
/* Results dashboard (stage 2) */
.fp-dashboard {{ display: flex; flex-direction: column; gap: 14px; color: #1d2733; font-size: 15px; line-height: 1.5; }}
.fp-dashboard h2 {{ color: {NAVY_TEXT}; font-size: 22px; font-weight: 600; margin: 0; }}
.fp-dashboard h3 {{ color: {NAVY_TEXT}; font-size: 17px; font-weight: 600; margin: 0 0 8px 0; }}
.fp-dashboard h4 {{ color: {NAVY_TEXT}; font-size: 15px; font-weight: 600; margin: 14px 0 6px 0; }}
.fp-dashboard p {{ margin: 4px 0; }}
.fp-dashboard ul {{ margin: 4px 0 4px 18px; padding: 0; }}
.fp-dashboard li {{ margin: 3px 0; }}
.fp-view, .fp-muted {{ color: {MUTED}; font-size: 13.5px; }}
.fp-card, .fp-result-head, .fp-details {{ background: #fff; border: 1px solid {BORDER}; border-radius: 12px;
  padding: 16px 18px; }}
.fp-fund p {{ color: {MUTED}; font-size: 14px; }}
.fp-status-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }}
.fp-status {{ border: 1px solid {BORDER}; border-left: 5px solid; border-radius: 10px; padding: 10px 14px; }}
.fp-kicker {{ color: {MUTED}; font-size: 12.5px; font-weight: 500; text-transform: uppercase; letter-spacing: .03em; }}
.fp-status-main {{ font-size: 20px; font-weight: 600; margin: 2px 0; }}
.fp-status-sub {{ color: #3c4857; font-size: 13.5px; }}
.fp-conclusion {{ font-size: 15.5px; }}
.fp-concern-title, .fp-group {{ font-weight: 600; color: {NAVY_TEXT}; margin-top: 10px !important; }}
.fp-metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
.fp-metric {{ background: #fff; border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 16px; }}
.fp-metric-label {{ color: {MUTED}; font-size: 13.5px; font-weight: 500; }}
.fp-metric-value {{ color: {NAVY_TEXT}; font-size: 24px; font-weight: 600; margin: 4px 0; }}
.fp-metric-value.fp-na {{ color: {MUTED}; font-size: 18px; }}
.fp-metric-meta {{ color: #3c4857; font-size: 13.5px; }}
.fp-metric-source {{ color: {MUTED}; font-size: 12.5px; margin-top: 6px; }}
.fp-attention {{ border-left: 5px solid #b7791f; background: #fffaf0; }}
.fp-rating {{ display: grid; grid-template-columns: minmax(150px, 1.1fr) auto 3fr; gap: 12px; align-items: start;
  padding: 10px 0; border-top: 1px solid #eef1f5; }}
.fp-rating:first-of-type {{ border-top: none; }}
.fp-rating-name span {{ display: block; color: {MUTED}; font-size: 13px; }}
.fp-chip {{ display: inline-block; color: #fff; font-size: 13px; font-weight: 600; border-radius: 999px;
  padding: 3px 12px; white-space: nowrap; }}
.fp-sub {{ color: #3c4857; font-size: 13.5px; }}
.fp-details summary {{ cursor: pointer; color: {NAVY_TEXT}; font-weight: 600; font-size: 16px; }}
.fp-details summary:focus-visible {{ outline: 2px solid {BLUE}; outline-offset: 3px; }}
.fp-details-body {{ margin-top: 8px; }}
.fp-table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
.fp-table th {{ background: #f1f4f8; color: {NAVY_TEXT}; font-weight: 600; text-align: right; padding: 6px 8px; }}
.fp-table td {{ text-align: right; padding: 6px 8px; border-top: 1px solid #eef1f5; }}
.fp-table .l {{ text-align: left; }}
.fp-table .src {{ color: {MUTED}; font-size: 12.5px; }}
.fp-total td {{ font-weight: 600; background: #f8fafc; }}
.fp-scroll {{ overflow-x: auto; }}
.fp-scroll .fp-table {{ min-width: 600px; }}
.fp-dashboard table, .fp-dashboard th, .fp-dashboard td {{ border-left: none !important; border-right: none !important;
  border-bottom: none !important; }}
.fp-dashboard table {{ border-top: none !important; }}
.fp-tech, .fp-small {{ font-size: 13.5px; }}
.fp-download button, button.fp-download {{ max-width: 320px; }}
@media (max-width: 760px) {{
  .fp-cards .wrap {{ grid-template-columns: 1fr; }}
  .fp-header h1 {{ font-size: 24px; }}
  .fp-status-row, .fp-metrics {{ grid-template-columns: 1fr; }}
  .fp-rating {{ grid-template-columns: 1fr auto; }}
  .fp-rating-why {{ grid-column: 1 / -1; }}
}}
"""


def theme() -> gr.themes.Base:
    """ Light neutral background, navy text, a muted blue for actions and selections; Inter if the browser can load
    it, else the system's sans-serif font """
    return gr.themes.Default(
        primary_hue=gr.themes.colors.blue, neutral_hue=gr.themes.colors.slate, radius_size=gr.themes.sizes.radius_lg,
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto",
              "Helvetica Neue", "Arial", "sans-serif"],
    ).set(
        body_background_fill="#f7f8fa", body_text_color="#1d2733", block_border_color=BORDER, block_shadow="none",
        button_primary_background_fill=BLUE, button_primary_background_fill_hover=BLUE_DARK,
        button_primary_text_color="#ffffff", button_secondary_background_fill="#ffffff",
        button_secondary_border_color=BORDER, button_secondary_text_color=BLUE_DARK,
        checkbox_label_background_fill_selected="#eef3fa", input_border_color_focus=BLUE,
    )


DETAILED_LABEL = "Detailed Report (PDF)"
EXECUTIVE_LABEL = "Executive Report (PDF, 2 pages)"


def download_buttons(data: dict, audience: str) -> tuple[dict, dict]:
    """ (Detailed, Executive) button updates: Investment Analyst gets the Detailed Report as the primary download,
    Management the Executive Report. An Executive Report that could not fit is hidden (the run's warning says why) """
    analyst = audience != "management"
    executive = data.get("executive_pdf")
    return (gr.update(value=data.get("pdf"), variant="primary" if analyst or not executive else "secondary",
                      visible=bool(data.get("pdf"))),
            gr.update(value=executive, variant="secondary" if analyst else "primary", visible=bool(executive)))


def _card(value: str) -> str:
    title, subtitle, _ = REVIEW_TYPES[value]
    return f"{ICONS[value]}  {title}\n{subtitle}"


def build_ui(limits: AiLimits | None = None) -> gr.Blocks:
    limits = limits or AiLimits(load_settings().web)
    web_settings = load_settings().web
    cleanup = (web_settings.cache_cleanup_minutes * 60, int(web_settings.keep_runs_hours * 3600))
    with gr.Blocks(title="Fund Performance Review", delete_cache=cleanup) as ui:
        gr.HTML("<div class='fp-header'><h1>Fund Performance Review</h1>"
                "<p>Clear insights for better investment oversight.</p></div>")

        # A. What to analyse (fills in the review question; never changes a calculation)
        gr.HTML("<h2>What would you like to analyse?</h2>", elem_classes="fp-section-title")
        review_type = gr.Radio([(_card(v), v) for v in REVIEW_TYPES], value=DEFAULT_REVIEW, show_label=False,
                               container=False, elem_classes="fp-cards", label="What would you like to analyse?")
        gr.Markdown(REVIEW_HELP, elem_classes="fp-help")

        # B. Review question
        question = gr.Textbox(label="Review question", value=UI_QUESTION, lines=2,
                              info="Edit it if you like. The agents use it to decide what to focus on.")

        # C. Try a demo (real funds; the made-up fund stays in the tests and the example files)
        demos = shown_demos()
        gr.HTML("<h2>Try a demo</h2>", elem_classes="fp-section-title")
        demo_choice = gr.Radio([(demo_card(d), d.id) for d in demos], value=None, show_label=False, container=False,
                               elem_classes=["fp-cards", "fp-demo-cards"], label="Try a demo", visible=bool(demos))
        demo_mode = gr.Radio([(label, value) for value, label in DEMO_MODES.items()], value=QUICK,
                             label="How to run the demo", elem_classes="fp-segmented",
                             visible=bool(demos) and live_demo_allowed())
        demo_info = gr.HTML("" if demos else f"<p class='fp-help'>{escape(NO_DEMOS)}</p>")

        # D. Fund documents
        gr.HTML("<h2>Fund documents</h2>", elem_classes="fp-section-title")
        with gr.Row(equal_height=True):
            with gr.Column(min_width=280):
                price = gr.File(label="Fund price data · CSV or Excel · Required", file_types=PRICE_TYPES,
                                type="filepath", height=150)
                price_status = gr.HTML()
            with gr.Column(min_width=280):
                factsheet = gr.File(label=FACTSHEET_LABEL, file_types=DOC_TYPES,
                                    type="filepath", height=150)
                factsheet_status_line = gr.HTML()

        # D. Report audience (recorded only in this version)
        audience = gr.Radio([(label, value) for value, label in AUDIENCES.items()], value="analyst",
                            label="Report audience", info=AUDIENCE_HELP, elem_classes="fp-segmented")

        # E. Additional options
        with gr.Accordion("Additional options", open=False) as options:
            with gr.Row():
                with gr.Column(min_width=280):
                    kid = gr.File(label="KID or prospectus · PDF or Word · Optional", file_types=DOC_TYPES,
                                  type="filepath")
                    kid_status = gr.HTML()
                with gr.Column(min_width=280):
                    peer = gr.File(label="Peer fund factsheets · PDF or Word · Optional (approved peers are built in)",
                                   file_count="multiple", file_types=DOC_TYPES, type="filepath")
                    peer_status = gr.HTML()
            json_files = gr.File(label="Advanced: JSON inputs (fund_profile.json, factsheet_performance.json, "
                                       "peer.json) · skip the AI reading step", file_count="multiple",
                                 file_types=[".json"], type="filepath")

        # F. Actions, the privacy note and help
        run = gr.Button("Run Fund Review", variant="primary", elem_classes="fp-run")
        gr.HTML(f"<div class='fp-notice' role='note'>{PUBLIC_DATA_HTML}</div>")
        with gr.Accordion("Help & methodology", open=False):
            gr.Markdown(INSTRUCTIONS)
            gr.Markdown(FILES_TABLE)
            gr.DownloadButton("Download example input files (a made-up fund)", value=example_zip(), size="sm")
            gr.Markdown("### How the agent works")
            gr.HTML(how_it_works_html())

        # Results (stage 2): hidden until a review finishes
        progress = gr.Markdown(elem_classes="fp-progress")
        message = gr.Markdown()
        result_state = gr.State(None)
        with gr.Column(visible=False) as results:
            gr.HTML("<h2>Results</h2>", elem_classes="fp-section-title")
            with gr.Row():
                pdf = gr.DownloadButton(DETAILED_LABEL, variant="primary", elem_classes="fp-download")
                executive_pdf = gr.DownloadButton(EXECUTIVE_LABEL, variant="secondary", elem_classes="fp-download")
            dashboard = gr.HTML()
            with gr.Accordion("Technical details", open=False):
                technical = gr.HTML()
                log = gr.File(label="Run log (log.json)", interactive=False)
                gr.Markdown("**Plain-text summary** (the same results as text, for copying)")
                plain = gr.Markdown()

        def show(outcome: Outcome, audience_value: str):
            """ The page's outputs for a finished review, or for a message when it could not run """
            if outcome.data is None:
                return (outcome.message, gr.update(visible=False), "", gr.update(value=None), gr.update(value=None),
                        "", None, "", None)
            data = outcome.data | {"pdf": outcome.pdf, "executive_pdf": outcome.executive}
            detailed, executive = download_buttons(data, audience_value)
            return ("", gr.update(visible=True), dashboard_html(data, audience_value), detailed, executive,
                    technical_html(data), outcome.log, outcome.message, data)

        async def on_run(q, p, f, k, pr, j, audience_value, picked, mode):
            hidden = gr.update(visible=False)
            yield "Starting…", "", hidden, "", gr.update(value=None), gr.update(value=None), "", None, "", None
            offline = run_offline(p, j)
            banner = demo_banner(p, j, picked, mode)
            tag = demo_tag(p, j, picked, mode)
            history: list[str] = []
            async for kind, item in with_progress(lambda say: start_review(q, p, f, k, pr, j, offline, limits, say)):
                if kind == "progress":
                    history = progress_history(history, item)
                    yield (progress_markdown(history),) + (gr.update(),) * 9
                else:
                    if tag:
                        item.message = f"{tag}\n\n{item.message}"
                    if banner and item.data is not None:
                        item.data = item.data | {"demo": banner}
                    shown = show(item, audience_value)
                    done = progress_markdown(history, item.run_info) if history else ""
                    yield (done,) + shown

        def on_audience(data, audience_value):
            """ A new view and a new primary download from the saved results: the review is not run again """
            if not data:
                return gr.update(), gr.update(), gr.update()
            return (dashboard_html(data, audience_value),) + download_buttons(data, audience_value)

        def on_demo(demo_id, mode):
            """ Fill the upload boxes with the demo's inputs for this mode, and show its card """
            demo = find_demo(demo_id) if demo_id else None
            if demo is None or not demo.available:
                return (gr.update(),) * 6 + ("",)
            mode = mode if mode == LIVE and live_demo_allowed() else QUICK
            d = demo_inputs(demo, mode)
            return (d["price"], d["factsheet"], d["kid"], d["peer"], d["json"], gr.update(open=bool(d["json"] or d["kid"])),
                    demo_info_html(demo, mode))

        private = {"api_visibility": "private"}         # the page is the only way in, with its limits
        review_type.change(question_for, inputs=[review_type, question], outputs=question, **private)
        for box, status_box, allowed, kinds in ((price, price_status, PRICE_TYPES, "CSV or Excel"),
                                                (kid, kid_status, DOC_TYPES, "PDF or Word"),
                                                (peer, peer_status, DOC_TYPES, "PDF or Word")):
            box.change(lambda v, a=allowed, k=kinds: file_status(v, a, k), inputs=box, outputs=status_box, **private)
        for box in (factsheet, json_files):         # the factsheet's line depends on the JSON inputs too
            box.change(factsheet_status, inputs=[factsheet, json_files], outputs=factsheet_status_line, **private)
        for trigger in (demo_choice.change, demo_mode.change):
            trigger(on_demo, inputs=[demo_choice, demo_mode],
                    outputs=[price, factsheet, kid, peer, json_files, options, demo_info], **private)
        run.click(on_run, inputs=[question, price, factsheet, kid, peer, json_files, audience, demo_choice, demo_mode],
                  outputs=[progress, message, results, dashboard, pdf, executive_pdf, technical, log, plain,
                           result_state], **private)
        audience.change(on_audience, inputs=[result_state, audience], outputs=[dashboard, pdf, executive_pdf],
                        **private)
    return ui


def launch(ui: gr.Blocks | None = None) -> None:
    """ Hosts such as Render set PORT and need the app to listen on all interfaces. With APP_USERNAME and
    APP_PASSWORD set, the page asks for them before it opens """
    ui = ui or build_ui()
    on_host = on_server()
    ui.queue(default_concurrency_limit=int(os.getenv("MAX_CONCURRENT_RUNS", "2")))
    ui.launch(css=CSS, theme=theme(), server_name="0.0.0.0" if on_host else None,
              server_port=int(os.environ["PORT"]) if on_host else None, auth=login(),
              auth_message="Fund performance review: please log in.", max_file_size="20mb")
