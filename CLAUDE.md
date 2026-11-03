# CLAUDE.md

## Project Summary
Fund Performance Agent is an AI-assisted investment oversight app. Python calculates financial evidence and the quantitative scorecard; AI proposes evidence-grounded investment ratings, an independent Judge challenges them, and a human analyst makes the final decision.

## Goals
- Improve reliable fund analysis, clear dashboards and professional PDFs.
- Keep financial comparisons evidence-based and transparent.
- Make changes small, readable and practical.

## Success Criteria
- No invented figures, sources or approvals.
- Saved facts, ratings, dashboard and PDFs remain consistent.
- Relevant tests pass, and important limitations are reported.
- No private data or credentials are committed.

## Code Standards and Guidelines
1. **Keep it simple.** Avoid overengineering, unnecessary abstraction and repeated safeguards.
2. **Use the shared rules in `AGENTS.md`.** They are the single source of truth for all coding agents.
3. **Respect financial boundaries.** Code owns calculations and the quantitative scorecard; AI proposals are separate and cannot override either. Do not change thresholds or golden baselines without approval.
4. **Be concise.** Use comments only when helpful; keep documentation short and avoid emojis.
5. **Handle real errors, not imaginary ones.** Validate inputs and external/model outputs, but avoid blanket exception handling.
6. **Test focused changes.** Mock live AI calls in ordinary tests and run the relevant non-live checks.
7. **Do not merge or deploy** without explicit owner approval. Leave a clear draft PR and handover.

## Working Context
Read `AGENTS.md` first. Inspect the current code and relevant tests before editing. Use `CODEX_HANDOVER.md` for current tasks and `docs/FUND_PERFORMANCE_AGENT_SPEC.md` for background; older notes may be out of date.

Run with the repository's existing Python environment and documented commands. **No `uv` requirement.**
