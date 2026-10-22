""" Price history from EODHD (eodhd.com), which covers UK and European funds by ISIN """
import os
import re
import pandas as pd
import requests

EODHD_URL = "https://eodhd.com/api"
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
# Yahoo-style suffixes people often type, mapped to EODHD exchange codes
SUFFIXES = {".L": ".LSE", ".AS": ".AS", ".PA": ".PA", ".DE": ".XETRA"}


class MarketDataError(Exception):
    """ A problem the user can act on, with a plain-English message """


def api_key() -> str | None:
    return os.getenv("EODHD_API_KEY")


def _get(path: str, **params) -> list | dict:
    params |= {"api_token": api_key(), "fmt": "json"}
    try:
        response = requests.get(f"{EODHD_URL}/{path}", params=params, timeout=20)
    except requests.RequestException as e:
        raise MarketDataError(f"Could not reach EODHD ({e.__class__.__name__}).") from e
    if response.status_code in (401, 403):
        raise MarketDataError("EODHD rejected the API key. Check EODHD_API_KEY, or whether your plan covers this data.")
    if response.status_code in (402, 429):
        raise MarketDataError("EODHD daily request limit reached. Try again tomorrow or upgrade the plan.")
    if response.status_code == 404:
        raise MarketDataError(f"EODHD has no data for '{path.split('/')[-1]}'.")
    if not response.ok:
        raise MarketDataError(f"EODHD returned an error ({response.status_code}).")
    return response.json()


def resolve(query: str) -> tuple[str, str, str]:
    """ ISIN, name or ticker -> (EODHD symbol, name, currency) """
    query = query.strip()
    for suffix, exchange in SUFFIXES.items():
        if query.upper().endswith(suffix.upper()) and not query.upper().endswith(exchange.upper()):
            query = query[: -len(suffix)] + exchange
    if "." in query and not ISIN_PATTERN.match(query.upper()):
        return query, query, ""  # already an EODHD symbol such as IUKD.LSE
    matches = _get(f"search/{query}")
    if not matches:
        raise MarketDataError(f"EODHD found nothing for '{query}'. Try the ISIN or the exact name.")
    if ISIN_PATTERN.match(query.upper()):
        # Several listings can share an ISIN; prefer the exact ISIN, then the fund listing
        exact = [m for m in matches if str(m.get("ISIN", "")).upper() == query.upper()] or matches
        matches = sorted(exact, key=lambda m: m.get("Exchange") != "EUFUND")
    best = matches[0]
    return f"{best['Code']}.{best['Exchange']}", best.get("Name", best["Code"]), best.get("Currency", "")


def monthly_prices(symbol: str, start: pd.Timestamp) -> pd.Series:
    """ Month-end adjusted closes (dividends added back) from the daily history """
    rows = _get(f"eod/{symbol}", **{"from": f"{start:%Y-%m-%d}", "period": "d"})
    if not rows:
        raise MarketDataError(f"EODHD returned no prices for {symbol}.")
    df = pd.DataFrame(rows)
    price = df["adjusted_close"] if "adjusted_close" in df else df["close"]
    series = pd.Series(pd.to_numeric(price, errors="coerce").values, index=pd.to_datetime(df["date"])).dropna()
    monthly = series.sort_index().resample("ME").last().dropna()
    # The current month is not finished yet, so its month-end would be in the future
    return monthly[monthly.index <= pd.Timestamp.today().normalize()]


def fetch_nav(fund: str, benchmark: str, years: int = 5) -> tuple[pd.DataFrame, str]:
    """ NAV table in the app's format (date, fund, benchmark) plus a note on what was fetched """
    if not api_key():
        raise MarketDataError("EODHD_API_KEY is not set, so prices cannot be downloaded.")
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years, months=1)
    fund_symbol, fund_name, fund_ccy = resolve(fund)
    bench_symbol, bench_name, bench_ccy = resolve(benchmark)
    if fund_symbol == bench_symbol:
        raise MarketDataError("The fund and benchmark matched the same listing. Use the benchmark's ticker.")
    nav = pd.concat({"fund": monthly_prices(fund_symbol, start), "benchmark": monthly_prices(bench_symbol, start)},
                    axis=1).dropna()
    if len(nav) < 3:
        raise MarketDataError("Fewer than 3 months of overlapping prices; check the fund and benchmark.")
    nav = (nav / nav.iloc[0] * 100).rename_axis("date").reset_index()
    note = f"Prices from EODHD: {fund_name} ({fund_symbol}) vs {bench_name} ({bench_symbol}), {len(nav)} months"
    # GBX (pence) and GBP are the same currency
    same = {c.upper().replace("GBX", "GBP") for c in (fund_ccy, bench_ccy) if c}
    if len(same) > 1:
        note += f". Currencies differ ({fund_ccy} vs {bench_ccy}), so returns include currency moves"
    return nav, note
