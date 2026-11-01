"""Synthetic partial reviews; no private fund documents are used."""
import asyncio
import json
import shutil
from pathlib import Path
import pytest

from fund_performance.controller import run_review
from fund_performance.dashboard import dashboard_data, dashboard_html
from fund_performance.models import FundProfile

FIXTURE = Path(__file__).parent / 'fixtures' / 'portable'


def test_omitted_performance_fee_remains_unknown():
    data = json.loads((FIXTURE / 'fund_profile.json').read_text())
    data.pop('performance_fee', None)
    assert FundProfile.model_validate(data).performance_fee is None


@pytest.mark.parametrize('requested_horizon', [5, 10])
def test_partial_review_preserves_horizon_and_unavailable_data(tmp_path, requested_horizon):
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
    result = asyncio.run(run_review(folder, question=f'Should I invest for {requested_horizon} years?',
                                    out_root=tmp_path / 'runs', offline=True))
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


def test_missing_fee_with_peers_and_calendar_returns_produces_reports(tmp_path):
    folder = tmp_path / 'inputs'
    shutil.copytree(Path(__file__).parents[1] / 'demo' / 'sample_index_fund', folder)
    path = folder / 'fund_profile.json'
    profile = json.loads(path.read_text())
    profile['ocf_pct'] = None
    path.write_text(json.dumps(profile))
    result = asyncio.run(run_review(folder, out_root=tmp_path / 'runs', offline=True))
    assert result.pdf.is_file() and result.executive_pdf.is_file()
    assert next(p for p in result.facts['scorecard']['pillars'] if p['name'] == 'Fees')['rating'] == 'CHECK DATA'
    assert result.facts['evidence']['hit_rate'] is None
    html = dashboard_html(dashboard_data(result))
    assert 'Hit rate: Not available' in html and '0 of 0 calendar years' not in html
