import asyncio

from conftest import FakeRun
from fund_performance.agents.chatbot import answer_question
from fund_performance.chat_presentation import specific_limits

EXAMPLE = '''Key figures for the **Vanguard FTSE Global All Cap Index Fund, A GBP Accumulation Shares**, as at 30 September 2026:

- **Size and holdings:** £10,626 million in fund assets and 7,336 stocks.
- **Exposure:** The factsheet reports 62.5% in the US, 34.3% in technology and 4.6% in NVIDIA.
- **Returns:** Annualised GBP fund NAV returns were 17.81% over one year, 17.68% over three years and 11.31% over five years. The corresponding index returns were 18.02%, 17.98% and 11.60%.
- **Charges and risk:** Ongoing charges are 0.23% a year, and the KIID risk indicator is 5.

The fund seeks to track the FTSE Global All Cap Index. Returns are net of fund fees; past performance is not a reliable indicator of future results.'''


def test_existing_bullet_and_paragraph_breaks_are_preserved_exactly():
    assert specific_limits(EXAMPLE) == EXAMPLE


def test_inline_bold_category_bullets_gain_separate_lines_without_changing_data():
    assert specific_limits(EXAMPLE.replace('\n- ', ' - ')) == EXAMPLE
    assert specific_limits('Tracking difference is -0.10 pp. A company - **name** is unchanged.') == 'Tracking difference is -0.10 pp. A company - **name** is unchanged.'


def test_provenance_cleanup_keeps_list_layout_and_real_qualifications():
    text = EXAMPLE + '\n\nAI-extracted figures require verification against the source documents.\nThe market-close price is illustrative, not a dealing price.'
    cleaned = specific_limits(text)
    assert cleaned.startswith(EXAMPLE + '\n\n')
    assert 'require verification' not in cleaned
    assert 'illustrative, not a dealing price' in cleaned
    assert len([line for line in cleaned.splitlines() if line.startswith('- **')]) == 4


def test_chat_response_keeps_four_bullets_sources_and_following_paragraph():
    out = {'status': 'answered', 'answer': EXAMPLE, 'evidence_references': ['fund_context'],
           'limitations': [], 'security_issue': False, 'proposes_investment_decision': False}
    runner = FakeRun(out)
    rendered = asyncio.run(answer_question({'fund_context': {'document_summary': EXAMPLE}},
                           'What are some key data / stats about the fund?', run=runner))
    assert rendered.startswith(EXAMPLE)
    assert '\n\n**Sources:** Fund context brief [fund_context]' in rendered
    assert len(runner.prompts) == 1
