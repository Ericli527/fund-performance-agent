"""Small arithmetic executor: grounded operands, no Python eval, tools or external access."""
import ast
import math
import re
from decimal import Decimal, DecimalException, localcontext
from html import escape

from pydantic import BaseModel, ConfigDict, Field

from fund_performance.chat_calculations import _user_numbers


class Operand(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(pattern=r'^[a-z][a-z_]{0,23}$')
    reference: str | None = Field(default=None, max_length=80, description='Exact catalogue reference for a fund figure; null for a user-provided assumption.')
    path: str | None = Field(default=None, max_length=160, description='JSON pointer to a numeric value within that reference, e.g. /fund_return_a_year/value. Not a file path.')
    user_value: float | None = Field(default=None, ge=-1e12, le=1e12, description='Only a number explicitly supplied by the user; never a model guess or a recalled assistant claim.')
    unit: str = Field(pattern=r'^(number|%|pp|bps|[A-Z]{3})$', description='Numeric unit as recorded, or the user assumption unit.')


class ArithmeticRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: str = Field(min_length=1, max_length=400, description='Arithmetic using named operands, parentheses, + - * / **. Percentages are in percentage units; divide by 100 when needed.')
    operands: list[Operand] = Field(max_length=10)
    result_unit: str = Field(pattern=r'^(number|%|pp|bps|[A-Z]{3})$')


def _resolve(node, path):
    if not path or not path.startswith('/'):
        raise ValueError('A source-backed calculation needs an exact numeric evidence path.')
    parent, key = None, None
    for key in path[1:].split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        parent = node
        try:
            node = node[int(key)] if isinstance(node, list) else node[key]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError('The requested numeric source value is unavailable.') from None
    return node, parent, key


def arithmetic(catalogue: dict, request: ArithmeticRequest, question: str, history=None) -> str:
    user_text = '\n'.join([m['content'] for m in (history or [])[-12:] if m.get('role') == 'user'
                           and isinstance(m.get('content'), str)] + [question])
    user_values = _user_numbers(user_text)
    values, details, refs, currencies = {}, [], [], set()
    uses_nav_return, uses_ocf = False, False
    for operand in request.operands:
        if operand.name in values:
            raise ValueError('Calculation input names must be distinct.')
        if operand.reference is not None:
            if operand.user_value is not None or operand.reference not in catalogue:
                raise ValueError('A fund figure must come from one known source, not a model-supplied value.')
            value, parent, key = _resolve(catalogue[operand.reference], operand.path)
            source_unit = parent.get('unit') if isinstance(parent, dict) else None
            source_unit = source_unit or ('%' if key.endswith('_pct') else 'pp' if key.endswith('_pp') else 'number')
            source_unit = 'number' if source_unit == 'ratio' else source_unit
            if source_unit != operand.unit:
                raise ValueError('The calculation input unit does not match its source.')
            refs.append(operand.reference)
            label = str(parent.get('name') or parent.get('label') or operand.path) if isinstance(parent, dict) else operand.path
            uses_nav_return |= any(tag in str(operand.path) + label for tag in ('fund_nav', 'fund_pnav', 'fund_return'))
            uses_ocf |= 'ocf' in (str(operand.path) + label).lower()
            origin = f'prepared evidence [{operand.reference}]'
        else:
            if operand.path is not None or operand.user_value is None or Decimal(str(operand.user_value)) not in user_values:
                raise ValueError('Please supply the calculation inputs; I will not assume a missing number.')
            value, origin = operand.user_value, 'your supplied assumption'
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e12:
            raise ValueError('The calculation source is not a finite, supported numeric value.')
        if re.fullmatch('[A-Z]{3}', operand.unit):
            currencies.add(operand.unit)
        values[operand.name] = Decimal(str(value))
        details.append(f"{operand.name.replace('_', ' ').capitalize()}: {value:g} {operand.unit if operand.unit != 'number' else ''} ({origin}).")
    if len(currencies) > 1:
        raise ValueError('Different cash currencies cannot be combined without supported exchange rates.')
    if uses_nav_return and uses_ocf:
        raise ValueError('Fund NAV returns already reflect OCF. Use the investment-value calculation so the ongoing charge is not deducted twice.')
    if uses_nav_return and currencies and currencies != {(catalogue.get('fund_identity') or {}).get('currency')}:
        raise ValueError('The cash currency and fund return currency differ; I cannot assume an exchange rate.')
    if re.fullmatch('[A-Z]{3}', request.result_unit) and request.result_unit not in currencies:
        raise ValueError('A cash result needs a matching cash-currency input.')
    try:
        tree = ast.parse(request.expression, mode='eval')
    except SyntaxError:
        raise ValueError('That arithmetic expression is not valid.') from None
    if len(list(ast.walk(tree))) > 80:
        raise ValueError('Please split this into shorter calculations.')

    def evaluate(node):
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            number = Decimal(str(node.value))
            constants = {Decimal(n) for n in (*range(13), 100, 365, 10000)}
            if abs(number) <= Decimal('1e12') and (number in user_values or number in constants):
                return number
            raise ValueError('Use a cited source operand or an explicitly supplied number, not a guessed figure.')
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            a, b = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): result = a + b
            elif isinstance(node.op, ast.Sub): result = a - b
            elif isinstance(node.op, ast.Mult): result = a * b
            elif isinstance(node.op, ast.Div): result = a / b
            else:
                if abs(b) > 600: raise ValueError('The compounding exponent is outside the calculator limit.')
                result = a ** b
            if not result.is_finite() or abs(result) > Decimal('1e30'):
                raise ValueError('The calculation result is outside the supported range.')
            return result
        raise ValueError('Only numeric arithmetic and named inputs are supported; code, calls and file access are not allowed.')

    try:
        with localcontext() as context:
            context.prec = 40
            result = evaluate(tree.body)
            unit = request.result_unit
            decimals = 2 if re.fullmatch('[A-Z]{3}', unit) else 4 if unit in ('%', 'pp') else 6
            number = f'{result:,.{decimals}f}'
            if not re.fullmatch('[A-Z]{3}', unit):
                number = number.rstrip('0').rstrip('.')
    except (DecimalException, OverflowError, ValueError) as error:
        if isinstance(error, ValueError): raise
        raise ValueError('The arithmetic is undefined, such as division by zero or an invalid compounding base.') from None
    prefix = {'GBP': '£', 'USD': '$', 'EUR': '€'}.get(unit, unit + ' ' if re.fullmatch('[A-Z]{3}', unit) else '')
    suffix = '%' if unit == '%' else ' ' + unit if unit in ('pp', 'bps') else ''
    text = f'**Calculated result: {prefix}{number}{suffix}.**\n\n'
    if details:
        text += '**Inputs used:**\n' + '\n'.join('- ' + escape(item) for item in details) + '\n\n'
    text += '**Calculation:** ' + escape(request.expression.replace('**', '^').replace('*', '×').replace('/', '÷'))
    text += '\n\nCalculated by Python from the inputs shown. User assumptions are hypothetical; provisional source figures require verification. This is not a forecast or investment recommendation.'
    return text
