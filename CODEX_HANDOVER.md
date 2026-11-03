# Fund Performance Agent — Coding Handover

Hybrid investment decision work is stacked on PR #51. Python retains financial calculations and the quantitative
scorecard; the existing Investment Analyst proposes evidence-referenced ratings, its Quality Reviewer checks them,
and the optional Assurance Judge independently challenges both. Human sign-off remains required. A Research Brief
is unavailable on the current main branch and is disclosed as unavailable.

Read `AGENTS.md` for shared rules; `CLAUDE.md` is a short Claude-specific entrypoint. This file is a **working map**, not an instruction to rebuild past stages. Confirm the current branch, merged PRs and tests before making changes.

## Project Summary
Python 3.13 / Gradio investment-oversight application. Python performs financial calculations and deterministic scorecard ratings; AI agents help extract, research, analyse and draft commentary; a human analyst verifies and signs off. The app produces an interactive dashboard plus Executive, Detailed and Research Brief PDFs.

## Goals
- Deliver reliable, explainable mandate, performance, risk, value and fee reviews.
- Keep financial claims traceable to source data and display meaningful qualifications.
- Maintain a simple UI, readable reporting and efficient AI calls.

## Success Criteria
- `facts.json`, dashboard, PDFs and AI commentary agree on figures, rating meanings and evidence limitations.
- Missing or incompatible evidence produces honest fallbacks rather than invented values.
- Relevant focused tests, golden-facts checks and non-live CI pass.
- No secrets, private fund documents or private demo inputs enter the public repository.

## Architecture and Key Files
- Entry points: `app.py` (web), `src/fund_performance/run_report.py` (CLI).
- Input and orchestration: `web.py`, `intake.py`, `controller.py`, `io.py`, `checks.py`, `models.py`.
- Calculations and ratings: `calc.py`, `precedence.py`, `peers.py`, `scorecard.py`, `facts.py`.
- AI: `src/fund_performance/agents/`; configuration: `config/models.yaml`, `settings.yaml`, `sources.yaml`, `thresholds.yaml`.
- Presentation: `dashboard.py`, `presentation.py`, `charts.py`, `executive.py`, `report.py`, `research_brief.py`.
- Tests and CI: `tests/`, `tests/test_golden_facts.py`, `.github/workflows/tests.yml`.

Typical flow: uploads/demo → extraction and validation → deterministic facts/scorecard → bounded AI research and assessment → dashboard and PDF generation → analyst review. Dashboard and PDF views must not re-run AI just to display a section.

## Current Capabilities (as of 3 November 2026)
- Four dashboard tabs: Overview, Performance & Risk, Portfolio & Research, Evidence & Actions. Clear key findings and rationale for Mandate, Performance, Value and Fees.
- Five-year fund-versus-benchmark growth chart from actual aligned observations. It distinguishes verified, indicative and unavailable evidence; no manual chart confirmation or fabricated time series. Annual tracking-gap chart remains secondary.
- Executive, Detailed and Research Brief PDF outputs, with shared facts and evidence qualifications. The two-page Executive and one-page Research Brief are **targets**, not a reason to hide material content.
- Separate deterministic scorecard and independent AI Investment Analyst, with a bounded quality-review/revision process. Research source availability and publication timing are qualified; failed assessments retain safe diagnostics.
- Demo library: synthetic public example, Fidelity Index US P Acc GBP with an HSBC US index peer, and Vanguard FTSE Global All Cap GBP Acc with the State Street SPDR MSCI ACWI Acc ETF as its global-equity peer. Vanguard's benchmark stays FTSE Global All Cap; USD SPDR returns are excluded from GBP comparisons. SPDR TER may be compared to Vanguard OCF with disclosed limitations; Value can require Manual check.
- CI and focused regression tests cover financial consistency, evidence caveats, dashboard and report fallbacks. Live AI tests are opt-in.

## Known Limitations and Immediate Priorities
1. **Real-fund acceptance:** Repeat Fidelity and Vanguard live reviews with complete authorised source packs. Review Analyst conclusions, all four ratings, chart comparability and all three exported PDFs.
2. **Demo availability:** `demo/library/*.yaml` is public metadata only. Private files live under `data/demos/<id>/` or the configured `FUND_DEMO_DATA` root, outside Git. A merged manifest does **not** install private PDFs or JSON on Render. Confirm the deployment's actual private-file availability before claiming a demo works.
3. **Research and pricing:** Post-review sources are not contemporaneous evidence. A USD peer's published returns cannot be compared directly with GBP fund returns. Treat unknown pricing/return-treatment assumptions as indicative when defensible; known material conflicts need an honest fallback.
4. **Visual QA:** Synthetic PDF previews and CI do not replace browser and real-document inspection, particularly long narratives, mobile layout and pagination.
5. **Handover freshness:** Older design notes/spec sections may describe superseded agents, peers, model names or page layouts. Inspect current code, config and recent merged PRs rather than copying historical statements.

## Development Commands
Use the existing project environment; **there is no `uv` requirement**.

```bash
pip install -r requirements.txt
python app.py
PYTHONPATH=src python -m fund_performance.run_report --data demo/sample_index_fund --offline

# Focused checks: choose files affected by the change
pytest -q tests/test_dashboard.py tests/test_web.py tests/test_report.py tests/test_golden_facts.py

# Full non-live regression and expected-skip audit
python -m pytest -m "not live" -q -ra --junitxml=test-results.xml
python scripts/check_test_skips.py test-results.xml
```

Check the repository's actual CI workflow for its authoritative non-live command and skip audit. Private fixtures are intentionally absent from public CI; skip counts vary by environment. Never use a paid live-model test by default or silently regenerate golden baselines.

## Working Rules and Delivery
- Work on a focused branch and open/update a **draft PR**. Do not merge or deploy without owner approval.
- Make small, evidence-grounded changes; test them; describe remaining limitations. Avoid extra LLM calls, overengineering and broad cleanup.
- Preserve `config/thresholds.yaml`, scorecard rules, financial calculations and golden facts unless explicitly asked to change them.
- Keep credentials in ignored environment files and avoid committing files from `data/`.
- Before handing off, record the PR/branch, what was changed, focused/full test results, blockers and the next concrete action.

## Stage 7: optional investment assurance

- `feat/investment-assurance-judge` adds an opt-in, one-call Investment Assurance Judge using the existing Judge model and AI limits. It reviews the completed review and extracted report text without changing calculations or ratings; human sign-off remains required.
- Results are session-only and include a schema version and run ID for future human-review comparison. Likelihoods are explicitly uncalibrated. No PDF page images are sent, so visual inspection is not performed. Research Brief coverage is reported unavailable when no such PDF exists.
- Details, example schema and limitations: `docs/investment-assurance.md`. Run focused assurance, web, controller and golden-facts tests before review. No live model evaluation has been performed.
