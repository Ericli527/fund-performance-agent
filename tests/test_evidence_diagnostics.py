from datetime import date
from types import SimpleNamespace
import pandas as pd
from fund_performance.evidence_diagnostics import evidence_gap_summary
from fund_performance.models import DataFlag
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import Pillar, SubRating


def inputs():
    profile = SimpleNamespace(objective_type='index_tracker', analysis_period_years=5, as_of_date=date(2026, 9, 30))
    factsheet = SimpleNamespace(risk_3y=None, risk_3y_nav=None)
    prices = pd.DataFrame({'nav': [100.0, 101.0]})
    calculated = SimpleNamespace(figures={'fund.vol.5y': object()})
    reported = ReportedFigures()
    card = SimpleNamespace(pillars={
        'Mandate': Pillar('Mandate', 'CHECK DATA', 'R² and beta not available from the factsheet or an index price series'),
        'Performance': Pillar('Performance', 'CHECK DATA', 'Not rated', sub_ratings=[
            SubRating('Tracking error', 'CHECK DATA', 'tracking error not available from the factsheet or an index series')])})
    return profile, factsheet, prices, calculated, reported, card


def test_successful_extraction_does_not_mean_missing_risk_was_absent_from_source():
    profile, factsheet, prices, calculated, reported, card = inputs()
    result = evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, [],
                                  {'factsheet': {'as_of_date': '2026-09-30'},
                                   'text_chars': {'factsheet.pdf': 13891, 'kiid.pdf': 10568}})
    message = ' '.join(result)
    assert 'R², beta, tracking error' in message and 'extraction returned structured figures' in message
    assert 'may be absent, missed during extraction or not retained' in message
    assert 'No benchmark price series was loaded' in message and 'fund-only risk measures' in message
    assert 'factsheet.pdf (13891 text characters)' in message and 'kiid.pdf (10568 text characters)' in message


def test_diagnostics_identify_available_return_and_risk_fields_without_filling_gaps():
    profile, factsheet, prices, calculated, reported, card = inputs()
    factsheet.series = {'fund_nav': SimpleNamespace(y1=3.0, y3=None, y5=None, since_launch=None)}
    factsheet.series_annualised = {'index': SimpleNamespace(y1=None, y3=2.0, y5=None, since_launch=None)}
    factsheet.risk_3y = SimpleNamespace(r2=0.99, beta=None, tracking_error=None)
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, []))
    assert 'Structured return figures are available for: fund NAV, benchmark' in message
    assert 'risk figures include R²' in message and 'beta, tracking error' in message


def test_failed_extraction_and_benchmark_alignment_are_distinguished():
    profile, factsheet, prices, calculated, reported, card = inputs()
    prices['index_level'] = [None, 123.0]
    flags = [DataFlag(check='extractor_agent', level='blocking', message='CHECK DATA: Extractor Agent gave no valid answer')]
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, flags))
    assert 'did not produce valid structured figures' in message
    assert 'fewer than two common observations' in message and 'No benchmark price series was loaded' not in message


def test_missing_fund_prices_are_not_mistaken_for_missing_benchmark():
    profile, factsheet, prices, calculated, reported, card = inputs()
    prices = pd.DataFrame({'index_level': [100.0, 101.0]})
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, []))
    assert 'No usable fund NAV price observations were loaded' in message
    assert 'Benchmark prices were supplied' in message and 'No benchmark price series was loaded' not in message


def test_empty_benchmark_column_is_not_described_as_an_absent_column():
    profile, factsheet, prices, calculated, reported, card = inputs()
    prices['index_level'] = [None, None]
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, []))
    assert 'benchmark column was loaded but contains no usable observations' in message
    assert 'No benchmark price series was loaded' not in message


def test_existing_benchmark_and_date_mismatch_are_not_described_as_missing():
    profile, factsheet, prices, calculated, reported, card = inputs()
    prices['index_level'] = [100.0, 101.0]
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, [],
                                             {'factsheet': {'as_of_date': '2026-08-31'}}))
    assert 'factsheet date differs' in message and 'benchmark series was loaded' in message
    assert 'No benchmark price series was loaded' not in message


def test_rejected_extra_risk_tables_are_reported_even_without_missing_ratings():
    profile, factsheet, prices, calculated, reported, card = inputs()
    card.pillars['Mandate'].rating = 'GREEN'
    card.pillars['Performance'].sub_ratings.clear()
    flags = [DataFlag(check='extraction_risk_tables', level='warning', message='Some risk tables were not retained')]
    message = ' '.join(evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, flags))
    assert 'warnings were recorded' in message
    assert 'Not established for the rating' not in message


def test_review_surfaces_actual_missing_benchmark_after_successful_intake(tmp_path):
    import asyncio
    import json
    import shutil
    from pathlib import Path
    from fund_performance.controller import run_review
    from fund_performance.dashboard import dashboard_data, dashboard_sections
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    folder = tmp_path / 'inputs'
    shutil.copytree(sample, folder)
    prices_path = folder / 'prices.csv'
    frame = pd.read_csv(prices_path).drop(columns=['Index Level'])
    frame.to_csv(prices_path, index=False)
    factsheet = json.loads((folder / 'factsheet_performance.json').read_text())
    intake = {'documents': ['factsheet.pdf', 'kiid.pdf'], 'rows': [], 'factsheet': factsheet,
              'text_chars': {'factsheet.pdf': 5000, 'kiid.pdf': 2000},
              'flags': [{'check': 'extractor_agent', 'level': 'info', 'message': 'Figures read by the Extractor Agent'}]}
    result = asyncio.run(run_review(folder, out_root=tmp_path / 'runs', offline=True, intake=intake))
    gaps = ' '.join(result.presentation_context['evidence_gaps'])
    assert 'Document extraction returned structured figures' in gaps
    assert 'No benchmark price series was loaded' in gaps and 'factsheet.pdf (5000 text characters)' in gaps
    assert 'Evidence gaps and next steps' in dashboard_sections(dashboard_data(result))['evidence']
    assert result.pdf.is_file() and result.executive_pdf.is_file()
