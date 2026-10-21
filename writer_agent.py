from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

INSTRUCTIONS = """
You are a fund performance analyst writing for an investment oversight committee.
You are given the request, calculated figures, extracts from uploaded documents and
web search summaries. Your text fills a two-page factsheet followed by a committee performance review
(one-page executive summary, then supporting evidence).

Rules:
- Use only the figures given to you. Never calculate, estimate or invent numbers.
- Quote figures exactly as shown, including signs and the period they refer to.
- Write in a clear, neutral, professional tone in British English. No hype.
- Be brief: each commentary field is one or two short paragraphs (60-120 words).
- Explain *why* results happened, linking the figures to the market context.
- If data is missing for a section, say so in one sentence.
- When the short-term and long-term statuses differ, explain the difference in the key
  messages and reflect it in the committee action.
- For the objective and benchmark description, use the uploaded documents where they
  cover it; otherwise describe it in general terms from the fund facts.
"""


class FundReport(BaseModel):
    title: str = Field(description="Report title, e.g. '<Fund name> Performance Review'.")
    fund_name: str = Field(description="The fund name, or 'The Fund' if unknown.")
    benchmark_name: str = Field(description="The benchmark name, or 'Benchmark' if unknown.")
    product_features: list[str] = Field(description="2-3 short factsheet bullets on who the fund is for and what it invests in, each under 15 words.")
    objective_and_policy: str = Field(description="The fund's objective and investment policy, under 80 words.")
    benchmark_description: str = Field(description="What the benchmark measures, under 60 words.")
    short_summary: str = Field(description="2-3 sentences for a push notification, under 600 characters.")
    key_messages: list[str] = Field(description="3-5 key messages for the executive summary, each under 30 words.")
    committee_action: str = Field(description="What the committee is asked to note or do, under 60 words.")
    performance_commentary: str = Field(description="Commentary on returns over each period.")
    risk_commentary: str = Field(description="Commentary on volatility, drawdown, tracking error and beta.")
    attribution_commentary: str = Field(description="Commentary on allocation and selection effects by segment.")
    market_context: str = Field(description="Market and sector background from the web searches.")
    outlook_and_risks: list[str] = Field(description="3-5 short points on the outlook and risks to monitor.")


writer_agent = Agent(name="Writer Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=FundReport)
