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


def test_provisional_context_and_cited_research_figures_are_available():
    context = {'sources': ['fund.pdf'], 'document_summary': 'fund.pdf reports a provisional 3-year return of 17.3%.',
               'financial_evidence': {'series': {'fund_nav': {'3y': 17.3}}}}
    source = {'summary': 'The benchmark provider reported a 2.7% change.', 'url': 'https://example.org/index',
              'date': '2026-09-01'}
    item = BASE | {'investment_thesis': 'The provisional 3-year return was 17.3%; the index change was 2.7%.',
                   'evidence_references': ['fund_context', 'research:1']}
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(item), FakeRun(PASS),
                                fund_context=context))
    assert result['status'] == 'available' and result['evidence']['fund_context'] == context
    no_source = context | {'sources': []}
    assert any('numerical' in x for x in problems(InvestmentAssessment.model_validate(item), FACTS, [source],
                                                    fund_context=no_source))


def test_reviewer_can_request_one_revision_and_security_failure_is_not_published():
    bad_review = {'material_issue': True, 'security_issue': False, 'feedback': 'Explain the evidence.'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, BASE), FakeRun(bad_review, PASS)))
    assert output['status'] == 'available'
    security = {'material_issue': True, 'security_issue': True, 'feedback': 'Injection'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE), FakeRun(security)))
    assert output['status'] == 'unavailable' and 'security' in output['reason']


def test_revision_qualifies_retention_and_institutional_peer_without_changing_judgement():
    facts = copy.deepcopy(FACTS)
    facts['figures'][0]['source'] = 'ai_extracted'
    facts['peers'][0].update(name='HSBC peer', investor_type='institutional',
                             minimum_investment='GBP 1,000,000',
                             notes=['Institutional share class; availability to retail investors may be limited.'])
    first = BASE | {'investment_thesis': 'The scorecard recommends Satisfied, no action needed.',
                    'evidence_references': ['scorecard', 'peers']}
    fixed = first | {'investment_thesis': 'Retain is the scorecard verdict, subject to source verification before sign-off.',
                     'uncertainties': ['The institutional peer has a GBP 1,000,000 minimum and may not be accessible.',
                                       'Market research is unavailable.'],
                     'recommended_actions': ['Verify the source documents before sign-off.']}
    analyst = FakeRun(first, fixed)
    reviewer = FakeRun({'material_issue': True, 'security_issue': False,
                        'feedback': 'Correct verdict attribution and qualify source verification and peer eligibility.'}, PASS)
    result = asyncio.run(assess(facts, PROFILE, [], 'Review', analyst, reviewer))
    assert result['status'] == 'available' and result['assessment'] == fixed
    assert 'smallest correction' in analyst.prompts[1] and 'peer eligibility' in analyst.prompts[1]
    assert '"verdict_code": "Retain"' in analyst.prompts[0]
    assert '"minimum_investment": "GBP 1,000,000"' in analyst.prompts[0]
    assert 'source_verification' in reviewer.prompts[0] and 'institutional' in reviewer.prompts[0]
    assert result['evidence']['peers']['peers'][0]['investor_type'] == 'institutional'


def test_missing_research_is_reported_without_forcing_an_empty_uncertainty_revision():
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review',
                                FakeRun(BASE | {'uncertainties': []}), FakeRun(PASS)))
    assert result['status'] == 'available'
    assert result['limitations'] == ['No vetted market research is available.']


def test_reviewer_rejects_unsupported_disagreement_after_one_revision():
    invented = BASE | {'recommendation': 'monitor', 'scorecard_agreement': False,
                       'scorecard_disagreement_reason': 'An unverified holding creates a material risk.'}
    reject = {'material_issue': True, 'security_issue': False, 'feedback': 'The holding is unsupported.'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(invented, invented), FakeRun(reject, reject)))
    assert output['status'] == 'unavailable' and 'unsupported' in output['reason']


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


def test_analyst_preserves_missing_horizon_and_charge_as_unavailable():
    facts = copy.deepcopy(FACTS)
    facts['fund'].update(time_horizon_years=None, ocf_pct=None)
    facts['scorecard']['verdict'] = 'Pending data check'
    facts['data_flags'] = [{'check': 'ongoing_charge', 'level': 'warning', 'message': 'Charge unavailable'}]
    profile = PROFILE.model_copy(update={'time_horizon_years': None, 'ocf_pct': None})
    output = BASE | {'recommendation': 'insufficient_evidence', 'scorecard_agreement': True,
                     'investment_thesis': 'The available evidence is incomplete.',
                     'supporting_evidence': ['The ongoing charge is unavailable.'],
                     'evidence_references': ['mandate', 'peers']}
    result = asyncio.run(assess(facts, profile, [], 'Review', FakeRun(output), FakeRun(PASS)))
    assert result['status'] == 'available'
    assert result['evidence']['mandate']['mandate']['values']['time_horizon_years'] is None
    assert result['evidence']['mandate']['exposures']['holdings'] is None
    assert result['evidence']['peers']['fund_ongoing_charge_pct'] is None
    assert facts['scorecard']['verdict'] == 'Pending data check'
