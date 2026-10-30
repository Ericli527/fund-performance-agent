""" Stage 3: facts.json, the web dashboard, the Executive Report and the Detailed Report agree on the verdict, the
four ratings and the headline figures (all from the shared presentation helpers). Uses the committed demo fund,
so it runs everywhere, CI included """
import asyncio
import json
from html import unescape
from pathlib import Path
import re
import pytest
from fund_performance.controller import run_review
from fund_performance.dashboard import dashboard_data, dashboard_html
from fund_performance.plain import verdict_name
from fund_performance.presentation import RATING_STYLE, headline_metrics
from fund_performance.report import page_texts

DEMO = Path(__file__).resolve().parents[1] / "demo" / "sample_index_fund"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return asyncio.run(run_review(DEMO, out_root=tmp_path_factory.mktemp("runs"), offline=True))


def flat(text: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())


def test_verdict_ratings_and_headline_figures_agree_everywhere(run):
    facts = json.loads((run.run_dir / "facts.json").read_text())
    assert facts == json.loads(json.dumps(run.facts))
    verdict = verdict_name(facts["scorecard"]["verdict"])
    ratings = [RATING_STYLE[p["rating"]][0] for p in facts["scorecard"]["pillars"]]
    metrics = [m.value for m in headline_metrics(facts)]
    dashboard = flat(dashboard_html(dashboard_data(run), "management"))
    executive = [flat(x) for x in page_texts(run.executive_pdf)]
    detailed = [flat(x) for x in page_texts(run.pdf)]
    for surface in (dashboard, executive[0], detailed[0]):
        assert verdict in surface
        for value in metrics:
            assert value in surface, value
        for name, word in zip(("Mandate", "Performance", "Value for investors", "Fees"), ratings):
            assert re.search(rf"{re.escape(name)}.{{0,60}}{word}", surface), (name, word)
    body = lambda text: flat(text.split("\n", 1)[1])                          # noqa: E731 - without the footer line
    assert [body(x) for x in page_texts(run.executive_pdf)] == [body(x) for x in page_texts(run.pdf)[:2]]


def test_two_executive_pages_and_every_appendix_in_the_detailed_report(run):
    from fund_performance.report import APPENDIX_TITLES
    assert len(page_texts(run.executive_pdf)) == 2
    detailed = " ".join(page_texts(run.pdf))
    assert all(title in detailed for title in APPENDIX_TITLES)
