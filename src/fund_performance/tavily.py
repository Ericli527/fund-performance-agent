"""Bounded Tavily search transport. Secrets and response/error bodies are never logged."""
import os
from urllib.parse import urlparse

import requests

from fund_performance.agents.base import load_env

ENDPOINT = 'https://api.tavily.com/search'
MAX_RESULTS = 3
MAX_CONTENT_CHARS = 6000


def _post(**kwargs):
    return requests.post(ENDPOINT, **kwargs)


def search(query: str, *, start_date: str | None = None, end_date: str | None = None,
           topic: str | None = None) -> tuple[list[dict], str | None]:
    load_env()
    key = os.getenv('TAVILY_API_KEY', '').strip()
    if not key:
        return [], 'Tavily search is unavailable: TAVILY_API_KEY is not configured.'
    options = {'query': query, 'search_depth': 'basic', 'max_results': MAX_RESULTS,
               'include_answer': False, 'include_raw_content': False}
    if start_date: options['start_date'] = start_date
    if end_date: options['end_date'] = end_date
    if topic: options['topic'] = topic
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
