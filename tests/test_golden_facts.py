""" Regression protection for the financial facts and ratings (UX redesign, Stage 0)

Each case runs the review offline (no AI, deterministic) and compares the whole facts JSON (every figure with its
source, the scorecard ratings and reasons, the verdict, data notes and flags, peers, the evidence statistics and the
code-written conclusion, points and questions) with a saved baseline. A change to the page or the report must never
change these; a deliberate change to a calculation updates the baseline on purpose:

    PYTHONPATH=src python tests/test_golden_facts.py --update

The demo baseline (a made-up fund) is committed in tests/golden/. The Test 1 baselines are kept next to the Test 1
files in data/test1/golden/, and the real-fund demo baselines in data/demos/golden/ (gitignored, like the files they
come from); their tests skip when absent.
"""
import asyncio
import json
from pathlib import Path
import shutil
import sys
import tempfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from conftest import TEST1  # noqa: E402

DEMO = ROOT / "demo" / "sample_index_fund"
DEMOS = ROOT / "data" / "demos"
CASES = {
    "demo": (DEMO, ROOT / "tests" / "golden" / "demo_facts.json", None),
    "test1": (TEST1, TEST1 / "golden" / "test1_facts.json", None),
    "test1_with_approved_peers": (TEST1, TEST1 / "golden" / "test1_with_approved_peers_facts.json", "peers"),
    # Stage 4B: the real-fund demos' Quick Demo inputs (private, gitignored: data/demos/), baselines beside them
    "demo_fidelity_us": (DEMOS / "fidelity_us" / "quick", DEMOS / "golden" / "fidelity_us_facts.json", None),
    "demo_vanguard_global": (DEMOS / "vanguard_global" / "quick", DEMOS / "golden" / "vanguard_global_facts.json", None),
}


def facts_for(case: str) -> dict:
    """ The facts JSON of an offline run, as plain JSON (what facts.json holds) """
    from fund_performance.controller import run_review
    folder, _, extra = CASES[case]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "in"
        shutil.copytree(folder, work, ignore=shutil.ignore_patterns("*.pdf", "golden"))
        if extra == "peers":                         # the two approved S&P 500 peers, as typed in test_peers.py
            from test_peers import HSBC, VANGUARD
            (work / "peer.json").write_text(json.dumps([VANGUARD, HSBC]))
        result = asyncio.run(run_review(work, out_root=Path(tmp) / "runs", offline=True))
        return json.loads(json.dumps(result.facts, ensure_ascii=False))


def _available(case: str) -> bool:
    folder, golden, _ = CASES[case]
    return folder.exists() and golden.exists()


@pytest.mark.parametrize("case", list(CASES))
def test_facts_and_ratings_match_the_baseline(case):
    if not _available(case):
        pytest.skip(f"no baseline for {case} (create it with: PYTHONPATH=src python tests/test_golden_facts.py --update)")
    expected = json.loads(CASES[case][1].read_text(encoding="utf-8"))
    actual = facts_for(case)
    assert actual["scorecard"] == expected["scorecard"], "ratings, reasons or verdict changed"
    assert actual["figures"] == expected["figures"], "a figure, its unit or its source changed"
    assert actual == expected, "the facts changed (data notes, flags, peers, evidence or code-written text)"


def update() -> None:
    import os
    os.environ.setdefault("FUND_PEER_FOLDER", tempfile.mkdtemp())     # as in the unit tests: no approved-peer files
    for case, (folder, golden, _) in CASES.items():
        if not folder.exists():
            print(f"skipped {case}: {folder} not found")
            continue
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(facts_for(case), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {golden.relative_to(ROOT)}")


if __name__ == "__main__":
    if "--update" in sys.argv:
        update()
    else:
        print(__doc__)
