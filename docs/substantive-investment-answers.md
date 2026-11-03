# Substantive investment answers

The Reporting Agent targets 2–3 paragraphs and approximately 150–200 words: mandate and conclusion, outcomes/value/
charges, then material risks and actions. Shorter evidence-limited answers remain valid. Desktop line counts depend
on viewport and font, so they are not enforced. The sentence ceiling is twelve; the existing 3,000-character
answer-plus-findings/action limit, numerical guard, citation validation and independent review remain in place.
Blank-line paragraph boundaries survive normalisation, dashboard HTML and the PDF answer fallback. Key findings and
next steps remain separate. Reviewed partial assessments are labelled evidence, not an invented approved conclusion.

The Analyst receives only the rubric retrieved from documented objective and mandate interpretation, with a general
fallback for uncertain strategy. This is context retrieval, not a Python investment rating. The LLM must confirm
its applicability. The Quality Reviewer receives the same selected rubric. Fee examples remain dated contextual
research and are not numerical authority. No model settings, financial calculations or scoring thresholds change.

The illustrative 3-paragraph Vanguard answer in tests/test_substantive_answers.py uses synthetic matching facts.
It explains 11.31% and 11.60% annualised returns, 0.23% OCF, unverified relative competitiveness, risks and sign-off.
It is a rendering/pipeline fixture, not an actual live assessment or investment recommendation. Additional mocked
cases cover -14.9%/-15% tracking, 20%/25% underperformance, fees without peers and essential evidence conflicts.
No additional model call is introduced. Shorter strategy context should reduce repeated guidance, while longer
answers may increase output tokens; no measured live cost or latency improvement is claimed.
