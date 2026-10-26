from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

INSTRUCTIONS = """
You are an investment oversight analyst preparing a short report for an oversight director who decides
whether to retain, monitor or review a fund partner. You are given the fund's mandate, calculated
performance figures, a rule-based scorecard (four ratings and a verdict), a comparison with one peer,
uploaded documents and web research.

Rules:
- The ratings and verdict are final. Explain them; never change or contradict them.
- Use only the figures given to you. Quote them exactly and name their period. Never invent numbers.
- Plain, neutral British English for a non-technical reader. No hype. Keep to the word limits.
- Only describe the fund's own positioning if the documents say it; market commentary is market context.
- If something could not be assessed, say what data would be needed.
"""


class OversightReport(BaseModel):
    title: str = Field(description="e.g. '<Fund name>: Investment Oversight Report'.")
    short_summary: str = Field(description="2-3 sentences with the verdict, for a push notification, under 600 characters.")
    verdict_reason: str = Field(description="One sentence explaining the verdict.")
    pillar_comments: list[str] = Field(description="Exactly 4 comments, in order: Mandate, Performance, Value for investors, Fees. Each under 45 words.")
    key_findings: list[str] = Field(description="3-4 key findings, each under 30 words.")
    actions: list[str] = Field(description="2-3 recommended actions for the oversight team, each under 25 words.")
    market_context: str = Field(description="What drove the fund's market over the last 12 months, under 110 words.")
    triggers: list[str] = Field(description="3 events that would change the verdict, each under 25 words.")


oversight_agent = Agent(name="Oversight Analyst", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=OversightReport)
