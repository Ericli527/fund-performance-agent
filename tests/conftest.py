""" Shared test paths. The real Test 1 files live in data/ (gitignored), so tests that need them skip when absent """
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEST1 = ROOT / "data" / "test1"
TEST1_CSV = TEST1 / "Fidelity_Index_US_P_Acc.csv"
TEST1_FACTSHEET = TEST1 / "factsheet_performance.json"
TEST1_PROFILE = TEST1 / "fund_profile.json"

requires_test1 = pytest.mark.skipif(
    not all(p.exists() for p in (TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE)),
    reason="Test 1 files are not in data/test1 (they are kept out of the public repo)")
