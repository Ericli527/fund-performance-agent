from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

# TODO: describe the final output you want
INSTRUCTIONS = """
You combine the results of several tasks into one clear answer to the
original query. Write the output in markdown.
"""


class FinalOutput(BaseModel):
    short_summary: str = Field(description="A 2-3 sentence summary.")
    markdown: str = Field(description="The final output in markdown.")


writer_agent = Agent(name="Writer Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=FinalOutput)
