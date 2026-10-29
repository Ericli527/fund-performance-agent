""" One set of definitions for the technical terms, shared by the Oversight Analyst's prompt and the report's
glossary (step 9), so the two always say the same thing. Each definition is under 10 words """

GLOSSARY: dict[str, str] = {
    "tracking difference": "how far the fund's return is from its index's",
    "tracking error": "how much that gap varies from month to month",
    "PNAV": "the fund's price worked out at market close",
    "ongoing charge (OCF)": "the yearly fee taken from the fund",
    "R²": "how closely fund and index move together (max 1)",
    "beta": "how much the fund moves when the index moves",
    "pp": "percentage points, the gap between two percentages",
}


def glossary_lines() -> list[str]:
    return [f"{term}: {definition}" for term, definition in GLOSSARY.items()]
