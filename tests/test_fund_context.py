"""Synthetic document evidence, provenance and reuse across the review."""
import asyncio
from conftest import FakeRun
from fund_performance.agents.extractor import ExtractedReturnEvidence
from fund_performance.calc import CalcResult
from fund_performance.config import load_thresholds
from fund_performance.fund_context import recover_returns
from fund_performance.intake import read_documents
from fund_performance.models import FactsheetPerformance
from fund_performance.precedence import apply_precedence
from fund_performance.report import fmt
from test_intake import FACTSHEET, MANDATE, extractor_answer
from test_investment_analyst import PROFILE


def test_intake_combines_document_summary_mandate_and_recovered_return(tmp_path):
    quote = '3 year cumulative fund NAV return GBP 30.5%'
    path = tmp_path / 'fund.txt'
    path.write_text(FACTSHEET + '\nIndex Fund Technology 25.0%\n' + quote)
    answer = extractor_answer() | {
        'document_summary': 'The fund tracks a global index. Technology is 25.0% (fund.txt).',
        'exposures': [{'category': 'sectors', 'name': 'Technology', 'weight_pct': 25.0,
                       'quote': 'Index Fund Technology 25.0%', 'subject': 'fund'}],
        'return_evidence': [{'series': 'fund_nav', 'period': '3y', 'basis': 'cumulative',
                             'currency': 'GBP', 'value': 30.5, 'quote': quote}]}
    answer['series'][0]['y3'] = None
    mandate = MANDATE | {'interpretation': 'The fund seeks to track its index before fees (fund.txt).'}
    runner = FakeRun(mandate)
    intake = asyncio.run(read_documents(path, run_extractor=FakeRun(answer), run_mandate=runner))
    context = intake['fund_context']
    assert 'global index' in context['document_summary'] and 'track its index' in context['mandate_interpretation']
    assert 'Technology' in runner.prompts[0] and 'fund.txt, page 1' in runner.prompts[0]
    assert context['portfolio_exposures']['sectors'][0]['weight_pct'] == 25.0
    assert context['recovered_returns'][0]['evidence_level'] == 'provisional'
    assert next(row for row in intake['rows'] if row['key'] == 'series.fund_nav.3y')['source'] == 'fund.txt, page 1'
    fs = FactsheetPerformance.model_validate(intake['factsheet'])
    assert fs.series['fund_nav'].y3 == 30.5 and 'fund_nav.cum.3y' in fs.provisional_returns
    reported = apply_precedence(CalcResult(), [], PROFILE, load_thresholds(), fs)
    assert reported.figures['fund_nav.cum.3y'].source == 'ai_extracted'
    assert reported.figures['fund_nav.ann.3y'].source == 'calculated_provisional'
    assert reported.figures['comparison.td.3y'].source == 'calculated_provisional'
    assert 'please verify' in fmt('fund_nav.ann.3y', reported.figures['fund_nav.ann.3y'])


def test_recovery_does_not_accept_unsourced_or_ambiguous_returns():
    fs = FactsheetPerformance.model_validate({'as_of_date': '2026-09-30', 'currency': 'GBP',
                                               'source': 'ai_extracted', 'series': {}})
    item = ExtractedReturnEvidence(series='fund_nav', period='3y', basis='cumulative', currency='GBP',
                                   value=30.5, quote='3 year cumulative fund NAV return GBP 30.5%')
    for text in (item.quote, '30.09.2026 Benchmark return GBP 30.5%',
                 '30.09.2026 ' + item.quote.replace('30.5%', '31.5%')):
        result, found = recover_returns(fs, [item], {'fund.pdf': [text]})
        assert not found and not result.series


def test_recovery_rejects_conflicting_quoted_values():
    fs = FactsheetPerformance.model_validate({'as_of_date': '2026-09-30', 'currency': 'GBP',
                                               'source': 'ai_extracted', 'series': {}})
    first = ExtractedReturnEvidence(series='fund_nav', period='3y', basis='cumulative', currency='GBP',
                                    value=30.5, quote='3 year cumulative fund NAV return GBP 30.5%')
    second = first.model_copy(update={'value': 31.5, 'quote': first.quote.replace('30.5%', '31.5%')})
    result, found = recover_returns(fs, [first, second],
                                    {'fund.pdf': ['30.09.2026 ' + first.quote + ' ' + second.quote]})
    assert not found and not result.series


def test_controller_reuses_context_for_planning_research_and_analyst(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from fund_performance import controller
    from test_controller import mocked
    from test_investment_analyst import BASE, PASS
    brief = {'document_summary': 'The fund follows a global index.', 'sources': ['fund.pdf'],
             'summary_evidence_level': 'provisional'}
    captured = {}
    original = controller.plan_tasks
    async def record(*args, **kwargs):
        captured['planner_context'] = kwargs.get('fund_context')
        return await original(*args, **kwargs)
    monkeypatch.setattr(controller, 'plan_tasks', record)
    runners = mocked()
    runners.investment_analyst, runners.investment_reviewer = FakeRun(BASE), FakeRun(PASS)
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    result = asyncio.run(controller.run_review(sample, out_root=tmp_path, runners=runners,
                         intake={'fund_context': brief, 'documents': [], 'rows': [], 'flags': []}))
    assert captured['planner_context'] == brief
    assert json.loads((result.run_dir / 'fund_context.json').read_text()) == brief
    assert runners.search.prompts and 'global index' in runners.search.prompts[0]
    assert runners.investment_reviewer.prompts and 'global index' in runners.investment_reviewer.prompts[0]
