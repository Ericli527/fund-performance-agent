import asyncio
import copy
import json
from pathlib import Path

from conftest import FakeRun, FIXTURES
from fund_performance.agents.investment_analyst import (AnalystContext, assess, problems, InvestmentAssessment,
                                                        research_availability, risk_quality)
from fund_performance.models import FundProfile

FACTS = json.loads((Path(__file__).parent / 'golden' / 'demo_facts.json').read_text())
PROFILE = FundProfile.model_validate(json.loads((FIXTURES / 'fund_profile_sample.json').read_text()))
PASS = {'material_issue': False, 'security_issue': False, 'feedback': ''}
BASE = {'recommendation': 'satisfied', 'investment_thesis': 'The fund tracks its benchmark.',
        'supporting_evidence': ['The performance rating is green.'], 'strengths': ['Tracking'],
        'material_risks': [], 'uncertainties': ['Market research is unavailable.'],
        'recommended_actions': ['Continue monitoring.'], 'manager_questions': ['How is tracking monitored?'],
        'scorecard_agreement': True, 'scorecard_disagreement_reason': None, 'evidence_references': ['scorecard'],
        'human_review_required': True,
        'investment_ratings': [{'dimension': p['name'], 'proposed_rating': p['rating'] if p['rating'] in
                                ('GREEN', 'AMBER', 'RED', 'MANUAL_CHECK') else 'MANUAL_CHECK',
                                'quantitative_scorecard_rating': p['rating'],
                                'agreement': p['rating'] in ('GREEN', 'AMBER', 'RED', 'MANUAL_CHECK'),
                                'rationale': 'Consider the evidence and its limitations.',
                                'supporting_evidence': ['scorecard'], 'limitations': [],
                                'further_review_required': True} for p in FACTS['scorecard']['pillars']]}


def test_agreement_and_supported_disagreement_are_distinct_from_scorecard():
    before = copy.deepcopy(FACTS)
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE), FakeRun(PASS)))
    assert output['status'] == 'available' and output['assessment']['recommendation'] == 'satisfied'
    disagreement = BASE | {'recommendation': 'monitor', 'scorecard_agreement': False,
                           'scorecard_disagreement_reason': 'Market research is unavailable.'}
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(disagreement), FakeRun(PASS)))
    assert output['status'] == 'available' and not output['assessment']['scorecard_agreement']
    assert FACTS == before


def test_rating_disagreement_is_preserved_and_reviewed_against_evidence():
    item = copy.deepcopy(BASE)
    rating = item['investment_ratings'][0]
    rating.update(proposed_rating='AMBER' if rating['quantitative_scorecard_rating'] != 'AMBER' else 'GREEN',
                  agreement=False, rationale='The available evidence warrants a different investment judgement.',
                  supporting_evidence=['mandate', 'risk_quality'], limitations=['Tracking error is unavailable.'])
    reviewer, audit = FakeRun(PASS), []
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(item), reviewer, audit_outputs=audit))
    assert output['status'] == 'available' and output['assessment']['investment_ratings'] == item['investment_ratings']
    assert audit == [item] and json.loads(reviewer.prompts[0])['assessment']['investment_ratings'] == item['investment_ratings']
    assert {'mandate', 'risk_quality'} <= set(output['evidence'])


def test_ratings_require_all_dimensions_authentic_scorecard_and_known_evidence():
    item = copy.deepcopy(BASE)
    item['investment_ratings'][0]['supporting_evidence'] = ['research:99']
    item['investment_ratings'][1]['quantitative_scorecard_rating'] = 'RED'
    item['investment_ratings'][2]['dimension'] = item['investment_ratings'][3]['dimension']
    issues = problems(InvestmentAssessment.model_validate(item), FACTS, [])
    assert 'Unknown evidence reference' in issues
    assert 'Exactly four distinct investment rating dimensions are required' in issues


def test_invented_number_in_rating_is_rejected():
    item = copy.deepcopy(BASE)
    item['investment_ratings'][0]['rationale'] = 'The fund returned 999.9%.'
    assert any('numerical' in issue for issue in problems(InvestmentAssessment.model_validate(item), FACTS, []))


def test_quality_reviewer_can_withhold_unsupported_green_rating():
    item = copy.deepcopy(BASE)
    item['investment_ratings'][0].update(proposed_rating='GREEN',
        agreement=item['investment_ratings'][0]['quantitative_scorecard_rating'] == 'GREEN',
        rationale='The mandate is fully met.')
    feedback = {'material_issue': True, 'security_issue': False,
                'feedback': 'The proposed green mandate rating is unsupported; tracking evidence is missing.',
                'recommendation_supported': True, 'supported_fields': ['investment_thesis']}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(item, item), FakeRun(feedback, feedback)))
    assert result['status'] == 'partial'
    assert 'investment_ratings' not in result['assessment']


def test_bad_references_and_unsupported_disagreement_are_not_accepted():
    bad = BASE | {'recommendation': 'monitor', 'scorecard_agreement': False,
                  'evidence_references': ['research:1']}
    issues = problems(InvestmentAssessment.model_validate(bad), FACTS, [])
    assert any('reference' in i for i in issues) and any('Disagreement' in i for i in issues)
    output = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(bad, bad), FakeRun(PASS)))
    assert output['status'] == 'partial' and output['assessment']['recommendation'] is None


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
                   'uncertainties': ['The source is limited.'],
                   'evidence_references': ['fund_context', 'research:1']}
    reviewer = FakeRun(PASS)
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(item), reviewer,
                                fund_context=context))
    assert result['status'] == 'available' and result['review_status'] == 'qualified_draft'
    assert result['evidence']['fund_context'] == context
    review_evidence = json.loads(reviewer.prompts[0])
    assert review_evidence['fund_context'] == review_evidence['cited_evidence']['fund_context'] == context
    assert review_evidence['sources'] == [source] and review_evidence['cited_evidence']['research:1'] == source
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
    assert output['status'] == 'partial' and output['assessment']['recommendation'] is None
    assert 'unsupported' in output['reason'] and 'investment_thesis' not in output['assessment']


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
                   'evidence_references': ['scorecard', 'research:1'], 'uncertainties': ['Evidence is limited.']}
    source = {'summary': 'Benchmark methodology changed.', 'url': 'https://example.org/change',
              'date': '2026-10-01', 'title': 'Methodology', 'timing': 'after the review date'}
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(item), FakeRun(PASS)))
    assert result['status'] == 'available'
    assert result['evidence']['research:1'] == source
    assert result['assessment']['recommendation'] == 'insufficient_evidence'


def test_research_availability_distinguishes_absent_excluded_and_partial_sources():
    assert research_availability(PROFILE, [], {'completed': True})['status'] == 'no_usable_research_retrieved'
    assert research_availability(PROFILE, [], {'candidate_count': 2, 'excluded_count': 2})['status'] == 'retrieved_but_excluded'
    assert research_availability(PROFILE, [], {'completed': True, 'retrieved_pages': 1})['status'] == 'retrieved_without_usable_summary'
    sources = [
        {'topic': 'fund_news', 'approved': True, 'date': '2026-10-15', 'date_basis': 'as_at',
         'summary': 'Fidelity fund page.', 'limitations': 'Published after the review.'},
        {'topic': 'fund_news', 'approved': True, 'date': '2026-11-01', 'date_basis': 'published',
         'summary': 'Fidelity manager page.', 'limitations': 'Later publication.'},
        {'topic': 'market_drivers', 'date': '2026-06-30', 'date_basis': 'published',
         'summary': 'Market commentary.', 'limitations': 'Only covers one quarter.'},
        {'topic': 'market_drivers', 'date': '2026-09-15', 'date_basis': 'published',
         'summary': 'Market commentary.', 'limitations': 'Limited period coverage.'}]
    summary = research_availability(PROFILE, sources, {'candidate_count': 5, 'excluded_count': 1})
    assert summary['status'] == 'vetted_sources_available' and summary['vetted_source_count'] == 4
    assert [s['date_relation'] for s in summary['sources']] == ['after_review', 'after_review', 'during_review', 'during_review']
    assert summary['sources'][2]['limitations'] == 'Only covers one quarter.'
    assert 'not proof of complete period coverage' in summary['qualification']


def test_false_missing_research_claim_is_corrected_without_losing_judgement():
    sources = [{'topic': 'fund_news', 'approved': True, 'date': day, 'summary': 'Fidelity fund page.',
                'limitations': 'Published after the review.'} for day in ('2026-10-15', '2026-11-01')]
    sources += [{'topic': 'market_drivers', 'date': day, 'summary': 'Market commentary.',
                 'limitations': 'Only partial period coverage.'} for day in ('2026-06-30', '2026-09-15')]
    first = BASE | {'uncertainties': ['Research evidence could not be retrieved.'],
                    'recommended_actions': ['Verify sources before sign-off.']}
    fixed = first | {'uncertainties': ['Two fund pages were published after the review; market commentary has partial coverage.']}
    analyst, reviewer = FakeRun(first, fixed), FakeRun(PASS)
    output = asyncio.run(assess(FACTS, PROFILE, sources, 'Review', analyst, reviewer,
                                research_state={'attempted': True, 'completed': True, 'candidate_count': 4,
                                                'excluded_count': 0}))
    assert output['status'] == 'available' and output['assessment']['recommendation'] == 'satisfied'
    assert output['assessment']['recommended_actions'] == ['Verify sources before sign-off.']
    assert '"vetted_source_count": 4' in analyst.prompts[0] and '"date_relation": "after_review"' in analyst.prompts[0]
    assert 'correct the claim' in analyst.prompts[1] and len(reviewer.prompts) == 1
    assert output['diagnostics']['attempts'][0]['validation_issues'] and output['diagnostics']['attempts'][1]['review'] == 'accepted'


def test_reviewer_can_request_narrow_date_qualification_after_research_was_supplied():
    sources = [{'date': '2026-10-15', 'topic': 'fund_news', 'summary': 'Later fund page.',
                'limitations': 'Published after the review.'}]
    initial = BASE | {'uncertainties': ['No research was available before the review date.'],
                      'recommended_actions': ['Verify sources before sign-off.']}
    revised = initial | {'uncertainties': ['The fund page was published after the review date.']}
    reviewer = FakeRun({'material_issue': True, 'security_issue': False,
                        'feedback': 'Clarify the publication date and historical coverage.'}, PASS)
    analyst = FakeRun(initial, revised)
    result = asyncio.run(assess(FACTS, PROFILE, sources, 'Review', analyst, reviewer))
    assert result['status'] == 'available' and result['assessment']['recommendation'] == 'satisfied'
    assert result['assessment']['recommended_actions'] == ['Verify sources before sign-off.']
    assert result['diagnostics']['attempts'][0]['review'] == 'material_issue'
    assert result['diagnostics']['attempts'][1]['review'] == 'accepted'
    assert 'smallest correction' in analyst.prompts[1]


def test_reviewer_feedback_and_unavailable_reason_are_logged_without_source_text():
    feedback = 'PRIVATE SOURCE PASSAGE: research evidence was unavailable; the publication date needs correction.'
    reviewer = FakeRun(*[{'material_issue': True, 'security_issue': False, 'feedback': feedback}] * 2)
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, BASE), reviewer))
    assert result['status'] == 'partial' and result['assessment']['recommendation'] is None
    assert 'PRIVATE SOURCE PASSAGE' not in json.dumps(result)
    assert result['diagnostics']['final_reason'] == 'unresolved_reviewer_issue_after_revision'
    assert len(result['diagnostics']['attempts']) == 2
    assert set(result['diagnostics']['attempts'][0]['feedback_categories']) >= {'research_availability', 'date_or_coverage'}


def test_repeated_false_availability_claim_records_validation_failure():
    source = {'date': '2026-09-01', 'summary': 'Market evidence.', 'limitations': 'Partial coverage.'}
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(BASE, BASE), FakeRun(PASS)))
    assert result['status'] == 'partial' and result['assessment']['recommendation'] is None
    assert result['diagnostics']['final_reason'] == 'validation_failed_after_revision'
    assert result['diagnostics']['attempts'][1]['validation_issues'] == ['false_missing_research']
    assert result['diagnostics']['attempts'][1]['review'] == 'not_run'


def test_absolute_research_absence_is_not_excused_by_a_later_coverage_caveat():
    from fund_performance.agents.investment_analyst import missing_research_claim
    assert missing_research_claim('Research evidence could not be retrieved, and period coverage is limited.')
    assert not missing_research_claim('No research was available before the review date.')


def test_positive_research_availability_is_not_misclassified_as_absent():
    from fund_performance.agents.investment_analyst import missing_research_claim
    assert not missing_research_claim('Research was available, but its historical coverage was limited.')
    assert not missing_research_claim('Research is available for the review.')
    assert not missing_research_claim('No research was available for a particular claim.')
    assert missing_research_claim('Research was not available.')
    assert missing_research_claim('Research was unavailable.')
    source = {'date': '2026-09-01', 'summary': 'Market context.', 'limitations': 'Partial coverage.'}
    assessment = BASE | {'uncertainties': ['Research was available, but coverage was limited.']}
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'Review', FakeRun(assessment), FakeRun(PASS)))
    assert result['status'] == 'available' and result['review_status'] == 'qualified_draft'
    assert result['assessment']['recommendation'] == 'satisfied'


def test_supported_assessment_is_approved_and_reviewer_sees_cited_evidence():
    source = {'date': '2026-09-01', 'summary': 'Market context.'}
    assessment = BASE | {'uncertainties': [], 'evidence_references': ['scorecard', 'performance:5y', 'research:1']}
    reviewer = FakeRun(PASS)
    result = asyncio.run(assess(FACTS, PROFILE, [source], 'What matters?', FakeRun(assessment), reviewer))
    prompt = json.loads(reviewer.prompts[0])
    assert result['status'] == 'available' and result['review_status'] == 'reviewed'
    assert prompt['question'] == 'What matters?'
    assert 'performance:5y' in prompt['cited_evidence'] and prompt['cited_evidence']['research:1'] == source
    assert 'facts' in prompt and 'fund_context' in prompt and prompt['previous_review'] is None


def test_second_reviewer_sees_revision_context_and_diagnostics_are_actionable():
    correction = {'material_issue': True, 'security_issue': False,
                  'feedback': 'Qualify the institutional peer eligibility.'}
    reviewer = FakeRun(correction, PASS)
    revised = BASE | {'uncertainties': ['The institutional peer may not be accessible.']}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, revised), reviewer))
    second = json.loads(reviewer.prompts[1])
    assert result['status'] == 'available' and result['review_status'] == 'qualified_draft'
    assert second['previous_review']['feedback'] == correction['feedback']
    assert second['assessment']['uncertainties'] == revised['uncertainties']

    invalid = BASE | {'investment_thesis': 'The fund returned 999.9%.'}
    analyst = FakeRun(invalid, invalid)
    rejected = asyncio.run(assess(FACTS, PROFILE, [], 'Review', analyst, FakeRun(PASS)))
    assert rejected['status'] == 'partial' and rejected['assessment']['recommendation'] is None
    assert 'numerical claim' in rejected['reason']
    assert '999.9%' in analyst.prompts[1] and '999.9%' not in json.dumps(rejected)


def test_controller_persists_redacted_diagnostics_for_both_attempts(tmp_path):
    from fund_performance.config import load_settings
    from fund_performance.controller import run_review
    from test_controller import mocked
    secret = 'PRIVATE SOURCE PASSAGE research publication date is incorrect'
    runners = mocked()
    runners.investment_analyst = FakeRun(BASE, BASE)
    runners.investment_reviewer = FakeRun(*[{'material_issue': True, 'security_issue': False, 'feedback': secret}] * 2)
    settings = load_settings().model_copy(deep=True)
    settings.research.enabled = False
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    result = asyncio.run(run_review(sample, out_root=tmp_path, runners=runners, settings=settings))
    log_text = (result.run_dir / 'log.json').read_text()
    log = json.loads(log_text)
    step = next(s for s in log['steps'] if s['step'] == 'investment_assessment')
    diagnostic = step['outputs']['diagnostics']
    assert secret not in log_text and diagnostic['final_reason'] == 'unresolved_reviewer_issue_after_revision'
    assert len(diagnostic['attempts']) == 2 and diagnostic['attempts'][0]['feedback_summary']


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


def test_unresolved_provisional_warning_keeps_explicitly_supported_recommendation():
    assessment = BASE | {'investment_thesis': 'Verified performance tools show a sound result.',
                         'supporting_evidence': ['The performance rating is green.'],
                         'uncertainties': ['Performance evidence is provisional.']}
    review = {'material_issue': True, 'security_issue': False,
              'feedback': 'Use provisional performance evidence and verify before sign-off.',
              'recommendation_supported': True,
              'supported_fields': ['supporting_evidence', 'uncertainties']}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(assessment, assessment), FakeRun(review, review)))
    assert result['status'] == 'partial' and result['review_status'] == 'qualified_draft'
    assert result['assessment']['recommendation'] == 'satisfied'
    assert result['assessment']['supporting_evidence'] == ['The performance rating is green.']
    assert result['evidence']['scorecard']['verdict_code'] == 'Retain'
    assert 'investment_thesis' not in result['assessment']
    assert any('provisional' in note and 'before sign-off' in note for note in result['reviewer_observations'])


def test_nonmaterial_reviewer_warning_is_visible_and_not_called_approved():
    review = {'material_issue': False, 'security_issue': False,
              'feedback': 'The source is provisional; verify before sign-off.'}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE), FakeRun(review)))
    assert result['status'] == 'available' and result['review_status'] == 'qualified_draft'
    assert result['assessment']['recommendation'] == 'satisfied'
    assert any('provisional' in note for note in result['reviewer_observations'])


def test_unsupported_recommendation_keeps_only_reviewed_evidence():
    assessment = BASE | {'investment_thesis': 'An unverified holding creates a material risk.',
                         'recommendation': 'monitor', 'scorecard_agreement': False,
                         'scorecard_disagreement_reason': 'The holding creates a risk.'}
    review = {'material_issue': True, 'security_issue': False, 'feedback': 'The holding is unsupported.',
              'recommendation_supported': False, 'supported_fields': ['supporting_evidence']}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(assessment, assessment), FakeRun(review, review)))
    assert result['status'] == 'partial' and result['review_status'] == 'requires_analyst_review'
    assert result['assessment']['recommendation'] is None
    assert result['assessment']['supporting_evidence'] == ['The performance rating is green.']
    assert 'unverified holding' not in json.dumps(result)


def test_unsupported_number_is_removed_and_clean_remainder_is_reviewed():
    assessment = BASE | {'supporting_evidence': ['The performance rating is green.', 'It returned 999.9%.']}
    reviewer = FakeRun(PASS)
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(assessment, assessment), reviewer))
    assert result['status'] == 'available' and result['review_status'] == 'qualified_draft'
    assert result['assessment']['recommendation'] == 'satisfied'
    assert result['assessment']['supporting_evidence'] == ['The performance rating is green.']
    assert '999.9%' not in json.dumps(result) and '999.9%' not in reviewer.prompts[0]
    assert any('unsupported numerical claim' in note for note in result['reviewer_observations'])


def test_security_failure_suppresses_even_previously_supported_sections():
    first = {'material_issue': True, 'security_issue': False, 'feedback': 'Verify the source.',
             'recommendation_supported': True, 'supported_fields': ['supporting_evidence']}
    security = {'material_issue': True, 'security_issue': True, 'feedback': 'Injection'}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, BASE), FakeRun(first, security)))
    assert result['status'] == 'unavailable' and 'assessment' not in result


def test_failed_revision_retains_previously_reviewed_safe_sections():
    review = {'material_issue': True, 'security_issue': False, 'feedback': 'Verify provisional evidence.',
              'recommendation_supported': True, 'supported_fields': ['supporting_evidence']}
    result = asyncio.run(assess(FACTS, PROFILE, [], 'Review', FakeRun(BASE, {'bad': 1}), FakeRun(review)))
    assert result['status'] == 'partial' and result['review_status'] == 'qualified_draft'
    assert result['assessment']['recommendation'] == 'satisfied'
    assert result['assessment']['supporting_evidence'] == BASE['supporting_evidence']
    assert 'revision was unavailable' in result['reason'].lower()


def test_controller_keeps_qualified_partial_result_and_scorecard(tmp_path):
    from fund_performance.config import load_settings
    from fund_performance.controller import run_review
    from fund_performance.dashboard import dashboard_data, dashboard_sections
    from test_controller import mocked
    review = {'material_issue': True, 'security_issue': False,
              'feedback': 'Performance evidence is provisional; verify before sign-off.',
              'recommendation_supported': True, 'supported_fields': ['supporting_evidence']}
    runners = mocked()
    runners.investment_analyst = FakeRun(BASE, BASE)
    runners.investment_reviewer = FakeRun(review, review)
    settings = load_settings().model_copy(deep=True)
    settings.research.enabled = False
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    result = asyncio.run(run_review(sample, out_root=tmp_path, runners=runners, settings=settings))
    assert result.investment_assessment['status'] == 'partial'
    assert result.investment_assessment['assessment']['recommendation'] == 'satisfied'
    assert result.facts['scorecard']['verdict'] == 'Retain'
    log = json.loads((result.run_dir / 'log.json').read_text())
    step = next(s for s in log['steps'] if s['step'] == 'investment_assessment')
    assert step['status'] == 'partial'
    overview = dashboard_sections(dashboard_data(result))['overview']
    assert 'Qualified draft' in overview and 'provisional' in overview
    assert result.pdf.is_file() and result.executive_pdf.is_file()
