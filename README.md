---
title: fund_report_agent
app_file: app.py
sdk: gradio
sdk_version: 6.14.0
---

# Fund Report Agent

A multi-agent app that analyses a fund's **performance and attribution** from uploaded
data, adds market context from up to **5 web searches**, and delivers a **factsheet and
committee performance review** as a **PDF**, by **email** (PDF attached) and as a
**Pushover** notification with a short summary.

Built with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and Gradio.
Based on the structure of [Deep-Research-Agent](https://github.com/ericli527/Deep-Research-Agent).

## How it works

```
Question + uploaded files (Gradio UI)
   │
   ├─► market_data.py     (Python)  optional: downloads fund and benchmark prices from EODHD
   ├─► file_parser.py     (Python)  reads CSV / Excel / PDF / Word / text
   ├─► Extractor Agent    (LLM)     only if factsheet data is missing: reads it from documents
   ├─► calculator.py      (Python)  performance metrics + Brinson-Fachler attribution
   ├─► charts.py          (Python)  growth of 100 + attribution charts
   ├─► Planner Agent      (LLM)     plans up to 5 searches to explain the results
   ├─► Search Agent × ≤5  (LLM)     web search, run in parallel
   ├─► Writer Agent       (LLM)     key messages, committee action, section commentary
   ├─► report_builder.py  (Python)  report layout (HTML for the PDF, Markdown for app/email)
   ├─► pdf_builder.py     (Python)  HTML → PDF
   └─► Notify Agent       (LLM)     tools: send_email_tool (PDF attached), send_push_tool
```

### Report structure

Pages 1-2 follow the layout of a fund manager's monthly factsheet. Pages 3 onwards follow
investment committee reports: the conclusion first, then the evidence.

| Page | Content |
|---|---|
| 1. Factsheet | Product features, fund facts, benchmark description, objective, 12-month and calendar-year returns, cumulative chart, risk indicator (1-7) |
| 2. Factsheet | Top 10 holdings, sector and geographic exposure (donut charts), risk measures (volatility, Sharpe, alpha, beta, tracking error, information ratio, R²) |
| 3. Executive summary | Status rating, headline figures, key messages, returns by period (3M, 6M, 1Y, 3Y, 5Y, since start), top contributors and detractors, recommended committee action |
| 4. Performance and risk | Commentary, growth of 100 chart, drawdown chart, risk and return metrics |
| 5. Attribution | Commentary, summary of effects, attribution chart, full Brinson-Fachler table |
| 6. Context and appendix | Market context, outlook and risks to monitor, methodology, glossary, data sources, disclaimer |

Every page has a footer with the fund name, report date and page number.

### Design choices

- **Python does the maths, the LLM explains it.** All figures in the report come from
  pandas, so the LLM cannot make arithmetic mistakes. The writer is told not to invent numbers.
- **Search limit in code, not just the prompt.** The plan is cut to 5 searches even if the
  planner returns more.
- **Run context keeps files away from the LLM.** The PDF path is passed to the notify tools
  through the SDK's `RunContextWrapper`, so the model decides *what* to send but never handles the file.
- **Rule-based status, not an LLM opinion.** On track / Watch / Under review comes from a
  documented rule on annualised excess return, shown in the appendix.
- **Supplied data beats AI extraction.** CSV data is always used first. The extractor only
  fills gaps, its weights are checked (0-100%, total at most 105%), and anything it supplies is
  labelled "AI-extracted, please verify" in the PDF.
- **Graceful failures.** A failed search is skipped; email or push without settings is
  reported as "skipped" instead of crashing.

## Data formats

Column names are matched without regard to case. See `samples/` for examples.

**NAV / price series** (CSV or an Excel sheet), used for performance and risk metrics:

| date | fund | benchmark |
|---|---|---|
| 2024-09-30 | 100.00 | 100.00 |

Values are NAV, price or index levels (not returns). Daily, weekly, monthly or quarterly data are detected automatically.

**Attribution data**, used for Brinson-Fachler attribution:

| sector | fund_weight | benchmark_weight | fund_return | benchmark_return |
|---|---|---|---|---|
| Information Technology | 28.0 | 24.0 | 14.2 | 12.5 |

Use either percentages (weights sum to 100) or decimals (weights sum to 1) for all four columns.

**Top holdings** (`security, fund_weight, benchmark_weight`). The benchmark column is optional.

**Exposures** (`category, name, fund_weight, benchmark_weight`), with `category` set to `sector` or
`country`. Separate files with a `sector` or `country` column also work. If no sector file is given,
sector weights are taken from the attribution data.

**Fund facts** (`field, value`), e.g. Fund name, ISIN, Benchmark, Launch date, Ongoing charges,
Fund size, Risk indicator. If no risk indicator is given, it is estimated from volatility.

Weights can be in percent or decimals.

**Documents** (PDF, Word, text, or any unrecognised table) are passed to the writer as reference.
If fund facts, holdings or exposures are missing, the Extractor Agent tries to read them from
these documents (for example, an existing factsheet or KID).

## One-click demos

Under the upload box, **Try a demo** has three buttons that load a question and fictional files
from `demo/`:

| Demo | Files | Shows |
|---|---|---|
| A · Full data + manager commentary | NAV, attribution, holdings, exposures, fund facts, a Word commentary | The full factsheet and review, with the AI using the manager's commentary |
| B · AI reads a factsheet PDF | NAV, attribution, a factsheet PDF | The Extractor Agent filling gaps from a PDF, with "please verify" labels |
| C · Attribution data only | Attribution | A report built from partial data |

`demo/TEST_GUIDE.md` lists the exact figures each demo should produce and what to check.

## Testing with a real fund

### Option 1: download prices in the app (EODHD)

Set `EODHD_API_KEY` (from [eodhd.com](https://eodhd.com)) in `.env` or in Render's Environment
settings. Then type the fund's ISIN or ticker and a benchmark ticker in the app, for example
`GB00B5L8VH15` and `IUKD.LSE`. The app downloads daily prices (dividends added back), takes
month-ends and uses them as the NAV series. An uploaded NAV file takes priority. EODHD covers many
UK unit trusts and OEICs that Yahoo does not; its free plan has a daily request limit and may
only include about a year of history, so a paid plan is needed for 3-5 year reports.

### Option 2: build a NAV file with the script

`tools/fetch_nav.py` downloads monthly prices for a real fund and a benchmark from Yahoo Finance
and saves a NAV CSV in the format above. Run it on your own computer:

```bash
pip install yfinance
python tools/fetch_nav.py --search "Marlborough Multi Cap Income"   # find the ticker
python tools/fetch_nav.py --fund "Marlborough Multi Cap Income" --benchmark "Vanguard FTSE UK Equity Income" --years 5
```

`--fund` and `--benchmark` take a Yahoo ticker, a name or an ISIN (Yahoo often cannot find UK
funds by ISIN, so names or tickers work better). The script prints what it
matched, so check it found the right share class. Then upload `nav_real.csv` with the fund's
latest factsheet PDF: the Extractor Agent reads the fund facts, holdings and exposures from it.

If Yahoo does not have the fund (common for UK unit trusts and OEICs), save its price history
as a CSV with a date column and a price column, for example from the historical prices table on
markets.ft.com, and pass it with `--fund-csv` instead of `--fund`:

```bash
python tools/fetch_nav.py --fund-csv fund_prices.csv --benchmark IUKD.L --years 5
```

Peer-group benchmarks (IA sectors) are not on Yahoo, so use an index tracker as a proxy and say
so in the report. Attribution needs sector returns for the fund, which are rarely public, so
real-fund reports usually skip that section.

## Metrics

- Total and annualised return, annualised volatility, Sharpe ratio, max drawdown
- Excess return, tracking error, information ratio, beta
- Allocation, selection and interaction effects by segment (Brinson-Fachler)

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY (email and Pushover are optional)
python app.py
```

Upload the files in `samples/` to try it.

## Deploy on Render

1. In the [Render dashboard](https://dashboard.render.com), choose **New > Blueprint** and pick this repo.
   Render reads `render.yaml` (free web service, `pip install -r requirements.txt`, `python app.py`).
2. Fill in the secrets it asks for. `OPENAI_API_KEY` is required; `EODHD_API_KEY` enables price downloads. Set `APP_USERNAME` and
   `APP_PASSWORD` to put a login in front of the app. Email and Pushover are optional:
   `EMAIL_ADDRESS`, `EMAIL_SMTP_SERVER` and `EMAIL_APP_PASSWORD` are the sending account, and
   `EMAIL_TO` lists where reports go (blank sends them to the sending account).
3. Click **Apply**. Every push to `main` then redeploys automatically.

Keys live in Render's environment settings, never in the repo. The free plan sleeps after
about 15 minutes without traffic, so the first visit afterwards takes a minute to wake up.

> Uploaded data is sent to OpenAI. Do not upload confidential client data.
> Reports are for demonstration only and are not investment advice.
