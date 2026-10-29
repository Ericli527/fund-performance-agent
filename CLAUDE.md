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
- Risk-free rate: 0 for v1, with a flag. Prefer the factsheet Sharpe ratios where supplied.
- Charts are built in step 9 with the report.
- Emailing the report is a plain code function (not an AI agent), off by default, set up in
  step 10. Recipients come from settings only.
- The old app (root-level `*.py`) keeps running until the new front end replaces it in step 11.
