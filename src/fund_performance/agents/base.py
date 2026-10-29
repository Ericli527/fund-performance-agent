""" Shared set-up for the AI agents (spec Section 8): one low-cost model at temperature 0, structured
output validated with Pydantic, one retry on invalid output, then a CHECK DATA flag

The API key is read by the OpenAI SDK from the OPENAI_API_KEY environment variable only; no key is ever
passed in code.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import os
from typing import Any, Generic, TypeVar
from agents import Agent, ModelSettings, Runner
from agents.exceptions import AgentsException, ModelBehaviorError
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gpt-4.1-mini"     # low cost, supports temperature 0 and structured outputs
MAX_ATTEMPTS = 2                   # the first try and one retry (owner decision)

T = TypeVar("T")
RunFn = Callable[[Agent, str], Awaitable[Any]]


def model_name() -> str:
    """ The model can be changed with FUND_AGENT_MODEL without touching code """
    return os.getenv("FUND_AGENT_MODEL", DEFAULT_MODEL)


def build_agent(name: str, instructions: str, output_type: type[BaseModel]) -> Agent:
    return Agent(name=name, instructions=instructions, model=model_name(), output_type=output_type,
                 model_settings=ModelSettings(temperature=0))


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
