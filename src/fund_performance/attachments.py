"""Deterministic attachment identification for the review input page."""
from pathlib import Path
import logging
import re
import uuid
import pandas as pd
from fund_performance.io import read_document, read_prices

PRICE = 'Price history'
FACTSHEET = 'Fund factsheet'
KID = 'KID/KIID'
PEER = 'Peer factsheet'
SUPPORTING = 'Other supporting document'
BENCHMARK = 'Benchmark evidence'
CONFIRM = 'Needs confirmation'
DEMO_INPUT = 'Prevalidated demo input'
ROLES = (PRICE, FACTSHEET, KID, PEER, SUPPORTING, BENCHMARK, CONFIRM)
PRICE_TYPES = {'.csv', '.xlsx', '.xls'}
DOC_TYPES = {'.pdf', '.docx'}
LOGGER = logging.getLogger(__name__)


def _signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns
    except OSError:
        return None


def classify(path: str, *, details: dict | None = None) -> tuple[str, str]:
    """Only assign a role where file structure or document text supports it."""
    p = Path(path)
    try:
        if p.suffix.lower() in PRICE_TYPES:
            try:
                prices = read_prices(p).prices
            except (OSError, ValueError, ImportError, IndexError):
                table = pd.read_csv(p, nrows=5) if p.suffix.lower() == '.csv' else pd.read_excel(p, nrows=5)
                names = {re.sub(r'[^a-z0-9]+', '_', str(c).strip().lower()).strip('_') for c in table.columns}
                if names & {'date', 'as_of', 'as_of_date', 'price_date', 'valuation_date'} and names & {
                    'index_level', 'index', 'benchmark', 'benchmark_level'
                } and not names & {'nav', 'price', 'nav_price', 'fund_nav', 'close'}:
                    return BENCHMARK, 'Confirm the benchmark name and currency before use.'
                raise
            if len(prices) < 2:
                return CONFIRM, 'Price history needs at least two observations.'
            return PRICE, ''
        if p.suffix.lower() in DOC_TYPES:
            raw = read_document(p)
            if details is not None:
                details['document_length'] = len(raw.strip())
            text = ' '.join(raw.lower().split())
            if not text:
                return CONFIRM, 'No readable text found.'
            kid = re.search(r'\b(key investor information|key information document|kiid|kid)\b', text)
            factsheet = re.search(r'\b(fund factsheet|fund fact sheet|fund fact card|fund factcard)\b', text)
            filename = re.sub(r'[^a-z0-9]+', ' ', p.stem.lower()).strip()
            named_factsheet = bool(re.search(r'\b(?:fact\s*sheet|factsheet)\b', filename))
            if named_factsheet:
                if re.match(r'^(?:key investor information|key information document|kiid|kid)\b', text):
                    return CONFIRM, 'Filename and document heading disagree; confirm its type.'
                if re.search(r'\bpeer\b', filename):
                    return PEER, ''
                return FACTSHEET, ''
            if kid and factsheet:
                return CONFIRM, 'The document mentions both a KID and a factsheet; confirm its role.'
            if kid:
                if re.match(r'^(?:key investor information|key information document|kiid|kid)\b', text):
                    return KID, ''
                return CONFIRM, 'The document mentions a KID; confirm its type.'
            if factsheet:
                return CONFIRM, 'Factsheet detected; confirm whether it is the fund or a peer.'
            return CONFIRM, 'Document role needs confirmation.'
        return CONFIRM, 'Unsupported file type.'
    except Exception:
        LOGGER.exception('Attachment classification failed for %s', p.name)
        return CONFIRM, 'File could not be read; replace it or check its format.'


def add_files(entries: list[dict] | None, paths: list[str] | None) -> list[dict]:
    result = list(entries or [])
    for path in paths or []:
        details = {}
        try:
            role, issue = classify(path, details=details)
        except Exception:
            LOGGER.exception('Unexpected attachment processing failure')
            role, issue = CONFIRM, 'File could not be processed; remove it and try again.'
        result.append({'id': uuid.uuid4().hex[:12], 'path': str(path), 'role': role, 'issue': issue,
                       'inspection': details | {'signature': _signature(Path(path)), 'role': role, 'issue': issue}})
    return result


def _inspection(entry: dict) -> dict:
    """Reuse only this session's inspection while the underlying file is unchanged."""
    path = Path(entry['path'])
    cached = entry.get('inspection') or {}
    signature = _signature(path)
    if signature is not None and tuple(cached.get('signature') or ()) == signature:
        return cached
    details = {}
    role, issue = classify(str(path), details=details)
    return details | {'signature': signature, 'role': role, 'issue': issue}


def rows(entries: list[dict]) -> list[list[str]]:
    return [[e['id'], Path(e['path']).name, e['role'], e.get('issue', ''), e.get('document_date', '')] for e in entries]


def apply_roles(entries: list[dict], table) -> tuple[list[dict], str]:
    """IDs refer only to server-side paths; deleting a row removes that attachment."""
    by_id = {e['id']: e for e in entries}
    selected = []
    seen = set()
    for row in table or []:
        if not row or not str(row[0]).strip():
            continue
        key, role = str(row[0]).strip(), str(row[2]).strip()
        if key not in by_id or key in seen or role not in (*ROLES, DEMO_INPUT):
            return [], 'Invalid attachment row; reload the files and confirm their roles.'
        original = by_id[key]
        if role == DEMO_INPUT and original['role'] != DEMO_INPUT:
            return [], 'Prevalidated demo inputs cannot be added manually.'
        seen.add(key)
        selected.append(original | {'role': role, 'document_date': str(row[4]).strip() if len(row) > 4 else ''})
    return selected, ''


def reconcile_roles(entries: list[dict], table) -> tuple[list[dict], str]:
    """Apply visible edits without losing files added after an overlapping event was queued."""
    selected, error = apply_roles(entries, table)
    if error:
        return [], error
    chosen = {entry['id']: entry for entry in selected}
    return [chosen.get(entry['id'], entry) for entry in entries], ''


def validate(question: str, entries: list[dict], synthetic: bool = False) -> list[str]:
    issues = []
    if not (question or '').strip():
        issues.append('Enter a review question.')
    for e in entries:
        role = e['role']
        path = Path(e['path'])
        if not path.is_file():
            issues.append(f'{path.name}: file is unavailable.')
        elif role == DEMO_INPUT and not synthetic:
            issues.append(f'{path.name}: prevalidated demo inputs can only be used with the synthetic demo.')
        elif role == CONFIRM:
            issues.append(f'{path.name}: confirm its role or remove it.')
        elif role == BENCHMARK:
            if path.suffix.lower() in PRICE_TYPES:
                from fund_performance.benchmark import read_benchmark
                try:
                    read_benchmark(path)
                except Exception:
                    issues.append(f'{path.name}: benchmark series needs readable dates and positive index levels.')
            elif path.suffix.lower() in DOC_TYPES:
                inspection = _inspection(e)
                issue = inspection['issue']
                if 'could not' in issue.lower() or 'no readable' in issue.lower():
                    issues.append(f'{path.name}: {issue}')
                elif inspection.get('document_length', 0) > 12000:
                    issues.append(f'{path.name}: benchmark evidence must contain at most 12000 characters of text.')
            else:
                issues.append(f'{path.name}: benchmark evidence must be CSV, Excel, PDF or Word.')
        elif role != DEMO_INPUT:
            inspection = _inspection(e)
            detected, issue = inspection['role'], inspection['issue']
            if issue and ('could not' in issue.lower() or 'unsupported' in issue.lower() or 'no readable' in issue.lower()):
                issues.append(f'{path.name}: {issue}')
            if role == PRICE and detected != PRICE:
                issues.append(f'{path.name}: select a readable price history.')
            if role in (FACTSHEET, KID, PEER, SUPPORTING) and path.suffix.lower() not in DOC_TYPES:
                issues.append(f'{path.name}: this role requires a readable PDF or Word document.')
    if sum(e['role'] == PRICE for e in entries) != 1:
        issues.append('Add exactly one fund price history.')
    if not synthetic and sum(e['role'] == FACTSHEET for e in entries) != 1:
        issues.append('Add exactly one main fund factsheet.')
    if sum(e['role'] == KID for e in entries) > 1:
        issues.append('Choose at most one KID/KIID.')
    if sum(e['role'] == BENCHMARK and Path(e['path']).suffix.lower() in PRICE_TYPES for e in entries) > 1:
        issues.append('Choose at most one separate benchmark series.')
    if synthetic and any(e['role'] == BENCHMARK for e in entries):
        issues.append('The synthetic demo uses its validated inputs; remove separate benchmark files.')
    if synthetic and any(e['role'] == SUPPORTING for e in entries):
        issues.append('The synthetic demo uses its validated inputs; remove supporting documents.')
    prices = [e['path'] for e in entries if e['role'] == PRICE]
    series = [e['path'] for e in entries if e['role'] == BENCHMARK and Path(e['path']).suffix.lower() in PRICE_TYPES]
    if len(prices) == len(series) == 1:
        from fund_performance.benchmark import align_benchmark, read_benchmark
        try:
            align_benchmark(read_prices(prices[0]).prices, read_benchmark(series[0]))
        except (ValueError, OSError, KeyError) as e:
            issues.append(f'Benchmark series: {e}')
    return issues


def engine_inputs(entries: list[dict]) -> tuple:
    def one(role):
        return next((e['path'] for e in entries if e['role'] == role), None)
    return (one(PRICE), one(FACTSHEET), one(KID), [e['path'] for e in entries if e['role'] == PEER],
            [e['path'] for e in entries if e['role'] == DEMO_INPUT])


def supporting_inputs(entries: list[dict]) -> list[str]:
    """Supporting documents remain separate from peer and benchmark evidence."""
    return [e['path'] for e in entries if e['role'] == SUPPORTING]


def select_type(entries: list[dict], table, attachment_id: str, selected_type: str):
    """Apply a per-file selection to the authoritative table and server-side state."""
    selected, error = reconcile_roles(entries or [], table)
    if error:
        return entries, rows(entries or [])
    if selected_type not in ROLES:
        return entries, rows(entries or [])
    if not any(e['id'] == attachment_id and e['role'] != DEMO_INPUT for e in selected):
        return entries, rows(entries or [])
    selected = [e | {'role': selected_type, 'issue': ''} if e['id'] == attachment_id else e for e in selected]
    return selected, rows(selected)


def remove_attachment(entries: list[dict], table, attachment_id: str) -> tuple[list[dict], list[list[str]]]:
    """Remove one current-session entry; never delete or replace the uploaded file."""
    selected, error = reconcile_roles(entries or [], table)
    if error:
        return entries, rows(entries or [])
    selected = [entry for entry in selected if entry['id'] != attachment_id]
    return selected, rows(selected)
