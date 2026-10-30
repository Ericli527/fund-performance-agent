# Codex handover: Fund Performance Review

Read `CLAUDE.md` (rules and agreed decisions) and `docs/FUND_PERFORMANCE_AGENT_SPEC.md` (the build spec) first.
Principle: **code does every number and rating, AI reads and writes text, a person decides.**

## 1. Architecture and important files

Python 3.13, Gradio 6.30 web app, PDF via xhtml2pdf + matplotlib, OpenAI Agents SDK. Deployed on Render from
`main` (`render.yaml`, `python app.py`). Package: `src/fund_performance/`.

Flow: page (`web.py`) → document reading (`intake.py`) → workflow controller (`controller.run_review`) →
`facts.json` → PDF (`report.build_report`) → dashboard (`dashboard.py`).

| Area | Files |
|---|---|
| Entry points | `app.py` (web), `run_report.py` (CLI) |
| Page and results | `web.py` (inputs, login, limits), `dashboard.py` (results, presentation only) |
| Inputs and checks | `io.py`, `checks.py`, `intake.py` (`self_check`), `models.py` |
| Calculations and ratings (do not change without owner approval) | `calc.py`, `precedence.py`, `peers.py`, `evidence.py`, `mandate.py`, `scorecard.py`, `config/thresholds.yaml` (never change unless asked) |
| Facts and code-written text | `facts.py`, `conclusion.py`, `actions.py`, `plain.py`, `glossary.py`, `number_guard.py` |
| AI agents (`agents/`) | extractor, mandate, task_planner, research (planner + search), analyst, evaluator, reporter, judge; models in `config/models.yaml` |
| PDF | `report.py` (pages, CSS, 5-page check), `charts.py` |
| Config | `config/settings.yaml` (timeouts, web limits, statistics, drafting, email), `config/peers.yaml`, `config/sources.yaml` |

Data: `data/` is gitignored (public repo). Test 1 files live in `data/test1/`, approved peer factsheets in
`data/peers/`. Demo (made-up fund): `demo/sample_index_fund/`.

## 2. Completed on branch `claude/ux-redesign`

- **Stage 0**: `tests/test_golden_facts.py` compares the whole facts JSON of offline runs with baselines (demo in
  `tests/golden/`; Test 1 and Test 1 + approved peers in `data/test1/golden/`, local only). Update deliberately with
  `PYTHONPATH=src python tests/test_golden_facts.py --update`.
- **Stage 1 (input page, `web.py`)**: header; three review-type cards (fill in the review question only; all four
  ratings always calculated); editable question; two required uploads with check lines; report audience;
  "Additional options" (KID, peer factsheets, JSON); "Run Fund Review" + "Use Demo Files"; public-data note;
  "Help & methodology". **No Offline switch**: the unchanged demo runs offline; `FUND_REVIEW_OFFLINE=1` for
  development; CLI keeps `--offline`. Theme: light neutral, navy headings, muted blue, Inter with fallbacks.
- **Stage 2 (results, `dashboard.py`)**: hidden until a run finishes; PDF download button; header (fund, ISIN,
  period); investment assessment and evidence quality shown **separately** ("Not final" while data issues remain;
  never "verified"); summary + material concerns; 3 headline figures with period/unit/source ("Not available",
  never zero); items needing attention; four ratings; collapsible detail; Technical details (plan, drafts, Judge,
  info flags, log.json, plain-text summary). Audience changes only the view (Analyst: detail; Management: key
  decisions). `RunResult` now carries every flag of the run.
- Tests: 555 passed, 6 skipped (live AI) at the last full run. Docs (spec step 11, CLAUDE.md, README) updated.

## 3. Remaining: Stage 3 PDF redesign (not started)

Agreed plan (presentation only; same facts, ratings and figures; golden facts must still pass):
- Page 1: verdict, conclusion, four ratings, points for judgement, questions for the manager, approval box
  (must stay on page 1). Owner to confirm: move key findings and actions from page 1 to page 3.
- Dashboard page: shorter one-line chart captions (source + period); significance test as one plain sentence
  with numbers in small print; tidy grid when a chart is missing.
- Mandate and performance page: keep returns and calendar tables; show only the risk group used for the rating,
  move the others to the appendix; consistent wording ("gap to the index (tracking difference)").
- Keep: 5 pages maximum (appendix shortened first, a main page overflow is an error), sources on every figure,
  xhtml2pdf limits (tables for layout, no flexbox), same style as the web page.
- Update spec Section 9, CLAUDE.md, README; replace brittle page-text tests with meaning checks (see 4).

## 4. Known issues and test findings

- **No CI** (no `.github/`). 57 test functions need `data/test1/` and **skip silently** without it, including
  the spec's expected-figure checks in `test_calc`/`test_precedence` and the Test 1 golden cases.
- Golden facts cover only index-fund verdicts Satisfied and "Monitor until a peer is added". Missing end-to-end:
  Action needed, Pending data check, active fund, short history, dual objective, daily/Excel prices, market-close
  fund without PNAV. Tests 2–4 still lack input files.
- No test that `facts.json`, the dashboard and PDF page 1 agree on verdict, ratings and headline figures.
- Brittle tests: `test_report` page-text checks (rewrite with Stage 3), Gradio internals in `test_web`, exact
  lists in `test_glossary` and `test_agent_base`.
- Outdated names in `test_intake` ("confirmation", "user marks"): the page no longer lets users correct values, so
  the "Entered by user" path is now reached only by tests and partly the CLI. Rename or retire on purpose.
- UI: arrow keys do not move between review cards (Gradio gives each radio its own name; Tab + Space works).
  Phone tables scroll sideways. Headline figures are index-fund oriented. A recommended action mentions "pages 2
  to 4" of the current PDF.
- Unmerged: `claude/ux-redesign` is not merged to `main`, so Render still serves the pre-Stage-1 page.
- Live AI runs need `OPENAI_API_KEY` in `.env`; this API key has data sharing on: public data only.

## 5. Commands

```bash
pip install -r requirements.txt
cp .env.example .env                      # OPENAI_API_KEY; APP_USERNAME/APP_PASSWORD optional locally
python app.py                             # http://127.0.0.1:7860
FUND_REVIEW_OFFLINE=1 python app.py       # every review without AI (development)
PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline

# UI work (~20 s)
pytest -q tests/test_web.py tests/test_dashboard.py "tests/test_golden_facts.py::test_facts_and_ratings_match_the_baseline[demo]"
# Anything near numbers (~15 s)
pytest -q tests/test_calc.py tests/test_checks.py tests/test_io.py tests/test_precedence.py tests/test_scorecard.py \
  tests/test_mandate.py tests/test_peers.py tests/test_evidence.py tests/test_facts.py tests/test_number_guard.py \
  tests/test_golden_facts.py
# Before deployment (~70 s): only the 6 live tests may skip; more skips = data/test1 missing
pytest -q -rs
# Optional, costs API credit
pytest --run-live -q
```

## 6. Git state (at handover)

- Branch: `claude/ux-redesign`, in sync with `origin/claude/ux-redesign` (last commit `d1444f0`, Stage 2),
  3 commits ahead of `main` (`678e7b2`). No PR open for it yet.
- Uncommitted: only this file and `AGENTS.md` (new, not committed). Application code has no uncommitted changes.
