"""Synthetic partial reviews; no private fund documents are used."""
import asyncio
import json
import shutil
from pathlib import Path

from fund_performance.controller import run_review
from fund_performance.dashboard import dashboard_data, dashboard_html

FIXTURE = Path(__file__).parent / 'fixtures' / 'portable'


def test_partial_review_preserves_horizon_and_unavailable_data(tmp_path):
    folder = tmp_path / 'inputs'
    shutil.copytree(FIXTURE, folder)
    profile_file = folder / 'fund_profile.json'
    profile = json.loads(profile_file.read_text())
    profile.update(time_horizon_years=None, ocf_pct=None, performance_fee=None)
    profile_file.write_text(json.dumps(profile))
    factsheet_file = folder / 'factsheet_performance.json'
    factsheet = json.loads(factsheet_file.read_text())
    factsheet['series'].pop('index', None)
    factsheet.get('series_annualised', {}).pop('index', None)
    factsheet.pop('risk_3y', None)
    factsheet_file.write_text(json.dumps(factsheet))
    result = asyncio.run(run_review(folder, question='Should I invest for five years?', out_root=tmp_path / 'runs', offline=True))
    facts = result.facts
    assert facts['fund']['time_horizon_years'] is None and facts['fund']['analysis_period_years'] == 5
    assert facts['fund']['ocf_pct'] is None
    assert any(f['name'] == 'fund_nav.cum.1y' for f in facts['figures'])
    assert not any(f['name'].startswith('index.') for f in facts['figures'])
    assert not any('td_ex_cost' in f['name'] or f['name'] == 'comparison.hit_rate' for f in facts['figures'])
    assert {p['name']: p['rating'] for p in facts['scorecard']['pillars']}['Fees'] == 'CHECK DATA'
    assert facts['scorecard']['verdict'] == 'Pending data check'
    assert {'fund_horizon', 'ongoing_charge'} <= {f['check'] for f in facts['data_flags']}
    assert result.pdf.is_file() and result.executive_pdf.is_file()
    html = dashboard_html(dashboard_data(result))
    assert 'not established' in html and 'Not available' in html
