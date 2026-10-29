""" Planner and Search agents (spec Sections 8 and 8.2): up to 5 web searches about the fund, its manager and
what drove its market in the review period, run in parallel, one search each, no retries.

Only public facts reach these agents: the Planner sees the fund's name, ISIN, share class, benchmark,
objective type, review period and ratings, and never figures, uploaded documents or client data; each Search
agent sees only its query and the reason for it. Data sharing is on for the API key: public data only.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from agents import WebSearchTool
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.models import DataFlag, FundProfile
from fund_performance.scorecard import Scorecard

Topic = Literal["fund_news", "manager_changes", "market_drivers"]
MAX_QUERY_CHARS = 200
MAX_SUMMARY_CHARS = 1200

PLANNER_INSTRUCTIONS = """
You plan web searches for an investment oversight review of one fund. Return up to {max_searches} search
queries, each with a topic and a one-line reason.

Topics:
- fund_news: news about this fund or share class (e.g. changes to the fund, its fees or its index).
- manager_changes: changes at the fund manager or the team that runs the fund.
- market_drivers: what drove the fund's market in the review period.

Rules:
- Every query must be about the fund, its manager, or its market in the review period.
- Name the fund, the manager or the market in each query, and the period where it matters.
- Use only the fund details given. Never include personal or client information.
- Do not repeat a query.
"""

SEARCH_INSTRUCTIONS = """
You run one web search for an investment oversight review and summarise what you find.

- Search the web once for the query you are given.
- Summary: 2 to 4 short sentences in plain English on what the sources say that matters for the reason
  given. Only report what the sources say. No opinions, no investment advice.
- url: the web address of the main source you used.
- date: the source's publication date as YYYY-MM-DD if it is shown, otherwise null.
"""


class PlannedSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Topic
    query: str
    reason: str


class SearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    searches: list[PlannedSearch]


class SearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    summary: str
    url: str
    date: str | None


@dataclass
class Research:
    plan: list[PlannedSearch] = field(default_factory=list)
    summaries: list[dict] = field(default_factory=list)       # {query, summary, url, date}, for the Analyst
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def planner_agent(max_searches: int):
    return build_agent("Planner Agent", PLANNER_INSTRUCTIONS.format(max_searches=max_searches), SearchPlan, "planner")


def search_agent():
    return build_agent("Search Agent", SEARCH_INSTRUCTIONS, SearchSummary, "search",
                       tools=[WebSearchTool(search_context_size="low")], tool_choice="required")


def planner_input(profile: FundProfile, card: Scorecard) -> str:
    """ Public fund details and the ratings only: no figures, documents or client data """
    as_of = profile.as_of_date
    start_12m = date(as_of.year - 1, as_of.month, as_of.day) if not (as_of.month == 2 and as_of.day == 29) \
        else date(as_of.year - 1, 2, 28)
    ratings = "; ".join(f"{p.name}: {p.rating}" for p in card.pillars.values())
    return (f"Fund: {profile.fund_name}\nISIN: {profile.isin}\nShare class: {profile.share_class}\n"
            f"Benchmark: {profile.benchmark_name}\nObjective type: {profile.objective_type}\n"
            f"Review period: {start_12m:%d %b %Y} to {as_of:%d %b %Y} (main test period: "
            f"{profile.time_horizon_years} years to {as_of:%d %b %Y})\n"
            f"Ratings: {ratings}\nDraft verdict: {card.verdict}")


def tidy_plan(plan: SearchPlan, max_searches: int) -> tuple[list[PlannedSearch], list[str]]:
    """ Code keeps the limits: at most max_searches, no empty, overlong or repeated queries """
    kept, seen, log = [], set(), []
    for item in plan.searches:
        query = " ".join(item.query.split())
        if not query or len(query) > MAX_QUERY_CHARS or query.lower() in seen:
            log.append(f"Planned query left out (empty, too long or repeated): {item.query[:80]!r}")
            continue
        seen.add(query.lower())
        kept.append(item.model_copy(update={"query": query}))
    if len(kept) > max_searches:
        log.append(f"Planner asked for {len(kept)} searches; only the first {max_searches} are run")
    return kept[:max_searches], log


def _check_summary(planned: PlannedSearch):
    def check(out: SearchSummary) -> dict:
        if not out.url.startswith(("https://", "http://")):
            raise ValueError("no source URL")
        summary = " ".join(out.summary.split())
        if not summary:
            raise ValueError("empty summary")
        try:
            when = date.fromisoformat(out.date).isoformat() if out.date else None
        except ValueError:
            when = None
        # The planned query is kept, so the report lists exactly what was searched
        return {"query": planned.query, "summary": summary[:MAX_SUMMARY_CHARS], "url": out.url, "date": when}
    return check


async def search_one(planned: PlannedSearch, run: RunFn | None = None) -> tuple[dict | None, str]:
    """ One search, once: no retries (spec 8). Returns the summary, or None and the reason it was left out """
    prompt = f"Search query: {planned.query}\nReason: {planned.reason}"
    result = await run_structured(search_agent(), prompt, SearchSummary, convert=_check_summary(planned), run=run,
                                  attempts=1)
    if result.ok:
        return result.output, f"Searched: {planned.query}"
    return None, f"Search left out ({planned.query}): {'; '.join(result.errors)}"


async def research(profile: FundProfile, card: Scorecard, max_searches: int, run_planner: RunFn | None = None,
                   run_search: RunFn | None = None) -> Research:
    """ Plan, then run the searches in parallel. Research is optional: if it fails, the review goes on
    without market context """
    out = Research()
    planned = await run_structured(planner_agent(max_searches), planner_input(profile, card), SearchPlan, run=run_planner)
    if not planned.ok:
        out.flags.append(DataFlag(check="research", level="warning",
                                  message="No web research: the Planner gave no valid plan, so there is no market context"))
        out.log.append("Planner failed: " + "; ".join(planned.errors))
        return out
    out.plan, notes = tidy_plan(planned.output, max_searches)
    out.log += notes
    results = await asyncio.gather(*(search_one(item, run_search) for item in out.plan))
    for summary, line in results:
        out.log.append(line)
        if summary is not None:
            out.summaries.append(summary)
    failed = len(out.plan) - len(out.summaries)
    if failed:
        out.flags.append(DataFlag(check="research", level="info",
                                  message=f"{failed} of {len(out.plan)} web searches gave no usable result and were left out"))
    return out
