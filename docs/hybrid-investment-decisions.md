# Hybrid investment decisions

Python calculates and validates financial evidence and produces the existing quantitative scorecard. The existing
Investment Analyst independently proposes four evidence-referenced investment ratings; its Quality Reviewer checks
the proposals. When requested, the independent Assurance Judge reviews the proposals, scorecard and report text.
The human analyst retains final responsibility. Neither AI output changes a financial figure or scorecard rating.

The investment assessment JSON retains the original recommendation and includes, for example, this rating among its
four required dimensions (illustrative only):

```json
{
  "dimension": "Performance",
  "proposed_rating": "AMBER",
  "quantitative_scorecard_rating": "GREEN",
  "agreement": false,
  "rationale": "Recent tracking concerns warrant monitoring despite the scorecard result.",
  "supporting_evidence": ["performance:5y", "risk_quality"],
  "limitations": ["The significance of the recent tracking concern requires verification."],
  "further_review_required": true
}
```

Rating references and original scorecard values are validated, numerical claims are checked against supplied
evidence, and the existing Quality Reviewer must accept the assessment before its ratings are presented. A valid
reference is not itself proof that it supports a claim. If the assessment remains materially unsupported, ratings
are withheld. Original structured attempts are stored in the run's `investment_assessment_audit.json`, including
unreviewed content, for audit; they are not rendered as approved output. These files share the run's retention and
privacy requirements.

The Judge cannot change either rating. Its result is available only after the opt-in Inspect Report action and
requires one additional model call. The existing Analyst and Quality Reviewer calls are reused, with at most the
existing single revision. Any Judge likelihood is an uncalibrated opinion about report quality, not future returns.
The Judge currently reads PDF text, not page images; visual quality is explicitly unassessed. The current main
branch does not generate a Research Brief, so it is reported as unavailable. No live model performance or
statistical calibration is claimed. The Analyst and Judge system prompts are in `agents/investment_analyst.py` and
`agents/assurance.py` respectively.
