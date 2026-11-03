# Review performance baseline and plan

No local completed review log contained recorded AI calls, and no paid live calls were made. Consequently there is
no measured token, latency or cost baseline, and no measured improvement is claimed. Comparable before/after runs
need identical inputs, model settings, source availability and cache conditions, with human review of investment
quality and material-error detection. Do not include private prompts or documents in benchmark records.

The current flow sends the full facts, fund context, research and assessment to the Investment Quality Reviewer.
The Reporting Agent and Reporting Judge also receive overlapping context. The optional Assurance Judge receives
bounded extracted text from all available PDFs. These are likely input-token bottlenecks, not measured findings.
The existing single Analyst response covers four ratings, quality review can request one revision, research and
calculation already overlap, and the optional Assurance Judge runs only on request. The configured Reporter uses
one draft; raising concurrency or removing reviewers would not be justified by the present evidence.

Priority: (1) collect actual SDK request, token, cache, tool and timing data; (2) benchmark carefully scoped evidence
packets while retaining sources, qualifications and access to details; (3) change sequencing or model settings only
where comparable measurements and independent quality checks show no material regression. A preliminary target is
20% fewer input tokens and 10% lower median elapsed time, with no loss of material-error detection or source
attribution; these are targets, not results. Reasoning tokens are a subset of output tokens and cached tokens a
subset of input tokens, so they must not be billed twice.

Uploaded or selected peer documents are independent after selection, so up to three can be extracted concurrently.
Their outputs are assembled in input order and sibling tasks are cancelled on failure. This changes scheduling,
not the extraction schema, validation or number of calls. Single-peer and no-peer paths stay sequential. The
latency benefit and provider rate-limit behaviour remain unmeasured with real API calls.

`run.performance` in `log.json` aggregates SDK-reported counts, per-agent elapsed time, retries and optional
costs. An optional `config/model_pricing.yaml` may contain `models: {MODEL: {input: RATE, cached_input: RATE,
output: RATE, source: URL, as_of: DATE}}` with rates in USD per million tokens. Without complete, sourced pricing
and SDK usage, cost is unknown, not zero. Elapsed review time includes document intake when the web documents
route provides it; for other callers it starts at the controller. Optional assurance performance is recorded
separately in its result and server log. SDK-normalised usage is a diagnostic, not an invoice; check actual billing.
