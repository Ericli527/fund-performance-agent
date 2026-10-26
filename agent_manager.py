from datetime import date
from pathlib import Path
import asyncio
import pandas as pd
import tempfile
from agents import Runner, trace, gen_trace_id
from file_parser import parse_files
from market_data import fetch_nav, MarketDataError, api_key, resolve, monthly_prices
from analysis import FundAnalysis, merge_extract
from extractor_agent import extractor_agent, FactsheetExtract
from pdf_builder import build_pdf
from planner_agent import planner_agent, WebSearchItem, WebSearchPlan, HOW_MANY_SEARCHES
from search_agent import search_agent
from notify_agent import notify_agent, NotifyContext
from mandate_agent import mandate_agent, Mandate
from oversight import assess, parse_percent
from oversight_agent import oversight_agent, OversightReport
from oversight_builder import build_oversight_html, build_oversight_markdown


class AgentManager:

    async def run(self, query: str, files: list[str] | None, fund_id: str = "", benchmark_id: str = ""):
        """ Run the oversight review, yielding (report, summary, pdf, charts) updates """
        status: list[str] = []

        def update(message: str):
            status.append(message)
            return "\n".join(f"- {s}" for s in status), "", None, []

        trace_id = gen_trace_id()
        with trace("Fund oversight trace", trace_id=trace_id):
            yield update(f"Starting. [View trace](https://platform.openai.com/traces/trace?trace_id={trace_id})")
            out_dir = Path(tempfile.mkdtemp(prefix="fund_oversight_"))

            # 1. Data: uploaded files, then prices from EODHD if a fund was named
            parsed = parse_files(files)
            for note in parsed.notes:
                yield update(note)
            if fund_id.strip():
                # Network calls run in a thread so the app stays responsive for other users
                yield update(await asyncio.to_thread(self.add_prices, parsed, fund_id, benchmark_id))
            if parsed.documents and (not parsed.fund_facts or (parsed.performance is None and parsed.nav is None)):
                yield update("Extractor Agent is reading fund facts and reported performance from the documents...")
                notes_before = len(parsed.notes)
                merge_extract(parsed, await self.extract(parsed.documents), [n for n, _ in parsed.documents])
                for note in parsed.notes[notes_before:]:
                    yield update(note)
            analysis = FundAnalysis.build(parsed, out_dir)
            if analysis.official:
                yield update(f"Using the fund manager's official performance figures ({analysis.data_label}).")

            # 2. What the fund promised
            yield update("Mandate Agent is reading what the fund promises...")
            mandate = await self.read_mandate(analysis)
            yield update(f"Mandate: {'index (passive)' if mandate.fund_type == 'passive' else 'actively managed'} fund, "
                         f"{len(mandate.commitments)} commitment(s) found.")

            # 3. Peer and scorecard, decided by fixed rules in code
            peer, peer_levels, note = await asyncio.to_thread(self.peer_prices, analysis)
            yield update(note)
            fund_name = analysis.fact("fund name") or "The Fund"
            benchmark = analysis.fact("benchmark") or benchmark_id or "Benchmark"
            if "nav" in parsed.sources and benchmark_id.strip() and not analysis.official:
                benchmark += f" (prices: stand-in {benchmark_id.strip()})"
            result = assess(analysis, mandate.fund_type, fund_name, peer, peer_levels)
            yield update("Scorecard (rules in code): " + ", ".join(f"{p.name} {p.rating}" for p in result.pillars)
                         + f". Draft verdict: {result.verdict}.")

            # 4. Research
            plan = await self.plan_searches(f"{query}\nThis is an investment oversight review of {fund_name}: research "
                                            "news about the fund and its manager, and what drove its market in the last "
                                            "12 months.", analysis)
            yield update(f"Running {len(plan.searches)} searches...")
            search_results = await self.perform_searches(plan)
            yield update(f"{len(search_results)} of {len(plan.searches)} searches succeeded; Oversight Analyst is writing...")

            # 5. Explain, build the PDF and send
            report = await self.write_report(query, analysis, mandate, result, search_results)
            searches = [s.query for s in plan.searches]
            report_md = build_oversight_markdown(report, analysis, mandate, result, fund_name)
            pdf_path = build_pdf(build_oversight_html(report, analysis, mandate, result, fund_name, benchmark, searches),
                                 str(out_dir / self.pdf_name(fund_name, analysis)))
            yield update("PDF created, sending email and push notification...")
            yield update(await self.notify(report.short_summary, report_md, pdf_path))
            charts = [analysis.charts[k] for k in ("growth", "calendar", "attribution") if k in analysis.charts]
            yield report_md, f"**{report.title}**\n\n{report.short_summary}", pdf_path, charts

    @staticmethod
    def add_prices(parsed, fund_id: str, benchmark_id: str) -> str:
        """ Download NAV history unless the user uploaded their own; problems become status notes """
        if parsed.nav is not None:
            return "NAV file uploaded, so prices were not downloaded."
        if not benchmark_id.strip():
            return "Price download skipped: add a benchmark ticker as well as the fund."
        try:
            nav, note = fetch_nav(fund_id, benchmark_id)
        except MarketDataError as e:
            return f"Price download failed: {e}"
        nav["date"] = pd.to_datetime(nav["date"])
        parsed.nav = nav
        parsed.sources["nav"] = note
        parsed.notes.append(note)
        return note

    async def extract(self, documents: list[tuple[str, str]]) -> FactsheetExtract:
        """ Read fund facts, holdings and exposures from documents when no fund facts file was given """
        text = "\n\n".join(f"--- {name} ---\n{content}" for name, content in documents)
        result = await Runner.run(extractor_agent, text)
        return result.final_output

    async def read_mandate(self, analysis: FundAnalysis) -> Mandate:
        facts = "\n".join(f"- {f}: {v}" for f, v in analysis.parsed.fund_facts) or "None"
        result = await Runner.run(mandate_agent, f"Fund facts:\n{facts}\n\nDocuments:\n{analysis.documents_text()}")
        return result.final_output

    @staticmethod
    def peer_prices(analysis: FundAnalysis):
        """ The first peer in the peer file and its month-end prices; problems become a status note """
        peers = analysis.parsed.peers
        if peers is None or peers.empty:
            return None, None, "No peer file uploaded, so value and fees cannot be compared."
        row = peers.iloc[0]
        peer = {"name": str(row["name"]), "ocf": None if pd.isna(row["ocf"]) else parse_percent(row["ocf"])}
        perf = analysis.parsed.performance
        if perf is not None and "peer" in perf.columns and perf["peer"].notna().any():
            return peer, None, f"Peer {peer['name']}: reported returns taken from the performance file."
        if analysis.nav is None:
            return peer, None, f"Peer {peer['name']}: no fund prices or reported peer returns to compare with."
        if "peer" in analysis.nav.columns:
            # Peer prices supplied in the NAV file, so no download is needed
            levels = analysis.nav.set_index("date")["peer"].dropna()
            return peer, levels, f"Peer prices for {peer['name']} taken from the NAV file ({len(levels)} months)."
        if not api_key():
            return peer, None, f"Peer {peer['name']}: prices skipped because EODHD_API_KEY is not set."
        try:
            symbol, _, _ = resolve(str(row["ticker"]))
            levels = monthly_prices(symbol, analysis.nav["date"].iloc[0] - pd.DateOffset(months=1))
        except MarketDataError as e:
            return peer, None, f"Peer {peer['name']}: price download failed ({e})"
        return peer, levels, f"Peer prices from EODHD: {peer['name']} ({symbol}), {len(levels)} months."

    async def plan_searches(self, query: str, analysis: FundAnalysis) -> WebSearchPlan:
        """ Plan the searches, with a hard limit in code as well as in the prompt """
        input_message = f"Request: {query}\n\nCalculated results:\n{analysis.facts_markdown()}"
        result = await Runner.run(planner_agent, input_message)
        plan = result.final_output
        plan.searches = plan.searches[:HOW_MANY_SEARCHES]
        return plan

    async def perform_searches(self, plan: WebSearchPlan) -> list[str]:
        """ Run the searches in parallel, skipping any that fail """
        results = await asyncio.gather(*(self.search(item) for item in plan.searches), return_exceptions=True)
        return [r for r in results if isinstance(r, str)]

    async def search(self, item: WebSearchItem) -> str:
        input_message = f"Search term: {item.query}\nReason for searching: {item.reason}"
        result = await Runner.run(search_agent, input_message)
        return result.final_output

    async def write_report(self, query: str, analysis: FundAnalysis, mandate: Mandate, result,
                           search_results: list[str]) -> OversightReport:
        input_message = (f"Request: {query}\n\n### Mandate\nType: {mandate.fund_type}\nObjective: {mandate.objective}\n"
                         + "\n".join(f"- {c}" for c in mandate.commitments)
                         + f"\n\n{result.facts_markdown()}\n\nCalculated figures:\n{analysis.facts_markdown()}\n\n"
                         f"Uploaded documents:\n{analysis.documents_text()}\n\nWeb search summaries:\n{search_results}")
        return (await Runner.run(oversight_agent, input_message)).final_output

    @staticmethod
    def pdf_name(fund_name: str, analysis: FundAnalysis) -> str:
        """ Fund name plus the data date, so monthly reports for the same fund don't overwrite each other """
        slug = "".join(c if c.isalnum() else "_" for c in fund_name).strip("_") or "fund"
        as_of = pd.to_datetime(analysis.as_of, errors="coerce", dayfirst=True) if analysis.as_of else pd.NaT
        as_of = f"{as_of:%Y-%m-%d}" if pd.notna(as_of) else f"{date.today():%Y-%m-%d}"
        return f"{slug}_oversight_report_{as_of}.pdf"

    async def notify(self, short_summary: str, report_md: str, pdf_path: str) -> str:
        input_message = f"Short summary:\n{short_summary}\n\nFull report:\n{report_md}"
        result = await Runner.run(notify_agent, input_message, context=NotifyContext(pdf_path=pdf_path))
        return result.final_output
