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


def test_readable_report_file_names():
    from datetime import date
    from fund_performance.presentation import report_filename
    assert report_filename("Fidelity Index US Fund P Accumulation", "Executive", date(2026, 9, 30)) == \
        "Fidelity_Index_US_Fund_P_Accumulation_Executive_Report_2026-09-30.pdf"
    assert report_filename("L&G / S&P 500 (GBP) – Acc", "Detailed", date(2026, 9, 30)) == \
        "L_G_S_P_500_GBP_Acc_Detailed_Report_2026-09-30.pdf"


def test_download_copy_keeps_the_original(tmp_path):
    from datetime import date
    from fund_performance.presentation import download_copy
    pdf = tmp_path / "report_executive.pdf"
    pdf.write_bytes(b"%PDF")
    copy = download_copy(pdf, "Fund A", date(2026, 9, 30))
    assert copy == tmp_path / "download" / "Fund_A_Executive_Report_2026-09-30.pdf"
    assert copy.read_bytes() == pdf.read_bytes() and pdf.is_file()


def test_only_a_blocking_currency_or_benchmark_mismatch_invalidates_the_comparison():
    from fund_performance.presentation import comparison_problems
    flags = [DataFlag(check="currency_match", level="blocking", message="CHECK DATA: currency mismatch"),
             DataFlag(check="gaps", level="blocking", message="CHECK DATA: gap"),
             {"check": "implausible_tracker_gap", "level": "blocking", "message": "CHECK DATA: far from index"},
             DataFlag(check="currency_match", level="warning", message="not blocking")]
    assert comparison_problems(flags) == ["CHECK DATA: currency mismatch", "CHECK DATA: far from index"]
    assert comparison_problems([]) == []


def test_the_same_wording_is_said_once():
    from fund_performance.executive import merge_resolve_actions
    from fund_performance.presentation import merge_same_ending, report_action
    end = ": not rated until the data check is resolved (see the data issues)"
    assert merge_same_ending([f"Mandate{end}", f"Performance{end}", "Fees: Add peer"], end) == \
        [f"Mandate and Performance{end}", "Fees: Add peer"]
    tail = "before signing off this review (see the data issues)."
    assert merge_resolve_actions([f"Resolve the data check on Mandate {tail}", "Other.",
                                  f"Resolve the data check on Performance {tail}"]) == \
        [f"Resolve the data check on Mandate and Performance {tail}", "Other."]
    assert report_action("Read the evidence on pages 2 to 4 before x.") == \
        "Read the evidence in the Detailed Report (Appendices A to D) before x."
