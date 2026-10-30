""" Scorecard (spec 6): every branch with made-up figures, then Test 1 end to end """
import json
import pytest
from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import load_thresholds
from fund_performance.io import read_json, read_prices
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, Figure, FundProfile, Peer
from fund_performance.precedence import ReportedFigures, apply_precedence
from fund_performance import scorecard as sc
from fund_performance.scorecard import AMBER, CHECK_DATA, GREEN, MANUAL_CHECK, RED
from conftest import FIXTURES, TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1

T = load_thresholds()


def profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text())
                                      | {"ocf_pct": 0.06} | changes)


def figures(**values) -> ReportedFigures:
    """ Reported figures by name; '__' stands for '.' (e.g. fund_nav__ann__5y=13.8) """
    rep = ReportedFigures()
    for name, value in values.items():
        rep.figures[name.replace("__", ".")] = Figure(value=value, exact=value, unit="%", source="factsheet")
    return rep


def index_fund(td=-0.10, te=0.02, r2=1.0, beta=1.0, **extra):
    return figures(fund_nav__ann__5y=13.9 + td, index__ann__5y=13.9, risk__pnav__tracking_error__3y=te,
                   risk__pnav__r2__3y=r2, risk__pnav__beta__3y=beta, **extra)


def path(prof, short=False, flags=()):
    return decision_path(prof, short, list(flags))


def peer(ocf=0.03, y5=13.48, basis="annualised", currency="GBP"):
    return Peer(name="Peer Tracker", ocf_pct=ocf, currency=currency, share_class="Acc",
                returns={"5y": y5, "basis": basis})


def test_weakest():
    assert sc.weakest([GREEN, AMBER]) == AMBER and sc.weakest([AMBER, RED, GREEN]) == RED
    assert sc.weakest([GREEN, CHECK_DATA, RED]) == CHECK_DATA


# 6.1 Mandate
@pytest.mark.parametrize("r2,beta,expected", [(1.0, 1.0, GREEN), (0.96, 1.0, AMBER), (0.99, 1.08, AMBER),
                                              (0.90, 1.0, RED), (0.99, 1.20, RED), (0.96, 1.08, AMBER)])
def test_index_mandate_bands(r2, beta, expected):
    assert sc.mandate_rating(index_fund(r2=r2, beta=beta), profile(), T).rating == expected


def test_index_mandate_prefers_calculated_r2_and_beta_from_an_index_series():
    rep = index_fund(r2=1.0, beta=1.0, relative__r2__5y=0.90, relative__beta__5y=1.0)
    pillar = sc.mandate_rating(rep, profile(), T)
    assert pillar.rating == RED and "5y (calculated)" in pillar.reason


def test_mandate_without_r2_or_beta_is_check_data():
    assert sc.mandate_rating(figures(), profile(), T).rating == CHECK_DATA


def test_active_mandate_is_a_manual_check():
    pillar = sc.mandate_rating(index_fund(), profile(objective_type="active_target"), T)
    assert (pillar.rating, pillar.reason) == (MANUAL_CHECK, "Style and holdings need a reviewer check")


# 6.2 Performance, index funds: TD and TE rated separately, the weaker one wins
@pytest.mark.parametrize("td,expected", [(-0.10, GREEN), (0.16, GREEN), (-0.30, AMBER), (-0.36, AMBER), (-0.40, RED)])
def test_tracking_difference_bands(td, expected):
    prof = profile()
    [td_sub, _], _ = sc._index_tests(index_fund(td=td), prof, path(prof), T, "fund_nav", 0.0)
    assert td_sub.rating == expected


@pytest.mark.parametrize("te,expected", [(0.02, GREEN), (0.30, GREEN), (0.80, AMBER), (1.00, AMBER), (1.50, RED)])
def test_tracking_error_bands(te, expected):
    prof = profile()
    [_, te_sub], _ = sc._index_tests(index_fund(te=te), prof, path(prof), T, "fund_nav", 0.0)
    assert te_sub.rating == expected


def test_three_percent_behind_with_low_tracking_error_is_red():
    prof = profile()
    pillar = sc.performance_rating(index_fund(td=-3.0, te=0.05), prof, path(prof), T, "fund_nav")
    assert pillar.rating == RED
    assert [(s.name, s.rating) for s in pillar.sub_ratings] == [("Tracking difference", RED), ("Tracking error", GREEN)]
    assert pillar.reason.startswith("Tracking difference RED")


def test_high_tracking_error_alone_makes_performance_weaker():
    prof = profile()
    pillar = sc.performance_rating(index_fund(td=-0.05, te=0.8), prof, path(prof), T, "fund_nav")
    assert pillar.rating == AMBER and pillar.reason.startswith("Tracking error AMBER")


def test_factsheet_te_period_is_labelled_and_the_difference_noted():
    prof = profile()
    pillar = sc.performance_rating(index_fund(), prof, path(prof), T, "fund_nav")
    assert "3y (factsheet)" in pillar.sub_ratings[1].reason
    assert "Periods differ: tracking difference is 5y, tracking error is 3y (factsheet)" in pillar.notes


def test_calculated_5y_te_is_used_when_an_index_series_exists():
    prof = profile()
    pillar = sc.performance_rating(index_fund(te=0.02, relative__tracking_error__5y=0.5), prof, path(prof), T, "fund_nav")
    assert "0.50%, 5y (calculated)" in pillar.sub_ratings[1].reason and pillar.notes == []


def test_timing_difference_widens_the_td_tolerance():
    prof = profile()
    without = sc.performance_rating(index_fund(td=-0.30), prof, path(prof), T, "fund_nav", 0.0)
    widened = sc.performance_rating(index_fund(td=-0.30), prof, path(prof), T, "fund_nav", 0.20)
    assert (without.rating, widened.rating) == (AMBER, GREEN)
    assert any("Tolerance widened by 0.20 pp" in n for n in widened.notes)


def test_missing_te_is_check_data():
    prof = profile()
    rep = figures(fund_nav__ann__5y=13.8, index__ann__5y=13.9)
    assert sc.performance_rating(rep, prof, path(prof), T, "fund_nav").rating == CHECK_DATA


# Short history: since-launch figures, at least Amber, never Red on history alone
def test_short_history_green_becomes_amber_with_the_reason():
    prof = profile(time_horizon_years=5)
    rep = figures(fund_nav__since_launch__ann=10.0, index__since_launch__ann=10.05, risk__pnav__tracking_error__3y=0.05)
    pillar = sc.performance_rating(rep, prof, path(prof, short=True), T, "fund_nav")
    assert pillar.rating == AMBER and pillar.reason.startswith("track record shorter than the fund's time horizon")
    assert "since launch" in pillar.sub_ratings[0].reason


def test_short_history_is_never_red_on_history_alone_but_poor_figures_still_are():
    prof = profile()
    poor = figures(fund_nav__since_launch__ann=7.0, index__since_launch__ann=10.0, risk__pnav__tracking_error__3y=0.05)
    pillar = sc.performance_rating(poor, prof, path(prof, short=True), T, "fund_nav")
    assert pillar.rating == RED and "Tracking difference RED" in pillar.reason
    assert "Short history: track record shorter than the fund's time horizon" in pillar.notes


# Active funds with a target
def _active(excess, windows):
    values = {"fund_nav__ann__5y": 10.0 + excess, "index__ann__5y": 10.0}
    for i, (f, b) in enumerate(windows):
        values[f"fund_nav__discrete_12m__202{i + 2}-09-30"] = f
        values[f"index__discrete_12m__202{i + 2}-09-30"] = b
    return figures(**values)


@pytest.mark.parametrize("excess,beats,expected", [(0.5, 4, GREEN), (0.5, 2, AMBER), (-0.5, 4, AMBER),
                                                  (-1.5, 4, RED), (0.0, 3, GREEN)])
def test_active_target_bands(excess, beats, expected):
    windows = [(11.0, 10.0)] * beats + [(9.0, 10.0)] * (5 - beats)
    prof = profile(objective_type="active_target")
    pillar = sc.performance_rating(_active(excess, windows), prof, path(prof), T, "fund_nav")
    assert pillar.rating == expected and f"hit rate {beats} of 5" in pillar.reason


# Dual objective: each rated, the weaker one wins
def test_dual_objective_takes_the_weaker_rating():
    prof = profile(secondary_objective="active_target")
    rep = index_fund(td=-0.05, te=0.02)                        # tracking Green; vs target -0.05 with no windows
    rep.figures.update(figures(fund_nav__ann__5y=8.0, index__ann__5y=10.0).figures)   # 2% behind the target
    pillar = sc.performance_rating(rep, prof, path(prof), T, "fund_nav")
    assert pillar.rating == RED and "Dual objective" in pillar.notes[-1]
    assert [s.name for s in pillar.sub_ratings] == ["Tracking difference", "Tracking error", "Excess return vs target"]


def test_secondary_objective_that_is_not_a_known_type_is_check_data():
    prof = profile(secondary_objective="grow income over time")
    assert sc.performance_rating(index_fund(), prof, path(prof), T, "fund_nav").rating == CHECK_DATA


@pytest.mark.parametrize("objective", ["active_comparator", "active_constraint", "income_target", "absolute_return"])
def test_objective_types_without_input_data_are_check_data(objective):
    prof = profile(objective_type=objective)
    pillar = sc.performance_rating(index_fund(), prof, path(prof), T, "fund_nav")
    assert pillar.rating == CHECK_DATA and "needs" in pillar.reason


# 6.3 Value
@pytest.mark.parametrize("peer_5y,expected", [(13.85, GREEN), (13.90, GREEN), (13.98, AMBER), (14.30, AMBER), (14.40, RED), (12.0, GREEN)])
def test_value_bands(peer_5y, expected):
    rep = figures(fund_nav__ann__5y=13.8)
    assert sc.value_rating(rep, profile(), T, peer(y5=peer_5y)).rating == expected


def test_value_converts_a_cumulative_peer_return():
    rep = figures(fund_nav__ann__5y=13.8)
    pillar = sc.value_rating(rep, profile(), T, peer(y5=91.6, basis="cumulative"))       # 13.89% a year
    assert pillar.rating == GREEN and "+0.09 pp" in pillar.reason


def test_no_peer_is_amber_add_peer():
    pillar = sc.value_rating(figures(fund_nav__ann__5y=13.8), profile(), T, None)
    assert (pillar.rating, pillar.reason, pillar.summary) == (AMBER, "no comparison available", "Add peer")


def test_a_peer_in_another_currency_counts_for_fees_only():
    pillar = sc.value_rating(figures(fund_nav__ann__5y=13.8), profile(), T, peer(currency="EUR"))
    assert (pillar.rating, pillar.summary) == (AMBER, "Add peer") and "returns in EUR, not GBP" in pillar.reason
    assert sc.fees_rating(profile(ocf_pct=0.06), T, peer(ocf=0.03, currency="EUR"), GREEN).rating == GREEN


# 6.4 Fees
@pytest.mark.parametrize("ocf,expected", [(0.06, GREEN), (0.08, GREEN), (0.20, AMBER), (0.23, AMBER), (0.30, RED)])
def test_index_fee_bands(ocf, expected):
    assert sc.fees_rating(profile(ocf_pct=ocf), T, peer(ocf=0.03), GREEN).rating == expected


@pytest.mark.parametrize("ocf,performance,expected", [
    (0.50, GREEN, GREEN), (0.80, GREEN, AMBER), (0.80, RED, RED),
    (0.80, AMBER, AMBER), (0.50, RED, AMBER)])          # the last two are the cases the spec leaves open
def test_active_fee_rules(ocf, performance, expected):
    pillar = sc.fees_rating(profile(objective_type="active_target", ocf_pct=ocf), T, peer(ocf=0.60), performance)
    assert pillar.rating == expected and pillar.notes == []


def test_performance_fee_without_justification_is_at_least_amber():
    pillar = sc.fees_rating(profile(performance_fee=True), T, peer(ocf=0.06), GREEN)
    assert pillar.rating == AMBER and "not justified in the profile" in pillar.notes[0]


def test_performance_fee_justified_by_a_person_keeps_the_rating():
    prof = profile(performance_fee=True, performance_fee_justification="Hurdle and high-water mark; agreed by the board")
    pillar = sc.fees_rating(prof, T, peer(ocf=0.06), GREEN)
    assert pillar.rating == GREEN and "justified in the profile: Hurdle" in pillar.notes[0]


# 6.5 Verdict
def _pillars(**ratings):
    return {name: sc.Pillar(name, r, sc.NO_PEER if name in ("Value for investors", "Fees") and r == AMBER else "x")
            for name, r in ratings.items()}


@pytest.mark.parametrize("ratings,expected", [
    ((GREEN, GREEN, GREEN, GREEN), "Retain"),
    ((GREEN, RED, GREEN, GREEN), "Review"),
    ((GREEN, AMBER, GREEN, GREEN), "Monitor"),
    ((GREEN, GREEN, AMBER, AMBER), "Monitor until a peer is added"),
    ((GREEN, AMBER, AMBER, AMBER), "Monitor"),
    ((CHECK_DATA, GREEN, GREEN, GREEN), "Pending data check"),
    ((GREEN, CHECK_DATA, RED, RED), "Pending data check"),
    ((GREEN, GREEN, CHECK_DATA, GREEN), "Monitor (data check needed: Value)"),
    ((GREEN, AMBER, CHECK_DATA, CHECK_DATA), "Monitor (data check needed: Value, Fees)"),
    ((GREEN, RED, CHECK_DATA, GREEN), "Review"),
    ((MANUAL_CHECK, GREEN, GREEN, GREEN), "Retain"),
    ((MANUAL_CHECK, AMBER, GREEN, GREEN), "Monitor"),
    ((MANUAL_CHECK, GREEN, AMBER, AMBER), "Monitor until a peer is added"),
])
def test_verdicts(ratings, expected):
    names = ("Mandate", "Performance", "Value for investors", "Fees")
    assert sc.verdict(_pillars(**dict(zip(names, ratings))))[0] == expected


def test_blocking_flag_turns_mandate_and_performance_into_check_data():
    prof = profile()
    flag = DataFlag(check="implausible_tracker_gap", level="blocking", message="CHECK DATA: index fund -1.20% a year")
    card = sc.score(index_fund(), prof, T, path(prof, flags=[flag]), peer())
    assert card.pillars["Mandate"].rating == card.pillars["Performance"].rating == CHECK_DATA
    assert card.verdict == "Pending data check"


# Test 1 end to end: files -> checks -> calculator -> precedence -> decision tree -> scorecard
@requires_test1
def test_test1_end_to_end():
    prof, fs = read_json(TEST1_PROFILE), read_json(TEST1_FACTSHEET)
    checked = check_prices(read_prices(TEST1_CSV), prof, T, fs)
    reported = apply_precedence(calculate(checked.prices, prof, T, fs), checked.flags, prof, T, fs, checked.comparison)
    card = sc.score(reported, prof, T, decision_path(prof, checked.short_history, reported.flags), peer=None,
                    comparison_series=checked.comparison.fund_series,
                    extra_tolerance_pp=checked.comparison.extra_tolerance_pp)
    ratings = {name: (p.rating, p.summary) for name, p in card.pillars.items()}
    assert ratings == {"Mandate": (GREEN, None), "Performance": (GREEN, None),
                       "Value for investors": (AMBER, "Add peer"), "Fees": (AMBER, "Add peer")}
    assert card.verdict == "Monitor until a peer is added"
    td, te = card.pillars["Performance"].sub_ratings
    assert "TD -0.10 pp a year (5y, fund_pnav vs index); Green within 0.16" in td.reason
    assert te.reason.startswith("TE 0.02%, 3y (factsheet)")
    assert "Periods differ: tracking difference is 5y, tracking error is 3y (factsheet)" in card.pillars["Performance"].notes
    # Must NOT be judged on midday NAV 88.3% vs index 91.6%
    assert "fund_nav" not in td.reason


def test_manual_check_is_named_in_the_reason_and_listed_for_the_approval_box():
    prof = profile(objective_type="active_target")
    rep = _active(0.5, [(11.0, 10.0)] * 5)
    card = sc.score(rep, prof, T, path(prof), peer(ocf=0.06, y5=10.4))
    assert card.pillars["Mandate"].rating == MANUAL_CHECK
    assert card.verdict == "Retain" and card.verdict_reason.endswith("Mandate need a reviewer check")
    assert [p.name for p in card.manual_checks] == ["Mandate"]


def test_value_and_fees_keep_the_figures_behind_their_reasons():
    """ For plain wording in the findings, the report and the page (owner review of step 11) """
    from fund_performance.plain import fees_sentence, value_sentence
    v = {"peer": "P", "years": 5, "peer_ann": 9.0, "fund_ann": 8.5, "gap_pp": 0.5}
    assert value_sentence(v) == "the peer, P, returned 0.50 pp a year more than the fund over 5 years, both after fees"
    assert value_sentence(v | {"gap_pp": 0.0}).startswith("the peer, P, returned the same as the fund")
    f = {"peer": "P", "fund_ocf": 0.06, "peer_ocf": 0.10, "gap_pp": -0.04}
    assert fees_sentence(f) == "the fund's 0.06% yearly ongoing charge (OCF) is 0.04 pp below the peer's 0.10%"


def test_value_and_fees_pillars_carry_their_values():
    pillar = sc.value_rating(figures(fund_nav__ann__5y=13.8), profile(), T, peer(y5=13.5))
    assert pillar.values["gap_pp"] == -0.3 and pillar.values["years"] == 5
    fees = sc.fees_rating(profile(ocf_pct=0.06), T, peer(ocf=0.03), GREEN)
    assert {k: fees.values[k] for k in ("fund_ocf", "peer_ocf", "gap_pp", "count")} == {
        "fund_ocf": 0.06, "peer_ocf": 0.03, "gap_pp": 0.03, "count": 1}
    assert fees.values["limits"][0] | {} == {"metric": "Fee gap", "value": 0.03, "green": 0.05, "amber": 0.2,
                                             "kind": "max", "unit": "pp"}
