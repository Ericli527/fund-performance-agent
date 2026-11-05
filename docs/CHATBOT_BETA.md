# Fund chatbot beta

Choose **Fund Review (Reporting)** for the existing independent investment assessment,
reviewers, dashboard and PDFs. Choose **AI Chatbot (Beta)** to prepare a fund evidence
summary once and ask follow-up questions. Switching modes starts no model calls.

## Preparing evidence

Use the same attachments and editable document types as Reporting. A main factsheet
is required, or validated demo JSON inputs. Price history, KID and peer documents are
optional for chat. Reporting still requires its existing inputs.

Document preparation reuses the existing Extractor, Mandate Agent, peer extraction
and self-check. With prices, the existing Python controller prepares calculations
and its quantitative scorecard, stopping before reporting research, investment judgement,
independent review and PDF generation. Without prices, published figures and document
context still support the basic cash illustrations below; no price history,
compatible observation series or scorecard is invented. Confirmed benchmark series retain the existing identity and
date-alignment checks. Benchmark documents are reserved for Reporting and explicitly
excluded from this beta's vetted research evidence.

The summary and full structured evidence remain in session state. Follow-up questions
and **New conversation** reuse them. File, type, selection or benchmark changes
invalidate the context. In-flight responses are revoked when inputs change. Closing
or expiring the session loses chat context; transcripts are not written to disk.
Completed Reporting narratives, research and independent recommendations are not
automatically imported into chat in this first beta; chat preparation is a separate,
explicit action. Existing chat context survives mode switches while inputs are unchanged.

## Current research and composition

**Prepare evidence and recent research** starts five independent Tavily basic searches in parallel,
using the existing Search Agent to summarise retrieved excerpts: market trends, macro policy,
portfolio-relevant news, material index/market changes and regulatory updates. Searches start
once the main fund context exists, overlapping mandate and peer processing where possible.
They cover the preceding 90 days as at the preparation date in London, not the historical
fund review period. Routine fund profiles/factsheets are excluded; Reporting's existing
historical research rules are unchanged.

Each kept source needs a returned URL, a trusted publisher (the relevant regulator for the
regulatory search), a recent source-supported date, substantive current context and summary
figures supported by the retrieved excerpt. Duplicate URLs are removed. Five searches do not
guarantee five usable sources. Missing credentials, timeouts and rejected sources leave the
fund evidence available, with a coverage count and structured exclusion reasons in session
state. Summaries are excerpt-based; Python checks cannot establish semantic correctness or
fund-specific causality. No extra search-planning or rewriting model call is added.

Follow-up questions and **New conversation** reuse research. Explicitly preparing again
refreshes five searches without re-extracting unchanged documents, and clears old conversation
so changed source IDs cannot refer to old articles. Research requires AI access and research
to be enabled. Current news is labelled separately from historical fund evidence; post-review
publications must not be represented as known at the fund review date.

Extraction retains top-stock, industry/sector, geography, market-cap and concentration tables.
Source matching accepts exact single rows when the percentage unit is in the table heading;
ambiguous multi-row quotations remain excluded. Index/benchmark composition is retained
separately from fund exposures, with source, page and provisional classification. No fund
weights are inferred from index membership. Tables absent from the source remain absent.
Scanned/image-only PDFs still depend on the existing document reader; no OCR was added.

The supplied Fidelity photo was visually inspected: its percentage columns are labelled
**Index**, but the explanatory note describes the tables as fund composition. Extraction must
read both together, retain the note as a source-matched scope excerpt, and avoid confidently
reclassifying these tables from one column label. Percentages appear in headings rather than
each row; the earlier inline-percentage check could discard valid rows. The private original PDF and live
extraction trace were not available for reproducing that particular run. Synthetic mocked
fixtures exercise the same layout and extraction-to-chat flow.

## Answer safeguards and cost

### Basic cash calculations

Chat can calculate a hypothetical investment value and gain/loss from stored one-,
three- or five-year fund returns. The model selects a typed calculation request;
Python chooses the exact-period fund return and renders the result, without a second
model call or arbitrary expression evaluation. Derived amounts do not need to be
present in the original source catalogue. Free-form model arithmetic is not published.

Use cumulative returns directly (`principal × (1 + return / 100)`), or compound an
annualised return over its stated period. Prefer dealing NAV for investor cash values;
market-close PNAV requires an explicit request and is labelled as an illustration.
Never substitute an index or different-period return, or invent an exchange rate.
The original structured fund context also supports previously prepared sessions.

NAV returns already reflect fund ongoing charges: OCF is never deducted a second time.
A separately stated annual platform/service fee is illustrated with
`value × (1 − annual_fee / 100)^years`, assuming year-end percentage deductions and
no flows. This is the impact on ending value, not a reconstruction of actual fees
paid. If that separate fee is missing, provide the known fund value and ask for the
additional annual rate. For example, £10,000 with an 88.3% cumulative return becomes
£18,830 before any separate service fee, with the fund's ongoing charge already reflected.
Show the source date and return basis; preserve provisional status internally and the closing AI notice; this is not a live balance
or future forecast. Calculations do not change the scorecard or independent ratings.

Other basic questions use a general arithmetic request rather than a template for
each question: addition, subtraction, multiplication, division, percentages, averages,
ratios and compounding. The model selects a formula and binds named inputs either
to numeric catalogue paths or to explicit user assumptions. Python executes only
bounded numeric `+`, `-`, `*`, `/` and `**` expressions. There is no `eval`, generated
Python execution, file access, function calling or web access. User-specified
hypothetical horizons can differ from the one-/three-/five-year historical cash
examples; they are labelled as assumptions, not fund forecasts. Currency and source
unit checks remain, with the protected NAV cash path retained for fund-fee handling.
Results show the inputs, formula and provenance. The model still owns interpretation
and formula selection; this does not replace independent investment review.

### Grounding and model calls

Each question makes at most one structured, tool-free AI call using the existing
Reporting model settings and environment overrides. No additional model configuration,
rewrite loop or contact/lead-recording tool is introduced for answers. Current research runs only during preparation. Daily AI limits
and concurrency limits apply. Document preparation has its usual extraction calls;
validated JSON preparation makes no extraction calls; enabled research adds up to five Search Agent calls and five Tavily basic searches. SDK usage metadata is retained in session
state without logging prompts or source text. Chat answer tracing is disabled.

The assistant uses only the prepared catalogue and the most recent six turns as
untrusted conversational context. The UI retains up to twenty turns. Unknown citations,
unsupported numerical claims detectable by the existing numerical guard, active HTML
and generated links are withheld. Scope, security and investment-decision flags
produce fixed safe responses. AI extraction remains provisional; text matching is
not independent source verification. Generic AI provenance appears once in a closing notice,
not repeatedly as missing evidence. Specific missing data, contradictory sources, price-basis
limitations and source-specific provisional recovery still need explanation. Numerical/citation
failures show a specific reason, with only reason codes logged (no private answer text). Missing evidence should lead to an actionable
qualification, never an invented comparison or a blanket negative investment rating.

This is evidence Q&A, not an independently reviewed investment recommendation. The
Python checks do not establish semantic truth, correct attribution of every number,
or investment suitability. Prompts and structured flags are additional safeguards,
not proof against every adversarial instruction. New ratings and investment decisions
belong in Reporting with independent review and human sign-off. Only public,
non-confidential documents should be supplied, as in the existing application.

Normal CI uses mocked responses. Live compatibility and answer quality require a
separate, bounded check in an environment with authorised API access.

### Numerical validation and partial overviews

Chat adapts known extracted return/risk and peer-return fields to their schema percentage units
within the cited source only. A number stored as `{"5y": 88.3}` must not be rejected solely
because the answer writes `88.3%`. This changes no financial values or global number guard.
If only numerical validation fails, the whole generated draft is discarded and replaced by
a clearly labelled, source-based partial overview of identity, objective, benchmark, charges
and supplied peer identity/eligibility terms. It does not invent an investment judgement,
claim to answer a more specific question fully, or retain any failed model claim. Source,
security or active-content failures still suppress the response. No retry/model call is added.
