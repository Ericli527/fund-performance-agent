import asyncio

from conftest import FakeRun
from fund_performance.agents.chatbot import answer_question
from fund_performance.chat_presentation import additional_context
from test_chatbot import ANSWER, CATALOGUE

ANSWER_WITH_SCOPE = ('The factsheet reports the fund composition. The tables are labelled Index, '
                     'although the accompanying note describes fund composition.')
SCOPE = 'The table labels and accompanying note leave some uncertainty over fund-versus-index attribution.'


def test_composition_scope_is_not_repeated_as_a_separate_warning():
    assert additional_context(ANSWER_WITH_SCOPE, [SCOPE]) == []
    text = asyncio.run(answer_question(CATALOGUE, 'Composition?', run=FakeRun(ANSWER | {
        'answer': ANSWER_WITH_SCOPE, 'limitations': [SCOPE]})))
    assert ANSWER_WITH_SCOPE in text
    assert '**Evidence limits:**' not in text and '**Important context:**' not in text


def test_new_gaps_and_material_details_survive_scope_deduplication():
    limits = additional_context(ANSWER_WITH_SCOPE, [SCOPE + ' Sector weights are missing.',
        'The table labels conflict with another holdings file dated 2026-08-31.',
        'The figures differ by 2.5%.'])
    assert limits == ['Sector weights are missing.',
        'The table labels conflict with another holdings file dated 2026-08-31.', 'The figures differ by 2.5%.']
    assert additional_context('The factsheet reports composition.', [SCOPE]) == [SCOPE]


def test_exact_duplicate_caveats_are_shown_once_and_new_context_is_plain():
    out = ANSWER | {'answer': 'The ongoing charge is 0.23%. Peer fee competitiveness is not established.',
                    'limitations': ['Peer fee competitiveness is not established.', 'No eligible peer is supplied.']}
    text = asyncio.run(answer_question(CATALOGUE, 'Fees?', run=FakeRun(out)))
    assert text.count('Peer fee competitiveness is not established.') == 1
    assert '**Important context:** No eligible peer is supplied.' in text
