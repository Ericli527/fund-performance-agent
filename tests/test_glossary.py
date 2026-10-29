""" One glossary for the Analyst prompt and the report """
from fund_performance.agents.analyst import INSTRUCTIONS
from fund_performance.glossary import GLOSSARY, glossary_lines, used_in


def test_the_terms_asked_for():
    assert list(GLOSSARY) == ["tracking difference", "tracking error", "NAV", "PNAV", "ongoing charge (OCF)", "R²",
                              "beta", "alpha", "Sharpe ratio", "information ratio", "largest fall", "pp",
                              "Assessment of Value (AoV)", "AFM"]


def test_only_the_terms_used_are_listed():
    text = "Fund (PNAV) 90.9%, gap −0.7 pp. Beta 1.00. It does not replace the AFM's formal Assessment of Value."
    assert list(used_in(text)) == ["PNAV", "beta", "pp", "Assessment of Value (AoV)", "AFM"]
    assert "NAV" in used_in("Fund, noon price (NAV)") and "NAV" not in used_in("PNAV only")
    assert used_in("an alphabet and a ppt file") == {}


def test_each_definition_is_under_10_words():
    for term, definition in GLOSSARY.items():
        assert len(definition.split()) < 10, term


def test_the_analyst_prompt_uses_the_same_definitions():
    for line in glossary_lines():
        assert line in INSTRUCTIONS
