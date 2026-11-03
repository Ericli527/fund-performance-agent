# Stage 7 investment reporting presentation

## Design reference

The owner's three-page NotebookLM Fidelity Index US oversight report is a **visual and editorial reference only**, not a financial or governance authority. Borrow its restrained navy headings, structured fund/performance comparisons, explicit governance-insight language and actionable oversight steps. Do **not** reuse unverified financial figures, external ratings, source attributions, or claims that a committee approved the fund.

## Dashboard

- Preserve the existing four sections, metrics, charts, and data-quality warnings.
- Show **Python quantitative rating versus AI proposed rating** in a compact table. Keep the AI rationale, evidence IDs, limitations and further-review requirement visible, not just a score.
- Where they differ, show a governance insight requesting evidence review rather than treating the difference as an automatic error.
- Present Assurance Judge inspection separately: decision, explicitly uncalibrated likelihood, four rating reviews, report standards, material findings, next actions, and report coverage.
- Keep human sign-off prominent. An AI PASS is not approval; PDF page-layout inspection remains unavailable until a vision inspection feature exists.

## PDF reports

- Executive: show the four AI proposals alongside Python ratings in a compact strip with a disagreement marker and an explicit human-review disclaimer. Continue using the existing benchmark/fees/risk views and sign-off box; never squeeze content by dropping material information.
- Detailed: use a comparison table, a separately labelled **Governance insight** when ratings differ, and full evidence-referenced explanations and limitations. Keep the detailed evidence, source and audit appendices.
- Research Brief: do not imply this report exists on `main` until the earlier Stage 6B branch-integration issue is resolved.
- Avoid fabricated performance histories, unverified peer data, misleading fee equivalences and false approval dates.

## Acceptance checks

1. Existing financial golden facts and scorecard values do not change.
2. UI and PDF correctly distinguish the AI proposals from deterministic ratings, including disagreement and evidence-gap cases.
3. The Assurance Judge does not make new calls merely because a saved results view is opened.
4. Use real rendered PDF page images to review typography, table breaks, chart legibility and overflow. Check Executive page targets and allow an informative overflow rather than cutting content.
5. Run the full non-live CI suite; run authorised public-fund reviews separately when the relevant source packs are available.

This stage changes presentation only; no prompts, model settings, extra model calls or financial calculations are changed.
