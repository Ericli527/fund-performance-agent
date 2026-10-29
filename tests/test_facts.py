""" The facts JSON given to the Oversight Analyst """
import json
from fund_performance.facts import build_facts, label
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, Figure, FundProfile
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import Pillar, Scorecard
from conftest import FIXTURES


def _facts():
    prof = FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()))
    rep = ReportedFigures(figures={
        "fund_pnav.ann.5y": Figure(value=13.8, exact=13.8, unit="%", source="factsheet", period="5y"),
        "comparison.td.5y": Figure(value=-0.1, exact=-0.1000001, unit="pp", source="calculated", period="5y"),
        "risk.pnav.beta.3y": Figure(value=1.0, exact=1.0, unit="ratio", source="factsheet", basis="pnav"),
        "index.cum.1y": Figure(value=17.1, exact=17.1, unit="%", source="ai_extracted")})
    card = Scorecard({"Performance": Pillar("Performance", "GREEN", "TD -0.10 pp")}, "Retain", "All Green",
                     decision_path(prof, False, []))
    flags = [DataFlag(check="a", level="info", message="info only"), DataFlag(check="b", level="warning", message="look")]
    return build_facts(prof, rep, card, flags, ["Track the index"])


def test_labels():
    assert label("fund_pnav.ann.5y") == "Fund PNAV (market-close) annualised return, 5y"
    assert label("risk.pnav.tracking_error.3y") == "Factsheet risk (PNAV basis): tracking error, 3y"
    assert label("comparison.td.5y") == "Fund vs index tracking difference, 5y"


def test_figures_keep_units_sources_and_display():
    figs = {f["name"]: f for f in _facts()["figures"]}
    assert figs["fund_pnav.ann.5y"]["display"] == "13.8%" and figs["fund_pnav.ann.5y"]["source"] == "factsheet"
    assert (figs["comparison.td.5y"]["unit"], figs["comparison.td.5y"]["display"]) == ("pp", "-0.10 pp")   # 2 d.p.
    assert figs["risk.pnav.beta.3y"]["display"] == "1.00"
    assert figs["index.cum.1y"]["note"] == "please verify" and "note" not in figs["fund_pnav.ann.5y"]


def test_scorecard_path_and_only_warning_or_blocking_flags():
    facts = _facts()
    assert facts["scorecard"]["verdict"] == "Retain" and facts["scorecard"]["pillars"][0]["rating"] == "GREEN"
    assert facts["decision_path"][0].startswith("1. Objective type")
    assert facts["data_flags"] == [{"check": "b", "level": "warning", "message": "look"}]
    assert facts["fund"]["promises"] == ["Track the index"]
    json.dumps(facts)                                       # plain JSON, ready for the prompt


# Data notes
import pytest
from fund_performance.facts import data_notes
from fund_performance.number_guard import check_numbers
from conftest import requires_test1


def _profile(**changes):
    return FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text())
                                      | {"ocf_pct": 0.06} | changes)


def _reported(**values):
    return ReportedFigures(figures={k.replace("__", "."): Figure(value=v, exact=v, unit="pp" if "comparison" in k else "%",
                                                                 source="factsheet") for k, v in values.items()})


def test_noon_pricing_note_has_both_gaps():
    flag = DataFlag(check="pricing_point", level="info", message="PNAV used")
    notes = data_notes(_profile(), _reported(fund_nav__cum__5y=88.3, fund_pnav__cum__5y=90.9, index__cum__5y=91.6), [flag])
    [note] = notes
    shown = [f["display"] for f in note["figures"]]
    assert shown == ["88.3%", "91.6%", "-3.3 pp", "90.9%", "-0.7 pp"] and "market-close price (PNAV)" in note["note"]


def test_timing_warning_note_without_pnav():
    flag = DataFlag(check="pricing_point", level="warning", message="Timing difference")
    [note] = data_notes(_profile(), _reported(), [flag])
    assert "no market-close price (PNAV)" in note["note"] and note["figures"] == []


@pytest.mark.parametrize("td,td_ex,start", [(-0.10, -0.04, "Most of the yearly gap"), (-0.30, -0.24, "The fee explains only part")])
def test_fee_note(td, td_ex, start):
    [note] = data_notes(_profile(), _reported(comparison__td__5y=td, comparison__td_ex_cost__5y=td_ex), [])
    assert note["note"].startswith(start)
    assert {(f["value"], f["unit"]) for f in note["figures"]} >= {(td, "pp"), (td, "%"), (0.06, "%"), (td_ex, "pp")}


def test_no_notes_for_an_active_fund_without_a_pricing_flag():
    assert data_notes(_profile(objective_type="active_target"),
                      _reported(comparison__td__5y=-0.5, comparison__td_ex_cost__5y=-0.44), []) == []


@requires_test1
def test_test1_notes_and_the_style_example_pass_the_number_guard():
    from test_agent_analyst import _test1_facts
    facts = _test1_facts()
    figures = {(f["value"], f["unit"]) for n in facts["data_notes"] for f in n["figures"]}
    assert {(88.3, "%"), (91.6, "%"), (-3.3, "pp"), (90.9, "%"), (-0.7, "pp"), (-0.1, "pp"), (0.06, "%"), (-0.04, "pp")} <= figures
    example = ("The fund tracks its index closely. Its noon price makes it look 3.3 pp behind over 5 years, because the "
               "index is measured at market close. Using the fund's market-close price (PNAV), the gap is only 0.7 pp, "
               "and most of it is the 0.06% yearly fee. The fund falls behind its index by about 0.10% a year "
               "(tracking difference -0.10 pp), or -0.04 pp after adding back the fee.")
    assert check_numbers(example, facts) == []
