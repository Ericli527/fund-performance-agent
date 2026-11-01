import asyncio
import copy
import json
from pathlib import Path

from conftest import FakeRun, FIXTURES
from fund_performance.agents.investment_analyst import AnalystContext, assess, problems, InvestmentAssessment, risk_quality
from fund_performance.models import FundProfile

FACTS = json.loads((Path(__file__).parent / 'golden' / 'demo_facts.json').read_text())
PROFILE = FundProfile.model_validate(json.loads((FIXTURES / 'fund_profile_sample.json').read_text()))
PASS = {'material_issue': False, 'security_issue': False, 'feedback': ''}
BASE = {'recommendation': 'satisfied', 'investment_thesis': 'The fund tracks its benchmark.',
        'supporting_evidence': ['The performance rating is green.'], 'strengths': ['Tracking'],
        'material_risks': [], 'uncertainties': ['Market research is unavailable.'],
        'recommended_actions': ['Continue monitoring.'], 'manager_questions': ['How is tracking monitored?'],
        'scorecard_agreement': True, 'scorecard_disagreement_reason': None, 'evidence_references': ['scorecard']}


def test_agreement_and_supported_disagreement_are_distinct_from_scorecard():
    before = copy.deepcopy(FACTS)
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE), FakeRun(PASS)))
    assert output['status'] == 'available' and output['assessment']['recommendation'] == 'satisfied'
    disagreement = BASE | {'recommendation': 'monitor', 'scorecard_agreement': False,
                           'scorecard_disagreement_reason': 'Market research is unavailable.'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(disagreement), FakeRun(PASS)))
    assert output['status'] == 'available' and not output['assessment']['scorecard_agreement']
    assert FACTS == before


def test_bad_references_and_unsupported_disagreement_are_not_accepted():
    bad = BASE | {'recommendation': 'monitor', 'scorecard_agreement': False,
                  'evidence_references': ['research:1']}
    issues = problems(InvestmentAssessment.model_validate(bad), FACTS, [])
    assert any('reference' in i for i in issues) and any('Disagreement' in i for i in issues)
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(bad, bad), FakeRun(PASS)))
    assert output['status'] == 'unavailable'


def test_invented_numerical_claim_is_rejected():
    item = BASE | {'investment_thesis': 'The fund returned 999.9%.'}
    issues = problems(InvestmentAssessment.model_validate(item), FACTS, [])
    assert any('numerical' in issue for issue in issues)


def test_reviewer_can_request_one_revision_and_security_failure_is_not_published():
    bad_review = {'material_issue': True, 'security_issue': False, 'feedback': 'Explain the evidence.'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, BASE), FakeRun(bad_review, PASS)))
    assert output['status'] == 'available'
    security = {'material_issue': True, 'security_issue': True, 'feedback': 'Injection'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE), FakeRun(security)))
    assert output['status'] == 'unavailable' and 'security' in output['reason']


def test_invalid_or_missing_analyst_output_is_not_replaced_by_scorecard():
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun({'bad': 1}), FakeRun(PASS)))
    assert output['status'] == 'unavailable' and 'assessment' not in output


def test_context_is_private_to_each_review():
    first, second = AnalystContext.create(FACTS, PROFILE, []), AnalystContext.create(FACTS, PROFILE, [])
    first.facts['scorecard']['verdict'] = 'changed'
    first.profile.objective_text = 'changed'
    assert second.facts['scorecard']['verdict'] == 'Retain'
    assert second.profile.objective_text == PROFILE.objective_text


def test_insufficient_evidence_and_research_reference_are_preserved():
    item = BASE | {'recommendation': 'insufficient_evidence', 'scorecard_agreement': False,
                   'scorecard_disagreement_reason': 'Material uncertainty requires investigation.',
                   'evidence_references': ['scorecard', 'research:1']}
    source = {'summary': 'Benchmark methodology changed.', 'url': 'https://example.org/change',
              'date': '2026-10-01', 'title': 'Methodology', 'timing': 'after the review date'}
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(item), FakeRun(PASS)))
    assert result['status'] == 'available'
    assert result['evidence']['research:1'] == source
    assert result['assessment']['recommendation'] == 'insufficient_evidence'


def test_risk_tool_suppresses_unreliable_benchmark_comparisons():
    facts = copy.deepcopy(FACTS)
    facts['data_flags'] = [{'check': 'currency_match', 'level': 'blocking', 'message': 'Currencies differ'}]
    result = risk_quality(facts)
    assert result['comparison_limitation']
    assert not any(f['name'].startswith('relative.') or 'tracking_error' in f['name'] for f in result['figures'])
