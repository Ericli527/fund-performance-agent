import copy
import json
from pathlib import Path

from fund_performance.agents.judge import judge_input
from fund_performance.agents.payloads import assessment_for_narrative
from fund_performance.agents.reporter import Draft, reporter_input


def test_narrative_agents_receive_assessment_and_all_evidence_without_execution_telemetry():
    facts = json.loads((Path(__file__).parent / 'golden' / 'demo_facts.json').read_text())
    assessment = {'status': 'available', 'assessment': {'investment_ratings': [
        {'dimension': 'Performance', 'proposed_rating': 'AMBER', 'agreement': False,
         'rationale': 'Tracking requires investigation.', 'supporting_evidence': ['performance:5y'],
         'limitations': ['Risk figures are provisional.']}]},
        'evidence': {'performance:5y': {'data': 'Source evidence remains available.'}},
        'limitations': ['Verify source figures.'], 'reviewer_observations': ['Review the peer currency.'],
        'tool_calls': ['get_fund_context'], 'diagnostics': {'attempts': [{'execution_marker': 'INTERNAL_TELEMETRY'}]}}
    original = copy.deepcopy(assessment)
    compact = assessment_for_narrative(assessment)
    assert assessment == original and len(json.dumps(compact)) < len(json.dumps(assessment))
    reporter = reporter_input(facts, 'analyst', ['Performance'], assessment=assessment)
    judge = judge_input(facts, Draft('analyst', text='The fund needs review.'), assessment=assessment)
    for prompt in (reporter, judge):
        assert 'Tracking requires investigation.' in prompt and 'Source evidence remains available.' in prompt
        assert 'Risk figures are provisional.' in prompt and 'Review the peer currency.' in prompt
        assert 'INTERNAL_TELEMETRY' not in prompt and 'get_fund_context' not in prompt
