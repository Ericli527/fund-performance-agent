# Optional Investment Assurance Judge

After a completed review, **Inspect Report** runs one additional AI call (subject to the existing AI switch, login and daily/concurrency limits). It uses the configured Judge model and the `FUND_MODEL_JUDGE` override. The prompt is in `src/fund_performance/agents/assurance.py`. It receives a session-local, read-only snapshot of the question, fund profile, financial facts, scorecard, peer and research evidence, existing investment assessment and extracted PDF text. It does not browse or modify the review. Inputs are untrusted; tracing is disabled for this call and raw report text is not added to the run log.

The current version extracts text from available PDFs; it does not send rendered page images or inspect visual layout. Missing, unreadable and truncated reports are labelled in the result. Results are shown in the session; they are not persisted as human decisions. The versioned result includes the run ID so future human labels can be associated with it without implementing speculative calibration.

Illustrative result (not an actual assessment):

```json
{
  "schema_version": 1,
  "run_id": "example-run",
  "review": {
    "decision": "REVISE",
    "pass_likelihood_pct": null,
    "likelihood_calibrated": false,
    "confidence": "MEDIUM",
    "decision_reason": "Peer comparability requires clarification.",
    "likelihood_explanation": "There is insufficient evidence for an estimate.",
    "supporting_factors": ["The scorecard records its rationale."],
    "uncertainties": ["Peer return comparability remains limited."],
    "rating_reviews": [
      {"dimension": "Mandate", "original_rating": "GREEN", "judgement": "SUPPORTED_WITH_QUALIFICATIONS", "reason": "Review tracking evidence.", "evidence_references": ["scorecard"], "recommended_action": "Verify the tracking basis."},
      {"dimension": "Performance", "original_rating": "GREEN", "judgement": "SUPPORTED", "reason": "The available evidence supports the rationale.", "evidence_references": ["performance:5y"], "recommended_action": "Continue monitoring."},
      {"dimension": "Value for investors", "original_rating": "MANUAL CHECK", "judgement": "INSUFFICIENT_EVIDENCE", "reason": "Peer return comparability is limited.", "evidence_references": ["peers"], "recommended_action": "Obtain a comparable peer or document a manual review."},
      {"dimension": "Fees", "original_rating": "GREEN", "judgement": "SUPPORTED_WITH_QUALIFICATIONS", "reason": "Fee measures require qualification.", "evidence_references": ["peers"], "recommended_action": "Check cost coverage."}
    ],
    "report_quality": {"factual_accuracy": "PASS", "investment_reasoning": "REVISE", "evidence_completeness": "REVISE", "professional_clarity": "PASS", "governance": "PASS"},
    "visual_inspection": {"performed": false, "findings": [], "limitations": ["Rendered page images were not available."]},
    "material_findings": [{"severity": "MODERATE", "issue": "Peer comparability is limited.", "evidence_references": ["peers"], "recommended_action": "Clarify the limitations."}],
    "human_review_required": true,
    "security_issue": false
  }
}
```

Any likelihood is an **uncalibrated LLM estimate — not a statistically validated probability**, and refers to a human reviewer judging reporting standards, not future investment performance. A PASS never means human approval. Python checks schema, evidence references, original rating attribution, numerical consistency and visual-claim restrictions; it does not compute the decision or a weighted quality score.
