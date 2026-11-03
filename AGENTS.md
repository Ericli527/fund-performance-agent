# AGENTS.md

## Project Summary
Fund Performance Agent is a Python/Gradio application for investment oversight. It combines deterministic fund and benchmark analysis with AI-assisted document extraction, research, investment commentary and PDF reporting. A human analyst reviews and signs off the output.

## Goals
- Produce clear, evidence-based fund reviews with useful dashboards and Executive, Detailed and Research Brief PDFs.
- Explain mandate, performance, value, fees, risks and follow-up actions in plain English.
- Make routine analysis and reporting faster without replacing analyst judgement.

## Success Criteria
- Figures, ratings and conclusions agree across saved facts, dashboard and PDFs.
- Every material claim has a traceable source or a clearly stated limitation.
- Incompatible currencies, pricing bases, dates and peer classes are never silently compared.
- Important checks pass; the app remains usable with missing optional evidence.
- Changes are focused, understandable and maintainable.

## Code Standards and Guidelines
1. **Simpler is better.** Prefer small changes and reuse existing helpers; do not overengineer.
2. **Code calculates; AI explains.** Python owns numbers, scorecard thresholds and ratings. AI may extract, research and draft text, not invent figures or override deterministic decisions.
3. **Evidence before confidence.** Clearly distinguish verified, indicative, missing and incompatible evidence. Never fabricate history, sources, returns or approvals.
4. **Be concise.** Write short, useful documentation and comments only where they help. Do not add decorative emojis to code or documentation.
5. **Avoid needless defensive programming.** Validate at real input/trust boundaries; handle expected failures without blanket exception handling or repeated checks.
6. **Protect secrets and private data.** Keep credentials in environment variables / ignored `.env`. Never commit files from `data/`, private fund documents, personal information or answer keys. Use public or synthetic data for model calls unless expressly authorised.
7. **Protect financial logic.** Do not change `config/thresholds.yaml`, financial formulas, scorecard rules or golden baselines without explicit approval. Keep human sign-off mandatory.
8. **Test what changes.** Run relevant focused tests; for consequential changes run the non-live regression suite and golden-facts checks. Mock AI in unit tests. Never silently update baselines to make tests pass.
9. **Keep the workflow safe.** Create or update a focused draft PR, explain meaningful limitations and test results, and do not merge or deploy without the owner's approval.

## Repository Guide
- App: `app.py`; package: `src/fund_performance/`.
- Inputs and orchestration: `intake.py`, `controller.py`; calculations and ratings: `calc.py`, `peers.py`, `scorecard.py`.
- UI and reports: `web.py`, `dashboard.py`, `charts.py`, `executive.py`, `report.py`, `research_brief.py`.
- AI agents: `src/fund_performance/agents/`; models and limits: `config/`.
- Tests: `tests/`; current work/handover: `CODEX_HANDOVER.md`.
- Design/reference material: `docs/FUND_PERFORMANCE_AGENT_SPEC.md` (historical details may be superseded by tested code and approved PRs).

If documentation conflicts with current code or decisions, investigate and call out the discrepancy rather than following an obsolete instruction blindly.
