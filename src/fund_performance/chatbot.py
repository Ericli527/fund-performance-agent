"""Prepare one session's evidence once; follow-up questions do not reread documents or run reports."""
import asyncio
import copy
import hashlib
import json
import logging
import os
import tempfile
from html import escape
from pathlib import Path

from fund_performance.agents.investment_analyst import investment_evidence_package
from fund_performance.attachments import engine_inputs, supporting_inputs
from fund_performance.calc import CalcResult
from fund_performance.config import load_thresholds
from fund_performance.controller import find_inputs, run_review
from fund_performance.fund_context import build_fund_context
from fund_performance.glossary import GLOSSARY
from fund_performance.intake import read_documents, self_check, write_inputs
from fund_performance.io import read_json, read_peers
from fund_performance.precedence import apply_precedence

REPORTING_MODE, CHAT_MODE = 'Fund Review (Reporting)', 'AI Chatbot (Beta)'


def ai_disabled() -> bool:
    from fund_performance.web import OFFLINE_ENV, ai_switched_off
    return ai_switched_off() or os.getenv(OFFLINE_ENV, '').strip().lower() in ('1', 'true', 'yes')


def evidence_key(entries: list[dict], benchmark: dict) -> str:
    """Detect type, selection, benchmark and file changes without re-reading document text."""
    files = []
    for item in entries:
        stat = Path(item['path']).stat()
        files.append({key: item.get(key) for key in ('id', 'path', 'role', 'document_date')}
                     | {'bytes': stat.st_size, 'mtime': stat.st_mtime_ns})
    return hashlib.sha256(json.dumps([files, benchmark], sort_keys=True).encode()).hexdigest()


def matches(state: dict | None, entries: list[dict], benchmark: dict) -> bool:
    try:
        return bool(state and not state.get('invalidated') and state.get('key') == evidence_key(entries, benchmark))
    except OSError:
        return False


def brief(bundle: dict) -> str:
    """A deterministic summary, with provenance; never a new AI verdict."""
    profile = bundle['profile']
    terms = [('Fund', profile.get('fund_name')), ('Share class', profile.get('share_class')),
             ('Currency', profile.get('currency')), ('Figures as at', profile.get('as_of_date')),
             ('Benchmark', profile.get('benchmark_name')), ('Objective', profile.get('objective_text'))]
    text = '**Prepared fund evidence — preliminary**\n\n' + '\n\n'.join(
        f'**{label}:** {escape(str(value))}' for label, value in terms if value)
    text += '\n\n**Inputs:** ' + ', '.join(escape(name) for name in bundle['input_files'])
    if profile.get('ocf_pct') is not None:
        text += f"\n\n**Published ongoing charge (OCF):** {profile['ocf_pct']:g}% a year."
    if bundle.get('highlights'):
        text += '\n\n**Available financial evidence**\n' + '\n'.join('- ' + escape(line) for line in bundle['highlights'])
    text += '\n\n' + bundle['notice']
    research = bundle.get('research') or {}
    if research.get('searches_requested'):
        text += (f"\n\n**Recent research:** {research['source_count']} vetted source(s) retained from five parallel searches, "
                 f"covering {research['window_start']} to {research['as_of_date']}. "
                 'Current news is separate from the historical fund review. Prepare again to refresh; follow-up questions reuse these sources.')
        if research['source_count'] < 5:
            text += ' Some searches returned no usable dated source; coverage is incomplete.'
    else:
        text += '\n\n**Recent research:** Not run (AI/research disabled, unavailable or not requested).'
    text += '\n\nPreparation does not run an independent investment assessment, quality review or PDF reporting.'
    from fund_performance.chat_presentation import FOOTER
    text += '\n\n' + FOOTER
    return text


async def _prepare_evidence(entries: list[dict], benchmark: dict, out_root: Path,
                           reader=read_documents, review=run_review, on_fund_context=None) -> dict:
    # Import locally to share the existing safe input copier without a module import cycle.
    from fund_performance.web import prepare_inputs
    price, factsheet, kid, peers, jsons = engine_inputs(entries)
    intake = None
    with tempfile.TemporaryDirectory(prefix='fund-chat-') as temporary:
        folder = Path(temporary)
        if jsons:
            prepare_inputs(([price] if price else []) + jsons, folder)
        else:
            options = {'supporting_documents': [Path(p) for p in supporting_inputs(entries)]} if supporting_inputs(entries) else {}
            if on_fund_context is not None:
                options['on_fund_context'] = on_fund_context
            intake = await reader(Path(factsheet), Path(kid) if kid else None, [Path(p) for p in peers], **options)
            built = self_check(intake)
            if built.problems:
                raise ValueError('The fund evidence could not be prepared. Check the required identity, dates and source documents.')
            write_inputs(built, folder)
            intake = intake | {'rows': built.rows, 'flags': intake.get('flags', []) + built.flags}
            if price:
                prepare_inputs([price], folder)
        files = find_inputs(folder)
        if 'fund_profile' not in files:
            raise ValueError('A fund profile is required. Add a readable main factsheet or validated fund profile.')
        profile = read_json(files['fund_profile'])
        context = (intake or {}).get('fund_context') or build_fund_context(profile=profile.model_dump(mode='json'))
        if on_fund_context is not None:
            on_fund_context(context)
        if price:
            request_intake = (intake or {}) | {'benchmark_inputs': benchmark} if intake or benchmark.get('series') else None
            result = await review(folder, 'Prepare evidence for fund questions', out_root=out_root,
                                  evidence_only=True, intake=request_intake)
            shared = result.presentation_context or {}
            package = investment_evidence_package(result.facts, profile, [],
                shared.get('portfolio_exposures'), shared.get('fund_context') or context)
            catalogue = package['evidence_catalogue']
            catalogue['fund_identity'] = package['fund_identity_and_terms']
            catalogue['investment_returns'] = {'figures': [f for f in result.facts.get('figures', [])
                if f.get('name', '').startswith(('fund_nav.cum.', 'fund_nav.ann.', 'fund_pnav.cum.', 'fund_pnav.ann.'))]}
            from fund_performance.presentation import headline_metrics
            highlights = [f'{m.label}: {m.value} ({m.period}); {m.source}.' for m in headline_metrics(result.facts)]
            notice = 'Published figures and Python calculations are available; quantitative scorecard indications are preliminary.'
        else:
            fs = read_json(files['factsheet_performance']) if 'factsheet_performance' in files else None
            # Reuse published-figure formatting. No price observations or comparable basis are invented.
            reported = apply_precedence(CalcResult(), [], profile, load_thresholds(), fs)
            figures = [{'name': key, **value.model_dump(mode='json')} for key, value in reported.figures.items()
                       if value.source == 'factsheet']
            catalogue = {'fund_identity': profile.model_dump(mode='json'), 'fund_context': context,
                         'published_figures': {'figures': figures, 'status': 'provisional; verify source documents'},
                         'peer_documents': {'peers': [p.model_dump(mode='json') for p in read_peers(files['peer'])]
                                            if 'peer' in files else [],
                                            'limitations': 'No peer comparison calculations were run.'}}
            series_labels = {'fund_nav': 'Fund (dealing NAV)', 'fund_pnav': 'Fund (market-close price)', 'index': 'Benchmark'}
            highlights = [f"{series_labels.get(row['name'].split('.')[0], 'Fund')}, five-year annualised return: "
                          f"{row['value']:g}% a year (published; provisional)."
                          for row in figures if row['name'].endswith('.ann.5y')]
            notice = 'No price history was supplied. Price-derived statistics, benchmark-relative calculations and scorecard ratings were not run.'
        if benchmark.get('documents'):
            notice += ' Benchmark documents are retained for Reporting mode; they are not vetted research in this beta.'
        catalogue['fund_composition'] = {
            'fund': context.get('portfolio_exposures'),
            'benchmark': context.get('benchmark_composition'),
            'scope_unconfirmed': context.get('unattributed_composition'),
            'as_of_date': context.get('document_date') or profile.as_of_date.isoformat(),
            'interpretation': 'Use headings and source scope excerpts together. Describe fund-labelled tables as factsheet-reported '
                              'composition, not independently verified holdings. Index is not by itself proof of benchmark-only scope. '
                              'Keep explicitly benchmark-only tables separate. Explain conflicting attribution briefly; do not discard their figures.'}
        catalogue['methodology'] = GLOSSARY.copy()
        catalogue['service_scope'] = {'identity': 'AI fund evidence assistant (Beta)',
            'limits': 'Bounded Python cash illustrations are supported. No new investment ratings, on-demand web searches, full report, human approval or independent quality review in chat.'}
        catalogue['evidence_limits'] = {'notice': notice, 'flags': (intake or {}).get('flags', []),
                                      'research': 'No web research was performed for this chat.',
                                      'verification': 'AI extraction and text matching are not independent verification.'}
        bundle = {'profile': profile.model_dump(mode='json'), 'catalogue': catalogue,
                  'notice': notice, 'highlights': highlights, 'input_files': [Path(item['path']).name for item in entries]}
        bundle['summary'] = brief(bundle)
        return bundle


def with_research(bundle: dict, research: dict) -> dict:
    result = copy.deepcopy(bundle)
    catalogue = result['catalogue']
    for key in list(catalogue):
        if key.startswith('research:'):
            del catalogue[key]
    for i, source in enumerate(research['sources'], 1):
        catalogue[f'research:{i}'] = source
    result['research'] = research
    catalogue['research_availability'] = {key: value for key, value in research.items() if key != 'sources'}
    catalogue['evidence_limits']['research'] = (f"{research['source_count']} vetted current sources; "
        f"{research['window_start']} to {research['as_of_date']}. These are current context, not historical fund performance evidence.")
    result['summary'] = brief(result)
    return result


async def prepare_evidence(entries: list[dict], benchmark: dict, out_root: Path,
                           reader=read_documents, review=run_review, *, research_enabled=False,
                           research_run=None, retrieve=None) -> dict:
    from fund_performance.chat_research import current_research
    task = None
    def start(context):
        nonlocal task
        if task is None:
            seed = dict(context.get('fund_facts') or {})
            seed['as_of_date'] = seed.get('as_of_date') or context.get('document_date')
            task = asyncio.create_task(current_research(seed, context.get('portfolio_exposures'),
                                                       run=research_run, retrieve=retrieve))
    try:
        bundle = await _prepare_evidence(entries, benchmark, out_root, reader, review,
                                        on_fund_context=start if research_enabled else None)
        return with_research(bundle, await task) if task else bundle
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def prepare_session(selected: list[dict], benchmark: dict, state: dict, limits,
                          reader=None, review=None, research_run=None, retrieve=None) -> tuple[dict | None, str]:
    """`state` is a session-local revocable preparation token, never a global evidence cache."""
    from fund_performance.agents.base import AI_CALLS, api_key_present
    from fund_performance.config import load_settings
    cached = bool(state.get('bundle') and matches(state, selected, benchmark))
    research_enabled = (not ai_disabled() and load_settings().research.enabled
                        and (api_key_present() or research_run is not None))
    if cached and not research_enabled:
        return state, state['bundle']['summary']
    needs_ai = not cached and not engine_inputs(selected)[4]
    if needs_ai and (ai_disabled() or (reader is None and not api_key_present())):
        return None, 'AI document reading is unavailable. Use validated demo inputs or configure the AI service.'
    if (needs_ai or research_enabled) and (refused := limits.start()):
        return None, refused
    calls = []
    token = AI_CALLS.set(calls)
    try:
        options = ({'reader': reader} if reader else {}) | ({'review': review} if review else {})
        options |= {'research_enabled': research_enabled, 'research_run': research_run, 'retrieve': retrieve}
        with tempfile.TemporaryDirectory(prefix='fund-chat-calculations-') as output:
            if cached:
                from fund_performance.chat_research import current_research
                bundle = state['bundle']
                composition = bundle['catalogue'].get('fund_composition') or {}
                research = await current_research(bundle['profile'], composition.get('fund'), run=research_run, retrieve=retrieve)
                bundle = with_research(bundle, research)
            else:
                bundle = await asyncio.wait_for(prepare_evidence(selected, benchmark, Path(output), **options),
                    timeout=load_settings().timeouts_seconds.extractor * 4)
        if not matches(state, selected, benchmark):
            return None, 'Inputs changed during preparation. Prepare the new fund evidence before chatting.'
        return state | {'bundle': bundle, 'history': [], 'usage': (state.get('usage') or []) + calls}, bundle['summary']
    except Exception as error:
        logging.getLogger(__name__).warning('Chat evidence preparation failed (%s)', type(error).__name__)
        return None, 'The evidence could not be prepared. Check the inputs and try again; your attachments are unchanged.'
    finally:
        AI_CALLS.reset(token)
        if needs_ai or research_enabled:
            limits.finish()


async def reply(selected: list[dict], benchmark: dict, state: dict | None, question: str, limits, run=None):
    from fund_performance.agents.base import AI_CALLS, api_key_present
    from fund_performance.agents.chatbot import MAX_QUESTION, answer_question
    from fund_performance.config import load_settings
    if not state or not state.get('bundle') or state.get('invalidated'):
        return None, [], 'Prepare the fund evidence first.'
    if not matches(state, selected, benchmark):
        return None, [], 'Inputs changed or a file is unavailable. Prepare the new fund evidence before chatting.'
    history = list(state.get('history') or [])
    if not question.strip() or len(question) > MAX_QUESTION:
        return state, history, 'Please ask a fund question of up to 2,000 characters.'
    if ai_disabled() or (run is None and not api_key_present()):
        return state, history, 'AI chat is unavailable in this environment. The prepared evidence remains available.'
    if refused := limits.start():
        return state, history, refused
    calls = []
    token = AI_CALLS.set(calls)
    try:
        answer = await asyncio.wait_for(answer_question(state['bundle']['catalogue'], question, history, run),
                                         timeout=load_settings().timeouts_seconds.narrative)
    except Exception as error:
        logging.getLogger(__name__).warning('Chat answer failed (%s)', type(error).__name__)
        return state, history, 'The answer could not be completed. Your evidence and conversation remain available.'
    finally:
        AI_CALLS.reset(token)
        limits.finish()
    if not matches(state, selected, benchmark):
        return None, [], 'Inputs changed while answering. Prepare the new evidence; the old answer was withheld.'
    history = (history + [{'role': 'user', 'content': escape(question, quote=False)},
                           {'role': 'assistant', 'content': answer}])[-40:]
    return state | {'history': history, 'usage': (state.get('usage') or []) + calls}, history, 'Response complete; review its sources and qualifications.'
