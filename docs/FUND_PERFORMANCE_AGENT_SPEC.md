# Fund Performance Agent: Build Specification

Purpose: fund documents in, a 3-page performance review (plus an appendix) out.
**Code does the maths and the decisions. AI reads and writes. A person makes the final call.**

This spec follows the design diagram `Fund_Performance_Agent_Overview.pdf` (workflow controller in code, 7 steps, 6 AI agents, 4 oversight questions, approved sources + up to 3 web searches in the demo, 3-page report plus an appendix, 1 person signs off). The 6 AI agents are: Extractor, Mandate, Planner, Search (several copies run in parallel), Oversight Analyst, Evaluator. Build in the order given in Section 11.

---

## 1. Core principles (non-negotiable)

1. **Same data, same answer.** Every number and every rating comes from deterministic Python. The AI never calculates figures or sets ratings.
2. **Official figures first.** Returns published by the fund manager (factsheet) take priority over anything calculated from prices. Price-based calculations are used for extra metrics and as a cross-check.
3. **Flag doubtful data, never guess.** If data fails a check, output `CHECK DATA` for the affected item instead of a rating.
4. **Every number has a source.** Each figure carries a `source` field: `factsheet`, `calculated`, `ai_extracted` (must be labelled "please verify"), or `web`.
5. **The AI explains but cannot change.** The Oversight Analyst may only quote numbers present in the facts JSON it is given (enforced by a validator, Section 8.3).
6. **A person decides.** The verdict is a draft until the reviewer signs Retain / Monitor / Review.
7. **Kept in bounds.** Approved sources (fetched by code from `config/sources.yaml`) plus at most 3 web searches per run (demo setting, in config); public data only; no confidential client data uploaded. This API key has OpenAI data sharing on: public data only, never upload confidential or client data.
9. **Code controls the flow.** A workflow controller in code runs the steps in a fixed order. No AI agent decides which step runs next.
8. **All thresholds live in `config/thresholds.yaml`**, are printed in the report, and are clearly labelled as illustrative until agreed with the oversight team.

---

## 2. Inputs (Step 1)

| Input | Required | Format |
|---|---|---|
| Question | Yes | Free text, e.g. "Is this index fund meeting its mandate, and is its fee justified?" |
| Factsheet | Yes (preferred) | PDF, or a structured file of its figures |
| Fund profile | Yes | `fund_profile.json` (schema below); can be created by the Extractor Agent from factsheet + KID, then confirmed by the user |
| Price history | Recommended | CSV/XLSX: `date, nav` (+ optional `index_level`) |
| Peer fund | Recommended | `peer.json` (name, OCF, 1/3/5y returns, currency, share class) or its factsheet |
| Optional evidence | No | Manager commentary, attribution data, fund code for price download |

### 2.1 `fund_profile.json` schema
```json
{
  "fund_name": "Fidelity Index US Fund P Accumulation",
  "isin": "GB00BJS8SH10",
  "share_class": "P Acc",
  "currency": "GBP",
  "distribution": "accumulation",
  "hedged": false,
  "launch_date": "2014-03-03",
  "objective_text": "Track the performance of the S&P 500 (NUK) index ... over 5 years or more.",
  "objective_type": "index_tracker",
  "benchmark_name": "S&P 500 Index NUK",
  "benchmark_role": "target",
  "time_horizon_years": 5,
  "secondary_objective": null,
  "ocf_pct": 0.06,
  "transaction_cost_pct": -0.01,
  "performance_fee": false,
  "fund_size_gbp_m": 11006,
  "risk_indicator": 5,
  "pricing_point": "midday",
  "as_of_date": "2026-09-30"
}
```
`objective_type` is one of: `index_tracker`, `active_target`, `active_comparator`, `active_constraint`, `income_target`, `absolute_return`.
`benchmark_role` is one of: `target`, `comparator`, `constraint`, `none`.

### 2.2 `factsheet_performance.json` schema (from file or Extractor Agent)
```json
{
  "as_of_date": "2026-09-30",
  "currency": "GBP",
  "series": {
    "fund_nav":  {"1y": 17.5, "3y": 69.0, "5y": 88.3, "basis": "cumulative", "pricing": "midday"},
    "fund_pnav": {"1y": 17.0, "3y": 69.0, "5y": 90.9, "basis": "cumulative", "pricing": "market_close"},
    "index":     {"1y": 17.1, "3y": 69.5, "5y": 91.6, "basis": "cumulative", "pricing": "market_close"}
  },
  "calendar_years": {"index": {"2021": 29.6, "2022": -8.0, "2023": 18.9, "2024": 27.0, "2025": 9.6}},
  "risk_3y": {"fund_vol": 12.14, "index_vol": 12.15, "tracking_error": 0.02, "beta": 1.00, "r2": 1.00,
              "sharpe_fund": 1.57, "sharpe_index": 1.58, "info_ratio": -5.27, "alpha": -0.09, "basis": "pnav"},
  "source": "factsheet",
  "entered_by": "manual"
}
```

Optional extra fields (all optional; added after the Test 1 factsheet review):
```json
{
  "series_annualised": {
    "fund_nav":  {"1y": 17.5, "3y": 19.1, "5y": 13.5, "since_launch": 15.7, "basis": "annualised", "pricing": "midday"},
    "fund_pnav": {"1y": 17.0, "3y": 19.1, "5y": 13.8, "since_launch": 15.6, "basis": "annualised", "pricing": "market_close"},
    "index":     {"1y": 17.1, "3y": 19.2, "5y": 13.9, "since_launch": 15.7, "basis": "annualised", "pricing": "market_close"}
  },
  "discrete_12m": {
    "fund_nav":  {"2022-09-30": 2.7, "2023-09-30": 8.5, "2024-09-30": 22.9, "2025-09-30": 17.0, "2026-09-30": 17.5},
    "fund_pnav": {"2022-09-30": 1.8, "2023-09-30": 10.9, "2024-09-30": 23.7, "2025-09-30": 16.9, "2026-09-30": 17.0},
    "index":     {"2022-09-30": 1.9, "2023-09-30": 10.9, "2024-09-30": 23.8, "2025-09-30": 16.9, "2026-09-30": 17.1}
  },
  "risk_3y_nav": {"fund_vol": 13.92, "sharpe_fund": 1.37, "basis": "nav"}
}
```
- `series` may also hold `since_launch` (cumulative). `series_annualised` holds the factsheet's annualised
  figures; official figures come first, so these are preferred over calculated annualised returns.
- `discrete_12m` is keyed by the end date of each 12-month window; step 4 uses it for cross-checking.
- Risk figures carry a `basis` label (`nav` or `pnav`) so the two sets are never mixed: `risk_3y_nav` is
  always `nav`, and when it is present `risk_3y` must be `pnav`.
- `entered_by` is `manual` for figures typed by a person, `extractor` for the Extractor Agent.
- `fund_profile.json` also takes an optional `asset_class` (default `equity`). A `transaction_cost_pct`
  that is not in the documents stays `null`; the report shows "Not disclosed in the documents provided".
```

---

## 3. Read the data (Step 2)

### 3.1 File reader (code)
- Detect file type by name and content: performance table, fund facts, peer, prices, documents.
- Parse dates explicitly (detect `MM/DD/YYYY` vs `DD/MM/YYYY`; never guess silently; log the format used).
- Strip trailing empty columns (e.g. rows ending with a comma).
- Convert `-` and blanks to missing values.
- Sort ascending by date.

### 3.2 Extractor Agent (AI)
- Only runs if no structured file contains the needed numbers.
- Reads factsheet/KID PDFs and returns `factsheet_performance.json` and draft `fund_profile.json`.
- Every extracted value gets `source: "ai_extracted"` and is shown in the report as "please verify".

### 3.3 Price download fallback (code)
- Only when there is no factsheet. Any results that look wrong are flagged `CHECK DATA`.

### 3.4 Data quality checks (code): each produces a flag in `data_flags[]`

| Check | Rule | Action |
|---|---|---|
| Currency match | Fund and benchmark series must be in the same currency | If not: `CHECK DATA: currency mismatch` (do not compare) |
| End-date alignment | Fund and benchmark end dates must be equal | Truncate to the common end date; log it |
| Pricing point | If fund is priced `midday` and index is `market_close`, use fund PNAV (market-close) for the fund-vs-index comparison when available | If PNAV unavailable: note "timing difference" and widen tolerance |
| Missing values | Any missing NAV/index value | List the dates; exclude from return-based risk stats; never interpolate silently |
| Gaps | Gap between observations > 35 days (monthly) or > 5 business days (daily) | Flag |
| Repeated prices | Same NAV on two different dates (consecutive or within 3 periods) for an equity fund | Flag as "suspicious repeated price" with dates. If every factsheet discrete 12-month window around those dates matches the calculated return within `repeated_price_factsheet_match_pp` (0.1 pp), lower it to info with "checked against factsheet: consistent"; otherwise it stays a warning |
| History length | Months of data < `time_horizon_years * 12` | Set `short_history = true` |
| Cross-check | Calculated 1/3/5y return vs factsheet NAV return | If abs diff > 0.3 percentage points: flag; factsheet wins |
| Implausible tracker gap | Index fund, price data only, abs(fund - index) annualised gap > 1.0% | Output `CHECK DATA` instead of Red |
| Pre-launch prices | Any price dated before the share class `launch_date` | Info flag "pre-launch (likely simulated)" with the dates; leave these prices out of risk statistics and since-launch figures; repeated prices in this period are info level, not warning |

Known traps (must be handled):
- Index level supplied in a different currency to the share class (e.g. EUR share class with USD index).
- Midday NAV vs market-close index: the midday 5y return (88.3%) vs index (91.6%) looks 3.3 points behind; the fair PNAV comparison (90.9% vs 91.6%) is only 0.7 points.

---

## 4. Calculator formulas (Step 3, code)

Notation: `P_t` = price at month-end t; monthly return `r_t = P_t / P_{t-1} - 1`. Use monthly data unless stated. All outputs in % to 2 d.p. internally, displayed to 1 d.p., rounded once from the exact value. Tracking error, tracking difference, alpha, beta, R2 and the information ratio are displayed to 2 d.p., as on the factsheet.

### 4.1 Returns
- **Cumulative return over n years:** `R_cum = P_end / P_start - 1`, where `P_start` is the last price on or before `end_date - n years`.
- **Annualised return:** `R_ann = (1 + R_cum)^(1/n) - 1`.
- **Discrete 12-month returns:** cumulative return for each 12-month window ending on `as_of_date`, `as_of_date - 1y`, ... (last 5 windows).
- **Calendar-year returns:** `P_Dec31(y) / P_Dec31(y-1) - 1`; current year labelled "YTD". Only full calendar years after launch (the year-start price is on or after `launch_date`), the last 10 at most, as on the factsheet.
- **Since launch (annualised):** use the first available price on or after `launch_date`; required when `short_history = true`. When the factsheet gives a since-launch figure it wins; any difference and its reason (e.g. no launch-day price) goes in the run log, not the report.

### 4.2 Relative performance
- **Excess return (cumulative):** `R_cum_fund - R_cum_bench` (percentage points).
- **Annualised excess / tracking difference:** `TD = R_ann_fund - R_ann_bench`.
- **Cost-adjusted tracking difference (index funds):** `TD_ex_cost = TD + OCF`. Values near 0 mean the gap is explained by charges.

### 4.3 Risk (monthly data, annualised)
- **Volatility:** `sigma = stdev(r_t) * sqrt(12)` (sample stdev). For daily data use `sqrt(252)`.
- **Maximum drawdown:** `MDD = min_t (P_t / max_{s<=t} P_s - 1)` over the window.
- **Sharpe ratio:** `(R_ann - rf_ann) / sigma`; `rf` from config (e.g. UK Bank Rate or SONIA average for the window). If no rf is supplied, use 0 and flag it.
- **Tracking error:** `TE = stdev(r_fund_t - r_bench_t) * sqrt(12)`.
- **Information ratio:** `IR = (R_ann_fund - R_ann_bench) / TE`.
- **Beta:** `cov(r_fund, r_bench) / var(r_bench)`.
- **R-squared:** `corr(r_fund, r_bench)^2`.
- **Alpha (annualised, simple):** `R_ann_fund - [rf + beta * (R_ann_bench - rf)]`.
- **Relative volatility:** `sigma_fund / sigma_bench`.
- Prefer factsheet risk figures when supplied; show calculated ones as a cross-check.
- Benchmark-relative measures (TE, beta, R2, information ratio, alpha, relative volatility, TD) need an
  index price series. Without one they are marked "not available: no index price series" and never
  approximated; the factsheet's figures are reported instead (`source: "factsheet"`).

### 4.4 Consistency
- **Hit rate:** number of the last 5 discrete 12-month periods where the fund met its objective test (index fund: abs(TD for that year) <= OCF + `hit_rate_td_margin_over_ocf_pp` (0.10); active: fund >= target).

### 4.5 Attribution by sector (optional, when weights and sector returns are supplied)
- Brinson: allocation `= (w_f - w_b) * (R_b,sector - R_b,total)`; selection `= w_b * (R_f,sector - R_b,sector)`; interaction `= (w_f - w_b) * (R_f,sector - R_b,sector)`. Sum across sectors.

### 4.6 Peer comparison
- **Peer return gap (annualised):** `R_ann_peer - R_ann_fund` for 1/3/5y (same currency and share class basis, both net of fees).
- **Fee gap:** `OCF_fund - OCF_peer` (percentage points).

### 4.7 Charts
1. Cumulative growth of 100: fund vs benchmark (and peer) over 5 years.
2. Discrete 12-month returns bar chart: fund vs benchmark.
3. Drawdown chart.

---

## 5. Mandate Agent (Step 3, AI) and the decision tree

The Mandate Agent reads `objective_text` and returns JSON only:
```json
{"objective_type": "index_tracker", "benchmark_role": "target", "time_horizon_years": 5,
 "secondary_objective": null, "promises": ["Track the S&P 500 (NUK) index", "Grow investment over 5+ years"]}
```
Code validates the JSON against the allowed values; if the user-supplied profile disagrees, the profile wins and a flag is raised. A free-text `secondary_objective` in the profile is classified by the Mandate Agent into one of the six types; if it cannot be classified, it is not rated (CHECK DATA).

### 5.1 Decision tree (code)
```
1. What is objective_type?
   index_tracker      -> judge tracking (TD, TD_ex_cost, TE, R2) vs benchmark
   active_target      -> judge annualised excess return vs the target over the horizon
   active_comparator  -> judge peer/sector ranking (quartile) and excess vs comparator
   active_constraint  -> judge excess vs benchmark + check stays within constraints
   income_target      -> judge yield/income vs target AND capital preservation
   absolute_return    -> judge return vs stated target (e.g. cash + x%) and drawdown
2. Is there a secondary_objective (dual objective)?
   yes -> rate each objective separately; Performance rating = the worse of the two
3. Is history shorter than the horizon (short_history)?
   yes -> use since-launch annualised figures; Performance = AMBER with reason
          "track record shorter than the fund's time horizon"; never RED on history alone
4. Main test period = time_horizon_years (default 5); 1y and 3y shown as trend context
5. Apply the Section 3.4 data checks before rating; any blocking flag -> CHECK DATA
```

---

## 6. Oversight scorecard (Step 4, code)

Four questions, each `GREEN`, `AMBER`, `RED` or `CHECK DATA`. Thresholds below are defaults in `config/thresholds.yaml` (illustrative; to be agreed with the oversight team).

### 6.1 Mandate: is the fund doing what it promised?
- GREEN: invests in line with its objective/policy (index fund: R2 >= 0.98 and beta 0.95 to 1.05; active: style and holdings consistent with policy).
- AMBER: minor drift (index fund: R2 0.95 to 0.98, or beta outside 0.95 to 1.05 but within 0.90 to 1.10).
- RED: clear drift from mandate.
- Active funds (v1): status **Manual check**, reason "Style and holdings need a reviewer check", with a tick box in the
  approval section. It does not block the verdict. Measurable rules come in v2.

### 6.2 Performance vs benchmark (main period = horizon)
Index funds: tracking difference and tracking error are rated separately, and Performance is the weaker of
the two (the same rule as for dual objectives). The report shows both sub-ratings and the reason.
- Tracking difference (annualised, main period, fair basis, e.g. PNAV vs index): GREEN if `abs(TD) <= OCF + 0.10`,
  AMBER if `abs(TD) <= OCF + 0.30`, else RED. Widened by the timing tolerance when PNAV is unavailable.
- Tracking error: GREEN if `TE <= 0.30`, AMBER if `TE <= 1.00`, else RED. Use the 5-year calculated TE when an
  index price series is available; otherwise the factsheet 3-year TE, labelled "3y (factsheet)". When the TD and
  TE periods differ, the report notes it.
- A fund 3% behind its index with a low TE is RED.
- `CHECK DATA` instead of RED if based on price data only and the gap is > 1.0%.
- Ratings compare values at the stored 2 d.p., so a value exactly on a limit counts as within it.

Active funds with a target:
- GREEN: annualised excess over horizon >= 0
- AMBER: between -1.0 and 0, or >= 0 but hit rate < 3 of 5
- RED: < -1.0
Comparator funds: GREEN = quartile 1 to 2, AMBER = quartile 3, RED = quartile 4 (over horizon).

### 6.3 Value for investors: compared with an alternative, did investors get a fair outcome?
Uses the peer return gap over the main period (annualised, net of fees):
- GREEN: peer outperforms by <= 0.10% a year (or fund outperforms peer)
- AMBER: peer outperforms by 0.10% to 0.50% a year
- RED: peer outperforms by > 0.50% a year
- No peer supplied: AMBER with reason "no comparison available".

### 6.4 Is the fee justified?
- Index funds: GREEN if `OCF_fund <= OCF_peer + 0.05`; AMBER if `<= OCF_peer + 0.20`; RED otherwise.
- Active funds: GREEN if OCF <= peer median OCF and Performance is not RED; AMBER if OCF above peer median but Performance GREEN; RED if OCF above peer median and Performance RED.
- Active funds, cases not listed above (fee above the peer median with Amber performance; fee at or below it with Red
  performance): AMBER.
- Any performance fee: add a note; AMBER minimum unless justified in the profile (`performance_fee_justification`, an
  optional text field filled in by a person only; an AI agent never writes it).

### 6.5 Verdict
- Any RED -> **Review**
- Else any AMBER -> **Monitor**
- Else -> **Retain**
- Any `CHECK DATA` on Performance or Mandate -> verdict "Pending data check" (no verdict until resolved).
- `CHECK DATA` on Value or Fees -> "Monitor (data check needed: Value)" (naming the items).
- A **Manual check** does not change the verdict; it is named in the verdict reason and ticked by the reviewer.

Expected example (Test 1, no peer supplied): Mandate GREEN (R2 1.00, beta 1.00, 3y factsheet), Performance GREEN (TD -0.10 pp a year over 5 years, PNAV vs index, within OCF + 0.10 = 0.16; TE 0.02, 3y (factsheet); note that the periods differ), Value and Fees AMBER with reason "no comparison available" (shown as "Add peer" in the summary) -> draft verdict **Monitor until a peer is added**. Never invent peer figures.

---

## 7. FCA Assessment of Value mapping (shown on report page 3)

The FCA rule (COLL 6.6.20R) requires an annual assessment of whether charges are justified by overall value, across 7 factors. The report maps the scorecard to them:

| AoV factor | Source in this agent | If no data |
|---|---|---|
| 1. Quality of service | Not public | "Requires internal data" |
| 2. Performance | Scorecard 6.1 + 6.2 | n/a |
| 3. AFM costs | OCF, transaction costs, performance fee | Flag missing; if transaction costs are not disclosed, show "Not disclosed in the documents provided" and mark the factor "Partly" |
| 4. Economies of scale | Fund size; OCF history if supplied | "Requires OCF history" |
| 5. Comparable market rates | Scorecard 6.4 (peer OCF) | "No peer supplied" |
| 6. Comparable services | Other share classes/mandates of same manager, if supplied | "Requires internal data" |
| 7. Classes of units | Share class list and fees, if supplied | "Requires share class data" |

The report must state clearly: "This is an indicative assessment from public data. It does not replace the AFM's formal Assessment of Value."

---

## 8. AI agents (Steps 5 to 7)

All agents return structured JSON validated with Pydantic. Use the OpenAI Agents SDK (or LangGraph). Temperature low (0 to 0.3).
- Models per agent in `config/models.yaml` (nothing hard-coded): Extractor, Mandate, Planner and Search `gpt-5.4-mini`;
  Oversight Analyst `gpt-5.4`; Evaluator `gpt-6.1-sol` with its own strict checking prompt. `FUND_MODEL_<AGENT>` may
  override one agent's model for testing (it must be listed in the file). Temperature 0 is sent only if the config
  says the model supports it; otherwise a low reasoning effort is sent.
- The API key is read from the `OPENAI_API_KEY` environment variable, loaded from `.env` (gitignored) by python-dotenv.
- This API key has OpenAI data sharing on: public data only, never upload confidential or client data.
- Invalid output (fails validation) is retried once, then the affected item is `CHECK DATA`. A failed call (network,
  key) is not retried.
- Unit tests mock the AI calls; one live test per agent runs only with `pytest --run-live`.
- The Extractor's answer is checked by code: every extracted number must appear in the document text, otherwise a
  warning lists it. The Extractor never sets `objective_type`, `benchmark_role`, the horizon, the secondary objective
  or `performance_fee_justification`.

| Agent | Input | Output | Limits |
|---|---|---|---|
| Extractor | Factsheet/KID text | `factsheet_performance.json`, draft `fund_profile.json` | Labels all values `ai_extracted` |
| Mandate | `objective_text` | Mandate JSON (Section 5) | Allowed values only |
| Planner | Fund profile + scorecard | Search queries for fund or manager changes and market drivers for the period | Up to 3 web searches in total, fallbacks for unreadable approved pages first |
| Search (parallel) | One query each, or the text of one approved page fetched by code | `{query, summary, url, date}` (for a page, the URL comes from the config) | One search or page each, no retries |
| Oversight Analyst | facts JSON + scorecard + search summaries | Findings, actions, market context | Cannot change ratings; may only quote given numbers |
| Evaluator | Analyst draft + facts JSON + scorecard + search summaries | `{pass: bool, issues: [..]}` (Section 8.4) | One rewrite only, then template fallback |

### 8.1 Oversight Analyst system prompt (core rules)
- You explain ratings that have already been decided by code. Never change, soften or override a rating.
- Only use numbers that appear in the provided facts. Do not calculate new numbers.
- If a figure is labelled `ai_extracted`, write "(please verify)" next to it.
- If any item is `CHECK DATA`, explain what needs checking instead of drawing a conclusion.
- Plain English, short sentences, no jargon without a one-line explanation.
- Structure: 3 key findings, 2 to 3 recommended actions, short market context with sources.
- Never a minus sign after "behind" or "below" ("behind by 0.10%"); code checks this. Every action is a real
  task with a when, never a restatement of the verdict or an internal technical note.
- Actions come from code (`actions.py`): candidate actions built from the ratings and data flags, in priority
  order (Check data, Red, Manual check, Add peer, Amber, data warnings, then "record the decision" and "read the
  sources"), each with an id, a default wording with its timing, words a rewording must keep, and a `required`
  mark. They are in the facts JSON as `candidate_actions`. The Analyst returns each action as
  `{candidate, text}`: it may only choose candidates and reword them, and must choose every required one while
  there is room. Code rejects an unknown candidate, a repeat, a left-out required candidate, missing keep-words,
  no "when", and method or period words (PNAV, NAV, noon, pricing, method, basis, period, calculation) that the
  candidate does not use. The template uses the default wording.
- Readable for experts and newcomers: plain meaning first, technical term second in brackets; explain each
  term once in under 10 words using the shared glossary (`glossary.py`); no unexplained abbreviations
  ("ongoing charge (OCF)"); sentences under 20 words, at most 2 per finding; say "Draft verdict"; at least one
  finding explains a "below the surface" point from the data notes when there is one; no point repeated in
  findings and actions; each action says what to do and when.
- Data notes (facts JSON, written by code): short notes with their figures for info flags that change how the
  results read, e.g. noon NAV vs market-close index (Test 1: 88.3% vs 91.6%, -3.3 pp; PNAV 90.9%, -0.7 pp) and
  how much of the tracking difference the fee explains (-0.10 pp a year, OCF 0.06%, cost-adjusted -0.04 pp).
- Market context uses no figures from search summaries (only numbers from the facts may be quoted); it describes
  direction and cites the URLs.

### 8.2 Planner/Search rules
- Approved sources (step 9b, `config/sources.yaml`): per fund (by ISIN) and per market (by market name), e.g.
  for Test 1 the Fidelity fund page, the Fidelity charges and key documents page, and the S&P Dow Jones Indices
  S&P 500 page. Code fetches them directly (`fetch.py`, in parallel); no AI chooses URLs. A Search agent with no
  web tool summarises each page's text, and the URL in the summary is the one from the config. The summary gets
  the same date, relevance and figure checks as a web result.
- A page that fails (HTTP error, no connection) or is nearly empty after removing HTML (JavaScript-only or
  blocked; under `fetch.min_page_chars`) gets an info flag and is replaced by a web search written by code
  (fund pages: fund name, ISIN, "fund changes", period; market pages: "<market> review <period>"). These
  fallbacks use the web-search budget first; two pages that need the same search share one.
- Web searches: at most `limits.max_web_searches` (3) per run, used only for fund or manager changes and for
  what drove the market in the review period. The Planner gets what is left after fallbacks, and is told which
  approved sources were read. If nothing is left, the Planner is not run.
- Queries must be about the fund, its manager, or market drivers in the review period.
- Never send client data or uploaded documents to search.
- Each summary must cite its URL; the report lists all sources.
- v1 (`agents/research.py`): the Planner sees only public fund details (name, ISIN, share class, benchmark,
  objective type, review period) and the ratings; never figures, uploaded documents or client data. Each Search
  agent sees only its query and reason. Code caps the plan at what is left of `limits.max_web_searches` (3) and drops empty,
  overlong or repeated queries. Searches run in parallel, one web search each, no retries; a failed search or a
  summary without a URL is left out (info flag). If the Planner fails twice, the review goes on with the approved
  sources and fallback searches only (warning flag); with no results at all, there is no market context (warning flag). The report lists the planned query, URL and date of every summary used.
- Queries: market_drivers queries are about the market, never the fund (e.g. "S&P 500 performance drivers Oct 2025
  to Sep 2026"); code drops any that name the fund. Only fund-specific searches (changes, manager, fees) use the
  fund's name. Prefer news and index-provider sources over fund data pages.
- Vetting (code, before the Analyst): a summary is excluded, with an info flag, if it has no date, is dated outside
  the 12-month review period, or states a fund or index return more than 0.5 pp from the factsheet figure for the
  same series and period: "web source figures differ from factsheet, likely different currency or date:
  excluded". Test 1: Morningstar USD pages (11.99% vs 17.0%) are excluded.
  - Only figures described as returns or performance (return, gained, fell, performance ...) with a period are
    checked; "total return" in an index name is not a return word, so fees and tax rates are not read as returns
    (Test 1: the Fidelity fund page's 0.06% fee and 15% withholding tax).
  - Market news may be dated up to `vetting.market_grace_days` (31, `config/sources.yaml`) after the period end,
    as period reviews come out just after the period (Test 1: the Nasdaq September 2026 review).
  - Identical URLs are kept once; the first kept wins, so an approved source beats a web result (log only).
- Citations: the market context cites sources as [1], [2]; the Analyst never sees or writes URLs, and the report
  lists each number with its URL under Sources.
- Dates: a page with no publish date but an "as at" or "updated" date is kept with `date_basis: "as_at"`; only
  pages with no date at all are excluded. Approved sources and fund-specific facts (fund news, manager changes)
  may be dated after the period end (e.g. a fund page "as at" the run date) and are excluded only if dated
  before the period start; market news from web searches must fall inside the review period.
- Relevance: a fund-news or manager summary must match the fund's name, ISIN, or share class with the manager's
  name, and US regulatory filings (sec.gov) are excluded for non-US funds; a market summary must name the market.
  Otherwise it is excluded with an info flag (Test 1: the SEC filing for a US Fidelity fund).
- Review period longer than 3 months: market queries ask for a review of the whole period, and the market context
  describes only what the cited sources cover.
- Required insights (code): every data note must be covered in the findings, i.e. one of its key figures appears
  (Test 1: the noon-pricing gap 3.3 pp and the 0.06% fee). A missing one triggers the one rewrite.
- AI text writes periods in words ("5 years", not "5y"). If the rewrite still fails, the flag names the failed
  checks: "AI text failed checks: number / rating / wording / insights".
- Wording checks in code (each triggers the one rewrite): at most 2 sentences per finding; no action containing
  "note that", "remains understood" or "be aware" (each action must change or check something specific).
- Definitions go in brackets after the term and its figure, the first time the term is used: "R² 1.00 (how
  closely fund and index move together)" (prompt rule).

### 8.3 Number-guard validator (code)
After the Analyst responds: extract all numbers from its text (regex for decimals and %). Every number must match a value in the facts JSON (allowing rounding to 1 d.p.). If not, reject and re-prompt once; if it fails again, use a template-only narrative and flag it.
- Units must match: every figure in the facts JSON carries its unit (`%` for returns, `pp` for tracking differences and gaps), and a number in the text matches only a fact with the same unit, so -0.10 pp is never confused with a 0.10% return. Rounding to 1 or 2 d.p. is allowed; a whole number with % or pp must match exactly; a written minus must match a negative fact.
- Not figures, so not checked: years (2024), periods ("5 years", "3y", "12-month"), counts ("4 questions", "5 of 5") and dates; in practice, any whole number without % or pp.
- Label guard (code): if "tracking difference", "tracking error", "ongoing charge"/"OCF" or "cost-adjusted gap"
  is within 8 words of a number (in the same sentence; the nearest label before the number with no other number
  between, else one after it in the same clause), the number must be a fact of that type, in its unit and for the
  period named nearby. A (cost-adjusted) tracking difference is yearly: "a year" must be nearby, and a negative
  one needs its minus sign or a word such as "behind". Test 1: "tracking difference −3.3 pp" (the 5-year noon gap)
  and "cost-adjusted gap 0.04 pp" (no sign, no "a year") are rejected. Counts as a number problem.
- Rating guard (code): the text must not give a pillar a different rating, or use a verdict word other than the decided verdict. A failing draft is re-prompted once with the list of problems (bad numbers and changed ratings); then the template narrative is used with the flag "AI text failed number check".
- The Analyst's inputs are the facts JSON (scorecard, decision-tree path, figures with units and sources, warning and blocking flags) and, from step 8, search summaries. Without search summaries, market context is null.

---

### 8.4 Evaluator Agent (quality check)
Runs after the number-guard validator passes. Checks the Analyst draft against a fixed rubric and returns JSON only:
```json
{"pass": false, "issues": [{"check": "rating_explained", "detail": "Value rating not explained"}]}
```
Rubric (each must pass):
1. **rating_explained:** every one of the 4 ratings is mentioned and its reason matches the scorecard reason.
2. **no_rating_change:** the text never suggests a different rating or verdict.
3. **supported_claims:** every claim is supported by the facts JSON or a cited search summary.
4. **sources_cited:** every market or news statement cites a search URL.
5. **check_data_handled:** any `CHECK DATA` item is explained as needing a check, not as a conclusion.
6. **plain_english:** short sentences; any technical term has a one-line explanation.

Flow: if `pass = false`, send the issues back to the Analyst for **one** rewrite, then re-run the number guard and the Evaluator. If it fails again, use the template-only narrative and add a flag "AI text failed quality check" to the report. The Evaluator never edits the text itself and never changes ratings. Use a different system prompt from the Analyst (and ideally a different model) so the work does not grade itself.

### 8.5 Workflow controller (code)
A plain Python function (not an AI agent) that runs: read files -> data checks -> extractor (if needed) -> mandate -> calculator -> scorecard -> planner -> search (parallel) -> analyst -> number guard -> evaluator -> report.
- Stops the run with a clear message if a blocking data check fails before scoring.
- Enforces limits from config: max searches, max one rewrite, timeouts.
- Logs each step (start, end, inputs used) to `runs/<timestamp>/log.json`; the report's sources list is built from this log.

## 9. Report (Step 7): 3 main pages plus an appendix

Length: 4 pages (3 main pages + 1 appendix page), 5 at most. Each main section starts on its own page.
If the content runs over 5 pages, the appendix is shortened first (info flags cut to the first 6 with
"... and N more (full list in run_log.txt)", thresholds cut to the main lines). A main page that runs
over is an error (`ReportLayoutError`), never a silent overflow. Code checks this after every render.

1. **Summary** (must stand on its own): fund, question, review date; draft verdict; the 4 ratings
   with one-line plain-English reasons and Green/Amber/Red colours; key findings and actions;
   approval box (reviewer name, date, Retain / Monitor / Review, signature) with a tick box for each
   Manual check item.
2. **Mandate and performance:** objective, promises and the decision-tree path in plain words (no code
   names); 1/3/5-year table (fund, index, gap; cumulative and annualised) with the note "Cumulative
   gaps to 1 d.p., yearly gaps to 2 d.p."; calendar years; risk table grouped under small subheadings
   by source, period and price basis (e.g. "Factsheet · 3 years, market-close price (PNAV)"), so no
   measure appears without its context; "Below the surface": the data notes' plain sentences, each
   followed by one short source line in small text with its figures; charts: growth of 100 and yearly
   returns, fund vs index.
3. **Value, fees and Assessment of Value:** peer and fee comparison ("Add peer" callout when there
   is no peer); the AoV 7-factor table (Covered / Partly / Not assessed) with its disclaimer; market
   context with [n] citations ("No market context" when there is none).
4. **Appendix:** flags by level (blocking, warning, info); excluded web sources with reasons;
   numbered sources with dates ("published" or "as at") and every input file; the calculated Sharpe
   ratio (risk-free rate 0), noted as not comparable with the factsheet figure; thresholds
   ("illustrative, to be agreed with the oversight team"); glossary of the terms the report actually
   uses (`glossary.py`, each definition under 10 words); known
   limitations (Section 12); the "public data only" note and the disclaimer.

Display rules:
- Percentages to 1 d.p.; tracking error, tracking difference, alpha, beta, R² and information ratio
  to 2 d.p. Displayed from the exact value, so rounded once.
- Negative numbers use the minus sign "−". Missing figures show "–".
- AI-extracted figures are marked "(please verify)".
- Every figure shows its source (calculated, factsheet, KID, profile).
- The template narrative (used offline or when the AI text fails its checks) is plain English.
- Style: clean, navy headings, Green/Amber/Red rating chips, DejaVu Sans font (shipped with
  matplotlib, so the same on any machine).

Output: `runs/<YYYYMMDD-HHMMSS>/report.pdf`, with `facts.json` and `run_log.txt` beside it.
Command: `PYTHONPATH=src python -m fund_performance.run_report --data data/test1` (add `--offline`
to skip all AI steps; the report then carries an info flag saying so).

Target runtime: about 1 to 2 minutes end to end.

---

## 10. Test cases and expected results

### Test 1: Fidelity Index US Fund P Acc (GB00BJS8SH10), as of 30 Sep 2026
Inputs: monthly NAV CSV (Nov 2012 to Sep 2026), UK factsheet, KID.
Expected:
- Calculated NAV cumulative returns match factsheet: **1y 17.5%, 3y 69.0%, 5y 88.3%** (5y annualised 13.5%).
- Fair comparison uses PNAV vs index: **1y 17.0 vs 17.1, 3y 69.0 vs 69.5, 5y 90.9 vs 91.6**; 5y annualised 13.8% vs about 13.9%.
- OCF 0.06%; TE (3y) 0.02; beta 1.00; R2 1.00 (factsheet).
- Calculated from the NAV CSV (cross-checks only, tested to 1 d.p.): 5-year volatility 13.7%, 5-year maximum
  drawdown -15.1%. The CSV has no index series, so TE, beta, R2, information ratio and alpha are reported from
  the factsheet and their calculated versions are "not available: no index price series".
- Mandate GREEN; Performance GREEN.
- Data flags raised: 16 pre-launch prices (2012-11-30 to 2014-02-28, before the 2014-03-03 share class launch) at info level; repeated prices 2013-06-30/2013-08-31 and 2013-12-31/2014-02-28 at **info** level (pre-launch); 2024-07-31/2024-09-30 raised as a warning by the price check, then lowered to **info** in step 4 with "checked against factsheet: consistent" (12 months to 2024-09-30: 22.93% vs 22.9%; to 2025-09-30: 17.03% vs 17.0%); trailing comma handled; dates read as `MM/DD/YYYY`.
- Factsheet precedence: reported 1/3/5y figures are the factsheet's; cross-check differences 0.01, 0.04 and 0.03 pp (no flag). Fair comparison PNAV vs index: excess -0.7 pp over 5 years, TD -0.10 pp a year, TD_ex_cost -0.04; hit rate 5 of 5. Calculated 3-year NAV volatility 13.92% matches the factsheet 13.92%.
- Must NOT rate Performance RED from midday NAV 88.3% vs index 91.6%.

### Test 2: Fidelity S&P 500 Index Fund P EUR Acc (IE00BYX5MX67): currency trap
Inputs: daily NAV XLSX with `Index Level` column (index in USD, fund in EUR), factsheet.
Expected:
- Fund 12-month return to 30 Sep 2026 = 19.3% (matches factsheet).
- Detect that the price-file index does not match the factsheet EUR index (e.g. 2022: file index -18.5% vs factsheet -13.2%) -> `CHECK DATA: currency mismatch`; use factsheet index figures instead.
- Flag 2 missing index values (2024-06-28, 2025-08-29).

### Test 3: A Marlborough fund (dual objective, e.g. income and growth)
- Mandate Agent detects a secondary objective; Performance = worse of the two ratings.

### Test 4: A fund with less than 5 years of history
- `short_history = true`; since-launch figures used; Performance AMBER with the history reason; never RED on history alone.

### Answer key
Keep the manager's published Value Assessment Report out of the agent's inputs. Compare the agent's conclusion with it afterwards.

---

## 11. Build order for Claude Code

1. **Project setup:** modules in the package `src/fund_performance/`: `io.py` (file reader), `checks.py` (Section 3.4), `calc.py` (Section 4), `precedence.py` (factsheet precedence and cross-check, step 4), `facts.py` (the facts JSON, step 7), `number_guard.py` (Section 8.3, step 7), `mandate.py` (decision tree), `scorecard.py` (Section 6), `agents/` (Section 8), `fetch.py` (approved sources, Section 8.2), `report.py` (Section 9), `controller.py` (Section 8.5); `config/thresholds.yaml`; `tests/`.
2. **File reader + data checks** with unit tests for Tests 1 and 2 (dates, trailing comma, `-` values, repeated prices, currency mismatch).
3. **Calculator** with unit tests reproducing the Test 1 figures exactly.
4. **Factsheet precedence and cross-check** (0.3 pp tolerance).
5. **Decision tree + scorecard** driven by `thresholds.yaml`; unit tests for each branch (index, active, dual, short history, CHECK DATA).
6. **Extractor and Mandate agents** with Pydantic schemas.
7. **Oversight Analyst + number-guard validator.**
8. **Planner + parallel Search agents** (no retries). 9b: approved sources fetched by code + up to 3 web searches.
9. **PDF report** (3 main pages + appendix, 5 pages at most) with charts and approval box.
10. **Evaluator agent + workflow controller** (Sections 8.4 and 8.5); unit test that a draft with a changed rating or an unsupported claim is rejected.
11. **Gradio front end** (upload files, ask the question, download the PDF); deploy as with the existing project.
12. **Run all 4 test cases**, compare Test 1 with the published Value Assessment Report, and record results in `tests/RESULTS.md`.

Definition of done: all unit tests pass; Test 1 and Test 2 expected values reproduced; no rating can be changed by the AI; every figure in the PDF has a source; the Evaluator rejects a bad draft in tests.

---

## 12. Known limitations

- Web figures are checked against the factsheet only when described as a return or performance with a period
  (e.g. "returned 17.1% over 1 year"). Other figures in web text (fees, tax rates, returns with no period) are not
  checked; the AI text may still quote only figures from the factsheet and calculations.
- Relevance checks match names and the ISIN in the summary text; a summary about this fund that names it in
  another way (e.g. only by a ticker) is excluded.

## 13. Roadmap (as shared with the team)

| Phase | Scope |
|---|---|
| **v1: next two days** | Steps 1 to 11 above on Test 1 (Fidelity Index US Fund). Value and Fees show "Add peer" when no peer is supplied. |
| **v2: next step** | Peer comparison for value and fees (e.g. SPDR S&P 500 UCITS ETF); run Tests 2, 3 and 4 (currency trap, dual objective, short history, active fund). |
| **v2: peers** | Allow the peer to be a sector median OCF (e.g. IA North America index funds, 0.10%), as Fidelity's own Assessment of Value does, as well as a single peer fund. |
| **v2: share classes** | Optional share-class table input (class, OCF, minimum investment, who can buy it) for the AoV "Classes of units" factor, which is "Not assessed" without it. |
| **v2: sources** | v1 fetches the approved pages in `config/sources.yaml` in code. v2 option: the MCP Fetch server, so an agent can choose and fetch further URLs (checked against an approved-domain list) instead of open web search. |
| **v3: later** | Agree thresholds and rating rules with the oversight team; adapt inputs to the team's own data and processes. |
