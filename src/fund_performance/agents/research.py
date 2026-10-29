""" Planner and Search agents (spec Sections 8 and 8.2): up to 5 web searches about the fund, its manager and
what drove its market in the review period, run in parallel, one search each, no retries.

Only public facts reach these agents: the Planner sees the fund's name, ISIN, share class, benchmark,
objective type, review period and ratings, and never figures, uploaded documents or client data; each Search
agent sees only its query and the reason for it. Data sharing is on for the API key: public data only.
"""
import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
import re
from typing import Literal
from agents import WebSearchTool
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.models import DataFlag, FundProfile
from fund_performance.scorecard import Scorecard

Topic = Literal["fund_news", "manager_changes", "market_drivers"]
MAX_QUERY_CHARS = 200
MAX_SUMMARY_CHARS = 1200
MARKET_NOISE = {"index", "nuk", "net", "tr", "total", "return", "gross", "price", "hedged", "gbp", "usd", "eur"}
FIGURES_DIFFER = "web source figures differ from factsheet, likely different currency or date: excluded"

PLANNER_INSTRUCTIONS = """
You plan web searches for an investment oversight review of one fund. Return up to {max_searches} search
queries, each with a topic and a one-line reason.

Topics:
- fund_news: news about this fund or share class (e.g. changes to the fund, its fees or its index).
- manager_changes: changes at the fund manager or the team that runs the fund.
- market_drivers: what drove the fund's market in the review period.

Rules:
- Every query must be about the fund, its manager, or its market in the review period.
- market_drivers queries are about the market, not the fund. Name the market and the review period, and
  never the fund, e.g. "S&P 500 performance drivers Oct 2025 to Sep 2026".
- Only fund-specific searches (fund_news, manager_changes: changes, manager, fees) use the fund's name.
- Write queries that find news and index-provider sources rather than fund data pages.
- Use only the fund details given. Never include personal or client information.
- Do not repeat a query.
"""

SEARCH_INSTRUCTIONS = """
You run one web search for an investment oversight review and summarise what you find.

- Search the web once for the query you are given.
- Prefer news articles and index-provider sources (e.g. S&P Dow Jones Indices, FTSE Russell, MSCI) over
  fund data pages (fund platforms, factsheet sites), whose figures may be in another currency or at
  another date.
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


def review_period(profile: FundProfile) -> tuple[date, date]:
    """ The 12 months to the as-of date: the period the searches cover """
    as_of = profile.as_of_date
    day = 28 if (as_of.month == 2 and as_of.day == 29) else as_of.day
    return date(as_of.year - 1, as_of.month, day), as_of


def market_name(profile: FundProfile) -> str:
    """ The benchmark without index-variant words, e.g. 'S&P 500 Index NUK' -> 'S&P 500' """
    words = [w for w in profile.benchmark_name.split() if w.lower().strip("()") not in MARKET_NOISE]
    return " ".join(words) or profile.benchmark_name


def fund_stem(profile: FundProfile) -> str:
    """ The fund's name without share-class words, e.g. 'Fidelity Index US Fund P Accumulation' -> 'Fidelity Index US' """
    words = profile.fund_name.split()
    cut = next((i for i, w in enumerate(words) if w.lower() in ("fund", "trust", "portfolio", "etf")), len(words))
    return " ".join(words[:cut]) or profile.fund_name


def names_the_fund(text: str, profile: FundProfile) -> bool:
    lower = text.lower()
    return fund_stem(profile).lower() in lower or profile.isin.lower() in lower


def planner_input(profile: FundProfile, card: Scorecard) -> str:
    """ Public fund details and the ratings only: no figures, documents or client data """
    start, end = review_period(profile)
    ratings = "; ".join(f"{p.name}: {p.rating}" for p in card.pillars.values())
    return (f"Fund: {profile.fund_name}\nISIN: {profile.isin}\nShare class: {profile.share_class}\n"
            f"Benchmark: {profile.benchmark_name}\nMarket (for market_drivers queries): {market_name(profile)}\n"
            f"Objective type: {profile.objective_type}\n"
            f"Review period: {start + timedelta(days=1):%b %Y} to {end:%b %Y} ({start:%d %b %Y} to {end:%d %b %Y}; "
            f"main test period: {profile.time_horizon_years} years to {end:%d %b %Y})\n"
            f"Ratings: {ratings}\nDraft verdict: {card.verdict}")


def tidy_plan(plan: SearchPlan, max_searches: int, profile: FundProfile | None = None) -> tuple[list[PlannedSearch], list[str]]:
    """ Code keeps the limits: at most max_searches, no empty, overlong or repeated queries, and no
    market-driver query that names the fund """
    kept, seen, log = [], set(), []
    for item in plan.searches:
        query = " ".join(item.query.split())
        if not query or len(query) > MAX_QUERY_CHARS or query.lower() in seen:
            log.append(f"Planned query left out (empty, too long or repeated): {item.query[:80]!r}")
            continue
        if profile is not None and item.topic == "market_drivers" and names_the_fund(query, profile):
            log.append(f"Market-driver query left out because it names the fund: {query!r}")
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
    out.plan, notes = tidy_plan(planned.output, max_searches, profile)
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


# --- Vetting the summaries before the Analyst sees them --------------------------------------------------------

_RETURN_WORDS = re.compile(r"\b(return|returns|returned|gain|gained|gains|rose|rise|fell|fall|lost|up|down|"
                           r"performance|performed|delivered)\b", re.IGNORECASE)
_PERIODS = [(re.compile(r"\b(1|one)[- ]year\b|\b12[- ]months?\b|\bpast year\b|\b1y\b", re.I), "1y"),
            (re.compile(r"\b(3|three)[- ]years?\b|\b3y\b", re.I), "3y"),
            (re.compile(r"\b(5|five)[- ]years?\b|\b5y\b", re.I), "5y"),
            (re.compile(r"\byear[- ]to[- ]date\b|\bYTD\b", re.I), "ytd")]


def _official_returns(facts: dict) -> dict[str, list[tuple[str, float]]]:
    """ The fund's and the index's % returns in the facts, with their period ('1y', '3y', '5y', 'ytd', a year) """
    out: dict[str, list[tuple[str, float]]] = {"fund": [], "index": []}
    for f in facts.get("figures", []):
        if f.get("unit") != "%":
            continue
        parts = f["name"].split(".")
        who = "fund" if parts[0] in ("fund_nav", "fund_pnav") else "index" if parts[0] == "index" else None
        if who is None or len(parts) < 3:
            continue
        kind, key = parts[1], parts[2]
        if kind in ("cum", "ann"):
            out[who].append((key, f["value"]))
        elif kind == "calendar":
            out[who].append(("ytd" if key == "YTD" else key, f["value"]))
        elif kind == "discrete_12m" and key == facts.get("fund", {}).get("as_of_date"):
            out[who].append(("1y", f["value"]))
    return out


def _sentence_period(sentence: str) -> str | None:
    for pattern, period in _PERIODS:
        if pattern.search(sentence):
            return period
    year = re.search(r"\b(?:in|during|for)\s+(20\d\d)\b", sentence)
    return year.group(1) if year else None


def conflicting_figures(summary: str, profile: FundProfile, facts: dict, tolerance_pp: float) -> list[str]:
    """ Returns stated for the fund or its index that are more than tolerance_pp from every factsheet figure
    for the same series (and the same period, when the sentence names one) """
    from fund_performance.number_guard import numbers_in
    official = _official_returns(facts)
    market = market_name(profile).lower()
    bad = []
    for sentence in re.split(r"(?<=[.!?])\s+", summary):
        who = "fund" if names_the_fund(sentence, profile) else "index" if market in sentence.lower() else None
        if who is None or not _RETURN_WORDS.search(sentence):
            continue
        period = _sentence_period(sentence)
        candidates = [v for p, v in official[who] if period is None or p == period]
        for n in numbers_in(sentence):
            if n.unit == "%" and candidates and not any(abs(abs(n.value) - abs(v)) <= tolerance_pp for v in candidates):
                bad.append(f"{n.text.strip()} ({who}{', ' + period if period else ''})")
    return bad


def vet_summaries(summaries: list[dict], profile: FundProfile, facts: dict,
                  tolerance_pp: float = 0.5) -> tuple[list[dict], list[DataFlag], list[str]]:
    """ Leave out summaries with no date, dated outside the review period, or with fund or index returns that
    differ from the factsheet by more than tolerance_pp (owner decisions). Each exclusion gets an info flag """
    start, end = review_period(profile)
    kept, flags, log = [], [], []

    def exclude(s: dict, why: str):
        flags.append(DataFlag(check="research", level="info", message=f"{why} ({s['url']})"))
        log.append(f"Summary excluded, {why}: {s['query']}")

    for s in summaries:
        if not s.get("date"):
            exclude(s, "web source has no date: excluded")
            continue
        when = date.fromisoformat(s["date"])
        if not start <= when <= end:
            exclude(s, f"web source dated {when.isoformat()}, outside the review period "
                       f"{start.isoformat()} to {end.isoformat()}: excluded")
            continue
        bad = conflicting_figures(s["summary"], profile, facts, tolerance_pp)
        if bad:
            exclude(s, f"{FIGURES_DIFFER}: {', '.join(bad)}")
            continue
        kept.append(s)
    return kept, flags, log
