"""Bounded Tavily search transport. Secrets and response/error bodies are never logged."""
import os
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

from fund_performance.agents.base import load_env

ENDPOINT = 'https://api.tavily.com/search'
MAX_RESULTS = 3
MAX_CONTENT_CHARS = 6000


def _post(**kwargs):
    return requests.post(ENDPOINT, **kwargs)


def publication_date(value: str | None) -> str | None:
    """Tavily news metadata may use ISO or RFC 2822; never infer a date from retrieval time."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def failure_code(error: str) -> str:
    """Map our own sanitised transport messages to stable diagnostic codes."""
    import re
    if 'TAVILY_API_KEY' in error:
        return 'tavily_not_configured'
    match = re.search(r'HTTP (\d{3})', error)
    if match:
        status = match.group(1)
        return {'401': 'tavily_authentication_failed', '403': 'tavily_access_denied',
                '429': 'tavily_rate_or_credit_limit', '432': 'tavily_rate_or_credit_limit'}.get(status, 'tavily_http_error')
    if 'no usable' in error:
        return 'no_search_results'
    if 'invalid search response' in error:
        return 'invalid_search_response'
    return 'tavily_connection_failed'


def search(query: str, *, start_date: str | None = None, end_date: str | None = None,
           topic: str | None = None, include_domains: list[str] | None = None) -> tuple[list[dict], str | None]:
    load_env()
    key = os.getenv('TAVILY_API_KEY', '').strip()
    if not key:
        return [], 'Tavily search is unavailable: TAVILY_API_KEY is not configured.'
    options = {'query': query, 'search_depth': 'basic', 'max_results': MAX_RESULTS,
               'include_answer': False, 'include_raw_content': False}
    if start_date: options['start_date'] = start_date
    if end_date: options['end_date'] = end_date
    if topic: options['topic'] = topic
    if include_domains: options['include_domains'] = include_domains
    try:
        response = _post(headers={'Authorization': f'Bearer {key}'},
                         json=options,
                         timeout=(5, 20), allow_redirects=False)
        if response.status_code != 200:
            return [], f'Tavily search is unavailable (HTTP {response.status_code}).'
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            return [], 'Tavily returned an invalid search response.'
        results = []
        for item in payload['results'][:MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            url, content = item.get('url'), item.get('content')
            if not isinstance(url, str) or not isinstance(content, str) or not content.strip():
                continue
            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                continue
            results.append({'url': url, 'title': str(item.get('title') or '')[:300],
                            'content': content[:MAX_CONTENT_CHARS],
                            'published_date': item.get('published_date') if isinstance(item.get('published_date'), str) else None,
                            'excerpt_truncated': len(content) > MAX_CONTENT_CHARS})
        return results, None if results else 'Tavily returned no usable search excerpts.'
    except (requests.RequestException, ValueError):
        return [], 'Tavily search could not be completed; try again later.'
