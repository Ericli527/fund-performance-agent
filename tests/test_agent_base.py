""" Shared agent set-up: models per agent, temperature vs reasoning effort, .env loading, retry rules """
import asyncio
import os
import pytest
import yaml
from pydantic import BaseModel, ValidationError
from agents.exceptions import ModelBehaviorError
from fund_performance.agents.base import build_agent, load_env, model_settings, run_structured, ENV_FILE
from fund_performance.config import MODELS_PATH, ModelSpec, load_models
from conftest import ROOT, FakeRun


class Out(BaseModel):
    value: int


# config/models.yaml
def test_models_per_agent_match_the_owner_decision(monkeypatch):
    for agent in ("extractor", "mandate", "planner", "search", "analyst", "evaluator"):
        monkeypatch.delenv(f"FUND_MODEL_{agent.upper()}", raising=False)
    m = load_models()
    assert {a: m.for_agent(a)[0] for a in m.agents} == {
        "extractor": "gpt-5.4-mini", "mandate": "gpt-5.4-mini", "planner": "gpt-5.4-mini",
        "search": "gpt-5.4-mini", "analyst": "gpt-5.4", "evaluator": "gpt-6.1-sol"}


def test_an_environment_variable_overrides_one_agent_only(monkeypatch):
    monkeypatch.setenv("FUND_MODEL_ANALYST", "gpt-5.4-mini")
    m = load_models()
    assert m.for_agent("analyst")[0] == "gpt-5.4-mini" and m.for_agent("evaluator")[0] == "gpt-6.1-sol"


def test_an_override_must_be_a_listed_model(monkeypatch):
    monkeypatch.setenv("FUND_MODEL_MANDATE", "some-unlisted-model")
    with pytest.raises(ValueError, match="not listed"):
        load_models().for_agent("mandate")


@pytest.mark.parametrize("change,message", [
    (lambda d: d["agents"].pop("evaluator"), "no model set"),
    (lambda d: d["agents"].update(search="gpt-x"), "not listed"),
    (lambda d: d["models"]["gpt-5.4"].update(temperature=0), "does not support"),
    (lambda d: d["models"]["gpt-5.4"].pop("reasoning_effort"), "reasoning_effort"),
])
def test_models_config_mistakes_are_rejected(tmp_path, change, message):
    data = yaml.safe_load(MODELS_PATH.read_text())
    change(data)
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValidationError, match=message):
        load_models(path)


# Temperature only where the model accepts it; otherwise a low reasoning effort
def test_a_model_that_supports_temperature_gets_temperature_0_and_no_reasoning():
    settings = model_settings(ModelSpec(supports_temperature=True, temperature=0))
    assert settings.temperature == 0 and settings.reasoning is None


def test_a_reasoning_model_gets_low_effort_and_no_temperature():
    settings = model_settings(ModelSpec(supports_temperature=False, reasoning_effort="low"))
    assert settings.temperature is None and settings.reasoning.effort == "low"


def test_build_agent_sends_what_the_model_supports(tmp_path, monkeypatch):
    data = yaml.safe_load(MODELS_PATH.read_text())
    data["models"]["gpt-4.1-mini"] = {"supports_temperature": True, "temperature": 0}
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr("fund_performance.agents.base.load_models", lambda: load_models(path))
    monkeypatch.setenv("FUND_MODEL_MANDATE", "gpt-4.1-mini")
    agent = build_agent("Test", "x", Out, "mandate")
    assert agent.model == "gpt-4.1-mini" and agent.model_settings.temperature == 0 and agent.model_settings.reasoning is None
    monkeypatch.delenv("FUND_MODEL_MANDATE")
    agent = build_agent("Test", "x", Out, "mandate")
    assert agent.model == "gpt-5.4-mini" and agent.model_settings.temperature is None
    assert agent.model_settings.reasoning.effort == "low"


# .env loading
def test_env_file_is_the_project_root_and_gitignored():
    assert ENV_FILE == ROOT / ".env"
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()


def test_load_env_reads_the_key_from_a_dot_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-test-not-a-real-key\n")
    assert load_env(env) is True
    assert os.environ["OPENAI_API_KEY"] == "sk-test-not-a-real-key"


def test_load_env_never_replaces_a_key_already_set(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-the-environment")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-the-file\n")
    load_env(env)
    assert os.environ["OPENAI_API_KEY"] == "from-the-environment"


# Retry rules
def test_valid_first_time():
    result = asyncio.run(run_structured(None, "p", Out, run=FakeRun({"value": 1})))
    assert result.ok and result.output.value == 1 and result.attempts == 1


def test_one_retry_then_give_up():
    fake = FakeRun({"value": "x"}, ModelBehaviorError("bad"), {"value": 3})
    result = asyncio.run(run_structured(None, "p", Out, run=fake))
    assert not result.ok and result.attempts == 2 and len(fake.prompts) == 2
