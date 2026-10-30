""" Task Planner Agent: turns the request into a plan of tasks (framework point 3)

It reads the question and the fund's public details and chooses, from a fixed menu, what kind of report this is,
which of the four oversight questions to put first, whether market context and questions for the manager are
needed, and which reporting angles to draft. Code checks the plan and runs it. The plan never removes a rating:
all four questions are always measured and rated by code, and the verdict always comes from them.

Offline, or when the agent gives no valid answer, code uses the default plan (everything, in the usual order).
"""
from dataclasses import asdict, dataclass, field
import json
from typing import Literal
from agents import Agent
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, model_kwargs, run_structured
from fund_performance.models import DataFlag, FundProfile

ReportType = Literal["quarterly_review", "fee_question", "performance_question", "mandate_question"]
Question = Literal["Mandate", "Performance", "Value for investors", "Fees"]
Angle = Literal["board", "analyst", "manager_meeting"]
QUESTIONS: tuple[str, ...] = ("Mandate", "Performance", "Value for investors", "Fees")
ANGLES: tuple[str, ...] = ("board", "analyst", "manager_meeting")
ANGLE_WORDS = {"board": "board", "analyst": "oversight analyst", "manager_meeting": "meeting with the manager"}
REPORT_WORDS = {"quarterly_review": "Quarterly oversight review", "fee_question": "Fee question",
                "performance_question": "Performance question", "mandate_question": "Mandate question"}

INSTRUCTIONS = """
You plan an investment oversight review of one fund. You do not calculate anything and you never rate the fund.
From the request and the fund's public details, choose from the menu only:
- report_type: quarterly_review (a full periodic review), fee_question, performance_question or mandate_question.
- focus: the oversight questions the request is most about, most important first, from: Mandate, Performance,
  "Value for investors", Fees. A full review names all four.
- market_context: true if the reader needs what happened in markets (usually true for a full review or a
  performance question; usually false for a fee question).
- manager_questions: true if the reader will need questions to ask the fund manager.
- angles: the readers to draft a summary for, from: board, analyst, manager_meeting. At least one.
- reason: one short sentence on why.
"""


class PlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: ReportType
    focus: list[Question]
    market_context: bool
    manager_questions: bool
    angles: list[Angle]
    reason: str


@dataclass
class TaskPlan:
    report_type: str = "quarterly_review"
    focus: list[str] = field(default_factory=lambda: list(QUESTIONS))     # all four, most important first
    market_context: bool = True
    manager_questions: bool = True
    angles: list[str] = field(default_factory=lambda: list(ANGLES))
    reason: str = "Default plan: a full review"
    source: str = "default"                                              # "planner" or "default"

    @property
    def tasks(self) -> list[str]:
        """ The task list, in the order the controller runs it (written by code from the plan) """
        steps = ["Read and check the documents and prices (Extractor Agent and code)",
                 "Measure and rate all four questions (code); focus: " + ", ".join(self.focus[:2]),
                 "Compare with approved peers (code)"]
        if self.market_context:
            steps.append("Research the market context (approved pages and up to 3 web searches)")
        steps.append("Draft the summary for: " + ", ".join(ANGLE_WORDS[a] for a in self.angles) + " (Reporting Agents)")
        steps.append("Judge the drafts against the checklist and pick the best (Judge Agent and code)")
        if self.manager_questions:
            steps.append("Write the questions to ask the manager (code)")
        steps.append("Build the report for the analyst to judge and sign (code, then a person)")
        return steps

    def to_dict(self) -> dict:
        return asdict(self) | {"tasks": self.tasks}


def checked_plan(out: PlanOutput) -> TaskPlan:
    """ Code's checks: every question stays (named ones first), angles from the menu, at least one """
    focus = list(dict.fromkeys(q for q in out.focus if q in QUESTIONS))
    focus += [q for q in QUESTIONS if q not in focus]
    angles = list(dict.fromkeys(a for a in out.angles if a in ANGLES)) or list(ANGLES)
    return TaskPlan(out.report_type, focus, out.market_context, out.manager_questions, angles,
                    out.reason.strip()[:200], "planner")


def task_planner_agent() -> Agent:
    return Agent(name="Task Planner Agent", instructions=INSTRUCTIONS, output_type=PlanOutput,
                 **model_kwargs("task_planner"))


def planner_input(question: str, profile: FundProfile) -> str:
    """ Public details only """
    details = {"fund_name": profile.fund_name, "objective_type": profile.objective_type,
               "benchmark_name": profile.benchmark_name, "as_of_date": profile.as_of_date.isoformat()}
    return f"Request: {question}\nFund (public details): {json.dumps(details)}"


async def plan_tasks(question: str, profile: FundProfile, run: RunFn | None = None) -> tuple[TaskPlan, list[DataFlag]]:
    result = await run_structured(task_planner_agent(), planner_input(question, profile), PlanOutput,
                                  convert=checked_plan, run=run)
    if result.ok:
        return result.output, []
    return TaskPlan(reason="Default plan: the Task Planner gave no valid answer"), [DataFlag(
        check="task_planner", level="info", message=(
            "The Task Planner Agent gave no valid plan, so the default plan was used (all sections, all angles): "
            + "; ".join(result.errors)[:200]))]
