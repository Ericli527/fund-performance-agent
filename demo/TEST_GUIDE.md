# Fund Oversight Agent: Test Guide

Click a demo under the upload box, then **Analyse**. One run takes about 1-2 minutes.
All figures, ratings and the verdict come from code, so for demos D and F they must match this guide
**exactly**. If the AI's text quotes a number that is not in the report's tables, note it as a fail.

---

## Demo F: Sample fund, offline (the backup demo)

Fictional data from files only, so it works without an EODHD subscription.

**Files:** `nav_with_peer.csv` (fund, benchmark and peer prices), `attribution_12m.csv`,
`fund_facts.csv`, `peer.csv`, `manager_commentary_Q3_2026.docx`

### Expected: status list
- [ ] 5 files read, including "NAV series with peer prices (85 rows)"
- [ ] "Mandate: actively managed fund"
- [ ] "Peer prices for Sample World Index Tracker taken from the NAV file (85 months)"
- [ ] "Scorecard (rules in code): Mandate Green, Performance Amber, Value for investors Green, Fees Green. Draft verdict: **Monitor**."

### Expected: page 1 scorecard
| Question | Rating | Evidence (must match) |
|---|---|---|
| Mandate | **Green** | Excess return vs benchmark **+1.53%** (5Y p.a.) |
| Performance | **Amber** | 1Y return **10.33%** vs benchmark **12.51%** (**-2.18%**) |
| Value for investors | **Green** | Sharpe ratio **0.54** vs peer **0.51** (Sep 2019 to Sep 2026) |
| Fees | **Green** | Fee **0.65%** vs peer **0.12%**: higher, but the return after fees was higher (gap **+0.91%** a year) |

**The story:** the fund has delivered over five years and its higher fee paid for itself, but it
lagged its benchmark over the last 12 months, so the verdict is **Monitor**, not Retain.

### Expected: page 2
- Returns: 1Y 10.33% vs 12.51%; 3Y p.a. 19.17% vs 17.28%; 5Y p.a. 16.07% vs 14.54%
- Risk (full period): volatility 18.48% vs 17.68%; maximum fall -38.19% vs -35.79%
- **Attribution (12 months to 30 Sep 2026):** allocation **+0.80%**, selection **-2.95%**,
  interaction **-0.03%**, active return **-2.18%**, the same as the 1-year shortfall
- Added most: Energy. Took most away: Information Technology, Financials

### Expected: page 3
- Fund 9.89% a year vs peer 8.98% a year; fees on £10,000 over 5 years: **£325** vs **£60**
- "Did the extra fee pay for itself? **Yes**"
- The rating rules and sources are listed

### Expected: the AI's text
- [ ] Explains Monitor as long-term delivery but recent underperformance
- [ ] Uses the attribution: right sectors (allocation +0.80%), wrong stocks (selection -2.95%)
- [ ] Links this to the manager commentary: the early-2026 sell-off in quality-growth stocks,
      and Litware Bank in financials
- [ ] Does **not** change any rating or invent figures

---

## Demo D: Fidelity S&P 500, official figures (no EODHD needed)

**Files:** `fund_facts.csv` and `performance.csv` copied from Fidelity's factsheet (P USD Acc, 30 Sep 2026),
`peer.csv`. The peer's returns (State Street SPDR S&P 500 UCITS ETF (Dist), 0.03%) are in the `peer` column
of `performance.csv`; check them against the SSGA factsheet.

### Expected: status list
- [ ] "performance.csv: read as official performance with peer returns (12 periods)"
- [ ] "Using the fund manager's official performance figures (Official figures to 30 Sep 2026)"
- [ ] "Scorecard (rules in code): Mandate Green, Performance Green, Value for investors Amber, Fees Amber. Draft verdict: **Monitor**."

### Expected: page 1 scorecard
| Question | Rating | Evidence (must match) |
|---|---|---|
| Mandate | **Green** | Tracking difference **+0.00%** (5Y p.a., official figures) |
| Performance | **Green** | 1-year return **15.30%** vs index **15.30%** |
| Value for investors | **Amber** | Return after fees **13.30%** vs peer **13.48%** (5Y p.a.; gap **-0.18%** a year) |
| Fees | **Amber** | Fee **0.06%** vs peer **0.03%**; return after fees lower |

**The story:** the fund tracks its index exactly, so the mandate is met. But a cheaper peer that tracks the
same index returned 0.18% a year more over five years, so the verdict is **Monitor**, not Retain.

### Expected: pages 2 and 3
- Returns by period and calendar years 2021-2025 from the factsheet, with a calendar-year chart
- Fees on £10,000 over 5 years: **£30** vs **£15**; "Did the extra fee pay for itself? **No**"

### The AI's text
- [ ] Says the figures are the fund manager's official, reported returns
- [ ] Quotes the peer fee as **0.03%** (not any other number)

### Optional: let the AI read the factsheet
Upload the Fidelity factsheet PDF and `peer.csv` only. The Extractor Agent should read the same
1-, 3- and 5-year figures (labelled "AI-extracted, please verify"). Value and fees are **Not assessed**
because the peer's returns are not in the upload.

---

## Demo E: Marlborough 8 (needs `EODHD_API_KEY`)

| Fund | Benchmark stand-in | Peer |
|---|---|---|
| IFSL Marlborough 8 Portfolio P Acc (`GB00B84KX912`, 0.65%) | Vanguard FTSE All-World (`VWRL.LSE`) | Vanguard LifeStrategy 80% Equity A Acc (`GB00B4PQW151`, 0.22%) |

Results depend on downloaded prices, so check the process rather than exact numbers:
- [ ] Status shows "Prices from EODHD: ..." with the right fund name, and the number of months
      (about 12 on a free plan means the history limit applies)
- [ ] The header shows the benchmark stand-in, and the evidence names the price period
- [ ] Peer prices downloaded; if not, Value and Fees say "Not assessed" with the reason
- [ ] Compare the 1-year return with the fund's own factsheet: it should be close. If not, prefer official figures

## Edge cases
| What to do | Expected |
|---|---|
| Demo E without `EODHD_API_KEY` | Prices skipped with a reason; verdict **Incomplete data** |
| Demo D files without `performance.csv`, with fund `IE00BYX5MX67` and benchmark `SXR8.XETRA` | An index fund far from a stand-in benchmark shows **Check data**, not Red |
| Upload only `fund_facts.csv` and `peer.csv` | Verdict **Incomplete data**; nothing crashes |
| Open the app in a private window with a wrong password | Login refused |

## Report back
Note **Pass / Fail** for each check. For any fail, send a screenshot of the status list and the PDF page.
