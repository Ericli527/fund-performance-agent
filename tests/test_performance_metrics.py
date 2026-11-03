import time
from types import SimpleNamespace

from agents.usage import Usage
from fund_performance.agents.base import AI_CALLS, _record
from fund_performance.performance_metrics import summary


def test_sdk_usage_details_tool_calls_and_pricing_are_counted_without_content():
    usage = Usage(input_tokens=1000, output_tokens=200, total_tokens=1200,
                  input_tokens_details={'cached_tokens': 400, 'cache_write_tokens': 0},
                  output_tokens_details={'reasoning_tokens': 80})
    response = SimpleNamespace(usage=usage, output=[SimpleNamespace(type='function_call'),
                                                    SimpleNamespace(type='message')])
    calls = []
    token = AI_CALLS.set(calls)
    try:
        _record(SimpleNamespace(name='Analyst', model='test-model'), 2, time.monotonic(), 'ok',
                SimpleNamespace(raw_responses=[response]))
    finally:
        AI_CALLS.reset(token)
    price = {'test-model': {'input': 2, 'cached_input': 1, 'output': 4,
                            'source': 'test pricing', 'as_of': '2026-01-01'}}
    metrics = summary(calls, 3, price)
    agent = metrics['agents'][0]
    assert agent['tokens']['cached_tokens'] == 400 and agent['tokens']['reasoning_tokens'] == 80
    assert agent['model_requests'] == 1 and agent['tool_calls'] == 1 and agent['retries'] == 1
    assert agent['estimated_cost_usd'] == 0.0024 and metrics['elapsed_seconds'] == 3
    assert metrics['slowest_agent'] == metrics['most_expensive_agent'] == 'Analyst'


def test_missing_usage_or_pricing_is_unknown_instead_of_zero_cost():
    calls = [{'agent': 'A', 'model': 'unknown', 'attempt': 1, 'seconds': 2, 'outcome': 'call failed'}]
    metrics = summary(calls, 5)
    assert metrics['agents'][0]['tokens'] is None and metrics['agents'][0]['model_requests'] is None
    assert metrics['agents'][0]['estimated_cost_usd'] is None and not metrics['cost_coverage_complete']
    assert metrics['most_expensive_agent'] is None
