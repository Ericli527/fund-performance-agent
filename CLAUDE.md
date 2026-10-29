# CLAUDE.md

Instructions for Claude Code in this project. The build specification is
`docs/FUND_OVERSIGHT_AGENT_SPEC.md`.

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
