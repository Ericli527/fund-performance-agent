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
and its quantitative scorecard, stopping before research, investment judgement,
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
Show the source date, return basis and provisional status; this is not a live balance
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
web search, rewrite loop or contact/lead-recording tool is introduced. Daily AI limits
and concurrency limits apply. Document preparation has its usual extraction calls;
validated JSON preparation makes none. SDK usage metadata is retained in session
state without logging prompts or source text. Chat answer tracing is disabled.

The assistant uses only the prepared catalogue and the most recent six turns as
untrusted conversational context. The UI retains up to twenty turns. Unknown citations,
unsupported numerical claims detectable by the existing numerical guard, active HTML
and generated links are withheld. Scope, security and investment-decision flags
produce fixed safe responses. AI extraction remains provisional; text matching is
not independent source verification. Missing evidence should lead to an actionable
qualification, never an invented comparison or a blanket negative investment rating.

This is evidence Q&A, not an independently reviewed investment recommendation. The
Python checks do not establish semantic truth, correct attribution of every number,
or investment suitability. Prompts and structured flags are additional safeguards,
not proof against every adversarial instruction. New ratings and investment decisions
belong in Reporting with independent review and human sign-off. Only public,
non-confidential documents should be supplied, as in the existing application.

Normal CI uses mocked responses. Live compatibility and answer quality require a
separate, bounded check in an environment with authorised API access.
