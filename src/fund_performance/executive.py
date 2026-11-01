""" The Executive Report (UX redesign, stage 3): two A4 pages for a decision (a target, not a limit)

Page 1 "Overview": fund and period, the suggested investment assessment and the evidence quality (kept apart), three
headline figures, the summary, two or three key findings, one chart chosen for the fund's mandate and data, and the
four ratings. Page 2 "Comparisons and decision": benchmark and peers, fees, selected risk measures, material issues
(insufficient evidence apart from performance concerns, then data issues), recommended actions, up to three questions
for the manager, and the analyst's approval.

Presentation only, from the same facts and shared helpers as the dashboard (presentation.py). Material warnings are
shown in full, never shortened; when there are more data warnings than fit, the page says how many more and where
they are (the Detailed Report's Appendix D). If page 1 or page 2 still runs over, the report is not cut and not
rejected (Version 1): it runs to three or more pages, with an info note. Only a broken structure is an error.
"""
from dataclasses import dataclass
from html import escape
from pathlib import Path
from fund_performance import charts
from fund_performance.plain import verdict_meaning, verdict_name
import re
from fund_performance.presentation import (CHART_LEFT_OUT, UNRELIABLE, comparison_invalid,
                                           NAVY, NOT_AVAILABLE, RATING_STYLE, VERDICT_STYLE, _figures,
                                           _shown, _source, assessment_caveat, chart_choice, comparison_problems,
                                           evidence_quality, flag_dicts, conclusion_origin, headline_metrics, summary_parts, executive_commentary,
                                           issue_groups, merge_same_ending, missing_evidence, point_to_data_issues,
                                           report_action, assessment_meaning, signoff_checks,
                                           risk_measures)

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
    chart_left_out: bool = False     # True: a data check makes the fund-vs-index chart misleading, so it is replaced


def content_from(inp, out_dir: Path) -> ExecutiveContent:
    """ The run's data in the dashboard's shape, plus the chart picked for this fund """
    facts = inp.facts
    out = inp.narrative.output if inp.narrative else None
    from fund_performance.report import plain_reason
    data = {"facts": facts, "reasons": {name: plain_reason(inp, name) for name in inp.card.pillars},
            "findings": list(out.key_findings) if out else [], "actions": list(out.action_texts) if out else [],
            "flags": flag_dicts(inp.flags)}
    if comparison_problems(inp.flags):
        return ExecutiveContent(data, None, CHART_LEFT_OUT, True)
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
        series = "market-close price (PNAV)" if ev.get("series") == "fund_pnav" else "price (NAV)"
        if kind == "yearly_gap":
            pi, ocf = inp.thresholds.performance_index, inp.profile.ocf_pct
            if ocf is None:
                path = charts.yearly_gap_chart(years, gaps, out_dir / "exec_chart.png",
                                               f"Yearly gap to the index, {years[0]}–{years[-1]}")
                return path, "Fund minus index, each calendar year (pp). Fee-dependent limits are unavailable."
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
        n = (facts.get("fund", {}).get("time_horizon_years") or facts.get("fund", {}).get("analysis_period_years", 5))
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
    n = p.analysis_period_years
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
            f"<br/>{escape(assessment_meaning(code, quality, verdict_meaning(code)))}. From fixed rules on the four "
            "ratings; the analyst decides."
            f"{('<br/><b>' + escape(caveat) + '</b>') if caveat else ''}</td><td width='2%'></td>"
            f"<td width='48%' class='x-box' style='border-left: 4px solid {q_colour}'><span class='x-label'>EVIDENCE "
            f"QUALITY (DATA CHECKS)</span><br/><span class='x-big' style='color:{q_colour}'>{escape(quality.label)}</span>"
            f"<br/>{escape(quality.detail)}.</td></tr></table>")


def _metrics(facts: dict) -> str:
    cells = "".join(
        f"<td width='33%' class='x-metric'><span class='x-label'>{escape(m.label.upper())}</span><br/>"
        f"<span class='x-value{' x-na' if m.value in (NOT_AVAILABLE, UNRELIABLE) else ''}'>{escape(m.value)}</span><br/>"
        f"{escape(m.period)}{('<br/>' + escape(m.note)) if m.note else ''}<br/><span class='x-src'>Source: "
        f"{escape(m.source)}</span></td>" for m in headline_metrics(facts))
    return f"<table class='x-metrics'><tr>{cells}</tr></table>"


def key_findings(data: dict) -> list[str]:
    """ Two or three findings that add to the ratings table rather than repeat it: the data-note findings, then the
    first points for judgement (not the standing note about illustrative limits) """
    found = list(data.get("findings", [])[1:])
    # Data issues are shown in full on page 2, so the points that repeat them (shortened) are not findings here
    points = [p for p in data["facts"].get("judgement_points", [])
              if not p.startswith(("The limits used", "Resolve this data check first", "Data warning:"))]
    for p in points:
        if len(found) >= MAX_FINDINGS:
            break
        found.append(p)
    return found[:MAX_FINDINGS]


def _scorecard(data: dict) -> str:
    missing = missing_evidence(data["facts"])
    rows = ""
    for p in data["facts"]["scorecard"]["pillars"]:
        if p["rating"] == "CHECK DATA" and p["name"] in missing:
            why = f"Not rated: {missing[p['name']]}."
        elif p["rating"] == "CHECK DATA":
            why = "Not rated yet: the data check on page 2 must be resolved first."
        else:
            why = data["reasons"].get(p["name"]) or p["reason"]
        rows += (f"<tr><td class='x-q'><b>{escape(p['name'])}</b><br/><span class='x-src'>"
                 f"{escape(SHORT_QUESTIONS.get(p['name'], ''))}</span></td>{_chip(p['rating'])}<td>{escape(why)}</td></tr>")
    return ("<table class='x-grid'><tr><th width='24%' class='l'>Question</th><th width='12%'>Rating</th>"
            f"<th class='l'>Why</th></tr>{rows}</table>")


def _summary_html(concl: dict) -> str:
    """ The Executive commentary (AI, checked by code); else the dashboard answer and its evidence; else code's
    conclusion as one paragraph """
    paragraphs = executive_commentary(concl)
    if paragraphs:
        return "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    parts = summary_parts(concl)
    if not parts:
        return f"<p>{escape(concl.get('text', ''))}</p>"
    answer, evidence = parts
    return (f"<p><b>Answer.</b> {escape(answer)}</p>"
            + (f"<p><b>Supporting evidence</b></p>{_ul(evidence)}" if evidence else ""))


def long_commentary(facts: dict) -> bool:
    concl = facts.get("suggested_conclusion") or {}
    return len(" ".join(executive_commentary(concl)) or concl.get("text", "")) > 700


def page1(inp, content: ExecutiveContent) -> str:
    data = content.data
    concl = data["facts"].get("suggested_conclusion") or {}
    findings = key_findings(data)
    import base64
    if content.chart:
        chart = (f"<img src='data:image/png;base64,{base64.b64encode(content.chart.read_bytes()).decode()}' width='330'/>"
                 f"<p class='x-src'>{escape(content.chart_caption)}</p>")
    elif content.chart_left_out:
        chart = (f"<table class='x-callout'><tr><td><b>Chart left out: the comparison with the index is not reliable"
                 f"</b><br/>{escape(content.chart_caption)}</td></tr></table>")
    else:
        chart = f"<p class='x-src'>{escape(content.chart_caption)}</p>"
    heading = 'Oversight commentary' if executive_commentary(concl) else 'Summary'
    summary = (f"<h2>{heading}</h2>{_summary_html(concl)}<p class='x-src'>"
               f"{escape(conclusion_origin(concl))}; a draft for the analyst.</p>")
    findings_html = '<h2>Key findings</h2>' + _ul(findings) if findings else ''
    # xhtml2pdf cannot split a table row. Long commentary in the side-by-side row moves the whole row to
    # the next page, leaving page one mostly empty. Render long commentary as normal flowing paragraphs.
    long_summary = long_commentary(data["facts"])
    if long_summary:
        chart = chart.replace("width='330'", "width='240'")
        narrative = summary + findings_html + f"<div align='center'>{chart}</div>"
    else:
        narrative = (f"<table width='100%'><tr><td width='52%' valign='top'>{summary}{findings_html}</td>"
                     f"<td width='3%'></td><td valign='top' align='center'>{chart}</td></tr></table>")
    return f"""
{_banner(inp)}
<h1>{PAGE1}</h1>
{_statuses(data)}
{_metrics(data['facts'])}
{narrative}
<h2>The four ratings</h2>{_scorecard(data)}
"""


def _comparison(inp, facts: dict) -> str:
    figs = _figures(facts)
    n = (facts.get("fund", {}).get("time_horizon_years") or facts.get("fund", {}).get("analysis_period_years", 5))
    basis = (figs.get(f"comparison.td.{n}y") or {}).get("basis") or "fund_nav"
    fund_label = "This fund, market-close price (PNAV)" if basis == "fund_pnav" else "This fund (NAV)"

    def row(label, cells, fee, used, bold=False):
        cls = " class='x-total'" if bold else ""
        return (f"<tr{cls}><td class='l'>{escape(label)}</td>" + "".join(f"<td>{escape(c)}</td>" for c in cells)
                + f"<td>{escape(fee)}</td><td class='l x-src'>{escape(used)}</td></tr>")
    def ann(s):
        return [f"{figs[name]['value']:.2f}%".replace("-", "−") if (name := f"{s}.{kind}.{k}y") in figs else "–"
                for kind, k in (("cum", 1), ("ann", 3), ("ann", 5))]
    fee = f"{inp.profile.ocf_pct:.2f}%" if inp.profile.ocf_pct is not None else "Not available"
    rows = row(fund_label, ann(basis), fee, _source(*(figs.get(f"{basis}.ann.{k}y") for k in (3, 5))), True)
    peer_series = {"fund_pnav" if "PNAV" in p.get("basis", "") else "fund_nav"
                   for p in facts.get("peers", []) if p.get("used_for_returns")}
    for other in sorted(peer_series - {basis}):          # the peers were compared with the other fund series
        words = "noon price (NAV)" if other == "fund_nav" else "market-close price (PNAV)"
        rows += row(f"This fund, {words}: compared with peers", ann(other), fee,
                    _source(*(figs.get(f"{other}.ann.{k}y") for k in (3, 5))), True)
    invalid = comparison_invalid(facts)
    rows += (row("Index or benchmark", ["–"] * 3, "–", f"{UNRELIABLE}: data check") if invalid else
             row("Index or benchmark", ann("index"), "–", _source(*(figs.get(f"index.ann.{k}y") for k in (3, 5)))))
    for p in facts.get("peers", []):
        r = p.get("returns_pct_a_year", {})
        cells = ["–" if r.get(k) is None else f"{r[k]:.2f}%".replace("-", "−") for k in ("1y", "3y", "5y")]
        used = (f"Peer, fees and returns ({p['basis']})" if p.get("used_for_returns")
                else f"Peer, fees only: {p.get('excluded')}")
        rows += row(p["name"], cells, f"{p['ocf_pct']:.2f}%", used)
    gap = figs.get(f"comparison.td.{n}y")
    note = (f"Gap to the index over {n} years: {_shown(gap)} a year (tracking difference; calculated from the "
            "factsheet). Returns a year; 1 year is the 1-year return. Two decimal places aid comparison; source "
            "figures may be rounded, and differences can vary by 0.01 pp after rounding." if gap else
            "Returns a year; 1 year is the 1-year return. Source figures may be rounded.")
    if invalid:
        note = ("Index figures and the gap to the index are not reliable until the data check is resolved (see the "
                "data issues); the Detailed Report keeps them, marked. Returns a year; 1 year is the 1-year return.")
    if not facts.get("peers"):
        note += " No comparable peer was supplied or approved for this benchmark."
    peer_notes = [_peer_note(p) for p in facts.get("peers", [])]
    return ("<table class='x-grid num'><tr><th class='l' width='34%'>Fund</th><th>1 year</th><th>3 years</th>"
            f"<th>5 years</th><th>Fee</th><th class='l' width='25%'>Source / use</th></tr>{rows}</table>"
            f"<p class='x-src'>{escape(note)}</p>" + _ul(n for n in peer_notes if n))


def _peer_note(peer: dict) -> str:
    """ What a reader needs to judge a peer: share class, currency, minimum investment, pricing basis, and the
    peer checks' notes (e.g. an institutional class) """
    share_class = peer.get("share_class")
    facts = [x for x in (None if share_class and share_class in peer["name"] else share_class,
                         peer.get("distribution"), peer.get("currency")) if x]
    parts = [", ".join(facts)] if facts else []
    if peer.get("minimum_investment"):
        parts.append(f"minimum investment {peer['minimum_investment']}")
    if peer.get("basis"):
        parts.append(f"pricing: {peer['basis']}")
    parts += [n for n in peer.get("notes", []) if n]
    return f"{peer['name']}: " + "; ".join(parts) + "." if parts else ""


def _fees_and_risk(inp, facts: dict) -> str:
    p = inp.profile
    value, fees = inp.card.pillars["Value for investors"].values, inp.card.pillars["Fees"].values
    fee_rows = [("Ongoing charge (OCF)", f"{p.ocf_pct:.2f}% a year" if p.ocf_pct is not None else "Not available"),
                ("Transaction costs", "Not disclosed in the documents provided" if p.transaction_cost_pct is None
                 else f"{p.transaction_cost_pct:.2f}%"),
                ("Performance fee", "Yes" if p.performance_fee else "None" if p.performance_fee is False
                 else "Not established in the documents (missing evidence)")]
    if fees.get("peer_ocf") is not None:
        each = fees.get("peer_fees", [])
        fee_rows.append(("Peer's fee" if len(each) <= 1 else "Peers' average fee", f"{fees['peer_ocf']:.2f}% a year"
                         + (f" ({'; '.join(f'{x:.2f}%' for x in each)})" if len(each) > 1 else "")))
    if value.get("gap_pp") is not None:
        fee_rows.append((f"Peer return gap, {value['years']} years", f"{value['gap_pp']:+.2f} pp a year".replace("-", "−")))
    fee_html = "".join(f"<tr><td class='l'>{escape(a)}</td><td class='l'>{escape(b)}</td></tr>" for a, b in fee_rows)
    risk = risk_measures(facts)[:6]
    risk_html = "".join(f"<tr><td class='l' width='58%'>{escape(a)}</td><td>{escape(b)}</td><td class='l x-src'>{escape(c)}</td></tr>"
                        for a, b, c in risk) or "<tr><td class='l' colspan='3'>No risk figures in the documents.</td></tr>"
    return (f"<table width='100%'><tr><td width='45%' valign='top'><h2>Fees</h2><table class='x-grid'>{fee_html}</table>"
            "</td><td width='3%'></td><td valign='top' width='52%'><h2>Risk</h2><table class='x-grid num'><tr><th class='l'>Measure"
            f"</th><th>Value</th><th class='l'>Source</th></tr>{risk_html}</table></td></tr></table>")


def material_issues(data: dict) -> str:
    """ Insufficient evidence apart from performance concerns, then data issues in full (never shortened) """
    quality = evidence_quality(data)
    gaps, concerns = issue_groups(data["facts"], data["reasons"])
    gaps = merge_same_ending(gaps, ": not rated until the data check is resolved (see the data issues)")
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
    if data_items:
        body += "<p class='x-group'>Data issues (evidence quality)</p>" + _ul(data_items)
    if quality.ai_read:
        body += "<p class='x-group'>Evidence note</p>" + _ul(["AI-extracted figures require verification against the documents."])
    return body or "<p>No performance concerns, no gaps in the evidence and no data issues.</p>"


RESOLVE = re.compile(r"^Resolve the data check on (.+?) (before signing off this review \(see the data issues\)\.)$")


def merge_resolve_actions(actions: list[str]) -> list[str]:
    """ "Resolve the data check on Mandate ..." and "... on Performance ..." -> one action naming both """
    matched = [(a, RESOLVE.match(a)) for a in actions]
    names = [m.group(1) for _, m in matched if m]
    if len(names) < 2:
        return actions
    tail = next(m.group(2) for _, m in matched if m)
    merged = f"Resolve the data check on {', '.join(names[:-1])} and {names[-1]} {tail}"
    out = []
    for a, m in matched:
        if not m:
            out.append(a)
        elif merged not in out:
            out.append(merged)
    return out


def page2(inp, content: ExecutiveContent) -> str:
    data = content.data
    facts = data["facts"]
    questions = facts.get("manager_questions", [])[:MAX_QUESTIONS]
    blocking = evidence_quality(data).blocking
    actions = merge_resolve_actions([report_action(point_to_data_issues(a, blocking)) for a in data.get("actions", [])])
    if checks := signoff_checks(facts):
        actions.insert(0, checks)
    suggested = verdict_name(facts["scorecard"]["verdict"])
    # Tick boxes as characters in one cell: a nested table of 12px box cells could be squeezed below its padding
    # when the box crosses a page break, and ReportLab then stops the whole report (Stage 6C Live run)
    ticks = "&nbsp;&nbsp;&nbsp;&nbsp;".join(f"<span class='x-box'>☐</span>&nbsp;{n}" for n in ("Satisfied", "Monitor",
                                                                                            "Action needed"))
    manual = "".join(f"<tr><td></td><td colspan='3'><span class='x-box'>☐</span>&nbsp;Manual check done: "
                     f"{escape(m.name)}: {escape(m.reason)}</td></tr>" for m in inp.card.manual_checks)
    return f"""
<h1>{PAGE2}</h1>
<h2>Benchmark and peers</h2>{_comparison(inp, facts)}
{_fees_and_risk(inp, facts)}
{_market_context(inp)}<h2>Material issues</h2>{material_issues(data)}
<h2>Recommended actions</h2>{_ul(actions) or '<p>None.</p>'}
{'<h2>Questions for the manager</h2>' + _ul(questions) if questions else ''}
<h2>Analyst sign-off</h2>
<table class="x-approval">
<tr><td colspan="4" class="x-signoff-lead">Suggested assessment: <b>{escape(suggested)}</b>. The analyst decides; tick one.</td></tr>
<tr><td width="22%" class="x-tick-head">Decision</td><td colspan="3" class="x-tick-row">{ticks}</td></tr>
{manual}
<tr><td>Analyst's comments</td><td class="x-line" colspan="3">&nbsp;</td></tr>
<tr><td>&nbsp;</td><td class="x-line" colspan="3">&nbsp;</td></tr>
<tr><td colspan="2">If you disagree with the suggested assessment, why?</td><td class="x-line" colspan="2">&nbsp;</td></tr>
<tr><td>Reviewer name</td><td class="x-line" width="38%">&nbsp;</td><td width="10%" class="x-right">Date</td><td class="x-line">&nbsp;</td></tr>
<tr><td>Signature</td><td class="x-line" colspan="3">&nbsp;</td></tr>
</table>
<p class="x-src x-after">Draft for oversight review from public data, prepared with AI assistance; every figure and rating comes
from code. Not investment advice. Full tables, sources, data checks and audit evidence: the Detailed Report.</p>
"""


EXEC_CSS = f"""
.x-banner td {{ background-color: {NAVY}; color: white; padding: 7px 10px; }}
.x-kicker {{ font-size: 7.4pt; color: #b9cbe0; }} .x-fund {{ font-size: 16pt; font-weight: bold; }}
.x-meta {{ font-size: 8.4pt; color: #dce6f1; }}
.x-status td.x-box, .x-metrics td.x-metric {{ border: 0.6px solid #dde3ea; padding: 6px 8px; vertical-align: top;
  background-color: #ffffff; font-size: 8.4pt; }}
.x-label {{ font-size: 7.2pt; color: #5b6878; }}
.x-big {{ font-size: 14pt; font-weight: bold; }}
.x-metrics {{ margin-top: 7px; }}
.x-value {{ font-size: 15pt; font-weight: bold; color: {NAVY}; }} .x-na {{ font-size: 11pt; color: #5b6878; }}
.x-src {{ font-size: 7.4pt; color: #5b6878; }}
.x-list li {{ margin-bottom: 2px; }}
.x-group {{ font-weight: bold; color: {NAVY}; margin-top: 3px; }}
.x-grid th {{ background-color: #eef3fa; color: {NAVY}; padding: 3px 4px; font-size: 8pt; text-align: center; }}
.x-grid td {{ padding: 3px 4px 2px 4px; border-bottom: 0.5px solid #dde3ea; vertical-align: top; }}
.x-grid.num td, .x-grid.num th {{ text-align: right; }} .x-grid td.l, .x-grid th.l {{ text-align: left; }}
.x-total td {{ font-weight: bold; background-color: #f6f8fb; }}
.x-chip {{ color: white; font-weight: bold; text-align: center; vertical-align: middle; font-size: 8.4pt; }}
.x-q {{ width: 24%; }}
.x-callout td {{ text-align: left; background-color: #f3eefa; border-left: 4px solid #6d4c9f; padding: 8px 10px; font-size: 8.8pt; }}
.x-approval {{ background-color: #f6f8fb; }}
.x-signoff-lead {{ font-size: 9pt; }}
.x-approval td {{ padding: 8px 4px 1px 4px; }} .x-line {{ border-bottom: 0.8px solid #1d2733; }}
.x-right {{ text-align: right; }} .x-after {{ margin-top: 8px; }}
.x-box {{ font-size: 12pt; }} .x-tick-row {{ font-size: 9pt; }}
.x-tick-head {{ font-weight: bold; color: {NAVY}; width: 22%; }}
"""


def _market_context(inp) -> str:
    """ The Reporting Agent's market context, checked by code and the Judge, with its sources in the Detailed Report;
    nothing when there is none (offline, research off or no credible source) """
    context = inp.narrative.output.market_context if inp.narrative else None
    if not context:
        return ""
    return (f"<h2>Market context</h2><p>{escape(context)}</p><p class='small'>Written by AI from the cited web "
            "sources [n] (listed with dates in the Detailed Report, Appendix D). It never changes a figure or rating.</p>")


def executive_html(inp, out_dir: Path) -> tuple[str, str]:
    """ The two pages' HTML (page 1, page 2) """
    content = content_from(inp, out_dir)
    return page1(inp, content), page2(inp, content)


def build_executive(inp, out_dir: Path, name: str = "report_executive.pdf") -> Path:
    """ Two pages as a target; more when the content needs them (nothing is cut). ReportLayoutError only if the
    report's structure is broken (no "Overview" on page 1, or no "Comparisons and decision" page) """
    from fund_performance.report import CSS, ReportLayoutError, _render, page_texts
    out_dir.mkdir(parents=True, exist_ok=True)
    p1, p2 = executive_html(inp, out_dir)
    footer = (f'<div id="footer">{escape(inp.profile.fund_name)} · Executive Report (draft) · figures to '
              f'{inp.profile.as_of_date:%d %b %Y} · Public data only · Page <pdf:pagenumber> of <pdf:pagecount></div>')
    separator = "" if long_commentary(inp.facts) else "<div style='page-break-before: always'></div>"
    html = (f"<html><head><meta charset='utf-8'/><style>{CSS}{EXEC_CSS}</style></head><body>{footer}{p1}"
            f"{separator}{p2}</body></html>")
    path = out_dir / name
    _render(html, path)
    problems = executive_structure_problems(page_texts(path))
    if problems:
        raise ReportLayoutError("Executive Report: " + "; ".join(problems))
    return path


def executive_pages_note(path: Path):
    """ An info flag when the Executive Report runs past its two-page target, else None """
    from fund_performance.models import DataFlag
    from fund_performance.report import page_texts
    pages = len(page_texts(path))
    if pages <= 2:
        return None
    return DataFlag(check="report_layout", level="info", message=(
        f"Executive Report: {pages} pages (target 2), so that no material information is cut"))


def build_executive_reliably(inp, out_dir: Path, name: str = "report_executive.pdf"):
    """ (path, info flag or None): the Executive Report, with a note if it runs past two pages """
    path = build_executive(inp, out_dir, name)
    return path, executive_pages_note(path)


def executive_structure_problems(texts: list[str]) -> list[str]:
    """ The overview comes first, followed by the comparisons and decision section. """
    if not texts or PAGE1 not in texts[0]:
        return ["page 1 is missing"]
    if not any(PAGE2 in t for t in texts) or (PAGE2 in texts[0] and texts[0].index(PAGE2) < texts[0].index(PAGE1)):
        return ["the 'Comparisons and decision' page is missing"]
    return []


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
