# Synthetic financial regression fixture

All inputs here are invented, contain no real fund history or confidential data, and are independent of
`data/test1/`. Do not use production calculation outputs to regenerate expected results.

`prices.csv` has 61 month-end observations, December 2020–December 2025. NAV is exactly 100 + month number.
The profile launches on the first observation. Expected arithmetic (percent unless stated):

| Measure | Independent derivation | Expected |
|---|---|---|
| 1-year cumulative | (160/148 − 1) × 100 | 8.108108108108 |
| 3-year cumulative | (160/124 − 1) × 100 | 29.032258064516 |
| 5-year cumulative | (160/100 − 1) × 100 | 60 |
| 3-year annualised | ((160/124)^(1/3) − 1) × 100 | 8.867796417793 |
| 5-year annualised | ((160/100)^(1/5) − 1) × 100 | 9.856054330612 |
| 5-year volatility | Sample standard deviation of 1/100,…,1/159 × √12 × 100 | 0.375587684024 |
| Maximum drawdown | Prices always increase | 0 |

Annual returns are 12 divided by the preceding December NAV (100,112,124,136,148), times 100.
CAGR constants were checked with Python's standard-library Decimal at 40-digit precision; volatility with
statistics.stdev and math.sqrt, without importing application code.

The fictional factsheet deliberately provides rounded NAV returns and separate market-close figures:
75% fund PNAV vs 76% index over five years, and published annualised figures of 12% vs 12.1%.
These are intentionally distinct from annualising the cumulative figures, to prove published annualised figures
win. Thus fair cumulative gap = −1 pp, annualised gap = −0.1 pp, cost-adjusted gap = 0 with OCF 0.1%.
NAV risk 9% and PNAV risk 8% must remain separate. TE 0.02%, beta/R² 1 produce Green mandate/performance;
abs(TD) 0.1 <= OCF + 0.1 = 0.2. Without peers the verdict is Monitor until a peer is added.

Tests copy these files into temporary directories for variations:
- Published fund annualised return 9% gives TD −3.1 pp, beyond the 0.4 pp Amber limit: Action needed.
- Missing TE gives CHECK DATA and Pending data check, not a fabricated zero.
- File index twice NAV gives 2025 return 8.108%, inconsistent with the fictional 20% factsheet index:
  blocking currency mismatch and Pending data check.
- A 10,000 pre-launch price cannot alter post-launch risk/returns.
- Missing March NAV in a four-row CSV and generated XLSX invalidates both adjacent monthly returns.
- Official 1-year NAV return 10% against calculated 8.108% retains a cross-check warning and official precedence.

The currency-mismatch controller run exposes an existing six-page PDF overflow. Its financial assertions run
before asserting the explicit RunStopped layout guard. No renderer is mocked and no financial assertion is
relaxed. This layout limitation belongs to Stage 3; when fixed, change that expectation to successful rendering.
