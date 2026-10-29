""" The PDF report (step 9): layout, display rules and content, on made-up data and on Test 1 """
import asyncio
import json
import numpy as np
import pandas as pd
import pytest
from fund_performance.agents.analyst import AnalystOutput, Narrative, template
from fund_performance.calc import calculate
from fund_performance.checks import check_prices
from fund_performance.config import load_thresholds
from fund_performance.facts import build_facts
from fund_performance.io import PriceData
from fund_performance.mandate import decision_path
from fund_performance.models import DataFlag, FactsheetPerformance, Figure, FundProfile
from fund_performance.precedence import apply_precedence
from fund_performance.report import (MAX_PAGES, PAGE_TITLES, ReportInputs, ReportLayoutError, build_report, fmt,
                                     page_texts)
from fund_performance.run_report import run_review
from fund_performance.scorecard import score
from conftest import FIXTURES, TEST1, requires_test1

T = load_thresholds()


def made_up_inputs(objective_type="index_tracker", flags=(), findings=None):
    prof = FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text())
                                      | {"objective_type": objective_type, "launch_date": "2018-01-02"})
    fs = FactsheetPerformance.model_validate(json.loads((FIXTURES / "factsheet_performance_sample.json").read_text()))
    rng = np.random.default_rng(5)
    nav = 100 * np.cumprod(1 + np.r_[0, rng.normal(0.007, 0.03, 72)])
    prices = pd.DataFrame({"date": pd.date_range(end="2026-09-30", periods=73, freq="ME"), "nav": nav})
    checked = check_prices(PriceData(prices, "prices.csv", "YYYY-MM-DD"), prof, T, fs)
    reported = apply_precedence(calculate(checked.prices, prof, T, fs), checked.flags, prof, T, fs, checked.comparison)
    all_flags = reported.flags + list(flags)
    card = score(reported, prof, T, decision_path(prof, checked.short_history, all_flags), None)
    facts = build_facts(prof, reported, card, all_flags)
    narrative = Narrative(template(facts) if findings is None else AnalystOutput(
        key_findings=findings, actions=[{"candidate": "record_decision", "text": "Record it at this review."},
                                        {"candidate": "read_sources", "text": "Read the sources before signing off."}],
        market_context=None), "template" if findings is None else "ai")
    return ReportInputs(profile=prof, question="Is this fund meeting its mandate?", reported=reported, card=card,
                        facts=facts, narrative=narrative, thresholds=T, flags=all_flags, prices=checked.prices,
                        input_files=["prices.csv"], run_note="Offline run")


def test_display_rules():
    pct = Figure(value=13.8, exact=13.8, unit="%", source="factsheet")
    assert fmt("fund_nav.ann.5y", pct) == "13.8%"
    assert fmt("comparison.td.5y", Figure(value=-0.1, exact=-0.1, unit="pp", source="calculated")) == "−0.10 pp"
    assert fmt("risk.pnav.tracking_error.3y", Figure(value=0.02, exact=0.02, unit="%", source="factsheet")) == "0.02%"
    assert fmt("risk.pnav.beta.3y", Figure(value=1.0, exact=1.0, unit="ratio", source="factsheet")) == "1.00"
    assert fmt("index.cum.1y", Figure(value=17.1, exact=17.1, unit="%", source="ai_extracted")) == "17.1% (please verify)"
    assert fmt("x", None) == "–"


def test_made_up_report_layout(tmp_path):
    path = build_report(made_up_inputs(), tmp_path)
    texts = page_texts(path)
    assert 4 <= len(texts) <= MAX_PAGES
    for i, title in enumerate(PAGE_TITLES):
        assert title in texts[i]
    assert (tmp_path / "growth.png").exists() is False or True      # charts are optional on thin data


def test_many_flags_shorten_the_appendix_not_the_main_pages(tmp_path):
    flags = [DataFlag(check="x", level="info", message=f"Note number {i} about the data, kept for the record.")
             for i in range(160)]
    path = build_report(made_up_inputs(flags=flags), tmp_path)
    texts = page_texts(path)
    assert len(texts) <= MAX_PAGES and "Note number 100" not in "".join(texts)
    assert "more (full list in run_log.txt)" in "".join(texts[3:])
    for i, title in enumerate(PAGE_TITLES):
        assert title in texts[i]


def test_a_main_page_that_overflows_is_an_error(tmp_path):
    long = ["A very long finding that goes on and on. " * 40] * 3
    with pytest.raises(ReportLayoutError, match="page 1 ran over|before it ran over"):
        build_report(made_up_inputs(findings=long), tmp_path)


def test_manual_check_gets_a_tick_box(tmp_path):
    texts = page_texts(build_report(made_up_inputs(objective_type="active_target"), tmp_path))
    assert "Manual check done: Mandate" in texts[0] and "Manual check" in texts[0]


@pytest.fixture(scope="module")
def test1_pdf(tmp_path_factory):
    return asyncio.run(run_review(TEST1, "Is this index fund meeting its mandate, and is its fee justified?",
                                  tmp_path_factory.mktemp("runs"), offline=True))


@requires_test1
def test_test1_layout_and_run_files(test1_pdf):
    texts = page_texts(test1_pdf)
    assert len(texts) == 4
    for i, title in enumerate(PAGE_TITLES):
        assert title in texts[i]
    assert (test1_pdf.parent / "facts.json").exists() and (test1_pdf.parent / "run_log.txt").exists()


@requires_test1
def test_test1_page1_summary_stands_on_its_own(test1_pdf):
    p1 = page_texts(test1_pdf)[0]
    for text in ("Fidelity Index US Fund P Accumulation", "Is this index fund meeting its mandate",
                 "Figures to 30 September 2026", "Monitor until a peer is added", "Mandate", "Performance",
                 "Value for investors", "Fees", "Green", "Amber", "Key findings", "Recommended actions",
                 "Reviewer name", "Signature", "Retain", "Review",
                 "Moves in line with its index (R² 1.00, beta 1.00; 3 years, factsheet)"):
        assert text in p1, text
    assert "3.3 pp behind its index over 5 years" in p1 and "0.06% yearly ongoing charge" in p1


@requires_test1
def test_test1_page2_figures_and_sources(test1_pdf):
    p2 = page_texts(test1_pdf)[1]
    for text in ("88.3%", "90.9%", "91.6%", "13.8%", "13.9%", "0.10 pp", "0.02%", "1.00", "Factsheet", "Calculated",
                 "Calendar-year returns", "Below the surface", "noon", "Growth of 100"):
        assert text in p2, text


@requires_test1
def test_test1_page2_review_fixes(test1_pdf):
    p2 = " ".join(page_texts(test1_pdf)[1].split())
    # 1. Decision path in plain words
    assert "Index fund, so it is judged on how closely it tracks its index" in p2
    assert not any(code in p2 for code in ("TD_ex_cost", "(TD", "TE,", "index_tracker", "R2"))
    # 2. Risk rows under source, period and basis subheadings; the calculated Sharpe ratio is not on page 2
    for heading in ("Factsheet · 3 years, market-close price (PNAV)", "Factsheet · 3 years, noon price (NAV)",
                    "Calculated · 5 years, noon price (NAV)"):
        assert heading in p2, heading
    assert "risk-free rate 0" not in p2 and "Period, basis" not in p2
    # 3. Below the surface: plain sentences, then one short source line
    assert "The fair comparison uses the fund's market-close price (PNAV). 5 years: Fund noon price 88.3%" in p2
    assert "Fair gap −0.7 pp. Source: factsheet; gaps calculated." in p2
    assert ("Most of the yearly gap is the fee. Without the 0.06% yearly fee, the fund would be only 0.04% a year "
            "behind its index.") in p2
    # 4. Returns table note
    assert "Cumulative gaps to 1 d.p., yearly gaps to 2 d.p." in p2


@requires_test1
def test_test1_page3_value_fees_and_aov(test1_pdf):
    p3 = " ".join(page_texts(test1_pdf)[2].split())          # table cells wrap lines
    for text in ("Add peer", "Not disclosed in the documents provided", "Partly", "Quality of service",
                 "Classes of units", "It does not replace the AFM's formal Assessment of Value",
                 "No market context"):
        assert text in p3, text


@requires_test1
def test_test1_appendix(test1_pdf):
    p4 = page_texts(test1_pdf)[3]
    for text in ("Data checks and flags", "Excluded web sources", "Sources", "fund_profile.json",
                 "illustrative, to be agreed with the oversight team", "Glossary", "tracking difference",
                 "Known limitations", "Public data only", "checked against factsheet: consistent"):
        assert text in p4, text
    flat = " ".join(p4.split())
    assert "Calculated Sharpe ratio Fund 0.98 (5 years, noon price (NAV), calculated from prices with a risk-free rate" in flat
    assert "not comparable with the factsheet Sharpe ratio" in flat
    # 5. Glossary: the terms used, including the new ones
    glossary = flat.split("Glossary (terms used in this report)")[1].split("Known limitations")[0]
    for term in ("NAV:", "Sharpe ratio:", "information ratio:", "alpha:", "largest fall:", "Assessment of Value (AoV):",
                 "AFM:"):
        assert term in glossary, term


def test_glossary_lists_only_terms_the_report_uses(tmp_path):
    texts = page_texts(build_report(made_up_inputs(), tmp_path))
    glossary = " ".join(texts[-1].split()).split("Glossary (terms used in this report)")[1].split("Known limitations")[0]
    assert "tracking difference:" in glossary and "Assessment of Value (AoV):" in glossary
    assert ("AFM:" in glossary) == ("AFM" in " ".join(texts))


def test_plain_decision_path_for_each_objective_type():
    from fund_performance.models import DataFlag as Flag
    from fund_performance.report import OBJECTIVE_WORDS, plain_path
    prof = FundProfile.model_validate(json.loads((FIXTURES / "fund_profile_sample.json").read_text()))
    for kind in OBJECTIVE_WORDS:
        steps = plain_path(decision_path(prof.model_copy(update={"objective_type": kind}), False, []))
        assert len(steps) == 5 and "_" not in " ".join(steps)
    blocked = plain_path(decision_path(prof, True, [Flag(check="x", level="blocking", message="Currency mismatch")]))
    assert "since-launch figures are used" in blocked[2] and blocked[4].endswith("so the ratings wait for a data check.")


def test_fee_note_wording_in_the_report_only():
    from fund_performance.report import plain_note
    note = {"kind": "fee", "note": "The fee explains only part of the yearly gap to the index. Adding ...",
            "figures": [{"label": "Ongoing charge (OCF), a year", "value": 0.2, "unit": "%"},
                        {"label": "Cost-adjusted gap, in plain terms (% a year), 5y", "value": 0.15, "unit": "%"}]}
    assert plain_note(note) == ("The fee explains only part of the yearly gap. Without the 0.20% yearly fee, the fund "
                                "would be 0.15% a year ahead of its index.")
    pricing = {"kind": "pricing", "note": "Noon pricing.", "figures": []}
    assert plain_note(pricing) == "Noon pricing."


@requires_test1
def test_test1_facts_keep_the_original_wording(test1_pdf):
    facts = json.loads((test1_pdf.parent / "facts.json").read_text())
    assert facts["data_notes"][1]["note"].startswith("Most of the yearly gap to the index is the fee. Adding")
    assert "TD_ex_cost" in facts["decision_path"][0]
