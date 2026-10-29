# Results (build step 12)

Results of the Fund Performance Review agent on Test 1, the live AI runs that shaped the design, and the
comparison with Fidelity's own 2025 Value Assessment. The spec is `docs/FUND_PERFORMANCE_AGENT_SPEC.md`.

## Summary

- **Test 1 (Fidelity Index US Fund P Acc, figures to 30 Sep 2026): passed.** Every expected figure, flag and rating
  in spec Section 10 matches. Draft verdict: **Monitor until a peer is added** (Mandate Green, Performance Green,
  Value for investors and Fees Amber "Add peer").
- **Live AI runs: the last full run, through the web page, passed.** The findings, the actions and the Fidelity
  approved pages were all correct. Earlier runs found problems that led to the design changes listed below.
- **Comparison with Fidelity's 2025 Value Assessment: the conclusions are consistent.** The fund tracks its
  index closely and its fee is low. The draft verdict waits on a peer only because none was supplied.
- **Tests 2, 3 and 4 were not run:** their input files have not been supplied yet (see the end).
- **Automated tests:** 466 passed, 5 skipped (the live AI tests, run with `pytest --run-live`).

## Test 1: Fidelity Index US Fund P Acc (GB00BJS8SH10), figures to 30 Sep 2026

Inputs: monthly NAV CSV (Nov 2012 to Sep 2026), `fund_profile.json`, `factsheet_performance.json` (typed from the
factsheet), factsheet and KID PDFs. No peer file. Run offline (`--offline`) for the figures below; the ratings and
figures are the same in the AI runs, because code decides them.

### Figures: expected (spec Section 10) and reported

| Figure | Expected | Reported | Source |
|---|---|---|---|
| Fund NAV, cumulative 1 / 3 / 5 years | 17.5% / 69.0% / 88.3% | 17.5% / 69.0% / 88.3% | Factsheet |
| Fund NAV, 5 years, per year (annualised) | 13.5% | 13.5% | Factsheet |
| Fund PNAV vs index, cumulative 1 year | 17.0% vs 17.1% | 17.0% vs 17.1% | Factsheet |
| Fund PNAV vs index, cumulative 3 years | 69.0% vs 69.5% | 69.0% vs 69.5% | Factsheet |
| Fund PNAV vs index, cumulative 5 years | 90.9% vs 91.6% | 90.9% vs 91.6% | Factsheet |
| Fund PNAV vs index, 5 years, per year (annualised) | 13.8% vs about 13.9% | 13.8% vs 13.9% | Factsheet |
| Gap to index, cumulative 5 years | −0.7 pp | −0.7 pp | Calculated from the factsheet |
| Tracking difference, a year over 5 years | −0.10 pp | −0.10 pp | Calculated from the factsheet |
| Cost-adjusted tracking difference | −0.04 pp | −0.04 pp | Calculated |
| Hit rate (12-month windows within OCF + 0.10) | 5 of 5 | 5 of 5 | Calculated |
| Tracking error, 3 years | 0.02 | 0.02% | Factsheet |
| Beta, R², 3 years | 1.00, 1.00 | 1.00, 1.00 | Factsheet |
| Ongoing charge (OCF) | 0.06% | 0.06% | Factsheet / KID |
| NAV volatility, 3 years (cross-check) | 13.92% (factsheet) | 13.92% | Calculated |
| NAV volatility, 5 years | 13.7% | 13.7% | Calculated |
| Largest fall from a peak, 5 years | −15.1% | −15.1% | Calculated |

Cross-checks of the calculated NAV returns against the factsheet: +0.01, +0.04 and +0.03 pp for 1, 3 and 5 years
(all within 0.3 pp, so no flag; the factsheet figures are reported).

### Ratings and verdict

| Question | Rating | Reason (code) |
|---|---|---|
| Mandate | Green | R² 1.00 and beta 1.00 over 3 years (factsheet) |
| Performance | Green | Tracking difference −0.10 pp a year over 5 years (PNAV vs index), within OCF + 0.10 = 0.16; tracking error 0.02% over 3 years (factsheet) |
| Value for investors | Amber | Add peer: no comparison fund was supplied |
| Fees | Amber | Add peer: no comparison fund was supplied |

**Draft verdict: Monitor until a peer is added.** Performance was **not** rated Red from the noon NAV (88.3%
against the index's 91.6% over 5 years): the fair comparison uses the market-close price (PNAV).

### Data checks

All as expected in the spec:
- Dates read as MM/DD/YYYY. The trailing comma (an empty extra field) was removed from 167 rows.
- 16 prices before the share class launch (2014-03-03) are flagged "pre-launch (likely simulated)" (info). They are
  left out of risk statistics and since-launch figures.
- Repeated prices: on 2013-06-30 / 2013-08-31 and 2013-12-31 / 2014-02-28, info (pre-launch). On 2024-07-31 /
  2024-09-30, raised as a warning, then lowered to info as "checked against factsheet: consistent" (12 months to
  2024-09-30: 22.93% vs 22.9%; to 2025-09-30: 17.03% vs 17.0%).
- Noon pricing: the fund is priced at midday and the index at market close, so PNAV is used for the comparison
  (info).
- No risk-free rate supplied: the Sharpe ratio and alpha use 0% (info).
- Since-launch: calculated 515.8% vs factsheet 525.8%. The price file has no launch-day price, so the factsheet
  figure is used and the reason goes in the run log.

### Report

4 pages (Summary; Mandate and performance; Value, fees and Assessment of Value; Appendix), within the 5-page
limit. The code-written findings read:
1. Mandate is Green: the fund moves in line with its index (R² 1.00 and beta 1.00 over 3 years, factsheet).
   Performance is Green: the fund is 0.10% a year behind its index over 5 years, a tracking difference of −0.10 pp
   (percentage points) a year; tracking error is 0.02% (over 3 years, factsheet).
2. Its noon price makes it look 3.3 pp behind its index over 5 years. At market close (PNAV) the gap is only 0.7 pp.
3. Most of the yearly gap is the fee, the 0.06% yearly ongoing charge (OCF). With the fee added back, the fund is
   0.04% a year behind its index over 5 years.

Actions (code): add a comparable peer fund before the next quarterly review; record the decision and its reasons
in the approval box at this review.

## Comparison with Fidelity's 2025 Value Assessment

Fidelity's published Value Assessment is the answer key. It was never an input to the agent (CLAUDE.md rule 4);
it was compared with the results only after the runs. Its figures are to 30 Jun 2025 and ours to 30 Sep 2026, so the
numbers are close but not directly comparable.

| | Fidelity Value Assessment 2025 (to 30 Jun 2025) | This review (to 30 Sep 2026) |
|---|---|---|
| 5-year return, per year (annualised; fund vs index) | 13.93% vs 13.99% | 13.8% vs 13.9% (PNAV vs index) |
| Gap to the index | −0.06 pp a year | −0.10 pp a year (tracking difference) |
| Tracking error | 0.03 | 0.02% (3 years, factsheet) |
| Ongoing charge (OCF) | 0.06%, against a sector median of 0.10% | 0.06%; no peer supplied |
| Conclusion | Tracks its index closely; fee below the sector median | Mandate and Performance Green; Value and Fees wait for a peer |

**The conclusions are consistent.** Both find a fund that tracks its index closely, at a gap that the low fee
mostly explains, with a low fee.

**The one difference is the comparator.** Fidelity compares the fee with a sector median, while this review
needs a peer fund and has none, so Value and Fees are Amber "Add peer". With Fidelity's sector median as the
comparator, the fee is 0.04 pp below it; under the current illustrative thresholds (Green up to 0.05 pp above the
peer) code would rate Fees Green. Accepting a sector median OCF as the peer is on the v2 roadmap (spec Section 13).

## Alignment with IFSL Marlborough's 2025 Value Assessment

A second published Value Assessment, from IFSL Marlborough (the AFM of Test 3's fund), supports the same design.
Like Fidelity's, it was read only for comparison, never as an input.

- **Rating levels.** Marlborough rates each fund on 4 levels. They map onto this review's draft verdicts:

  | IFSL Marlborough rating | This review |
  |---|---|
  | Fees justified | Retain |
  | Fees justified, but targeting improvement | Monitor |
  | Requires improvement | Review |
  | Too soon to rate | Short history (since-launch figures; Performance at least Amber, never Red on history alone) |

- **Comparable market rates.** Marlborough's market-rates test compares each fund's OCF with the mean of its IA
  peer group. That supports the v2 roadmap item to accept a sector average as the peer (spec Section 13), as
  Fidelity also does with its sector median.
- **A person makes the final call.** Marlborough's US Focus Fund example shows that underperforming a comparator
  does not decide the rating on its own: the AFM weighs it with the other factors. That is why this agent gives a
  *draft* verdict from code, and a reviewer signs the final decision in the approval box.

## Live AI runs and what they changed

The runs are listed in order. Each found something that a mocked test could not, and each led to a design change
(all now covered by mocked tests).

| Run | What happened | What changed |
|---|---|---|
| 1. Research (step 8) | Passed; the AI text passed all checks. | Pages with only an "as at" date are kept. Sources about another fund or jurisdiction are excluded (Test 1: a US SEC filing). Each data note's key figure must appear in the findings. Market queries cover the whole period. Periods are written in words. |
| 2. First full run with approved sources (step 9b) | The Fidelity charges page was kept. The S&P DJI page returned HTTP 403, so a web search replaced it. The Fidelity fund page was wrongly excluded: the figure check read the 0.06% fee and the 15% withholding tax as index returns. One source was listed twice, and two market searches were near-duplicates. | (Changed in run 3.) |
| 3. Compared with the answer key | Consistent conclusions. The AI wrote "tracking difference −3.3 pp" (the 5-year noon-price gap) and "cost-adjusted gap 0.04 pp" (no sign, no "a year"). | Label guard. Web figures checked only when described as a return with a period. Market news may be dated up to 31 days after the period (a September 2026 market review is kept). Code builds the candidate actions. Duplicate URLs kept once. |
| 4. Step 10, with the Evaluator | The Evaluator rejected draft 2, so the template was used. A generic timing hint in code's error message clashed with the add-peer action's own timing. | Separate rewrite budgets for code's checks and the Evaluator. Each action has its own fixed "when". The findings must name the Mandate and Performance ratings. The Evaluator's plain-English rule covers only glossary terms. Tracking differences need their period. |
| 5. Full run | Draft 1 passed code's checks, but the Evaluator rejected it, mostly rightly. It found a real error: the AI said the fee explains the 3.3 pp noon-price gap (the fee explains the yearly tracking difference). Drafts 2 and 3 then each broke a different code rule. | Code writes finding 1 and the actions. Every rewrite gets all the issues so far. Rewrites: 2 for code's checks, 1 for the Evaluator. Each data note says what it "explains". |
| 6. Full run | The Evaluator's objections were correct both times: the −3.3 pp gap was called "NAV", and "after fees −0.04%" should be "with the fee added back". A web search with a `site:` operator returned no usable result. | Code writes all the findings, with fixed wording per data note; the AI writes only the market context. Search operators are removed from planned queries. |
| 7. Full run through the web page (step 11) | **Passed**: findings, actions and the Fidelity approved pages were correct. All three market-context sentences cited [3], published 2025-11-03, but described "the later part of the period" and September 2026. A kept approved page was also listed as excluded. | Citation-date check in code (a sentence may not describe a month after its cited source's date; it uses the Evaluator's rewrite). The Search agent summarises only the page it returns. Duplicate URLs are dropped before the relevance check. |

## What the Evaluator caught

The Evaluator (a separate model with its own rubric) found real errors that code's checks did not:

| What it caught | Why it mattered | Design change |
|---|---|---|
| The fee was said to explain the 3.3 pp noon-price gap | Wrong cause: the fee explains the yearly tracking difference (−0.10 pp); the noon gap is timing, not cost | Data notes state what they "explain"; then code writes these findings |
| The −3.3 pp gap was called "NAV" | Wrong label for a gap between two prices | Code writes all the findings, using fixed wording for each data note |
| "After fees −0.04%" | Wrong meaning: −0.04% is the gap *with the fee added back* | Fixed wording in code ("With the fee added back, …") |
| Market context described months its source could not cover | A source from November 2025 cannot support a statement about September 2026 | Citation-date check in code; Evaluator rubric: "each sentence's claims must be covered by the cited source's date and content" |
| Asked for definitions of everyday market words (run 4) | Too strict: rejected good text | Plain-English rule limited to glossary terms; the Evaluator gets the glossary |

The lesson for v1: insights that are fixed facts are best written by code, and the AI is most useful where the
text depends on outside sources (the market context). Each rule the AI broke more than once became a code check
or a code-written sentence. AI-written insight findings stay on the v2 roadmap, once a canonical phrasing per data
note is defined.

## Tests 2, 3 and 4

Not run yet: their input files (price files, factsheets, fund profiles) have not been supplied. The behaviour they
test is covered by unit tests with made-up data:
- Test 2, currency trap: a price-file index in the wrong currency gives "CHECK DATA: currency mismatch", and the
  factsheet index is used instead.
- Test 3, dual objective: each objective is rated separately, and Performance is the weaker rating.
- Test 4, short history: since-launch figures are used, and Performance is at least Amber, never Red on history
  alone.

They are on the v2 roadmap (spec Section 13).

## How to reproduce

```bash
pytest -q                                                                   # 466 passed, 5 skipped
PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline   # figures and ratings above
PYTHONPATH=src python -m fund_performance.run_report --data data/test1             # full run with AI
python app.py                                                               # the web page
```

`data/` is gitignored (the repository is public), so the Test 1 files stay local.
