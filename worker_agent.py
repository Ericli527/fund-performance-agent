from agents import Agent, WebSearchTool
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")

# TODO: describe what each worker does with one task
INSTRUCTIONS = """
You are a worker. Complete the task you are given and reply with a concise
result of under 300 words. Reply only with the result.
"""

# TODO: swap in the tools your agent needs (function_tool, MCP servers, etc.)
tools = [WebSearchTool()]

worker_agent = Agent(name="Worker Agent", instructions=INSTRUCTIONS, tools=tools, model=MODEL_NAME)
