""" The results dashboard on the web page (UX redesign, stage 2): presentation only

Built from what the run already decided: the facts JSON (figures with their sources, ratings, reasons, verdict,
data notes, peers, statistics, code-written conclusion, points and questions), the one-line reasons, the narrative
(findings, actions, market context) and every flag of the run. Nothing here calculates a figure or sets a rating:
a figure the facts do not hold is shown as "Not available", never as zero.

Two things are kept apart on purpose:
- the investment assessment: the suggested verdict and the four ratings (code's rules), and
- the evidence quality: whether the data behind them raised blocking checks or warnings (code's data checks and
  flags). A suggested "Satisfied" is never shown as approved: it is a suggestion, and while data issues remain it
  says so next to it.

The audience changes only how much is shown: the Investment Analyst view opens the detail; the Management view
leads with the summary and the decisions. Both show the same facts and ratings.
"""
import base64
import math
import re
from html import escape
from urllib.parse import urlparse
from fund_performance.plain import verdict_meaning, verdict_name
from fund_performance.presentation import (NAVY, NOT_AVAILABLE, QUESTIONS, RATING_STYLE,  # noqa: F401
                                           VERDICT_STYLE, EvidenceQuality, _date, _figures, _shown, _source,
                                           assessment_caveat, evidence_quality, flag_dicts, headline_metrics,
                                           conclusion_origin, issue_groups, summary_parts, next_step, risk_measures, UNRELIABLE,
                                           UNRELIABLE_SOURCE, UNRELIABLE_WHY, assessment_meaning, comparison_invalid,
                                           report_action, rating_explanation)
from fund_performance.report import ANGLE_WORDS, JUDGE_WORDS, REPORT_TYPE_WORDS, plain_note

AUDIENCES = ("analyst", "management")


# --- What the page keeps from a run ----------------------------------------------------------------------------

def dashboard_data(result) -> dict:
    """ A plain dict of the finished run (kept in the page's state, so switching audience needs no new run) """
    narrative = getattr(result, "narrative", None)
    output = narrative.output if narrative else None
    log = getattr(result, "log", None)
    flags = flag_dicts(getattr(result, "flags", []))
    source_reader = getattr(log, "report_sources", None)
    sources = source_reader()[1] if callable(source_reader) else (list(narrative.sources) if narrative else [])
    chart = None
    primary_chart = None
    shared = getattr(result, 'presentation_context', None) or {}
    primary_status = shared.get('performance_chart') or {}
    chart_path = getattr(result, "run_dir", None)
    if chart_path and not comparison_invalid(result.facts or {}):
        try:
            image = (chart_path / "exec_chart.png").read_bytes()
            chart = base64.b64encode(image).decode("ascii")
        except OSError:
            pass
        if primary_status.get('available'):
            try:
                primary_chart = base64.b64encode((chart_path / 'dashboard_growth.png').read_bytes()).decode('ascii')
            except OSError:
                primary_status = {'available': False, 'reason': 'The prepared chart image is unavailable.'}
    return {"facts": result.facts or {}, "reasons": dict(getattr(result, "reasons", {}) or {}),
            "findings": list(output.key_findings) if output else [],
            "actions": list(output.action_texts) if output else [],
            "market_context": output.market_context if output else None,
            "sources": sources, "performance_chart": chart, "primary_chart": primary_chart,
            "primary_chart_status": primary_status, "presentation_context": shared,
            "flags": flags or [dict(f) for f in (result.facts or {}).get("data_flags", [])],
            "offline": bool(log.run.get("offline")) if log is not None else False}



# --- HTML pieces -------------------------------------------------------------------------------------------------

def _chip(rating: str) -> str:
    word, colour = RATING_STYLE.get(rating, (rating.title(), "#546e7a"))
    return f"<span class='fp-chip' style='background:{colour}'>{escape(word)}</span>"


def _list(items, cls: str = "") -> str:
    items = [i for i in items if i]
    return f"<ul class='{cls}'>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>" if items else ""


def _details(title: str, body: str, open_: bool = False, cls: str = "") -> str:
    if not body:
        return ""
    return (f"<details class='fp-details {cls}'{' open' if open_ else ''}><summary>{escape(title)}</summary>"
            f"<div class='fp-details-body'>{body}</div></details>")


def _header(data: dict, quality: EvidenceQuality, institutional: bool = False) -> str:
    facts = data["facts"]
    fund, card = facts.get("fund", {}), facts.get("scorecard", {})
    code = card.get("verdict", "")
    colour = next((c for k, c in VERDICT_STYLE.items() if code.startswith(k)), NAVY)
    n = (fund.get("time_horizon_years") or fund.get("analysis_period_years", 5))
    caveat = assessment_caveat(quality)
    q_colour = {"check": "#6d4c9f", "warnings": "#b7791f", "clear": "#4c5966"}[quality.level]
    offline = " · Run without AI (offline)" if data.get("offline") else ""
    demo = data.get("demo")
    banner = (f"<div class='fp-demo-banner'><b>{escape(demo['label'])}: {escape(demo['fund'])}.</b> "
              f"{escape(demo['evidence'])} <span class='fp-muted'>{escape(demo['notice'])}</span></div>" if demo else "")
    return f"""{banner}
<div class='fp-result-head'>
  <div class='fp-fund'><h2>{escape(fund.get('fund_name', 'Fund'))}</h2>
    <p>ISIN {escape(fund.get('isin', '–'))} · {escape(fund.get('share_class', ''))} · {escape(fund.get('currency', '–'))} · Benchmark:
    {escape(fund.get('benchmark_name', '–'))}</p>
    <p>Reporting period: {n} years to {escape(_date(fund.get('as_of_date')))}{offline}</p></div>
  <div class='fp-status-row'>
    <div class='fp-status fp-assessment' style='border-left-color:{colour}'>
      <div class='fp-kicker'>{'Deterministic scorecard' if institutional else 'Investment assessment (suggested)'}</div>
      <div class='fp-status-main' style='color:{colour}'>{escape(code if institutional else verdict_name(code))}</div>
      <div class='fp-status-sub'>{escape(assessment_meaning(code, quality, verdict_meaning(code)))}. From fixed rules on the four ratings; the analyst
      decides and signs.{(' <b>' + escape(caveat) + '</b>') if caveat else ''}</div></div>
    <div class='fp-status fp-quality' style='border-left-color:{q_colour}'>
      <div class='fp-kicker'>Evidence quality (data checks)</div>
      <div class='fp-status-main' style='color:{q_colour}'>{escape(quality.label)}</div>
      <div class='fp-status-sub'>{escape(quality.detail)}.</div></div>
  </div>
</div>"""


def _summary(data: dict, quality: EvidenceQuality, title: str = "Summary", concise: bool = False) -> str:
    """ The analyst's answer: Answer, Supporting evidence and Recommended next step. The verdict and ratings are shown
    in their own sections; data-quality items are listed once, in a collapsible section """
    facts = data["facts"]
    concl = facts.get("suggested_conclusion") or {}
    who = conclusion_origin(concl)
    parts = summary_parts(concl)
    if parts:
        answer, evidence = parts
        shown = evidence[:3] if concise else evidence
        body = (f"<p class='fp-concern-title'>Answer</p><p class='fp-conclusion'>{escape(answer)}</p>"
                + (f"<p class='fp-concern-title'>{'Key findings' if concise else 'Supporting evidence'}</p>"
                   + _list(shown, "fp-evidence") if shown else ""))
        if concise and len(evidence) > 3:
            body += _details("Full supporting evidence", _list(evidence))
    else:
        answer = concl.get('text') or 'The answer is unavailable; review the scorecard and evidence below.'
        body = f"<p class='fp-concern-title'>Answer</p><p class='fp-conclusion'>{escape(answer)}</p>"
    check = next_step(facts)
    step = concl.get("next_step") or check
    if step:
        body += f"<p class='fp-concern-title'>Recommended next step</p><p>{escape(step)}</p>"
    if check and step != check:
        body += f"<p class='fp-concern-title'>Sign-off check</p><p>{escape(check)}</p>"
    gaps, concerns = issue_groups(facts, data["reasons"])
    details = ""
    if concerns:
        details += "<p class='fp-concern-title'>Performance concerns</p>" + _list(concerns, "fp-concerns")
    if gaps:
        details += "<p class='fp-concern-title'>Not enough evidence to judge</p>" + _list(gaps, "fp-concerns")
    count = len(gaps) + len(concerns)
    details_html = (f"<details class='fp-details'><summary>Data quality and missing evidence ({count})</summary>"
                    f"{details}</details>" if details else
                    "<p class='fp-muted'>No rating is Amber, Red or waiting for a data check.</p>")
    question = (data.get("presentation_context") or {}).get("question") or concl.get("question")
    question_html = f"<p class='fp-question'>{escape(question)}</p>" if question else ""
    return (f"<div class='fp-card fp-answer'><h3>{escape(title)}</h3>{question_html}{body}"
            f"<p class='fp-muted'>{escape(who)}; a draft for the analyst.</p>{details_html}</div>")


def _metrics(facts: dict) -> str:
    cards = "".join(
        f"<div class='fp-metric'><div class='fp-metric-label'>{escape(m.label)}</div>"
        f"<div class='fp-metric-value{' fp-na' if m.value == NOT_AVAILABLE else ''}'>{escape(m.value)}</div>"
        f"<div class='fp-metric-meta'>{escape(m.period)}</div>"
        f"{(chr(60) + 'div class=' + chr(39) + 'fp-metric-meta' + chr(39) + '>' + escape(m.note) + '</div>') if m.note else ''}"
        f"<div class='fp-metric-source'>Source: {escape(m.source)}</div></div>"
        for m in headline_metrics(facts))
    return f"<div class='fp-metrics'>{cards}</div>"


def _ratings(data: dict, analyst: bool, explanatory: bool = False) -> str:
    rows = ""
    for p in data["facts"].get("scorecard", {}).get("pillars", []):
        if explanatory:
            explanation = rating_explanation(data["facts"], p)
            limits = (p.get('values') or {}).get('limits') or []
            rules = [f"{v.get('metric', 'Measure')}: Green {v.get('green')}, Amber {v.get('amber')}; "
                     f"rule {v.get('kind', 'not specified')} ({v.get('unit') or 'ratio'})." for v in limits]
            methodology = _list([explanation['methodology']] + [s.get('reason', '') for s in p.get('sub_ratings', [])] + rules)
            content = (f"<p><b>{escape(explanation['conclusion'])}</b></p>"
                       f"<p><b>Why this rating?</b> {escape(explanation['why'])}</p>"
                       + ("<p><b>Supporting evidence</b></p>" + _list(explanation['evidence']) if explanation['evidence'] else "")
                       + ("<p><b>Limitations</b></p>" + _list(explanation['limitations']) if explanation['limitations'] else "")
                       + _details("Rating methodology", methodology))
            rows += (f"<div class='fp-rating'><div class='fp-rating-name'><b>{escape(p['name'])}</b></div>"
                     f"{_chip(p['rating'])}<div class='fp-rating-why'>{content}</div></div>")
            continue
        extra = ""
        if analyst:
            subs = [f"{s['name']}: {RATING_STYLE.get(s['rating'], (s['rating'],))[0]} ({s['reason']})"
                    for s in p.get("sub_ratings", [])]
            extra = _list(subs + list(p.get("notes", [])), "fp-sub")
        rows += (f"<div class='fp-rating'><div class='fp-rating-name'><b>{escape(p['name'])}</b>"
                 f"<span>{escape(QUESTIONS.get(p['name'], ''))}</span></div>{_chip(p['rating'])}"
                 f"<div class='fp-rating-why'>{escape(data['reasons'].get(p['name']) or p['reason'])}{extra}</div></div>")
    return f"<div class='fp-card'><h3>The four ratings</h3>{rows}</div>"


def _attention(data: dict, quality: EvidenceQuality, analyst: bool) -> str:
    facts = data["facts"]
    manual = [f"{p['name']}: {p['reason']}" for p in facts.get("scorecard", {}).get("pillars", [])
              if p["rating"] == "MANUAL CHECK"]
    data_items = ([f"Data check: {m}" for m in quality.blocking] + [f"Warning: {m}" for m in quality.warnings]
                  + [f"Reviewer check: {m}" for m in manual])
    data_items += list(data.get("attachment_limitations") or [])
    actions = [report_action(a) for a in data.get("actions") or []]
    body = ""
    if data_items:
        body += "<p class='fp-group'>Evidence quality: data issues to resolve or check</p>" + _list(data_items)
    if quality.ai_read:
        body += "<p class='fp-group'>Evidence note</p>" + _list(["AI-extracted figures require verification against the documents."])
    if actions:
        body += "<p class='fp-group'>Recommended actions</p>" + _list(actions)
    if not body:
        body = "<p class='fp-muted'>Nothing needs attention: no data issues and no actions.</p>"
    return f"<div class='fp-card fp-attention'><h3>Items needing attention</h3>{body}</div>"


def _decisions(data: dict, quality: EvidenceQuality) -> str:
    """ Management view: the decisions to take, in order """
    code = data["facts"].get("scorecard", {}).get("verdict", "")
    items = []
    if quality.level == "check" and quality.label == "Evidence missing":
        items.append("Ask for the missing evidence before a decision is made: " + quality.detail + ".")
    elif quality.level == "check":
        items.append("Ask for the data check to be resolved before a decision is made.")
    items.append(f"Confirm or change the suggested assessment: {verdict_name(code)} "
                 f"({assessment_meaning(code, quality, verdict_meaning(code)).lower()}).")
    required = [c["action"] for c in data["facts"].get("candidate_actions", []) if c.get("required")]
    items += required[:2]
    questions = data["facts"].get("manager_questions", [])[:2]
    if questions:
        items.append("Raise with the fund manager: " + " ".join(questions))
    return "<div class='fp-card'><h3>Key decisions</h3>" + _list(items) + "</div>"


def _returns_table(facts: dict) -> str:
    figs = _figures(facts)
    cols = [("1 year", "cum.1y"), ("3 years", "cum.3y"), ("5 years", "cum.5y"), ("3 years, a year", "ann.3y"),
            ("5 years, a year", "ann.5y")]
    rows = ""
    invalid = comparison_invalid(facts)
    for label, series in (("Fund price (NAV)", "fund_nav"), ("Fund, market-close price (PNAV)", "fund_pnav"),
                          ("Index or benchmark", "index")):
        cells = [figs.get(f"{series}.{c}") for _, c in cols]
        if any(cells) and invalid and series == "index":
            rows += (f"<tr><td class='l'>{label}</td>" + f"<td>{UNRELIABLE}</td>" * len(cols)
                     + f"<td class='l src'>{UNRELIABLE_SOURCE}</td></tr>")
        elif any(cells):
            rows += (f"<tr><td class='l'>{label}</td>" + "".join(f"<td>{_shown(c) if c else '–'}</td>" for c in cells)
                     + f"<td class='l src'>{escape(_source(*cells))}</td></tr>")
    gaps = [figs.get(f"comparison.excess_cum.{c[-2:]}") if c.startswith("cum") else figs.get(f"comparison.td.{c[-2:]}")
            for _, c in cols]
    if any(gaps) and invalid:
        rows += ("<tr class='fp-total'><td class='l'>Gap to the index</td>" + f"<td>{UNRELIABLE}</td>" * len(cols)
                 + f"<td class='l src'>{UNRELIABLE_SOURCE}</td></tr>")
    elif any(gaps):
        basis = next((g.get("basis") for g in gaps if g and g.get("basis")), None)
        basis_label = "market-close PNAV vs index" if basis == "fund_pnav" else "NAV vs index"
        rows += (f"<tr class='fp-total'><td class='l'>Gap to the index ({basis_label})</td>" + "".join(
            f"<td>{_shown(g) if g else '–'}</td>" for g in gaps) + "<td class='l src'>Calculated from the factsheet</td></tr>")
    if not rows:
        return ""
    head = "".join(f"<th>{c}</th>" for c, _ in cols)
    return (f"<h4>Returns to {_date(facts.get('fund', {}).get('as_of_date'))}</h4><div class='fp-scroll'>"
            f"<table class='fp-table'><tr><th class='l'>Return</th>{head}<th class='l'>Source</th></tr>{rows}</table></div>")


def _risk_rows(facts: dict) -> str:
    rows = "".join(f"<tr><td class='l'>{label}</td><td>{value}</td><td class='l src'>{escape(source)}</td></tr>"
                   for label, value, source in risk_measures(facts))
    return (f"<h4>Risk and tracking</h4><table class='fp-table'><tr><th class='l'>Measure</th><th>Value</th>"
            f"<th class='l'>Source</th></tr>{rows}</table>") if rows else ""


def _statistics(facts: dict) -> str:
    ev = facts.get("evidence") or {}
    if not ev or not ev.get("gaps"):
        return ""
    if comparison_invalid(facts):
        return "<h4>Statistics (calculated from the factsheet)</h4>" + _list([UNRELIABLE_WHY + "."])
    years = list(ev["gaps"])
    hits = ev.get("hit_rate")
    test = ev.get("test") or {}
    lines = [f"Yearly gap to the index, {years[0]}–{years[-1]}: average {ev['average']:+.2f} pp; best "
             f"{ev['best'][0]} ({ev['best'][1]:+.2f} pp); worst {ev['worst'][0]} ({ev['worst'][1]:+.2f} pp).",
             (f"Hit rate: {hits[0]} of {hits[1]} calendar years" + (f" within {ev['hit_margin_pp']:.2f} pp (fee + margin)."
              if ev.get("hit_margin_pp") is not None else ".")) if hits is not None else
             "Hit rate: Not available; ongoing charge not established.",
             f"Significance test ({test.get('what', '')}): {test.get('result', 'not run')}."]
    if ev.get("percentile"):
        q = ev["percentile"]
        lines.append(f"Peer percentile: better than {q['beaten']} of {q['peers']} peers over {q['years']} years.")
    return "<h4>Statistics (calculated from the factsheet)</h4>" + _list([x.replace("-", "−") for x in lines])


def _peers(facts: dict) -> str:
    rows = ""
    for p in facts.get("peers", []):
        r = p.get("returns_pct_a_year", {})
        used = f"Fees and returns ({p['basis']})" if p.get("used_for_returns") else f"Fees only: {p.get('excluded')}"
        rows += (f"<tr><td class='l'>{escape(p['name'])}</td><td class='l'>{escape(p.get('currency') or '')}</td>"
                 f"<td>{p['ocf_pct']:.2f}%</td>" + "".join(
                     f"<td>{'–' if r.get(k) is None else f'{r[k]:.2f}%'.replace('-', '−')}</td>" for k in ("1y", "3y", "5y"))
                 + f"<td class='l'>{escape(used)}</td></tr>")
    if not rows:
        return ""
    return ("<h4>Peers</h4><div class='fp-scroll'><table class='fp-table'><tr><th class='l'>Peer</th><th class='l'>"
            "Currency</th><th>Fee</th><th>1 year</th><th>3 years, a year</th><th>5 years, a year</th>"
            f"<th class='l'>Used for</th></tr>{rows}</table></div>")


def _findings(data: dict) -> str:
    facts = data["facts"]
    body = ""
    if data.get("findings"):
        body += "<h4>Key findings</h4>" + _list(data["findings"])
    notes = [plain_note(n) for n in facts.get("data_notes", [])]
    if notes and comparison_invalid(facts):        # the notes compare the fund with its index: not findings yet
        notes = [UNRELIABLE_WHY + ". The notes are kept in the Detailed Report (Appendix B), marked."]
    if notes:
        body += "<h4>Below the surface</h4>" + _list(notes)
    sources = [f"[{s['number']}] {s.get('query', '')} ({s.get('date', '')}) {s.get('url', '')}"
               for s in data.get("sources", [])]
    if data.get("market_context"):
        body += (f"<h4>Market context (AI, checked)</h4><p>{escape(data['market_context'])}</p>"
                 + _list(sources, "fp-sources"))
    elif sources:
        body += "<h4>Research sources</h4>" + _list(sources, "fp-sources")
    return body


def _judgement(facts: dict) -> str:
    points, questions = facts.get("judgement_points", []), facts.get("manager_questions", [])
    body = ""
    if points:
        body += "<h4>Points for your judgement</h4>" + _list(points)
    if questions:
        body += "<h4>Questions to ask the manager</h4>" + _list(questions)
    return body


def technical_html(data: dict) -> str:
    """ The plan, the drafts with the Judge's checklist, and info flags: for the Technical details section """
    facts = data["facts"]
    plan = facts.get("plan") or {}
    body = ""
    if plan:
        body += (f"<p><b>Plan</b> ({escape('Task Planner Agent' if plan.get('source') == 'planner' else str(plan.get('source')))}): "
                 f"{escape(REPORT_TYPE_WORDS.get(plan.get('report_type'), str(plan.get('report_type'))))}; focus "
                 f"{escape(', '.join(plan.get('focus', [])[:2]))}.</p>" + _list(plan.get("tasks", [])))
    drafts = facts.get("drafts") or []
    if drafts:
        rows = "".join(f"<tr><td class='l'>{escape(ANGLE_WORDS.get(d['angle'], d['angle']))}</td><td class='l'>"
                       f"{escape(JUDGE_WORDS.get(d.get('decision'), ''))}</td><td class='l'>{escape(d.get('reason', ''))}"
                       f"</td><td>{'Chosen' if d['chosen'] else ''}</td></tr>" for d in drafts)
        body += ("<p><b>Draft and the Judge's review</b></p><table class='fp-table'><tr><th class='l'>Draft for</th>"
                 f"<th class='l'>Judge's decision</th><th class='l'>Reason</th><th></th></tr>{rows}</table>")
    info = [f["message"] for f in data.get("flags", []) if f["level"] == "info"]
    if info:
        body += "<p><b>For the record (info flags)</b></p>" + _list(info, "fp-small")
    return f"<div class='fp-tech'>{body or '<p>No technical details.</p>'}</div>"


def dashboard_html(data: dict, audience: str = "analyst") -> str:
    """ The whole dashboard for one audience. Same facts and ratings for both """
    analyst = audience != "management"
    facts = data["facts"]
    quality = evidence_quality(data)
    detail = _risk_rows(facts) + _statistics(facts) + _peers(facts) + _findings(data)
    parts = [_summary(data, quality), _header(data, quality), _ratings(data, analyst)]
    if not analyst:
        parts.append(_decisions(data, quality))
    parts += [_attention(data, quality, analyst)]
    detail = "<div class='fp-card'>" + _returns_table(facts) + "</div>" + _metrics(facts) + detail
    if analyst:
        parts.append(_details("Points for your judgement and questions for the manager", _judgement(facts), True))
        parts.append(_details("Detailed performance statistics and findings", detail, True))
    else:
        parts.append(_details("Detailed performance statistics and findings", detail + _judgement(facts)))
    view = "Investment Analyst view: full detail" if analyst else "Management view: summary and decisions"
    return (f"<div class='fp-dashboard' data-audience='{'analyst' if analyst else 'management'}'>"
            f"<p class='fp-view'>{view}. Both views use the same figures and ratings.</p>{''.join(parts)}</div>")


def _chartable_allocation(row: dict) -> bool:
    if (not isinstance(row, dict) or not row.get("name") or not row.get("source")
            or row.get("subject") in ("benchmark", "peer", "unknown")):
        return False
    value, level = row.get("weight_pct"), row.get("evidence_level")
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or not 0 <= value <= 100 or level not in ("verified", "provisional")):
        return False
    if level == "provisional":
        numbers = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%', row.get('excerpt') or '')
        return len(numbers) == 1 and abs(float(numbers[0]) - value) <= 1e-9
    return True


def _allocation_bars(exposures: dict) -> str:
    """Display only sourced, unambiguous weights; extracted classifications remain provisional."""
    sections = []
    for key, heading in (("sectors", "Sector allocation"), ("regions", "Geographic allocation")):
        bars = []
        for row in exposures.get(key) or []:
            if not _chartable_allocation(row):
                continue
            value = row.get("weight_pct")
            level = row.get("evidence_level")
            label = f"{row['name']} — {value:g}%"
            source = str(row['source']) + ("; provisional, classification and date require verification"
                                           if level == "provisional" else "")
            bars.append(f"<div class='fp-allocation'><div class='fp-allocation-label'><span>{escape(str(row['name']))}</span>"
                        f"<b>{value:g}%</b></div><div class='fp-allocation-track' role='img' aria-label='{escape(label, quote=True)}'>"
                        f"<div class='fp-allocation-fill' style='width:{value:g}%'></div></div>"
                        f"<div class='fp-metric-source'>{escape(source)}</div></div>")
        if bars:
            sections.append(f"<h4>{heading}</h4>" + "".join(bars))
    return "".join(sections)


def _strategy(facts: dict, context: dict, exposures: dict, assessment: dict | None = None) -> str:
    fund, extracted = facts.get('fund') or {}, context.get('fund_facts') or {}
    objective = fund.get('objective_text') or extracted.get('objective_text')
    lines = []
    if objective:
        lines.append('Investment objective: ' + str(objective))
    kind = fund.get('objective_type')
    benchmark = fund.get('benchmark_name') or extracted.get('benchmark_name')
    if kind == 'index_tracker':
        lines.append('Investment approach: index tracking' + (f'; benchmark: {benchmark}.' if benchmark else '.'))
    elif benchmark:
        lines.append(f'Benchmark: {benchmark}; consult the mandate for its role.')
    if fund.get('time_horizon_years') is not None:
        lines.append(f"Documented investment horizon: {fund['time_horizon_years']} years.")
    asset = fund.get('asset_class') or extracted.get('asset_class')
    if asset:
        lines.append('Asset class: ' + str(asset))
    regions = [str(item['name']) for item in exposures.get('regions') or []
               if isinstance(item, dict) and item.get('name') and item.get('subject') not in ('benchmark', 'peer', 'unknown')]
    if regions and len(lines) < 6:
        lines.append('Documented geographic exposure: ' + ', '.join(regions[:2]) + ' (AI-extracted; verify).')
    ai = ((assessment or {}).get('assessment') or {}) if (assessment or {}).get('status') == 'available' else {}
    risks = ai.get('material_risks') or []
    if risks and len(lines) < 6:
        lines.append('Main investment risk (AI assessment): ' + str(risks[0]))
    for group in ('portfolio_description', 'concentration'):
        for item in exposures.get(group) or []:
            if isinstance(item, dict) and item.get('name') and len(lines) < 6:
                lines.append(f"Portfolio characteristic: {item['name']} (AI-extracted; verify classification and date).")
    if not lines:
        lines.append('Strategy details are unavailable in the structured evidence.')
    full = ''.join(f"<p>{escape(str(value))}</p>" for value in
                   (context.get('document_summary'), context.get('mandate_interpretation')) if value)
    return ("<div class='fp-card'><h3>Fund strategy &amp; mandate</h3>" + _list(lines[:6])
            + ("<p class='fp-muted'>AI-extracted descriptions require source verification.</p>" if full else '')
            + _details('Source details', full) + '</div>')


def _research_cards(research: list[dict], as_of: str | None) -> str:
    if not research:
        return "<div class='fp-card'><h3>Research findings</h3><p class='fp-muted'>No vetted research is available for this review.</p></div>"
    cards, full = [], []
    for item in research:
        summary = str(item.get('summary') or item.get('title') or 'Research finding unavailable.')
        first = re.split(r'(?<=[.!?])\s+(?=[A-Z])', summary, maxsplit=1)[0]
        url = str(item.get('url') or '')
        try:
            parsed = urlparse(url)
            host = parsed.hostname
        except ValueError:
            parsed, host = urlparse(''), None
        source = host or item.get('title') or 'Source'
        link = (f"<a href='{escape(url, quote=True)}' target='_blank' rel='noopener noreferrer'>{escape(str(source))}</a>"
                if parsed.scheme in ('http', 'https') and host else escape(str(source)))
        day = str(item.get('date') or 'Date unavailable')
        timing = ((' — published after review date' if item.get('date_basis') == 'published'
                   else ' — source date after review; publication date not established')
                  if as_of and item.get('date') and str(item['date']) > as_of else '')
        relevance = item.get('relevance') or 'Assess its relevance to the fund and review question.'
        limitation = item.get('limitations')
        cards.append(f"<div class='fp-research-item'><p><b>Finding:</b> {escape(first)}</p>"
                     f"<p><b>Why it matters:</b> {escape(str(relevance))}</p>"
                     f"<p class='fp-muted'>{link} · {escape(day + timing)}</p>"
                     + (f"<p><b>Limitation:</b> {escape(str(limitation))}</p>" if limitation else '') + '</div>')
        full.append(f"<p>{escape(summary)}</p><p class='fp-muted'>{link} · {escape(day + timing)}</p>")
    return ("<div class='fp-card'><h3>Research findings</h3>" + ''.join(cards[:3])
            + _details('Full research summaries', ''.join(full)) + '</div>')


def dashboard_sections(data: dict) -> dict[str, str]:
    """Four saved-result views; building or opening a view never runs an agent."""
    facts = data["facts"]
    shared = data.get("presentation_context") or {}
    fund_context = shared.get("fund_context") or {}
    assessment = shared.get("investment_assessment") or {}
    research = shared.get("research") or data.get("sources") or []
    quality = evidence_quality(data)
    if assessment.get("status") == "available":
        ai = assessment.get("assessment") or {}
        label = str(ai.get("recommendation", "insufficient_evidence")).replace("_", " ").capitalize()
        details = f"<p class='fp-verdict'>{escape(label)}</p><p>{escape(ai.get('investment_thesis') or '')}</p>"
        for heading, key in (("Strengths", "strengths"), ("Material risks", "material_risks"),
                             ("Uncertainties", "uncertainties"), ("Monitoring actions", "recommended_actions")):
            if ai.get(key):
                details += f"<p class='fp-group'>{heading}</p>" + _list(ai[key])
        if not ai.get("scorecard_agreement", True) and ai.get("scorecard_disagreement_reason"):
            details += f"<p><b>Difference from scorecard:</b> {escape(ai['scorecard_disagreement_reason'])}</p>"
    else:
        details = "<p class='fp-muted'>Independent assessment unavailable; use the scorecard and evidence below.</p>"
    ai_card = "<div class='fp-card'><h3>AI Investment Analyst</h3>" + details + "</div>"
    overview = _header(data, quality, True) + _summary(data, quality, "Answer to your question", True) + _ratings(data, True, True) + ai_card + _metrics(facts)
    chart = ("<figure><img style='width:100%;max-width:720px' alt='Yearly tracking analysis from the review' "
             f"src='data:image/png;base64,{escape(data['performance_chart'], quote=True)}'><figcaption>"
             "Yearly tracking analysis; see labels and source in the report.</figcaption></figure>"
             if data.get("performance_chart") else "")
    status = data.get('primary_chart_status') or {}
    primary = ("<figure><img style='width:100%;max-width:900px' alt='Five-year growth of 100: fund and benchmark' "
               f"src='data:image/png;base64,{escape(data['primary_chart'], quote=True)}'>"
               f"<figcaption>{escape(status.get('caption') or '')}</figcaption></figure>"
               if data.get('primary_chart') else
               f"<p class='fp-muted'>Five-year line chart unavailable: {escape(status.get('reason') or 'Comparable total-return series have not been confirmed.')}</p>")
    financial_detail = _returns_table(facts) + _risk_rows(facts) + _statistics(facts)
    performance = ("<div class='fp-card'><h3>Five-year cumulative performance — fund vs benchmark</h3>" + primary
                   + "</div><div class='fp-card'><h3>Period returns &amp; risk</h3>" + (financial_detail or
                   "<p class='fp-muted'>Performance and risk figures are unavailable for this review.</p>")
                   + "</div>" + _details('Tracking analysis', chart) + _peers(facts))
    exposures = fund_context.get("portfolio_exposures") or {}
    portfolio = _strategy(facts, fund_context, exposures, assessment)
    exposure_items = []
    all_exposure_items = []
    for group in ("holdings", "sectors", "regions", "currencies", "asset_classes", "concentration", "portfolio_description"):
        for row in exposures.get(group) or []:
            if isinstance(row, dict):
                weight = f" — {row['weight_pct']:g}%" if isinstance(row.get("weight_pct"), (float, int)) else ""
                scope = row.get('subject')
                prefix = f"{scope.title()} " if scope in ('benchmark', 'peer', 'unknown') else ''
                text = (f"{prefix}{group.replace('_', ' ').title()}: {row.get('name', '')}{weight}"
                        + (f" ({row['source']})" if row.get('source') else "")
                        + (f" — {row['qualification']}" if row.get('qualification') else ""))
                all_exposure_items.append(text)
                if group not in ('sectors', 'regions') or not _chartable_allocation(row):
                    exposure_items.append(text)
    bars = _allocation_bars(exposures)
    fallback = "<p class='fp-muted'>Exact portfolio exposures are unavailable; see the strategy description above.</p>"
    portfolio += ("<div class='fp-card'><h3>Portfolio exposures</h3>" + bars
                  + (_list(exposure_items) if exposure_items else '' if bars else fallback)
                  + _details('Exposure source details', _list(all_exposure_items)) + "</div>")
    portfolio += _research_cards(research, (facts.get('fund') or {}).get('as_of_date'))
    research_narrative = (facts.get("suggested_conclusion") or {}).get("research_narrative") or []
    if research_narrative:
        portfolio += "<div class='fp-card'><h3>Research interpretation</h3>" + _list(research_narrative) + "</div>"
    documents = [str(name) for name in fund_context.get("sources") or []]
    document_date = fund_context.get("document_date")
    evidence = (_attention(data, quality, True) + "<div class='fp-card'><h3>Documents &amp; evidence</h3>"
                + (_list(documents) or "<p class='fp-muted'>Document details are unavailable.</p>")
                + (f"<p>Document date: {escape(str(document_date))}</p>" if document_date else "") + "</div>"
                + _details("Manager questions and judgement points", _judgement(facts))
                + _details("Technical details", technical_html(data)))
    return {"overview": overview, "performance": performance, "portfolio": portfolio, "evidence": evidence}
