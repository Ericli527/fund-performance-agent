"""Chat presentation and seven-day research reuse the existing validated evidence."""
import asyncio
import json
from datetime import date

from conftest import FakeRun
from fund_performance import chat_research, chat_views
from fund_performance.agents.chatbot import answer_question
from test_chatbot import ANSWER, CATALOGUE

TODAY = date(2026, 11, 5)


def test_weekly_research_uses_inclusive_window_and_deduplicates(monkeypatch):
    from fund_performance import tavily
    calls = []

    def lookup(query, **kwargs):
        calls.append(kwargs)
        rows = [{'url': 'https://reuters.com/markets/update?topic=' + str(len(calls)),
                 'title': 'A market update', 'content': 'Market volatility increased. ' * 80,
                 'published_date': '2026-10-30'}]
        return rows + [
            rows[0] | {'url': 'https://reuters.com/old', 'published_date': '2026-10-29'},
            rows[0] | {'url': 'https://reuters.com/future', 'published_date': '2026-11-06'},
        ], None

    monkeypatch.setattr(tavily, 'search', lookup)
    snapshot = asyncio.run(chat_research.weekly_research({'isin': 'GB0000000000', 'as_of_date': '2026-09-30'}, as_of=TODAY))
    assert len(calls) == 5 and all(c['start_date'] == '2026-10-30' and c['end_date'] == '2026-11-06' for c in calls)
    assert snapshot['source_count'] == 1 and snapshot['window_start'] == '2026-10-30'
    article = snapshot['sources'][0]
    assert article['date'] == '2026-10-30' and article['timing'] == 'after fund review'
    assert len(article['excerpt']) <= 1000


def test_weekly_answer_one_call_with_dated_links_and_stale_fallback(monkeypatch):
    monkeypatch.setattr(chat_views, 'current_day', lambda: TODAY)
    coverage = {'window_start': '2026-10-30', 'as_of_date': '2026-11-05',
                'source_count': 1, 'refreshed_at': '2026-11-05T14:00+00:00'}
    article = {'date': '2026-11-04', 'title': 'US rate outlook changed',
               'publisher': 'reuters.com', 'url': 'https://reuters.com/markets/news',
               'excerpt': 'US inflation reshaped expectations for interest rates.', 'timing': 'after fund review'}
    catalogue = CATALOGUE | {'research_availability': coverage, 'research:1': article}
    response = FakeRun(ANSWER | {'answer': 'Interest rate expectations were a theme this week.',
        'limitations': [], 'evidence_references': ['research:1'],
        'weekly_developments': [{'reference': 'research:1', 'relevance': 'Rate expectations can affect equity valuations.'}]})
    question = chat_views.VIEW_QUESTIONS[2]
    text = asyncio.run(answer_question(catalogue, question, run=response))
    assert len(response.prompts) == 1
    prompt = json.loads(response.prompts[0])
    assert 'scorecard' not in prompt['evidence_catalogue']
    assert '2026-10-30 to 2026-11-05' in text and 'Coverage is partial' in text
    assert '04 Nov 2026 · [reuters.com](https://reuters.com/markets/news)' in text
    assert 'published after the fund review' in text and 'equity valuations' in text

    unsupported = FakeRun(ANSWER | {'answer': 'Interest rate expectations were a theme this week.',
        'limitations': [], 'evidence_references': ['research:1'],
        'weekly_developments': [{'reference': 'research:1', 'relevance': 'The fund gained 99.99%.'}]})
    text = asyncio.run(answer_question(catalogue, question, run=unsupported))
    assert 'US rate outlook changed' in text and '99.99%' not in text

    monkeypatch.setattr(chat_views, 'current_day', lambda: date(2026, 11, 6))
    stale = asyncio.run(answer_question(catalogue, question, run=response))
    assert 'refresh research' in stale and 'reuters.com' not in stale and len(response.prompts) == 1
    empty = asyncio.run(answer_question(CATALOGUE, question, run=response))
    assert 'Weekly research is unavailable' in empty and len(response.prompts) == 1


def test_benchmark_panel_shows_only_comparable_returns_and_fund_basis():
    fund_return = {'display': '11.31%'}
    row = {'as_of_date': '2026-09-30', 'fund_return_a_year': fund_return,
           'benchmark_return_a_year': {'display': '11.60%'}, 'fund_benchmark_basis': 'fund_pnav'}
    catalogue = CATALOGUE | {'performance:5y': row}
    panel = chat_views.fund_panel(catalogue, 'benchmark')
    assert 'Fund 11.31% · Benchmark 11.60%' in panel and 'illustrative' in panel
    panel = chat_views.fund_panel(catalogue | {'performance:5y': row | {'benchmark_return_a_year': None}}, 'benchmark')
    assert 'comparable fund and benchmark return pair is unavailable' in panel
    assert '11.31%' not in panel
