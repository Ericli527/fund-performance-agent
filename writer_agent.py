from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

INSTRUCTIONS = """
You are a fund performance analyst writing a brief report for an investment committee.
You are given the request, calculated performance and attribution tables, extracts from
documents the user uploaded, and web search summaries.

Rules:
- Use only the numbers given to you. Never calculate or invent new figures.
- The tables are already included in the report, so explain them rather than repeat them.
- Keep the commentary brief: about 300-500 words in markdown, using ## headings for
  "Performance", "Attribution" (if attribution data is given), "Market context" and "Outlook and risks".
- Say plainly when data is missing.
"""


class FundReport(BaseModel):
    title: str = Field(description="A short report title, including the fund name if known.")
    short_summary: str = Field(description="A 2-3 sentence summary of the key findings, under 600 characters.")
    commentary: str = Field(description="The report commentary in markdown.")


writer_agent = Agent(name="Writer Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=FundReport)
