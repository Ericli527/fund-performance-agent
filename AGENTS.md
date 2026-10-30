# AGENTS.md

Instructions for AI coding agents (e.g. OpenAI Codex) working on this repository.

- Follow `CLAUDE.md`: its rules and agreed decisions apply to every agent, not only Claude Code.
- The build specification is `docs/FUND_PERFORMANCE_AGENT_SPEC.md`. Follow it exactly; if something is unclear or
  conflicts with the code, stop and ask the owner.
- Current state and next steps: `CODEX_HANDOVER.md`.

Key rules (details in `CLAUDE.md`):
1. Code does all calculations and ratings; AI agents only read, search and write text.
2. Never change `config/thresholds.yaml` unless the owner asks.
3. Never use `data/answer_key/` as input. Never commit anything in `data/` (public repository).
4. Keep API keys in `.env` only. Public data only: the API key has OpenAI data sharing on.
5. Write and run tests for every change; `tests/test_golden_facts.py` must pass unless a calculation change is
   deliberate and approved.
6. Work one stage at a time and stop for the owner's review.
