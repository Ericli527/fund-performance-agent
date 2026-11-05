"""Current chat research, composition scope and concise provenance, with no live calls."""
import asyncio
import copy
from datetime import date
from types import SimpleNamespace

import pytest

from conftest import FakeRun, FakeRunBy
from fund_performance import chat_research as research
from fund_performance.agents.chatbot import answer_question
from fund_performance.agents.extractor import ExtractedExposure
from fund_performance.chat_presentation import FOOTER
from fund_performance.portfolio import source_checked_exposures
from test_chatbot import ANSWER, CATALOGUE, entries, limits, session

TODAY = date(2026, 11, 5)
SEED = {'fund_name': 'Example US Index Fund', 'benchmark_name': 'S&P 500 Index', 'asset_class': 'equity',
        'isin': 'GB0000000000', 'as_of_date': '2026-09-30'}


def excerpt(query):
    category = next(item['category'] for item in research.plan(SEED, as_of=TODAY) if item['query'] == query)
    host = 'fca.org.uk' if category == 'regulation' else 'reuters.com'
    return {'url': f'https://{host}/news/{category}', 'title': f'{category} update',
            'content': 'Published 30 October 2026. Market volatility and regulatory policy changed.',
            'published_date': '2026-10-30'}


def retrieve(query):
    return [excerpt(query)], None


def summary(prompt):
    query = prompt.split('Search query: ', 1)[1].split('\n', 1)[0]
    item = excerpt(query)
    return {'query': query, 'summary': 'Recent market volatility and regulatory policy changed.',
            'url': item['url'], 'title': item['title'], 'date': '2026-10-30', 'date_basis': 'published'}


def test_five_searches_run_concurrently_and_retain_current_not_backdated_context():
    async def scenario():
        entered = 0
        ready = asyncio.Event()
        async def answer(prompt):
            nonlocal entered
            entered += 1
            if entered == 5:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            return summary(prompt)
        runner = FakeRunBy(answer)
        result = await research.current_research(SEED | {'as_of_date': date(2026, 9, 30)}, as_of=TODAY, run=runner, retrieve=retrieve)
        assert entered == 5 and result['source_count'] == 5 and result['status'] == 'complete'
        assert len({item['query'] for item in result['searches']}) == 5
        assert all('after fund review' in source['timing'] for source in result['sources'])
        assert all('source_excerpt' not in source for source in result['sources'])
        assert not any('factsheet' in item['query'].lower() or SEED['fund_name'] in item['query'] for item in result['searches'])
        assert any('FCA UK' in item['query'] for item in result['searches'])
    asyncio.run(scenario())


@pytest.mark.parametrize('changes,reason', [
    ({'url': 'http://localhost/private'}, 'unsafe_source_url'),
    ({'url': 'https://untrusted.example/news'}, 'source_not_in_current_research_publishers'),
    ({'date': None}, 'publication_date_unavailable'),
    ({'date': '2026-11-06'}, 'source_outside_recent_window'),
    ({'date': '2026-01-01'}, 'source_outside_recent_window'),
    ({'date': '2026-10-29'}, 'publication_date_not_supported_by_retrieval'),
    ({'title': 'Fund factsheet'}, 'static_fund_information_already_supplied'),
    ({'summary': 'Markets gained 99.9%.'}, 'summary_numbers_not_in_source_excerpt'),
])
def test_current_source_validation_keeps_dates_provenance_and_numeric_checks(changes, reason):
    source = {'url': 'https://reuters.com/news/market', 'title': 'Market update', 'date': '2026-10-30',
              'summary': 'Market volatility changed.', 'source_excerpt': '30 October 2026. Market volatility changed.'}
    assert research.vet(source | changes, {'category': 'market_trends'}, SEED, TODAY) == reason


def test_failed_searches_preserve_successful_sources():
    def partial_retrieve(query):
        if 'regulatory' in query:
            raise RuntimeError('private provider error')
        if 'inflation' in query:
            return [], 'unavailable'
        return retrieve(query)
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=FakeRunBy(summary), retrieve=partial_retrieve))
    assert result['source_count'] == 3 and result['status'] == 'partial'
    assert 'private provider error' not in str(result)
    assert len(result['searches']) == 5


def test_slow_search_is_bounded_without_losing_others(monkeypatch):
    monkeypatch.setattr(research, 'load_settings', lambda: SimpleNamespace(timeouts_seconds=SimpleNamespace(research=1)))
    async def respond(prompt):
        if 'regulatory policy updates' in prompt:
            await asyncio.sleep(10)
        return summary(prompt)
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=FakeRunBy(respond), retrieve=retrieve))
    assert result['source_count'] == 4
    assert result['searches'][-1]['reason'] == 'search_timeout'


def test_refresh_reuses_fund_extraction_and_followups_reuse_research(monkeypatch, limits):
    from fund_performance.chatbot import prepare_session, reply
    monkeypatch.setattr(research, 'current_day', lambda: TODAY)
    selected = entries()
    state = session(selected)
    state['bundle']['profile'] = SEED
    state['bundle']['input_files'] = ['fund_profile.json']
    state['bundle']['notice'] = 'Prepared evidence.'
    state['bundle']['highlights'] = []
    state['history'] = [{'role': 'user', 'content': 'Old question'}]
    before = copy.deepcopy(state)
    runner = FakeRunBy(summary)
    async def forbidden(*args, **kwargs):
        raise AssertionError('Prepared documents must not be extracted again')
    prepared, _ = asyncio.run(prepare_session(selected, {}, state, limits, reader=forbidden,
                                             research_run=runner, retrieve=retrieve))
    assert prepared['bundle']['research']['source_count'] == 5 and len(runner.prompts) == 5
    assert prepared['history'] == [] and state == before and limits.active == 0
    more, _, _ = asyncio.run(reply(selected, {}, prepared, 'Fees?', limits, run=FakeRun(ANSWER)))
    assert len(runner.prompts) == 5 and more['bundle'] is prepared['bundle']


def test_research_starts_during_intake_and_cancellation_leaves_no_background_task(monkeypatch, tmp_path):
    import fund_performance.chatbot as chat
    started, finished = [], []
    async def current(seed, exposures, **kwargs):
        started.append(seed)
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(True)
    async def failed(*args, on_fund_context=None, **kwargs):
        on_fund_context({'fund_facts': SEED})
        await asyncio.sleep(0)
        assert started
        raise ValueError('bad input')
    monkeypatch.setattr(research, 'current_research', current)
    monkeypatch.setattr(chat, '_prepare_evidence', failed)
    with pytest.raises(ValueError):
        asyncio.run(chat.prepare_evidence([], {}, tmp_path, research_enabled=True))
    assert len(started) == len(finished) == 1


def test_percent_column_rows_keep_composition_and_benchmark_scope():
    page = ('Top Stocks (%) Index\nNVIDIA CORP 8.4\nAPPLE INC 7.4\n'
            'Sector/Industry Breakdown (%) Index\nInformation Technology 39.7\n'
            'Geographic Breakdown (%) Index\nUSA 99.7\nMarket Cap Breakdown (%) Index\n>10bn 99.2')
    rows = [('holdings', 'NVIDIA CORP', 8.4), ('sectors', 'Information Technology', 39.7),
            ('regions', 'USA', 99.7), ('market_cap', '>10bn', 99.2)]
    candidates = [ExtractedExposure(category=category, name=name, weight_pct=value,
                    quote=f'{name} {value}', subject='benchmark') for category, name, value in rows]
    benchmark = source_checked_exposures(candidates, {'factsheet.pdf': [page]}, subject='benchmark')
    assert all(benchmark[category][0]['weight_pct'] == value for category, _, value in rows)
    assert benchmark['holdings'][0]['source'] == 'factsheet.pdf, page 1'
    assert benchmark['market_cap'][0]['subject'] == 'benchmark'
    assert source_checked_exposures(candidates, {'factsheet.pdf': [page]})['holdings'] is None
    bad = [candidates[0].model_copy(update={'weight_pct': 7.4}),
           candidates[0].model_copy(update={'quote': 'NVIDIA CORP 8.4 APPLE INC 7.4'})]
    assert source_checked_exposures(bad, {'factsheet.pdf': [page]}, subject='benchmark')['holdings'] is None
    assert source_checked_exposures([candidates[0]], {'factsheet.pdf': ['NVIDIA CORP 8.4']}, subject='benchmark')['holdings'] is None


def test_generic_ai_notice_once_but_actual_limit_and_pricing_warning_remain():
    out = ANSWER | {'answer': 'The ongoing charge is 0.23%. These figures are provisional and should be checked against the source documents; the market-close price is illustrative, not a dealing price.',
                    'limitations': ['AI-extracted figures require verification against the source documents.',
                                    'Sector weights are missing; AI-extracted information requires source verification.']}
    text = asyncio.run(answer_question(CATALOGUE, 'Explain', run=FakeRun(out)))
    assert text.count(FOOTER) == 1 and 'Sector weights are missing' in text
    assert 'not a dealing price' in text
    assert 'require verification' not in text and 'should be checked' not in text
    assert 'requires source verification' not in text


def test_vetted_research_can_be_cited_without_repeating_private_excerpt():
    catalogue = CATALOGUE | {'research:1': {'url': 'https://reuters.com/news/market', 'date': '2026-10-30',
                              'title': 'Market update', 'summary': 'Market volatility increased.', 'timing': 'after fund review'}}
    out = ANSWER | {'answer': 'Recent market volatility increased. This is current context, published after the fund review.',
                    'evidence_references': ['research:1'], 'limitations': []}
    text = asyncio.run(answer_question(catalogue, 'Recent news?', run=FakeRun(out)))
    assert '[Market update](https://reuters.com/news/market)' in text and '2026-10-30' in text
    assert 'withheld' not in text


def test_composition_flows_from_extraction_to_chat_catalogue_without_another_read(tmp_path):
    from test_intake import FACTSHEET, MANDATE, extractor_answer
    from fund_performance.attachments import FACTSHEET as ROLE
    from fund_performance.intake import read_documents
    from fund_performance.chatbot import prepare_evidence
    path = tmp_path / 'factsheet.txt'
    path.write_text(FACTSHEET + '\nTop Stocks (%) Index\nExample Corp 8.4\n'
                    'Market Cap Breakdown (%) Index\nLarge 99.2\nFund sectors Technology 25.0%')
    output = extractor_answer() | {'exposures': [
        {'category': 'holdings', 'name': 'Example Corp', 'weight_pct': 8.4,
         'quote': 'Example Corp 8.4', 'subject': 'benchmark'},
        {'category': 'market_cap', 'name': 'Large', 'weight_pct': 99.2,
         'quote': 'Large 99.2', 'subject': 'benchmark'},
        {'category': 'sectors', 'name': 'Technology', 'weight_pct': 25.0,
         'quote': 'Fund sectors Technology 25.0%', 'subject': 'fund'}]}
    extractor = FakeRun(output)
    async def reader(*args, **kwargs):
        return await read_documents(*args, **kwargs, run_extractor=extractor, run_mandate=FakeRun(MANDATE))
    bundle = asyncio.run(prepare_evidence([{'id': 'fund', 'path': str(path), 'role': ROLE}], {}, tmp_path, reader=reader))
    composition = bundle['catalogue']['fund_composition']
    assert composition['benchmark']['market_cap'][0]['weight_pct'] == 99.2
    assert composition['benchmark']['holdings'][0]['name'] == 'Example Corp'
    assert composition['fund']['holdings'] is None
    assert composition['fund']['sectors'][0]['weight_pct'] == 25.0
    answer = ANSWER | {'answer': 'The factsheet reports Example Corp at 8.4% of the index and large-cap exposure at 99.2%. These are benchmark weights, not verified fund holdings. The fund sector table reports Technology at 25.0%.',
        'evidence_references': ['fund_composition'], 'limitations': []}
    text = asyncio.run(answer_question(bundle['catalogue'], 'Composition?', run=FakeRun(answer)))
    assert 'withheld' not in text and '8.4%' in text and len(extractor.prompts) == 1


def test_tavily_current_dates_are_optional_and_explicit(monkeypatch):
    from fund_performance import tavily
    monkeypatch.setenv('TAVILY_API_KEY', 'fake')
    bodies = []
    def post(**kwargs):
        bodies.append(kwargs['json'])
        return SimpleNamespace(status_code=200, json=lambda: {'results': [excerpt(research.plan(SEED, as_of=TODAY)[0]['query'])]})
    monkeypatch.setattr(tavily, '_post', post)
    tavily.search('ordinary reporting search')
    tavily.search('current chat search', start_date='2026-08-07', end_date='2026-11-05', topic='news')
    assert not {'start_date', 'end_date', 'topic'} & bodies[0].keys()
    assert bodies[1]['start_date'] == '2026-08-07' and bodies[1]['end_date'] == '2026-11-05'
    assert bodies[1]['topic'] == 'news' and bodies[1]['search_depth'] == 'basic'


def test_numeric_validation_reason_is_specific_without_logging_private_answer(caplog):
    text = asyncio.run(answer_question(CATALOGUE, 'Fees?', run=FakeRun(ANSWER | {'answer': 'Private draft: 99.99%.'})))
    assert 'numerical detail in the AI draft could not be confirmed' in text
    assert 'Source-based fund overview' in text and '99.99' not in text
    assert 'unsupported_number_or_unit' in caplog.text and 'Private draft' not in caplog.text


def test_duplicate_sources_are_not_presented_as_five_independent_articles():
    def same_retrieval(query):
        item = excerpt(query) | {'url': 'https://reuters.com/news/common'}
        return [item], None
    def same_summary(prompt):
        return summary(prompt) | {'url': 'https://reuters.com/news/common'}
    result = asyncio.run(research.current_research(SEED, as_of=TODAY, run=FakeRunBy(same_summary), retrieve=same_retrieval))
    assert result['source_count'] == 1
    assert sum(item['reason'] == 'duplicate_source' for item in result['searches']) == 3
    assert result['searches'][-1]['reason'] == 'source_not_in_current_research_publishers'


@pytest.mark.parametrize('notice', ['AI-extracted figures remain provisional.',
    'The extracted information should be verified against the source documents.',
    'AI extraction and text matching are not independent verification.'])
def test_standalone_provenance_is_not_a_missing_evidence_limit(notice):
    from fund_performance.chat_presentation import specific_limits
    assert specific_limits(notice) == ''
    assert specific_limits('The five-year return was recovered provisionally from conflicting sources.')
