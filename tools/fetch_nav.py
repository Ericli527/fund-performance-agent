"""
Download monthly price history for a fund and its benchmark from Yahoo Finance and
save it as a NAV CSV the app can read (date, fund, benchmark).

Run on your own computer (needs internet access):

    pip install yfinance
    python tools/fetch_nav.py --search "Marlborough Multi Cap Income"   # find the ticker
python tools/fetch_nav.py --fund "Marlborough Multi Cap Income" --benchmark "Vanguard FTSE UK Equity Income" --years 5

--fund and --benchmark accept a Yahoo ticker (e.g. VUKG.L), an ISIN or a name. ISINs and names
are looked up and the best match is used; check the printed match is the share class you meant.
Yahoo often cannot find UK funds by ISIN, so a name usually works better. To see matches only:

    python tools/fetch_nav.py --search "Marlborough Multi Cap Income"
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
    parser.add_argument("--benchmark", help="Benchmark index or ETF ticker, ISIN or name")
    parser.add_argument("--years", type=int, default=5, help="Years of history (default 5)")
    parser.add_argument("--out", default="nav_real.csv", help="Output CSV (default nav_real.csv)")
    args = parser.parse_args()
    if args.search:
        if not search(args.search):
            print(f"No matches for '{args.search}'. Try a shorter name.")
        return
    if not args.fund or not args.benchmark:
        parser.error("--fund and --benchmark are both needed (or use --search to look up a name)")

    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=args.years, months=1)
    fund_ticker, fund_name = resolve(args.fund)
    bench_ticker, bench_name = resolve(args.benchmark)
    print(f"\nFund:      {fund_ticker}  ({fund_name})")
    print(f"Benchmark: {bench_ticker}  ({bench_name})")
    if fund_ticker == bench_ticker:
        sys.exit("The fund and benchmark matched the same ticker. Pass the benchmark's Yahoo ticker instead.")

    fund_ccy = yf.Ticker(fund_ticker).fast_info.get("currency")
    bench_ccy = yf.Ticker(bench_ticker).fast_info.get("currency")
    if fund_ccy and bench_ccy and fund_ccy.upper() != bench_ccy.upper():
        print(f"Warning: currencies differ ({fund_ccy} vs {bench_ccy}), so returns include currency moves.")

    nav = build_nav(monthly_prices(fund_ticker, start), monthly_prices(bench_ticker, start))
    # The latest month is usually incomplete, so drop it unless it is a month end
    if pd.Timestamp(nav["date"].iloc[-1]) > pd.Timestamp.today().normalize():
        nav = nav.iloc[:-1]
    nav.to_csv(args.out, index=False)
    print(f"\nSaved {len(nav)} months ({nav['date'].iloc[0]} to {nav['date'].iloc[-1]}) to {args.out}")
    print("Upload it in the app together with the fund's latest factsheet PDF.")


if __name__ == "__main__":
    main()
