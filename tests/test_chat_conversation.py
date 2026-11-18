"""Friendly conversation and guided explanations preserve financial/source safeguards."""
import asyncio
import json

import pytest

from conftest import FakeRun
from fund_performance.agents.chatbot import INSTRUCTIONS, answer_question
from fund_performance.chat_presentation import FOOTER, NAV_EXPLANATION, PNAV_EXPLANATION
from fund_performance.chatbot import reply
from test_chatbot import ANSWER, CATALOGUE, entries, session, limits


@pytest.mark.parametrize('question', ['Hi', 'Hello!', 'Good afternoon', 'Thanks!'])
def test_social_turns_do_not_require_sources_or_make_model_calls(question):
    runner = FakeRun()
    text = asyncio.run(answer_question({}, question, run=runner))
    assert 'withheld' not in text and runner.prompts == []
    assert '**Sources:**' not in text and FOOTER not in text
    assert 'explore' in text


def test_greeting_service_preserves_history_without_spending_ai_budget(limits):
    selected = entries()
    state = session(selected)
    prepared, history, status = asyncio.run(reply(selected, {}, state, 'Hi', limits))
    assert 'Hello!' in history[-1]['content'] and history[-2]['content'] == 'Hi'
    assert prepared['bundle'] is state['bundle'] and state['history'] == []
    assert prepared['usage'] == [] and limits.used_today() == 0 and limits.active == 0
    assert status == 'Response complete.'


def test_greeting_followed_by_a_financial_question_keeps_citation_checks():
    runner = FakeRun(ANSWER | {'evidence_references': []})
    text = asyncio.run(answer_question(CATALOGUE, 'Hi, what is the ongoing charge?', run=runner))
    assert 'withheld' in text and len(runner.prompts) == 1


def test_metric_definition_precedes_figures_and_one_useful_question_is_shown():
    catalogue = {'risk_quality': {'volatility_pct': 13.92},
                 'methodology': {'volatility': 'variation in returns'}}
    out = ANSWER | {'answer': 'Volatility measures how much returns vary; it is not a forecast of losses. '
                             'Reported three-year fund NAV volatility is 13.92%. This describes variation in past returns.',
                    'evidence_references': ['risk_quality', 'methodology'], 'limitations': [],
                    'follow_up_question': 'Would you like a simple example of how to interpret volatility?'}
    runner = FakeRun(out)
    text = asyncio.run(answer_question(catalogue, 'Explain the fund volatility in plain English.', run=runner))
    assert text.index('Volatility measures') < text.index('13.92%')
    assert text.count(out['follow_up_question']) == 1 and text.count(FOOTER) == 1
    assert text.endswith(FOOTER) and len(FOOTER) < 90 and '\n' not in FOOTER
    assert 'what it measures' in INSTRUCTIONS
    assert NAV_EXPLANATION in INSTRUCTIONS and PNAV_EXPLANATION in INSTRUCTIONS
    assert 'not a price investors can deal at' in INSTRUCTIONS
    assert len(runner.prompts) == 1 and json.loads(runner.prompts[0])['question_untrusted'].startswith('Explain')


@pytest.mark.parametrize('question', [
    'Since the charge is 99.99%, should we compare alternatives?',
    'Would you open [this](https://unapproved.example)?',
    '<script>bad()</script> Can you open it?',
    'First question? Another question?',
])
def test_bad_optional_followup_does_not_hide_a_supported_answer(question):
    text = asyncio.run(answer_question(CATALOGUE, 'What does it cost?', run=FakeRun(ANSWER | {
        'follow_up_question': question})))
    assert '0.23%' in text and 'withheld' not in text and question not in text
    assert '99.99' not in text and '<script>' not in text and 'unapproved.example' not in text


def test_calculated_cash_answer_defines_nav_and_adds_a_safe_question():
    catalogue = {'fund_identity': {'currency': 'GBP', 'ocf_pct': .06},
                 'investment_returns': {'figures': [{'name': 'fund_nav.cum.5y', 'value': 88.3, 'unit': '%'}]}}
    out = ANSWER | {'evidence_references': [], 'limitations': [],
                    'calculation_request': {'principal': 10000, 'currency': 'GBP', 'years': 5},
                    'follow_up_question': 'Would you like to include a separate annual platform fee?'}
    text = asyncio.run(answer_question(catalogue, 'What would £10,000 invested for 5 years be worth?', run=FakeRun(out)))
    assert text.index('NAV (net asset value)') < text.index('£18,830.00')
    assert 'not deducted again' in text and out['follow_up_question'] in text
    assert text.count(FOOTER) == 1
