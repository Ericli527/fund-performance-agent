"""Evidence-led chat layouts. Display figures come from the prepared catalogue."""
import math
import re
from datetime import date
from html import escape
from urllib.parse import quote

from fund_performance.chat_research import current_day, public_url

VIEW_QUESTIONS = [
    'Give me a fund overview.',
    'How has the fund performed against its benchmark?',
    'What market news and trends mattered for this fund over the past week?',
    'What does the fund hold?',
]


def chat_view(question: str) -> str | None:
    question = question.casefold().strip().rstrip('?.!')
    if (question in {VIEW_QUESTIONS[2].casefold().rstrip('?'), 'tell me your research about the fund'}
            or re.search(r'\b(?:news|trends|research|regulatory (?:news|updates?))\b', question)
            and re.search(r'\b(?:recent|latest|this week|(?:last|past) (?:week|(?:7|seven) days))\b', question)
            and not re.search(r'\b(?:review date|review period|as of|as at|in \d{4}|(?:last|past) (?:\d+|one|two|three) (?:weeks|months|years))\b', question)):
        return 'weekly'
    if question in {VIEW_QUESTIONS[0].casefold().rstrip('.'), 'tell me about the fund',
                    'summarise key information', 'summarize key information', 'what are some key data / stat about the fund',
                    'summarise the fund', 'fund overview'}:
        return 'overview'
    if question in {VIEW_QUESTIONS[1].casefold().rstrip('?'),
                    'how closely has the fund followed its benchmark', 'benchmark performance'}:
        return 'benchmark'
    if question in {'what does the fund hold', 'what is the fund composition', 'tell me about the fund composition',
                    'show me the fund allocation', 'how is the fund invested'}:
        return 'composition'
    return None


def plain(value) -> str:
    return escape(re.sub(r'([\\`*_{}\[\]|~])', r'\\\1', ' '.join(str(value).split())), quote=False)


def html_text(value) -> str:
    return escape(' '.join(str(value).split()))


def fund_header(fund: dict | None = None) -> str:
    fund = fund or {}
    title = fund.get('fund_name') or 'Fund chatbot'
    details = [html_text(fund[key]) for key in ('share_class', 'currency') if fund.get(key)]
    if fund.get('as_of_date'):
        details.append('Evidence as at ' + html_text(fund['as_of_date']))
    description = ' · '.join(details) or 'Choose a demo or add a factsheet, then prepare the evidence.'
    return (f'<header class="fp-chat-header"><p>FUND EVIDENCE CHAT · BETA</p>'
            f'<h2>{html_text(title)}</h2><div>{description}</div></header>')


def metric_cards(items: list[tuple[str, str]]) -> str:
    if not items:
        return ''
    return '<div class="fp-chat-metrics">' + ''.join(
        f'<div class="fp-chat-metric"><span>{html_text(label)}</span><strong>{html_text(value)}</strong></div>'
        for label, value in items) + '</div>'


def valid_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def composition_panel(catalogue: dict) -> str:
    composition = catalogue.get('fund_composition') or {}
    fund = composition.get('fund') or {}

    def rows(kind):
        return sorted(
            (row for row in fund.get(kind) or [] if row.get('subject') == 'fund' and row.get('source')
             and row.get('name') and valid_number(row.get('weight_pct')) and 0 <= row['weight_pct'] <= 100),
            key=lambda row: row['weight_pct'], reverse=True)[:5]

    blocks = []
    for kind, title in [('sectors', 'Sector allocation'), ('regions', 'Geographic allocation'),
                        ('market_cap', 'Market capitalisation')]:
        allocation = rows(kind)
        if not allocation:
            continue
        bars = []
        for row in allocation:
            name, weight = html_text(row['name']), f"{row['weight_pct']:g}"
            bars.append(f'<div class="fp-chat-allocation"><span>{name}</span><strong>{weight}%</strong>'
                        f'<progress max="100" value="{weight}" aria-label="{name} allocation"></progress></div>')
        blocks.append(f'<section class="fp-chat-data"><h4>{title}</h4>{"".join(bars)}</section>')
    if holdings := rows('holdings'):
        table = ''.join(f"<tr><td>{html_text(row['name'])}</td><td>{row['weight_pct']:g}%</td></tr>"
                        for row in holdings)
        blocks.append('<section class="fp-chat-data"><h4>Largest reported holdings</h4>'
                      '<table><thead><tr><th scope="col">Holding</th><th scope="col">Weight</th></tr></thead>'
                      f'<tbody>{table}</tbody></table></section>')
    if not blocks:
        return ''
    when = ' · ' + html_text(composition['as_of_date']) if composition.get('as_of_date') else ''
    return '<div class="fp-chat-viz">' + ''.join(blocks) + (
        f'<p class="fp-chat-caption">Source: fund composition tables{when} · selected reported weights</p></div>')


def fund_panel(catalogue: dict, view: str | None) -> str:
    if view == 'composition':
        return composition_panel(catalogue)
    if view not in ('overview', 'benchmark'):
        return ''
    fund = catalogue.get('fund_identity') or {}
    if not fund.get('fund_name'):
        return ''
    mandate = ((catalogue.get('mandate') or {}).get('mandate') or {}).get('values') or {}
    benchmark = mandate.get('benchmark_name') or fund.get('benchmark_name')
    if view == 'overview':
        figures = []
        if valid_number(charge := fund.get('ocf_pct')):
            figures.append(('Ongoing charge', f'{charge:g}% a year'))
        if valid_number(risk := fund.get('risk_indicator')):
            figures.append(('Published risk indicator', f'{risk:g}'))
        row = catalogue.get('performance:1y') or {}
        annual = row.get('fund_return_a_year') or {}
        cumulative = row.get('fund_return_cumulative') or {}
        if row.get('fund_benchmark_basis') == 'fund_nav' and (display := annual.get('display') or cumulative.get('display')):
            end = f" to {row['as_of_date']}" if row.get('as_of_date') else ''
            figures.append(('One-year dealing return' + end, display))
        context = (f'<p class="fp-chat-caption">Benchmark · {html_text(benchmark)}</p>' if benchmark else '')
        return metric_cards(figures) + context
    periods = {'5y': 'Five years', '3y': 'Three years', '1y': 'One year'}
    horizon = f"{mandate.get('time_horizon_years')}y"
    order = dict.fromkeys(([horizon] if horizon in periods else []) + list(periods))
    basis = {'fund_nav': 'fund dealing value', 'fund_pnav': 'estimated market-close value (illustrative)'}
    comparisons = []
    for period in order:
        row = catalogue.get('performance:' + period) or {}
        if row.get('fund_benchmark_basis') not in basis:
            continue
        for suffix, frequency in [('a_year', 'annualised'), ('cumulative', 'cumulative')]:
            fund_return, index_return = (row.get(f'{side}_return_{suffix}') for side in ('fund', 'benchmark'))
            if all(isinstance(figure, dict) and figure.get('display') for figure in (fund_return, index_return)):
                end = f" to {html_text(row['as_of_date'])}" if row.get('as_of_date') else ''
                caption = f'{periods[period]}{end} ({frequency}) · {basis[row["fund_benchmark_basis"]]}'
                if any(figure.get('source') == 'factsheet' for figure in (fund_return, index_return)):
                    caption += ' · includes factsheet-reported returns'
                comparisons.append((caption, fund_return['display'], index_return['display']))
                break
    if not comparisons:
        return '<p>A comparable fund and benchmark return pair is unavailable in the prepared calculations.</p>'
    primary, fund_value, index_value = comparisons[0]
    cards = metric_cards([('Fund return', fund_value), ('Benchmark return', index_value)])
    context = f'{html_text(benchmark)} · ' if benchmark else ''
    more = ''.join(f'<tr><td>{caption}</td><td>{html_text(f)}</td><td>{html_text(b)}</td></tr>'
                   for caption, f, b in comparisons[1:])
    table = ('<div class="fp-chat-data"><table><thead><tr><th scope="col">Period and basis</th>'
             '<th scope="col">Fund</th><th scope="col">Benchmark</th></tr></thead>'
             f'<tbody>{more}</tbody></table></div>') if more else ''
    return cards + f'<p class="fp-chat-caption">{context}{primary}</p>' + table


def weekly_unavailable(catalogue: dict, question: str) -> str | None:
    if chat_view(question) != 'weekly':
        return None
    coverage = catalogue.get('research_availability') or {}
    if not coverage.get('as_of_date'):
        return 'Weekly research is unavailable. Use **Prepare evidence / refresh research** to check for dated sources.'
    if coverage['as_of_date'] != current_day().isoformat():
        return (f"The saved research window ended on {plain(coverage['as_of_date'])}. "
                'Use **Prepare evidence / refresh research** for the latest seven days.')
    if not coverage.get('source_count'):
        window = f"{plain(coverage.get('window_start', ''))} to {plain(coverage['as_of_date'])}"
        return f'**Weekly market brief · {window}**\n\n' + plain(coverage.get('message') or 'No dated sources were kept.')
    return None


def weekly_heading(catalogue: dict) -> str:
    coverage = catalogue['research_availability']
    window = f"{plain(coverage['window_start'])} to {plain(coverage['as_of_date'])}"
    refreshed = plain(coverage['refreshed_at']).replace('T', ' ').replace('+00:00', ' UTC')
    count = coverage['source_count']
    scope = f'{count} dated {"source" if count == 1 else "sources"} retained.'
    if count < 5:
        scope += ' Coverage is partial.'
    return (f'<div class="fp-chat-brief"><span>WEEKLY MARKET BRIEF</span>'
            f'<strong>{window}</strong><small>Refreshed {refreshed} · {scope}</small></div>')


def development(source: dict, relevance: str) -> str:
    if not public_url(source.get('url', '')):
        return ''
    try:
        when = date.fromisoformat(source.get('date', ''))
    except (TypeError, ValueError):
        return ''
    timing = ' · published after the fund review' if source.get('timing') == 'after fund review' else ''
    publisher = html_text(source.get('publisher') or 'Source')
    url = escape(quote(source['url'], safe=':/?=&%#@+~.-_'))
    body = f'<p>{html_text(relevance)}</p>' if relevance else ''
    return (f'<article class="fp-chat-story"><div><time datetime="{when.isoformat()}">{when:%d %b %Y}</time>'
            f' · <a href="{url}">{publisher}</a>{timing}</div>'
            f'<h4>{html_text(source.get("title") or "Read the article")}</h4>{body}</article>')
