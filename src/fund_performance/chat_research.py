"""Five current-context searches using the existing Search Agent and Tavily; no fund-page refresh loop."""
import asyncio
import copy
from datetime import date, datetime, timedelta
from functools import partial
import ipaddress
import logging
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fund_performance.agents.research import PlannedSearch, search_one, same_url, MARKET_NOISE
from fund_performance.number_guard import check_numbers
from fund_performance.config import load_settings

LOOKBACK_DAYS = 90
NEWS_DOMAINS = ('reuters.com', 'ft.com', 'bloomberg.com', 'wsj.com', 'cnbc.com', 'bbc.com', 'bbc.co.uk',
                'spglobal.com', 'msci.com', 'ftserussell.com', 'lseg.com', 'morningstar.com',
                'bankofengland.co.uk', 'federalreserve.gov', 'ecb.europa.eu', 'imf.org', 'oecd.org',
                'fca.org.uk', 'esma.europa.eu', 'centralbank.ie', 'cssf.lu', 'sec.gov', 'iosco.org')
AUTHORITIES = {'GB': ('FCA UK', ('fca.org.uk',)), 'IE': ('Central Bank of Ireland ESMA', ('centralbank.ie', 'esma.europa.eu')),
               'LU': ('CSSF ESMA', ('cssf.lu', 'esma.europa.eu')), 'US': ('SEC', ('sec.gov',))}


def current_day() -> date:
    return datetime.now(ZoneInfo('Europe/London')).date()


def public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return False
        if re.search(r'[\s<>"\\]', url) or parsed.hostname == 'localhost' or parsed.hostname.endswith('.local'):
            return False
        try:
            return ipaddress.ip_address(parsed.hostname).is_global
        except ValueError:
            return '.' in parsed.hostname
    except ValueError:
        return False


def plan(seed: dict, exposures: dict | None = None, as_of: date | None = None) -> list[dict]:
    today = as_of or current_day()
    benchmark = str(seed.get('benchmark_name') or '')
    market = ' '.join(w for w in benchmark.split() if w.lower().strip('()') not in MARKET_NOISE)
    market = (market or str(seed.get('asset_class') or 'investment markets'))[:90]
    asset = str(seed.get('asset_class') or 'fund markets')[:40]
    names = [row['name'] for category in ('holdings', 'sectors', 'regions')
             for row in (exposures or {}).get(category) or [] if row.get('name') and row.get('subject') not in ('peer', 'benchmark', 'unknown')]
    exposure = ' '.join(names[:2])[:70] or market
    authority, _ = AUTHORITIES.get(str(seed.get('isin') or '')[:2].upper(), ('IOSCO fund regulation', ('iosco.org',)))
    window = f'{today - timedelta(days=LOOKBACK_DAYS):%Y-%m-%d} to {today:%Y-%m-%d}'
    topics = [('market_trends', f'{market} recent market trends volatility', 'Recent market conditions and risks relevant to the benchmark.'),
              ('macro_policy', f'{market} {asset} inflation interest rates currency news', 'Macro conditions, rates and currency transmission; not fund-specific attribution.'),
              ('portfolio_news', f'{exposure} earnings sector concentration latest news', 'Relevant portfolio/market developments; do not infer holdings from an index.'),
              ('material_changes', f'{market} index methodology corporate actions material changes news', 'New index or market developments, not a static fund profile or repeated fee lookup.'),
              ('regulation', f'{authority} investment funds {asset} regulatory policy updates', 'Dated regulatory changes; verify applicability and effective dates for this fund.')]
    return [{'category': category, 'query': f'{query[:150]} {window}', 'reason': reason} for category, query, reason in topics]


def _domain(host: str, domains) -> bool:
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def _dated_in_excerpt(source: dict, when: date) -> bool:
    from fund_performance.tavily import publication_date
    metadata = publication_date(source.get('retrieved_publication_date'))
    if metadata and source.get('date_basis') != 'as_at':
        return metadata == when.isoformat()
    text = ' '.join(str(source.get('source_excerpt') or '').lower().replace(',', '').split())
    variants = [when.isoformat(), when.strftime('%Y/%m/%d'),
                f'{when.day} {when:%B %Y}'.lower(), f'{when:%B} {when.day} {when.year}'.lower(),
                f'{when.day} {when:%b %Y}'.lower()]
    return any(value in text for value in variants)


def vet(source: dict, item: dict, seed: dict, as_of: date) -> str | None:
    if not public_url(source.get('url', '')):
        return 'unsafe_source_url'
    host = urlparse(source['url']).hostname.lower()
    domains = AUTHORITIES.get(str(seed.get('isin') or '')[:2].upper(), ('', ('iosco.org',)))[1] if item['category'] == 'regulation' else NEWS_DOMAINS
    if not _domain(host, domains):
        return 'source_not_in_current_research_publishers'
    try:
        when = date.fromisoformat(source.get('date') or '')
    except ValueError:
        return 'publication_date_unavailable'
    if not as_of - timedelta(days=LOOKBACK_DAYS) <= when <= as_of:
        return 'source_outside_recent_window'
    if not _dated_in_excerpt(source, when):
        return 'publication_date_not_supported_by_retrieval'
    title_url = (str(source.get('title') or '') + ' ' + source['url']).lower()
    if re.search(r'factsheet|fact-sheet|key.statistic|key.investor|kiid|charges-and-key|fund.profile', title_url):
        return 'static_fund_information_already_supplied'
    text = str(source.get('source_excerpt') or '')
    if not re.search(r'trend|earnings|inflation|interest|rate|volatil|concentrat|policy|regulat|change|rebalanc|outlook|rall|risk|corporate', text, re.I):
        return 'no_current_development_in_excerpt'
    if check_numbers(source.get('summary') or '', {'retrieved_excerpt': text}):
        return 'summary_numbers_not_in_source_excerpt'
    return None


async def current_research(seed: dict, exposures: dict | None = None, *, as_of: date | None = None,
                           run=None, retrieve=None) -> dict:
    from fund_performance.tavily import search
    seed = {key: value.isoformat() if isinstance(value, date) else value for key, value in seed.items()}
    today = as_of or current_day()
    start = today - timedelta(days=LOOKBACK_DAYS)
    items = plan(seed, exposures, today)
    context = {'fund_name': seed.get('fund_name'), 'benchmark': seed.get('benchmark_name'),
               'asset_class': seed.get('asset_class'), 'fund_review_date': seed.get('as_of_date')}
    async def one(item):
        diagnostic = {}
        domains = AUTHORITIES.get(str(seed.get('isin') or '')[:2].upper(), ('', ('iosco.org',)))[1] if item['category'] == 'regulation' else NEWS_DOMAINS
        try:
            query = PlannedSearch(topic='market_drivers', query=item['query'], reason=item['reason'])
            source, _ = await asyncio.wait_for(search_one(query, run, context,
                f'Current chat research window {start} to {today}. Prefer substantive dated news; exclude routine fund factsheets. '
                'This is current context, not information necessarily available at the historical fund review date.',
                retrieve=retrieve or partial(search, start_date=start.isoformat(), end_date=today.isoformat(),
                                             topic='general' if item['category'] == 'regulation' else 'news', include_domains=list(domains)),
                include_excerpt=True, diagnostics=diagnostic), timeout=load_settings().timeouts_seconds.research)
            issue = vet(source, item, seed, today) if source else diagnostic.get('reason', 'search_summary_failed')
            return source, issue, diagnostic
        except asyncio.TimeoutError:
            return None, 'search_timeout', diagnostic
        except Exception:
            return None, 'search_failed', diagnostic  # No provider response, source text or private prompt in diagnostics.
    results = await asyncio.gather(*(one(item) for item in items))
    kept, diagnostics, seen = [], [], set()
    for item, (source, issue, diagnostic) in zip(items, results):
        if not issue and same_url(source['url']) in seen:
            issue = 'duplicate_source'
        if not issue:
            seen.add(same_url(source['url']))
            source = copy.deepcopy(source)
            source.pop('source_excerpt', None)
            source['category'] = item['category']
            source['research_as_of'] = today.isoformat()
            source['fund_review_date'] = seed.get('as_of_date')
            reviewed = seed.get('as_of_date')
            source['timing'] = ('fund review date unavailable; current context only' if not reviewed else
                                'after fund review; current context only' if source['date'] > reviewed else 'published by fund review date')
            source['limitations'] = (source.get('limitations') or '') + ' Context relevance is not proof of fund-return attribution or regulatory applicability.'
            kept.append(source)
        status = 'kept' if not issue else 'excluded' if source else 'failed'
        diagnostics.append({'category': item['category'], 'query': item['query'], 'status': status, 'reason': issue,
                            'retrieved_count': diagnostic.get('retrieved_count', 0), 'stage': diagnostic.get('stage', 'retrieval')})
        if issue:
            logging.getLogger(__name__).info('Chat research %s: %s (%s)', item['category'], issue, status)
    result = {'status': 'complete' if len(kept) == 5 else 'partial' if kept else 'unavailable',
            'as_of_date': today.isoformat(), 'window_start': start.isoformat(), 'searches_requested': 5,
            'source_count': len(kept), 'sources': kept, 'searches': diagnostics}

    if not kept:
        reasons = sorted({item['reason'] for item in diagnostics if item['reason']})
        logging.getLogger(__name__).warning('Chat research unavailable: %s', ','.join(reasons))
    result['message'] = availability_message(result)
    return result


REASONS = {
    'tavily_not_configured': 'Tavily is not configured on the server',
    'tavily_authentication_failed': 'Tavily rejected its API credentials',
    'tavily_access_denied': 'Tavily denied access',
    'tavily_rate_or_credit_limit': 'Tavily reached a rate or credit limit',
    'tavily_http_error': 'the search provider returned an error',
    'tavily_connection_failed': 'the search provider could not be reached',
    'no_search_results': 'the searches returned no usable excerpts',
    'invalid_search_response': 'the search provider returned an invalid response',
    'search_summary_failed': 'the Search Agent could not produce a valid source summary',
    'summary_source_not_retrieved': 'the summary cited a source not returned by the search',
    'search_timeout': 'a search exceeded its time limit',
    'search_failed': 'a search could not complete',
    'publication_date_unavailable': 'a source date was unavailable',
    'publication_date_not_supported_by_retrieval': 'a source date could not be confirmed',
    'source_outside_recent_window': 'sources fell outside the requested dates',
    'source_not_in_current_research_publishers': 'sources were outside the accepted publishers',
    'summary_numbers_not_in_source_excerpt': 'summary figures were not supported by the excerpt',
    'duplicate_source': 'duplicate articles were removed',
    'static_fund_information_already_supplied': 'static fund information was excluded',
    'no_current_development_in_excerpt': 'an excerpt contained no current development',
    'unsafe_source_url': 'a source address failed safety checks',
}


def availability_message(result: dict) -> str:
    reasons = list(dict.fromkeys(item.get('reason') for item in result.get('searches', []) if item.get('reason')))
    count = result['source_count']
    text = f'{count} current source(s) retained from five searches.'
    if reasons:
        text += ' Coverage limits: ' + '; '.join(REASONS.get(reason, 'a source failed validation') for reason in reasons) + '.'
    if count == 0:
        text += ' Recent news could not be prepared; this does not mean there were no relevant developments. Prepare again to retry; server configuration may need attention for provider errors.'
    return text
