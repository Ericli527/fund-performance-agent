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
]


def chat_view(question: str) -> str | None:
    question = question.casefold().strip().rstrip('?.!')
    if (question in {VIEW_QUESTIONS[2].casefold().rstrip('?'), 'tell me your research about the fund'}
            or re.search(r'\b(?:news|trends|research|regulatory (?:news|updates?))\b', question)
            and re.search(r'\b(?:recent|latest|this week|(?:last|past) (?:week|(?:7|seven) days))\b', question)
            and not re.search(r'\b(?:review date|review period|as of|as at|in \d{4}|(?:last|past) (?:\d+|one|two|three) (?:weeks|months|years))\b', question)):
        return 'weekly'
    if question in {VIEW_QUESTIONS[0].casefold().rstrip('.'), 'tell me about the fund',
                    'summarise key information', 'what are some key data / stat about the fund',
                    'summarise the fund', 'fund overview'}:
        return 'overview'
    if question in {VIEW_QUESTIONS[1].casefold().rstrip('?'),
                    'how closely has the fund followed its benchmark', 'benchmark performance'}:
        return 'benchmark'
    return None


def plain(value) -> str:
    return escape(re.sub(r'([\\`*_{}\[\]|~])', r'\\\1', ' '.join(str(value).split())), quote=False)


def fund_panel(catalogue: dict, view: str | None) -> str:
    if view not in ('overview', 'benchmark'):
        return ''
    fund = catalogue.get('fund_identity') or {}
    if not fund.get('fund_name'):
        return ''
    name = plain(fund['fund_name'])
    details = [plain(fund[key]) for key in ('share_class', 'currency') if fund.get(key)]
    if fund.get('as_of_date'):
        details.append('as at ' + plain(fund['as_of_date']))
    lines = [f'**{name}**']
    if details:
        lines.append(' · '.join(details))
    mandate = ((catalogue.get('mandate') or {}).get('mandate') or {}).get('values') or {}
    if benchmark := mandate.get('benchmark_name') or fund.get('benchmark_name'):
        lines.append('**Documented benchmark** · ' + plain(benchmark))
    if view == 'overview':
        charge = fund.get('ocf_pct')
        if isinstance(charge, (int, float)) and not isinstance(charge, bool) and math.isfinite(charge):
            lines.append(f'**Published ongoing charge** · {charge:g}% a year')
        return '\n\n'.join(lines)
    periods = {'5y': 'Five years', '3y': 'Three years', '1y': 'One year'}
    horizon = f"{mandate.get('time_horizon_years')}y"
    order = dict.fromkeys(([horizon] if horizon in periods else []) + list(periods))
    for period in order:
        label = periods[period]
        row = catalogue.get('performance:' + period) or {}
        pair = []
        for suffix, frequency in [('a_year', 'annualised'), ('cumulative', 'cumulative')]:
            fund_return, index_return = (row.get(f'{side}_return_{suffix}') for side in ('fund', 'benchmark'))
            if all(isinstance(figure, dict) and figure.get('display') for figure in (fund_return, index_return)):
                pair = [plain(fund_return['display']), plain(index_return['display'])]
                break
        basis = {'fund_nav': 'fund dealing value', 'fund_pnav': 'estimated market-close value (illustrative)'}
        if pair and row.get('fund_benchmark_basis') in basis:
            end = f" to {plain(row['as_of_date'])}" if row.get('as_of_date') else ''
            lines.append(f"**{label}{end} ({frequency})** · Fund {pair[0]} · Benchmark {pair[1]}")
            lines.append('Fund price basis · ' + basis[row['fund_benchmark_basis']])
            if any(figure.get('source') == 'factsheet' for figure in (fund_return, index_return)):
                lines.append('Includes factsheet-reported performance.')
            return '\n\n'.join(lines)
    lines.append('A comparable fund and benchmark return pair is unavailable in the prepared calculations.')
    return '\n\n'.join(lines)


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
    return f'**Weekly market brief · {window}**\n\nRefreshed {refreshed} · {scope}'


def research_link(source: dict, title: str) -> str:
    return f"[{plain(title)}]({quote(source['url'], safe=':/?=&%#@+~.-_')})"


def development(source: dict, relevance: str) -> str:
    if not public_url(source.get('url', '')):
        return ''
    try:
        when = date.fromisoformat(source.get('date', ''))
    except (TypeError, ValueError):
        return ''
    timing = ' · published after the fund review' if source.get('timing') == 'after fund review' else ''
    publisher = source.get('publisher') or 'Source'
    headline = (f"**{plain(source.get('title') or 'Read the article')}**\n\n"
                f"{when:%d %b %Y} · {research_link(source, publisher)}{timing}")
    return headline + ('\n\n' + plain(relevance) if relevance else '')
