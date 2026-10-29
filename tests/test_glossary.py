""" One glossary for the Analyst prompt and the report """
from fund_performance.agents.analyst import INSTRUCTIONS
from fund_performance.glossary import GLOSSARY, glossary_lines


def test_the_terms_asked_for():
    assert list(GLOSSARY) == ["tracking difference", "tracking error", "PNAV", "ongoing charge (OCF)", "R²", "beta", "pp"]


def test_each_definition_is_under_10_words():
    for term, definition in GLOSSARY.items():
        assert len(definition.split()) < 10, term


def test_the_analyst_prompt_uses_the_same_definitions():
    for line in glossary_lines():
        assert line in INSTRUCTIONS
