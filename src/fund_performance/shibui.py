"""Optional read-only market context from a fixed Shibui MCP query."""
import asyncio
import json
import logging
import os
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field, TypeAdapter

ENDPOINT = 'https://mcp.shibui.finance/mcp'
SYMBOL = 'SPY.NYSE'
SOURCE_URL = 'https://shibui.finance/data'
CHAT_REF = 'external:shibui:spy_direction'
BENCHMARK = re.compile(r'S\s*&\s*P\s*500(?:\s+Index)?(?:\s*\(NUK\)|\s+NUK)?', re.I)


class DailyClose(BaseModel):
    symbol: Literal['SPY.NYSE']
    date: date
    close: Decimal = Field(gt=0, allow_inf_nan=False)


ROWS = TypeAdapter(list[DailyClose])


def enabled() -> bool:
    return os.getenv('FUND_SHIBUI_ENABLED', '').strip().lower() in {'1', 'true', 'yes'}


def _rows(result: CallToolResult) -> list[DailyClose]:
    if not isinstance(result, CallToolResult) or result.is_error:
        raise ValueError('Shibui query failed')
    payload = result.structured_content
    if not payload and len(result.content) == 1 and isinstance(result.content[0], TextContent):
        payload = json.loads(result.content[0].text)
    if isinstance(payload, dict):
        payload = payload.get('rows', payload.get('data', payload.get('result')))
    if not isinstance(payload, list) or not 2 <= len(payload) <= 3:
        raise ValueError('Unexpected number of closes')
    return ROWS.validate_python(payload)


async def _query(cutoff: date) -> list[DailyClose]:
    earliest = cutoff - timedelta(days=10)
    sql = (
        f"SELECT symbol, date, close FROM shibui.stock_quotes WHERE symbol = '{SYMBOL}' "
        f"AND date >= DATE '{earliest.isoformat()}' AND date <= DATE '{cutoff.isoformat()}' "
        "ORDER BY date DESC LIMIT 3"
    )
    async with streamable_http_client(ENDPOINT, max_sse_event_size=65536) as (incoming, outgoing, _):
        async with ClientSession(incoming, outgoing) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool = next((tool for tool in tools.tools if tool.name == 'query'), None)
            if tool is None:
                raise ValueError('Shibui query tool unavailable')
            properties = tool.input_schema.get('properties', {})
            parameter = next((key for key in ('sql', 'query') if key in properties), None)
            if parameter is None or set(tool.input_schema.get('required', [])) - {parameter}:
                raise ValueError('Unsupported Shibui query schema')
            return _rows(await session.call_tool('query', {parameter: sql}))


async def market_context(benchmark: str | None, cutoff: date, *, historical: bool) -> dict | None:
    """Return direction and provenance only. Raw closes never enter the model's evidence."""
    if not enabled() or not BENCHMARK.fullmatch((benchmark or '').strip()):
        return None
    try:
        async with asyncio.timeout(8):
            rows = sorted(await _query(cutoff), key=lambda row: row.date)
        if (len({row.date for row in rows}) != len(rows)
                or rows[0].date < cutoff - timedelta(days=10) or rows[-1].date > cutoff):
            raise ValueError('Duplicate or out-of-window observations')
    except Exception as error:
        # Optional provider boundary, including MCP transport exception groups.
        logging.getLogger(__name__).warning('Shibui market context unavailable (%s)', type(error).__name__)
        return None
    first, last = rows[0], rows[-1]
    direction = 'rose' if last.close > first.close else 'fell' if last.close < first.close else 'was unchanged'
    return {
        'title': 'Shibui Finance MCP · SPY closing-price direction',
        'provider': 'Shibui Finance MCP', 'instrument': SYMBOL, 'measure': 'ETF daily close direction',
        'url': SOURCE_URL, 'date': last.date.isoformat(), 'date_basis': 'as_at', 'topic': 'market_drivers',
        'query': 'Bounded SPY daily closes',
        'summary': f'The US-listed ETF SPY closing price {direction} from {first.date} to {last.date}.',
        'scope': 'historical market context' if historical else 'current market context',
        'limitations': ('Use only for broad US equity context. SPY is a separate instrument from the fund and its '
                        'official benchmark. The price series excludes dividend adjustment. It cannot establish fund '
                        'NAV, total returns, tracking, or the cause of a fund outcome.'),
    }
