""" The PDF reports (step 9, redesigned in stage 3): the two-page Executive Report and the Detailed Report (the
executive pages plus Appendices A to D): layout, display rules and content, on made-up data and on Test 1 """
import asyncio
import json
import re
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
from fund_performance.executive import EXEC_TITLES, build_executive
from fund_performance.report import (APPENDIX_TITLES, PAGE_TITLES, ReportInputs, ReportLayoutError, build_report, fmt,
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


def section(texts: list[str], title: str) -> str:
    """ The text of one part of the Detailed Report: from the page its title is on to the page before the next part """
    starts = [next(i for i, x in enumerate(texts) if name in x) for name in PAGE_TITLES]
    i = PAGE_TITLES.index(title)
    end = starts[i + 1] if i + 1 < len(starts) else len(texts)
    pages = [re.sub(r"^.*?Page \d+ of \d+", "", x, count=1, flags=re.S) for x in texts[starts[i]:max(end, starts[i] + 1)]]
    return " ".join(" ".join(pages).split())          # page footers left out, so a sentence may cross a page break


def test_made_up_reports_layout(tmp_path):
    inp = made_up_inputs()
    executive = page_texts(build_executive(inp, tmp_path))
    assert len(executive) == 2 and EXEC_TITLES[0] in executive[0] and EXEC_TITLES[1] in executive[1]
    detailed = page_texts(build_report(inp, tmp_path))
    assert EXEC_TITLES[0] in detailed[0] and EXEC_TITLES[1] in detailed[1] and APPENDIX_TITLES[0] in detailed[2]
    pages = [next(i for i, x in enumerate(detailed) if title in x) for title in APPENDIX_TITLES]
    assert pages == sorted(pages)                                       # each appendix, in order, from a new page


def test_many_flags_keep_two_executive_pages_and_every_flag_in_the_detailed_report(tmp_path):
    flags = [DataFlag(check="x", level="info", message=f"Note number {i} about the data, kept for the record.")
             for i in range(160)]
    inp = made_up_inputs(flags=flags)
    assert len(page_texts(build_executive(inp, tmp_path))) == 2
    detailed = page_texts(build_report(inp, tmp_path))
    assert "Note number 159" in section(detailed, APPENDIX_TITLES[3])     # nothing shortened in the Detailed Report


def test_many_warnings_are_counted_not_hidden_on_the_executive_pages(tmp_path):
    flags = [DataFlag(check="x", level="warning", message=f"Warning number {i} about a price.") for i in range(6)]
    inp = made_up_inputs(flags=flags)
    page2 = " ".join(page_texts(build_executive(inp, tmp_path))[1].split())
    # the made-up fund has 3 warnings of its own: the first 3 are shown in full, the other 6 are counted
    assert page2.count("Warning: ") == 3 and "Warning number 5" not in page2
    assert "and 6 more data warnings, listed in full in the Detailed Report (Appendix D)" in page2
    assert "Warning number 5 about a price." in section(page_texts(build_report(inp, tmp_path)), APPENDIX_TITLES[3])


def test_executive_content_that_does_not_fit_is_an_error_not_cut(tmp_path):
    long = ["A very long finding that goes on and on. " * 40] * 3
    inp = made_up_inputs(findings=long)
    with pytest.raises(ReportLayoutError, match="Executive Report: page 1 runs over"):
        build_executive(inp, tmp_path)
    assert len(page_texts(build_report(inp, tmp_path))) > 2             # the Detailed Report keeps it all


def test_manual_check_gets_a_tick_box(tmp_path):
    texts = [" ".join(x.split()) for x in page_texts(build_executive(made_up_inputs(objective_type="active_target"),
                                                                     tmp_path))]
    assert "Manual check done: Mandate" in texts[1] and "Manual check" in texts[0]


@pytest.fixture(scope="module")
def test1_pdf(tmp_path_factory):
    return asyncio.run(run_review(TEST1, "Is this index fund meeting its mandate, and is its fee justified?",
                                  tmp_path_factory.mktemp("runs"), offline=True))


@requires_test1
def test_test1_layout_and_run_files(test1_pdf):
    texts = page_texts(test1_pdf)
    assert EXEC_TITLES[0] in texts[0] and EXEC_TITLES[1] in texts[1] and APPENDIX_TITLES[0] in texts[2]
    assert len(page_texts(test1_pdf.parent / "report_executive.pdf")) == 2
    assert (test1_pdf.parent / "facts.json").exists() and (test1_pdf.parent / "run_log.txt").exists()


@requires_test1
def test_test1_executive_pages_stand_on_their_own(test1_pdf):
    p1, p2 = (" ".join(x.split()) for x in page_texts(test1_pdf.parent / "report_executive.pdf"))
    for text in ("Fidelity Index US Fund P Accumulation", "Reporting period: 5 years to 30 Sep 2026",
                 "INVESTMENT ASSESSMENT (SUGGESTED)", "Monitor until a peer is added", "EVIDENCE QUALITY",
                 "13.8% a year", "−0.10 pp a year", "0.06% a year", "Summary", "Key findings",
                 "Its noon price makes it look 3.3 pp behind its index over 5 years", "The four ratings",
                 "Moves in line with its index (R² 1.00, beta 1.00; 3 years, factsheet)",
                 "Bands: the Performance limits for the size of the gap"):
        assert text in p1, text
    for text in ("Benchmark and peers", "Fees", "Not disclosed in the documents provided", "Risk",
                 "Tracking error, 3 years", "Material issues", "Not enough evidence to judge", "Recommended actions",
                 "Questions for the manager", "Analyst sign-off", "Suggested assessment: Monitor until a peer is added", "Reviewer name", "Satisfied", "Action needed",
                 "Analyst's comments", "If you disagree with the suggested assessment, why?", "Signature"):
        assert text in p2, text


@requires_test1
def test_test1_evidence_dashboard(test1_pdf):
    dash = section(page_texts(test1_pdf), APPENDIX_TITLES[0])
    for text in ("Evidence dashboard", "Each rated figure (◆) against its Green, Amber and Red zones",
                 "Fund market-close price (PNAV) minus index, each calendar year 2016–2025. Source: factsheet",
                 "Hit rate, calendar years", "Average yearly gap", "Best year", "Worst year",
                 "Significance test (one-sample t-test against zero, 5% level)",
                 "Not reliable: the data is rounded and too short for a significance test",
                 "Fund vs peers chart left out: no peer with returns in GBP"):
        assert text in dash, text


@requires_test1
def test_test1_page2_figures_and_sources(test1_pdf):
    p2 = section(page_texts(test1_pdf), APPENDIX_TITLES[1])
    for text in ("88.3%", "90.9%", "91.6%", "13.8%", "13.9%", "0.10 pp", "0.02%", "1.00", "Factsheet", "Calculated",
                 "Calendar-year returns", "Below the surface", "noon", "Growth of 100"):
        assert text in p2, text


@requires_test1
def test_test1_page2_review_fixes(test1_pdf):
    p2 = section(page_texts(test1_pdf), APPENDIX_TITLES[1])
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
    p3 = section(page_texts(test1_pdf), APPENDIX_TITLES[2])         # table cells wrap lines
    for text in ("Add peer", "Not disclosed in the documents provided", "Partly", "Quality of service",
                 "Classes of units", "It does not replace the AFM's formal Assessment of Value",
                 "No market context"):
        assert text in p3, text


@requires_test1
def test_test1_appendix(test1_pdf):
    p4 = section(page_texts(test1_pdf), APPENDIX_TITLES[3])
    for text in ("Data checks and flags", "Excluded web sources", "Sources", "fund_profile.json",
                 "illustrative, to be agreed with the oversight team", "Glossary", "tracking difference",
                 "Known limitations", "Public data only", "checked against factsheet: consistent"):
        assert text in p4, text
    flat = p4
    assert "Calculated Sharpe ratio Fund 0.98 (5 years, noon price (NAV), calculated from prices with a risk-free rate" in flat
    assert "not comparable with the factsheet Sharpe ratio" in flat
    # 5. Glossary: the terms used, including the new ones
    glossary = flat.split("Glossary (terms used in this report)")[1].split("Known limitations")[0]
    for term in ("NAV:", "Sharpe ratio:", "information ratio:", "alpha:", "largest fall:", "Assessment of Value (AoV):",
                 "AFM:"):
        assert term in glossary, term


def test_glossary_lists_only_terms_the_report_uses(tmp_path):
    texts = page_texts(build_report(made_up_inputs(), tmp_path))
    glossary = section(texts, APPENDIX_TITLES[3]).split("Glossary (terms used in this report)")[1].split("Known limitations")[0]
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


# Stage 4B: a long AI summary never stops the Executive Report being made
def test_a_long_ai_summary_falls_back_to_codes_summary_on_the_executive_pages_only(tmp_path):
    from fund_performance.executive import EXECUTIVE_FALLBACK, build_executive_reliably
    inp = made_up_inputs()
    concl = inp.facts["suggested_conclusion"]
    code_text = concl.get("code_text") or concl["text"]
    long_ai = "The evidence suggests the fund stayed close to its index over the period. " * 30
    inp.facts["suggested_conclusion"] = concl | {"text": long_ai, "source": "ai", "angle": "board", "code_text": code_text}
    with pytest.raises(ReportLayoutError):
        build_executive(inp, tmp_path / "plain")                       # without the fallback it would not fit
    path, flag = build_executive_reliably(inp, tmp_path / "exec")
    pages = page_texts(path)
    text = " ".join(" ".join(pages).split())
    assert len(pages) == 2 and flag.level == "info" and flag.message == EXECUTIVE_FALLBACK
    assert " ".join(code_text.split()) in text and long_ai.split(".")[0] not in text
    assert "the AI draft did not fit on this page and is kept in full in the Detailed Report" in text
    assert inp.facts["suggested_conclusion"]["text"] == long_ai          # the run's facts keep the AI text
    detailed = " ".join(" ".join(page_texts(build_report(inp, tmp_path / "detailed"))).split())
    assert " ".join(long_ai.split()) in detailed                         # kept in full in the Detailed Report


def test_a_short_ai_summary_or_code_summary_is_used_as_it_is(tmp_path):
    from fund_performance.executive import build_executive_reliably
    inp = made_up_inputs()
    path, flag = build_executive_reliably(inp, tmp_path)
    assert flag is None and len(page_texts(path)) == 2
    inp.facts["drafts"] = []
    inp.facts["suggested_conclusion"] |= {"source": "ai", "angle": "board", "code_text": "x"}
    assert build_executive_reliably(inp, tmp_path / "b")[1] is None


def test_overlong_drafts_fail_codes_checks():
    from fund_performance.agents.reporter import MAX_SUMMARY_CHARS, draft_problems
    from fund_performance.config import load_settings
    assert load_settings().drafting.max_summary_chars == MAX_SUMMARY_CHARS == 700
    facts = made_up_inputs().facts
    short = "Short. " * 3
    assert not any(p.startswith("style: ") and "characters" in p for p in draft_problems(short, facts))
    long_text = ("x" * 200 + ". ") * 4
    assert f"style: {len(long_text.strip())} characters; use at most 700 (shorter sentences)" in \
        draft_problems(long_text.strip(), facts)
    assert not any("characters" in p for p in draft_problems(long_text.strip(), facts, max_chars=2000))
