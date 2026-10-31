""" Shared set-up for the AI agents (spec Section 8): each agent's model comes from config/models.yaml,
structured output is validated with Pydantic, invalid output is retried once, then a CHECK DATA flag

The API key is read by the OpenAI SDK from the OPENAI_API_KEY environment variable only; no key is ever
passed in code. load_env() copies it from the project's .env file into the environment.
Data sharing is on for this key: public data only, never confidential or client data.
"""
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
import time
from typing import Any, Generic, TypeVar
from pathlib import Path
from agents import Agent, ModelSettings, RunConfig, Runner
from agents.exceptions import AgentsException, ModelBehaviorError
from agents.models.openai_provider import OpenAIProvider
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError
from openai.types.shared import Reasoning
from pydantic import BaseModel, ValidationError
from fund_performance.config import AgentName, ModelSpec, load_models

MAX_ATTEMPTS = 2                   # the first try and one retry (owner decision)
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"     # gitignored

T = TypeVar("T")
RunFn = Callable[[Agent, str], Awaitable[Any]]


def load_env(path: Path = ENV_FILE) -> bool:
    """ Copy OPENAI_API_KEY (and other settings) from .env into the environment. A value already set in
    the environment is kept. Returns True if a .env file was found """
    return load_dotenv(path, override=False)


def model_settings(spec: ModelSpec, tool_choice: str | None = None) -> ModelSettings:
    """ Temperature only for models that accept it; reasoning models get a low reasoning effort instead """
    if spec.supports_temperature:
        return ModelSettings(temperature=spec.temperature, tool_choice=tool_choice)
    return ModelSettings(reasoning=Reasoning(effort=spec.reasoning_effort), tool_choice=tool_choice)


def model_kwargs(agent: AgentName, tool_choice: str | None = None) -> dict:
    """ The agent's model and settings from config/models.yaml, for Agent(..., **model_kwargs("judge")) """
    load_env()
    model, spec = load_models().for_agent(agent)
    return {"model": model, "model_settings": model_settings(spec, tool_choice)}


def build_agent(name: str, instructions: str, output_type: type[BaseModel], agent: AgentName,
                tools: list | None = None, tool_choice: str | None = None) -> Agent:
    return Agent(name=name, instructions=instructions, output_type=output_type, tools=tools or [],
                 **model_kwargs(agent, tool_choice))


async def run_with_fresh_client(agent: Agent, prompt: str, *, context: Any = None, max_turns: int = 10) -> Any:
    """ Run an agent with a new OpenAI client, closed afterwards.

    The SDK otherwise reuses one shared client whose connections belong to the first event loop; once
    that loop is closed (e.g. by asyncio.run), the next agent fails with "Event loop is closed". A client
    per run keeps agents independent, so they can run one after another in any loop """
    client = AsyncOpenAI()          # reads OPENAI_API_KEY from the environment
    try:
        return await Runner.run(agent, prompt, context=context, max_turns=max_turns,
                                run_config=RunConfig(model_provider=OpenAIProvider(openai_client=client)))
    finally:
        await client.close()


def api_key_present() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


@dataclass
class StructuredResult(Generic[T]):
    """ The validated (and converted) output, or None after two invalid attempts or a failed call """
    output: T | None
    attempts: int
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output is not None


# Every model call of one review, for log.json and the page: agent, attempt, seconds, outcome (set by the controller)
AI_CALLS: ContextVar[list[dict] | None] = ContextVar("AI_CALLS", default=None)


def _record(agent: Agent, attempt: int, started: float, outcome: str) -> None:
    calls = AI_CALLS.get()
    if calls is not None:
        calls.append({"agent": agent.name, "attempt": attempt, "seconds": round(time.monotonic() - started, 2),
                      "outcome": outcome})


async def run_structured(agent: Agent, prompt: str, output_model: type[BaseModel],
                         convert: Callable[[Any], T] | None = None, run: RunFn | None = None,
                         attempts: int = MAX_ATTEMPTS, context: Any = None,
                         max_turns: int | None = None) -> StructuredResult[T]:
    """ Run an agent and validate its output; invalid output is retried once (attempts=1: no retry).

    `convert` turns the agent's output into the internal shape (it may raise ValueError, which counts as
    invalid output). `run` replaces the real model call in unit tests """
    if run is None:
        # The real model call. An agent with tools gets its run context (read only, this review's facts) and a bound
        # on model turns, so its tool calls cannot loop. Looked up at call time, so tests can replace it
        async def run(agent, prompt):
            kwargs = {"context": context} if context is not None else {}
            return await run_with_fresh_client(agent, prompt, max_turns=max_turns or 10, **kwargs)
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            result = await run(agent, prompt)
            output = output_model.model_validate(result.final_output) if not isinstance(
                result.final_output, output_model) else result.final_output
            converted = convert(output) if convert else output
            _record(agent, attempt, started, "ok")
            return StructuredResult(converted, attempt, errors)
        except (ValidationError, ModelBehaviorError, ValueError) as e:
            _record(agent, attempt, started, "invalid output")
            errors.append(f"attempt {attempt}: invalid output ({type(e).__name__}: {str(e)[:200]})")
        except (AgentsException, OpenAIError) as e:
            # A failed call (network, key, quota) is not invalid output: no retry
            _record(agent, attempt, started, "call failed")
            errors.append(f"attempt {attempt}: call failed ({type(e).__name__}: {str(e)[:200]})")
            return StructuredResult(None, attempt, errors)
    return StructuredResult(None, attempts, errors)
