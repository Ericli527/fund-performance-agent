""" Run one review end to end and save the PDF to runs/<timestamp>/ (step 9 runner; the workflow controller
with its JSON run log replaces it in step 10)

    PYTHONPATH=src python -m fund_performance.run_report --data data/test1
    PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline   # no AI calls

The folder holds fund_profile.json, factsheet_performance.json, a price file and optionally peer.json.
"""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
from fund_performance.agents.analyst import Narrative, template, write_narrative
from fund_performance.agents.mandate import read_mandate
from fund_performance.agents.research import market_name, research, vet_summaries
from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import load_sources, load_thresholds
from fund_performance.facts import build_facts
from fund_performance.fetch import fetch_pages
from fund_performance.io import detect_file_type, read_json, read_prices
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, FactsheetPerformance, FundProfile, Peer
from fund_performance.precedence import apply_precedence
from fund_performance.report import ReportInputs, build_report
from fund_performance.scorecard import score

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTION = "Is this index fund meeting its mandate, and is its fee justified?"
OFFLINE_NOTE = "Offline run: AI steps skipped (no Mandate Agent, approved sources, web research or Analyst)"


def find_inputs(folder: Path) -> dict:
    """ The input files in a folder, by type (answer keys are never read) """
    found: dict = {"documents": []}
    for path in sorted(folder.iterdir()):
        if path.is_dir() or "answer_key" in path.parts:
            continue
        kind = detect_file_type(path)
        if kind == "document":
            found["documents"].append(path)
        elif kind != "unknown":
            found.setdefault(kind, path)
    return found


async def run_review(folder: Path, question: str, out_root: Path, offline: bool = False) -> Path:
    t = load_thresholds()
    files = find_inputs(folder)
    profile: FundProfile = read_json(files["fund_profile"])
    factsheet: FactsheetPerformance | None = read_json(files["factsheet_performance"]) if "factsheet_performance" in files else None
    peer: Peer | None = read_json(files["peer"]) if "peer" in files else None
    log: list[str] = []

    data = read_prices(files["prices"])
    log += data.log
    checked = check_prices(data, profile, t, factsheet)
    calculated = calculate(checked.prices, profile, t, factsheet)
    reported = apply_precedence(calculated, checked.flags, profile, t, factsheet, checked.comparison)
    log += reported.log
    flags: list[DataFlag] = list(reported.flags)

    promises: list[str] = []
    if offline:
        flags.append(DataFlag(check="run", level="info", message=OFFLINE_NOTE))
    else:
        mandate = await read_mandate(profile)
        profile, promises = mandate.profile, mandate.promises
        flags += mandate.flags

    path = decision_path(profile, checked.short_history, flags)
    comparison = checked.comparison
    card = score(reported, profile, t, path, peer, comparison.fund_series if comparison else "fund_nav",
                 comparison.extra_tolerance_pp if comparison else 0.0)
    facts = build_facts(profile, reported, card, flags, promises)

    if offline:
        narrative = Narrative(template(facts), "template")
    else:
        sources = load_sources()
        pages = await fetch_pages(sources.for_fund(profile.isin, market_name(profile)), sources.fetch)
        found = await research(profile, card, t.limits.max_web_searches, pages)
        vetted, vet_flags, vet_log = vet_summaries(found.summaries, profile, facts,
                                                   market_grace_days=sources.vetting.market_grace_days)
        flags += found.flags + vet_flags
        log += found.log + vet_log
        narrative = await write_narrative(facts, vetted)
        flags += narrative.flags
        log += narrative.log

    run_dir = out_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    inputs = ReportInputs(profile=profile, question=question, reported=reported, card=card, facts=facts,
                          narrative=narrative, thresholds=t, flags=flags, promises=promises, peer=peer,
                          prices=checked.prices, run_note=OFFLINE_NOTE if offline else None,
                          input_files=[p.name for k, p in files.items() if k != "documents"]
                          + [f"{p.name} (document; not read, as structured files were supplied)" for p in files["documents"]])
    pdf = build_report(inputs, run_dir)
    (run_dir / "facts.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding="utf-8")
    (run_dir / "run_log.txt").write_text("\n".join(log + [f"[{f.level}] {f.message}" for f in flags]), encoding="utf-8")
    return pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one fund performance review and save the PDF")
    parser.add_argument("--data", required=True, help="folder with fund_profile.json, factsheet_performance.json and prices")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--out", default=str(ROOT / "runs"))
    parser.add_argument("--offline", action="store_true", help="skip all AI steps (template narrative, no web research)")
    args = parser.parse_args()
    pdf = asyncio.run(run_review(Path(args.data), args.question, Path(args.out), args.offline))
    print(f"Report: {pdf}")


if __name__ == "__main__":
    main()
