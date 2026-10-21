from agents import Agent, WebSearchTool, ModelSettings
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

INSTRUCTIONS = """
You are a research assistant. Given a search term, search the web and produce a concise
summary of what you find, in under 200 words. Focus on facts that help explain a fund's
performance. Reply only with the summary.
"""

search_agent = Agent(
    name="Search Agent",
    instructions=INSTRUCTIONS,
    tools=[WebSearchTool()],
    model=MODEL_NAME,
    model_settings=ModelSettings(tool_choice="required"),
)
