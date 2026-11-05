"""Flexible arithmetic uses source/user inputs; generated Python code is never executed."""
import asyncio
from decimal import Decimal

import pytest

from conftest import FakeRun
from fund_performance.chat_arithmetic import ArithmeticRequest, Operand, arithmetic
from fund_performance.agents.chatbot import answer_question


def user(name, value, unit='number'):
    return Operand(name=name, user_value=value, unit=unit)


@pytest.mark.parametrize('expression,question,expected', [
    ('2 + 3', 'What is 2 plus 3?', '5'),
    ('200 - 50', 'Subtract 50 from 200', '150'),
    ('20 / 100 * 5000', 'What is 20% of 5,000?', '1,000'),
    ('(10 + 20 + 30) / 3', 'Average 10, 20 and 30', '20'),
    ('75 / 25', 'Ratio of 75 to 25', '3'),
    ('(120 - 100) / 100 * 100', 'Percentage increase from 100 to 120', '20'),
])
def test_simple_questions_do_not_need_a_new_calculation_template(expression, question, expected):
    request = ArithmeticRequest(expression=expression, operands=[], result_unit='number')
    assert f'**Calculated result: {expected}.**' in arithmetic({}, request, question)


def test_source_backed_fee_difference_is_percentage_points():
    catalogue = {'fund_identity': {'ocf_pct': 0.23}, 'peer': {'ter_pct': 0.12}}
    request = ArithmeticRequest(expression='fund_fee - peer_fee', result_unit='pp', operands=[
        Operand(name='fund_fee', reference='fund_identity', path='/ocf_pct', unit='%'),
        Operand(name='peer_fee', reference='peer', path='/ter_pct', unit='%')])
    text = arithmetic(catalogue, request, 'What is the difference in these published fees?')
    assert '0.11 pp' in text and '[fund_identity]' in text and '[peer]' in text


def test_basis_point_conversion_keeps_its_unit():
    request = ArithmeticRequest(expression='rate * 100', operands=[user('rate', 0.23, '%')], result_unit='bps')
    assert 'Calculated result: 23 bps.' in arithmetic({}, request, 'Convert 0.23% into basis points.')


def test_user_assumptions_support_other_horizons_and_monthly_compounding():
    request = ArithmeticRequest(expression='principal * (1 + rate / 100 / 12) ** (years * 12)',
        result_unit='GBP', operands=[user('principal', 10000, 'GBP'), user('rate', 6, '%'), user('years', 10)])
    text = arithmetic({}, request, 'Assume £10,000 at 6% for ten years, compounded monthly.')
    expected = Decimal('10000') * (1 + Decimal('.06') / 12) ** 120
    assert f'£{expected:,.2f}' in text and 'not a forecast' in text and 'your supplied assumption' in text


@pytest.mark.parametrize('expression', [
    '__import__("os").system("whoami")', 'open("secret")', '(1).__class__',
    '[x for x in (1,2)]', 'lambda: 1', '1 if True else 2', 'sum([1,2])', 'missing + 1',
    '1 # [click](https://unapproved.example)',
])
def test_python_code_and_unknown_names_are_rejected(expression):
    with pytest.raises(ValueError):
        arithmetic({}, ArithmeticRequest(expression=expression, operands=[], result_unit='number'), 'Calculate 1 and 2')


@pytest.mark.parametrize('expression', ['1 / 0', '(-1) ** (1 / 2)', '2 ** 10000'])
def test_undefined_or_excessive_arithmetic_has_a_safe_failure(expression):
    with pytest.raises(ValueError):
        arithmetic({}, ArithmeticRequest(expression=expression, operands=[], result_unit='number'), 'Use 1 and 2')


def test_source_values_cannot_be_replaced_with_model_guesses_or_assistant_numbers():
    with pytest.raises(ValueError, match='cited source operand'):
        arithmetic({}, ArithmeticRequest(expression='99.9 + 1', operands=[], result_unit='number'), 'What is the fee?')
    request = ArithmeticRequest(expression='principal * 2', operands=[user('principal', 10000, 'GBP')], result_unit='GBP')
    with pytest.raises(ValueError, match='supply the calculation inputs'):
        arithmetic({}, request, 'Double it.', [{'role': 'assistant', 'content': 'The investment is £10,000.'}])


def test_unknown_reference_and_wrong_units_are_rejected():
    request = ArithmeticRequest(expression='fee * 2', operands=[
        Operand(name='fee', reference='invented', path='/ocf_pct', unit='%')], result_unit='%')
    with pytest.raises(ValueError, match='known source'):
        arithmetic({}, request, 'Double the charge.')
    request.operands[0].reference = 'fund'
    request.operands[0].unit = 'GBP'
    with pytest.raises(ValueError, match='unit does not match'):
        arithmetic({'fund': {'ocf_pct': 0.23}}, request, 'Double the charge.')


def test_mixed_cash_currencies_and_ocf_double_count_are_rejected():
    request = ArithmeticRequest(expression='a + b', operands=[user('a', 100, 'GBP'), user('b', 100, 'USD')], result_unit='GBP')
    with pytest.raises(ValueError, match='Different cash currencies'):
        arithmetic({}, request, 'Add GBP 100 and USD 100.')
    request = ArithmeticRequest(expression='ret - fee', operands=[
        Operand(name='ret', reference='fund', path='/figures/0/value', unit='%'),
        Operand(name='fee', reference='fund_identity', path='/ocf_pct', unit='%')], result_unit='pp')
    catalogue = {'fund': {'figures': [{'name': 'fund_nav.cum.5y', 'value': 88.3, 'unit': '%'}]}, 'fund_identity': {'ocf_pct': 0.06}}
    with pytest.raises(ValueError, match='already reflect OCF'):
        arithmetic(catalogue, request, 'Deduct OCF again.')


def test_flexible_arithmetic_still_needs_only_one_model_call():
    request = ArithmeticRequest(expression='20 / 100 * 5000', operands=[], result_unit='number')
    output = {'status': 'answered', 'answer': 'An incorrect draft says 99,999.', 'evidence_references': [],
        'limitations': [], 'security_issue': False, 'proposes_investment_decision': False,
        'arithmetic_request': request.model_dump()}
    runner = FakeRun(output)
    text = asyncio.run(answer_question({}, 'What is 20% of 5,000?', run=runner))
    assert 'Calculated result: 1,000.' in text and '99,999' not in text and len(runner.prompts) == 1
