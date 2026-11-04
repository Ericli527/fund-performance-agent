# Tavily web retrieval

Planned web queries now use Tavily's HTTPS `/search` endpoint with basic depth and at most three results, followed
by the existing Search model's structured summarisation. OpenAI's hosted WebSearchTool is no longer configured.
Approved-source page fetching remains unchanged, as do the research budget and date, relevance, numerical and
citation checks. The summary URL must match a returned result. Excerpts are labelled as incomplete evidence;
missing publication dates are not replaced by search/retrieval dates.

Set `TAVILY_API_KEY` in the Render service environment (already configured by the user) or local ignored `.env`.
Keep `OPENAI_API_KEY` for summarisation and the other agents. The Render blueprint declares both secrets without
values. No provider switch is required. The new code takes effect only after the PR is approved and deployed.
No merge or deployment is performed by this change.

There is no silent OpenAI-search fallback. Missing keys, failed requests, rate limits, malformed responses and
empty results produce research limitations while allowing the fund review to continue. The transport uses a fixed
endpoint, no redirects, bounded timeouts and no automatic retries. Only the public planned query goes to Tavily;
source documents, full review context and credentials are not included in its query payload or logs.

Normal CI mocks the Tavily transport and models. Injected legacy search runners can supply complete offline test
summaries; default production retrieval always uses Tavily. No paid live compatibility call was made.

This removes OpenAI hosted web-search charges and tool round trips. Tavily credits and Search-model summarisation
still incur costs; total savings are unmeasured and depend on plans and usage. Existing API-cost diagnostics cover
LLM tokens, not Tavily credits, so they are not an all-in cost comparison. Search excerpts may omit important source
context; source qualifications and independent review remain necessary.
