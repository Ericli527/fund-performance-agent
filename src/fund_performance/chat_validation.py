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
