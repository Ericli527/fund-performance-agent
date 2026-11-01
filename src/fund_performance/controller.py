""" Workflow controller (spec Section 8.5): a plain Python function, not an AI agent, that runs one review

read files -> extractor (only if there is no factsheet_performance.json) -> approved peers (only if there is no
peer.json: the Extractor reads their factsheets) -> task plan (Task Planner Agent: focus, angles and up to
limits.max_web_searches web searches; default plan offline) -> data checks -> mandate -> web research (Search Agent:
approved pages and the planned searches, started as a background task) alongside the calculator and scorecard ->
code vets the research -> Reporting Agent (summary and cited market context) -> code's checks and the Judge Agent
-> report -> email (off by default). The financial review never depends on the research.

The extractor runs before the data checks because the repeated-price check compares with the factsheet.

- The run stops with a clear message (RunStopped) when it cannot be scored at all: no folder, no or an invalid
  fund profile, no or an unreadable price file. A blocking data check does not stop the run: the affected
  rating is CHECK DATA and the verdict waits for a data check (spec 5.1 and 6.5), so the report says what to fix.
- Limits from config: at most limits.max_web_searches web searches (thresholds.yaml); a timeout for each AI step
  (settings.yaml). A step that times out is handled like a
  failed step and flagged.
- Each step is logged (start, end, inputs used, outputs) to runs/<timestamp>/log.json; the report's sources
  list is built from this log.
"""
import asyncio
from dataclasses import asdict, dataclass, field
from typing import Callable
from datetime import datetime
import json
import re
from pathlib import Path
import time
import traceback
from contextlib import nullcontext
from contextvars import ContextVar
import uuid
from fund_performance.agents.analyst import Narrative, assemble, numbered_sources, template
from agents import get_current_trace, trace
from fund_performance.agents.base import AI_CALLS, RunFn, api_key_present
from fund_performance.agents.extractor import extract
from fund_performance.agents.judge import draft_and_judge, REVISED
from fund_performance.agents.task_planner import TaskPlan, plan_tasks
from fund_performance.agents.mandate import read_mandate
from fund_performance.agents.research import PlannedSearch, market_name, research, vet_summaries, with_timing
from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import RunSettings, Thresholds, load_settings, load_sources, load_thresholds
from fund_performance.emailer import PostFn, send_report
from fund_performance.evidence import build_evidence
from fund_performance.facts import build_facts
from fund_performance.fetch import GetFn, fetch_pages, http_get
from fund_performance.config import load_peers
from fund_performance.intake import peer_record, read_peer
from fund_performance.io import detect_file_type, read_document, read_json, read_peers, read_prices
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, FactsheetPerformance, FundProfile, Peer
from fund_performance.peers import approved_peers, compare_peers
from fund_performance.presentation import report_filename
from fund_performance.precedence import apply_precedence
from fund_performance.executive import build_executive_reliably
from fund_performance.report import ReportInputs, ReportLayoutError, build_report, plain_reason
from fund_performance.scorecard import score

DEFAULT_QUESTION = "Is this index fund meeting its mandate, and is its fee justified?"
OFFLINE_NOTE = "Offline run: AI steps skipped (no Mandate Agent, approved sources, web research or Analyst)"
NOT_READ = "(document; not read, as structured files were supplied)"


class RunStopped(RuntimeError):
    """ The run cannot be scored; the message says what is missing """


@dataclass
class Runners:
    """ Stand-ins for the model calls, page fetching and email, for tests. None = the real thing """
    extractor: RunFn | None = None
    mandate: RunFn | None = None
    planner: RunFn | None = None
    search: RunFn | None = None
    page: RunFn | None = None
    analyst: RunFn | None = None
    evaluator: RunFn | None = None
    task_planner: RunFn | None = None
    reporter: RunFn | None = None
    judge: RunFn | None = None
    http_get: GetFn = http_get
    email_post: PostFn | None = None


ProgressFn = Callable[[str], None]
# Live progress: each workflow step is shown as "Step X of 5 · who · what" when it actually starts, and again with
# its outcome when it ends (done, skipped, failed). The five stages: 1 documents (Extractor), 2 planning and mandate
# (Task Planner, Mandate, data checks), 3 analysis and research (code, Research Agents), 4 reporting and evaluation
# (Reporting Agent, Judge; Analyst and Evaluator when there are web sources), 5 the reports
STAGES = {
    "read_files": (1, "Code: input files", "Reading the price file and the inputs"),
    "self_check": (1, "Code: self-check", "Checking every value the agents read against the documents"),
    "plan": (2, "Task Planner Agent", "Choosing what the review should focus on"),
    "extractor": (1, "Extractor Agent", "Reading the factsheet and KID"),
    "peers": (1, "Extractor Agent (approved peers)", "Reading the approved peers' factsheets"),
    "data_checks": (2, "Code: data checks", "Checking the prices and the factsheet figures"),
    "mandate": (2, "Mandate Agent", "Reading the fund's objective and promises"),
    "calculator": (3, "Code: calculator", "Calculating returns, risk and gaps to the index"),
    "scorecard": (3, "Code: scorecard", "Rating mandate, performance, value for investors and fees"),
    "research": (3, "Search Agent", "Reading approved sources and running the planned web searches, alongside the calculations"),
    "narrative": (4, "Oversight Analyst and Evaluator", "Writing and checking the market context"),
    "drafts": (4, "Reporting Agent and Judge", "Drafting the summary and checking it"),
    "report": (5, "Code: reports", "Building the Executive and Detailed PDF reports"),
}
TOTAL_STAGES = 5
OUTCOME_ICON = {"ok": "✓", "skipped": "↷", "fallback": "↷", "unavailable": "↷", "failed": "✗", "timeout": "✗",
                "stopped": "✗"}
DOCUMENTS_STAGE = (1, "Extractor Agent and Mandate Agent", "Reading the factsheet, KID and peer factsheets")


def progress_line(stage: int, who: str, what: str) -> str:
    """ "▶ Step 2 of 5 · Code: data checks · Checking the prices and the factsheet figures…" """
    return f"▶ Step {stage} of {TOTAL_STAGES} · {who} · {what}…"


@dataclass
class StepRecord:
    step: str
    started: str
    ended: str | None = None
    seconds: float | None = None
    status: str = "running"                  # ok, skipped, failed, timeout, stopped
    inputs: list[str] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class RunLog:
    """ What each step did, for log.json and the report's sources list """

    def __init__(self, folder: Path, question: str, offline: bool, on_step: ProgressFn | None = None):
        self.run = {"folder": str(folder), "question": question, "offline": offline,
                    "started": _now(), "ended": None, "status": "running", "message": None}
        self.steps: list[StepRecord] = []
        self._clock: dict[str, float] = {}
        self.background: list[asyncio.Task] = []   # steps running alongside others (web research)
        self.on_step = on_step                   # gets a short progress message as each step starts

    def announce(self, step: str) -> None:
        """ Tell the page which step is running now (only steps that really run are announced) """
        if self.on_step and step in STAGES:
            self.on_step(progress_line(*STAGES[step]))

    def start(self, step: str, inputs: list[str] | None = None, announce: bool = True) -> StepRecord:
        if announce:
            self.announce(step)
        record = StepRecord(step, _now(), inputs=list(inputs or []))
        self._clock[step] = time.monotonic()
        self.steps.append(record)
        return record

    def end(self, record: StepRecord, status: str = "ok", outputs: dict | None = None,
            notes: list[str] | None = None, quiet: bool = False) -> None:
        """ quiet: the step was already shown on the page (the agents that read the documents in Step 1) """
        record.ended, record.status = _now(), status
        record.seconds = round(time.monotonic() - self._clock.get(record.step, time.monotonic()), 2)
        record.outputs |= outputs or {}
        record.notes += notes or []
        if self.on_step and record.step in STAGES and not quiet:
            stage, who, _ = STAGES[record.step]
            word = {"ok": f"done ({record.seconds:.1f} s)", "skipped": "skipped",
                    "fallback": f"fallback after {record.seconds:.1f} s"}.get(status, status)
            if status == "ok" and record.step == "research" and record.notes:
                word += f": {record.notes[0]}"
            why = f": {record.notes[0]}" if status not in ("ok", "fallback") and record.notes else (
                f": code's conclusion is used (labelled as such); {record.notes[0]}" if status == "fallback"
                and record.notes else "")
            self.on_step(f"{OUTCOME_ICON.get(status, '•')} Step {stage} of {TOTAL_STAGES} · {who} · {word}{why}")

    def finish(self, status: str, message: str | None = None) -> None:
        self.run |= {"ended": _now(), "status": status, "message": message}

    def step(self, name: str) -> StepRecord | None:
        return next((s for s in self.steps if s.step == name), None)

    def report_sources(self) -> tuple[list[str], list[dict]]:
        """ The input files the read step used, and the numbered web sources the market context may cite """
        read, drafts = self.step("read_files"), self.step("drafts")
        files = read.outputs.get("input_files", []) if read else []
        return files, drafts.outputs.get("sources", []) if drafts else []

    def to_json(self) -> dict:
        files, web = self.report_sources()
        return {"run": self.run, "steps": [asdict(s) for s in self.steps],
                "sources": {"input_files": files, "web": web}}


@dataclass
class RunResult:
    pdf: Path | None                           # the Detailed Report, report.pdf (kept for compatibility)
    run_dir: Path
    log: RunLog
    narrative: Narrative | None = None
    facts: dict | None = None
    reasons: dict[str, str] = field(default_factory=dict)    # one-line plain reason per rating, as on report page 1
    flags: list[DataFlag] = field(default_factory=list)       # every flag of the run, as in the report's appendix
    executive_pdf: Path | None = None          # report_executive.pdf (2 pages), or None if it could not fit


def new_run_dir(root: Path) -> Path:
    """ A new folder for one review: the time (readable, sortable) plus a random id, created exclusively, so two
    reviews that start in the same second never share a folder or a report """
    root.mkdir(parents=True, exist_ok=True)
    while True:
        path = root / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue


def _count(calls: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in calls:
        out[c["agent"]] = out.get(c["agent"], 0) + 1
    return out


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def find_inputs(folder: Path) -> dict:
    """ The input files in a folder, by type (answer keys are never read) """
    found: dict = {"documents": []}
    for path in sorted(folder.iterdir()):
        if path.is_dir() or "answer_key" in path.parts or "answer_key" in path.name.lower():
            continue
        kind = detect_file_type(path)
        if kind == "document":
            found["documents"].append(path)
        elif kind != "unknown":
            found.setdefault(kind, path)
    return found


_FAILURE: ContextVar[str | None] = ContextVar("_FAILURE", default=None)


async def _timed(coro, seconds: float):
    """ Run one optional AI step with its timeout; None if it ran over or failed unexpectedly. An optional step
    never destroys the review: the caller uses its fallback, and _why() says what happened (the traceback goes to
    the server log) """
    _FAILURE.set(None)
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        _FAILURE.set(f"did not finish within {seconds:g} seconds")
        return None
    except Exception as e:                       # noqa: BLE001 - any unexpected error in an optional AI step
        traceback.print_exc()
        _FAILURE.set(f"failed ({type(e).__name__}: {_short(str(e))})")
        return None


def _why(seconds: float) -> str:
    """ "did not finish within 60 seconds" or "failed (ValueError: ...)" for the last _timed step """
    return _FAILURE.get() or f"did not finish within {seconds:g} seconds"


def _status() -> str:
    return "failed" if (_FAILURE.get() or "").startswith("failed") else "timeout"


def _short(text: str, limit: int = 240) -> str:
    """ An error message for the page and log.json: one line, no file paths, no key-like strings, short. A long one
    keeps its start and its end, where libraries usually put the reason """
    text = re.sub(r"(/[\w.\-]+)+", "<path>", " ".join(text.split()))
    text = re.sub(r"\b(sk|re)[-_][A-Za-z0-9_\-]{8,}", "<redacted>", text)
    return text if len(text) <= limit else text[:limit // 2] + " … " + text[-(limit // 2):]


async def run_review(folder: Path, question: str = DEFAULT_QUESTION, out_root: Path | None = None,
                     offline: bool = False, thresholds: Thresholds | None = None,
                     settings: RunSettings | None = None, runners: Runners | None = None,
                     intake: dict | None = None, on_step: ProgressFn | None = None) -> RunResult:
    """ One review. `intake` is the documents route (intake.read_documents + code's self-check of the values):
    the Extractor and Mandate agents have already run, so they are not run again. `on_step` gets a short message
    as each step starts, for the page's progress line """
    t = thresholds or load_thresholds()
    s = settings or load_settings()
    r = runners or Runners()
    folder = Path(folder)
    run_dir = new_run_dir(Path(out_root or Path(__file__).resolve().parents[2] / "runs"))
    log = RunLog(folder, question, offline, on_step)
    log.run["run_id"] = run_dir.name
    text_log: list[str] = []
    calls: list[dict] = list((intake or {}).get("ai_calls", []))       # the page's reading step, if any
    token = AI_CALLS.set(calls)
    current = get_current_trace()
    review_trace = nullcontext(current) if current else trace(
        "Fund performance review", group_id=run_dir.name, metadata={"run_id": run_dir.name},
        disabled=offline or not api_key_present())
    try:
        with review_trace as tr:
            trace_id = getattr(tr, "trace_id", None)
            log.run["trace_id"] = trace_id if trace_id and trace_id != "no-op" else None
            result = await _run(folder, question, run_dir, offline, t, s, r, log, text_log, intake)
        log.finish("ok")
        return result
    except RunStopped as e:
        log.finish("stopped", str(e))
        raise
    except Exception as e:                       # noqa: BLE001 - a critical step failed: stop, naming the stage
        traceback.print_exc()
        running = next((x for x in reversed(log.steps) if x.status == "running"), None)
        where = (f"Step {STAGES[running.step][0]} of {TOTAL_STAGES} ({STAGES[running.step][1]})"
                 if running and running.step in STAGES else f"step '{running.step}'" if running else "the start")
        if running:
            log.end(running, "failed", notes=[f"{type(e).__name__}: {_short(str(e))}"])
        message = (f"Run stopped at {where}: {type(e).__name__}: {_short(str(e))}. Calculations and reports were not "
                   f"completed; run ID {run_dir.name} (details in its log.json and the server log)")
        log.finish("stopped", message)
        raise RunStopped(message) from e
    finally:
        for task in log.background:              # a run that stopped early does not leave research running
            task.cancel()
        log.run["ai_calls"] = {"total": len(calls), "by_agent": _count(calls), "calls": calls}
        AI_CALLS.reset(token)
        (run_dir / "log.json").write_text(json.dumps(log.to_json(), indent=1, ensure_ascii=False), encoding="utf-8")
        if text_log:
            (run_dir / "run_log.txt").write_text("\n".join(text_log), encoding="utf-8")


async def _read_approved(paths: list[Path], r: Runners, s: RunSettings,
                         flags: list[DataFlag]) -> tuple[list[Peer], list[str]]:
    """ Read the approved peers' factsheets with the Extractor Agent (in parallel); a peer that cannot be read or
    does not validate is left out with a warning """
    async def one(path: Path):
        return await _timed(read_peer(path, r.extractor), s.timeouts_seconds.extractor)
    results = await asyncio.gather(*(one(p) for p in paths))
    peers, notes = [], []
    for path, result in zip(paths, results):
        if result is None:
            flags.append(DataFlag(check="peers", level="warning", message=(
                f"Approved peer factsheet {path.name}: the Extractor Agent did not finish in time or failed, so it is left "
                "out")))
            continue
        values, extracted, _ = result
        flags += [DataFlag(check="peers", level="warning" if f.level == "blocking" else f.level,
                           message=f"Approved peer factsheet {path.name}: {f.message}") for f in extracted.flags]
        try:
            peers.append(Peer.model_validate(peer_record(values, "approved")))
            notes.append(f"read {path.name}")
        except ValueError as e:
            flags.append(DataFlag(check="peers", level="warning", message=(
                f"Approved peer factsheet {path.name}: the values read do not fit a peer ({str(e)[:150]}), so it is "
                "left out")))
    return peers, notes


def _sector_ocf(profile: FundProfile) -> dict | None:
    group = load_peers().for_benchmark(profile.benchmark_name)
    return group.sector_average_ocf.model_dump() if group and group.sector_average_ocf else None


def _stop(log: RunLog, record: StepRecord, message: str):
    log.end(record, "stopped", notes=[message])
    raise RunStopped(message)


def pages_read(found) -> list[dict]:
    return [x for x in found.summaries if x.get("approved")]


async def _run(folder: Path, question: str, run_dir: Path, offline: bool, t: Thresholds, s: RunSettings,
               r: Runners, log: RunLog, text_log: list[str], intake: dict | None = None) -> RunResult:
    flags: list[DataFlag] = [DataFlag(**f) for f in (intake or {}).get("flags", [])]

    # 0. The documents route: what the agents read and what the person confirmed, before the run
    if intake:
        step = log.start("self_check", intake.get("documents", []))
        changed = [r["label"] for r in intake.get("rows", []) if r.get("status") == "Entered by user"]
        text_log += intake.get("log", []) + [f"Entered by user on the page: {', '.join(changed) or 'nothing'}"]
        log.end(step, outputs={"values": intake.get("rows", []), "entered_by_user": changed},
                notes=["values read by the Extractor Agent; code found each in the documents or flagged it"])

    # 1. Read files
    step = log.start("read_files", [str(folder)])
    if not folder.is_dir():
        _stop(log, step, f"Run stopped: the folder {folder} does not exist")
    files = find_inputs(folder)
    if "fund_profile" not in files:
        _stop(log, step, f"Run stopped: no fund_profile.json in {folder}. The fund profile is required to score the fund")
    if "prices" not in files:
        _stop(log, step, f"Run stopped: no price file (CSV or XLSX) in {folder}")
    try:
        profile: FundProfile = read_json(files["fund_profile"])
        factsheet: FactsheetPerformance | None = (read_json(files["factsheet_performance"])
                                                  if "factsheet_performance" in files else None)
        peers: list[Peer] = read_peers(files["peer"]) if "peer" in files else []
    except ValueError as e:
        _stop(log, step, f"Run stopped: an input file does not match its schema ({str(e)[:300]})")
    structured = [p.name for k, p in files.items() if k != "documents"]
    documents_read = factsheet is None and bool(files["documents"]) and not offline
    input_files = structured + [p.name if documents_read else f"{p.name} {NOT_READ}" for p in files["documents"]]
    if intake:
        input_files = [f for f in structured if not f.endswith(".json")] + [
            f"{name} (read by the Extractor Agent; values checked by code)" for name in intake.get("documents", [])]
    log.end(step, outputs={"input_files": input_files})

    # 2. Extractor (only when no factsheet_performance.json was supplied)
    step = log.start("extractor", [p.name for p in files["documents"]],
                     announce=not intake and factsheet is None and not offline and bool(files["documents"]))
    if intake:
        log.end(step, "skipped", notes=["documents read before the run; values checked by code"], quiet=True)
    elif factsheet is not None:
        log.end(step, "skipped", notes=["factsheet_performance.json supplied"])
    elif offline or not files["documents"]:
        why = "offline run" if offline else "no factsheet or KID document"
        flags.append(DataFlag(check="extractor_agent", level="warning",
                              message=f"No factsheet figures: no factsheet_performance.json, and the Extractor Agent was "
                                      f"not run ({why}). Calculated figures only"))
        log.end(step, "skipped", notes=[why])
    else:
        text = "\n\n".join(read_document(p) for p in files["documents"])
        extracted = await _timed(extract(text, r.extractor), s.timeouts_seconds.extractor)
        if extracted is None:
            flags.append(DataFlag(check="extractor_agent", level="warning", message=(
                f"No factsheet figures: the Extractor Agent {_why(s.timeouts_seconds.extractor)}. Calculated figures "
                "only")))
            log.end(step, _status(), notes=[_why(s.timeouts_seconds.extractor)])
        else:
            factsheet = extracted.factsheet
            flags += extracted.flags
            log.end(step, "ok" if factsheet else "failed", {"figures": "ai_extracted" if factsheet else None})

    # 2b. Approved peers (config/peers.yaml), when no peer was given: the Extractor reads their factsheets
    step = log.start("peers", ["peer.json"] if peers else ["config/peers.yaml"], announce=False)
    if peers:
        log.end(step, "skipped", outputs={"peers": [p.name for p in peers]}, notes=["peer.json supplied"])
    else:
        approved = approved_peers(load_peers(), profile.benchmark_name, profile.isin)
        flags += approved.flags
        if not approved.files:
            log.end(step, "skipped", notes=["no approved peer for this benchmark" if approved.group is None
                                            else "no approved peer factsheet found in data/peers/"])
        elif offline:
            flags.append(DataFlag(check="peers", level="info", message=(
                "Approved peers not read: offline run (the Extractor Agent reads their factsheets)")))
            log.end(step, "skipped", notes=["offline run"])
        else:
            log.announce("peers")
            peers, notes = await _read_approved([path for _, path in approved.files], r, s, flags)
            step.inputs = [f"data/peers/{path.name}" for _, path in approved.files]
            log.end(step, outputs={"peers": [p.name for p in peers]}, notes=notes)
            input_files += [f"{path.name} (approved peer, read by the Extractor Agent)" for _, path in approved.files
                            if any(n.endswith(path.name) for n in notes)]
            log.step("read_files").outputs["input_files"] = input_files

    # 2a. Task plan (Step 2 of 5): the Task Planner Agent turns the request into tasks (menu choices only, checked by code)
    step = log.start("plan", ["question", "fund_profile.json: public details"], announce=not offline)
    if offline:
        plan = TaskPlan(reason="Default plan: offline run", source="default (offline)")
        log.end(step, "skipped", outputs=plan.to_dict(), notes=["offline run: default plan"])
    else:
        budget = t.limits.max_web_searches if s.research.enabled else 0
        planned = await _timed(plan_tasks(question, profile, r.task_planner, budget), s.timeouts_seconds.task_planner)
        if planned is None:
            plan = TaskPlan(reason="Default plan: the Task Planner did not answer in time")
            flags.append(DataFlag(check="task_planner", level="info", message=(
                f"The Task Planner Agent {_why(s.timeouts_seconds.task_planner)}; default plan used")))
            log.end(step, _status(), outputs=plan.to_dict(), notes=[_why(s.timeouts_seconds.task_planner)])
        else:
            plan, plan_flags = planned
            flags += plan_flags
            log.end(step, "ok" if plan.source == "planner" else "failed", outputs=plan.to_dict())
    text_log.append(f"Plan ({plan.source}): {plan.report_type}; focus {', '.join(plan.focus)}; " + " -> ".join(plan.tasks))

    # 3. Data checks
    step = log.start("data_checks", [files["prices"].name] + (["factsheet figures"] if factsheet else []))
    try:
        data = read_prices(files["prices"])
        benchmark_inputs = (intake or {}).get("benchmark_inputs") or {}
        if benchmark_inputs.get("series"):
            from fund_performance.benchmark import align_benchmark, confirm_identity, read_benchmark
            confirm_identity(benchmark_inputs.get("name"), benchmark_inputs.get("currency"),
                             benchmark_inputs.get("confirmed"), profile, benchmark_inputs.get("pricing_point"))
            benchmark_path = Path(benchmark_inputs["series"])
            data.prices = align_benchmark(data.prices, read_benchmark(benchmark_path))
            data.log.append(f"Separate benchmark series: {benchmark_path.name}; exact date matches only; "
                            f"name, currency and pricing time confirmed by the analyst")
            log.step("read_files").outputs["input_files"].append(f"{benchmark_path.name} (benchmark series; analyst confirmed)")
    except (ValueError, KeyError, OSError) as e:
        _stop(log, step, f"Run stopped: the price file {files['prices'].name} cannot be read ({str(e)[:300]})")
    text_log += data.log
    checked = check_prices(data, profile, t, factsheet,
                           index_currency=benchmark_inputs.get("currency") if benchmark_inputs.get("series") else None)
    if len(checked.prices) < 2:
        _stop(log, step, f"Run stopped: fewer than 2 usable prices in {files['prices'].name}")
    log.end(step, outputs={"prices": len(checked.prices), "flags": len(checked.flags),
                           "blocking": [f.message for f in checked.blocking]})

    # 4. Mandate Agent
    step = log.start("mandate", ["fund_profile.json: objective text"], announce=not offline and not intake)
    promises: list[str] = []
    if offline:
        flags.append(DataFlag(check="run", level="info", message=OFFLINE_NOTE))
        log.end(step, "skipped", notes=["offline run"])
    elif intake:
        promises = list(intake.get("promises", []))
        log.end(step, outputs={"promises": len(promises)},
                notes=["Mandate Agent read the objective before the run"], quiet=True)
    else:
        mandate = await _timed(read_mandate(profile, r.mandate), s.timeouts_seconds.mandate)
        if mandate is None:
            flags.append(DataFlag(check="mandate_agent", level="blocking", message=(
                f"CHECK DATA: Mandate Agent {_why(s.timeouts_seconds.mandate)}")))
            log.end(step, _status(), notes=[_why(s.timeouts_seconds.mandate)])
        else:
            profile, promises = mandate.profile, mandate.promises
            flags += mandate.flags
            log.end(step, outputs={"promises": len(promises), "flags": [f.message for f in mandate.flags]})

    # 5. Web research (Search Agent) starts now and runs alongside the calculations: it needs only the public fund
    # details and the plan, never a figure. The calculations never wait for it or depend on it
    research_step = log.start("research", announce=not offline and plan.market_context and s.research.enabled)
    research_task = None
    if offline:
        log.end(research_step, "skipped", notes=["offline run"])
    elif not s.research.enabled:
        log.end(research_step, "skipped", notes=["web research is off (config/settings.yaml research.enabled)"])
    elif not plan.market_context:
        log.end(research_step, "skipped", notes=["the plan needs no market context"])
    else:
        sources_config = load_sources()
        approved_pages = sources_config.for_fund(profile.isin, market_name(profile))
        planned_searches = [PlannedSearch(**x) for x in plan.searches]
        research_step.inputs = ([f"approved: {a.url}" for a in approved_pages]
                                + [f"planned web search: {p.query}" for p in planned_searches])

        async def do_research():
            pages = await fetch_pages(approved_pages, sources_config.fetch, r.http_get)
            found = await research(profile, planned_searches, t.limits.max_web_searches, pages, r.search, r.page)
            return found, _FAILURE.get()

        async def timed_research():
            done = await _timed(do_research(), s.timeouts_seconds.research)
            return done if done is not None else (None, _FAILURE.get())
        research_task = asyncio.create_task(timed_research())
        await asyncio.sleep(0)                     # let the research start before the calculations

        log.background.append(research_task)    # cancelled by run_review if the run stops before it is awaited

    # 6. Calculator (with factsheet precedence), in a worker thread so the research can make progress meanwhile
    step = log.start("calculator", [files["prices"].name] + (["factsheet figures"] if factsheet else []))
    calculated = await asyncio.to_thread(calculate, checked.prices, profile, t, factsheet)
    reported = apply_precedence(calculated, checked.flags, profile, t, factsheet, checked.comparison)
    from fund_performance.checks import repeated_price_scope
    reported.flags = [repeated_price_scope(f, checked.prices) for f in reported.flags]
    text_log += reported.log
    flags = list(reported.flags) + flags
    log.end(step, outputs={"figures": len(reported.figures)})

    # 6. Decision tree and scorecard
    step = log.start("scorecard", ["config/thresholds.yaml"] + (["peers"] if peers else []))
    peer_comparison = compare_peers(peers, profile, reported)
    flags += peer_comparison.flags
    path = decision_path(profile, checked.short_history, flags)
    comparison = checked.comparison
    card = score(reported, profile, t, path, peers, comparison.fund_series if comparison else "fund_nav",
                 comparison.extra_tolerance_pp if comparison else 0.0)
    evidence = build_evidence(reported, profile, t, s.statistics, peer_comparison)
    facts = build_facts(profile, reported, card, flags, promises, peer_comparison, evidence)
    facts["plan"] = plan.to_dict()
    if not plan.manager_questions:
        facts["manager_questions"] = []
    text_log += [f"Suggested conclusion: {x}" for x in facts["suggested_conclusion"]["left_out"]]
    log.end(step, outputs={"ratings": {p.name: p.rating for p in card.pillars.values()}, "verdict": card.verdict})

    # 7. Web research results: wait for the Search Agent, then code vets each summary against the facts
    vetted: list[dict] = []
    if research_task is not None:
        found, failure = await research_task
        if found is None:
            flags.append(DataFlag(check="research", level="info", message=(
                f"Web research {failure or 'did not finish'}, so the report has no market context (the financial "
                "review is complete without it)")))
            log.end(research_step, "unavailable", notes=[failure or "did not finish"])
        else:
            vetted, vet_flags, vet_log = vet_summaries(found.summaries, profile, facts,
                                                       market_grace_days=sources_config.vetting.market_grace_days)
            vetted = with_timing(vetted, profile)
            flags += found.flags + vet_flags
            text_log += found.log + vet_log
            research_step.inputs += [f"web search: {p.query}" for p in found.plan]
            outputs = {"summaries": len(found.summaries), "kept": len(vetted), "web_searches": len(found.plan),
                       "queries": [{"topic": p.topic, "query": p.query, "reason": p.reason} for p in found.plan],
                       "sources": [{"url": v["url"], "date": v["date"], "topic": v["topic"], "timing": v["timing"]}
                                   for v in vetted]}
            if vetted:
                log.end(research_step, outputs=outputs, notes=[
                    f"{len(vetted)} source(s) kept from {len(pages_read(found))} approved page(s) and "
                    f"{len(found.plan)} web search(es)"])
            else:
                log.end(research_step, "unavailable", outputs=outputs,
                        notes=["no credible source passed the date, relevance and figure checks"])

    # Analyst-supplied benchmark documents are untrusted sources for the existing Reporting Agent and Judge.
    # They are never part of the financial input or facts JSON. Apply the same source checks as market research.
    benchmark_documents = ((intake or {}).get("benchmark_inputs") or {}).get("documents") or []
    if benchmark_documents and not offline:
        from datetime import date
        from urllib.parse import quote
        documents = []
        for i, document in enumerate(benchmark_documents, 1):
            path = Path(document['path'])
            try:
                document_date = date.fromisoformat(document.get('date') or '').isoformat()
            except ValueError:
                _stop(log, research_step, f"Run stopped: provide the date for {path.name} as YYYY-MM-DD")
            try:
                text = read_document(path).strip()
            except Exception as e:
                _stop(log, research_step, f"Run stopped: benchmark document {path.name} cannot be read ({type(e).__name__})")
            if not text or len(text) > 12000:
                _stop(log, research_step, f"Run stopped: benchmark document {path.name} must contain readable text of at most 12000 characters")
            log.step("read_files").outputs["input_files"].append(f"{path.name} (benchmark evidence; analyst supplied)")
            normalise = lambda value: ' '.join(re.sub(r'[^\w]+', ' ', value.casefold()).split())
            if not profile.benchmark_name or normalise(profile.benchmark_name) not in normalise(text):
                flags.append(DataFlag(check="research", level="info", message=(
                    f"Benchmark document {path.name} excluded: its text does not establish the fund's benchmark identity")))
                text_log.append(f"Benchmark document excluded: {path.name} does not name the fund's benchmark")
                continue
            documents.append({"query": f"Uploaded benchmark document: {path.name}", "topic": "market_drivers",
                              "summary": text, "url": f"uploaded://benchmark/{i}-{quote(path.name)}",
                              "date": document_date, "date_basis": "as_at", "source_type": "uploaded_document",
                              "limitations": "Analyst-supplied document and date; treat as untrusted and verify against the original."})
        doc_sources, doc_flags, doc_log = vet_summaries(documents, profile, facts,
            market_grace_days=load_sources().vetting.market_grace_days)
        vetted += with_timing(doc_sources, profile)
        flags += doc_flags
        text_log += doc_log
        research_step.outputs["benchmark_documents_kept"] = len(doc_sources)

    # 8. Narrative: the findings and actions are written by code; the market context, if any, comes from the
    # Reporting Agent's checked draft below (the Analyst and Evaluator are not called in Version 1)
    narrative = Narrative(template(facts), "template")

    # 8b. Reporting Agent (one draft per angle) and the Judge Agent's review; code checks and decides
    step = log.start("drafts", ["facts JSON"] + [f"angle: {a}" for a in plan.angles], announce=not offline)
    if offline:
        log.end(step, "skipped", notes=["offline run: code's conclusion"])
    else:
        drafted = await _timed(draft_and_judge(facts, plan.angles, plan.focus, r.reporter, r.judge,
                                               s.drafting.max_rewrites, s.drafting.max_summary_chars,
                                               s.drafting.max_drafts, s.drafting.rejudge_after_rewrite, vetted,
                                               s.drafting.reporter_tools, plan.to_dict(),
                                               s.drafting.reporter_max_turns, question),
                               s.timeouts_seconds.drafting)
        if drafted is None:
            flags.append(DataFlag(check="judge", level="info", message=(
                f"AI drafts: the Reporting Agent or Judge {_why(s.timeouts_seconds.drafting)}; code's conclusion "
                "used (labelled as written by code)")))
            log.end(step, _status(), notes=[_why(s.timeouts_seconds.drafting)])
        else:
            chosen = drafted.chosen
            facts["drafts"] = [x.to_dict(x is chosen) for x in drafted.scored]
            if chosen:
                facts["suggested_conclusion"] |= {"text": chosen.draft.text, "answer": chosen.draft.answer,
                                                  "evidence": chosen.draft.evidence, "question": question,
                                                  "next_step": chosen.draft.next_step,
                                                  "executive": [] if chosen.draft.executive_problems else
                                                  chosen.draft.executive,
                                                  "source": "ai", "angle": chosen.draft.angle,
                                                  "revised": REVISED in chosen.issues}
                if not facts["suggested_conclusion"]["executive"]:
                    flags.append(DataFlag(check="judge", level="info", message=(
                        "Executive commentary left out: " + ("it did not pass code's checks"
                                                             if chosen.draft.executive else "the AI draft had none")
                        + "; the PDF shows the dashboard answer")))
                if vetted and ("[" in chosen.draft.text or "[" in " ".join(chosen.draft.executive)):
                    step.outputs["sources"] = numbered_sources(vetted)      # cited commentary needs a source list
                context = chosen.draft.market_context if not chosen.draft.context_problems else None
                if context:
                    narrative = Narrative(assemble(facts, context), "ai", [], [], numbered_sources(vetted))
                    step.outputs["sources"] = narrative.sources
                elif vetted:
                    flags.append(DataFlag(check="research", level="info", message=(
                        "Market context left out: " + ("it did not pass code's checks (figures, citations, dates)"
                                                       if chosen.draft.market_context else
                                                       "the Reporting Agent found no source relevant to this fund"))))
            elif vetted:
                flags.append(DataFlag(check="research", level="info", message=(
                    "Market context left out: the AI draft was not used, so code's conclusion stands alone")))
            flags += drafted.flags
            text_log += drafted.log
            log.end(step, "ok" if chosen else "fallback", outputs={
                "chosen": chosen.draft.angle if chosen else None, "reason": drafted.reason,
                "decisions": {x.draft.angle: x.decision for x in drafted.scored}},
                notes=([] if chosen else [f"Judge: {drafted.reason}"]) + drafted.log)

    # 9. Report (its sources list comes from this log)
    step = log.start("report")
    input_files, web_sources = log.report_sources()
    inputs = ReportInputs(profile=profile, question=question, reported=reported, card=card, facts=facts,
                          narrative=narrative, thresholds=t, flags=flags, promises=promises, peers=peers,
                          peer_comparison=peer_comparison, evidence=evidence, sector_ocf=_sector_ocf(profile),
                          prices=checked.prices, run_note=OFFLINE_NOTE if offline else None,
                          input_files=input_files, web_sources=web_sources,
                          entered_by_user=[r["label"] for r in (intake or {}).get("rows", [])
                                           if r.get("status") == "Entered by user"])
    # The Executive Report (2 pages) first: if it cannot fit without losing information it is not produced, and a
    # warning says so in the Detailed Report, which keeps everything
    executive_pdf = None
    try:
        executive_pdf, fallback = build_executive_reliably(inputs, run_dir)
        if fallback:
            flags.append(fallback)
            inputs.flags = flags
    except ReportLayoutError as e:
        flags.append(DataFlag(check="report_layout", level="warning", message=(
            f"Executive Report not produced: {e}. Nothing was cut; the Detailed Report has every section.")))
        inputs.flags = flags
    try:
        pdf = build_report(inputs, run_dir)
    except ReportLayoutError as e:
        _stop(log, step, f"Run stopped: the report does not fit its pages ({e})")
    (run_dir / "facts.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding="utf-8")
    text_log += [f"[{f.level}] {f.message}" for f in flags]
    log.end(step, outputs={"pdf": str(pdf), "executive_pdf": str(executive_pdf) if executive_pdf else None})

    # 10. Email (plain code, off by default; recipients from EMAIL_TO only)
    step = log.start("email", announce=False)
    attach = executive_pdf if s.email.attachment == "executive" and executive_pdf else pdf
    kind = "Executive" if attach == executive_pdf else "Detailed"
    line = send_report(attach, s.email, profile.fund_name, f"{profile.as_of_date:%d %b %Y}",
                       **({"post": r.email_post} if r.email_post else {}),
                       filename=report_filename(profile.fund_name, kind, profile.as_of_date))
    if s.email.attachment == "executive" and executive_pdf is None and s.email.enabled:
        line += " (Detailed Report attached: the Executive Report was not produced)"
    text_log.append(line)
    log.end(step, "ok" if line.startswith("Email: sent") else "failed" if s.email.enabled else "skipped", notes=[line])
    return RunResult(pdf, run_dir, log, narrative, facts, {name: plain_reason(inputs, name) for name in card.pillars},
                     list({(f.level, f.message): f for f in flags}.values()), executive_pdf)
