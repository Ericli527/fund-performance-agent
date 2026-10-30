"""Exercise the CI gate with reports independent of the application test runner."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('skip_audit', Path(__file__).parents[1] / 'scripts/check_test_skips.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.mark.parametrize('body,expected', [
    ('<testcase name="passes"/>', 0),
    ('<testcase classname="private" name="known"><skipped message="Skipped: missing private data"/></testcase><testcase/>', 0),
    ('<testcase classname="private" name="known"><skipped message="different reason"/></testcase><testcase/>', 1),
    ('<testcase classname="core" name="new"><skipped message="missing private data"/></testcase><testcase/>', 1),
    ('<testcase><failure/></testcase>', 1),
    ('<testcase><error/></testcase>', 1),
    ('', 1),
])
def test_skip_gate(tmp_path, body, expected):
    report = tmp_path / 'results.xml'
    report.write_text('<testsuites><testsuite>' + body + '</testsuite></testsuites>')
    allowed = tmp_path / 'allowed.json'
    allowed.write_text(json.dumps({'private::known': 'missing private data'}))
    assert audit.check(report, allowed) == expected
