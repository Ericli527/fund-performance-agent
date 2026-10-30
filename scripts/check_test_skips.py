"""Fail CI for skips outside the reviewed private-data allowlist (JUnit from pytest)."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def check(report: Path, allowlist: Path) -> int:
    allowed = json.loads(allowlist.read_text())
    cases = list(ET.parse(report).iter('testcase'))
    unexpected = []
    expected = []
    for case in cases:
        skipped = case.find('skipped')
        if skipped is None:
            continue
        key = f"{case.get('classname')}::{case.get('name')}"
        reason = skipped.get('message', '').removeprefix('Skipped: ')
        bucket = expected if allowed.get(key) == reason else unexpected
        bucket.append((key, reason))
    for label, rows in [('Expected private-data skips', expected), ('UNEXPECTED skips', unexpected)]:
        print(f'{label}: {len(rows)}')
        for key, reason in rows:
            print(f'  {key}: {reason}')
    executed = sum(c.find('skipped') is None for c in cases)
    print(f'Executed tests: {executed}')
    failed = any(c.find('failure') is not None or c.find('error') is not None for c in cases)
    return int(bool(unexpected) or executed == 0 or failed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--allowlist', type=Path, default=Path('tests/expected_private_skips.json'))
    args = parser.parse_args()
    raise SystemExit(check(args.report, args.allowlist))
