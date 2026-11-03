# Rating evidence contract

The old InvestmentRating schema described supporting_evidence as strings but validated every string as an exact
source identifier. A useful claim such as “The fund lagged the benchmark ... [performance:5y]” therefore failed
reference validation. The revised contract separates readable supporting_evidence claims from exact
 evidence_references. The same numerical guard still checks all rating text. Embedded citations must agree with
structured references, and the independent reviewer checks claim/source support, not merely identifier existence.
The existing one-revision budget, independent judgement and human sign-off remain in place.

Saved older assessments can still be displayed: consumers use the old ID-only field when the new reference field
is absent. New model output must supply separate references. No ambiguous citation is silently remapped.

The request includes illustrative Vanguard claims and metrics but no complete pair of raw model outputs or original
run pack. Tests cover the embedded-citation and plain-claim patterns with synthetic matching facts; they do not
establish that the private Vanguard source evidence supports those figures. No paid live review is claimed.
