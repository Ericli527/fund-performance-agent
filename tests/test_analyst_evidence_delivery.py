import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from agents.usage import Usage

from conftest import FakeRun
from test_investment_analyst import BASE, FACTS, PROFILE, PASS
from fund_performance.agents.investment_analyst import (analyst_agent, assess, investment_evidence_package,
                                                       normalise_mechanical_fields, InvestmentAssessment)
from fund_performance.agents.base import AI_CALLS


@pytest.mark.parametrize('state', ['complete', 'missing_peer', 'failed_peer', 'missing_risk', 'missing_period', 'incompatible'])
def test_complete_detached_package_uses_existing_evidence_with_explicit_gaps(state):
    facts = copy.deepcopy(FACTS)
    if state in ('missing_peer', 'failed_peer'):
        facts['peers'] = []
    if state == 'failed_peer':
        facts['data_flags'] = [{'check': 'peers', 'level': 'warning', 'message': 'Peer factsheet example.pdf: extraction failed.'}]
    if state == 'missing_risk':
        facts['figures'] = [f for f in facts['figures'] if not any(x in f['name'] for x in ('r2', 'beta', 'tracking_error'))]
    if state == 'missing_period':
        facts['figures'] = [f for f in facts['figures'] if not f['name'].endswith('3y')]
    if state == 'incompatible':
        facts['data_flags'] = [{'check': 'currency_match', 'level': 'blocking', 'message': 'Fund/benchmark currency mismatch.'}]
    before = copy.deepcopy(facts)
    source = {'summary': 'Dated context with limited period coverage.', 'date': '2026-09-01'}
    package = investment_evidence_package(facts, PROFILE, [source])
    catalogue = package['evidence_catalogue']
    assert {'mandate', 'fund_context', 'scorecard', 'peers', 'risk_quality', 'performance:5y', 'research:1'} <= set(catalogue)
    assert catalogue['research:1'] == source and package['fund_identity_and_terms']['currency'] == PROFILE.currency
    if state in ('missing_peer', 'failed_peer'):
        assert catalogue['peers']['status'] == 'not_available'
    if state == 'failed_peer':
        assert 'extraction failed' in catalogue['peers']['extraction_or_comparability_notes'][0]['message']
    if state == 'missing_risk':
        assert not any(x in f['name'] for f in catalogue['risk_quality']['figures'] for x in ('r2', 'beta', 'tracking_error'))
    if state in ('missing_period', 'incompatible'):
        row = catalogue['performance:3y' if state == 'missing_period' else 'performance:5y']
        assert row['benchmark_return_a_year'] is None and row['unavailable']
    catalogue['scorecard']['ratings'].clear()
    assert facts == before


def test_single_response_needs_no_tools_or_mechanical_revision_and_keeps_audit():
    raw = copy.deepcopy(BASE)
    raw['scorecard_agreement'] = False
    raw['evidence_references'] = [' [scorecard] ']
    for rating in raw['investment_ratings']:
        rating.update(agreement=None, quantitative_scorecard_rating='incorrect copied value')
    analyst, reviewer, audit = FakeRun(raw), FakeRun(PASS), []
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', analyst, reviewer, audit_outputs=audit))
    assert output['status'] == 'available' and output['tool_calls'] == []
    assert not analyst_agent().tools and len(analyst.prompts) == len(reviewer.prompts) == 1
    assert output['assessment']['scorecard_agreement'] is True and output['assessment']['evidence_references'] == ['scorecard']
    assert output['assessment']['recommendation'] == raw['recommendation']
    assert audit == [raw] and audit[0]['investment_ratings'][0]['quantitative_scorecard_rating'] == 'incorrect copied value'
    attempt = output['diagnostics']['attempts'][0]
    assert attempt['normalised_fields'] and attempt['successful_tool_calls'] == attempt['refused_tool_calls'] == 0
    assert not output['diagnostics']['revision_required']
    assert 'incorrect copied value' not in json.dumps(output['diagnostics'])


def test_real_disagreement_is_retained_and_requires_substantive_explanation():
    item = copy.deepcopy(BASE)
    item.update(recommendation='monitor', scorecard_agreement=True,
                scorecard_disagreement_reason='Material investment uncertainty warrants monitoring.')
    out, changes = normalise_mechanical_fields(InvestmentAssessment.model_validate(item), FACTS, [])
    assert out.recommendation == 'monitor' and out.scorecard_agreement is False and 'scorecard_agreement' in changes
    unknown = copy.deepcopy(BASE)
    unknown['evidence_references'] = ['The return comes from performance:5y', 'research:99']
    out, _ = normalise_mechanical_fields(InvestmentAssessment.model_validate(unknown), FACTS, [])
    assert out.evidence_references == unknown['evidence_references']


def test_actual_sdk_usage_is_retained_in_attempt_diagnostics():
    async def analyst(agent, prompt):
        return SimpleNamespace(final_output=BASE, raw_responses=[SimpleNamespace(
            usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120), output=[])])
    calls = []
    token = AI_CALLS.set(calls)
    try:
        result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', analyst, FakeRun(PASS)))
    finally:
        AI_CALLS.reset(token)
    usage = result['diagnostics']['attempts'][0]['usage'][0]
    assert usage['model_requests'] == 1 and usage['tokens']['input_tokens'] == 100


@pytest.mark.parametrize('name,fund_return,index_return,charge', [
    ('Illustrative Fidelity-like tracker', 13.8, 13.9, .06),
    ('Illustrative Vanguard-like tracker', 11.31, 11.60, .23),
])
def test_displayed_failure_context_is_delivered_in_one_response_without_peers(name, fund_return, index_return, charge):
    facts = copy.deepcopy(FACTS)
    facts['peers'] = []
    facts['fund'].update(fund_name=name, ocf_pct=charge)
    replacements = {'fund_nav.ann.5y': fund_return, 'index.ann.5y': index_return}
    for figure in facts['figures']:
        if figure['name'] in replacements:
            figure.update(value=replacements[figure['name']], display=f"{replacements[figure['name']]:.2f}%")
    profile = PROFILE.model_copy(update={'fund_name': name, 'ocf_pct': charge})
    raw = copy.deepcopy(BASE)
    raw['scorecard_agreement'] = None
    raw['investment_thesis'] = 'The available performance evidence supports a preliminary interpretation.'
    analyst, reviewer = FakeRun(raw), FakeRun(PASS)
    result = asyncio.run(assess(facts, profile, [], 'Review', analyst, reviewer))
    assert result['status'] == 'available' and result['tool_calls'] == []
    package = json.loads(analyst.prompts[0][analyst.prompts[0].index('{'):])
    assert package['evidence_catalogue']['performance:5y']['fund_return_a_year']['value'] == fund_return
    assert package['fund_identity_and_terms']['ocf_pct'] == charge
    assert package['evidence_catalogue']['peers']['status'] == 'not_available'
    assert len(analyst.prompts) == len(reviewer.prompts) == 1
