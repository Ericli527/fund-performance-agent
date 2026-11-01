"""Deterministic attachment identification for the review input page."""
from pathlib import Path
import re
import pandas as pd
from fund_performance.io import read_document, read_prices

PRICE = 'Price history'
FACTSHEET = 'Fund factsheet'
KID = 'KID/KIID'
PEER = 'Peer factsheet'
BENCHMARK = 'Benchmark evidence'
CONFIRM = 'Needs confirmation'
DEMO_INPUT = 'Prevalidated demo input'
ROLES = (PRICE, FACTSHEET, KID, PEER, BENCHMARK, CONFIRM)
PRICE_TYPES = {'.csv', '.xlsx', '.xls'}
DOC_TYPES = {'.pdf', '.docx'}


def classify(path: str) -> tuple[str, str]:
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
            text = ' '.join(read_document(p).lower().split())
            if not text:
                return CONFIRM, 'No readable text found.'
            kid = re.search(r'\b(key investor information|key information document|kiid|kid)\b', text)
            factsheet = re.search(r'\b(fund factsheet|fund fact sheet|fund fact card|fund factcard)\b', text)
            if kid and factsheet:
                return CONFIRM, 'The document mentions both a KID and a factsheet; confirm its role.'
            if kid:
                return KID, ''
            if factsheet:
                return CONFIRM, 'Factsheet detected; confirm whether it is the fund or a peer.'
            return CONFIRM, 'Document role needs confirmation.'
        return CONFIRM, 'Unsupported file type.'
    except Exception:
        return CONFIRM, 'File could not be read; replace it or check its format.'


def add_files(entries: list[dict] | None, paths: list[str] | None) -> list[dict]:
    result = list(entries or [])
    for path in paths or []:
        role, issue = classify(path)
        result.append({'id': str(len(result) + 1), 'path': str(path), 'role': role, 'issue': issue})
    return result


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
                detected, issue = classify(str(path))
                if 'could not be read' in issue or 'No readable' in issue:
                    issues.append(f'{path.name}: {issue}')
                elif len(read_document(path).strip()) > 12000:
                    issues.append(f'{path.name}: benchmark evidence must contain at most 12000 characters of text.')
            else:
                issues.append(f'{path.name}: benchmark evidence must be CSV, Excel, PDF or Word.')
        elif role != DEMO_INPUT:
            detected, issue = classify(str(path))
            if issue and ('could not be read' in issue or 'Unsupported' in issue or 'No readable' in issue):
                issues.append(f'{path.name}: {issue}')
            if role == PRICE and detected != PRICE:
                issues.append(f'{path.name}: select a readable price history.')
            if role in (FACTSHEET, KID, PEER) and path.suffix.lower() not in DOC_TYPES:
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
