""" Number guard (spec 8.3) and rating guard """
import pytest
from fund_performance.number_guard import allowed_numbers, check_numbers, check_ratings, numbers_in

FACTS = {"figures": [{"value": 13.8, "unit": "%"}, {"value": 13.89, "unit": "%"}, {"value": -0.1, "unit": "pp"},
                     {"value": 17.51, "unit": "%"}, {"value": 1.0, "unit": "ratio"}, {"value": 0.02, "unit": "%"}],
         "fund": {"ocf_pct": 0.06},
         "scorecard": {"pillars": [{"name": "Performance", "rating": "GREEN", "reason": "Green within 0.16"}]}}


@pytest.mark.parametrize("text", ["In 2024 and 2025", "over 5 years", "the 3y figure", "a 12-month window",
                                  "4 questions", "hit rate 5 of 5", "the S&P 500 index", "R2 and Q3",
                                  "as of 2026-09-30", "on 30/09/2026", "£10,000"])
def test_years_periods_counts_and_dates_are_not_figures(text):
    assert numbers_in(text) == []


def test_units_are_read():
    found = {(n.value, n.unit) for n in numbers_in("13.8%, -0.10 pp, 0.1 percentage points, beta 1.00, 2 bps")}
    assert found == {(13.8, "%"), (-0.1, "pp"), (0.1, "pp"), (1.0, None), (0.02, "pp")}


@pytest.mark.parametrize("text", ["returned 13.8% a year", "about 13.9% for the index", "13.89%",
                                  "a tracking difference of -0.10 pp", "0.1 pp behind the index",
                                  "0.06% a year", "beta of 1.00", "TE 0.02%", "a limit of 0.16", "17.5%"])
def test_figures_in_the_facts_pass_with_rounding(text):
    assert check_numbers(text, FACTS) == []


@pytest.mark.parametrize("text,bad", [
    ("a tracking difference of -0.10%", "-0.10%"),      # pp, not %
    ("a return of 0.10%", "0.10%"),
    ("the fund returned 18.2%", "18.2%"),
    ("the fund returned 17%", "17%"),                    # whole-number rounding of 17.51 is not allowed
    ("a return of -13.8%", "-13.8%"),                    # a written minus must match a negative fact
    ("a gap of 0.12 pp", "0.12 pp"),
])
def test_figures_not_in_the_facts_are_caught(text, bad):
    assert check_numbers(text, FACTS) == [bad]


def test_numbers_written_in_the_facts_text_keep_their_units():
    allowed = allowed_numbers({"reason": "TD -0.10 pp a year; OCF 0.06%; Green within 0.16"})
    assert {(-0.1, "pp"), (0.06, "%"), (0.16, None)} <= allowed


SCORECARD = {"verdict": "Monitor until a peer is added",
             "pillars": [{"name": "Mandate", "rating": "GREEN"}, {"name": "Performance", "rating": "GREEN"},
                         {"name": "Value for investors", "rating": "AMBER"}, {"name": "Fees", "rating": "AMBER"}]}


def test_correct_ratings_pass():
    text = ("The mandate is Green. Performance is Green; fees are Amber because no peer was supplied. "
            "The draft verdict is Monitor until a peer is added.")
    assert check_ratings(text, SCORECARD) == []


@pytest.mark.parametrize("text", ["Performance is Amber.", "Fees are Green.", "Performance is Amber and fees Green.",
                                  "Value for investors is Red."])
def test_a_different_rating_is_rejected(text):
    assert check_ratings(text, SCORECARD)


@pytest.mark.parametrize("text", ["We would Retain the fund.", "This calls for a Review.", "Verdict: Pending data check."])
def test_a_different_verdict_is_rejected(text):
    assert any(p.startswith("verdict") for p in check_ratings(text, SCORECARD))


# Label guard: a figure next to "tracking difference", "tracking error" or "ongoing charge" must be that fact
from fund_performance.number_guard import check_labels  # noqa: E402

LABEL_FACTS = {
    "fund": {"ocf_pct": 0.06},
    "figures": [{"name": "comparison.td.5y", "value": -0.1, "unit": "pp"},
                {"name": "comparison.td_ex_cost.5y", "value": -0.04, "unit": "pp"},
                {"name": "comparison.excess_cum.5y", "value": -0.7, "unit": "pp"},
                {"name": "risk.pnav.tracking_error.3y", "value": 0.02, "unit": "%"}],
    "data_notes": [{"kind": "pricing", "note": "Noon pricing.", "figures": [
        {"label": "Gap at noon prices (NAV vs index), 5y", "value": -3.3, "unit": "pp", "display": "-3.3 pp"}]},
        {"kind": "fee", "note": "Most of the gap is the fee.", "figures": [
            {"label": "Fund behind its index, in plain terms (% a year), 5y", "value": -0.1, "unit": "%"},
            {"label": "Cost-adjusted gap, in plain terms (% a year), 5y", "value": -0.04, "unit": "%"}]}]}


def test_the_noon_gap_called_a_tracking_difference_is_rejected():
    # From the full Test 1 run: -3.3 pp is the 5-year noon-price gap, not a tracking difference
    issues = check_labels("Over 5 years, the fund shows a tracking difference −3.3 pp at noon prices.", LABEL_FACTS)
    assert issues == ["label: '-3.3 pp' next to 'tracking difference' is not a tracking difference for 5 years in the facts"]


def test_a_cost_adjusted_gap_needs_its_sign_and_a_year():
    # From the full Test 1 run: "cost-adjusted gap 0.04 pp" leaves out the sign and "a year"
    issues = check_labels("The cost-adjusted gap 0.04 pp is small.", LABEL_FACTS)
    assert issues == ["label: '0.04 pp' next to 'cost-adjusted gap' is a yearly figure; add 'a year'",
                      "label: '0.04 pp' next to 'cost-adjusted gap' needs its period; add 'over 5 years'",
                      "label: '0.04 pp' next to 'cost-adjusted gap' is negative; write the minus sign or say 'behind'"]
    assert check_labels("The cost-adjusted gap is -0.04 pp a year over 5 years.", LABEL_FACTS) == []
    assert check_labels("Over 5 years, the cost-adjusted gap is 0.04 pp a year behind.", LABEL_FACTS) == []


@pytest.mark.parametrize("text", [
    "The fund is behind its index by 0.10% a year over 5 years (tracking difference -0.10 pp).",
    "Ongoing charge (OCF) 0.06% (the yearly fee taken from the fund) explains most of the gap.",
    "Tracking error 0.02% (how much that gap varies from month to month) is low.",
    "Its noon price makes it look 3.3 pp behind over 5 years, but the tracking difference is -0.10 pp a year.",
    "The 5-year gap is 0.7 pp, and the tracking error 0.02% is low.",
])
def test_correctly_labelled_figures_pass(text):
    assert check_labels(text, LABEL_FACTS) == []


@pytest.mark.parametrize("text, problem", [
    ("Tracking error 0.02% over 5 years is low.", "is not a tracking error for 5 years"),
    ("The ongoing charge is 0.10%.", "is not an ongoing charge"),
    ("The tracking difference is -0.10% a year over 5 years.", None),    # the plain-terms % figure is allowed
    ("The tracking error is 0.02 pp.", "is not a tracking error"),       # wrong unit
])
def test_wrong_type_period_or_unit_is_rejected(text, problem):
    issues = check_labels(text, LABEL_FACTS)
    assert (issues == []) if problem is None else (len(issues) == 1 and problem in issues[0])


def test_a_tracking_difference_must_state_its_period():
    issues = check_labels("The tracking difference is -0.10 pp a year.", LABEL_FACTS)
    assert issues == ["label: '-0.10 pp' next to 'tracking difference' needs its period; add 'over 5 years'"]
    assert check_labels("The tracking difference is -0.10 pp a year over 5 years.", LABEL_FACTS) == []
    # The hint names the main test period when the same figure is given for several periods
    facts = LABEL_FACTS | {"fund": {"ocf_pct": 0.06, "time_horizon_years": 3},
                           "figures": LABEL_FACTS["figures"] + [{"name": "comparison.td.3y", "value": -0.1, "unit": "pp"}]}
    assert check_labels("The tracking difference is -0.10 pp a year.", facts)[0].endswith("add 'over 3 years'")


def test_punctuation_is_not_counted_as_a_word():
    """ ", the gap between fund and index returns, was" is 8 words, so the label still applies """
    issues = check_labels("The tracking difference, the gap between fund and index returns, was -0.10 pp a year.",
                          LABEL_FACTS)
    assert issues == ["label: '-0.10 pp' next to 'tracking difference' needs its period; add 'over 5 years'"]
