# Fund Report Agent: Test Pack

All data and documents here are **fictional** ("Sample Global Equity Fund"), made for testing only.
Every figure in the tables below was calculated by the app's own Python code, so the PDF must match
them **exactly**. If the AI's text quotes a number that is not in these tables, note it as a fail.

Run each test in the app. The quickest way is the **Try a demo** buttons under the upload box:
**Demo A**, **Demo B** and **Demo C** load the question and files for Tests A, B and C2 below.
You can also upload the files from the `demo/` folders yourself. One run takes about 1-3 minutes.

---

## Test A: Full data (the main demo)

**Upload all 6 files in `test_A_full_data/`:**
`nav_sample.csv`, `attribution_sample.csv`, `holdings_sample.csv`, `exposures_sample.csv`,
`fund_facts_sample.csv`, `manager_commentary_Q3_2026.docx`

**Question:**
> Analyse the Sample Global Equity Fund's performance and attribution against the MSCI World over the period, and explain why it lagged over the last 12 months.

**Leave the ISIN and benchmark boxes empty.**

### Expected: status list
- [ ] 6 files read (NAV 85 rows, attribution 8 segments, holdings 10 rows, fund facts 13 items, exposure data, document)
- [ ] **No** "extracting from documents" step (all factsheet data came from the CSVs)
- [ ] "Running **5** searches" (or fewer), then PDF created, then email and push lines

### Expected: PDF, 6 pages
| Page | Check |
|---|---|
| 1 | Header "Sample Global Equity Fund", fund facts incl. **Fund size GBP 412.6m**, risk indicator **6** with the note "Estimated from up to 5 years of fund volatility" |
| 2 | Top holding **Northwind Semiconductors 6.2**, top 10 total **30.8**, sector source "attribution data", country **United States 68.5** |
| 3 | Executive summary with two badges: **Last 1 year: UNDER REVIEW** and **Since start: ON TRACK** |
| 4-6 | Performance, risk, attribution, market context, outlook, appendix with glossary |

### Expected: key figures (all must match)
| Figure | Fund | Benchmark | Relative |
|---|---|---|---|
| Total return (30 Sep 2019 to 30 Sep 2026) | **93.51%** | **83.93%** | |
| 3M | -1.18% | 0.59% | -1.77% |
| 6M | 16.51% | 17.27% | -0.76% |
| 1Y | **10.33%** | **12.51%** | **-2.18%** |
| 3Y p.a. | 19.17% | 17.28% | +1.90% |
| 5Y p.a. | 16.07% | 14.54% | +1.53% |
| Since start p.a. | 9.89% | 9.09% | **+0.79%** |
| Max drawdown | -38.19% | -35.79% | |
| Tracking error / information ratio (full period, page 3 tile) | | | 2.72% / 0.29 |

**Calendar years (%), page 1:** 2020 -4.2 / -3.6 · 2021 -16.8 / -15.1 · 2022 12.9 / 12.0 · 2023 0.6 / 0.9 · 2024 19.8 / 15.5 · 2025 39.4 / 36.5 (fund / benchmark)

**Risk measures over 3 years, page 2:** volatility 18.0 / 17.6 · relative volatility 1.03 · Sharpe 1.06 / 0.98 · alpha 1.7 · beta **1.01** · tracking error 2.7 · information ratio 0.69 · R² **0.98**

**Attribution:** active return **+0.99%** = allocation +0.42% + selection +0.44% + interaction +0.14%
- Top contributors: **Information Technology +0.70%**, Consumer Discretionary +0.22%, Energy +0.14%
- Top detractors: Financials -0.10%, Industrials -0.05%, Utilities -0.03%

### Expected: the AI used the manager commentary
The commentary (Word file) says these things. At least some should appear in the key messages or commentary:
- [ ] The 12-month lag came from the **sharp sell-off in early 2026**, when rising bond yields hit **quality-growth** stocks
- [ ] **Litware Bank** / stock selection in financials held back returns
- [ ] Outlook is **cautious** (technology valuations, AI spending, concentration in technology)

### Expected: delivery
- [ ] Email arrives at your `EMAIL_TO` address, **from** your own mailbox, with the PDF attached (check spam the first time)
- [ ] Pushover shows the short summary

---

## Test B: AI extraction from a factsheet

**Upload the 3 files in `test_B_ai_extraction/`:**
`nav_sample.csv`, `attribution_sample.csv`, `sample_factsheet_Sep2026.pdf`

**Question:**
> Produce a factsheet and performance review for the Sample Global Equity Fund.

The factsheet PDF **differs from the CSVs on purpose**, so you can see where each number came from.

| Item | Expected in report | Why |
|---|---|---|
| Status list | "Some factsheet data is missing, extracting it from the documents..." | No holdings, country or fund-facts CSV was uploaded |
| Fund size | **GBP 418.3m** (orange "AI-extracted ... please verify" label) | Read from the PDF (the CSV says 412.6m) |
| Risk indicator | **5**, note "As stated in the fund documents" | The PDF states 5, so the app does not estimate 6 |
| Top holding | **Northwind Semiconductors 6.3** (orange label) | From the PDF (the CSV says 6.2) |
| Top 10 total | **30.7** | Sum of the PDF's weights |
| Countries | **United States 69.0** (orange label) | From the PDF |
| Sectors | **Information Technology 28.0**, source "attribution data" | Uploaded attribution data beats AI extraction (the PDF says 27.5) |
| Performance, risk, attribution | **Same as Test A** | Same NAV and attribution files |
| Appendix, data sources | A line saying some factsheet data was AI-extracted | |

- [ ] **Pass** if all rows match. If an extracted value is wrong (e.g. 6.2 instead of 6.3), the Extractor Agent misread the PDF.

---

## Test C: Edge cases (quick)

| # | What to do | Expected |
|---|---|---|
| C1 | **No files**, just ask "Analyse the fund" | Finishes without crashing. No status badges. Factsheet sections say no data was supplied, and the AI says the data is missing |
| C2 | Upload only `attribution_sample.csv` | One badge, **Attribution period: ON TRACK** (+0.99%). Page 3 tiles show allocation and selection. No performance tables |
| C3 | Upload `attribution_sample.csv` + `unrelated_table.csv` | Status says "unrelated_table.csv: table not recognised, used as a reference document". The extractor runs but finds nothing, so there are **no** orange labels |
| C4 | (Only if `EODHD_API_KEY` is set) type a fund ISIN but leave the benchmark box empty | Status says "Price download skipped: add a benchmark ticker as well as the fund." |
| C5 | Open the app in a private window and log in with a wrong password | Login refused |

---

## Report back
For each test, note **Pass / Fail**. For any fail, send a screenshot of the status list and the PDF page.
Also note how long a run took and the cost on platform.openai.com → Usage.
