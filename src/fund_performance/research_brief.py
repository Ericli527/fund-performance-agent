"""One-page research brief from already-vetted review evidence; no model calls."""
from html import escape
from pathlib import Path
import re
from urllib.parse import urlparse

from fund_performance.report import CSS, NAVY, _render, page_texts


def _sentences(text: str, count: int = 1) -> str:
    return ' '.join(re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip())[:count])


def research_html(inp) -> str:
    context = inp.presentation_context or {}
    sources = context.get('research') or []
    assessment = context.get('investment_assessment') or {}
    ai = (assessment.get('assessment') or {}) if assessment.get('status') == 'available' else {}
    narrative = (inp.facts.get('suggested_conclusion') or {}).get('research_narrative') or []
    summary = ' '.join(narrative[:2]) if narrative else (
        'Vetted research is available below; assess its relevance and coverage for the review.' if sources else
        'No vetted research was available. Obtain relevant dated evidence before drawing research conclusions.')
    findings = []
    for i, source in enumerate(sources[:3], 1):
        text = str(source.get('summary') or source.get('title') or 'Source summary unavailable.')
        url = str(source.get('url') or '')
        try:
            parsed = urlparse(url)
            host = parsed.hostname
        except ValueError:
            parsed, host = urlparse(''), None
        link = (f"<a href='{escape(url, quote=True)}'>{escape(host)}</a>"
                if parsed.scheme in ('http', 'https') and host else escape(str(source.get('title') or 'Source')))
        day = str(source.get('date') or 'Date unavailable')
        late = bool(source.get('date') and str(source['date']) > inp.profile.as_of_date.isoformat())
        timing = ' · source date after review' if late else ''
        relevance = source.get('relevance') or 'Assess relevance to the fund and review question.'
        limitation = source.get('limitations')
        findings.append(f"<p><b>[{i}] {escape(_sentences(text))}</b><br/>"
                        f"<span class='src'>{link} · {escape(day + timing)}</span><br/>"
                        f"Why it matters: {escape(str(relevance))}"
                        + (f"<br/>Limitation: {escape(str(limitation))}" if limitation else '') + '</p>')
    questions = ai.get('manager_questions') or inp.facts.get('manager_questions') or []
    questions_html = ''.join(f'<li>{escape(str(q))}</li>' for q in questions[:4])
    cited = {int(x) for x in re.findall(r'\[(\d+)\]', summary + ' ' + str(ai.get('investment_thesis') or '')
                                         + ' ' + ' '.join(map(str, questions[:4])))}
    extra_sources = []
    for n in sorted(cited):
        if n <= 3 or n > len(sources):
            continue
        source = sources[n - 1]
        url = str(source.get('url') or '')
        try:
            parsed = urlparse(url)
            host = parsed.hostname
        except ValueError:
            parsed, host = urlparse(''), None
        link = (f"<a href='{escape(url, quote=True)}'>{escape(host)}</a>"
                if parsed.scheme in ('http', 'https') and host else 'Source')
        extra_sources.append(f"[{n}] {link} · {escape(str(source.get('date') or 'date unavailable'))}")
    footer = (f'<div id="footer">{escape(inp.profile.fund_name)} · Research Brief (draft) · '
              'Page <pdf:pagenumber> of <pdf:pagecount></div>')
    return (f"<html><head><meta charset='utf-8'/><style>{CSS}"
            f".research-title{{font-size:20pt;color:{NAVY};}} .research-body{{font-size:9.5pt;line-height:1.3;}}"
            "</style></head><body>" + footer + "<div class='research-body'>"
            f"<p class='research-title'><b>Research Brief</b></p><p><b>{escape(inp.profile.fund_name)}</b><br/>"
            f"Benchmark: {escape(inp.profile.benchmark_name)} · Review: {inp.profile.as_of_date:%d %b %Y} · "
            f"Prepared: {inp.prepared:%d %b %Y}</p><h2>Research summary</h2><p>{escape(summary)}</p>"
            "<h2>Key findings</h2>" + (''.join(findings) or '<p>No vetted findings available.</p>')
            + "<h2>Investment implications and monitoring</h2>"
            + (f"<p>{escape(str(ai.get('investment_thesis')))}</p>" if ai.get('investment_thesis') else
               '<p>Assess the relevance of new research against the fund mandate and available evidence.</p>')
            + "<h2>Questions for the investment manager</h2>"
            + (f'<ul>{questions_html}</ul>' if questions_html else '<p>No evidence-specific questions are available.</p>')
            + '<h2>Sources and limitations</h2>'
            + ("<p class='src'>" + '<br/>'.join(extra_sources) + '</p>' if extra_sources else '')
            + "<p class='src'>Draft for analyst review. Source dates and stated limitations are shown above; "
              "post-review sources were not available at the review date. No human approval is implied.</p>"
            + '</div></body></html>')


def build_research_brief(inp, out_dir: Path) -> tuple[Path, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / 'report_research.pdf'
    _render(research_html(inp), path)
    return path, len(page_texts(path))
