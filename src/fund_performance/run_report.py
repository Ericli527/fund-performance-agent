""" Run one review from the command line and save the PDF to runs/<timestamp>/ (the workflow controller,
controller.py, does the work)

    PYTHONPATH=src python -m fund_performance.run_report --data data/test1
    PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline   # no AI calls

The folder holds fund_profile.json, a price file, and factsheet_performance.json (or the factsheet and KID
PDFs, read by the Extractor Agent), and optionally peer.json.
"""
import argparse
import asyncio
from pathlib import Path
import sys
from fund_performance.controller import DEFAULT_QUESTION, RunStopped
from fund_performance.controller import run_review as run_controller

ROOT = Path(__file__).resolve().parents[2]


async def run_review(folder: Path, question: str, out_root: Path, offline: bool = False) -> Path:
    """ The PDF's path (kept for the step 9 tests and scripts) """
    return (await run_controller(folder, question, out_root, offline)).pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one fund performance review and save the PDF")
    parser.add_argument("--data", required=True, help="folder with fund_profile.json, a price file and factsheet figures")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--out", default=str(ROOT / "runs"))
    parser.add_argument("--offline", action="store_true", help="skip all AI steps (template narrative, no web research)")
    args = parser.parse_args()
    try:
        result = asyncio.run(run_controller(Path(args.data), args.question, Path(args.out), args.offline))
    except RunStopped as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    print(f"Report: {result.pdf}\nRun log: {result.run_dir / 'log.json'}")


if __name__ == "__main__":
    main()
