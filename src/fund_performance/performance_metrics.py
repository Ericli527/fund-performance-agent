"""Aggregate SDK-reported usage without retaining prompts, tool inputs or source text."""
from collections import defaultdict
from pathlib import Path

import yaml


def configured_prices() -> dict:
    """Optional local pricing must include provenance and an effective date; absent means unknown."""
    path = Path(__file__).resolve().parents[2] / 'config' / 'model_pricing.yaml'
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        return data.get('models', {}) if isinstance(data, dict) and isinstance(data.get('models', {}), dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def summary(calls: list[dict], elapsed_seconds: float, prices: dict | None = None) -> dict:
    """Prices, if explicitly configured, are USD per million input, cached input and output tokens."""
    grouped = defaultdict(list)
    for call in calls:
        grouped[(call.get('agent'), call.get('model'))].append(call)
    agents = []
    for (name, model), group in grouped.items():
        complete = all('tokens' in c for c in group)
        tokens = ({k: (sum(c['tokens'][k] for c in group) if all(c['tokens'].get(k) is not None for c in group) else None)
                   for k in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens')}
                  if complete else None)
        price = (prices or {}).get(model) or {}
        cost = None
        if tokens and tokens['cached_tokens'] is not None and tokens['input_tokens'] is not None and tokens['output_tokens'] is not None and price.get('source') and price.get('as_of') and all(
                isinstance(price.get(k), (int, float)) and not isinstance(price[k], bool) and price[k] >= 0
                for k in ('input', 'cached_input', 'output')):
            cached = tokens['cached_tokens']
            if 0 <= cached <= tokens['input_tokens']:
                cost = round(((tokens['input_tokens'] - cached) * price['input'] + cached * price['cached_input']
                              + tokens['output_tokens'] * price['output']) / 1_000_000, 8)
        agents.append({'agent': name, 'model': model, 'attempts': len(group),
                       'retries': sum(c.get('attempt', 1) > 1 for c in group),
                       'seconds': round(sum(c.get('seconds', 0) for c in group), 2),
                       'model_requests': sum(c['model_requests'] for c in group) if all('model_requests' in c for c in group) else None,
                       'tool_calls': sum(c['tool_calls'] for c in group) if all('tool_calls' in c for c in group) else None,
                       'tokens': tokens, 'estimated_cost_usd': cost})
    slowest = max(agents, key=lambda x: x['seconds'], default=None)
    priced = [a for a in agents if a['estimated_cost_usd'] is not None]
    costliest = max(priced, key=lambda x: x['estimated_cost_usd'], default=None)
    return {'elapsed_seconds': round(elapsed_seconds, 2), 'agents': agents,
            'slowest_agent': slowest['agent'] if slowest else None,
            'most_expensive_agent': costliest['agent'] if costliest else None,
            'cost_coverage_complete': bool(agents) and len(priced) == len(agents)}
