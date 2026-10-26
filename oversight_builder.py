""" The 3-page Investment Oversight Report (PDF HTML and Markdown) """
from datetime import date
from html import escape
import pandas as pd
from analysis import FundAnalysis
from calculator import fmt_pct, top_and_bottom
from mandate_agent import Mandate
from oversight import (OversightResult, RULES, GREEN, AMBER, RED, CHECK_DATA, FEE_EXAMPLE_AMOUNT, FEE_HORIZON_YEARS,
                       comparison_markdown, comparison_cell)
from oversight_agent import OversightReport

NAVY, GREY, LIGHT = "#12355b", "#6b7785", "#f2f5f8"
COLOURS = {GREEN: "#2e7d32", AMBER: "#e0a100", RED: "#c62828", CHECK_DATA: "#6d4c9f"}
VERDICT_COLOURS = {"Retain": "#2e7d32", "Monitor": "#e0a100", "Review": "#c62828", "Incomplete data": "#6b7785"}
DISCLAIMER = ("Draft prepared by an AI agent for demonstration; not investment advice. Ratings follow the fixed rules above, "
              "all figures are calculated from the data listed, and the verdict needs human approval.")

CSS = f"""
@page {{ size: a4 portrait; margin: 1.4cm 1.6cm 1.9cm 1.6cm;
  @frame footer {{ -pdf-frame-content: footer; left: 1.6cm; width: 17.8cm; bottom: 0.7cm; height: 0.8cm; }} }}
body {{ font-family: Helvetica; font-size: 8.6pt; line-height: 1.35; color: #1d2733; }}
h2 {{ font-size: 11.5pt; color: {NAVY}; border-bottom: 1.5px solid {NAVY}; padding-bottom: 2px; margin: 10px 0 5px 0; -pdf-keep-with-next: true; }}
h3 {{ font-size: 9.5pt; color: {NAVY}; margin: 8px 0 3px 0; -pdf-keep-with-next: true; }}
p {{ margin: 0 0 4px 0; }} ul {{ margin: 0 0 4px 0; }} li {{ margin-bottom: 2px; }}
table {{ width: 100%; }}
.banner td {{ background-color: {NAVY}; color: white; padding: 8px 10px; }}
.b1 {{ font-size: 16pt; font-weight: bold; }} .b2 {{ font-size: 8pt; color: #c9d6e3; }} .b0 {{ font-size: 7pt; color: #8fb3d9; }}
.data th {{ background-color: {NAVY}; color: white; font-weight: bold; padding: 3px 4px 1px 4px; text-align: right; }}
.data td {{ padding: 3px 4px 1px 4px; border-bottom: 0.5px solid #d5dbe1; text-align: right; vertical-align: top; }}
.data th.left, .data td.left {{ text-align: left; }}
.data tr.total td {{ font-weight: bold; background-color: {LIGHT}; }}
.score td {{ padding: 4px 4px 2px 4px; border-bottom: 0.5px solid #d5dbe1; vertical-align: top; }}
.score th {{ background-color: {NAVY}; color: white; padding: 3px 4px 1px 4px; text-align: left; }}
.chip {{ color: white; font-weight: bold; text-align: center; }}
.box td {{ background-color: {LIGHT}; border-left: 3px solid {NAVY}; padding: 6px 8px; }}
.small {{ font-size: 7pt; color: {GREY}; }}
.pos {{ color: #2e7d32; }} .neg {{ color: #c62828; }}
img {{ width: 17.4cm; }}
#footer {{ font-size: 7pt; color: {GREY}; border-top: 0.5px solid #d5dbe1; padding-top: 3px; }}
"""


def _signed(value: float) -> str:
    css = "pos" if round(value, 4) > 0 else "neg" if round(value, 4) < 0 else ""
    return f'<span class="{css}">{fmt_pct(value, signed=True)}</span>'


def _bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def _periods_table(periods: pd.DataFrame) -> str:
    head = '<th class="left"></th>' + "".join(f"<th>{c}</th>" for c in periods.columns)
    rows = ""
    for name, row in periods.iterrows():
        cells = "".join(f"<td>{_signed(v) if name == 'Relative' else fmt_pct(v)}</td>" for v in row)
        css = ' class="total"' if name == "Relative" else ""
        rows += f'<tr{css}><td class="left">{name}</td>{cells}</tr>'
    return f'<table class="data" cellspacing="0"><tr>{head}</tr>{rows}</table>'


def _attribution_block(analysis: FundAnalysis) -> str:
    """ Why the fund beat or lagged its benchmark, by sector (Brinson-Fachler), when attribution data is uploaded """
    total = analysis.attribution.iloc[-1]
    effects = "".join(f'<tr><td class="left">{e}</td><td>{_signed(total[e])}</td></tr>'
                      for e in ("Allocation", "Selection", "Interaction"))
    top, bottom = top_and_bottom(analysis.attribution)
    def names(df):
        return ", ".join(f"{escape(str(r.Segment))} ({fmt_pct(r.Total, True)})" for r in df.itertuples()) or "none"
    return (f"<h3>Why: attribution by sector (period: {escape(analysis.attribution_period)})</h3>"
            '<table cellspacing="0"><tr><td width="42%" valign="top">'
            f'<table class="data" cellspacing="0"><tr><th class="left">Effect</th><th>Contribution</th></tr>{effects}'
            f'<tr class="total"><td class="left">Active return</td><td>{_signed(total["Total"])}</td></tr></table></td>'
            f'<td valign="top" style="padding-left: 10px;"><p><b>Added most:</b> {names(top)}</p>'
            f"<p><b>Took most away:</b> {names(bottom)}</p>"
            '<p class="small">Allocation = being over- or under-weight in a sector; selection = picking better or worse '
            "stocks within it.</p></td></tr></table>")


def _chip(rating: str) -> str:
    colour = COLOURS.get(rating, "#9aa5b1")
    return f'<td class="chip" width="13%" style="background-color: {colour};">{escape(rating.upper())}</td>'


def _scorecard(result: OversightResult, report: OversightReport) -> str:
    questions = {"Mandate": "Is it doing what it promised?", "Performance": "How did it do vs its benchmark?",
                 "Value for investors": "Did investors get good value?", "Fees": "Is the fee justified?"}
    comments = report.pillar_comments + [""] * (4 - len(report.pillar_comments))
    rows = "".join(
        f'<tr><td width="20%"><b>{escape(p.name)}</b><br/><span class="small">{questions.get(p.name, "")}</span></td>'
        f'{_chip(p.rating)}<td width="30%">{escape(p.evidence)}</td><td>{escape(c)}</td></tr>'
        for p, c in zip(result.pillars, comments))
    return ('<table class="score" cellspacing="0"><tr><th>Question</th><th>Rating</th><th>Evidence (calculated)</th>'
            f'<th>Assessment</th></tr>{rows}</table>')


def _comparison_table(result: OversightResult) -> str:
    df = result.comparison
    head = "".join(f"<th>{escape(c)}</th>" for c in df.columns)
    rows = ""
    for i, (name, r) in enumerate(df.iterrows()):
        css = ' class="total"' if i == 0 else ""
        cells = "".join(f"<td>{comparison_cell(c, r[c])}</td>" for c in df.columns)
        rows += f'<tr{css}><td class="left">{escape(str(name))}</td>{cells}</tr>'
    return f'<table class="data" cellspacing="0"><tr><th class="left" width="34%">Fund</th>{head}</tr>{rows}</table>'


def _risk_table(analysis: FundAnalysis) -> str:
    m = analysis.metrics
    rows = [("Annualised volatility", fmt_pct(m.at["Annualised volatility", "Fund"]), fmt_pct(m.at["Annualised volatility", "Benchmark"])),
            ("Maximum fall from peak", fmt_pct(m.at["Max drawdown", "Fund"]), fmt_pct(m.at["Max drawdown", "Benchmark"])),
            ("Sharpe ratio", f'{m.at["Sharpe ratio", "Fund"]:.2f}', f'{m.at["Sharpe ratio", "Benchmark"]:.2f}'),
            ("Tracking error", fmt_pct(m.at["Tracking error", "Relative"]), ""),
            ("Information ratio", f'{m.at["Information ratio", "Relative"]:.2f}', "")]
    body = "".join(f'<tr><td class="left">{a}</td><td>{b}</td><td>{c}</td></tr>' for a, b, c in rows)
    return (f'<table class="data" cellspacing="0"><tr><th class="left">Risk (full period, {analysis.period_label})</th>'
            f'<th>Fund</th><th>Benchmark</th></tr>{body}</table>')


def build_oversight_html(report: OversightReport, analysis: FundAnalysis, mandate: Mandate, result: OversightResult,
                         fund_name: str, benchmark: str, searches: list[str]) -> str:
    today = f"{date.today():%d %B %Y}"
    colour = VERDICT_COLOURS.get(result.verdict, NAVY)
    peer_name = result.peer["name"] if result.peer else "none"
    banner = (f'<table class="banner" cellspacing="0"><tr><td><span class="b0">INVESTMENT OVERSIGHT REPORT</span><br/><br/>'
              f'<span class="b1">{escape(fund_name)}</span><br/><span class="b2">Benchmark: {escape(benchmark)} &nbsp;|&nbsp; '
              f'Peer: {escape(peer_name)} &nbsp;|&nbsp; Data: {escape(analysis.data_label)} &nbsp;|&nbsp; Prepared: {today}</span></td></tr></table>')
    verdict = (f'<table cellspacing="0" style="margin-top: 6px;"><tr><td width="22%" style="background-color: {colour}; color: white; '
               f'font-weight: bold; font-size: 13pt; text-align: center; padding: 8px;">{result.verdict.upper()}</td>'
               f'<td style="padding: 6px 10px; background-color: {LIGHT};"><b>Draft verdict.</b> {escape(report.verdict_reason)}</td></tr></table>')
    approval = ('<table class="box" cellspacing="0"><tr><td><b>Human approval</b> &nbsp; Reviewed by: _______________ &nbsp; '
                'Date: _________ &nbsp; Decision: [ &nbsp; ] Retain &nbsp; [ &nbsp; ] Monitor &nbsp; [ &nbsp; ] Review</td></tr></table>')

    page1 = (banner + verdict + "<h2>Oversight scorecard</h2>" + _scorecard(result, report)
             + "<h2>Key findings</h2>" + _bullets(report.key_findings)
             + "<h2>Recommended actions</h2>" + _bullets(report.actions) + approval)

    commitments = _bullets(mandate.commitments) if mandate.commitments else "<p>No specific commitments found in the documents.</p>"
    page2 = (f"<h2>1. Mandate</h2><p><b>Objective:</b> {escape(mandate.objective)}</p>"
             f"<p><b>Fund type:</b> {'Index (passive)' if result.fund_type == 'passive' else 'Actively managed'}. "
             f"The objective is tested in the scorecard; the commitments below are listed for the reviewer to confirm.</p>"
             + "<h3>Commitments in the fund documents</h3>" + commitments)
    if analysis.periods is not None:
        title = f"Returns by period ({analysis.data_label})" if analysis.official else "Returns by period"
        page2 += "<h2>2. Performance against the benchmark</h2>" + f"<h3>{escape(title)}</h3>" + _periods_table(analysis.periods)
        if analysis.official:
            page2 += '<p class="small">Reported by the fund manager, after fees. Periods over 1 year are a year.</p>'
        if analysis.calendar is not None:
            page2 += "<h3>Calendar-year returns</h3>" + _periods_table(analysis.calendar)
        if analysis.metrics is not None:
            page2 += "<h3>Risk (from prices)</h3>" + _risk_table(analysis)
        if analysis.attribution is not None:
            page2 += _attribution_block(analysis)
        if "growth" in analysis.charts:
            page2 += (f'<table cellspacing="0"><tr><td><img src="{analysis.charts["growth"]}"/><p class="small">'
                      f"Growth of 100, {analysis.period_label}. Source: price data listed on page 3.</p></td></tr></table>")
        elif "calendar" in analysis.charts:
            page2 += (f'<table cellspacing="0"><tr><td><img src="{analysis.charts["calendar"]}"/><p class="small">'
                      "Calendar-year returns, official figures. Source: listed on page 3.</p></td></tr></table>")
    else:
        page2 += "<h2>2. Performance against the benchmark</h2><p>No performance figures or price data were supplied.</p>"

    page3 = "<h2>3. Value for investors and fees</h2>"
    if result.comparison is not None:
        intro = ("Compared with one peer, using both funds' reported returns after fees"
                 if result.comparison_period.startswith("official") else "Compared with one peer over the same months")
        page3 += f"<p>{intro} ({escape(result.comparison_period)}).</p>" + _comparison_table(result)
        if result.fee_costs:
            costs = " &nbsp;vs&nbsp; ".join(f"{escape(k)}: <b>£{v:,.0f}</b>" for k, v in result.fee_costs.items())
            page3 += f"<h3>What the fee costs</h3><p>Fees on £{FEE_EXAMPLE_AMOUNT:,} over {FEE_HORIZON_YEARS} years (ignoring growth): {costs}.</p>"
        if result.fee_justified is not None:
            page3 += ("<p><b>Did the extra fee pay for itself?</b> "
                      + ("Yes: after fees, the fund returned more than the cheaper peer." if result.fee_justified
                         else "No: after fees, the fund returned less than the cheaper peer.") + "</p>")
    else:
        reason = next((p.evidence for p in result.pillars if p.name == "Value for investors"), "")
        page3 += f"<p>Value and fees could not be compared with a peer: {escape(reason)}</p>"
    sources = [analysis.parsed.sources[k] for k in ("performance", "nav") if k in analysis.parsed.sources
               and not analysis.parsed.sources[k].endswith((".csv", ".xlsx", ".xls"))]
    uploaded = list(dict.fromkeys([n.split(":")[0] for n in analysis.parsed.notes if "read as" in n]
                                  + [n for n, _ in analysis.parsed.documents]))
    sources += [f"Uploaded: {n}" for n in uploaded] + [f"Web search: {s}" for s in searches]
    page3 += ("<h2>4. Market context</h2>" + f"<p>{escape(report.market_context)}</p>"
              + "<h2>5. What would change our view</h2>" + _bullets(report.triggers)
              + "<h3>How the ratings were decided</h3>" + f'<div class="small">{_bullets(RULES)}</div>'
              + "<h3>Sources</h3>" + f'<div class="small">{_bullets(sources or ["None"])}</div>'
              + f'<p class="small">{DISCLAIMER}</p>')

    footer = (f'<div id="footer">{escape(fund_name)} &nbsp;|&nbsp; Investment oversight report (draft), {today} '
              f'&nbsp;|&nbsp; Page <pdf:pagenumber> of <pdf:pagecount></div>')
    return (f"<html><head><style>{CSS}</style></head><body>{footer}{page1}<pdf:nextpage />{page2}"
            f"<pdf:nextpage />{page3}</body></html>")


def build_oversight_markdown(report: OversightReport, analysis: FundAnalysis, mandate: Mandate,
                             result: OversightResult, fund_name: str) -> str:
    parts = [f"# {report.title}", f"**Draft verdict: {result.verdict}.** {report.verdict_reason}", "## Scorecard",
             "| Question | Rating | Evidence |", "|---|---|---|"]
    parts[-1] += "".join(f"\n| {p.name} | {p.rating} | {p.evidence} |" for p in result.pillars)
    parts += ["## Key findings", "\n".join(f"- {k}" for k in report.key_findings),
              "## Recommended actions", "\n".join(f"- {a}" for a in report.actions),
              f"## Mandate\n\n{mandate.objective}"]
    if result.comparison is not None:
        parts.append(f"## Fund vs peer ({result.comparison_period})\n\n" + comparison_markdown(result.comparison))
    parts += [f"## Market context\n\n{report.market_context}", "## What would change our view",
              "\n".join(f"- {t}" for t in report.triggers), f"*{DISCLAIMER}*"]
    return "\n\n".join(parts)
