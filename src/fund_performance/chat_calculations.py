"""Bounded cash illustrations from stored fund returns, never model-supplied return figures."""
import math
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from html import escape
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InvestmentValueRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    principal: float = Field(ge=0, le=1_000_000_000_000, description='Amount explicitly supplied by the user, including a recent user follow-up.')
    currency: str = Field(pattern=r'^[A-Za-z]{3}$', description='ISO currency of the investment; never convert currencies.')
    years: Literal[1, 3, 5]
    pricing_basis: Literal['fund_nav', 'fund_pnav'] = 'fund_nav'
    additional_annual_fee_pct: float | None = Field(default=None, ge=0, lt=100,
        description='Separate platform/service/adviser fee explicitly stated by the user as an annual percentage. Never the fund OCF.')


def _user_numbers(text: str) -> set[Decimal]:
    values = set()
    for match in re.finditer(r'(?<![\w.])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(thousand|million|k\b)?', text, re.I):
        scale = {'k': 1000, 'thousand': 1000, 'million': 1000000}.get((match[2] or '').lower(), 1)
        values.add(Decimal(match[1].replace(',', '')) * scale)
    words = dict(zip(('zero one two three four five six seven eight nine ten eleven twelve thirteen '
                      'fourteen fifteen sixteen seventeen eighteen nineteen twenty').split(), range(21)))
    for match in re.finditer(r'\b(' + '|'.join(words) + r')\b(?:\s+(hundred|thousand|million))?', text, re.I):
        scale = {'hundred': 100, 'thousand': 1000, 'million': 1000000}.get((match[2] or '').lower(), 1)
        values.add(Decimal(words[match[1].lower()] * scale))
    return values


def _return(catalogue: dict, years: int, basis: str) -> tuple[dict, str, str]:
    """Prefer the cumulative return for the exact period and basis; never substitute the benchmark."""
    for kind in ('cum', 'ann'):
        name = f'{basis}.{kind}.{years}y'
        for ref in ('investment_returns', 'published_figures'):
            for figure in (catalogue.get(ref) or {}).get('figures', []):
                if figure.get('name') == name and figure.get('unit') == '%':
                    return figure, ref, kind
        # Older prepared sessions already carry the source-backed structured factsheet in the brief.
        context = catalogue.get('fund_context') or {}
        financial = context.get('financial_evidence') or {}
        for group in (('series', 'series_annualised') if kind == 'cum' else ('series_annualised', 'series')):
            series = (financial.get(group) or {}).get(basis) or {}
            expected = 'cumulative' if kind == 'cum' else 'annualised'
            if series.get('basis', 'cumulative' if group == 'series' else 'annualised') != expected:
                continue
            value = series.get(f'{years}y')
            if value is not None:
                return {'value': value, 'unit': '%', 'name': name}, 'fund_context', kind
        performance = catalogue.get(f'performance:{years}y') or {}
        if performance.get('fund_benchmark_basis') == basis:
            figure = performance.get('fund_return_cumulative' if kind == 'cum' else 'fund_return_a_year')
            if figure and figure.get('unit') == '%':
                return figure, f'performance:{years}y', kind
    raise ValueError('No fund return is available for that exact period and pricing basis. Add the relevant fund return; a benchmark or different-period return cannot replace it.')


def investment_value(catalogue: dict, request: InvestmentValueRequest, question: str,
                     history: list[dict] | None = None) -> dict:
    user_text = '\n'.join([item['content'] for item in (history or [])[-12:]
                           if item.get('role') == 'user' and isinstance(item.get('content'), str)] + [question])
    if Decimal(str(request.principal)) not in _user_numbers(user_text):
        raise ValueError('Please provide the amount to invest; I will not assume a cash amount.')
    identity = catalogue.get('fund_identity') or {}
    currency = request.currency.upper()
    if not identity.get('currency') or currency != identity['currency'].upper():
        raise ValueError('The investment and fund return must use the same currency. A currency conversion needs separate exchange-rate evidence.')
    financial = (catalogue.get('fund_context') or {}).get('financial_evidence') or {}
    if financial.get('currency') and financial['currency'].upper() != currency:
        raise ValueError('The source return currency conflicts with the fund currency. Resolve that evidence before calculating a cash value.')
    if financial.get('as_of_date') and identity.get('as_of_date') and financial['as_of_date'] != identity['as_of_date']:
        raise ValueError('The source return date conflicts with the review date. Confirm the matching review-period return before calculating a cash value.')
    mentioned = {code for pattern, code in [(r'£|\bpounds?\b|\bGBP\b', 'GBP'),
                 (r'\bUSD\b|\bUS dollars?\b', 'USD'), (r'€|\beuros?\b|\bEUR\b', 'EUR')]
                 if re.search(pattern, question, re.I)}
    if mentioned and mentioned != {currency}:
        raise ValueError('The requested cash currency differs from the fund return. I cannot assume an exchange rate.')
    if re.search(r'\$|\bdollars?\b', question, re.I) and currency not in ('USD', 'CAD', 'AUD', 'NZD', 'SGD', 'HKD'):
        raise ValueError('The requested dollar amount does not match the fund currency. Please confirm the currency; I cannot assume an exchange rate.')
    periods = {int(value) for value in re.findall(r'\b(\d+)\s*[- ]?\s*(?:years?|yrs?|y)\b', question, re.I)}
    words = {'one': 1, 'three': 3, 'five': 5, 'ten': 10}
    periods |= {value for word, value in words.items() if re.search(r'\b' + word + r'\s+years?\b', question, re.I)}
    if periods and request.years not in periods:
        raise ValueError('The requested period does not match the selected return. Please use an available one-, three- or five-year period.')
    if request.pricing_basis == 'fund_pnav' and not re.search(r'PNAV|market.close', user_text, re.I):
        raise ValueError('For an investment value, use the dealing-NAV return. A market-close PNAV estimate needs an explicit request and is not a dealing price.')
    fee = request.additional_annual_fee_pct
    fee_unconfirmed = False
    if fee is not None:
        fee_text = question if re.search(r'fee|charge|OCF', question, re.I) else user_text
        separate = re.search(r'platform|service|advis[eo]r|broker|additional', fee_text, re.I)
        annual = re.search(r'annual|per\s+year|a\s+year|yearly|per\s+annum', fee_text, re.I)
        rates = {Decimal(value.replace(',', '')) for value in re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*(?:%|per\s+cent)', fee_text, re.I)}
        if not separate and re.search(r'ongoing|OCF|fund (?:fee|charge)', question, re.I):
            fee = None  # A mislabelled OCF request must not double-charge or suppress the valid base illustration.
        elif not separate or not annual or Decimal(str(fee)) not in rates:
            fee, fee_unconfirmed = None, True  # Still provide the known fund value, clearly before this unknown fee.
    figure, reference, kind = _return(catalogue, request.years, request.pricing_basis)
    value = figure.get('exact') if figure.get('exact') is not None else figure.get('value')
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or not -100 <= value <= 1_000_000:
        raise ValueError('The stored return is invalid for an investment-value calculation. Verify the source figure first.')
    with localcontext() as context:
        context.prec = 50
        principal, rate = Decimal(str(request.principal)), Decimal(str(value))
        growth = 1 + rate / 100
        if kind == 'ann':
            growth = growth ** request.years
        before_service_fee = principal * growth
        after_service_fee = before_service_fee * ((1 - Decimal(str(fee)) / 100) ** request.years if fee is not None else 1)
        cash = lambda amount: str(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        return {'principal': cash(principal), 'ending_value': cash(after_service_fee),
                'gain': cash(after_service_fee - principal), 'before_service_fee': cash(before_service_fee),
                'additional_fee_impact': cash(before_service_fee - after_service_fee), 'currency': currency,
                'return_pct': value, 'return_kind': kind, 'years': request.years,
                'pricing_basis': request.pricing_basis, 'source_reference': reference,
                'as_of_date': identity.get('as_of_date') or (catalogue.get(f'performance:{request.years}y') or {}).get('as_of_date'),
                'additional_annual_fee_pct': fee, 'service_fee_unconfirmed': fee_unconfirmed}


def render_investment_value(result: dict) -> str:
    symbol = {'GBP': '£', 'USD': '$', 'EUR': '€'}.get(result['currency'], result['currency'] + ' ')
    money = lambda key: symbol + f"{Decimal(result[key]):,.2f}"
    period = f"{result['years']} years" + (f" to {escape(result['as_of_date'])}" if result.get('as_of_date') else '')
    kind = 'cumulative' if result['return_kind'] == 'cum' else 'annualised'
    basis = 'dealing-NAV' if result['pricing_basis'] == 'fund_nav' else 'illustrative market-close PNAV'
    text = (f"Using the **{result['return_pct']:g}% {kind} {basis} return** over {period}, "
            f"**{money('principal')} would have grown to about {money('ending_value')}**, "
            f"a {'gain' if Decimal(result['gain']) >= 0 else 'loss'} of **{symbol}{abs(Decimal(result['gain'])):,.2f}**. "
            'The fund’s ongoing charge is already reflected in NAV returns, so it is not deducted again.')
    if result['additional_annual_fee_pct'] is not None:
        text += (f"\n\nThis includes your separate **{result['additional_annual_fee_pct']:g}% annual service fee**, "
                 f"modelled as a year-end percentage deduction: an illustrative reduction of **{money('additional_fee_impact')}** "
                 f"from {money('before_service_fee')}. Actual charges depend on the provider’s calculation and payment timing.")
    elif result['service_fee_unconfirmed']:
        text += ('\n\nI could not confirm a separate annual service-fee rate from your question, so the value above excludes it. '
                 'Please confirm the provider’s annual percentage and I can include it; I have not assumed a fee.')
    else:
        text += '\n\nNo separate platform or service fee has been assumed. If you mean an additional service charge, provide its annual percentage and I can include it.'
    if result['pricing_basis'] == 'fund_pnav':
        text += ' PNAV is a market-close comparison estimate, not a price at which investors deal.'
    return (text + '\n\nThis illustration follows the supplied return’s income treatment, assumes no further contributions or withdrawals, and excludes investor-level taxes. '
            'It uses the available review-period figures, not a live account balance or a forecast; provisional source figures still need verification.'
            f"\n\n**Sources:** Prepared fund return [{escape(result['source_reference'])}]; Python cash-value calculation.")
