"""
Download monthly price history for a fund and its benchmark from Yahoo Finance and
save it as a NAV CSV the app can read (date, fund, benchmark).

Run on your own computer (needs internet access):

    pip install yfinance
    python tools/fetch_nav.py --search "Marlborough Multi Cap Income"   # find the ticker
    python tools/fetch_nav.py --fund "Marlborough Multi Cap Income" --benchmark "Vanguard FTSE UK Equity Income" --years 5

--fund and --benchmark accept a Yahoo ticker (e.g. VUKG.L), a name or an ISIN, and print what
they matched; check it is the share class you meant. Yahoo often cannot find UK funds by ISIN,
so a name or ticker usually works better.

If Yahoo does not have the fund at all, save its price history as a CSV (any source, e.g. the
historical prices table on markets.ft.com pasted into Excel) with a date column and a price
column, and pass it instead of --fund:

    python tools/fetch_nav.py --fund-csv marlborough_prices.csv --benchmark IUKD.L --years 5
"""
import argparse
import re
import sys
import pandas as pd
import yfinance as yf


ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def search(query: str) -> list[dict]:
    """ Yahoo search results, printed so the user can check or pick a ticker """
    try:
        quotes = yf.Search(query, max_results=10, news_count=0, enable_fuzzy_query=True).quotes
    except Exception as e:
        sys.exit(f"Yahoo Finance search failed ({e}). Check your internet connection and try again.")
    if quotes:
        print(f"\nMatches for '{query}':")
        for q in quotes:
            print(f"  {q.get('symbol', ''):<16} {q.get('quoteType', ''):<11} {q.get('longname') or q.get('shortname', '')}")
    return quotes


def resolve(query: str) -> tuple[str, str]:
    """ Turn a ticker, ISIN or name into a Yahoo ticker """
    looks_like_ticker = " " not in query.strip() and not ISIN_PATTERN.match(query.upper())
    if looks_like_ticker:
        try:
            if not yf.Ticker(query).history(period="5d").empty:
                return query, query
        except Exception:
            pass
    quotes = search(query)
    if not quotes:
        hint = ("Yahoo often cannot find UK funds by ISIN. Try the fund name instead, e.g. "
                '--fund "Marlborough Multi Cap Income", or look up its ticker (like 0P0000XXXX.L) '
                "on finance.yahoo.com.") if ISIN_PATTERN.match(query.upper()) else (
                "Try a shorter name, or look up the ticker on finance.yahoo.com.")
        sys.exit(f"No Yahoo Finance match for '{query}'. {hint}")
    best = quotes[0]
    return best["symbol"], best.get("longname") or best.get("shortname") or best["symbol"]


def monthly_prices(ticker: str, start: pd.Timestamp) -> pd.Series:
    """ Month-end prices; auto_adjust adds dividends back for income share classes """
    df = yf.download(ticker, start=start, interval="1d", auto_adjust=True, progress=False, multi_level_index=False)
    if df.empty:
        sys.exit(f"No price history for {ticker}.")
    return df["Close"].dropna().resample("ME").last()


PRICE_WORDS = ("nav", "price", "close", "mid", "bid", "value")


def csv_prices(path: str, start: pd.Timestamp) -> pd.Series:
    """ Month-end prices from a user's CSV: finds the date column and the price column """
    try:
        df = pd.read_csv(path)
    except Exception as e:
        sys.exit(f"Could not read {path} ({e}).")
    dates = None
    for col in df.columns:
        parsed = pd.to_datetime(df[col], errors="coerce", dayfirst=True, format="mixed")
        if parsed.notna().mean() > 0.8:
            dates, date_col = parsed, col
            break
    if dates is None:
        sys.exit(f"No date column found in {path}.")
    numeric = {c: pd.to_numeric(df[c].astype(str).str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
               for c in df.columns if c != date_col}
    numeric = {c: v for c, v in numeric.items() if v.notna().mean() > 0.8}
    if not numeric:
        sys.exit(f"No price column found in {path}.")
    named = [c for c in numeric if any(w in str(c).lower() for w in PRICE_WORDS)]
    price_col = named[0] if named else next(iter(numeric))
    print(f"Read {path}: dates from '{date_col}', prices from '{price_col}'")
    prices = pd.Series(numeric[price_col].values, index=dates).dropna().sort_index()
    prices = prices[prices.index >= start - pd.DateOffset(months=1)]
    return prices.resample("ME").last().dropna()


def build_nav(fund: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """ Keep months both series cover, rebased to 100 so the levels are easy to compare """
    nav = pd.concat({"fund": fund, "benchmark": benchmark}, axis=1).dropna()
    nav = nav / nav.iloc[0] * 100
    nav.index.name = "date"
    return nav.round(4).reset_index().assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--search", help="Only list Yahoo matches for a name, then stop")
    parser.add_argument("--fund", help="Fund ticker, ISIN or name")
    parser.add_argument("--fund-csv", help="CSV of the fund's prices, for funds Yahoo does not have")
    parser.add_argument("--benchmark", help="Benchmark index or ETF ticker, ISIN or name")
    parser.add_argument("--years", type=int, default=5, help="Years of history (default 5)")
    parser.add_argument("--out", default="nav_real.csv", help="Output CSV (default nav_real.csv)")
    args = parser.parse_args()
    if args.search:
        if not search(args.search):
            print(f"No matches for '{args.search}'. Try a shorter name.")
        return
    if not (args.fund or args.fund_csv) or not args.benchmark:
        parser.error("--benchmark and one of --fund or --fund-csv are needed (or use --search to look up a name)")

    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=args.years, months=1)
    bench_ticker, bench_name = resolve(args.benchmark)
    if args.fund_csv:
        fund = csv_prices(args.fund_csv, start)
        print(f"\nFund:      prices from {args.fund_csv}")
        print(f"Benchmark: {bench_ticker}  ({bench_name})")
        print("Check the fund prices and the benchmark are in the same currency.")
    else:
        fund_ticker, fund_name = resolve(args.fund)
        print(f"\nFund:      {fund_ticker}  ({fund_name})")
        print(f"Benchmark: {bench_ticker}  ({bench_name})")
        if fund_ticker == bench_ticker:
            sys.exit("The fund and benchmark matched the same ticker. Pass the benchmark's Yahoo ticker instead.")
        fund_ccy = yf.Ticker(fund_ticker).fast_info.get("currency")
        bench_ccy = yf.Ticker(bench_ticker).fast_info.get("currency")
        if fund_ccy and bench_ccy and fund_ccy.upper() != bench_ccy.upper():
            print(f"Warning: currencies differ ({fund_ccy} vs {bench_ccy}), so returns include currency moves.")
        fund = monthly_prices(fund_ticker, start)

    nav = build_nav(fund, monthly_prices(bench_ticker, start))
    if len(nav) < 13:
        print(f"Warning: only {len(nav)} months overlap, so 1-year and longer figures will be missing.")
    # The latest month is usually incomplete, so drop it unless it is a month end
    if pd.Timestamp(nav["date"].iloc[-1]) > pd.Timestamp.today().normalize():
        nav = nav.iloc[:-1]
    nav.to_csv(args.out, index=False)
    print(f"\nSaved {len(nav)} months ({nav['date'].iloc[0]} to {nav['date'].iloc[-1]}) to {args.out}")
    print("Upload it in the app together with the fund's latest factsheet PDF.")


if __name__ == "__main__":
    main()
