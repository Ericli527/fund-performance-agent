# Fund Oversight Agent: Test Guide

Click a demo under the upload box, then **Analyse**. One run takes about 1-2 minutes.
All figures, ratings and the verdict come from code, so for demo F they must match this guide
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

## Demos D and E: real funds (need `EODHD_API_KEY`)

| Demo | Fund | Benchmark stand-in | Peer |
|---|---|---|---|
| D | Fidelity S&P 500 Index Fund P-ACC-EUR (`IE00BYX5MX67`, 0.06%) | iShares Core S&P 500 (`SXR8.XETRA`) | SPDR S&P 500 UCITS ETF Acc (`SPYL.XETRA`, 0.03%) |
| E | IFSL Marlborough 8 Portfolio P Acc (`GB00B84KX912`, 0.65%) | Vanguard FTSE All-World (`VWRL.LSE`) | Vanguard LifeStrategy 80% Equity A Acc (`GB00B4PQW151`, 0.22%) |

Results depend on live data, so check the process rather than exact numbers:
- [ ] Status shows "Prices from EODHD: ..." with the right fund name, and the number of months
      (about 12 on a free plan means the history limit applies)
- [ ] Peer prices downloaded; if not, Value and Fees say "Not assessed" with the reason
- [ ] **D** is treated as an index fund (tracking tests); **E** as an active fund (excess return tests)
- [ ] Compare the 1-year return with the fund's own factsheet: it should be close
- [ ] The verdict follows the printed rules

## Edge cases
| What to do | Expected |
|---|---|
| Demo D or E without `EODHD_API_KEY` | Prices skipped with a reason; verdict **Incomplete data** |
| Upload only `fund_facts.csv` and `peer.csv` | Verdict **Incomplete data**; nothing crashes |
| Open the app in a private window with a wrong password | Login refused |

## Report back
Note **Pass / Fail** for each check. For any fail, send a screenshot of the status list and the PDF page.
