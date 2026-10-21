from agents import Runner, trace, gen_trace_id
from planner_agent import planner_agent, Task, TaskPlan
from worker_agent import worker_agent
from writer_agent import writer_agent, FinalOutput
from notify_agent import notify_agent
import asyncio
import os

USE_NOTIFY = os.getenv("USE_NOTIFY", "false").lower() == "true"


class AgentManager:

    async def run(self, query: str):
        """ Run the workflow, yielding status updates and the final output """
        trace_id = gen_trace_id()
        with trace("Agent trace", trace_id=trace_id):
            yield f"Starting. Trace: https://platform.openai.com/traces/trace?trace_id={trace_id}"
            plan = await self.plan(query)
            yield f"Plan ready, running {len(plan.tasks)} tasks..."
            results = await self.run_tasks(plan)
            yield f"{len(results)} of {len(plan.tasks)} tasks succeeded, writing output..."
            output = await self.write(query, results)
            if USE_NOTIFY:
                yield "Output written, sending notification..."
                await self.notify(output)
            yield output.markdown

    async def plan(self, query: str) -> TaskPlan:
        """ Break the query into smaller tasks """
        result = await Runner.run(planner_agent, f"Query: {query}")
        return result.final_output

    async def run_tasks(self, plan: TaskPlan) -> list[str]:
        """ Run all tasks in parallel, skipping any that fail """
        results = await asyncio.gather(*(self.run_task(t) for t in plan.tasks), return_exceptions=True)
        return [r for r in results if isinstance(r, str)]

    async def run_task(self, task: Task) -> str:
        """ Run a single task with the worker agent """
        input_message = f"Task: {task.description}\nReason: {task.reason}"
        result = await Runner.run(worker_agent, input_message)
        return result.final_output

    async def write(self, query: str, results: list[str]) -> FinalOutput:
        """ Combine the task results into the final output """
        input_message = f"Original query: {query}\nTask results: {results}"
        result = await Runner.run(writer_agent, input_message)
        return result.final_output

    async def notify(self, output: FinalOutput) -> None:
        await Runner.run(notify_agent, output.markdown)
