from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

INSTRUCTIONS = """
You extract fund data from documents such as factsheets, KIDs and prospectuses.
Copy values exactly as written. Never estimate, calculate or guess. If an item is not in
the documents, leave it out (empty list). Give all weights in percent, as numbers.
"""


class FactItem(BaseModel):
    field: str = Field(description="e.g. 'Fund name', 'ISIN', 'Ongoing charges', 'Fund size', 'Launch date', 'Risk indicator'.")
    value: str = Field(description="The value exactly as written in the document.")


class WeightItem(BaseModel):
    name: str = Field(description="Security, sector or country name.")
    fund_weight: float = Field(description="Fund weight in percent.")
    benchmark_weight: float | None = Field(default=None, description="Benchmark or index weight in percent, if shown.")


class FactsheetExtract(BaseModel):
    fund_facts: list[FactItem] = Field(description="Key facts about the fund and share class.")
    holdings: list[WeightItem] = Field(description="Top holdings, largest first (up to 10).")
    sectors: list[WeightItem] = Field(description="Sector exposure.")
    countries: list[WeightItem] = Field(description="Country or geographic exposure.")


extractor_agent = Agent(name="Extractor Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=FactsheetExtract)
