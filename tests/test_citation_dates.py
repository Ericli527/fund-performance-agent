""" Citation dates (code): a market-context sentence may not describe a month after its cited source's date """
import asyncio
from datetime import date
import pytest
from fund_performance.agents.analyst import LEFT_OUT, QUALITY_FAILED, write_narrative
from fund_performance.citation_dates import citation_date_problems, described_month
from conftest import FakeRun
from test_agent_analyst import FACTS

END = date(2026, 9, 30)
SOURCES = [{"number": 1, "date": "2026-09-25"}, {"number": 2, "date": "2026-06-30"}, {"number": 3, "date": "2025-11-03"}]


def test_the_full_run_case_is_rejected():
    """ All three sentences cited [3] (2025-11-03) but described the later part of the period and September 2026 """
    text = ("US shares rose in the later part of the period, led by large technology companies [3]. "
            "Gains continued into September 2026 [3]. Volatility rose late in the period [3].")
    problems = citation_date_problems(text, SOURCES, END)
    assert len(problems) == 3 and all(p.startswith("quality (sources_cited): sentence") for p in problems)
    assert "describes 'September 2026', after its newest cited source, dated 2025-11-03" in problems[1]


@pytest.mark.parametrize("sentence, ok", [
    ("Shares rose in October [3].", True),                         # October 2025, before the source
    ("Shares rose in October and November 2025 [3].", True),
    ("Shares rose in December 2025 [3].", False),
    ("In Q3 2026 shares rose [1].", True),
    ("In the third quarter of 2026 shares rose [2].", False),
    ("In the second half of 2025 shares rose [3].", False),
    ("Shares rose over the period [1].", True),
    ("Shares rose over the period [2].", False),                   # June 2026 cannot cover the whole period
    ("Shares rose in September 2026 [2][1].", True),               # the newest cited source counts
    ("Shares rose in 2026 [3].", True),                            # a year alone is not checked
    ("Rates may fall, said the Fed [3].", True),                   # "may" the verb is not a month
    ("In May shares fell [3].", False),
    ("Shares rose in September 2026.", True),                      # no citation: the citation check handles it
])
def test_sentences(sentence, ok):
    assert (citation_date_problems(sentence, SOURCES, END) == []) is ok


def test_months_without_a_year_fall_in_the_review_period():
    assert described_month("in October", END)[0] == 2025 * 12 + 9
    assert described_month("in March", END)[0] == 2026 * 12 + 2


def test_a_dated_problem_uses_the_evaluator_rewrite_then_leaves_the_market_context_out():
    sources = [{"query": "q", "summary": "Shares rose in October 2025.", "url": "https://example.com/a",
                "date": "2025-11-03"}]
    facts = FACTS | {"fund": FACTS["fund"] | {"as_of_date": "2026-09-30"}}
    late = {"market_context": "US shares rose in September 2026 [1]."}
    analyst = FakeRun(late, {"market_context": "US shares rose in October 2025 [1]."})
    result = asyncio.run(write_narrative(facts, sources, run=analyst))
    assert result.source == "ai" and "quality (sources_cited): sentence 1 describes 'September 2026'" in analyst.prompts[1]
    result = asyncio.run(write_narrative(facts, sources, run=FakeRun(late, late)))
    assert result.source == "template"
    assert result.flags[0].message == (f"{QUALITY_FAILED}: the market context describes months after its cited "
                                       f"sources (sources_cited); {LEFT_OUT}")


def test_the_rule_is_in_the_prompts():
    from fund_performance.agents.analyst import INSTRUCTIONS
    from fund_performance.agents.evaluator import INSTRUCTIONS as EVALUATOR
    for text in (INSTRUCTIONS, EVALUATOR):
        assert "claims must be covered by" in " ".join(text.split())
