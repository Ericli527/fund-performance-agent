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
- Ambiguous dates: use the format that gives one price per month in date order (oldest or newest first, one
  direction, every step a month apart, with an info flag naming the order chosen and the dates); if both formats
  do, or neither does, stop and ask the user.
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
  the budget first. Then at most 5 web searches in total (thresholds.yaml limits, a maximum not a target),
  proposed by the Task Planner (topic, query, objective, relevance; no separate research planner) for fund/manager
  changes and market trends, benchmark developments and risks. The Task Planner gets public fund details only;
  one Search Agent; searches run in parallel, one each, no retries, alongside the calculator (a background task;
  the financial review never depends on it); failures are left out with an info flag. Market-driver
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
- Reports (step 9, redesigned in UX stage 3): `report_executive.pdf` (2 pages as a target: Overview; Comparisons and
  decision) and `report.pdf` (Detailed: the executive pages + Appendices A-D, free length). Material warnings are
  never shortened; executive content that needs more room runs to a third page with an info note (Version 1), never
  a silent cut and never a rejected report; only a broken structure is a layout error. Saved to `runs/<timestamp>/` with `facts.json` and `run_log.txt`; `--offline` skips AI steps.
  Plain wording (decision path, fee note) is for the report only; facts.json and the Analyst keep the codes.
- Emailing the report is a plain code function (`emailer.py`, not an AI agent), off by default
  (`config/settings.yaml`). Resend over HTTPS, as in the old app (RESEND_API_KEY, EMAIL_FROM in .env).
  Recipients come only from the EMAIL_TO environment variable (never the public repo).
- Evaluator (step 10, gpt-6.1-sol; not called in Version 1, the Judge reviews the market context): judges only the market context on 5 checks (no_rating_change,
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
  (offline). Results table has a "Why" column. Login: with APP_USERNAME/APP_PASSWORD set, the page asks for them
  before it opens (Gradio auth); on a server with no login set up AI runs are off (offline demo only). AI-run
  limits (per day, one at a time) in `config/settings.yaml`. Page events are private (not in Gradio's API).
  Main route = documents (price file + factsheet, optional KID and peer factsheets) read by the Extractor and
  Mandate agents, then run straight on: no confirmation table. Code checks itself (`intake.self_check`): values
  not found in the documents are warnings; a required value nobody could read stops the run. JSON = "Advanced".
- Input page (UX stage 1): review-type cards (fill in the question only; all ratings always calculated), review
  question, two required uploads with check lines, audience (recorded only for now), "Additional options" (KID,
  peers, JSON), "Run Fund Review" + "Use Demo Files", public-data note, "Help & methodology". No Offline switch:
  the unchanged demo runs offline; `FUND_REVIEW_OFFLINE=1` for development. `tests/test_golden_facts.py` guards
  every figure and rating (baselines: tests/golden/, data/test1/golden/).
- Results dashboard (UX stage 2, `dashboard.py`, presentation only): investment assessment and evidence quality
  shown separately (evidence from code's checks and all run flags; never "verified"; "Not final" while data issues
  remain); 3 headline figures from the facts with period/unit/source ("Not available", never zero); items needing
  attention; four ratings; collapsible detail; Technical details (plan, drafts, Judge, info flags, log.json). The
  audience changes the view only (Analyst: detail open; Management: key decisions). RunResult carries every flag.
- Peers: approved peers per benchmark in `config/peers.yaml` (factsheets in `data/peers/`, found by ISIN), used when
  no peer is given. Peer checks in `peers.py`: returns only in the fund's currency (else fees only, info flag);
  noon vs noon NAV, market close vs PNAV; share class type and minimum investment (institutional note);
  income/accumulation shown. Several peers: Value = average gap over usable peers, Fees = average OCF of all.
- Verdict names for people: Retain -> "Satisfied", Monitor -> "Monitor", Review -> "Action needed" (codes stay in
  facts.json and the scorecard). Page 1: suggested conclusion, points for judgement (max 4) and questions for the
  manager (2-4), all code-built (`conclusion.py`); the conclusion passes the number/label/rating checks. Approval
  box has "Analyst's comments" and "If you disagree with the suggested verdict, why?".
- Shared presentation helpers (`presentation.py`): headline figures, evidence quality, caveat, risk rows, chart
  choice, insufficient evidence vs performance concerns; used by the dashboard and both PDFs (consistency tested).
  Email attaches the Executive Report by default (`email.attachment: detailed` for report.pdf). Downloads and attachments are
  named `{Fund_Name}_{Executive|Detailed}_Report_{YYYY-MM-DD}.pdf`; the run folder keeps report.pdf/report_executive.pdf.
  A blocking currency or benchmark mismatch (`presentation.comparison_invalid`) replaces the executive chart with an
  explanation, and no fund-vs-index figure is presented as reliable: findings, points and questions drop the data-note
  comparisons; dashboard and Executive Report replace the gap, index and tracking figures with "Not reliable"; the
  Detailed Report keeps them for audit, marked "not reliable: data check". The web page offers
  both PDFs: Analyst view = Detailed primary, Management view = Executive primary (no rerun). Evidence dashboard
  (Appendix A) is code only (`evidence.py`, charts): t-test level and min points in `config/settings.yaml`.
- Agent team (spec 8.6): Task Planner (menu choices only; code keeps all four ratings; default plan offline or on
  failure), Reporting Agent (explains the verified findings for one angle; facts only; must end with code's verdict
  sentence; code's checks), Judge (`ReviewResult`: approved, factual_issue, security_issue, conclusion_reasonable,
  clear_for_analysts, feedback; no text, numbers or ratings). Code decides: security -> code's conclusion; factual,
  reasoning or not approved -> one targeted rewrite; else pass (clarity alone never rejects). Each agent is a plain
  `Agent(name, instructions, output_type, **model_kwargs(...))`. Unit tests can never reach OpenAI (conftest blocks
  the real client).
- Agentic Tools V2.1 (`agents/reporting_tools.py`): the Reporting Agent fetches verified evidence with three read-only
  `@function_tool`s (get_fund_performance(period), get_oversight_scorecard(), get_peer_comparison()) instead of the
  whole facts payload; it gets a brief (fund, review date, the Planner's task plan, verdict sentence, sources). The
  tools read only this review's facts through the run context (`ReviewContext`, a private copy; no global state, no
  files), return code's stored figures as displayed and name what is unavailable (never estimated; an invalid
  fund-vs-index comparison is "not reliable"). Bounds: `drafting.reporter_max_turns` (4) model turns and 6 tool calls
  per draft; `drafting.reporter_tools: false` restores the payload. Code's checks and the Judge are unchanged.
- Value and Fees reasons (findings, report, page) give the peer return gap and the fee gap (`plain.py`,
  from the figures the scorecard keeps in `Pillar.values`).
- Test cases (Version 1, `docs/TEST_CASES.md`): "Choose a test case" offers Synthetic Demo, Fidelity Index US P Acc GBP,
  Vanguard FTSE Global All Cap Index Fund GBP Acc and Upload Your Own Fund. A real case runs the Live AI workflow by
  default where AI runs are on (else its Quick inputs); one whose private files are missing stays listed, names them
  and fills in nothing (never synthetic data). On Render the private case files go on a persistent disk named by
  FUND_DEMO_DATA (`scripts/check_test_cases.py` checks them); never in the repository.
- Real-fund demo library (Stage 4B, `demos.py`): metadata in `demo/library/*.yaml` (no document figures); inputs and
  documents private in `data/demos/<id>/` (gitignored, never on Render); a demo with missing files is not shown.
  "Try a demo" cards (Fidelity + HSBC Acc C peer; Vanguard FTSE Global All Cap): Quick Demo (default) = prevalidated
  quick inputs, offline; Live AI Demo only where AI runs are on (key, login on servers), within the run limit. The
  made-up fund stays for CI and the example input files. Code checks each demo's NAV 1/3/5y returns against the
  factsheet (0.05 pp). Golden baselines in `data/demos/golden/`.
- Price files: title rows above the column names, month names ("Sept"), currency-formatted values and newest-first
  order are read; prices after the review date are left out with an info flag (`review_date_cutoff`).
- Return basis: a `series` declared `annualised` stays annualised (its cumulative return derived by code; an
  annualised since-launch figure is never read as cumulative); the cross-check compares like with like.
- Peer `benchmark_name` (optional): a different variant from the fund's gets an information note only.
- Peer `as_of_date` (optional; read from an uploaded peer factsheet): a peer dated differently from the fund keeps its
  fee in the Fees comparison, but its returns are left out of Value (different periods), with an info flag. Vanguard's
  peer: HSBC FTSE All-World Index Fund Acc C (report 31 May 2026; FTSE All-World excludes small caps, disclosed).
- Fund profile `pricing_point`: must be given; `null` = not stated in the documents (info flag: a timing
  difference cannot be ruled out; the fund's NAV is compared as published). Never guessed.
- Ratings waiting for figures the documents do not give are "missing evidence" in the wording (evidence quality
  "Evidence missing", "obtain the evidence missing for ..."), not a data check; ratings and verdict codes unchanged.
- Deployment safety (Stage 6B): AI runs only when `AI_RUNS_ENABLED` is true (default off) and, on a server, the
  login is set; the login alone never turns AI on. Each review gets its own folder (`<time>-<random id>`); on a server
  run folders and Gradio's cached files older than `web.keep_runs_hours` (24) are deleted. Where no real-fund demo is
  installed (Render), the made-up fund is the Quick Demo (`demo/library/sample_index_fund.yaml`, fallback).
- Performance fee (Stage 6C): read from the documents' explicit words with the quote as evidence ("N/A", "None",
  "0%" = no; "20% ..." = yes; "excludes performance fees (where applicable)" is not evidence). Not established =
  `null` (warning, missing evidence), never taken as no fee: Fees that would be Green becomes CHECK DATA (verdict rule
  "Monitor (data check needed: Fees)"); Amber/Red stand with a missing-evidence note. The review is not stopped.
- Live progress (Stage 6C): "Step X of 5 · agent or component · status", sent by the controller as each step really
  starts (`controller.STAGES`); skipped AI steps are not announced.
- Version 1 workflow: one Reporting Agent draft (`drafting.max_drafts: 1`), one Judge pass, at most one targeted
  rewrite accepted on code's checks (`rejudge_after_rewrite: false`); web research on (`research.enabled: true`):
  the Reporting Agent writes the cited market context (code's market-context checks: no figures, citations to
  existing sources, citation dates, at most 3 sentences; it never changes a rating), so the Analyst and Evaluator are
  not called (their code stays, with its tests); email off. Optional AI steps (Task Planner, Mandate, Extractor in the controller, research, AI text,
  drafts) never destroy a review: an unexpected error or timeout gives the step's fallback and a flag with the reason;
  a critical step's error stops the run naming "Step X of 5 (component)". One OpenAI trace per review (the page's
  reading agents included); log.json records run_id, trace_id and every AI call (agent, attempt, seconds, outcome).
  Progress shows "▶" when a step starts and its outcome (✓ done, ↷ skipped, ✗ failed) when it ends.
- Executive summary: AI drafts over `drafting.max_summary_chars` (700) fail code's checks; an Executive Report that
  still runs past two pages keeps everything and says so (info flag).
