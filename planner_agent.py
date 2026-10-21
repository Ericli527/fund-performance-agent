from pydantic import BaseModel, Field
from agents import Agent
import os

MODEL_NAME = os.getenv("DEFAULT_MODEL_NAME", "gpt-5.4")
HOW_MANY_TASKS = int(os.getenv("HOW_MANY_TASKS", 3))

# TODO: describe how your agent should break down a request
INSTRUCTIONS = f"""
You are a planning assistant. Given a user query, break it into {HOW_MANY_TASKS}
smaller tasks that together answer the query.
"""


class Task(BaseModel):
    reason: str = Field(description="Why this task matters for the query.")
    description: str = Field(description="What the worker should do.")


class TaskPlan(BaseModel):
    tasks: list[Task] = Field(description="The tasks to run to answer the query.")


planner_agent = Agent(name="Planner Agent", instructions=INSTRUCTIONS, model=MODEL_NAME, output_type=TaskPlan)
