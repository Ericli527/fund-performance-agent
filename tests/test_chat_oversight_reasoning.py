"""Stage 1 materiality and three Stage 2 investigation modes, with no live calls."""
import asyncio
import copy
import json

import pytest

from conftest import FakeRun
from fund_performance.agents.chatbot import answer_question
from fund_performance.chat_validation import evidence_readiness
from fund_performance.chatbot import OVERSIGHT_QUESTIONS
from test_chat_interpretation import BASE, CATALOGUE, figure


def ask(question, response, catalogue=None):
    source = copy.deepcopy(catalogue or CATALOGUE)
    before = copy.deepcopy(source)
    runner = FakeRun(BASE | response)
    text = asyncio.run(answer_question(source, question, run=runner))
    assert len(runner.prompts) == 1 and source == before
    return text, json.loads(runner.prompts[0])


def test_limitations_are_scoped_to_the_decision_not_converted_into_a_bad_fund_rating():
    ready = evidence_readiness(CATALOGUE)
    assert 'tracking_consistency' in ready['limitation_scopes']
    assert 'not the fund’s own compatible benchmark' in ready['limitation_scopes']['peer_returns']
    assert 'valuation_alignment' in ready['limitation_scopes']
    no_peer = copy.deepcopy(CATALOGUE)
    del no_peer['peers']
    ready = evidence_readiness(no_peer)
    assert 'relative_competitiveness' in ready['limitation_scopes']
    assert ready['performance_references'] == ['performance:5y']
    assert 'rating' not in ready and 'verdict' not in ready


def test_documented_horizon_guides_relevance_without_changing_figures():
    catalogue = copy.deepcopy(CATALOGUE)
    catalogue['mandate']['mandate']['values'] |= {'objective_type': 'index_tracker', 'benchmark_role': 'target',
                                                  'time_horizon_years': 3}
    catalogue['performance:3y'] = {'fund_return_a_year': figure(17.68), 'benchmark_return_a_year': figure(17.98)}
    ready = evidence_readiness(catalogue)
    assert ready['performance_references'] == ['performance:3y', 'performance:5y']
    assert ready['strategy_context']['time_horizon_years'] == 3
    assert catalogue['performance:3y']['fund_return_a_year']['value'] == 17.68


def test_preliminary_conclusion_evidence_qualification_and_action_remain_one_answer():
    text, _ = ask(OVERSIGHT_QUESTIONS[0], {'answer_focus': 'mandate_delivery',
        'answer': 'The reported outcomes are broadly consistent with the tracking objective. The five-year fund return '
                  'is 11.31% a year against 11.60% for the benchmark, with a stored difference of -0.29 pp. '
                  'Missing tracking error qualifies the consistency assessment; it does not invalidate these outcomes. '
                  'Confirm valuation alignment before drawing an exact tracking conclusion.'})
    assert 'broadly consistent' in text and 'Confirm valuation alignment' in text and 'withheld' not in text


def test_challenge_tests_the_working_view_without_inventing_a_negative_rating():
    text, _ = ask('Challenge my working view that the fund should be retained.', {'answer_focus': 'challenge',
        'answer': 'The strongest reservation is whether timing differences affect the apparent benchmark shortfall. '
                  'The fund reports 11.31% a year against 11.60% for its benchmark over five years. '
                  'Confirm matched valuation times and tracking consistency before treating this as persistent weak delivery. '
                  'This challenges the strength of the conclusion, not a demonstrated mandate breach.'})
    assert 'strongest reservation' in text and 'not a demonstrated mandate breach' in text
    assert 'new investment recommendation needs' not in text


def test_alternative_explanations_are_hypotheses_not_a_fabricated_attribution():
    text, _ = ask(OVERSIGHT_QUESTIONS[3], {'answer_focus': 'alternative_explanations',
        'answer': 'Valuation timing and charges are plausible explanations to test, not established causes. '
                  'The published ongoing charge is 0.23%, but that does not prove how much of the shortfall it caused. '
                  'Compare matched-time returns and the documented charge treatment to distinguish the explanations.'})
    assert 'not established causes' in text and 'does not prove' in text and 'withheld' not in text


def test_priorities_use_current_relevance_without_discarding_historical_records():
    catalogue = CATALOGUE | {'risk_quality': {'warnings': [
        'Repeated prices occurred outside the current five-year review window; longer-history checks remain unresolved.']}}
    text, prompt = ask(OVERSIGHT_QUESTIONS[4], {'answer_focus': 'priorities',
        'evidence_references': ['fund_identity', 'performance:5y', 'risk_quality'],
        'answer': 'First confirm pricing-time alignment because it affects the benchmark interpretation. '
                  'Then establish tracking consistency because it qualifies the strength of the tracking conclusion. '
                  'The historical price observations remain recorded for longer-history checks; their dates alone '
                  'do not establish an error in the current review window.'}, catalogue)
    assert 'First confirm' in text and 'historical price observations remain recorded' in text
    assert prompt['question_support']['oversight_references'] == ['risk_quality']


@pytest.mark.parametrize('focus,title', [
    ('challenge', 'Evidence for testing the working conclusion'),
    ('alternative_explanations', 'Evidence for investigating possible explanations'),
    ('priorities', 'Evidence and unresolved checks for oversight')])
def test_invalid_stage2_claim_keeps_facts_without_manufacturing_a_replacement_judgement(focus, title):
    text, _ = ask('Investigate the evidence', {'answer_focus': focus, 'answer': 'An unsupported claim of 99.99%.'})
    assert title in text and '11.31%' in text and '99.99' not in text
    assert 'failed draft judgement has not been retained' in text


def test_genuinely_blocked_benchmark_comparison_stays_blocked_in_context_and_fallback():
    catalogue = copy.deepcopy(CATALOGUE)
    catalogue['performance:5y'] |= {'benchmark_return_a_year': None,
        'unavailable': {'benchmark_return_a_year': 'Currency check failed.'}}
    ready = evidence_readiness(catalogue)
    assert 'do not reconstruct rejected figures' in ready['limitation_scopes']['benchmark_comparison']
    text, _ = ask('Challenge the comparison', {'answer_focus': 'challenge', 'answer': 'Unsupported 99.99%.'}, catalogue)
    assert 'Currency check failed' in text and '11.6%' not in text


def test_oversight_examples_populate_input_without_running_the_chatbot():
    from fund_performance.web import build_ui
    from fund_performance.chat_views import VIEW_QUESTIONS
    ui = build_ui()
    datasets = [component for component in ui.get_config_file()['components']
                if component['type'] == 'dataset' and component['props'].get('label') == 'Explore the fund or start an oversight question']
    assert len(datasets) == 1
    assert datasets[0]['props']['samples'] == [[question] for question in VIEW_QUESTIONS + OVERSIGHT_QUESTIONS]
    assert len(OVERSIGHT_QUESTIONS) == 5
    example_events = [fn for fn in ui.fns.values() if fn.api_name == 'load_example']
    assert len(example_events) == 1 and example_events[0].api_visibility == 'private'
    assert '/load_example' not in ui.get_api_info()['named_endpoints']
