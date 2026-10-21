from pathlib import Path
import asyncio
import tempfile
from agents import Runner, trace, gen_trace_id
from file_parser import parse_files
from analysis import FundAnalysis
from report_builder import build_html, build_markdown
from pdf_builder import build_pdf
from planner_agent import planner_agent, WebSearchItem, WebSearchPlan, HOW_MANY_SEARCHES
from search_agent import search_agent
from writer_agent import writer_agent, FundReport
from notify_agent import notify_agent, NotifyContext


class AgentManager:

    async def run(self, query: str, files: list[str] | None):
        """ Run the fund report workflow, yielding (report, summary, pdf, charts) updates """
        status: list[str] = []

        def update(message: str):
            status.append(message)
            return "\n".join(f"- {s}" for s in status), "", None, []

        trace_id = gen_trace_id()
        with trace("Fund report trace", trace_id=trace_id):
            yield update(f"Starting. [View trace](https://platform.openai.com/traces/trace?trace_id={trace_id})")
            out_dir = Path(tempfile.mkdtemp(prefix="fund_report_"))

            analysis = FundAnalysis.build(parse_files(files), out_dir)
            for note in analysis.parsed.notes:
                yield update(note)
            yield update("Calculations done, planning searches...")

            plan = await self.plan_searches(query, analysis)
            yield update(f"Running {len(plan.searches)} searches...")
            search_results = await self.perform_searches(plan)
            yield update(f"{len(search_results)} of {len(plan.searches)} searches succeeded, writing report...")

            report = await self.write_report(query, analysis, search_results)
            searches = [s.query for s in plan.searches]
            report_md = build_markdown(report, analysis, searches)
            pdf_path = build_pdf(build_html(report, analysis, searches), str(out_dir / self.pdf_name(report)))
            yield update("PDF created, sending email and push notification...")

            notify_result = await self.notify(report, report_md, pdf_path)
            yield update(notify_result)
            yield report_md, f"**{report.title}**\n\n{report.short_summary}", pdf_path, list(analysis.charts.values())

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

    async def write_report(self, query: str, analysis: FundAnalysis, search_results: list[str]) -> FundReport:
        input_message = (
            f"Request: {query}\n\n"
            f"Calculated figures:\n{analysis.facts_markdown()}\n\n"
            f"Uploaded documents:\n{analysis.documents_text()}\n\n"
            f"Web search summaries:\n{search_results}"
        )
        result = await Runner.run(writer_agent, input_message)
        return result.final_output

    @staticmethod
    def pdf_name(report: FundReport) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in report.fund_name).strip("_") or "fund"
        return f"{slug}_performance_review.pdf"

    async def notify(self, report: FundReport, report_md: str, pdf_path: str) -> str:
        input_message = f"Short summary:\n{report.short_summary}\n\nFull report:\n{report_md}"
        result = await Runner.run(notify_agent, input_message, context=NotifyContext(pdf_path=pdf_path))
        return result.final_output
