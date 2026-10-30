""" The results dashboard (UX redesign, stage 2): presentation of what the run decided, with the investment
assessment kept apart from evidence quality, both audiences on the same facts, and nothing lost from the old
plain-text results """
import asyncio
import copy
import json
from pathlib import Path
import re
import pytest
from fund_performance.dashboard import (NOT_AVAILABLE, dashboard_data, dashboard_html, evidence_quality,
                                        headline_metrics, technical_html)

GOLDEN = Path(__file__).parent / "golden" / "demo_facts.json"


def data(**changes) -> dict:
    facts = json.loads(GOLDEN.read_text())
    reasons = {"Mandate": "Moves in line with its index.", "Performance": "Stays close to its index.",
               "Value for investors": "The peer returned less.", "Fees": "The fee is 0.05 pp above the peer's."}
    base = {"facts": facts, "reasons": reasons, "findings": ["Finding one."], "actions": ["Action one."],
            "market_context": None, "sources": [], "flags": [], "offline": True}
    return base | changes


def text(html: str) -> str:
    from html import unescape
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


# Evidence quality, separate from the investment assessment
def test_no_flags_means_no_data_issues_raised_not_verified():
    q = evidence_quality(data())
    assert (q.level, q.label) == ("clear", "No data issues raised") and "verified" not in q.detail.lower()


def test_warnings_and_blocking_checks_set_the_evidence_status():
    warn = evidence_quality(data(flags=[{"check": "x", "level": "warning", "message": "Repeated price on 2024-07-31"},
                                        {"check": "y", "level": "info", "message": "for the record"}]))
    assert (warn.level, warn.label) == ("warnings", "Warnings to review") and warn.warnings == ["Repeated price on 2024-07-31"]
    d = data(flags=[{"check": "c", "level": "blocking", "message": "CHECK DATA: currency mismatch"}])
    d["facts"]["scorecard"]["pillars"][1]["rating"] = "CHECK DATA"
    check = evidence_quality(d)
    assert (check.level, check.label) == ("check", "Data check needed") and "(Performance)" in check.detail


def test_ai_read_figures_are_noted_but_do_not_raise_a_warning():
    d = data()
    d["facts"]["figures"][0]["source"] = "ai_extracted"
    q = evidence_quality(d)
    assert q.level == "clear" and "read from the documents by AI" in q.detail


def test_a_suggested_satisfied_with_open_data_issues_is_never_shown_as_final():
    html = text(dashboard_html(data(flags=[{"check": "x", "level": "warning", "message": "Gap in prices"}])))
    assert "Satisfied" in html and "Not final: review the data warnings first." in html
    assert "Warning: Gap in prices" in html and "approved" not in html.lower()
    clean = text(dashboard_html(data()))
    assert "Not final" not in clean and "Investment assessment (suggested)" in clean


# Headline metrics: from the facts, with period, unit and source; missing is never zero
def test_headline_metrics_come_from_the_facts():
    fund, gap, ocf = headline_metrics(data()["facts"])
    assert (fund.value, fund.period, fund.source) == ("9.8% a year", "5 years to 30 Sep 2026, fund price (NAV)", "Calculated")
    assert (gap.value, gap.note) == ("−0.11 pp a year", "Index 9.9% a year") and gap.label.startswith("Gap to index")
    assert (ocf.value, ocf.source) == ("0.10% a year", "Fund documents")


def test_a_missing_figure_says_not_available_never_zero():
    facts = data()["facts"]
    facts["figures"] = [f for f in facts["figures"] if not f["name"].startswith(("comparison.td.5y", "fund_nav.ann.5y"))]
    fund, gap, _ = headline_metrics(facts)
    assert fund.value == gap.value == NOT_AVAILABLE
    html = text(dashboard_html(data(facts=facts)))
    assert "Not available" in html and "0.00" not in html


def test_the_market_close_series_is_used_when_the_gap_is_measured_on_it():
    facts = data()["facts"]
    for f in facts["figures"]:
        if f["name"] == "comparison.td.5y":
            f["basis"] = "fund_pnav"
    facts["figures"].append({"name": "fund_pnav.ann.5y", "display": "13.8%", "value": 13.8, "unit": "%",
                             "source": "factsheet"})
    fund = headline_metrics(facts)[0]
    assert (fund.value, fund.source) == ("13.8% a year", "Factsheet") and "market-close price (PNAV)" in fund.period


# Audiences: different views, same facts and ratings
def test_both_audiences_show_the_same_ratings_reasons_and_figures():
    d = data()
    analyst, management = dashboard_html(d, "analyst"), dashboard_html(d, "management")
    for html in (analyst, management):
        for reason in d["reasons"].values():
            assert reason.replace("'", "&#x27;") in html
        for value in ("9.8% a year", "−0.11 pp a year", "0.10% a year", "Satisfied"):
            assert value in html
    assert re.findall(r"fp-chip' style='background:[^']+'>(\w[\w ]*)<", analyst) == \
        re.findall(r"fp-chip' style='background:[^']+'>(\w[\w ]*)<", management)
    assert "Investment Analyst view" in analyst and "Key decisions" not in analyst
    assert "Management view" in management and "Key decisions" in management
    assert "<details class='fp-details ' open><summary>Detailed performance" in analyst
    assert "<details class='fp-details '><summary>Detailed performance" in management     # closed for management


def test_the_audience_does_not_change_the_facts():
    d = data()
    before = copy.deepcopy(d)
    dashboard_html(d, "analyst")
    dashboard_html(d, "management")
    assert d == before


# Nothing from the old plain-text results is lost
def test_everything_from_the_old_results_is_still_on_the_page():
    d = data(findings=["Finding one."], actions=["Action one."],
             flags=[{"check": "x", "level": "warning", "message": "Gap in prices"},
                    {"check": "i", "level": "info", "message": "Risk-free rate 0"}])
    d["facts"]["drafts"] = [{"angle": "board", "score": 6, "max_score": 6, "checks": {"figures_match": True},
                             "chosen": True, "issues": [], "rewritten": False, "text": "x"}]
    page = text(dashboard_html(d, "analyst") + technical_html(d))
    facts = d["facts"]
    for expected in ([facts["fund"]["fund_name"], "30 Sep 2026", "Satisfied", facts["suggested_conclusion"]["text"],
                      "Finding one.", "Action one.", "Warning: Gap in prices", "Risk-free rate 0", "Plan (",
                      "Drafts and the Judge's checklist", "6 of 6"]
                     + list(d["reasons"].values()) + facts["judgement_points"] + facts["manager_questions"]):
        assert expected in page, expected


def test_technical_details_hold_the_plan_drafts_and_info_flags():
    d = data(flags=[{"check": "i", "level": "info", "message": "Offline run"}])
    tech = text(technical_html(d))
    assert "Plan (default (offline))" in tech and "For the record (info flags) Offline run" in tech


@pytest.mark.parametrize("audience", ["analyst", "management"])
def test_text_is_escaped(audience):
    d = data()
    d["facts"]["fund"]["fund_name"] = "<script>alert(1)</script>"
    assert "<script>" not in dashboard_html(d, audience)


# From a real (offline) run
def test_dashboard_data_from_a_demo_run(tmp_path):
    from fund_performance.controller import run_review
    demo = Path(__file__).parents[1] / "demo" / "sample_index_fund"
    result = asyncio.run(run_review(demo, out_root=tmp_path, offline=True))
    d = dashboard_data(result)
    assert d["facts"] == result.facts and d["offline"] is True and d["findings"] and d["actions"]
    assert any(f["level"] == "info" for f in d["flags"])                 # every flag of the run, info included
    assert "Sample World Index Fund A Acc" in dashboard_html(d)
