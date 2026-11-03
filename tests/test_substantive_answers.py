import asyncio
import copy
from html import unescape

import pytest

from conftest import FakeRun
from test_investment_analyst import BASE, FACTS, PROFILE, PASS
from fund_performance.agents.investment_analyst import assess
from fund_performance.agents.reporter import write_draft
from fund_performance.agents.judge import judge_input
from fund_performance.dashboard import _summary
from fund_performance.executive import _summary_html
from fund_performance.presentation import EvidenceQuality
from fund_performance.agents.judgement_guidance import guidance_for

ANSWER = '''The available evidence supports a preliminary positive assessment of mandate delivery. The fund seeks to track its documented global equity index using representative sampling. Over five years it returned 11.31% a year against 11.60% for the benchmark. This supports a qualified interpretation of the available tracking evidence.

The published OCF is 0.23%, which should be considered alongside the fund's implementation and delivered outcomes. That disclosure supports a discussion of charges but does not establish market competitiveness. No comparable peer factsheet is available in this review. Investor value can still be considered through the fund's own mandate, net outcomes and documented risk exposure.

Missing supplementary risk measures limit the precision of the tracking assessment rather than proving poor performance. Global equity exposure remains subject to market losses, and historical returns are not forecasts. Confirm the basis and source figures before sign-off. Obtain a comparable peer if a relative fee or competitor-value conclusion is required.'''


def test_reviewed_no_peer_judgement_reaches_reporter_and_paragraphs_survive_both_views():
    facts = copy.deepcopy(FACTS)
    facts['peers'] = []
    facts['fund']['ocf_pct'] = .23
    facts['figures'] += [{'name': 'fund_nav.ann.5y', 'value': 11.31, 'unit': '%', 'source': 'factsheet'},
                         {'name': 'index.ann.5y', 'value': 11.60, 'unit': '%', 'source': 'factsheet'}]
    profile = PROFILE.model_copy(update={'objective_text': 'Track FTSE Global All Cap using representative sampling.',
                                         'benchmark_name': 'FTSE Global All Cap'})
    facts['fund']['benchmark_name'] = profile.benchmark_name
    analyst = copy.deepcopy(BASE)
    analyst['investment_thesis'] = 'The available evidence supports a preliminary mandate assessment.'
    assessment = asyncio.run(assess(facts, profile, [], 'Assess mandate and investor value without peers.',
                                    FakeRun(analyst), FakeRun(PASS)))
    runner = FakeRun({'answer': ANSWER, 'evidence': [], 'next_step': None})
    draft = asyncio.run(write_draft(facts, 'analyst', ['Performance'], run=runner, assessment=assessment))
    assert not draft.problems and draft.answer.count('\n\n') == 2
    assert 'preliminary mandate assessment' in runner.prompts[0]
    concl = {'source': 'ai', 'answer': draft.answer, 'evidence': [], 'text': draft.text}
    html = _summary({'facts': facts | {'suggested_conclusion': concl}, 'reasons': {}}, EvidenceQuality('clear', 'Clear', ''))
    pdf = _summary_html(concl)
    assert html.count("class='fp-conclusion'") == 3
    for paragraph in ANSWER.split('\n\n'):
        assert paragraph in unescape(html) and paragraph in unescape(pdf)
    assert 'preliminary mandate assessment' in judge_input(facts, draft, assessment=assessment)


@pytest.mark.parametrize('objective,benchmark,expected', [
    ('Track FTSE Global All Cap through sampling.', 'FTSE Global All Cap', 'Passive global equity'),
    ('Track the S&P 500 NUK Index.', 'S&P 500 NUK', 'Passive US equity'),
    ('An active equity strategy seeking to outperform its index.', 'Equity Index', 'Active equity'),
    ('An unclear investment objective.', None, 'Uncertain: use the documented objective'),
])
def test_documented_strategy_selects_only_applicable_guidance(objective, benchmark, expected):
    profile = PROFILE.model_copy(update={'objective_text': objective, 'benchmark_name': benchmark})
    assert guidance_for(profile)['strategy_framework'] == expected


@pytest.mark.parametrize('fund_return,benchmark_return,interpretation,recommendation', [
    (-14.9, -15.0, 'A falling market does not itself establish poor benchmark tracking.', 'satisfied'),
    (20.0, 25.0, 'The benchmark shortfall warrants investigation despite a positive absolute return.', 'monitor'),
    (None, None, 'The disclosed charge supports fee transparency; relative competitiveness is not established.', 'satisfied'),
    (None, None, 'The unclear mandate and incompatible source evidence prevent a defensible conclusion.', 'insufficient_evidence'),
])
def test_evidence_proportionate_judgement_pipeline(fund_return, benchmark_return, interpretation, recommendation):
    facts = copy.deepcopy(FACTS)
    facts['peers'] = []
    facts['fund']['ocf_pct'] = .23
    if fund_return is not None:
        facts['figures'] += [{'name': 'scenario.fund', 'value': fund_return, 'unit': '%'},
                            {'name': 'scenario.index', 'value': benchmark_return, 'unit': '%'}]
    analyst = copy.deepcopy(BASE)
    analyst.update(recommendation=recommendation, investment_thesis=interpretation,
                   scorecard_agreement=recommendation == 'satisfied',
                   scorecard_disagreement_reason=None if recommendation == 'satisfied' else interpretation)
    analyst['evidence_references'] = ['mandate', 'scorecard']
    if recommendation == 'insufficient_evidence':
        for rating in analyst['investment_ratings']:
            rating.update(proposed_rating='MANUAL_CHECK', agreement=False, rationale=interpretation)
    profile = PROFILE.model_copy(update={'objective_text': 'Track the S&P 500 NUK Index.', 'benchmark_name': 'S&P 500 NUK'})
    if recommendation == 'insufficient_evidence':
        profile = PROFILE.model_copy(update={'objective_text': 'The investment objective is unclear.'})
        facts['data_flags'] = [{'check': 'currency_match', 'level': 'blocking', 'message': 'Fund and benchmark currencies conflict.'}]
    facts['fund']['benchmark_name'] = profile.benchmark_name
    reviewed = asyncio.run(assess(facts, profile, [], 'Review the available evidence.', FakeRun(analyst), FakeRun(PASS)))
    assert reviewed['status'] == 'available'
    assert reviewed['assessment']['recommendation'] == recommendation
    report_runner = FakeRun({'answer': interpretation + '\n\nVerify the material source evidence before sign-off.',
                             'evidence': [], 'next_step': None})
    draft = asyncio.run(write_draft(facts, 'analyst', ['Performance'], run=report_runner, assessment=reviewed))
    assert draft.answer.count('\n\n') == 1 and not draft.problems
    assert interpretation in report_runner.prompts[0]


def test_extra_answer_paragraphs_are_bounded_without_removing_financial_checks():
    from fund_performance.agents.reporter import draft_problems
    assert any('three answer paragraphs' in issue for issue in draft_problems('A.\n\nB.\n\nC.\n\nD.', FACTS))
    assert any('check:' in issue for issue in draft_problems('The fund returned 999.9%.', FACTS))


def test_supported_ai_view_remains_available_with_check_data_scorecard():
    facts = copy.deepcopy(FACTS)
    facts['scorecard']['verdict'] = 'Pending data check'
    facts['scorecard']['pillars'][1]['rating'] = 'CHECK DATA'
    item = copy.deepcopy(BASE)
    item.update(scorecard_agreement=False,
                scorecard_disagreement_reason='A preliminary view is supported despite an incomplete quantitative check.')
    item['investment_ratings'][1].update(quantitative_scorecard_rating='CHECK DATA', agreement=False)
    output = asyncio.run(assess(facts, PROFILE, [], 'Give a preliminary view.', FakeRun(item), FakeRun(PASS)))
    assert output['assessment']['recommendation'] == 'satisfied'
    runner = FakeRun({'answer': 'The evidence supports a preliminary view.\n\nComplete the material data checks before sign-off.',
                      'evidence': [], 'next_step': None})
    draft = asyncio.run(write_draft(facts, 'analyst', ['Performance'], run=runner, assessment=output))
    assert not draft.problems and 'preliminary view' in draft.answer
    assert 'CHECK DATA' in runner.prompts[0]
