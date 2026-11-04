import asyncio
from types import SimpleNamespace

import pytest
import requests

from conftest import FakeRun
from fund_performance import tavily
from fund_performance.agents.research import PlannedSearch, search_one, search_agent

QUERY = PlannedSearch(topic='market_drivers', query='Global equity review September 2026', reason='Market context')
RESULT = {'url': 'https://example.org/review', 'title': 'Market review',
          'content': 'Published 30 September 2026. Global equities moved higher.'}
SUMMARY = {'query': QUERY.query, 'summary': 'Global equities moved higher.', 'url': RESULT['url'],
           'date': '2026-09-30', 'date_basis': 'published'}


def test_transport_uses_one_basic_search_and_keeps_secret_out_of_result(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'test-secret')
    calls = []
    def post(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {'results': [RESULT]})
    monkeypatch.setattr(tavily, '_post', post)
    results, error = tavily.search(QUERY.query)
    assert not error and results[0]['url'] == RESULT['url'] and len(calls) == 1
    assert calls[0]['headers']['Authorization'] == 'Bearer test-secret'
    assert calls[0]['json']['search_depth'] == 'basic' and calls[0]['json']['max_results'] == 3
    assert not calls[0]['allow_redirects'] and 'test-secret' not in str(results)


@pytest.mark.parametrize('case', ['missing_key', 'http_error', 'bad_json', 'timeout', 'no_results'])
def test_errors_are_sanitised_and_never_retried(monkeypatch, case):
    monkeypatch.setattr(tavily, 'load_env', lambda: None)
    monkeypatch.setenv('TAVILY_API_KEY', '' if case == 'missing_key' else 'secret')
    calls = []
    def post(**kwargs):
        calls.append(kwargs)
        if case == 'timeout':
            raise requests.Timeout('secret provider response')
        def payload():
            if case == 'bad_json':
                raise ValueError('secret invalid response')
            return {'results': []}
        return SimpleNamespace(status_code=429 if case == 'http_error' else 200, json=payload)
    monkeypatch.setattr(tavily, '_post', post)
    result, error = tavily.search(QUERY.query)
    assert not result and error and 'secret' not in error
    assert len(calls) == (0 if case == 'missing_key' else 1)


def test_search_summary_uses_returned_source_and_no_openai_search_tool():
    runner = FakeRun(SUMMARY)
    result, _ = asyncio.run(search_one(QUERY, runner, retrieve=lambda query: ([RESULT], None)))
    assert result['retrieval_provider'] == 'tavily' and result['date'] == SUMMARY['date']
    assert 'Search excerpt only' in result['limitations']
    assert RESULT['content'] in runner.prompts[0] and search_agent().tools == []
    wrong = FakeRun(SUMMARY | {'url': 'https://invented.example/source'})
    result, error = asyncio.run(search_one(QUERY, wrong, retrieve=lambda query: ([RESULT], None)))
    assert result is None and 'not returned by Tavily' in error


def test_retrieval_failure_skips_model_call_without_fallback():
    runner = FakeRun(SUMMARY)
    result, error = asyncio.run(search_one(QUERY, runner, retrieve=lambda query: ([], 'Tavily is unavailable.')))
    assert result is None and error and runner.prompts == []
