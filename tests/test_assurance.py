import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from conftest import FakeRun
from fund_performance.agents.assurance import (AssuranceResult, DISCLAIMER, DIMENSIONS, inspect, render,
                                                report_text, session_handle, snapshot)

FACTS = json.loads((Path(__file__).parent / 'golden' / 'demo_facts.json').read_text())


def answer(facts=FACTS):
    ratings = {p['name']: p['rating'] for p in facts['scorecard']['pillars']}
    return {'decision': 'REVISE', 'pass_likelihood_pct': None, 'likelihood_calibrated': False,
            'confidence': 'MEDIUM', 'decision_reason': 'The evidence needs further qualification.',
            'likelihood_explanation': 'An estimate is not justified with limited evidence.',
            'supporting_factors': ['The scorecard records its rationale.'], 'uncertainties': ['Evidence needs review.'],
            'rating_reviews': [{'dimension': d, 'original_rating': ratings[d], 'proposed_rating': None,
                                'judgement': 'SUPPORTED_WITH_QUALIFICATIONS', 'reason': 'Review the evidence.',
                                'evidence_references': ['scorecard'], 'recommended_action': 'Check sources.'}
                               for d in DIMENSIONS],
            'report_quality': {'factual_accuracy': 'PASS', 'investment_reasoning': 'REVISE',
                'evidence_completeness': 'REVISE', 'professional_clarity': 'PASS', 'governance': 'PASS'},
            'visual_inspection': {'performed': False, 'findings': [], 'limitations': ['No page images supplied.']},
            'material_findings': [{'severity': 'MODERATE', 'issue': 'Peer evidence requires review.',
                                    'evidence_references': ['peers'], 'recommended_action': 'Review comparability.'}],
            'human_review_required': True, 'security_issue': False}


def evidence():
    return {'question': 'Is the fund suitable?', 'facts': copy.deepcopy(FACTS),
            'research': [{'summary': 'Dated market context.', 'date': '2026-09-01'}],
            'fund_context': {'mandate': 'Index tracking; provisional.'},
            'reports': {'executive': {'status': 'available', 'text': 'A public executive report.'},
                        'detailed': {'status': 'available', 'text': 'A public detailed report.'},
                        'research': {'status': 'unavailable', 'reason': 'Report was not generated.'}}}


def test_structured_review_preserves_scorecard_and_displays_uncalibrated_estimate():
    data = evidence()
    before = copy.deepcopy(data)
    a = answer() | {'pass_likelihood_pct': 72,
                    'likelihood_explanation': 'The 72% estimate is uncertain and uncalibrated.'}
    runner = FakeRun(a)
    result = asyncio.run(inspect(data, run=runner))
    assert result['status'] == 'available' and result['review']['decision'] == 'REVISE'
    assert data == before and result['review']['human_review_required'] is True
    assert result['review']['material_findings'][0]['evidence_references'] == ['peers']
    html = render(result)
    assert DISCLAIMER in html and '72%' in html and 'Human review and sign-off required' in html
    assert 'Visual inspection not performed' in html and 'Research: unavailable' in html
    assert 'public executive report' not in html
    sent = json.loads(runner.prompts[0])
    assert sent['facts']['scorecard'] == before['facts']['scorecard'] and sent['question'] == before['question']


@pytest.mark.parametrize('bad', ['rating', 'reference', 'visual', 'claim_visual', 'human', 'calibration', 'security', 'probability'])
def test_invalid_or_unsafe_assurance_never_becomes_a_pass(bad):
    a = answer() | {'decision': 'PASS'}
    if bad == 'rating': a['rating_reviews'][0]['original_rating'] = 'CHANGED'
    if bad == 'reference': a['material_findings'][0]['evidence_references'] = ['research:99']
    if bad == 'visual': a['visual_inspection']['performed'] = True
    if bad == 'claim_visual': a['material_findings'][0]['issue'] = 'The chart is clipped.'
    if bad == 'human': a['human_review_required'] = False
    if bad == 'calibration': a['likelihood_calibrated'] = True
    if bad == 'security': a['security_issue'] = True
    if bad == 'probability': a['pass_likelihood_pct'] = 101
    result = asyncio.run(inspect(evidence(), run=FakeRun(a)))
    assert result['status'] == 'unavailable' and 'review' not in result


def test_model_failure_and_missing_report_are_unavailable():
    result = asyncio.run(inspect(evidence(), run=FakeRun({'bad': 1})))
    assert result['status'] == 'unavailable'
    data = evidence()
    data['reports'] = {'detailed': {'status': 'unavailable'}}
    runner = FakeRun(answer())
    assert asyncio.run(inspect(data, run=runner))['status'] == 'unavailable'
    assert not runner.prompts


def test_sources_dates_comparability_and_provisional_evidence_reach_judge():
    data = evidence()
    data['facts']['peers'] = [{'currency': 'USD', 'fee_type': 'ter', 'used_for_returns': False,
                                'excluded': 'returns in USD, not GBP'}]
    data['facts']['figures'][0]['source'] = 'ai_extracted'
    data['fund_context'] = {'mandate': 'Passive tracker', 'limitations': ['R² and beta alone are not enough.']}
    data['investment_assessment'] = {'status': 'available', 'assessment': {'recommendation': 'monitor',
                                                                         'scorecard_agreement': False}}
    a = answer()
    a['material_findings'][0]['evidence_references'] = ['peers', 'research:1']
    runner = FakeRun(a)
    result = asyncio.run(inspect(data, run=runner))
    assert result['status'] == 'available'
    given = json.loads(runner.prompts[0])
    assert given['facts']['peers'][0]['excluded'] == 'returns in USD, not GBP'
    assert given['facts']['peers'][0]['fee_type'] == 'ter' and given['facts']['figures'][0]['source'] == 'ai_extracted'
    assert given['investment_assessment']['assessment']['scorecard_agreement'] is False
    assert 'R² and beta alone' in given['fund_context']['limitations'][0]


def test_report_text_and_session_snapshot_are_bounded_and_text_only(tmp_path):
    pdf = tmp_path / 'sample.pdf'
    c = canvas.Canvas(str(pdf))
    c.drawString(30, 800, 'Public report for inspection')
    c.save()
    assert report_text(pdf)['status'] == 'available'
    log = SimpleNamespace(report_sources=lambda: ([], []))
    result = SimpleNamespace(facts=copy.deepcopy(FACTS), presentation_context={'question': 'Review?', 'research': []},
                             log=log, pdf=pdf, executive_pdf=pdf)
    handle = session_handle(result)
    snap = snapshot(handle)
    assert snap['question'] == 'Review?' and snap['reports']['executive']['status'] == 'available'
    assert snap['reports']['research']['status'] == 'unavailable' and 'text-only' in snap['visual_inspection']
    assert str(pdf) not in json.dumps(snap)


def test_render_escapes_model_text():
    data = evidence()
    a = answer() | {'decision_reason': '<script>alert(1)</script>'}
    output = asyncio.run(inspect(data, run=FakeRun(a)))
    html = render(output)
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_an_unsupported_report_number_is_not_promoted_into_assurance():
    data = evidence()
    data['reports']['executive']['text'] = 'The report claims a return of 999.9%.'
    a = answer()
    a['material_findings'][0]['issue'] = 'The fund returned 999.9%.'
    assert asyncio.run(inspect(data, run=FakeRun(a)))['status'] == 'unavailable'
    a['material_findings'][0]['issue'] = 'The report contains an unsupported return claim.'
    a['material_findings'][0]['evidence_references'] = ['report:executive']
    assert asyncio.run(inspect(data, run=FakeRun(a)))['status'] == 'available'


def test_report_missing_risks_can_be_flagged_without_changing_ratings():
    data = evidence()
    data['reports']['detailed']['text'] = 'No discussion of investment risks was provided.'
    a = answer()
    a['material_findings'][0] = {'severity': 'HIGH', 'issue': 'The detailed report omits material risks.',
                                 'evidence_references': ['report:detailed'],
                                 'recommended_action': 'Add the relevant risks before sign-off.'}
    result = asyncio.run(inspect(data, run=FakeRun(a)))
    assert result['status'] == 'available'
    assert result['review']['material_findings'][0]['evidence_references'] == ['report:detailed']
    assert result['review']['rating_reviews'] == a['rating_reviews']


def test_assurance_reviews_proposals_without_overwriting_disagreement():
    data = evidence()
    a = answer()
    proposals = []
    for i, rating in enumerate(a['rating_reviews']):
        proposal = 'AMBER' if rating['original_rating'] != 'AMBER' else 'GREEN'
        proposals.append({'dimension': rating['dimension'], 'proposed_rating': proposal,
                          'rationale': 'Evidence supports a qualified disagreement.'})
        rating['proposed_rating'] = proposal
    data['investment_assessment'] = {'status': 'available', 'assessment': {'investment_ratings': proposals}}
    before = copy.deepcopy(data)
    result = asyncio.run(inspect(data, run=FakeRun(a)))
    assert result['status'] == 'available' and data == before
    assert result['review']['rating_reviews'][0]['proposed_rating'] == proposals[0]['proposed_rating']
    a['rating_reviews'][0]['proposed_rating'] = None
    assert asyncio.run(inspect(data, run=FakeRun(a)))['status'] == 'unavailable'


def test_optional_ui_inspection_respects_switch_and_shared_limits(tmp_path, monkeypatch):
    from fund_performance.config import load_settings
    from fund_performance.web import AiLimits, build_ui, inspect_saved_review
    import gradio as gr
    pdf = tmp_path / 'public.pdf'
    c = canvas.Canvas(str(pdf))
    c.drawString(30, 800, 'Public report for inspection')
    c.save()
    result = SimpleNamespace(facts=copy.deepcopy(FACTS), presentation_context={'question': 'Review?', 'research': []},
                             log=SimpleNamespace(report_sources=lambda: ([], [])), pdf=pdf, executive_pdf=pdf)
    handle = session_handle(result)
    settings = load_settings().web.model_copy(update={'max_ai_runs_per_day': 1})
    limits = AiLimits(settings, path=tmp_path / 'limit.json')
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('FUND_REVIEW_OFFLINE', raising=False)
    monkeypatch.setenv('AI_RUNS_ENABLED', 'false')
    runner = FakeRun(answer())
    assert 'switched off' in asyncio.run(inspect_saved_review(handle, limits, runner=runner))
    assert not runner.prompts and limits.used_today() == 0
    monkeypatch.setenv('AI_RUNS_ENABLED', 'true')
    html = asyncio.run(inspect_saved_review(handle, limits, runner=runner))
    assert 'Decision: REVISE' in html and limits.used_today() == 1 and limits.active == 0
    assert 'limit is reached' in asyncio.run(inspect_saved_review(handle, limits, runner=FakeRun(answer())))
    ui = build_ui(limits)
    buttons = [c for c in ui.blocks.values() if isinstance(c, gr.Button) and c.value == 'Inspect Report']
    assert len(buttons) == 1 and buttons[0].interactive is False
    assert all(f.api_visibility == 'private' for f in ui.fns.values())
