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


def test_historical_repeated_prices_are_grouped_consistently_in_dashboard_and_report():
    from fund_performance.executive import material_issues
    entries = [{'check': 'repeated_prices', 'level': 'warning', 'message':
                f'Suspicious repeated price {value}; flagged dates are outside the five-year price window'}
               for value in ('0.95', '1.01')]
    d = data(flags=entries)
    d['facts']['data_flags'] = entries
    d['facts']['figures'][0]['source'] = 'ai_extracted'
    q = evidence_quality(d)
    assert q.level == 'clear' and len(q.warnings) == 1
    for output in (text(dashboard_html(d)), text(material_issues(d))):
        assert output.count('Historical repeated prices fall outside') == 1
        assert 'Evidence note' in output and '0.95' not in output and '1.01' not in output
    assert d['facts']['data_flags'] == entries


def test_four_sections_show_question_separate_assessments_and_partial_evidence():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    question = 'For a five-year investor,\nwhat matters most?'
    d['presentation_context'] = {'question': question,
        'fund_context': {'document_summary': 'A global index strategy.', 'mandate_interpretation': 'Tracks the index.',
                         'portfolio_exposures': {'sectors': [{'name': 'Technology', 'source': 'fund.pdf'}]}},
        'investment_assessment': {'status': 'available', 'assessment': {
            'recommendation': 'monitor', 'investment_thesis': 'Watch concentration.', 'scorecard_agreement': False,
            'scorecard_disagreement_reason': 'Concentration merits monitoring.'}}, 'research': []}
    views = dashboard_sections(d)
    assert set(views) == {'overview', 'performance', 'portfolio', 'evidence'}
    assert question in views['overview'] and 'Retain' in views['overview'] and 'Monitor' in views['overview']
    assert 'Concentration merits monitoring.' in views['overview']
    assert 'Technology' in views['portfolio'] and 'fund.pdf' in views['portfolio']
    assert 'No vetted research' in views['portfolio'] and 'Returns to' in views['performance']


def test_ai_assessment_status_and_unavailable_reason_are_clear_and_escaped():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    assessment = {'recommendation': 'satisfied', 'investment_thesis': 'The fund tracks its index.'}
    for status, label in [('reviewed', 'Reviewed'), ('qualified_draft', 'Qualified draft')]:
        d['presentation_context'] = {'investment_assessment': {'status': 'available', 'review_status': status,
                                                                'assessment': assessment}}
        overview = text(dashboard_sections(d)['overview'])
        assert f'AI assessment status: {label}' in overview and 'Satisfied' in overview and 'Retain' in overview
    d['presentation_context'] = {'investment_assessment': {'status': 'unavailable',
        'reason': 'Check the evidence <script>unsafe</script>.'}}
    raw = dashboard_sections(d)['overview']
    assert 'AI assessment status: Unavailable' in raw and 'Check the evidence' in raw and '<script>' not in raw


def test_partial_assessment_displays_reviewer_observations_and_supported_evidence():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    d['presentation_context'] = {'investment_assessment': {
        'status': 'partial', 'review_status': 'requires_analyst_review',
        'assessment': {'recommendation': None, 'supporting_evidence': ['Tracking evidence is available.']},
        'reviewer_observations': ['Verify provisional figures before sign-off.'],
        'evidence_summary': 'The deterministic scorecard and source evidence remain available.'}}
    overview = text(dashboard_sections(d)['overview'])
    assert 'Requires analyst review' in overview and 'Recommendation requires further assessment' in overview
    assert 'Tracking evidence is available.' in overview and 'Verify provisional figures' in overview
    assert 'Retain' in overview


def test_analyst_summary_is_bounded_and_details_preserve_full_assessment():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    thesis = ' '.join(f'word{i}' for i in range(120))
    ai = {'recommendation': 'monitor', 'investment_thesis': thesis,
          'supporting_evidence': [f'finding {i}' for i in range(6)],
          'strengths': ['extra strength'], 'material_risks': [f'risk {i}' for i in range(5)],
          'recommended_actions': [f'action {i}' for i in range(5)],
          'manager_questions': ['A specific manager question?'], 'evidence_references': ['research:1'],
          'uncertainties': ['A provisional figure needs verification.']}
    d['presentation_context'] = {'investment_assessment': {
        'status': 'available', 'review_status': 'qualified_draft', 'assessment': ai,
        'reviewer_observations': ['Reviewer says verify the source.'],
        'limitations': ['Evidence is provisional.'], 'diagnostics': {'attempts': [{'review': 'accepted'}]},
        'evidence': {'research:1': {'summary': 'Full source evidence.'}}}}
    before = copy.deepcopy(d['presentation_context'])
    html = dashboard_sections(d)['overview']
    default, details = html.split('<summary>Detailed AI Analysis</summary>', 1)
    assert 'Qualified draft' in default and 'word89' in default and 'word90' not in default
    assert 'finding 3' in default and 'finding 4' not in default
    assert 'risk 2' in default and 'risk 3' not in default
    assert 'action 2' in default and 'action 3' not in default
    assert 'Reviewer says verify the source.' in default and 'Evidence is provisional.' in default
    assert 'A specific manager question?' not in default and 'A specific manager question?' in details
    assert 'word119' in details and 'Full source evidence.' in details and 'accepted' in details
    assert d['presentation_context'] == before


def test_evidence_gap_summary_is_visible_in_evidence_tab():
    from fund_performance.dashboard import dashboard_sections
    d = data(presentation_context={'evidence_gaps': ['No benchmark price series was loaded.']})
    output = text(dashboard_sections(d)['evidence'])
    assert 'Evidence gaps and next steps' in output and 'No benchmark price series was loaded.' in output


def test_sourced_allocation_bars_and_qualitative_fallback():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    d['presentation_context'] = {'fund_context': {'portfolio_exposures': {
        'sectors': [{'name': 'Technology', 'weight_pct': 25, 'source': 'fund.pdf, page 1',
                     'excerpt': 'Fund technology sector 25%', 'evidence_level': 'provisional'},
                    {'name': 'Unverified', 'weight_pct': 40, 'source': 'fund.pdf',
                     'excerpt': 'Fund sector 41%', 'evidence_level': 'provisional'},
                    {'name': 'Benchmark weight', 'weight_pct': 50, 'source': 'index.pdf',
                     'evidence_level': 'verified', 'subject': 'benchmark'}],
        'regions': [{'name': 'Global diversification', 'weight_pct': None, 'source': 'fund.pdf'}]}}}
    html = dashboard_sections(d)['portfolio']
    assert "width:25%" in html and 'Sector allocation' in html and 'provisional' in html
    assert "width:40%" not in html and "width:50%" not in html and 'Global diversification' in html


def test_question_answer_preserves_requested_action_alongside_signoff():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    d['facts']['figures'][0]['source'] = 'ai_extracted'
    d['facts']['data_flags'] = [{'check': 'repeated_prices', 'level': 'warning', 'message': 'Repeated price'}]
    d['facts']['suggested_conclusion'] = {'source': 'ai', 'answer': 'The fund tracks its benchmark.',
        'evidence': ['Tracking is close.'], 'next_step': 'Ask the manager about the fee.'}
    d['presentation_context'] = {'question': '  Please assess the fund.\nExplain the risks.  '}
    overview = dashboard_sections(d)['overview']
    assert '  Please assess the fund.\nExplain the risks.  ' in overview
    assert 'The fund tracks its benchmark.' in overview and 'Tracking is close.' in overview
    assert 'Ask the manager about the fee.' in overview and 'Sign-off check' in overview


def test_rating_explanations_show_logic_evidence_and_peer_limitations():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    d['facts']['peers'][0].update(investor_type='institutional', minimum_investment='GBP 1,000,000')
    overview = text(dashboard_sections(d)['overview'])
    assert all(name in overview for name in ('Mandate', 'Performance', 'Value for investors', 'Fees'))
    assert 'R² and beta alone do not establish' in overview and 'Tracking difference provides a separate' in overview
    assert '1,000,000' in overview and 'institutional share class' in overview
    assert 'Rating methodology' in overview and 'Supporting evidence' in overview


def test_strategy_and_research_use_progressive_disclosure_and_safe_links():
    from fund_performance.dashboard import dashboard_sections
    d = data()
    long_summary = 'Long original source description. ' * 30
    d['presentation_context'] = {'fund_context': {'document_summary': long_summary}, 'research': [
        {'summary': 'The benchmark changed. A longer source discussion follows.', 'url': 'https://example.org/a',
         'date': '2026-10-15', 'date_basis': 'published', 'relevance': 'The fund tracks this benchmark.',
         'limitations': 'Published after the review.'},
        {'summary': 'Unsafe source.', 'url': 'javascript:alert(1)', 'date': '2026-08-01'}]}
    page = dashboard_sections(d)['portfolio']
    assert '<summary>Source details</summary>' in page and long_summary in page
    assert "href='https://example.org/a'" in page and "href='javascript:" not in page
    assert 'published after review date' in page and 'Full research summaries' in page


def test_chart_evidence_states_and_observed_date_alignment(tmp_path):
    import pandas as pd
    from fund_performance.charts import dashboard_five_year_chart
    dates = pd.date_range('2021-09-30', '2026-09-30', freq='ME')
    prices = pd.DataFrame({'date': dates, 'nav': range(100, 100 + len(dates)),
                           'index_level': range(200, 200 + len(dates))})
    evidence = {'benchmark_identity_confirmed': True, 'fund_total_return': True,
                'benchmark_total_return': True, 'currency': 'GBP', 'benchmark_pricing': 'midday'}
    def chart(frame=prices, ev=evidence, date='2026-09-30'):
        return dashboard_five_year_chart(frame, date, 'GBP', 'midday', ev, tmp_path / 'chart.png')
    before = prices.copy(deep=True)
    verified = chart()
    assert verified['state'] == 'verified' and 'Verified historical' in verified['caption']
    indicative = chart(ev={})
    assert indicative['state'] == 'indicative' and 'Return treatment requires verification' in indicative['caption']
    timed = chart(ev=evidence | {'benchmark_pricing': 'market_close'})
    assert timed['state'] == 'indicative' and 'Fund NAV at noon' in timed['caption']
    assert not chart(ev=evidence | {'currency': 'USD'})['available']
    assert not chart(ev=evidence | {'benchmark_total_return': False})['available']
    assert not chart(frame=prices.drop(columns='index_level'))['available']
    assert not chart(frame=pd.concat([prices, prices.iloc[[0]]]))['available']
    invalid = prices.copy()
    invalid.loc[2, 'nav'] = 0
    assert not chart(frame=invalid)['available']
    assert not chart(frame=prices.drop(index=[2, 3]))['available']
    holiday = chart(date='2026-10-03')
    assert holiday['available'] and '30 Sep 2026' in holiday['caption']
    shorter = chart(frame=prices.iloc[12:])
    assert shorter['state'] == 'indicative' and 'Shorter Period' in shorter['title']
    pd.testing.assert_frame_equal(prices, before)


def test_review_surfaces_automatic_chart_and_qualifies_reports(tmp_path):
    from fund_performance.controller import run_review
    from fund_performance.dashboard import dashboard_data, dashboard_sections
    from fund_performance.report import page_texts
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    result = asyncio.run(run_review(sample, out_root=tmp_path, offline=True))
    displayed = dashboard_data(result)
    html = dashboard_sections(displayed)['performance']
    assert displayed['primary_chart_status']['state'] == 'indicative' and displayed['primary_chart']
    assert 'Indicative Comparison' in html and 'Return treatment requires verification' in html
    assert 'Tracking analysis' in html and result.pdf.is_file() and result.executive_pdf.is_file()
    for report in (result.pdf, result.executive_pdf):
        text = ' '.join(' '.join(page_texts(report)).split())
        assert 'Indicative historical comparison' in text and 'Return treatment requires verification' in text


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
    d["facts"]["drafts"] = [{"angle": "board", "score": 5, "max_score": 5, "checks": {"figures_match": True},
                             "decision": "pass", "reason": "Accurate and clear.", "chosen": True, "issues": [],
                             "rewritten": False, "text": "x"}]
    page = text(dashboard_html(d, "analyst") + technical_html(d))
    facts = d["facts"]
    for expected in ([facts["fund"]["fund_name"], "30 Sep 2026", "Satisfied", facts["suggested_conclusion"]["text"],
                      "Finding one.", "Action one.", "Warning: Gap in prices", "Risk-free rate 0", "Plan (",
                      "Draft and the Judge's review", "approved by the Judge", "Accurate and clear."]
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


def test_the_summary_shows_the_answer_then_the_supporting_evidence():
    d = data()
    d["facts"]["suggested_conclusion"] = {"source": "ai", "angle": "analyst", "text": "x",
                                          "answer": "Yes, the fund met its objective.",
                                          "evidence": ["It tracked its index closely.", "Its fee is competitive."]}
    page = text(dashboard_html(d, "analyst"))
    assert page.index("Answer") < page.index("Yes, the fund met its objective.") < page.index("Supporting evidence")
    assert page.index("Supporting evidence") < page.index("It tracked its index closely.")
    d["facts"]["suggested_conclusion"] = {"source": "code", "text": "Code's conclusion."}
    assert "Supporting evidence" not in text(dashboard_html(d, "analyst"))      # code's conclusion: one paragraph


def test_the_dashboard_summary_is_answer_evidence_next_step_with_data_issues_collapsed():
    d = data()
    d["facts"]["suggested_conclusion"] = {"source": "ai", "angle": "analyst", "text": "x",
                                          "answer": "Partly: it tracked its index, but the fee needs a peer check.",
                                          "evidence": ["It tracked its index closely."],
                                          "next_step": "Ask the manager for a peer fee comparison."}
    html = dashboard_html(d, "analyst")
    page = text(html)
    assert page.index("Answer") < page.index("Supporting evidence") < page.index("Recommended next step")
    assert "Ask the manager for a peer fee comparison." in page
    summary = html.split("<h3>Summary</h3>", 1)[1].split("</div>", 1)[0]
    assert "Suggested verdict:" not in summary                     # the verdict has its own section, not prose
    if "Data quality and missing evidence" in summary:
        assert "<details class='fp-details'>" in summary            # data issues are listed once, collapsed


def test_code_fallback_shows_codes_conclusion_and_codes_next_step():
    from fund_performance.presentation import next_step
    d = data()
    d["facts"]["suggested_conclusion"] = {"source": "code", "text": "Code's conclusion."}
    d["facts"]["candidate_actions"] = [{"id": "record_decision", "action": "Record the decision.", "required": False},
                                       {"id": "add_peer", "action": "Add a peer fund factsheet.", "required": False}]
    page = text(dashboard_html(d, "analyst"))
    assert "Code's conclusion." in page and "Supporting evidence" not in page
    assert next_step(d["facts"]) == "Add a peer fund factsheet." and "Add a peer fund factsheet." in page
def test_next_step_covers_both_extraction_and_repeated_price_warnings():
    from fund_performance.presentation import next_step
    facts = {"figures": [{"source": "ai_extracted"}], "data_flags": [
        {"check": "repeated_prices", "level": "warning"}],
        "suggested_conclusion": {"source": "ai", "next_step": "Check the figures."}}
    text = next_step(facts)
    assert "AI-extracted" in text and "flagged historical prices" in text and "before sign-off" in text
