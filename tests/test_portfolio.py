from fund_performance.agents.extractor import ExtractedExposure
from fund_performance.agents.planning_tools import PlanningContext, portfolio_exposures
from fund_performance.portfolio import source_checked_exposures
from test_investment_analyst import PROFILE


def candidate(**changes):
    value = {'category': 'holdings', 'name': 'Example Corp', 'weight_pct': 4.2,
             'quote': 'Fund holdings Example Corp 4.2%'}
    return ExtractedExposure.model_validate(value | changes)


def test_source_match_retains_page_and_isolates_each_run():
    values = source_checked_exposures([candidate()], {'fund.pdf': ['Fund holdings Example Corp 4.2%']})
    assert values['holdings'][0]['source'] == 'fund.pdf, page 1'
    assert values['sectors'] is None and values['concentration'] is None
    assert 'require review' in values['holdings'][0]['qualification']
    a, b = PlanningContext.of(PROFILE, exposures=values), PlanningContext.of(PROFILE, exposures=values)
    a.exposures['holdings'][0]['name'] = 'changed'
    assert portfolio_exposures(b.exposures)['holdings'][0]['name'] == 'Example Corp'


def test_invented_or_ambiguous_portfolio_items_are_not_used():
    text = {'fund.pdf': ['Fund holdings Example Corp 4.2%', 'Benchmark holdings Other Corp 8.0%',
                         'Fund holdings Example Corp 4.2% Other Corp 8.0%']}
    values = source_checked_exposures([candidate(weight_pct=4.3), candidate(name='Other Corp'),
        candidate(name='Other Corp', weight_pct=8.0, quote='Benchmark holdings Other Corp 8.0%'),
        candidate(quote='Fund holdings Example Corp 4.2% Other Corp 8.0%')], text)
    assert values['holdings'] is None and values['unavailable']


def test_index_fund_rows_and_qualitative_exposures_are_provisional():
    documents = {'fund.pdf': ['Index Fund\nTechnology 25.0%\nThe portfolio invests globally.\n'
                              'Benchmark holdings Other Corp 8.0%']}
    items = [candidate(category='sectors', name='Technology', weight_pct=25.0,
                       quote='Index Fund Technology 25.0%', subject='fund'),
             candidate(category='portfolio_description', name='invests globally', weight_pct=None,
                       quote='The portfolio invests globally.', subject='fund'),
             candidate(name='Other Corp', weight_pct=8.0, quote='Benchmark holdings Other Corp 8.0%',
                       subject='benchmark')]
    result = source_checked_exposures(items, documents)
    assert result['sectors'][0]['weight_pct'] == 25.0
    assert result['portfolio_description'][0]['weight_pct'] is None
    assert result['holdings'] is None and result['sectors'][0]['evidence_level'] == 'provisional'
