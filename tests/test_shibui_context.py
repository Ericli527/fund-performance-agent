"""Bound the MCP integration and protect instrument attribution in chat."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from fund_performance import shibui
from fund_performance.agents.chatbot import answer_question
from fund_performance.chatbot import evidence_key, prepare_session, reply
from mcp.types import CallToolResult, ListToolsResult, Tool


DAYS = [{'symbol': 'SPY.NYSE', 'date': '2026-11-17', 'close': '732.44'},
        {'symbol': 'SPY.NYSE', 'date': '2026-11-13', 'close': '754.37'}]


@pytest.fixture
def provider(monkeypatch):
    calls = []

    @asynccontextmanager
    async def transport(url, **kwargs):
        assert url == shibui.ENDPOINT
        yield None, None, None

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            schema = {'properties': {'sql': {'type': 'string'}}, 'required': ['sql']}
            return ListToolsResult(tools=[Tool(name='query', inputSchema=schema)])

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return CallToolResult(content=[], structuredContent={'rows': DAYS})

    monkeypatch.setenv('FUND_SHIBUI_ENABLED', 'true')
    monkeypatch.setattr(shibui, 'streamable_http_client', transport)
    monkeypatch.setattr(shibui, 'ClientSession', lambda *_: Session())
    return calls


def test_fixed_query_and_qualitative_only_evidence(provider):
    source = asyncio.run(shibui.market_context('S&P 500 Index NUK', date(2026, 11, 18), historical=False))
    name, args = provider[0]
    assert name == 'query' and "symbol = 'SPY.NYSE'" in args['sql']
    assert "date <= DATE '2026-11-18'" in args['sql'] and 'LIMIT 3' in args['sql']
    assert source['date'] == '2026-11-17' and 'fell' in source['summary']
    assert '732.44' not in str(source) and '754.37' not in str(source)
    assert source['instrument'] == 'SPY.NYSE'


def test_post_cutoff_rows_and_irrelevant_benchmarks_are_excluded(provider):
    assert asyncio.run(shibui.market_context('S&P 500', date(2026, 11, 16), historical=True)) is None
    assert "date <= DATE '2026-11-16'" in provider[0][1]['sql']
    assert asyncio.run(shibui.market_context('S&P 500 Equal Weight', date(2026, 11, 18), historical=False)) is None
    assert len(provider) == 1


def test_default_off_and_provider_failure(monkeypatch, provider):
    async def failed(_):
        raise OSError('offline')
    monkeypatch.setattr(shibui, '_query', failed)
    assert asyncio.run(shibui.market_context('S&P 500', date(2026, 11, 18), historical=False)) is None
    monkeypatch.delenv('FUND_SHIBUI_ENABLED')
    async def unexpected(_):
        pytest.fail('Disabled integration queried Shibui')
    monkeypatch.setattr(shibui, '_query', unexpected)
    assert asyncio.run(shibui.market_context('S&P 500', date(2026, 11, 18), historical=False)) is None


def test_chat_number_guard_cannot_match_raw_etf_close(provider):
    source = asyncio.run(shibui.market_context('S&P 500', date(2026, 11, 18), historical=False))
    catalogue = {shibui.CHAT_REF: source}

    async def run(agent, prompt):
        assert '732.44' not in prompt
        return SimpleNamespace(final_output={
            'status': 'answered', 'answer': 'The fund NAV was 732.44.',
            'evidence_references': [shibui.CHAT_REF], 'limitations': [],
            'security_issue': False, 'proposes_investment_decision': False,
        })

    response = asyncio.run(answer_question(catalogue, 'What happened to the fund?', run=run))
    assert 'withheld' in response and '732.44' not in response


def test_chat_prepares_market_context_once_and_reuses_it(provider, monkeypatch, tmp_path):
    from fund_performance import chatbot, chat_research
    from test_chatbot import entries
    from fund_performance.web import AiLimits, WebSettings

    async def prepare(*args, **kwargs):
        return {'profile': {'benchmark_name': 'S&P 500'}, 'catalogue': {},
                'input_files': [], 'notice': 'Prepared.', 'summary': 'Prepared.'}

    async def run(agent, prompt):
        assert shibui.CHAT_REF in prompt and '732.44' not in prompt
        return SimpleNamespace(final_output={
            'status': 'answered', 'answer': 'The SPY ETF close fell over the supplied period.',
            'evidence_references': [shibui.CHAT_REF], 'limitations': [],
            'security_issue': False, 'proposes_investment_decision': False,
        })

    monkeypatch.setattr(chatbot, 'ai_disabled', lambda: False)
    monkeypatch.setattr(chatbot, 'prepare_evidence', prepare)
    monkeypatch.setattr(chat_research, 'current_day', lambda: date(2026, 11, 18))
    selected = entries()
    limits = AiLimits(WebSettings(max_ai_runs_per_day=20, max_ai_runs_at_once=2), tmp_path / 'limits.json')

    async def scenario():
        state, summary = await prepare_session(selected, {}, {'key': evidence_key(selected, {})}, limits)
        assert 'US equity market context' in summary
        for _ in range(2):
            state, messages, _ = await reply(selected, {}, state, 'What did SPY do?', limits, run=run)
            assert 'https://shibui.finance/data' in messages[-1]['content']
        assert len(provider) == 1

    asyncio.run(scenario())


def test_full_review_supplies_historical_source_to_analyst(provider, monkeypatch, tmp_path):
    import json
    import shutil
    from datetime import timedelta
    from fund_performance.controller import run_review
    from test_chatbot import SAMPLE
    from test_controller import mocked

    folder = tmp_path / 'inputs'
    shutil.copytree(SAMPLE, folder)
    profile_file = folder / 'fund_profile.json'
    profile = json.loads(profile_file.read_text())
    profile['benchmark_name'] = 'S&P 500'
    profile_file.write_text(json.dumps(profile))
    review_day = date.fromisoformat(profile['as_of_date'])
    cutoff = review_day - timedelta(days=1)

    def rows(day):
        assert day == cutoff
        return shibui.ROWS.validate_python([
            row | {'date': (cutoff - timedelta(days=i)).isoformat()} for i, row in enumerate(DAYS)
        ])

    async def query(day):
        return rows(day)

    seen = []

    async def analyst(agent, prompt):
        seen.append(prompt)
        raise ValueError('Stop after inspecting the existing analyst prompt')

    monkeypatch.setattr(shibui, '_query', query)
    runners = mocked()
    runners.investment_analyst = analyst
    result = asyncio.run(run_review(folder, out_root=tmp_path / 'runs', runners=runners))
    assert seen and shibui.SYMBOL in seen[0] and '732.44' not in seen[0]
    sources = result.presentation_context['research']
    assert any(source['date'] == cutoff.isoformat() and source.get('instrument') == shibui.SYMBOL for source in sources)
