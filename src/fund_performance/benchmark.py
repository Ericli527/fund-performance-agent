"""Read and align an explicitly identified, separate benchmark price series."""
from pathlib import Path
import re
import numpy as np
import pandas as pd
from fund_performance.io import DATE_ALIASES, INDEX_ALIASES, _find, _normalise, _to_number, parse_dates


def confirm_identity(name: str, currency: str, confirmed: bool, profile, pricing_point: str | None = None) -> None:
    """Require an explicit match to the extracted fund profile before using a separate series."""
    if not confirmed or not (name or '').strip() or not re.fullmatch(r'[A-Za-z]{3}', (currency or '').strip()):
        raise ValueError('Confirm the benchmark name and three-letter currency')
    normalise = lambda value: ' '.join(re.sub(r'[^\w]+', ' ', value.casefold()).split())
    if normalise(name) != normalise(profile.benchmark_name or ''):
        raise ValueError('The confirmed benchmark name does not match the fund profile; check both before continuing')
    if currency.strip().upper() != profile.currency.upper():
        raise ValueError('The confirmed benchmark currency differs from the fund currency; use comparable data')
    if pricing_point not in ('midday', 'market_close') or not profile.pricing_point:
        raise ValueError('Confirm the benchmark pricing time and establish the fund pricing time before continuing')
    if pricing_point != profile.pricing_point:
        raise ValueError('Benchmark and fund price-series pricing times differ; use matching price series')


def read_benchmark(path: str | Path) -> pd.DataFrame:
    """Read date and index level without inferring values or the benchmark's identity."""
    path = Path(path)
    if path.suffix.lower() == '.csv':
        data = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
    elif path.suffix.lower() in ('.xlsx', '.xls'):
        data = pd.read_excel(path)
    else:
        raise ValueError('Benchmark price series must be CSV or Excel')
    data.columns = [_normalise(c) for c in data.columns]
    if data.columns.duplicated().any():
        raise ValueError('Benchmark columns must have distinct names')
    matching = lambda aliases: [c for c in data.columns if any(c == a or c.startswith(a + '_') for a in aliases)]
    if len(matching(DATE_ALIASES)) > 1 or len(matching(INDEX_ALIASES)) > 1:
        raise ValueError('Benchmark date and index level columns must be unambiguous')
    date_col, index_col = _find(list(data.columns), DATE_ALIASES), _find(list(data.columns), INDEX_ALIASES)
    if not date_col or not index_col:
        raise ValueError('Benchmark series needs date and index level columns')
    dates = data[date_col]
    if pd.api.types.is_datetime64_any_dtype(dates):
        dates = pd.to_datetime(dates)
    else:
        dates, _, _ = parse_dates(dates)
    values = _to_number(data[index_col], index_col)
    result = pd.DataFrame({'date': dates, 'index_level': values})
    if result.empty or result['date'].isna().any() or result['date'].duplicated().any():
        raise ValueError('Benchmark dates must be non-empty and unique')
    if result['index_level'].isna().any() or not np.isfinite(result['index_level']).all() or (result['index_level'] <= 0).any():
        raise ValueError('Benchmark levels must be present and positive')
    return result.sort_values('date').reset_index(drop=True)


def align_benchmark(prices: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    """Join exact fund dates only; never fill, interpolate or replace existing index values."""
    if 'index_level' in prices.columns:
        raise ValueError('The fund price file already contains an index series; remove the separate benchmark file')
    merged = prices.merge(benchmark, on='date', how='left', validate='one_to_one', sort=False)
    if merged['index_level'].isna().any():
        raise ValueError('Benchmark series must contain an exact match for every fund price date')
    return merged
