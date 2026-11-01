"""Conservatively match extracted portfolio observations to the uploaded documents."""
import re
from fund_performance.agents.extractor import ExtractedExposure

MARKERS = {'holdings': r'\b(holdings?|positions?)\b', 'sectors': r'\bsectors?\b',
           'regions': r'\b(regions?|geograph(?:y|ic|ical)|countr(?:y|ies))\b',
           'currencies': r'\bcurrenc(?:y|ies)\b'}


def source_checked_exposures(candidates: list[ExtractedExposure], documents: dict[str, list[str]]) -> dict:
    """Keep only excerpts naming the category, asset and exact percentage on a single page.

    Text matching establishes provenance, not that the extracted classification is necessarily correct.
    """
    groups = {key: [] for key in MARKERS}
    for item in candidates[:50]:
        quote = ' '.join(item.quote.split())
        if not 0 <= item.weight_pct <= 100 or len(quote) > 500 or not item.name.strip():
            continue
        if (not re.search(MARKERS[item.category], quote, re.I) or item.name.casefold() not in quote.casefold()
                or not re.search(r'\bfund\b', quote, re.I) or re.search(r'\b(benchmark|index)\b', quote, re.I)):
            continue
        percentages = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%', quote)
        if len(percentages) != 1 or abs(float(percentages[0]) - item.weight_pct) >= 1e-9:
            continue
        for name, pages in documents.items():
            match = next((i for i, page in enumerate(pages, 1) if quote.casefold() in ' '.join(page.split()).casefold()), None)
            if match is not None:
                row = {'name': item.name, 'weight_pct': item.weight_pct, 'source': f'{name}, page {match}',
                       'excerpt': quote, 'qualification': 'AI-extracted; quotation matched, classification requires review'}
                if row not in groups[item.category]:
                    groups[item.category].append(row)
                break
    return {**{key: values or None for key, values in groups.items()}, 'concentration': None,
            'unavailable': None if any(groups.values()) else 'No source-matched portfolio exposures were found.'}
