""" Run one review from the command line and save the PDF to runs/<timestamp>/ (the workflow controller,
controller.py, does the work)

    PYTHONPATH=src python -m fund_performance.run_report --data data/test1
    PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline          # no AI calls
    PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --from-documents   # documents route

The folder holds fund_profile.json, a price file, and factsheet_performance.json (or the factsheet and KID
PDFs, read by the Extractor Agent), and optionally peer.json.

--from-documents uses only the price file and the documents, as the page's main route does: the Extractor and
Mandate agents read them, code checks each value against the
documents (as on the page), and the review
runs. It prints what was read and, when typed JSON files are in the folder, every value that differs from them;
both are saved in extraction_check.txt in the run folder.
"""
import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
from fund_performance.controller import DEFAULT_QUESTION, RunResult, RunStopped, find_inputs
from fund_performance.controller import run_review as run_controller
from fund_performance.intake import differences, read_documents, self_check, write_inputs

ROOT = Path(__file__).resolve().parents[2]


async def run_review(folder: Path, question: str, out_root: Path, offline: bool = False) -> Path:
    """ The PDF's path (kept for the step 9 tests and scripts) """
    return (await run_controller(folder, question, out_root, offline)).pdf


def document_roles(documents: list[Path]) -> dict[str, Path | None]:
    """ Which document is which, from its name: KID or prospectus, peer factsheet, else the fund's factsheet """
    roles: dict[str, Path | None] = {"factsheet": None, "kid": None, "peer": None}
    for p in documents:
        name = p.name.lower()
        role = ("peer" if "peer" in name else
                "kid" if any(w in name for w in ("kid", "key_investor", "key investor", "kiid", "prospectus")) else
                "factsheet")
        roles[role] = roles[role] or p
    return roles


async def from_documents(folder: Path, question: str, out_root: Path, scoring_offline: bool = False,
                         reader=read_documents) -> tuple[RunResult | None, str]:
    """ The documents route without a person: read, accept the values as read, run. Returns the run (or None if a
    required value is missing) and the check text """
    files = find_inputs(folder)
    roles = document_roles(files["documents"])
    if "prices" not in files or not roles["factsheet"]:
        raise RunStopped(f"Run stopped: --from-documents needs a price file and the factsheet in {folder}")
    intake = await reader(roles["factsheet"], roles["kid"], roles["peer"])
    lines = ["What the agents read:"] + [f"  {r['label']}: {r['value'] or '(empty)'}  [{r['status']}; {r['source']}]"
                                         for r in intake["rows"]]
    if "fund_profile" in files and "factsheet_performance" in files:
        typed = (json.loads(files["fund_profile"].read_text()), json.loads(files["factsheet_performance"].read_text()))
        diffs = differences(intake, *typed)
        lines += ["", f"Compared with the typed JSON files: {len(diffs)} value(s) differ"]
        lines += [f"  {label}: read '{got}', typed '{want}'" for label, got, want in diffs]
    built = self_check(intake)
    if built.problems:
        return None, "\n".join(lines + ["", "Cannot run: " + "; ".join(built.problems)])
    work = Path(tempfile.mkdtemp(prefix="fund-review-"))
    try:
        write_inputs(built, work)
        shutil.copy(files["prices"], work / files["prices"].name)
        result = await run_controller(work, question, out_root, scoring_offline,
                                      intake=intake | {"rows": built.rows, "flags": intake.get("flags", []) + built.flags})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    text = "\n".join(lines)
    (result.run_dir / "extraction_check.txt").write_text(text + "\n", encoding="utf-8")
    return result, text


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one fund performance review and save the PDF")
    parser.add_argument("--data", required=True, help="folder with fund_profile.json, a price file and factsheet figures")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--out", default=str(ROOT / "runs"))
    parser.add_argument("--offline", action="store_true", help="skip all AI steps (template narrative, no web research)")
    parser.add_argument("--from-documents", action="store_true",
                        help="use only the price file and the documents (the Extractor and Mandate agents read them)")
    args = parser.parse_args()
    try:
        if args.from_documents:
            if args.offline:
                sys.exit("--from-documents reads the documents with AI, so it cannot run --offline")
            result, text = asyncio.run(from_documents(Path(args.data), args.question, Path(args.out)))
            print(text)
            if result is None:
                sys.exit(1)
        else:
            result = asyncio.run(run_controller(Path(args.data), args.question, Path(args.out), args.offline))
    except RunStopped as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    executive = result.executive_pdf or "not produced (see the warning in the Detailed Report)"
    print(f"Detailed Report: {result.pdf}\nExecutive Report: {executive}\nRun log: {result.run_dir / 'log.json'}")


if __name__ == "__main__":
    main()
