---
title: fund_oversight_agent
app_file: app.py
sdk: gradio
sdk_version: 6.14.0
---

# Fund Oversight Agent

A multi-agent app that drafts a 3-page **investment oversight report**: is a fund doing what it
promised, how did it do against its benchmark, did investors get good value, and is its fee
justified against a peer? It gives a draft **Retain / Monitor / Review** verdict for a person to
approve, and delivers the report as a **PDF**, by **email** (PDF attached) and as a **Pushover**
notification.

Built with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and Gradio.

**Code does the maths, AI does the reading and writing, and a person makes the call.**

## How it works

```
Question + files (fund facts, official performance, peer, prices, documents) + optional fund ISIN and benchmark
   │
   ├─► file_parser.py     (Python)  reads CSV / Excel / PDF / Word / text
   ├─► market_data.py     (Python)  prices from EODHD, if a fund ISIN or ticker is given (fallback)
   ├─► Extractor Agent    (LLM)     reads fund facts and reported performance from a factsheet, if no file has them
   ├─► analysis.py        (Python)  official returns first, else returns from prices; risk, attribution, charts
   ├─► Mandate Agent      (LLM)     what the fund promises; index or active fund
   ├─► oversight.py       (Python)  peer comparison and the scorecard, by fixed rules
   ├─► Planner Agent      (LLM)     plans up to 5 web searches
   ├─► Search Agent × ≤5  (LLM)     web search, run in parallel
   ├─► Oversight Analyst  (LLM)     explains the ratings (it cannot change them)
   ├─► oversight_builder  (Python)  3-page report → PDF
   └─► Notify Agent       (LLM)     tools: send_email_tool (PDF attached), send_push_tool
```

### The scorecard (rules in `oversight.py`, printed in every report)

| Question | Index fund | Active fund |
|---|---|---|
| **Mandate:** is it doing what it promised? | Tracking difference over up to 5 years (0.30 / 0.75 pp a year) | Excess return over up to 5 years (0% / -1% a year) |
| **Performance** vs benchmark | 1-year tracking difference (official figures), or tracking error from prices (1% / 2%) | 1-year excess return (0% / -3%) |
| **Value for investors** | Return after fees vs the peer's, longest common period (equal / within 0.50% a year); with prices only, Sharpe ratio (equal / within 0.10) | same |
| **Is the fee justified?** | Fee vs the peer's | A higher fee is justified if the return after fees was higher; up to 1% a year behind = Amber |

Any Red gives **Review**; any Amber, Not assessed or Check data gives **Monitor**; otherwise
**Retain**. Fewer than two rated questions gives **Incomplete data**. The verdict is always a draft
with a human approval box.

**Official figures first.** Oversight teams judge a fund on the returns its manager reports against
its official benchmark, so a performance file (or a factsheet the Extractor reads) is used before
anything calculated from prices. **Data check:** for an index fund rated on downloaded prices only,
a result outside the Green limit is shown as **Check data**, not Red. Downloaded fund and benchmark
prices are often taken at different times of day, which can make a good tracker look poor.

### The report

| Page | Contents |
|---|---|
| 1. Summary | Draft verdict, scorecard (rating, calculated evidence, plain-English assessment), key findings, actions, approval box |
| 2. Mandate and performance | Objective and commitments, returns by period, risk, attribution by sector (when supplied), growth chart |
| 3. Value and fees | Fund vs peer (fee, return, volatility, Sharpe), fee cost on £10,000, whether the extra fee paid for itself, market context, what would change the view, rules and sources |

### Design choices

- **Official data beats calculated data.** Reported returns are used before prices, and a result
  that looks wrong for an index fund is flagged for checking, not rated.
- **Python decides, the LLM explains.** All figures, ratings and the verdict come from code, so
  the same data always gives the same answer. The Oversight Analyst is told the ratings are final.
- **A person approves.** The verdict is a draft; the report has an approval box.
- **Supplied data beats AI extraction.** The Extractor Agent only fills gaps, and what it supplies
  is labelled "AI-extracted, please verify".
- **Graceful failures.** A missing key, price or peer becomes "Not assessed" or a status note, not
  a crash. Email and push failures return a reason and are not retried.
- **Run context keeps files away from the LLM.** The PDF path reaches the email tool through the
  SDK's `RunContextWrapper`; recipients come from settings, never from the model.

## Inputs

| File | Columns | Notes |
|---|---|---|
| Fund facts | `field, value` | Fund name, Benchmark, Management approach, **Ongoing charges**, Objective, Investment policy |
| Official performance | `period, fund, benchmark[, peer, as_of, source]` | Returns in percent from the factsheet, e.g. `1Y`, `3Y p.a.`, `5Y p.a.`, `2025`. The `peer` column holds the peer's reported returns. **Best source** |
| Peer | `peer, ticker, ocf` | One peer; `ocf` in percent (e.g. `0.22`). Prices from EODHD by ticker or ISIN if no peer returns are given |
| NAV / prices | `date, fund, benchmark[, peer]` | Optional. A `peer` column supplies peer prices without EODHD |
| Attribution | `sector, fund_weight, benchmark_weight, fund_return, benchmark_return[, period]` | Optional; explains why the fund beat or lagged its benchmark |
| Documents | PDF, Word, text | Factsheets, KIDs, manager commentary |

Templates are in `samples/`. Weights and returns can be in percent or decimals.

## One-click demos

| Demo | Data | Needs |
|---|---|---|
| D · Fidelity S&P 500 (index fund) | Official figures from Fidelity's 30 Sep 2026 factsheet (P USD Acc); peer State Street SPDR S&P 500 UCITS ETF (0.03%) with its reported returns | Nothing extra |
| E · Marlborough 8 (active fund) | Fund facts; peer Vanguard LifeStrategy 80% (0.22%); prices from EODHD | `EODHD_API_KEY` |
| F · Sample fund, offline (backup) | Fictional fund, peer and attribution, all from files | Nothing extra |

Figures for D and E come from public sources noted in the files; check the factsheets and KIDs
before relying on them. `demo/TEST_GUIDE.md` lists the expected results for demo F and what to check for D and E.

## Real fund data

**Official figures (recommended):** download the fund's monthly factsheet from the fund manager's
website and either upload the PDF (the Extractor Agent reads the performance table, labelled "please
verify") or copy the 1-, 3- and 5-year and calendar-year returns into a performance CSV (two
minutes; template in `samples/performance_sample.csv`). Do the same for the peer, and put its
returns in the `peer` column. In a firm, the same figures come from Morningstar, FE fundinfo,
Bloomberg or the fund administrator.

**Prices from EODHD (fallback):** set `EODHD_API_KEY` ([eodhd.com](https://eodhd.com)), then type the fund's
ISIN or ticker and a benchmark ticker (e.g. `GB00B84KX912` and `VWRL.LSE`). The app downloads daily
prices (dividends added back) and uses month-ends. EODHD covers many UK funds that Yahoo does not;
its free plan has a daily request limit (each review uses about 4-6) and may only include about a
year of history.

**With the script:** `tools/fetch_nav.py` builds a NAV CSV from Yahoo Finance, or from a price CSV
saved from another source such as markets.ft.com:

```bash
pip install yfinance
python tools/fetch_nav.py --search "Marlborough Multi Cap Income"   # find the ticker
python tools/fetch_nav.py --fund-csv fund_prices.csv --benchmark IUKD.L --years 5
```

Peer-group benchmarks (IA sectors) are not freely available, so use an index tracker as a stand-in
and say so. Sector attribution needs the fund's sector returns, which are rarely public.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY (EODHD, email and Pushover are optional)
python app.py
```

Click **Demo D** or **Demo F** to try it without any data subscription.

## Deploy on Render

1. In the [Render dashboard](https://dashboard.render.com), choose **New > Blueprint** and pick this repo.
   Render reads `render.yaml` (free web service, `pip install -r requirements.txt`, `python app.py`).
2. Fill in the secrets it asks for. `OPENAI_API_KEY` is required; `EODHD_API_KEY` enables price
   downloads. Set `APP_USERNAME` and `APP_PASSWORD` to put a login in front of the app.
   For email on Render, use **Resend** (`RESEND_API_KEY`, `EMAIL_TO`, optionally `EMAIL_FROM`):
   Render's free plan blocks SMTP ports, while Resend sends over HTTPS. Resend's test sender only
   delivers to the address you signed up with. SMTP settings are used when no Resend key is set.
3. Click **Apply**. Every push to `main` then redeploys automatically.

The free plan sleeps after about 15 minutes without traffic, so open the app a minute before a demo.

> Uploaded data is sent to OpenAI. Do not upload confidential client data.
> Reports are drafts for demonstration only and are not investment advice.
