"""Conservatively match extracted portfolio observations to the uploaded documents."""
import re
from fund_performance.agents.extractor import ExtractedExposure

MARKERS = {'holdings': r'\b(holdings?|positions?|top stocks?)\b', 'sectors': r'\b(sectors?|industr(?:y|ies))\b',
           'regions': r'\b(regions?|geograph(?:y|ic|ical)|countr(?:y|ies))\b',
           'currencies': r'\bcurrenc(?:y|ies)\b', 'asset_classes': r'\bassets?\b',
           'market_cap': r'\bmarket cap(?:italisation)?\b', 'concentration': r'\bconcentrat', 'portfolio_description': r'\bportfolio\b'}


def source_checked_exposures(candidates: list[ExtractedExposure], documents: dict[str, list[str]], *, subject: str = 'fund') -> dict:
    """Keep only excerpts naming the category, asset and exact percentage on a single page.

    Text matching establishes provenance, not that the extracted classification is necessarily correct.
    """
    groups = {key: [] for key in MARKERS}
    for item in candidates:
        quote = ' '.join(item.quote.split())
        if ((item.subject not in ('fund', 'unknown') if subject == 'fund' else item.subject != subject) or not quote or not item.name.strip()
                or (item.weight_pct is not None and not 0 <= item.weight_pct <= 100)):
            continue
        if (item.name.casefold() not in quote.casefold()
                or (subject == 'fund' and re.search(r'\b(?:benchmark|index)\s+(?:holdings|constituents|allocations)\b', quote, re.I))):
            continue
        # Legacy outputs without a subject require explicit fund and category context. New fund-labelled
        # observations remain provisional: text matching does not independently verify classification.
        if subject == 'fund' and item.subject == 'unknown' and (not re.search(MARKERS[item.category], quote, re.I)
                                          or not re.search(r'\bfund\b', quote, re.I)):
            continue
        if subject == 'unknown' and re.search(MARKERS[item.category], quote, re.I) and re.search(r'\bfund\b', quote, re.I):
            continue  # Legacy explicitly fund-labelled rows are already retained in the fund group.
        percentages = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%', quote)
        if item.weight_pct is not None and percentages and (len(percentages) != 1 or abs(float(percentages[0]) - item.weight_pct) >= 1e-9):
            continue
        for name, pages in documents.items():
            match = next((i for i, page in enumerate(pages, 1) if quote.casefold() in ' '.join(page.split()).casefold()), None)
            if match is not None:
                scope = ' '.join((item.scope_quote or '').split())
                if scope and scope.casefold() not in ' '.join(pages[match - 1].split()).casefold():
                    continue
                if item.weight_pct is not None and not percentages:
                    # PDFs often put (%) in the heading only. Accept a single exact numeric row,
                    # with the category's percentage heading on that same page; never a whole table.
                    rest = re.sub(re.escape(item.name), '', quote, count=1, flags=re.I)
                    numbers = re.findall(r'(?<![\d.])\d+(?:\.\d+)?', rest)
                    page = ' '.join(pages[match - 1].split())
                    heading = MARKERS[item.category] + r'[^%]{0,45}\(\s*%\s*\)'
                    if len(numbers) != 1 or abs(float(numbers[0]) - item.weight_pct) >= 1e-9 or not re.search(heading, page, re.I):
                        continue
                row = {'name': item.name, 'weight_pct': item.weight_pct, 'source': f'{name}, page {match}',
                       'excerpt': quote, 'subject': subject, 'evidence_level': 'provisional',
                       'qualification': 'AI-extracted; quotation matched, classification and date require review'}
                if scope:
                    row['scope_excerpt'] = scope
                if row not in groups[item.category]:
                    groups[item.category].append(row)
                break
    return {**{key: values or None for key, values in groups.items()},
            'unavailable': None if any(groups.values()) else 'No source-matched portfolio exposures were found.'}
