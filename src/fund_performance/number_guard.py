""" Number guard (spec 8.3) and rating guard: checks the Oversight Analyst's text before it is used

Number guard: every figure in the text must match a value in the facts JSON, with the same unit, allowing
rounding to 1 or 2 d.p. ("-0.10 pp" never matches a 0.10% return). Years, periods and counts are not
figures: a whole number with no % or pp (2024, "5 years", "3y", "4 questions", "5 of 5") is not checked.

Rating guard: the text must not state a rating or verdict other than the one code decided.
"""
from dataclasses import dataclass
import re

UNIT_PCT, UNIT_PP, UNIT_NONE = "%", "pp", None
_MINUS = str.maketrans({"−": "-", "–": "-"})
_DATES = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")
_NUMBER = re.compile(r"(?<![\w.])(-)?(\d+(?:,\d{3})*(?:\.\d+)?)(?![\w.]*\d)")
_PERIOD_AFTER = re.compile(r"^\s?-?\s?(years?|yrs?|y|months?|m|weeks?|days?|quarters?)\b", re.IGNORECASE)
_UNIT_AFTER = re.compile(r"^\s?(%|pp\b|percentage points?\b|bps?\b|basis points?\b)", re.IGNORECASE)


@dataclass(frozen=True)
class Number:
    value: float          # as written, with its sign
    decimals: int
    unit: str | None      # "%", "pp" or None
    text: str


def numbers_in(text: str) -> list[Number]:
    """ The figures in a text that need checking (years, periods, counts and dates are left out) """
    text = _DATES.sub(" ", text.translate(_MINUS))
    found = []
    for m in _NUMBER.finditer(text):
        sign, digits = m.group(1), m.group(2)
        after = text[m.end():]
        if _PERIOD_AFTER.match(after):
            continue                                       # "5 years", "3y", "12-month"
        unit_match = _UNIT_AFTER.match(after)
        word = unit_match.group(1).lower() if unit_match else ""
        unit = UNIT_PCT if word == "%" else UNIT_PP if word else UNIT_NONE
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        if decimals == 0 and unit is None:
            continue                                       # years, counts, "S&P 500", "5 of 5"
        value = float(digits.replace(",", "")) * (-1 if sign else 1)
        if word.startswith("b"):                           # basis points -> percentage points
            value, decimals = value / 100, decimals + 2
        found.append(Number(value, decimals, unit, m.group(0) + (unit_match.group(0) if unit_match else "")))
    return found


def _unit_of(figure_unit: str | None) -> str | None:
    return UNIT_PCT if figure_unit == "%" else UNIT_PP if figure_unit == "pp" else UNIT_NONE


def allowed_numbers(facts: dict) -> set[tuple[float, str | None]]:
    """ Every (value, unit) in the facts: figures with their units, numeric fields, and numbers written
    inside the facts' own text (reasons, notes, flags) with the unit written there """
    allowed: set[tuple[float, str | None]] = set()

    def walk(node, key: str = ""):
        if isinstance(node, dict):
            if "value" in node and "unit" in node and isinstance(node["value"], (int, float)):
                allowed.add((float(node["value"]), _unit_of(node["unit"])))
            for k, v in node.items():
                if k not in ("value",):
                    walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            allowed.add((float(node), UNIT_PCT if key.endswith("_pct") else UNIT_PP if key.endswith("_pp") else UNIT_NONE))
        elif isinstance(node, str):
            for n in numbers_in(node):
                allowed.add((n.value, n.unit))
    walk(facts)
    return allowed


def _matches(n: Number, value: float, unit: str | None) -> bool:
    """ Same unit, and the fact rounds to what is written: to 1 or 2 d.p. (any tie rule), or exactly for a
    whole number. A sign may be left out when the words carry it ("0.10 pp behind"), but a written minus
    must match a negative fact """
    if unit != n.unit:
        return False
    target = value if n.value < 0 else abs(value)
    if n.decimals == 0:
        return abs(target - n.value) < 1e-9
    return abs(target - n.value) <= 0.5 * 10 ** -n.decimals + 1e-9


def mentions(text: str, value: float, unit: str | None) -> bool:
    """ True if the text states this figure (same unit, rounded to 1 or 2 d.p., sign optional) """
    unit = _unit_of(unit) if unit not in (UNIT_PCT, UNIT_PP, UNIT_NONE) else unit
    return any(_matches(Number(abs(n.value), n.decimals, n.unit, n.text), abs(value), unit) for n in numbers_in(text))


def check_numbers(text: str, facts: dict) -> list[str]:
    """ The figures in the text that match nothing in the facts """
    allowed = allowed_numbers(facts)
    return [n.text.strip() for n in numbers_in(text) if not any(_matches(n, v, u) for v, u in allowed)]


# --- Rating guard -------------------------------------------------------------------------------------------

RATING_WORDS = {"green": "GREEN", "amber": "AMBER", "red": "RED", "check data": "CHECK DATA",
                "manual check": "MANUAL CHECK"}
PILLAR_WORDS = {"Mandate": ("mandate",), "Performance": ("performance",),
                "Value for investors": ("value for investors", "value"), "Fees": ("fees", "fee")}
VERDICT_WORDS = ("Retain", "Monitor", "Review", "Pending data check")


def _positions(lower: str, words: dict) -> list[tuple[int, str]]:
    return sorted((m.start(), key) for key, options in words.items()
                  for w in options for m in re.finditer(rf"\b{re.escape(w)}\b", lower))


def check_ratings(text: str, scorecard: dict) -> list[str]:
    """ Sentences that give a pillar a rating code did not give it, or state a verdict other than the decided
    one. Each rating word is checked against the nearest pillar named before it in the sentence (or after
    it, if none is named before), so swapped ratings are caught too """
    ratings = {p["name"]: p["rating"] for p in scorecard["pillars"]}
    verdict = scorecard["verdict"]
    rating_words = {code: (word,) for word, code in RATING_WORDS.items()}
    problems = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        lower = sentence.lower()
        pillars = _positions(lower, PILLAR_WORDS)
        for pos, code in _positions(lower, rating_words):
            before = [name for p, name in pillars if p < pos]
            after = [name for p, name in pillars if p > pos]
            pillar = before[-1] if before else (after[0] if after else None)
            if pillar and ratings[pillar] != code:
                problems.append(f"rating: '{sentence.strip()}' calls {pillar} {code}; the scorecard says {ratings[pillar]}")
        for word in VERDICT_WORDS:
            # Verdict words are capitalised in the report; a verdict other than the decided one is a change
            if re.search(rf"\b{word}\b", sentence) and word.lower() not in verdict.lower():
                problems.append(f"verdict: '{sentence.strip()}' uses '{word}'; the draft verdict is '{verdict}'")
    return problems
