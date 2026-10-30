""" One set of definitions for the technical terms, shared by the Oversight Analyst's prompt and the report's
glossary (step 9), so the two always say the same thing. Each definition is under 10 words.

The report's glossary lists only the terms its text actually uses (`used_in`).
"""
import re

GLOSSARY: dict[str, str] = {
    "tracking difference": "how far the fund's return is from its index's",
    "tracking error": "how much that gap varies from month to month",
    "NAV": "net asset value: the fund's price per unit",
    "PNAV": "the fund's price worked out at market close",
    "ongoing charge (OCF)": "the yearly fee taken from the fund",
    "R²": "how closely fund and index move together",
    "beta": "how much the fund moves when the index moves",
    "alpha": "return above what the index's moves would explain",
    "Sharpe ratio": "return earned for each unit of risk taken",
    "information ratio": "gap to the index divided by tracking error",
    "largest fall": "the biggest drop from a peak to a low",
    "pp": "percentage points, the gap between two percentages",
    "Assessment of Value (AoV)": "the yearly value review UK fund managers publish",
    "AFM": "authorised fund manager, legally responsible for the fund",
    "t-statistic": "the average gap measured against its own variation",
    "p-value": "the chance of a gap this large by luck",
    "statistically significant": "unlikely to be chance (p-value below 5%)",
    "percentile": "the share of peers the fund did better than",
    "drawdown": "a fall from a peak, as a percentage",
}

# How each term shows up in text (a term is in the report's glossary only if its text matches)
_PATTERNS: dict[str, re.Pattern] = {
    "tracking difference": re.compile(r"tracking difference", re.I),
    "tracking error": re.compile(r"tracking error", re.I),
    "NAV": re.compile(r"\bNAV\b"),
    "PNAV": re.compile(r"\bPNAV\b"),
    "ongoing charge (OCF)": re.compile(r"ongoing charge|\bOCF\b", re.I),
    "R²": re.compile(r"R²"),
    "beta": re.compile(r"\bbeta\b", re.I),
    "alpha": re.compile(r"\balpha\b", re.I),
    "Sharpe ratio": re.compile(r"Sharpe ratio", re.I),
    "information ratio": re.compile(r"information ratio", re.I),
    "largest fall": re.compile(r"largest fall", re.I),
    "pp": re.compile(r"\bpp\b"),
    "Assessment of Value (AoV)": re.compile(r"Assessment of Value|\bAoV\b"),
    "AFM": re.compile(r"\bAFM\b"),
    "t-statistic": re.compile(r"t-statistic", re.I),
    "p-value": re.compile(r"p-value|\bp [=<]", re.I),
    "statistically significant": re.compile(r"statistically significant", re.I),
    "percentile": re.compile(r"percentile", re.I),
    "drawdown": re.compile(r"drawdown", re.I),
}


def glossary_lines() -> list[str]:
    return [f"{term}: {definition}" for term, definition in GLOSSARY.items()]


def used_in(text: str) -> dict[str, str]:
    """ The glossary terms that appear in the text, in glossary order """
    return {term: definition for term, definition in GLOSSARY.items() if _PATTERNS[term].search(text)}
