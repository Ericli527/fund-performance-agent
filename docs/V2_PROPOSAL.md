# V2 architecture proposal

The chat interface and separate benchmark inputs are already on the current main branch. The latest local remote-tracking branch also contains the two-narrative work. Live GitHub PR status could not be checked in this environment; check it before opening dependent PRs.

The existing Extractor reads documents; Mandate classifies the objective; Task Planner chooses priorities and searches; Search gathers research; Analyst writes market context; Reporter writes dashboard and executive narratives; Judge reviews drafts. Evaluator and the earlier research planner remain available but are not used in the main workflow. The Mandate Agent remains useful for classification and conflict checks; merging it into extraction now would risk losing those checks.

First extend the existing per-run reporting tools and pure evidence accessors rather than duplicating financial formulas. The planner needs mandate and exposure access; the analyst needs performance, scorecard, peers, fees, quality and research; communicators need the same evidence and both assessments. Extract portfolio evidence with source locations in a later increment; absent evidence must remain unavailable. Move mandate interpretation ahead of planning, then leave calculations and research concurrent. Gradually move orchestration details out of the controller as structured handoffs mature.

Keep numerical, evidence, source, injection and isolation checks. Review duplicate draft retries and stylistic guards only after the new quality reviewer is in place; do not remove safeguards speculatively. Preserve the existing deterministic scorecard independently of qualitative AI recommendations.

The first increment adds no separate agent calls, but tool use may add model turns; measure actual calls and runtime in the run log. Later increments add an analyst and research output while replacing overlapping drafting/review calls where safe. Read-only shared services reduce duplication. The existing chat interface must keep its question and benchmark inputs, and all changes should build on the current main branch in focused, reviewable increments. No merge or deployment is included.
