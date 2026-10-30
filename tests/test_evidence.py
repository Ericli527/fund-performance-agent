""" The evidence dashboard's statistics (Phase C): yearly gaps, hit rate, the t-test and the peer percentile """
import pytest
from fund_performance.config import StatisticsSettings
from fund_performance.evidence import NOT_RELIABLE, build_evidence, peer_percentile, t_p_value, t_test, yearly_gaps
from fund_performance.models import Peer
from fund_performance.peers import compare_peers
from test_scorecard import T, figures, profile

STATS = StatisticsSettings(significance_level=0.05, min_points=8)


@pytest.mark.parametrize("t, df, p", [(2.262, 9, 0.05), (1.0, 9, 0.3434), (3.25, 9, 0.01), (0.0, 5, 1.0)])
def test_p_values_match_the_t_table(t, df, p):
    assert t_p_value(t, df) == pytest.approx(p, abs=5e-4)


def test_t_test_needs_8_points_and_unrounded_data():
    assert t_test([0.1] * 7, "x", STATS).result.startswith("Not run: 7 yearly values, at least 8")
    assert t_test([-0.1] * 6 + [0.0, 0.1], "x", STATS).result == NOT_RELIABLE      # most values identical
    significant = t_test([-0.30, -0.25, -0.31, -0.28, -0.35, -0.22, -0.27, -0.33, -0.29, -0.26], "x", STATS)
    assert significant.significant and significant.result.startswith("Statistically significant (p < 0.001)")
    chance = t_test([0.3, -0.2, 0.1, -0.4, 0.2, -0.1, 0.05, -0.15], "x", STATS)
    assert not chance.significant and chance.result.startswith("Not statistically significant (p = ")
    assert chance.result.endswith("the gap could be chance")


def calendar(**years):
    values = {}
    for y, (fund, index) in years.items():
        values[f"fund_pnav__calendar__{y[1:]}"] = fund
        values[f"index__calendar__{y[1:]}"] = index
    return figures(**values)


def test_yearly_gaps_prefer_pnav_and_the_statistics():
    rep = calendar(y2023=(10.0, 10.2), y2024=(20.0, 19.9), y2025=(5.0, 5.1))
    gaps, series = yearly_gaps(rep)
    assert series == "fund_pnav" and gaps == pytest.approx({"2023": -0.2, "2024": 0.1, "2025": -0.1})
    ev = build_evidence(rep, profile(ocf_pct=0.06, objective_type="index_tracker"), T, STATS)
    assert ev.hit_rate == (2, 3) and ev.hit_margin_pp == pytest.approx(0.16)     # within OCF + 0.10
    assert ev.best[0] == "2024" and ev.worst[0] == "2023" and ev.average == pytest.approx(-0.0667, abs=1e-4)
    assert ev.test.what == "fee-adjusted yearly gap (gap + OCF)" and ev.test.result.startswith("Not run")


def test_the_peer_percentile_needs_3_peers():
    prof = profile(currency="GBP", pricing_point="midday")
    rep = figures(fund_nav__ann__5y=10.0)
    peers = [Peer(name=f"P{i}", ocf_pct=0.1, currency="GBP", share_class="Acc", pricing_point="midday",
                  returns={"5y": r, "basis": "annualised"}) for i, r in enumerate((9.0, 9.5, 11.0))]
    assert peer_percentile(compare_peers(peers[:2], prof, rep)) is None
    assert peer_percentile(compare_peers(peers, prof, rep)) == {"beaten": 2, "peers": 3, "percentile": 67, "years": 5}
