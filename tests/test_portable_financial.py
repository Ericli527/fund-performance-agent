"""Portable integration checks; arithmetic and provenance in fixtures/portable/README.md."""
import asyncio
import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import load_thresholds
from fund_performance.controller import run_review
from fund_performance.io import read_json, read_prices
from fund_performance.mandate import decision_path
from fund_performance.precedence import apply_precedence
from fund_performance.scorecard import score

FIXTURE = Path(__file__).parent / 'fixtures' / 'portable'
T = load_thresholds()


def pipeline(folder=FIXTURE):
    profile = read_json(folder / 'fund_profile.json')
    fs = read_json(folder / 'factsheet_performance.json')
    checked = check_prices(read_prices(folder / 'prices.csv'), profile, T, fs)
    calculated = calculate(checked.prices, profile, T, fs)
    reported = apply_precedence(calculated, checked.flags, profile, T, fs, checked.comparison)
    card = score(reported, profile, T, decision_path(profile, checked.short_history, reported.flags),
                 comparison_series=checked.comparison.fund_series,
                 extra_tolerance_pp=checked.comparison.extra_tolerance_pp)
    return checked, calculated, reported, card


@pytest.mark.parametrize('period,cumulative,annualised', [
    ('1y', 8.108108108108108, 8.108108108108108),
    ('3y', 29.03225806451613, 8.867796417793),
    ('5y', 60.0, 9.856054330612)])
def test_price_file_returns_have_independent_expected_values(period, cumulative, annualised):
    _, result, _, _ = pipeline()
    assert result.figures[f'fund.cum.{period}'].exact == pytest.approx(cumulative, abs=1e-9)
    assert result.figures[f'fund.ann.{period}'].exact == pytest.approx(annualised, abs=1e-9)


def test_official_figures_and_fair_pricing_flow_into_ratings():
    checked, calculated, reported, card = pipeline()
    assert not checked.short_history
    assert checked.comparison.fund_series == 'fund_pnav'
    assert reported.figures['fund_nav.cum.1y'].value == 8.1
    assert reported.figures['fund_nav.cum.1y'].source == 'factsheet'
    assert reported.figures['comparison.excess_cum.5y'].exact == -1.0  # 75 - 76, not 60 - 76
    assert reported.figures['comparison.td.5y'].exact == pytest.approx(-0.1)  # official 12 - 12.1
    assert reported.figures['comparison.td_ex_cost.5y'].exact == pytest.approx(0.0)
    assert reported.figures['risk.nav.fund_vol.3y'].value == 9.0
    assert reported.figures['risk.pnav.fund_vol.3y'].value == 8.0
    assert calculated.not_available['relative.tracking_error.5y'] == 'not available: no index price series'
    assert card.pillars['Mandate'].rating == card.pillars['Performance'].rating == 'GREEN'
    assert card.verdict == 'Monitor until a peer is added'
    assert not any(f.check == 'cross_check' for f in reported.flags)


def test_prelaunch_prices_cannot_change_postlaunch_risk_or_returns(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / 'inputs')
    path = tmp_path / 'inputs' / 'prices.csv'
    path.write_text(path.read_text().replace('Date,NAV\n', 'Date,NAV\n2020-11-30,10000\n'))
    checked, result, _, _ = pipeline(path.parent)
    assert any(f.check == 'pre_launch' and f.dates == [date(2020, 11, 30)] for f in checked.flags)
    baseline = pipeline()[1]
    for key in ('fund.vol.5y', 'fund.mdd.5y', 'fund.since_launch.cum'):
        assert result.figures[key].exact == baseline.figures[key].exact
    assert result.figures['fund.mdd.5y'].exact == 0.0


def test_csv_and_excel_preserve_missing_prices_without_interpolation(tmp_path):
    from fund_performance.calc import period_returns
    csv = tmp_path / 'prices.csv'
    csv.write_text('Date,NAV,Index Level\n2025-01-31,100,200\n2025-02-28,110,220\n2025-03-31,-,242\n2025-04-30,121,266.2\n')
    excel = tmp_path / 'prices.xlsx'
    pd.read_csv(csv).to_excel(excel, index=False)
    for path in (csv, excel):
        loaded = read_prices(path)
        checked = check_prices(loaded, read_json(FIXTURE / 'fund_profile.json'), T)
        assert any(f.check == 'missing_values' and f.dates == [date(2025, 3, 31)] for f in checked.flags)
        returns = period_returns(loaded.prices.set_index('date')['nav'])
        assert returns.iloc[0] == pytest.approx(0.1)
        assert returns.iloc[1:].isna().all()


@pytest.mark.parametrize('scenario,verdict,performance', [
    ('underperformance', 'Review', 'RED'),
    ('missing_te', 'Pending data check', 'CHECK DATA'),
    ('currency_mismatch', 'Pending data check', 'CHECK DATA')])
def test_offline_controller_material_outcomes(tmp_path, scenario, verdict, performance):
    folder = tmp_path / 'inputs'
    shutil.copytree(FIXTURE, folder)
    path = folder / 'factsheet_performance.json'
    fs = json.loads(path.read_text())
    if scenario == 'underperformance':
        fs['series_annualised']['fund_pnav']['5y'] = 9.0  # 9 - 12.1 = -3.1 pp, beyond 0.4 pp Amber limit
    elif scenario == 'missing_te':
        del fs['risk_3y']['tracking_error']
    else:
        prices = pd.read_csv(folder / 'prices.csv')
        prices['Index Level'] = prices['NAV'] * 2  # 2025: 160 / 148 - 1 = 8.108%, not 20%
        prices.to_csv(folder / 'prices.csv', index=False)
        fs['calendar_years'] = {'index': {'2025': 20.0}}
    path.write_text(json.dumps(fs))
    if scenario == 'currency_mismatch':
        # Financial checks pass independently of the reports
        checked, _, _, card = pipeline(folder)
        assert any(f.level == 'blocking' and f.check == 'currency_match' for f in checked.flags)
        assert card.verdict == verdict
        assert card.pillars['Performance'].rating == performance
    result = asyncio.run(run_review(folder, out_root=tmp_path / 'runs', offline=True))
    facts = json.loads((result.run_dir / 'facts.json').read_text())
    assert facts['scorecard']['verdict'] == verdict
    pillars = {p['name']: p for p in facts['scorecard']['pillars']}
    assert pillars['Performance']['rating'] == performance
    if scenario == 'currency_mismatch':
        # Stage 3: the long blocking warning used to push the old summary page to six pages and stop the run. Now
        # the Executive Report keeps exactly two pages and shows the warning in full; the Detailed Report has it too
        from fund_performance.report import page_texts
        blocking = next(f for f in result.flags if f.level == 'blocking' and f.check == 'currency_match')
        executive = page_texts(result.executive_pdf)
        assert len(executive) == 2
        assert ' '.join(blocking.message.split()) in ' '.join(executive[1].split())   # never shortened
        assert 'Pending data check' in executive[0] and 'Data check needed' in executive[0]
        assert ' '.join(blocking.message.split()) in ' '.join(' '.join(page_texts(result.pdf)).split())
        # Stage 3.1: the misleading gap chart is replaced on the Executive Report by an explanation; the Detailed
        # Report keeps the original charts, marked as not reliable
        assert 'Chart left out: the comparison with the index is not reliable' in ' '.join(executive[0].split())
        assert not (result.run_dir / 'exec_chart.png').exists()
        detailed = ' '.join(' '.join(page_texts(result.pdf)).split())
        assert 'Read with care. Not reliable until the data check is resolved' in detailed
        assert (result.run_dir / 'dash_gaps.png').is_file()
        # ... and nothing on the dashboard or in either PDF treats the comparison as reliable (Stage 3.1 follow-up):
        # the summaries replace the fund-vs-index figures; the Detailed Report keeps them, marked
        from html import unescape
        import re
        from fund_performance.dashboard import dashboard_data, dashboard_html
        page = ' '.join(unescape(re.sub(r'<[^>]+>', ' ', dashboard_html(dashboard_data(result), 'analyst'))).split())
        summary = ' '.join(' '.join(executive).split())
        for text in (summary, page):
            assert '16.0 pp' not in text and 'behind its index' not in text and 'would match its index' not in text
            assert '−0.10 pp' not in text and 'Not reliable' in text
        assert 'no finding is drawn from them' in summary and 'no finding is drawn from them' in page
        assert 'Index (not reliable: data check)' in detailed and 'Gap at noon prices −16.0 pp' in detailed
        assert 'Not reliable (data check): The fund is priced at noon' in detailed
    if scenario == 'underperformance':
        assert 'Action needed' in json.dumps(facts)
    assert result.pdf.is_file()  # real controller/report execution, no mocked financial stages


def test_risk_and_calendar_results_from_the_same_price_fixture():
    _, result, _, _ = pipeline()
    # Sample stdev of 1/100, ..., 1/159; independently evaluated with statistics.stdev.
    assert result.figures['fund.vol.5y'].exact == pytest.approx(0.375587684024, abs=1e-9)
    assert result.figures['fund.mdd.5y'].exact == 0.0  # strictly increasing prices
    for year, expected in [('2021', 12.0), ('2022', 10.714285714286),
                           ('2023', 9.677419354839), ('2024', 8.823529411765),
                           ('2025', 8.108108108108)]:
        assert result.figures[f'fund.calendar.{year}'].exact == pytest.approx(expected, abs=1e-9)
        assert result.figures[f'fund.discrete_12m.{year}-12-31'].exact == pytest.approx(expected, abs=1e-9)


def test_unresolved_cross_check_is_reported_without_overwriting_official_values(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / 'inputs')
    path = tmp_path / 'inputs' / 'factsheet_performance.json'
    data = json.loads(path.read_text())
    data['series']['fund_nav']['1y'] = 10.0  # price return 8.108...; discrepancy exceeds 0.3 pp
    path.write_text(json.dumps(data))
    _, _, reported, _ = pipeline(path.parent)
    flags = [f for f in reported.flags if f.check == 'cross_check']
    assert len(flags) == 1 and flags[0].level == 'warning'
    assert reported.figures['fund_nav.cum.1y'].value == 10.0
    assert reported.figures['fund_nav.cum.1y'].source == 'factsheet'
