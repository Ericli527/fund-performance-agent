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
