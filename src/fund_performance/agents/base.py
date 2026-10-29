""" Shared set-up for the AI agents (spec Section 8): each agent's model comes from config/models.yaml,
structured output is validated with Pydantic, invalid output is retried once, then a CHECK DATA flag

The API key is read by the OpenAI SDK from the OPENAI_API_KEY environment variable only; no key is ever
passed in code. load_env() copies it from the project's .env file into the environment.
Data sharing is on for this key: public data only, never confidential or client data.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import os
from typing import Any, Generic, TypeVar
from pathlib import Path
from agents import Agent, ModelSettings, Runner
from agents.exceptions import AgentsException, ModelBehaviorError
from dotenv import load_dotenv
from openai import OpenAIError
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


def model_settings(spec: ModelSpec) -> ModelSettings:
    """ Temperature only for models that accept it; reasoning models get a low reasoning effort instead """
    if spec.supports_temperature:
        return ModelSettings(temperature=spec.temperature)
    return ModelSettings(reasoning=Reasoning(effort=spec.reasoning_effort))


def build_agent(name: str, instructions: str, output_type: type[BaseModel], agent: AgentName) -> Agent:
    load_env()
    model, spec = load_models().for_agent(agent)
    return Agent(name=name, instructions=instructions, model=model, output_type=output_type,
                 model_settings=model_settings(spec))


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


async def run_structured(agent: Agent, prompt: str, output_model: type[BaseModel],
                         convert: Callable[[Any], T] | None = None, run: RunFn | None = None) -> StructuredResult[T]:
    """ Run an agent and validate its output; invalid output is retried once.

    `convert` turns the agent's output into the internal shape (it may raise ValueError, which counts as
    invalid output). `run` replaces the real model call in unit tests """
    run = run or Runner.run
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await run(agent, prompt)
            output = output_model.model_validate(result.final_output) if not isinstance(
                result.final_output, output_model) else result.final_output
            return StructuredResult(convert(output) if convert else output, attempt, errors)
        except (ValidationError, ModelBehaviorError, ValueError) as e:
            errors.append(f"attempt {attempt}: invalid output ({type(e).__name__}: {str(e)[:200]})")
        except (AgentsException, OpenAIError) as e:
            # A failed call (network, key, quota) is not invalid output: no retry
            errors.append(f"attempt {attempt}: call failed ({type(e).__name__}: {str(e)[:200]})")
            return StructuredResult(None, attempt, errors)
    return StructuredResult(None, MAX_ATTEMPTS, errors)
