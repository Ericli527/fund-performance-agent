"""Cash illustrations are computed from the fund evidence, not invented by the language model."""
import asyncio
import copy
from decimal import Decimal, ROUND_HALF_UP

import pytest
from pydantic import ValidationError

from conftest import FakeRun
from fund_performance.agents.chatbot import answer_question
from fund_performance.chat_calculations import InvestmentValueRequest, investment_value, render_investment_value


@pytest.fixture
def catalogue():
    return {'fund_identity': {'currency': 'GBP', 'ocf_pct': 0.06, 'as_of_date': '2026-09-30'},
            'investment_returns': {'figures': [
                {'name': 'fund_nav.cum.5y', 'value': 88.3, 'unit': '%'},
                {'name': 'fund_nav.ann.5y', 'value': 13.5, 'unit': '%'},
                {'name': 'fund_pnav.cum.5y', 'value': 90.9, 'unit': '%'},
                {'name': 'index.cum.5y', 'value': 91.6, 'unit': '%'}]}}


def request(**kwargs):
    return InvestmentValueRequest(principal=kwargs.pop('principal', 10000), currency='GBP', years=5, **kwargs)


QUESTION = 'Imagine I invested 10,000 pounds in this fund 5 years ago, how much would I have now, after reducing the service fee?'


def test_screenshot_question_gets_cash_value_without_double_charging_ocf(catalogue):
    original = copy.deepcopy(catalogue)
    result = investment_value(catalogue, request(), QUESTION)
    assert result['ending_value'] == '18830.00' and result['gain'] == '8830.00'
    text = render_investment_value(result)
    assert '£18,830.00' in text and '88.3% cumulative dealing-NAV' in text
    assert 'not deducted again' in text and 'No separate platform or service fee has been assumed' in text
    assert '2026-09-30' in text and 'not a live account balance or a forecast' in text
    assert catalogue == original


def test_explicit_fund_ocf_is_not_deducted_as_an_additional_fee(catalogue):
    result = investment_value(catalogue, request(additional_annual_fee_pct=0.06),
        'What would £10,000 over 5 years be after the 0.06% annual ongoing charge?')
    assert result['ending_value'] == '18830.00' and result['additional_annual_fee_pct'] is None


def test_explicit_separate_annual_platform_fee_is_applied_once(catalogue):
    result = investment_value(catalogue, request(additional_annual_fee_pct=0.5),
        'How much would £10,000 be after 5 years and a separate 0.5% annual platform fee?')
    expected = Decimal('18830') * Decimal('0.995') ** 5
    assert result['ending_value'] == str(expected.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    assert result['before_service_fee'] == '18830.00'
    text = render_investment_value(result)
    assert 'year-end percentage deduction' in text and 'Actual charges depend' in text


def test_annualised_return_is_compounded_for_the_exact_period(catalogue):
    catalogue['investment_returns']['figures'] = [catalogue['investment_returns']['figures'][1]]
    result = investment_value(catalogue, request(), QUESTION)
    expected = Decimal('10000') * Decimal('1.135') ** 5
    assert result['return_kind'] == 'ann'
    assert result['ending_value'] == str(expected.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize('value,ending,gain', [(-20, '8000.00', '-2000.00'), (-100, '0.00', '-10000.00'),
                                            (0, '10000.00', '0.00')])
def test_losses_and_zero_return_are_handled(value, ending, gain, catalogue):
    catalogue['investment_returns']['figures'] = [{'name': 'fund_nav.cum.5y', 'value': value, 'unit': '%'}]
    result = investment_value(catalogue, request(), QUESTION)
    assert result['ending_value'] == ending and result['gain'] == gain


def test_old_prepared_session_uses_source_backed_fund_context_without_reextraction(catalogue):
    catalogue.pop('investment_returns')
    catalogue['fund_context'] = {'financial_evidence': {'currency': 'GBP', 'series': {
        'fund_nav': {'5y': 88.3, 'basis': 'cumulative'}}}}
    result = investment_value(catalogue, request(), QUESTION)
    assert result['ending_value'] == '18830.00' and result['source_reference'] == 'fund_context'
    catalogue['fund_context']['financial_evidence']['series']['fund_nav'] = {'5y': 13.5, 'basis': 'annualised'}
    result = investment_value(catalogue, request(), QUESTION)
    assert result['return_kind'] == 'ann'  # A series' declared basis takes precedence over its container name.


def test_calculator_never_replaces_missing_fund_return_with_benchmark_or_pnav(catalogue):
    catalogue['investment_returns']['figures'] = catalogue['investment_returns']['figures'][2:]
    with pytest.raises(ValueError, match='No fund return'):
        investment_value(catalogue, request(), QUESTION)
    with pytest.raises(ValueError, match='explicit request'):
        investment_value(catalogue, request(pricing_basis='fund_pnav'), QUESTION)
    result = investment_value(catalogue, request(pricing_basis='fund_pnav'), 'Illustrate £10,000 over 5 years using market-close PNAV.')
    assert result['ending_value'] == '19090.00'
    assert 'not a price at which investors deal' in render_investment_value(result)


@pytest.mark.parametrize('question,options', [
    ('What is the fund performance?', {}),
    ('What would £10,000 be over ten years?', {}),
    ('What would EUR 10,000 be over 5 years?', {}),
])
def test_missing_or_mismatched_user_assumptions_are_not_invented(question, options, catalogue):
    with pytest.raises(ValueError):
        investment_value(catalogue, request(**options), question)


@pytest.mark.parametrize('question', [
    'How much would £10,000 be?',
    '£10,000 over 5 years with a service fee of 0.5%',
    '£10,000 with a separate 0.4% annual platform fee',
])
def test_unknown_fee_does_not_suppress_known_base_value_or_authorise_a_guessed_rate(question, catalogue):
    result = investment_value(catalogue, request(additional_annual_fee_pct=0.5), question)
    assert result['ending_value'] == '18830.00' and result['additional_annual_fee_pct'] is None
    assert result['service_fee_unconfirmed'] is True
    text = render_investment_value(result)
    assert '£18,830.00' in text and 'value above excludes it' in text


def test_conflicting_source_currency_is_rejected(catalogue):
    catalogue['fund_context'] = {'financial_evidence': {'currency': 'USD'}}
    with pytest.raises(ValueError, match='source return currency conflicts'):
        investment_value(catalogue, request(), QUESTION)


def test_conflicting_source_date_is_rejected(catalogue):
    catalogue['fund_context'] = {'financial_evidence': {'as_of_date': '2025-09-30', 'currency': 'GBP'}}
    with pytest.raises(ValueError, match='source return date conflicts'):
        investment_value(catalogue, request(), QUESTION)


@pytest.mark.parametrize('years,rate,ending', [(1, 10, '11000.00'), (3, 30, '13000.00'), (5, 88.3, '18830.00')])
def test_each_supported_period_uses_its_own_return(years, rate, ending, catalogue):
    catalogue['investment_returns']['figures'] = [{'name': f'fund_nav.cum.{years}y', 'value': rate, 'unit': '%'}]
    selected = InvestmentValueRequest(principal=10000, currency='GBP', years=years)
    assert investment_value(catalogue, selected, f'Illustrate £10,000 over {years} years')['ending_value'] == ending


def test_followup_can_reuse_amount_from_user_history_but_not_assistant_claims(catalogue):
    history = [{'role': 'user', 'content': 'Illustrate a £10k investment.'}]
    result = investment_value(catalogue, request(), 'What about its 5-year return?', history)
    assert result['ending_value'] == '18830.00'
    history[0]['role'] = 'assistant'
    with pytest.raises(ValueError, match='provide the amount'):
        investment_value(catalogue, request(), 'What about its 5-year return?', history)


def test_followup_can_reuse_an_explicit_user_service_fee(catalogue):
    history = [{'role': 'user', 'content': 'Use a separate 0.5% annual platform fee.'}]
    result = investment_value(catalogue, request(principal=20000, additional_annual_fee_pct=0.5),
                              'What about £20,000 over five years?', history)
    assert result['before_service_fee'] == '37660.00'
    assert result['additional_annual_fee_pct'] == 0.5


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -101, '88.3'])
def test_invalid_source_values_are_withheld(value, catalogue):
    catalogue['investment_returns']['figures'] = [{'name': 'fund_nav.cum.5y', 'value': value, 'unit': '%'}]
    with pytest.raises(ValueError, match='stored return is invalid'):
        investment_value(catalogue, request(), QUESTION)


def test_request_is_bounded_without_arbitrary_expression_evaluation():
    for fields in [{'principal': -1}, {'principal': float('inf')}, {'additional_annual_fee_pct': 100}]:
        with pytest.raises(ValidationError):
            request(**fields)


def test_chat_routes_calculation_to_python_with_one_model_call_and_discards_untrusted_draft(catalogue):
    output = {'status': 'insufficient_evidence', 'answer': 'An invented £999,999.99 cash value must not appear.',
              'evidence_references': [], 'limitations': [], 'security_issue': False,
              'proposes_investment_decision': False, 'calculation_request': request().model_dump()}
    runner = FakeRun(output)
    text = asyncio.run(answer_question(catalogue, QUESTION, run=runner))
    assert '£18,830.00' in text and '999,999' not in text and len(runner.prompts) == 1
    assert 'withheld' not in text


def test_calculation_request_does_not_override_security_or_new_rating_checks(catalogue):
    base = {'status': 'answered', 'answer': 'Unsafe content', 'evidence_references': [], 'limitations': [],
            'security_issue': False, 'proposes_investment_decision': False, 'calculation_request': request().model_dump()}
    for field in ('security_issue', 'proposes_investment_decision'):
        text = asyncio.run(answer_question(catalogue, QUESTION, run=FakeRun(base | {field: True})))
        assert '18,830' not in text
