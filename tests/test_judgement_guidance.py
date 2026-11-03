"""Mocked delivery of strategy evidence to the existing Analyst and independent reviewer."""
import asyncio
import copy
import json

import pytest

from conftest import FakeRun
from test_investment_analyst import BASE, FACTS, PROFILE, PASS
from fund_performance.agents.investment_analyst import analyst_agent, reviewer_agent, assess


@pytest.mark.parametrize('objective,benchmark', [
    ('Track the S&P 500 NUK through passive US equity investment.', 'S&P 500 NUK'),
    ('Track FTSE Global All Cap using representative sampling.', 'FTSE Global All Cap'),
    ('Track a government bond total-return index with specified duration exposure.', 'Government Bond Index'),
    ('Maintain a balanced equity and bond allocation within the documented target risk.', 'Published Balanced Reference'),
])
@pytest.mark.parametrize('peer_state', ['not_supplied', 'unreadable'])
def test_strategy_and_evidence_reach_both_agents_without_requiring_a_peer(objective, benchmark, peer_state):
    facts = copy.deepcopy(FACTS)
    facts['peers'] = []
    facts['fund']['benchmark_name'] = benchmark
    facts['data_flags'] = ([{'check': 'peers', 'level': 'warning', 'message':
        'Approved peer factsheet example.pdf: extraction failed; no peer figures available.'}]
        if peer_state == 'unreadable' else [])
    profile = PROFILE.model_copy(update={'objective_text': objective, 'benchmark_name': benchmark})
    item = copy.deepcopy(BASE)
    item['investment_thesis'] = objective + ' A preliminary assessment is supported by the available fund evidence.'
    item['evidence_references'] = ['mandate', 'performance:5y', 'peers']
    item['uncertainties'] = ['Relative market competitiveness is not established without comparable peer evidence.']
    for rating in item['investment_ratings']:
        rating['evidence_references'] = ['mandate', 'scorecard']
        rating['limitations'] = ['Relative competitiveness is not established.']
    analyst, reviewer = FakeRun(item), FakeRun(PASS)
    before = copy.deepcopy(facts)
    output = asyncio.run(assess(facts, profile, [], 'Assess each pillar independently.', analyst, reviewer))
    assert output['status'] == 'available'
    assert output['assessment']['investment_ratings'] == item['investment_ratings']
    assert facts == before and len(analyst.prompts) == len(reviewer.prompts) == 1
    assert objective in analyst.prompts[0] and benchmark in analyst.prompts[0]
    reviewed = json.loads(reviewer.prompts[0])
    assert reviewed['mandate'] and reviewed['facts']['peers'] == []
    assert reviewed['facts']['data_flags'] == facts['data_flags']
    assert output['assessment']['human_review_required']


def test_both_existing_agents_receive_strategy_rubric_without_fee_example_authority():
    for agent in (analyst_agent(), reviewer_agent()):
        prompt = agent.instructions
        for strategy in ('Passive US equity', 'Passive global equity', 'Active equity',
                         'Government or investment-grade bonds', 'Active credit', 'Multi-asset',
                         'Money market', 'Absolute-return or alternatives'):
            assert strategy in prompt
        assert 'not approved policy or automatic thresholds' in prompt
        assert 'Missing peers or secondary risk metrics alone do not justify AMBER or RED' in prompt
        assert '0.06%' not in prompt and '0.23%' not in prompt
        assert 'not an uploaded peer' in prompt
