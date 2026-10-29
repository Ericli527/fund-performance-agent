# CLAUDE.md

Instructions for Claude Code in this project. The build specification is
`docs/FUND_PERFORMANCE_AGENT_SPEC.md`.

## Rules

1. **Follow the spec exactly.** If something in the spec is unclear or conflicts with existing
   code, stop and ask. Do not guess or change the design.
2. **Code does all calculations and ratings.** AI agents never calculate numbers or set ratings.
   They read, search and write text only, and may quote only numbers that code gave them.
3. **Never change `config/thresholds.yaml` unless I ask.**
4. **Never use files in `data/answer_key/` as agent input.** They are only for comparing results
   after a run.
5. **Write and run unit tests for every module.** Do not report a step as done until its tests pass.
6. **Work one build step at a time** (spec Section 11). Stop after each step and wait for my approval
   before starting the next.
7. **Keep API keys in `.env`.** Never write a key into code, tests, docs or commits. `.env` stays
   in `.gitignore`.
8. **Data sharing.** This API key has OpenAI data sharing on: public data only, never upload confidential or client data.

## Agreed decisions

- Code lives in the package `src/fund_performance/` (so `io.py` cannot hide Python's own `io`).
- Everything in `data/` is gitignored, because the repository is public. Never commit price files,
  factsheets, KIDs or answer keys. Unit tests use small made-up files in `tests/fixtures/`; tests
  that need the real Test 1 files are skipped when those files are missing.
- Factsheet figures typed by hand carry `source: "factsheet"` and `entered_by: "manual"`.
- Fund profile: optional `asset_class`, default `equity`.
- Transaction cost not in the documents stays `null`. The report shows "Not disclosed in the
  documents provided" and marks the AoV Costs factor "Partly". Never use a figure from elsewhere.
- Factsheet schema extras (all optional): `series_annualised` (preferred over calculated
  annualised returns), `discrete_12m` (for the step 4 cross-check), `alpha`, and NAV-basis risk in
  `risk_3y_nav`. Risk figures carry `basis` (`nav`/`pnav`) and the two sets are never mixed.
- Prices before `launch_date` get an info flag "pre-launch (likely simulated)" and are left out of
  risk statistics and since-launch figures. Repeated prices in that period are info, not warning.
- Ambiguous dates: use the format that gives one price per month in date order; if both formats
  do, stop and ask the user.
- Benchmark-relative risk (TE, beta, R², information ratio, alpha) is calculated only from an index
  price series. Without one: "not available: no index price series", factsheet figures reported with
  `source: "factsheet"`, never approximated.
- Figures are stored to 2 d.p. but displayed from the exact value, so they are rounded once
  (10.5499 shows as 10.5%, not 10.55 -> 10.6%).
- Repeated price: lowered to info with "checked against factsheet: consistent" when every factsheet
  12-month window around it matches the calculated return within 0.1 pp (config); otherwise a warning.
- Display: tracking error, tracking difference, alpha, beta, R² and information ratio to 2 d.p. (step 9).
- Calendar years: only full calendar years after launch, last 10 at most.
- Since-launch: the factsheet figure wins; the difference and its reason go in the run log only.
- Hit rate (index funds): a window counts if abs(TD) <= OCF + 0.10 (own config key).
- Index fund Performance: TD and TE rated separately, Performance = the weaker; both sub-ratings and
  the reason shown. TE: 5y calculated with an index series, else factsheet 3y labelled "3y (factsheet)";
  note when periods differ.
- Ratings compare values at the stored 2 d.p. (a value on a limit counts as within it).
- `precedence.py` is part of the module list (spec Section 11).
- Active fund Mandate: "Manual check" ("Style and holdings need a reviewer check"), tick box in the
  approval section, does not block the verdict.
- CHECK DATA on Value or Fees: verdict "Monitor (data check needed: Value)".
- `performance_fee_justification`: optional, written by a person only; an AI agent must never write it.
- Agents: structured output validated with Pydantic; retry once on invalid output, then CHECK DATA.
  Unit tests mock AI calls; live tests only with `pytest --run-live`. Each agent's model is set in
  `config/models.yaml` (nothing hard-coded); `FUND_MODEL_<AGENT>` may override one agent for testing.
  Temperature is sent only to models the config marks `supports_temperature`; others get a low
  reasoning effort. The key comes from the `OPENAI_API_KEY` environment variable, loaded from `.env`
  by python-dotenv.
- Mandate Agent: the profile wins on any disagreement (flag); it classifies a free-text secondary
  objective into the six types, or CHECK DATA if it cannot.
- Who writes what (v1): code writes all findings (finding 1: Mandate and Performance ratings with their
  reasons; then one per data note, fixed wording; "pp (percentage points)" defined at first use) and the
  actions (`actions.py`, word for word, each with its fixed "when"). The Oversight Analyst (gpt-5.4, low
  reasoning) writes only the market context: plain English, at most 3 sentences, direction only, no figures,
  [n] citations; not called without sources. v2: AI-written insights once canonical phrasing per data note
  is defined. Data notes state what they "explain".
- Code checks on the market context: no figures, label and rating guards, no minus after "behind", no URLs,
  citations to existing sources, periods in words, at most 3 sentences. Rewrites: code checks 2, Evaluator 1
  (thresholds.yaml); each rewrite gets every issue so far and must keep earlier-passed rules. Then the
  market context is left out + flag "AI text failed checks: number / rating / wording; market context left out".
- Research (`agents/research.py`): approved sources in `config/sources.yaml` are fetched by code
  (`fetch.py`; no AI chooses URLs) and summarised by a Search agent with no web tool, with the same
  checks as web results. A failed or nearly empty page: info flag + a code-written web search, taking
  the budget first. Then at most 3 web searches in total (config), only for fund/manager changes and
  market drivers. Planner gets public fund details and ratings only; searches run in parallel, one
  each, no retries; failures are left out with a flag. Market-driver
  queries never name the fund (code drops them). Summaries with no date, outside the review period,
  or with fund/index returns >0.5 pp from the factsheet are excluded with an info flag (only figures
  described as returns with a period are checked; fees and tax rates are not returns). Identical URLs
  kept once. Market news may be dated up to 31 days after the period end (`config/sources.yaml`). Market
  context cites [1], [2]; URLs only in the report's sources list. No minus sign after "behind"/
  "below" (code check). "As at" dates count; approved sources and fund/manager news may be dated
  after the period end (excluded only before the start), market news keeps the strict window. Fund
  news must match name/ISIN/share class (no sec.gov for non-US funds), market news must name the
  market. v2: MCP Fetch for agent-chosen URLs.
- Risk-free rate: 0 for v1, with a flag. Prefer the factsheet Sharpe ratios where supplied.
- Charts are built in step 9 with the report.
- Report (step 9): 3 main pages (Summary; Mandate and performance; Value, fees and AoV) plus an
  appendix, 4 pages, 5 at most. Over 5: shorten the appendix first; a main page running over is an
  error. Saved to `runs/<timestamp>/` with `facts.json` and `run_log.txt`; `--offline` skips AI steps.
  Plain wording (decision path, fee note) is for the report only; facts.json and the Analyst keep the codes.
- Emailing the report is a plain code function (`emailer.py`, not an AI agent), off by default
  (`config/settings.yaml`). Resend over HTTPS, as in the old app (RESEND_API_KEY, EMAIL_FROM in .env).
  Recipients come only from the EMAIL_TO environment variable (never the public repo).
- Evaluator (step 10, gpt-6.1-sol): judges only the market context on 5 checks (no_rating_change,
  supported_claims, sources_cited, check_data_handled, plain_english); output {pass, issues} only; runs only
  on drafts that pass code's checks. Rejected -> "AI text failed quality check: the Evaluator rejected the
  draft (...); market context left out"; unreachable or no valid answer -> "AI text not quality-checked: ...".
  Everyday market words are fine; it gets the glossary. Citation dates (code, before it): a sentence may
  not describe a month after its cited source's date; counts as a quality issue (uses its rewrite).
- Search agent summarises only the page whose URL it returns. Duplicate URLs are dropped before any other
  vetting check, so a kept approved page is never also listed as excluded.
- Planner queries: plain words only; code removes search operators (site:, inurl: ...).
- Controller (step 10, `controller.py`): stops (RunStopped) only when the run cannot be scored (missing or
  invalid inputs, unreadable prices, report not fitting); blocking data checks give CHECK DATA, not a stop.
  Extractor runs before data checks. Timeouts per AI step in `config/settings.yaml`. log.json per run;
  the report's sources list comes from it.
- Front end (step 11): `src/fund_performance/web.py` + `app.py` (Gradio; Render runs `python app.py`,
  blueprint in `render.yaml`). Public-data warning first; demo = made-up fund in `demo/sample_index_fund`
  (offline). Results table has a "Why" column. AI runs need the in-page login when APP_USERNAME/APP_PASSWORD
  are set; without login only the offline demo runs; on a server with no login set up AI runs are off.
  Page events are private (not in Gradio's API). The old root-level app was removed in step 11.
- Value and Fees reasons (findings, report, page) give the peer return gap and the fee gap (`plain.py`,
  from the figures the scorecard keeps in `Pillar.values`).
