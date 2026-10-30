""" Workflow controller (spec Section 8.5): a plain Python function, not an AI agent, that runs one review

read files -> task plan (Task Planner Agent; default plan offline) -> extractor (only if there is no
factsheet_performance.json) -> approved peers (only if there is no
peer.json: the Extractor reads their factsheets) -> data checks -> mandate -> calculator
-> scorecard -> approved sources, planner and searches (parallel; only if the plan needs market context) ->
analyst -> number, label, rating and wording checks -> evaluator -> reporting agents (one draft per angle, in
parallel) -> code's checks and the Judge Agent -> report -> email (off by default).

The extractor runs before the data checks because the repeated-price check compares with the factsheet.

- The run stops with a clear message (RunStopped) when it cannot be scored at all: no folder, no or an invalid
  fund profile, no or an unreadable price file. A blocking data check does not stop the run: the affected
  rating is CHECK DATA and the verdict waits for a data check (spec 5.1 and 6.5), so the report says what to fix.
- Limits from config: at most limits.max_web_searches web searches and limits.max_analyst_rewrites rewrites
  (thresholds.yaml); a timeout for each AI step (settings.yaml). A step that times out is handled like a
  failed step and flagged.
- Each step is logged (start, end, inputs used, outputs) to runs/<timestamp>/log.json; the report's sources
  list is built from this log.
"""
import asyncio
from dataclasses import asdict, dataclass, field
from typing import Callable
from datetime import datetime
from functools import partial
import json
from pathlib import Path
import time
import uuid
from fund_performance.agents.analyst import AI_TEXT_UNAVAILABLE, Narrative, template, write_narrative
from fund_performance.agents.base import RunFn
from fund_performance.agents.evaluator import review
from fund_performance.agents.extractor import extract
from fund_performance.agents.judge import draft_and_judge
from fund_performance.agents.task_planner import TaskPlan, plan_tasks
from fund_performance.agents.mandate import read_mandate
from fund_performance.agents.research import market_name, research, vet_summaries
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
# Live progress (Stage 6C): each workflow step, as it actually starts, is shown as "Step X of 5 · who · what".
# AI steps that are skipped (offline, or already done on the page) are not announced
STAGES = {
    "read_files": (1, "Code: input files", "Reading the price file and the inputs"),
    "self_check": (1, "Code: self-check", "Checking every value the agents read against the documents"),
    "plan": (1, "Task Planner Agent", "Choosing what the review should focus on"),
    "extractor": (1, "Extractor Agent", "Reading the factsheet and KID"),
    "peers": (1, "Extractor Agent", "Reading the approved peers' factsheets"),
    "data_checks": (2, "Code: data checks", "Checking the prices and the factsheet figures"),
    "mandate": (2, "Mandate Agent", "Reading the fund's objective and promises"),
    "calculator": (3, "Code: calculator", "Calculating returns, risk and gaps to the index"),
    "scorecard": (3, "Code: scorecard", "Rating mandate, performance, value for investors and fees"),
    "research": (4, "Research Agents", "Checking approved sources and searching for market news"),
    "narrative": (4, "Oversight Analyst and Evaluator", "Writing and checking the market context"),
    "drafts": (4, "Reporting Agents and Judge", "Drafting and judging the summary"),
    "report": (5, "Code: reports", "Building the Executive and Detailed PDF reports"),
}
TOTAL_STAGES = 5
DOCUMENTS_STAGE = (1, "Extractor Agent and Mandate Agent", "Reading the factsheet, KID and peer factsheets")


def progress_line(stage: int, who: str, what: str) -> str:
    """ "Step 2 of 5 · Code: data checks · Checking the prices and the factsheet figures…" """
    return f"Step {stage} of {TOTAL_STAGES} · {who} · {what}…"


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
            notes: list[str] | None = None) -> None:
        record.ended, record.status = _now(), status
        record.seconds = round(time.monotonic() - self._clock.get(record.step, time.monotonic()), 2)
        record.outputs |= outputs or {}
        record.notes += notes or []

    def finish(self, status: str, message: str | None = None) -> None:
        self.run |= {"ended": _now(), "status": status, "message": message}

    def step(self, name: str) -> StepRecord | None:
        return next((s for s in self.steps if s.step == name), None)

    def report_sources(self) -> tuple[list[str], list[dict]]:
        """ The input files the read step used, and the numbered web sources the narrative step cited """
        read, narrative = self.step("read_files"), self.step("narrative")
        files = read.outputs.get("input_files", []) if read else []
        return files, narrative.outputs.get("sources", []) if narrative else []

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


async def _timed(coro, seconds: float):
    """ Run one AI step with its timeout; None if it ran over """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        return None


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
    text_log: list[str] = []
    try:
        result = await _run(folder, question, run_dir, offline, t, s, r, log, text_log, intake)
        log.finish("ok")
        return result
    except RunStopped as e:
        log.finish("stopped", str(e))
        raise
    finally:
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
                f"Approved peer factsheet {path.name}: the Extractor Agent did not finish in time, so it is left out")))
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

    # 1b. Task plan: the Task Planner Agent turns the request into tasks (menu choices only, checked by code)
    step = log.start("plan", ["question", "fund_profile.json: public details"], announce=not offline)
    if offline:
        plan = TaskPlan(reason="Default plan: offline run", source="default (offline)")
        log.end(step, "skipped", outputs=plan.to_dict(), notes=["offline run: default plan"])
    else:
        planned = await _timed(plan_tasks(question, profile, r.task_planner), s.timeouts_seconds.task_planner)
        if planned is None:
            plan = TaskPlan(reason="Default plan: the Task Planner did not answer in time")
            flags.append(DataFlag(check="task_planner", level="info", message=(
                f"The Task Planner Agent did not answer within {s.timeouts_seconds.task_planner:g} seconds; default plan used")))
            log.end(step, "timeout", outputs=plan.to_dict())
        else:
            plan, plan_flags = planned
            flags += plan_flags
            log.end(step, "ok" if plan.source == "planner" else "failed", outputs=plan.to_dict())
    text_log.append(f"Plan ({plan.source}): {plan.report_type}; focus {', '.join(plan.focus)}; " + " -> ".join(plan.tasks))

    # 2. Extractor (only when no factsheet_performance.json was supplied)
    step = log.start("extractor", [p.name for p in files["documents"]],
                     announce=not intake and factsheet is None and not offline and bool(files["documents"]))
    if intake:
        log.end(step, "skipped", notes=["documents read before the run; values checked by code"])
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
                f"No factsheet figures: the Extractor Agent did not finish within {s.timeouts_seconds.extractor:g} "
                "seconds. Calculated figures only")))
            log.end(step, "timeout")
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

    # 3. Data checks
    step = log.start("data_checks", [files["prices"].name] + (["factsheet figures"] if factsheet else []))
    try:
        data = read_prices(files["prices"])
    except (ValueError, KeyError) as e:
        _stop(log, step, f"Run stopped: the price file {files['prices'].name} cannot be read ({str(e)[:300]})")
    text_log += data.log
    checked = check_prices(data, profile, t, factsheet)
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
                notes=["Mandate Agent read the objective before the run"])
    else:
        mandate = await _timed(read_mandate(profile, r.mandate), s.timeouts_seconds.mandate)
        if mandate is None:
            flags.append(DataFlag(check="mandate_agent", level="blocking", message=(
                f"CHECK DATA: Mandate Agent did not answer within {s.timeouts_seconds.mandate:g} seconds")))
            log.end(step, "timeout")
        else:
            profile, promises = mandate.profile, mandate.promises
            flags += mandate.flags
            log.end(step, outputs={"promises": len(promises), "flags": [f.message for f in mandate.flags]})

    # 5. Calculator (with factsheet precedence)
    step = log.start("calculator", [files["prices"].name] + (["factsheet figures"] if factsheet else []))
    calculated = calculate(checked.prices, profile, t, factsheet)
    reported = apply_precedence(calculated, checked.flags, profile, t, factsheet, checked.comparison)
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

    # 7. Research: approved sources, planner and web searches, then vetting
    vetted: list[dict] = []
    step = log.start("research", announce=not offline and plan.market_context)
    if offline:
        log.end(step, "skipped", notes=["offline run"])
    elif not plan.market_context:
        log.end(step, "skipped", notes=["the plan needs no market context"])
    else:
        sources = load_sources()
        approved = sources.for_fund(profile.isin, market_name(profile))
        step.inputs = [f"approved: {a.url}" for a in approved]

        async def do_research():
            pages = await fetch_pages(approved, sources.fetch, r.http_get)
            found = await research(profile, card, t.limits.max_web_searches, pages, r.planner, r.search, r.page)
            return found, vet_summaries(found.summaries, profile, facts,
                                        market_grace_days=sources.vetting.market_grace_days)
        done = await _timed(do_research(), s.timeouts_seconds.research)
        if done is None:
            flags.append(DataFlag(check="research", level="warning", message=(
                f"Web research did not finish within {s.timeouts_seconds.research:g} seconds, so there is no "
                "market context")))
            log.end(step, "timeout")
        else:
            found, (vetted, vet_flags, vet_log) = done
            flags += found.flags + vet_flags
            text_log += found.log + vet_log
            step.inputs += [f"web search: {p.query}" for p in found.plan]
            log.end(step, outputs={"summaries": len(found.summaries), "kept": len(vetted),
                                   "web_searches": len(found.plan)})

    # 8. Analyst, code checks and Evaluator (one rewrite in total)
    step = log.start("narrative", ["facts JSON"] + [f"source: {v['url']}" for v in vetted], announce=not offline)
    if offline:
        narrative = Narrative(template(facts), "template")
        log.end(step, "skipped", notes=["offline run: template narrative"])
    else:
        narrative = await _timed(write_narrative(facts, vetted, max_rewrites=t.limits.max_analyst_rewrites,
                                                 run=r.analyst, quality_check=partial(review, run=r.evaluator),
                                                 max_evaluator_rewrites=t.limits.max_evaluator_rewrites),
                                 s.timeouts_seconds.narrative)
        if narrative is None:
            narrative = Narrative(template(facts), "template", [DataFlag(
                check="analyst", level="warning", message=(
                    f"{AI_TEXT_UNAVAILABLE}: the Analyst did not finish within {s.timeouts_seconds.narrative:g} "
                    "seconds; template narrative used"))])
            log.end(step, "timeout")
        else:
            log.end(step, "ok" if narrative.source == "ai" else "failed", notes=narrative.log)
        flags += narrative.flags
        text_log += narrative.log
    step.outputs |= {"source": narrative.source, "sources": narrative.sources}

    # 8b. Reporting Agents (one draft per angle) and the Judge Agent; code checks, scores and picks
    step = log.start("drafts", ["facts JSON"] + [f"angle: {a}" for a in plan.angles], announce=not offline)
    if offline:
        log.end(step, "skipped", notes=["offline run: code's conclusion"])
    else:
        drafted = await _timed(draft_and_judge(facts, plan.angles, plan.focus, r.reporter, r.judge,
                                               s.drafting.max_rewrites, s.drafting.max_summary_chars),
                               s.timeouts_seconds.drafting)
        if drafted is None:
            flags.append(DataFlag(check="judge", level="warning", message=(
                f"AI drafts not finished within {s.timeouts_seconds.drafting:g} seconds; code's conclusion used")))
            log.end(step, "timeout")
        else:
            chosen = drafted.chosen
            facts["drafts"] = [x.to_dict(x is chosen) for x in drafted.scored]
            if chosen:
                facts["suggested_conclusion"] |= {"text": chosen.draft.text, "source": "ai", "angle": chosen.draft.angle}
            flags += drafted.flags
            text_log += drafted.log
            log.end(step, "ok" if chosen else "failed", outputs={
                "chosen": chosen.draft.angle if chosen else None,
                "scores": {x.draft.angle: x.score for x in drafted.scored}}, notes=drafted.log)

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
