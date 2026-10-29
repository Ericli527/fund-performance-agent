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
    return [n for _, _, n in _figures(text)]


def _figures(text: str) -> list[tuple[int, int, Number]]:
    """ numbers_in, with each figure's start and end in the text (dates are blanked, so positions hold) """
    text = _DATES.sub(lambda d: " " * len(d.group(0)), text.translate(_MINUS))
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
        found.append((m.start(), m.end(), Number(value, decimals, unit,
                                                 m.group(0) + (unit_match.group(0) if unit_match else ""))))
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


# --- Label guard -------------------------------------------------------------------------------------------
# A figure named "tracking difference", "tracking error" or "ongoing charge" must be a fact of that type, for
# the period named nearby and in its unit. E.g. "tracking difference -3.3 pp" is wrong when -3.3 pp is the
# 5-year noon-price gap. Tracking differences are yearly, signed and for a period: "a year", the sign (a minus,
# or a word such as "behind") and the period ("over 5 years") must be there.

LABEL_WINDOW_WORDS = 8
LABELS = (("cost_adjusted", re.compile(r"cost[- ]adjusted (?:tracking difference|gap)", re.I)),
          ("tracking_difference", re.compile(r"tracking difference", re.I)),
          ("tracking_error", re.compile(r"tracking error", re.I)),
          ("ocf", re.compile(r"ongoing charges?|\bOCF\b", re.I)))
LABEL_WORDS = {"cost_adjusted": "cost-adjusted tracking difference", "tracking_difference": "tracking difference",
               "tracking_error": "tracking error", "ocf": "ongoing charge"}
YEARLY_LABELS = {"cost_adjusted", "tracking_difference"}
_YEARLY = re.compile(r"\ba year\b|\bper year\b|\byearly\b|\bannual(?:ly|ised)?\b|\beach year\b|\bper annum\b|\bp\.a\.",
                     re.I)
_DIRECTION = re.compile(r"\b(behind|below|lags?|lagged|trails?|trailed|short of|under)\b", re.I)
_PERIOD_NEAR = re.compile(r"\b(\d+|one|three|five|ten)[- ]years?\b|\b(12|twelve)[- ]months?\b", re.I)
_CLAUSE_BREAK = re.compile(r"[,;:.!?]|\b(but|while|whereas)\b", re.I)
_WORDS_IN = {"one": "1", "three": "3", "five": "5", "ten": "10", "twelve": "1"}


@dataclass(frozen=True)
class TypedFact:
    kind: str                  # cost_adjusted, tracking_difference, tracking_error, ocf
    value: float
    unit: str | None
    period: str | None         # "5y" or None


def _kind_of_name(name: str) -> str | None:
    parts = name.split(".")
    if "td_ex_cost" in parts:
        return "cost_adjusted"
    if "td" in parts:
        return "tracking_difference"
    if "tracking_error" in parts:
        return "tracking_error"
    return None


def _kind_of_label(label: str) -> str | None:
    lower = label.lower()
    if lower.startswith("cost-adjusted"):
        return "cost_adjusted"
    if lower.startswith(("tracking difference", "fund behind its index")):
        return "tracking_difference"
    if lower.startswith("tracking error"):
        return "tracking_error"
    if lower.startswith("ongoing charge"):
        return "ocf"
    return None


def typed_facts(facts: dict) -> list[TypedFact]:
    """ The facts that have a labelled type: figures by name, data-note figures by label, and the OCF """
    found = []
    for f in facts.get("figures", []):
        kind = _kind_of_name(f.get("name", ""))
        if kind and isinstance(f.get("value"), (int, float)):
            last = f["name"].rsplit(".", 1)[-1]
            found.append(TypedFact(kind, float(f["value"]), _unit_of(f["unit"]), last if last.endswith("y") else None))
    for note in facts.get("data_notes", []):
        for f in note.get("figures", []):
            kind = _kind_of_label(f.get("label", ""))
            if kind:
                last = f["label"].rsplit(", ", 1)[-1]
                found.append(TypedFact(kind, float(f["value"]), _unit_of(f["unit"]),
                                       last if re.fullmatch(r"\d+y", last) else None))
    ocf = facts.get("fund", {}).get("ocf_pct")
    if isinstance(ocf, (int, float)):
        found.append(TypedFact("ocf", float(ocf), UNIT_PCT, None))
    return found


def _label_spans(sentence: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for kind, pattern in LABELS:
        for m in pattern.finditer(sentence):
            if not any(s <= m.start() < e for s, e, _ in spans):      # "cost-adjusted tracking difference" once
                spans.append((m.start(), m.end(), kind))
    return sorted(spans)


def _word_count(text: str) -> int:
    """ Words only: a comma or bracket on its own is not a word """
    return sum(1 for w in text.split() if any(c.isalnum() for c in w))


def check_labels(text: str, facts: dict) -> list[str]:
    """ Figures next to a label (within 8 words, in the same sentence) that are not a fact of that type, period
    and unit; yearly tracking differences also need "a year" and their sign """
    typed = typed_facts(facts)
    problems = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])|\n+", text.translate(_MINUS)):
        labels = _label_spans(sentence)
        if not labels:
            continue
        numbers = _figures(sentence)
        for start, end, n in numbers:
            label = _nearest_label(sentence, labels, numbers, start, end)
            if label is None:
                continue
            kind = label[2]
            window = _window(sentence, start, end)
            period = _period_in(window)
            candidates = [f for f in typed if f.kind == kind and f.unit == n.unit
                          and (period is None or f.period in (None, period))]
            where = f"'{n.text.strip()}' next to '{sentence[label[0]:label[1]]}'"
            match = next((f for f in candidates if _matches(Number(abs(n.value), n.decimals, n.unit, n.text),
                                                            abs(f.value), f.unit)), None)
            if match is None:
                period_text = f" for {period[:-1]} years" if period else ""
                article = "an" if LABEL_WORDS[kind][0] in "aeiou" else "a"
                problems.append(f"label: {where} is not {article} {LABEL_WORDS[kind]}{period_text} in the facts")
                continue
            if kind in YEARLY_LABELS:
                if not _YEARLY.search(window):
                    problems.append(f"label: {where} is a yearly figure; add 'a year'")
                if period is None:
                    problems.append(f"label: {where} needs its period; add '{_period_hint(candidates, match, facts)}'")
                if match.value < 0 and n.value >= 0 and not _DIRECTION.search(window):
                    problems.append(f"label: {where} is negative; write the minus sign or say 'behind'")
    return problems


def _nearest_label(sentence: str, labels, numbers, start: int, end: int):
    """ The label this figure belongs to: the nearest one before it within 8 words with no other figure in
    between, else the nearest one after it in the same clause """
    best = None
    for s, e, kind in labels:
        if e <= start:
            gap = sentence[e:start]
            if _word_count(gap) <= LABEL_WINDOW_WORDS and not any(e <= ns < start for ns, _, _ in numbers):
                best = (s, e, kind)                                   # the last one before wins
    if best:
        return best
    for s, e, kind in labels:
        if s >= end:
            gap = sentence[end:s]
            if (_word_count(gap) <= LABEL_WINDOW_WORDS and not _CLAUSE_BREAK.search(gap)
                    and not any(end <= ns < s for ns, _, _ in numbers)):
                return (s, e, kind)
    return None


def _window(sentence: str, start: int, end: int) -> str:
    before = sentence[:start].split()[-LABEL_WINDOW_WORDS:]
    after = sentence[end:].split()[:LABEL_WINDOW_WORDS]
    return " ".join(before + [sentence[start:end]] + after)


def _period_hint(candidates: list[TypedFact], match: TypedFact, facts: dict) -> str:
    """ The period to name, from the facts: the main test period if this figure is given for it, else the
    figure's own period """
    same = [f for f in candidates if f.period and abs(abs(f.value) - abs(match.value)) < 1e-9]
    periods = [f.period for f in same]
    main = f"{facts.get('fund', {}).get('time_horizon_years', '')}y"
    period = main if main in periods else (match.period or (periods[0] if periods else main))
    years = period[:-1]
    return f"over {years} year{'' if years == '1' else 's'}"


def _period_in(window: str) -> str | None:
    m = _PERIOD_NEAR.search(window)
    if not m:
        return None
    word = (m.group(1) or m.group(2)).lower()
    if m.group(2):
        return "1y"
    return f"{_WORDS_IN.get(word, word)}y"
