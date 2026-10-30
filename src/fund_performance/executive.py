""" The Executive Report (UX redesign, stage 3): exactly two A4 pages for a decision

Page 1 "Overview": fund and period, the suggested investment assessment and the evidence quality (kept apart), three
headline figures, the summary, two or three key findings, one chart chosen for the fund's mandate and data, and the
four ratings. Page 2 "Comparisons and decision": benchmark and peers, fees, selected risk measures, material issues
(insufficient evidence apart from performance concerns, then data issues), recommended actions, up to three questions
for the manager, and the analyst's approval.

Presentation only, from the same facts and shared helpers as the dashboard (presentation.py). Material warnings are
shown in full, never shortened; when there are more data warnings than fit, the page says how many more and where
they are (the Detailed Report's Appendix D). If page 1 or page 2 still runs over, the report is not cut: a layout
error is raised and the caller says so.
"""
from dataclasses import dataclass
from html import escape
from pathlib import Path
from fund_performance import charts
from fund_performance.plain import verdict_meaning, verdict_name
from fund_performance.presentation import (NAVY, NOT_AVAILABLE, RATING_STYLE, VERDICT_STYLE, _figures, _shown,
                                           _source, assessment_caveat, chart_choice, evidence_quality, flag_dicts,
                                           headline_metrics, issue_groups, risk_measures)

PAGE1, PAGE2 = "Overview", "Comparisons and decision"
EXEC_TITLES = (PAGE1, PAGE2)
MAX_FINDINGS, MAX_QUESTIONS, MAX_WARNINGS = 3, 3, 3
SHORT_QUESTIONS = {"Mandate": "Doing what it promised?", "Performance": "Against its index?",
                   "Value for investors": "A fair outcome for investors?", "Fees": "Fee justified?"}


@dataclass
class ExecutiveContent:
    """ What the two pages show, chosen by code from the run """
    data: dict              # facts, reasons, findings, actions, flags (as for the dashboard)
    chart: Path | None
    chart_caption: str


def content_from(inp, out_dir: Path) -> ExecutiveContent:
    """ The run's data in the dashboard's shape, plus the chart picked for this fund """
    facts = inp.facts
    out = inp.narrative.output if inp.narrative else None
    from fund_performance.report import plain_reason
    data = {"facts": facts, "reasons": {name: plain_reason(inp, name) for name in inp.card.pillars},
            "findings": list(out.key_findings) if out else [], "actions": list(out.action_texts) if out else [],
            "flags": flag_dicts(inp.flags)}
    chart, caption = _chart(inp, out_dir)
    return ExecutiveContent(data, chart, caption)


# --- The chart: chosen by the fund's mandate and the data there is -------------------------------------------------

def _chart(inp, out_dir: Path) -> tuple[Path | None, str]:
    facts = inp.facts
    kind = chart_choice(facts)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = facts.get("evidence") or {}
    if kind in ("yearly_gap", "yearly_excess"):
        years, gaps = list(ev["gaps"]), list(ev["gaps"].values())
        series = "market-close price (PNAV)" if ev.get("series") == "fund_pnav" else "fund price (NAV)"
        if kind == "yearly_gap":
            pi, ocf = inp.thresholds.performance_index, inp.profile.ocf_pct
            path = charts.yearly_gap_chart(years, gaps, out_dir / "exec_chart.png",
                                           f"Yearly gap to the index, {years[0]}–{years[-1]}", ocf,
                                           ocf + pi.green_td_margin_over_ocf_pp, ocf + pi.amber_td_margin_over_ocf_pp)
            return path, (f"Fund {series} minus index, each calendar year (pp). Bands: the Performance limits for the "
                          "size of the gap; dashed line: the fee. Source: factsheet; gaps calculated.")
        path = charts.yearly_gap_chart(years, gaps, out_dir / "exec_chart.png",
                                       f"Yearly return above the benchmark, {years[0]}–{years[-1]}")
        return path, f"Fund {series} minus benchmark, each calendar year (pp). Source: factsheet; calculated."
    if kind == "rolling_12m":
        figs = _figures(facts)
        n = facts.get("fund", {}).get("time_horizon_years", 5)
        basis = (figs.get(f"comparison.td.{n}y") or {}).get("basis") or "fund_nav"
        ends = sorted({k.rsplit(".", 1)[1] for k in figs if k.startswith(f"{basis}.discrete_12m.")}
                      & {k.rsplit(".", 1)[1] for k in figs if k.startswith("index.discrete_12m.")})
        if ends:
            fund = [figs[f"{basis}.discrete_12m.{e}"]["value"] for e in ends]
            index = [figs[f"index.discrete_12m.{e}"]["value"] for e in ends]
            path = charts.yearly_returns_chart([f"to {e[5:7]}/{e[2:4]}" for e in ends], fund, index,
                                               out_dir / "exec_chart.png", "Fund", "Index or benchmark",
                                               "12-month returns (%)")
            return path, f"12-month returns, fund vs index or benchmark. Source: {_source(*(figs[f'{basis}.discrete_12m.{e}'] for e in ends))}."
    return None, "No chart: the documents give no calendar-year or 12-month returns for the fund and its benchmark."


# --- Page pieces ---------------------------------------------------------------------------------------------------------

def _ul(items) -> str:
    items = [i for i in items if i]
    return "<ul class='x-list'>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>" if items else ""


def _chip(rating: str) -> str:
    word, colour = RATING_STYLE.get(rating, (rating.title(), "#546e7a"))
    return f"<td class='x-chip' style='background-color:{colour}'>{escape(word)}</td>"


def _banner(inp) -> str:
    p = inp.profile
    n = p.time_horizon_years
    return (f"<table class='x-banner'><tr><td><span class='x-kicker'>FUND PERFORMANCE REVIEW · EXECUTIVE REPORT</span><br/>"
            f"<span class='x-fund'>{escape(p.fund_name)}</span><br/><span class='x-meta'>ISIN {escape(p.isin)} · "
            f"{escape(p.share_class)} · {escape(p.currency)} · Benchmark: {escape(p.benchmark_name)}<br/>Reporting "
            f"period: {n} years to {p.as_of_date:%d %b %Y} · prepared {inp.prepared:%d %b %Y}</span></td></tr></table>")


def _statuses(data: dict) -> str:
    facts = data["facts"]
    code = facts["scorecard"]["verdict"]
    quality = evidence_quality(data)
    colour = next((c for k, c in VERDICT_STYLE.items() if code.startswith(k)), NAVY)
    q_colour = {"check": "#6d4c9f", "warnings": "#b7791f", "clear": "#4c5966"}[quality.level]
    caveat = assessment_caveat(quality)
    return (f"<table class='x-status'><tr>"
            f"<td width='50%' class='x-box' style='border-left: 4px solid {colour}'><span class='x-label'>INVESTMENT "
            f"ASSESSMENT (SUGGESTED)</span><br/><span class='x-big' style='color:{colour}'>{escape(verdict_name(code))}</span>"
            f"<br/>{escape(verdict_meaning(code))}. From fixed rules on the four ratings; the analyst decides."
            f"{('<br/><b>' + escape(caveat) + '</b>') if caveat else ''}</td><td width='2%'></td>"
            f"<td width='48%' class='x-box' style='border-left: 4px solid {q_colour}'><span class='x-label'>EVIDENCE "
            f"QUALITY (DATA CHECKS)</span><br/><span class='x-big' style='color:{q_colour}'>{escape(quality.label)}</span>"
            f"<br/>{escape(quality.detail)}.</td></tr></table>")


def _metrics(facts: dict) -> str:
    cells = "".join(
        f"<td width='33%' class='x-metric'><span class='x-label'>{escape(m.label.upper())}</span><br/>"
        f"<span class='x-value{' x-na' if m.value == NOT_AVAILABLE else ''}'>{escape(m.value)}</span><br/>"
        f"{escape(m.period)}{('<br/>' + escape(m.note)) if m.note else ''}<br/><span class='x-src'>Source: "
        f"{escape(m.source)}</span></td>" for m in headline_metrics(facts))
    return f"<table class='x-metrics'><tr>{cells}</tr></table>"


def key_findings(data: dict) -> list[str]:
    """ Two or three findings that add to the ratings table rather than repeat it: the data-note findings, then the
    first points for judgement (not the standing note about illustrative limits) """
    found = list(data.get("findings", [])[1:])
    points = [p for p in data["facts"].get("judgement_points", []) if not p.startswith("The limits used")]
    for p in points:
        if len(found) >= MAX_FINDINGS:
            break
        found.append(p)
    return found[:MAX_FINDINGS]


def _scorecard(data: dict) -> str:
    rows = ""
    for p in data["facts"]["scorecard"]["pillars"]:
        if p["rating"] == "CHECK DATA":
            why = "Not rated yet: the data check on page 2 must be resolved first."
        else:
            why = data["reasons"].get(p["name"]) or p["reason"]
        rows += (f"<tr><td class='x-q'><b>{escape(p['name'])}</b><br/><span class='x-src'>"
                 f"{escape(SHORT_QUESTIONS.get(p['name'], ''))}</span></td>{_chip(p['rating'])}<td>{escape(why)}</td></tr>")
    return ("<table class='x-grid'><tr><th width='24%' class='l'>Question</th><th width='12%'>Rating</th>"
            f"<th class='l'>Why</th></tr>{rows}</table>")


def page1(inp, content: ExecutiveContent) -> str:
    data = content.data
    concl = data["facts"].get("suggested_conclusion") or {}
    findings = key_findings(data)
    import base64
    chart = (f"<img src='data:image/png;base64,{base64.b64encode(content.chart.read_bytes()).decode()}' width='300'/>"
             if content.chart else "")
    return f"""
{_banner(inp)}
<h1>{PAGE1}</h1>
{_statuses(data)}
{_metrics(data['facts'])}
<table width="100%"><tr><td width="55%" valign="top">
<h2>Summary</h2><p>{escape(concl.get('text', ''))}</p>
{'<h2>Key findings</h2>' + _ul(findings) if findings else ''}
</td><td width="3%"></td><td valign="top" align="center">{chart}<p class='x-src'>{escape(content.chart_caption)}</p></td></tr></table>
<h2>The four ratings</h2>{_scorecard(data)}
"""


def _comparison(inp, facts: dict) -> str:
    figs = _figures(facts)
    n = facts.get("fund", {}).get("time_horizon_years", 5)
    basis = (figs.get(f"comparison.td.{n}y") or {}).get("basis") or "fund_nav"
    fund_label = "This fund, market-close price (PNAV)" if basis == "fund_pnav" else "This fund (NAV)"

    def row(label, cells, fee, used, bold=False):
        cls = " class='x-total'" if bold else ""
        return (f"<tr{cls}><td class='l'>{escape(label)}</td>" + "".join(f"<td>{escape(c)}</td>" for c in cells)
                + f"<td>{escape(fee)}</td><td class='l x-src'>{escape(used)}</td></tr>")
    ann = lambda s: [_shown(figs.get(f"{s}.cum.1y")) if figs.get(f"{s}.cum.1y") else "–"] + [  # noqa: E731
        _shown(figs[f"{s}.ann.{k}y"]) if figs.get(f"{s}.ann.{k}y") else "–" for k in (3, 5)]
    rows = row(fund_label, ann(basis), f"{inp.profile.ocf_pct:.2f}%", _source(*(figs.get(f"{basis}.ann.{k}y") for k in (3, 5))), True)
    rows += row("Index or benchmark", ann("index"), "–", _source(*(figs.get(f"index.ann.{k}y") for k in (3, 5))))
    for p in facts.get("peers", []):
        r = p.get("returns_pct_a_year", {})
        cells = ["–" if r.get(k) is None else f"{r[k]:.1f}%".replace("-", "−") for k in ("1y", "3y", "5y")]
        used = (f"Peer, fees and returns ({p['basis']})" if p.get("used_for_returns")
                else f"Peer, fees only: {p.get('excluded')}")
        rows += row(p["name"], cells, f"{p['ocf_pct']:.2f}%", used)
    gap = figs.get(f"comparison.td.{n}y")
    note = (f"Gap to the index over {n} years: {_shown(gap)} a year (tracking difference; calculated from the "
            "factsheet). Returns a year; 1 year is the 1-year return." if gap else
            "Returns a year; 1 year is the 1-year return.")
    if not facts.get("peers"):
        note += " No comparable peer was supplied or approved for this benchmark."
    return ("<table class='x-grid num'><tr><th class='l' width='34%'>Fund</th><th>1 year</th><th>3 years</th>"
            f"<th>5 years</th><th>Fee</th><th class='l' width='25%'>Source / use</th></tr>{rows}</table>"
            f"<p class='x-src'>{escape(note)}</p>")


def _fees_and_risk(inp, facts: dict) -> str:
    p = inp.profile
    value, fees = inp.card.pillars["Value for investors"].values, inp.card.pillars["Fees"].values
    fee_rows = [("Ongoing charge (OCF)", f"{p.ocf_pct:.2f}% a year"),
                ("Transaction costs", "Not disclosed in the documents provided" if p.transaction_cost_pct is None
                 else f"{p.transaction_cost_pct:.2f}%"),
                ("Performance fee", "Yes" if p.performance_fee else "None")]
    if fees.get("peer_ocf") is not None:
        fee_rows.append(("Peers' average fee", f"{fees['peer_ocf']:.2f}% ({'; '.join(f'{x:.2f}%' for x in fees.get('peer_fees', []))})"))
    if value.get("gap_pp") is not None:
        fee_rows.append((f"Peer return gap, {value['years']} years", f"{value['gap_pp']:+.2f} pp a year".replace("-", "−")))
    fee_html = "".join(f"<tr><td class='l'>{escape(a)}</td><td class='l'>{escape(b)}</td></tr>" for a, b in fee_rows)
    risk = risk_measures(facts)[:6]
    risk_html = "".join(f"<tr><td class='l'>{escape(a)}</td><td>{escape(b)}</td><td class='l x-src'>{escape(c)}</td></tr>"
                        for a, b, c in risk) or "<tr><td class='l' colspan='3'>No risk figures in the documents.</td></tr>"
    return (f"<table width='100%'><tr><td width='48%' valign='top'><h2>Fees</h2><table class='x-grid'>{fee_html}</table>"
            "</td><td width='4%'></td><td valign='top'><h2>Risk</h2><table class='x-grid num'><tr><th class='l'>Measure"
            f"</th><th>Value</th><th class='l'>Source</th></tr>{risk_html}</table></td></tr></table>")


def material_issues(data: dict) -> str:
    """ Insufficient evidence apart from performance concerns, then data issues in full (never shortened) """
    quality = evidence_quality(data)
    gaps, concerns = issue_groups(data["facts"], data["reasons"])
    body = ""
    if concerns:
        body += "<p class='x-group'>Performance concerns</p>" + _ul(concerns)
    if gaps:
        body += "<p class='x-group'>Not enough evidence to judge</p>" + _ul(gaps)
    data_items = [f"Data check: {m}" for m in quality.blocking]
    data_items += [f"Warning: {m}" for m in quality.warnings[:MAX_WARNINGS]]
    more = len(quality.warnings) - MAX_WARNINGS
    if more > 0:
        data_items.append(f"… and {more} more data warning{'s' if more != 1 else ''}, listed in full in the Detailed "
                          "Report (Appendix D).")
    if quality.ai_read:
        data_items.append("Figures were read from the documents by AI: check them against the factsheet.")
    if data_items:
        body += "<p class='x-group'>Data issues (evidence quality)</p>" + _ul(data_items)
    return body or "<p>No performance concerns, no gaps in the evidence and no data issues.</p>"


def page2(inp, content: ExecutiveContent) -> str:
    data = content.data
    facts = data["facts"]
    questions = facts.get("manager_questions", [])[:MAX_QUESTIONS]
    ticks = "".join(f"<td class='x-box-tick'>&nbsp;</td><td>{n}</td>" for n in ("Satisfied", "Monitor", "Action needed"))
    manual = "".join(f"<tr><td class='x-box-tick'>&nbsp;</td><td>Manual check done: {escape(m.name)}: "
                     f"{escape(m.reason)}</td></tr>" for m in inp.card.manual_checks)
    return f"""
<h1>{PAGE2}</h1>
<h2>Benchmark and peers</h2>{_comparison(inp, facts)}
{_fees_and_risk(inp, facts)}
<h2>Material issues</h2>{material_issues(data)}
<h2>Recommended actions</h2>{_ul(data.get('actions', [])) or '<p>None.</p>'}
{'<h2>Questions for the manager</h2>' + _ul(questions) if questions else ''}
<h2>Analyst approval</h2>
<table class="x-approval">
<tr><td width="20%">Reviewer name</td><td class="x-line">&nbsp;</td><td width="8%">Date</td><td class="x-line" width="22%">&nbsp;</td></tr>
<tr><td>Decision</td><td colspan="3"><table class="x-ticks"><tr>{ticks}</tr></table></td></tr>
<tr><td>Analyst's comments</td><td class="x-line" colspan="3">&nbsp;</td></tr>
<tr><td colspan="4">If you disagree with the suggested assessment, why?</td></tr>
<tr><td>&nbsp;</td><td class="x-line" colspan="3">&nbsp;</td></tr>
<tr><td>Signature</td><td class="x-line" colspan="3">&nbsp;</td></tr>
</table>
{f'<table class="x-ticks">{manual}</table>' if manual else ''}
<p class="x-src">Draft for oversight review from public data, prepared with AI assistance; every figure and rating comes
from code. Not investment advice. Full tables, sources, data checks and audit evidence: the Detailed Report.</p>
"""


EXEC_CSS = f"""
.x-banner td {{ background-color: {NAVY}; color: white; padding: 7px 10px; }}
.x-kicker {{ font-size: 6.8pt; color: #b9cbe0; }} .x-fund {{ font-size: 14pt; font-weight: bold; }}
.x-meta {{ font-size: 7.6pt; color: #dce6f1; }}
.x-status td.x-box, .x-metrics td.x-metric {{ border: 0.6px solid #dde3ea; padding: 6px 8px; vertical-align: top;
  background-color: #ffffff; font-size: 7.6pt; }}
.x-label {{ font-size: 6.6pt; color: #5b6878; }}
.x-big {{ font-size: 12.5pt; font-weight: bold; }}
.x-metrics {{ margin-top: 6px; }}
.x-value {{ font-size: 14pt; font-weight: bold; color: {NAVY}; }} .x-na {{ font-size: 10pt; color: #5b6878; }}
.x-src {{ font-size: 6.8pt; color: #5b6878; }}
.x-list li {{ margin-bottom: 1px; }}
.x-group {{ font-weight: bold; color: {NAVY}; margin-top: 3px; }}
.x-grid th {{ background-color: #eef3fa; color: {NAVY}; padding: 2px 4px; font-size: 7.4pt; text-align: center; }}
.x-grid td {{ padding: 2px 4px 1px 4px; border-bottom: 0.5px solid #dde3ea; vertical-align: top; }}
.x-grid.num td, .x-grid.num th {{ text-align: right; }} .x-grid td.l, .x-grid th.l {{ text-align: left; }}
.x-total td {{ font-weight: bold; background-color: #f6f8fb; }}
.x-chip {{ color: white; font-weight: bold; text-align: center; vertical-align: middle; font-size: 7.4pt; }}
.x-q {{ width: 24%; }}
.x-approval td {{ padding: 5px 4px 2px 4px; }} .x-line {{ border-bottom: 0.8px solid #1d2733; }}
.x-ticks td {{ padding: 2px 4px; }} .x-box-tick {{ border: 0.8px solid #1d2733; width: 10px; }}
"""


def executive_html(inp, out_dir: Path) -> tuple[str, str]:
    """ The two pages' HTML (page 1, page 2) """
    content = content_from(inp, out_dir)
    return page1(inp, content), page2(inp, content)


def build_executive(inp, out_dir: Path, name: str = "report_executive.pdf") -> Path:
    """ Exactly two pages, or ReportLayoutError: content is never dropped to make it fit """
    from fund_performance.report import CSS, ReportLayoutError, _render, page_texts
    out_dir.mkdir(parents=True, exist_ok=True)
    p1, p2 = executive_html(inp, out_dir)
    footer = (f'<div id="footer">{escape(inp.profile.fund_name)} · Executive Report (draft) · figures to '
              f'{inp.profile.as_of_date:%d %b %Y} · Public data only · Page <pdf:pagenumber> of <pdf:pagecount></div>')
    html = (f"<html><head><meta charset='utf-8'/><style>{CSS}{EXEC_CSS}</style></head><body>{footer}{p1}"
            f"<div style='page-break-before: always'></div>{p2}</body></html>")
    path = out_dir / name
    _render(html, path)
    problems = executive_layout_problems(page_texts(path))
    if problems:
        raise ReportLayoutError("Executive Report: " + "; ".join(problems))
    return path


def executive_layout_problems(texts: list[str], next_title: str | None = None) -> list[str]:
    """ Page 1 holds "Overview" and page 2 starts with "Comparisons and decision"; nothing spills over. On its own
    the report has exactly two pages; inside the Detailed Report, page 3 must start with `next_title` """
    problems = []
    if not texts or PAGE1 not in texts[0]:
        problems.append("page 1 is missing")
    elif len(texts) < 2 or PAGE2 not in texts[1]:
        problems.append("page 1 runs over onto page 2; its content cannot be shortened without losing information")
    elif next_title is None and len(texts) > 2:
        problems.append(f"{len(texts)} pages: page 2 runs over; its content cannot be shortened without losing "
                        "information")
    elif next_title is not None and (len(texts) < 3 or next_title not in texts[2]):
        problems.append("page 2 runs over onto page 3; its content cannot be shortened without losing information")
    return problems
