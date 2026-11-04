# Analyst evidence delivery

The previous Analyst prompt already contained a catalogue resolving the financial tools, yet still instructed the
model to call those tools. Its permitted six calls could be exhausted even though the information was present.
The user reported ten attempted calls with four refusals; the original private trace is unavailable locally, so
that specific live failure is not independently reproduced.

The Analyst now receives one detached package: identity and fee terms, the mandate/portfolio context, source-labelled
fund context, period-specific performance with unavailable/comparability flags, scorecard, peers and extraction
notes, risk figures/data restrictions, vetted dated research and the selected qualitative strategy rubric. The
catalogue uses the existing tool helpers and identifiers. Top-level duplicate scorecard/peer summaries are removed.
No raw documents or arbitrary truncation are added. The Analyst has no function tools and one model turn per attempt;
the existing single substantive revision and independent Quality Reviewer remain. Legacy tool helpers remain for
compatibility but are not exposed to this agent.

Agreement fields and copied quantitative ratings may be omitted/null in the proposal. Python derives them from the
unchanged scorecard and proposed ratings/recommendation. Exact citation-format equivalents (surrounding whitespace,
brackets and known performance/research separators) are repaired only when they resolve to an existing allowed ID.
No source is extracted from a narrative sentence or invented. Claims, recommendations, proposed ratings, rationale
and sign-off are not changed. Genuine disagreements still need explanation and independent review.

The private run audit retains the original proposal; diagnostics list normalised field paths and the final saved
assessment records canonical values. Attempt diagnostics include elapsed time, SDK usage where available, zero
exposed tools, successful/refused call counts (unknown after failed output), validation issues and revision status.
No prompts or private source text are added to performance records.

Mocked tests cover evidence gaps, comparability restrictions, mechanical corrections, source/number validation,
review rejection and illustrative Fidelity-like/Vanguard-like evidence. These establish delivery and safeguards,
not actual live-model judgement quality. Zero routine tool calls removes tool round trips by construction, but
no live latency, token or API-cost improvement is measured. All available evidence still consumes context tokens;
provider usage is required to quantify the trade-off. Financial formulas, thresholds and model settings are unchanged.
