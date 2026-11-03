import copy
import json
from pathlib import Path

from fund_performance.charts import published_performance_charts

FACTS = json.loads((Path(__file__).parent / 'golden/demo_facts.json').read_text())


def test_published_returns_provide_charts_without_price_history(tmp_path):
    facts = copy.deepcopy(FACTS)
    before = copy.deepcopy(facts)
    panels = published_performance_charts(facts, tmp_path)
    assert {'cumulative', 'annualised'} <= {p['kind'] for p in panels}
    assert all(p['path'].stat().st_size > 0 for p in panels)
    assert facts == before
    assert 'not an observed price path' in panels[0]['caption']


def test_missing_periods_and_risk_metrics_do_not_block_remaining_charts(tmp_path):
    facts = copy.deepcopy(FACTS)
    facts['figures'] = [f for f in facts['figures'] if f['name'].endswith('5y')]
    panels = published_performance_charts(facts, tmp_path)
    assert 'annualised' in {p['kind'] for p in panels}


def test_empty_evidence_never_creates_invented_charts(tmp_path):
    assert published_performance_charts({}, tmp_path) == []
