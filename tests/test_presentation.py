""" Shared presentation helpers (stage 3): the dashboard and both PDFs show the same figures and wording """
import json
from pathlib import Path
from fund_performance.models import DataFlag
from fund_performance.presentation import (assessment_caveat, chart_choice, evidence_quality, flag_dicts,
                                           headline_metrics, issue_groups, risk_measures)

FACTS = json.loads((Path(__file__).parent / "golden" / "demo_facts.json").read_text())


def facts():
    return json.loads(json.dumps(FACTS))


def test_flags_become_plain_dicts_once_each():
    flags = [DataFlag(check="a", level="warning", message="M"), {"check": "b", "level": "warning", "message": "M"},
             {"check": "c", "level": "info", "message": "I"}]
    assert flag_dicts(flags) == [{"check": "a", "level": "warning", "message": "M"},
                                 {"check": "c", "level": "info", "message": "I"}]


def test_insufficient_evidence_is_kept_apart_from_underperformance():
    f = facts()
    pillars = {p["name"]: p for p in f["scorecard"]["pillars"]}
    pillars["Performance"]["rating"] = "RED"
    pillars["Value for investors"].update(rating="AMBER", summary="Add peer")
    pillars["Fees"]["rating"] = "CHECK DATA"
    gaps, concerns = issue_groups(f, {"Performance": "Behind its index.", "Fees": "Peer currency unclear."})
    assert concerns == ["Performance (Red): Behind its index."]
    assert [g.split(":")[0] for g in gaps] == ["Value for investors", "Fees"]


def test_the_chart_follows_the_mandate_and_the_data():
    f = facts()
    assert chart_choice(f) == "yearly_gap"                                  # index fund with calendar-year gaps
    f["fund"]["objective_type"] = "active_target"
    assert chart_choice(f) == "yearly_excess"
    f["evidence"]["gaps"] = {}
    assert chart_choice(f) == "rolling_12m"                                 # 12-month windows, fund and index
    f["figures"] = [x for x in f["figures"] if ".discrete_12m." not in x["name"]]
    assert chart_choice(f) is None


def test_caveat_and_risk_rows_and_metrics_are_shared():
    q = evidence_quality({"facts": facts(), "flags": [{"check": "x", "level": "warning", "message": "W"}]})
    assert assessment_caveat(q) == "Not final: review the data warnings first."
    assert risk_measures(facts())[0] == ("Tracking error, 5 years", "0.10%", "Calculated")
    assert [m.value for m in headline_metrics(facts())] == ["9.8% a year", "−0.11 pp a year", "0.10% a year"]
