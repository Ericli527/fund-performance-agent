from typing import Literal
from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("NOTIFY_MODEL_NAME", "gpt-5.4-mini")

INSTRUCTIONS = """
You read a fund's documents and fund facts and set out its mandate: what it promises investors.
Use only what the documents say. Do not add promises they do not make.
- fund_type is "passive" if the fund aims to track an index, otherwise "active".
- objective: the fund's objective in one or two plain sentences.
- commitments: up to 5 specific promises or limits (e.g. target risk rating, minimum holding period,
  investment limits, the benchmark it is measured against).
"""


class Mandate(BaseModel):
    fund_type: Literal["passive", "active"] = Field(description="passive if it tracks an index, otherwise active.")
    objective: str = Field(description="The fund's objective in one or two plain sentences.")
    commitments: list[str] = Field(description="Up to 5 specific promises or limits from the documents.")


mandate_agent = Agent(name="Mandate Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=Mandate)
