""" Shared test paths. The real Test 1 files live in data/ (gitignored), so tests that need them skip when absent """
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TEST1 = ROOT / "data" / "test1"
TEST1_CSV = TEST1 / "Fidelity_Index_US_P_Acc.csv"
TEST1_FACTSHEET = TEST1 / "factsheet_performance.json"
TEST1_PROFILE = TEST1 / "fund_profile.json"

requires_test1 = pytest.mark.skipif(
    not all(p.exists() for p in (TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE)),
    reason="Test 1 files are not in data/test1 (they are kept out of the public repo)")


# Live AI tests: skipped unless run with --run-live (and OPENAI_API_KEY set in the environment or .env)
def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False, help="run tests that call the OpenAI API")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls the OpenAI API; run with --run-live")


def pytest_collection_modifyitems(config, items):
    import os
    if config.getoption("--run-live"):
        from fund_performance.agents.base import load_env
        load_env()                              # .env -> environment; code reads the key from there only
        if os.getenv("OPENAI_API_KEY"):
            return
        reason = "OPENAI_API_KEY is not set"
    else:
        reason = "live AI test: run with --run-live"
    for item in items:
        if "live" in item.keywords:
            item.add_marker(pytest.mark.skip(reason=reason))


class FakeRun:
    """ Stands in for the model call in unit tests: returns the given outputs (or raises the given errors) in order """
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    async def __call__(self, agent, prompt):
        from types import SimpleNamespace
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(final_output=response)


class FakeRunBy:
    """ Like FakeRun, but answers by prompt (for agents run in parallel, whose order is not fixed) """
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def __call__(self, agent, prompt):
        from types import SimpleNamespace
        self.prompts.append(prompt)
        response = self.answer(prompt)
        if hasattr(response, "__await__"):
            response = await response
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(final_output=response)


@pytest.fixture(autouse=True)
def _no_approved_peer_files(request, tmp_path_factory, monkeypatch):
    """ Unit tests never read the real approved peers in data/peers/ (that would call the Extractor); tests that
    want approved peers point FUND_PEER_FOLDER at their own folder. Live tests use the real folder """
    if "live" not in request.keywords:
        monkeypatch.setenv("FUND_PEER_FOLDER", str(tmp_path_factory.mktemp("no_peers")))
