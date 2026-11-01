"""Construct a per-review, source-labelled fund context from existing agent outputs."""
import copy


def build_fund_context(summary: str = '', profile: dict | None = None, factsheet=None,
                       exposures: dict | None = None, documents: list[str] | None = None,
                       mandate: str = '', recovered: list[dict] | None = None) -> dict:
    """No model call: the narrative and extracted data remain provisional, not verified facts."""
    return {'document_summary': summary or None, 'mandate_interpretation': mandate or None,
            'fund_facts': copy.deepcopy(profile or {}),
            'financial_evidence': factsheet.model_dump(mode='json', by_alias=True) if factsheet else None,
            'portfolio_exposures': copy.deepcopy(exposures), 'recovered_returns': copy.deepcopy(recovered or []),
            'sources': list(documents or []), 'document_date': factsheet.as_of_date.isoformat() if factsheet else None,
            'summary_evidence_level': 'provisional',
            'financial_evidence_level': ('provisional' if factsheet and factsheet.source == 'ai_extracted'
                                         else 'verified' if factsheet else 'unavailable'),
            'limitations': ['AI-extracted narratives and figures require verification against their sources.',
                            'Do not treat benchmark or peer information as fund holdings.']}


def recover_returns(factsheet, candidates, documents: dict[str, list[str]]):
    """Fill only absent returns from unambiguous, source-matched quotations; preserve existing values."""
    import re
    from fund_performance.models import SeriesReturns
    if factsheet is None:
        return factsheet, []
    result = factsheet.model_copy(deep=True)
    recovered = []
    # Conflicting proposed values are ambiguous even if each has a plausible
    # quotation; do not let document order decide a financial input.
    values = {}
    for item in candidates:
        values.setdefault((item.series, item.period, item.basis), set()).add(item.value)
    for item in candidates:
        if len(values[(item.series, item.period, item.basis)]) != 1:
            continue
        quote = ' '.join(item.quote.split())
        if not quote or item.currency.upper() != result.currency.upper():
            continue
        as_of = result.as_of_date
        dates = {as_of.isoformat(), f'{as_of:%d.%m.%Y}', f'{as_of:%d/%m/%Y}',
                 f'{as_of.day} {as_of:%B %Y}', f'{as_of.day} {as_of:%b %Y}'}
        sources = [(name, i) for name, pages in documents.items() for i, page in enumerate(pages, 1)
                   if quote.casefold() in ' '.join(page.split()).casefold()
                   and any(date.casefold() in page.casefold() for date in dates)]
        if not sources:
            continue
        percentages = re.findall(r'(?<![\d.])([−-]?\d+(?:\.\d+)?)\s*%', quote)
        if len(percentages) != 1 or abs(float(percentages[0].replace('−', '-')) - item.value) > 1e-9:
            continue
        years = item.period[0]
        if not re.search(rf'\b{years}\s*(?:-\s*)?(?:years?|yrs?|y)\b', quote, re.I):
            continue
        if not re.search(r'\b' + re.escape(item.currency) + r'\b', quote, re.I):
            continue
        if not re.search(r'\b(cumulative|total return)\b' if item.basis == 'cumulative' else
                         r'\b(annualised|annualized|per annum|a year)\b', quote, re.I):
            continue
        marker = {'fund_nav': r'\bfund\s+nav\s+return\b', 'fund_pnav': r'\bfund\s+pnav\s+return\b',
                  'index': r'\b(?:benchmark|index)\s+return\b'}[item.series]
        if not re.search(marker, quote, re.I):
            continue
        group = result.series if item.basis == 'cumulative' else result.series_annualised
        series = group.get(item.series)
        attr = 'y' + years
        if series is not None and getattr(series, attr) is not None:
            continue
        if series is None:
            series = SeriesReturns(basis=item.basis)
            group[item.series] = series
        if series.basis != item.basis:
            continue
        setattr(series, attr, item.value)
        key = f"{item.series}.{'cum' if item.basis == 'cumulative' else 'ann'}.{item.period}"
        result.provisional_returns.append(key)
        recovered.append({'series': item.series, 'period': item.period, 'basis': item.basis, 'value': item.value,
                          'currency': item.currency.upper(), 'source': f'{sources[0][0]}, page {sources[0][1]}',
                          'excerpt': quote, 'evidence_level': 'provisional'})
    return result, recovered
