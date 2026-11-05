"""Chat-only numerical evidence adapters and a safe, source-based fallback; no model calls."""
import math
import re

from fund_performance.agents.investment_analyst import context_numbers


def numerical_evidence(catalogue: dict, refs: list[str]) -> dict:
    """Add units only for known schema fields, and only within the cited evidence."""
    evidence = {ref: catalogue[ref] for ref in refs if ref in catalogue}
    percentages = []
    context = evidence.get('fund_context') or {}
    if context.get('sources'):
        evidence = evidence | {'context_units': context_numbers(context)}
        financial = context.get('financial_evidence') or {}
        for group in ('risk_3y', 'risk_3y_nav'):
            risk = financial.get(group) or {}
            percentages.extend(risk.get(key) for key in ('fund_vol', 'index_vol', 'tracking_error', 'alpha'))
        for group in ('calendar_years', 'discrete_12m'):
            percentages.extend(value for series in (financial.get(group) or {}).values() for value in series.values())
    for peer in (evidence.get('peer_documents') or {}).get('peers') or []:
        for group in ('returns', 'returns_annualised'):
            series = peer.get(group) or {}
            percentages.extend(series.get(key) for key in ('1y', '3y', '5y', 'y1', 'y3', 'y5', 'since_launch'))
        percentages.append(peer.get('vol_3y'))
    for peer in (evidence.get('peers') or {}).get('peers') or []:
        percentages.extend((peer.get('returns_pct_a_year') or {}).values())
    evidence['schema_percentages'] = [{'value': value, 'unit': '%'} for value in percentages
                                     if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
    return evidence


def _plain(value) -> str | None:
    if not isinstance(value, str) or not value.strip() or re.search(r'<|https?://|```', value):
        return None
    return re.sub(r'([\\`*_{}\[\]()#!|>])', r'\\\1', ' '.join(value.split()))


def source_overview(catalogue: dict) -> tuple[str, list[str]] | None:
    """Discard the failed model draft, rather than guessing which clauses are safe to salvage.

    This is a clearly labelled partial overview from known fields, never an investment recommendation.
    """
    identity = catalogue.get('fund_identity') or {}
    name = _plain(identity.get('fund_name'))
    if not name:
        return None
    refs = ['fund_identity']
    details = [_plain(identity.get(key)) for key in ('share_class', 'currency')]
    text = '**Source-based fund overview**\n\n' + name
    if any(details):
        text += ' — ' + ', '.join(value for value in details if value)
    text += '.'
    mandate = ((catalogue.get('mandate') or {}).get('mandate') or {}).get('values') or {}
    objective = _plain(mandate.get('objective_text') or identity.get('objective_text'))
    benchmark = _plain(mandate.get('benchmark_name') or identity.get('benchmark_name'))
    if objective:
        text += '\n\n**Objective:** ' + objective
    if benchmark:
        text += '\n\n**Benchmark:** ' + benchmark + '.'
    if (objective or benchmark) and mandate:
        refs.append('mandate')
    charge = identity.get('ocf_pct')
    if isinstance(charge, (int, float)) and not isinstance(charge, bool) and math.isfinite(charge):
        text += f'\n\n**Ongoing charge:** {charge:g}% a year. This is the published charge, not a comparison with alternatives.'
    for ref in ('peers', 'peer_documents'):
        peers = (catalogue.get(ref) or {}).get('peers') or []
        descriptions = []
        for peer in peers[:3]:
            peer_name = _plain(peer.get('name'))
            if not peer_name:
                continue
            terms = [_plain(peer.get(key)) for key in ('share_class', 'currency', 'investor_type', 'minimum_investment')]
            descriptions.append(peer_name + (' (' + ', '.join(term for term in terms if term) + ')' if any(terms) else ''))
        if descriptions:
            text += '\n\n**Peer evidence:** ' + '; '.join(descriptions) + '. Identification alone does not establish eligibility or a like-for-like performance comparison.'
            refs.append(ref)
            break
    return text, refs


def evidence_readiness(catalogue: dict) -> dict:
    """A compact map of existing evidence, not a rating or a claim that source documents lack it."""
    identity = catalogue.get('fund_identity') or {}
    mandate = ((catalogue.get('mandate') or {}).get('mandate') or {}).get('values') or {}
    performance = [ref for ref in ('performance:5y', 'performance:3y', 'performance:1y')
                   if catalogue.get(ref)]
    financial = (catalogue.get('fund_context') or {}).get('financial_evidence') or {}
    tracking = any((catalogue[ref].get('tracking_error') or {}).get('value') is not None for ref in performance)
    if (catalogue.get('fund_context') or {}).get('sources'):
        tracking |= any((financial.get(key) or {}).get('tracking_error') is not None for key in ('risk_3y', 'risk_3y_nav'))
    gaps = []
    if not (mandate.get('objective_text') or identity.get('objective_text')):
        gaps.append('The objective is not established in structured mandate fields; check the source context before calling it absent.')
    if not tracking:
        gaps.append('Tracking error is not established in the prepared metrics; return gaps alone do not establish tracking consistency.')
    if not identity.get('pricing_point'):
        gaps.append('The fund valuation time is not established; exact pricing-time alignment needs confirmation.')
    if identity.get('ocf_pct') is None:
        gaps.append('The ongoing charge is not established in the prepared charge fields.')
    comparability = []
    peer_ref = 'peers' if (catalogue.get('peers') or {}).get('peers') else 'peer_documents'
    peers = (catalogue.get(peer_ref) or {}).get('peers') or []
    for peer in peers:
        currency = peer.get('currency')
        if identity.get('currency') and currency and currency != identity['currency']:
            comparability.append(f"Peer returns are in {currency}, while the fund is in {identity['currency']}; do not compare them directly.")
        if peer.get('investor_type') == 'institutional' or peer.get('minimum_investment'):
            comparability.append('Peer share-class eligibility and minimum investment need checking.')
    blocked = {ref: catalogue[ref]['unavailable']['benchmark_return_a_year'] for ref in performance
               if (catalogue[ref].get('unavailable') or {}).get('benchmark_return_a_year')}
    return {'performance_references': performance,
            'published_figures_reference': 'published_figures' if (catalogue.get('published_figures') or {}).get('figures') else None,
            'missing_or_unestablished': gaps,
            'comparison_limits': list(dict.fromkeys(comparability)), 'unavailable_comparisons': blocked,
            'peer_reference': peer_ref if peers else None,
            'interpretation': 'Missing secondary metrics or peers do not automatically prevent a preliminary mandate interpretation. '
                              'Use the documented objective and compatible returns; no universal acceptable return gap is implied. '
                              'Missing evidence is separate from investment quality and from a comparison limitation.'}


def focused_fallback(catalogue: dict, focus: str) -> tuple[str, list[str]] | None:
    """Keep relevant facts/gaps after discarding an invalid draft; never manufacture its judgement."""
    if focus == 'general':
        return source_overview(catalogue)
    ready = evidence_readiness(catalogue)
    refs, facts = [], []
    mandate = ((catalogue.get('mandate') or {}).get('mandate') or {}).get('values') or {}
    objective = _plain(mandate.get('objective_text') or (catalogue.get('fund_identity') or {}).get('objective_text'))
    if objective:
        facts.append('**Objective:** ' + objective)
        refs.append('mandate' if mandate.get('objective_text') else 'fund_identity')
    for ref in ready['performance_references']:
        row = catalogue[ref]
        fund, benchmark = row.get('fund_return_a_year') or {}, row.get('benchmark_return_a_year') or {}
        def pct(figure):
            value = figure.get('value')
            return f'{value:g}%' if figure.get('unit') == '%' and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        fund_value, benchmark_value = pct(fund), pct(benchmark)
        if fund_value:
            sentence = f"**{ref.split(':')[1][0]}-year annualised return:** fund {fund_value}"
            sentence += f'; benchmark {benchmark_value}' if benchmark_value else '; no comparable benchmark figure is established'
            date = _plain(row.get('as_of_date'))
            basis = _plain(row.get('fund_benchmark_basis'))
            sentence += (f' (as at {date})' if date else '') + (f'; prepared basis: {basis}' if basis else '') + '.'
            facts.append(sentence)
            refs.append(ref)
    identity = catalogue.get('fund_identity') or {}
    charge = identity.get('ocf_pct')
    if isinstance(charge, (int, float)) and not isinstance(charge, bool) and math.isfinite(charge):
        facts.append(f'**Published ongoing charge:** {charge:g}% a year; this alone does not establish competitiveness.')
        refs.append('fund_identity')
    if not facts:
        return source_overview(catalogue)
    title = 'Evidence available for mandate assessment' if focus == 'mandate_delivery' else 'Available evidence and remaining gaps'
    text = '**' + title + '**\n\n' + '\n'.join('- ' + fact for fact in facts)
    gaps = ready['missing_or_unestablished']
    if gaps:
        text += '\n\n**Still to establish:** ' + ' '.join(gaps)
        refs.extend(ref for ref in ('fund_identity', 'fund_context') if ref in catalogue)
    if ready['comparison_limits']:
        text += '\n\n**Comparison limits:** ' + ' '.join(ready['comparison_limits'])
        refs.append(ready['peer_reference'])
    if ready['unavailable_comparisons']:
        text += '\n\n**Benchmark comparison unavailable:** ' + ' '.join(
            _plain(reason) or 'A comparison check remains unresolved.' for reason in ready['unavailable_comparisons'].values())
    text += '\n\nThese are prepared facts and qualifications, not an approved investment rating. The failed draft judgement has not been retained.'
    return text, list(dict.fromkeys(refs))
