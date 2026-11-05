"""Realistic Tavily date formats and actionable research failure reasons, all mocked."""
import asyncio
from types import SimpleNamespace

import pytest

from conftest import FakeRunBy
from fund_performance import chat_research as research, tavily
from fund_performance.chatbot import with_research
from test_chat_enrichment import SEED, TODAY, excerpt, summary


@pytest.mark.parametrize('raw,expected', [
    ('Fri, 30 Oct 2026 08:00:00 GMT', '2026-10-30'),
    ('2026-10-30T08:00:00Z', '2026-10-30'), ('2026-10-30', '2026-10-30'),
    ('yesterday', None), (None, None)])
def test_provider_publication_dates_are_normalised_without_guessing(raw, expected):
    assert tavily.publication_date(raw) == expected


def test_rfc_dates_keep_five_valid_news_sources_even_when_excerpts_omit_dates():
    def retrieve(query):
        return [excerpt(query) | {'content': 'Market volatility and regulatory policy changed.',
                                  'published_date': 'Fri, 30 Oct 2026 08:00:00 GMT'}], None
    runner = FakeRunBy(lambda prompt: summary(prompt) | {'date': None, 'date_basis': None})
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=runner, retrieve=retrieve))
    assert result['source_count'] == 5 and len(runner.prompts) == 5
    assert all(source['date'] == '2026-10-30' and source['date_basis'] == 'published' for source in result['sources'])
    assert all('after fund review' in source['timing'] for source in result['sources'])
    assert all(item['retrieved_count'] == 1 for item in result['searches'])


def test_metadata_does_not_validate_a_conflicting_model_publication_date():
    source = {'url': 'https://reuters.com/news/market', 'title': 'Market update', 'date': '2026-10-29',
              'date_basis': 'published', 'retrieved_publication_date': 'Fri, 30 Oct 2026 08:00:00 GMT',
              'summary': 'Market volatility changed.', 'source_excerpt': 'On 29 October 2026 market volatility changed.'}
    assert research.vet(source, {'category': 'market_trends'}, SEED, TODAY) == 'publication_date_not_supported_by_retrieval'


@pytest.mark.parametrize('error,code,message', [
    ('Tavily search is unavailable: TAVILY_API_KEY is not configured.', 'tavily_not_configured', 'not configured'),
    ('Tavily search is unavailable (HTTP 401).', 'tavily_authentication_failed', 'credentials'),
    ('Tavily search is unavailable (HTTP 429).', 'tavily_rate_or_credit_limit', 'rate or credit'),
    ('Tavily returned no usable search excerpts.', 'no_search_results', 'no usable excerpts')])
def test_retrieval_failures_reach_the_chat_summary_without_calling_models(error, code, message):
    runner = FakeRunBy(lambda prompt: pytest.fail('A failed retrieval must not call the model'))
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=runner, retrieve=lambda query: ([], error)))
    assert result['source_count'] == 0 and all(item['reason'] == code for item in result['searches'])
    assert all(item['status'] == 'failed' for item in result['searches'])
    bundle = with_research({'profile': SEED, 'catalogue': {'evidence_limits': {}},
                            'input_files': [], 'notice': 'Fund evidence remains available.'}, result)
    assert message in bundle['summary'] and message in bundle['catalogue']['research_availability']['message']
    assert 'does not mean there were no relevant developments' in result['message']


def test_searches_request_the_publishers_and_regulator_the_validator_accepts(monkeypatch):
    options = []
    def search(query, **kwargs):
        options.append(kwargs)
        return [excerpt(query)], None
    monkeypatch.setattr(tavily, 'search', search)
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=FakeRunBy(summary)))
    assert result['source_count'] == 5 and len(options) == 5
    assert all('reuters.com' in item['include_domains'] for item in options[:4])
    assert options[-1]['include_domains'] == ['fca.org.uk'] and options[-1]['topic'] == 'general'
    assert all(item['start_date'] == '2026-08-07' and item['end_date'] == '2026-11-05' for item in options)


def test_transport_domain_filter_is_optional_and_not_added_to_reporting(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'fake')
    calls = []
    def post(**kwargs):
        calls.append(kwargs['json'])
        return SimpleNamespace(status_code=200, json=lambda: {'results': []})
    monkeypatch.setattr(tavily, '_post', post)
    tavily.search('ordinary reporting query')
    tavily.search('chat query', include_domains=['reuters.com'])
    assert 'include_domains' not in calls[0] and calls[1]['include_domains'] == ['reuters.com']
