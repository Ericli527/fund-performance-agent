from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")
MAX_SEARCHES = 5
HOW_MANY_SEARCHES = min(int(os.getenv("HOW_MANY_SEARCHES", MAX_SEARCHES)), MAX_SEARCHES)

INSTRUCTIONS = f"""
You are a fund research assistant. You are given a request to analyse a fund, plus a
summary of its calculated performance and attribution. Plan up to {HOW_MANY_SEARCHES} web
searches that explain the results: for example the fund's strategy and recent news, the
benchmark, and market or sector moves over the period that drove the biggest effects.
Do not search for numbers that are already provided.
"""


class WebSearchItem(BaseModel):
    reason: str = Field(description="Why this search helps explain the fund's results.")
    query: str = Field(description="The search term to use for the web search.")


class WebSearchPlan(BaseModel):
    searches: list[WebSearchItem] = Field(description=f"Up to {HOW_MANY_SEARCHES} web searches to perform.")


planner_agent = Agent(name="Planner Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=WebSearchPlan)
