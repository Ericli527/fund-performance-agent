"""Overview reliability without another model call or relaxed numerical/source checks."""
import asyncio

import pytest

from conftest import FakeRun
from fund_performance.agents.chatbot import answer_question
from fund_performance.chat_validation import numerical_evidence
from fund_performance.number_guard import check_numbers
from test_chatbot import ANSWER

CATALOGUE = {'fund_identity': {'fund_name': 'Example US Tracker', 'share_class': 'P Acc', 'currency': 'GBP',
                              'ocf_pct': 0.06, 'benchmark_name': 'Example US Index'},
             'mandate': {'mandate': {'values': {'objective_text': 'The fund aims to track the Example US Index.',
                                               'benchmark_name': 'Example US Index'}}},
             'fund_context': {'sources': ['factsheet.pdf'], 'financial_evidence': {
                 'series': {'fund_nav': {'5y': 88.3, 'basis': 'cumulative'}},
                 'series_annualised': {'fund_nav': {'5y': 13.8, 'basis': 'annualised'}},
                 'risk_3y': {'tracking_error': 0.02, 'beta': 1.01}}},
             'peer_documents': {'peers': [{'name': 'Example institutional peer', 'share_class': 'Institutional Acc',
                 'currency': 'GBP', 'investor_type': 'institutional', 'minimum_investment': 'GBP 1 million',
                 'returns': {'5y': 87.9, 'basis': 'cumulative'}}]}}


def ask(draft, refs, **changes):
    runner = FakeRun(ANSWER | {'answer': draft, 'evidence_references': refs, 'limitations': []} | changes)
    text = asyncio.run(answer_question(CATALOGUE, 'Tell me about the fund and its benchmark / peer', run=runner))
    assert len(runner.prompts) == 1
    return text


def test_extracted_returns_and_risk_keep_their_known_percentage_units():
    # Reproduce the old false positive using the same source-labelled intake shape.
    assert check_numbers('88.3%', {'fund_context': CATALOGUE['fund_context']}) == ['88.3%']
    text = ask('The five-year cumulative fund return is 88.3%, equivalent to the published annualised 13.8%. '
               'Reported three-year tracking error is 0.02%.', ['fund_context'])
    assert 'withheld' not in text and '88.3%' in text and '13.8%' in text
    assert '0.02%' in text


def test_peer_returns_use_peer_schema_units_without_mandating_a_peer():
    text = ask('The uploaded peer reports a five-year cumulative return of 87.9%. This does not establish eligibility.', ['peer_documents'])
    assert 'withheld' not in text
    assert check_numbers('87.9%', numerical_evidence(CATALOGUE, ['fund_identity']))
    assert check_numbers('1.01%', numerical_evidence(CATALOGUE, ['fund_context']))  # Beta is not a percentage.


def test_invalid_draft_becomes_source_based_overview_not_an_empty_response(caplog):
    text = ask('A private unsupported draft claims a return of 99.99%.', ['fund_context'])
    assert 'Source-based fund overview' in text and 'Example US Tracker' in text
    assert 'aims to track' in text and '**Benchmark:** Example US Index' in text
    assert '0.06%' in text and 'Example institutional peer' in text and 'GBP 1 million' in text
    assert 'withheld' in text and 'partial overview' in text
    assert '99.99' not in text and 'private unsupported draft' not in text.lower()
    assert 'fund_identity' in text and '[mandate]' in text and '[peer_documents]' in text
    assert 'private unsupported draft' not in caplog.text.lower()


@pytest.mark.parametrize('changes', [
    {'evidence_references': ['unknown']}, {'evidence_references': []},
    {'answer': 'Unsupported 99.99%. <script>do_bad_things()</script>'},
    {'security_issue': True}, {'proposes_investment_decision': True}])
def test_source_or_security_failures_do_not_gain_a_partial_display_bypass(changes):
    text = ask('Unsupported 99.99%.', ['fund_context'], **changes)
    assert 'Source-based fund overview' not in text and '99.99' not in text and '<script>' not in text


def test_source_free_context_does_not_gain_percentage_provenance():
    context = {'fund_context': CATALOGUE['fund_context'] | {'sources': []}}
    assert check_numbers('88.3%', numerical_evidence(context, ['fund_context']))


def test_correct_overview_stays_as_written():
    text = ask('Example US Tracker aims to follow the Example US Index. Its published ongoing charge is 0.06% a year.',
               ['fund_identity', 'mandate'])
    assert 'Source-based fund overview' not in text and 'withheld' not in text
    assert '0.06%' in text


def test_fund_scope_note_is_retained_despite_index_column_label():
    from fund_performance.agents.extractor import ExtractedExposure
    from fund_performance.portfolio import source_checked_exposures
    note = "Each table shows a different breakdown of the fund's investments."
    page = 'Market Cap Breakdown (%)\nGBP Index\n>10bn 99.2\n' + note
    row = ExtractedExposure(category='market_cap', name='>10bn', quote='>10bn 99.2', weight_pct=99.2,
                            subject='fund', scope_quote=note)
    result = source_checked_exposures([row], {'factsheet.pdf': [page]})
    assert result['market_cap'][0]['weight_pct'] == 99.2
    assert result['market_cap'][0]['scope_excerpt'] == note
    assert source_checked_exposures([row], {'factsheet.pdf': [page]}, subject='benchmark')['market_cap'] is None
    assert source_checked_exposures([row.model_copy(update={'scope_quote': 'An invented note'})],
                                    {'factsheet.pdf': [page]})['market_cap'] is None


def test_conflicting_scope_can_be_retained_without_guessing_fund_or_benchmark():
    from fund_performance.agents.extractor import ExtractedExposure
    from fund_performance.portfolio import source_checked_exposures
    row = ExtractedExposure(category='holdings', name='Example Corp', quote='Example Corp 8.4%', weight_pct=8.4,
                            subject='unknown', scope_quote='Index')
    page = 'Top stocks (%) Index\nExample Corp 8.4%'
    values = source_checked_exposures([row], {'fund.pdf': [page]}, subject='unknown')
    assert values['holdings'][0]['subject'] == 'unknown'
    assert source_checked_exposures([row], {'fund.pdf': [page]})['holdings'] is None


@pytest.mark.parametrize('ref,entry', [
    ('peer_documents', {'peers': [{'returns': {'y5': 87.9, 'basis': 'cumulative'}}]}),
    ('peers', {'peers': [{'returns_pct_a_year': {'5y': 13.77}}]})])
def test_actual_peer_serialisation_has_percentage_units_only_when_cited(ref, entry):
    catalogue = {ref: entry}
    value = '87.9%' if ref == 'peer_documents' else '13.77%'
    assert check_numbers(value, catalogue)
    assert check_numbers(value, numerical_evidence(catalogue, [ref])) == []
    assert check_numbers(value, numerical_evidence(catalogue, []))
