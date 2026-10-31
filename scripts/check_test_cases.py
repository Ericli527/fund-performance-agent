""" Check the test cases installed on this machine (or a server): which case files are present, and whether each real
case's price returns match its factsheet (code's return check). Prints file names only, never their content.

    python scripts/check_test_cases.py                 # the folder in FUND_DEMO_DATA, else data/demos/
    python scripts/check_test_cases.py /var/data/demos # a server's persistent disk

Exit code 0 when every listed case is ready, 1 otherwise.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fund_performance.demos import DATA_ENV, load_demos, return_checks  # noqa: E402


def main(folder: str | None = None) -> int:
    if folder:
        os.environ[DATA_ENV] = folder
    ready = True
    for demo in load_demos():
        missing = demo.missing()
        status = "ready" if not missing else "NOT INSTALLED"
        print(f"{demo.title} ({demo.id}): {status} · folder {demo.folder}")
        for name in missing:
            print(f"  missing: {name}")
        if missing:
            ready = False
            continue
        for check in return_checks(demo):
            if check.calculated is None or check.published is None:
                print(f"  return check {check.period}: not available")
                continue
            print(f"  return check {check.period}: prices {check.calculated:.2f}% vs factsheet {check.published:.2f}% "
                  f"({check.basis}) {'ok' if check.ok else 'OUTSIDE ' + str(check.tolerance_pp) + ' pp'}")
            ready = ready and check.ok
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
