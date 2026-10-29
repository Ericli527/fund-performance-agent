""" Citation dates (code): a market-context sentence may not describe a month later than its cited source's date

From the full Test 1 run through the page: all three sentences cited [3] (published 2025-11-03) but described "the
later part of the period" and "September 2026". A sentence that names a time after its newest cited source is
rejected; it counts as a quality issue (sources_cited), so it uses the Evaluator's rewrite.

The latest month a sentence describes:
- a month, with or without a year ("September 2026", "Sep", in the review period when there is no year);
- a quarter or half year ("Q3 2026", "third quarter of 2026", "second half of 2026") -> its last month;
- the later part, end or whole of the review period ("later in the period", "over the period") -> the start of the
  period's last quarter (the period end minus 2 months).
A year on its own ("in 2026") is not checked.
"""
from datetime import date
import re

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}
_MONTH = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?(?:\s+(20\d\d))?",
                    re.IGNORECASE)
_QUARTER = re.compile(r"\bQ([1-4])\s*(20\d\d)\b|\b(first|second|third|fourth)\s+quarter(?:\s+of)?\s+(20\d\d)\b",
                      re.IGNORECASE)
_HALF = re.compile(r"\b(first|second)\s+half(?:\s+of)?\s+(20\d\d)\b", re.IGNORECASE)
_LATE_OR_WHOLE = re.compile(
    r"\b(?:later|latter|last|final|closing|second)\s+(?:part|half|months|stretch|quarter|weeks)\s+of\s+the\s+"
    r"(?:review\s+)?period\b|\bend\s+of\s+the\s+(?:review\s+)?period\b|\b(?:late|later)\s+in\s+the\s+(?:review\s+)?"
    r"period\b|\b(?:over|throughout|across|during)\s+the\s+(?:whole\s+|full\s+|entire\s+)?(?:review\s+)?period\b|"
    r"\b(?:recent|past|last)\s+(?:few\s+)?months\b|\bmost\s+recently\b",
    re.IGNORECASE)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_CITATION = re.compile(r"\[(\d+)\]")
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
# "may" is also a verb: only "May" with a capital, or followed by a year, is the month
_VERB_MAY = re.compile(r"\bmay\b(?!\s+20\d\d)")


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def _label(index: int) -> str:
    return date(index // 12, index % 12 + 1, 1).strftime("%B %Y")


def described_month(sentence: str, period_end: date) -> tuple[int, str] | None:
    """ The latest month the sentence describes, as (year*12 + month - 1, the words that say it), or None """
    end = _month_index(period_end.year, period_end.month)
    found: list[tuple[int, str]] = []
    for m in _MONTH.finditer(sentence):
        if m.group(1) == "may" and _VERB_MAY.match(sentence, m.start()):
            continue
        month = _MONTHS[m.group(1)[:3].lower()]
        year = int(m.group(2)) if m.group(2) else (period_end.year if month <= period_end.month else period_end.year - 1)
        found.append((_month_index(year, month), m.group(0).strip()))
    for m in _QUARTER.finditer(sentence):
        q = int(m.group(1)) if m.group(1) else _ORDINAL[m.group(3).lower()]
        found.append((_month_index(int(m.group(2) or m.group(4)), q * 3), m.group(0)))
    for m in _HALF.finditer(sentence):
        found.append((_month_index(int(m.group(2)), 6 if m.group(1).lower() == "first" else 12), m.group(0)))
    if (m := _LATE_OR_WHOLE.search(sentence)):
        found.append((end - 2, f"{m.group(0)}, to {_label(end)}"))
    return max(found) if found else None


def citation_date_problems(text: str, sources: list[dict], period_end: date) -> list[str]:
    """ Sentences that describe a month after the date of their newest cited source """
    dated = {s["number"]: date.fromisoformat(s["date"]) for s in sources if s.get("date")}
    problems = []
    for i, sentence in enumerate(_SENTENCES.split(text.strip()), start=1):
        cited = [dated[int(n)] for n in _CITATION.findall(sentence) if int(n) in dated]
        described = described_month(sentence, period_end)
        if not cited or described is None:
            continue
        newest = max(cited)
        if described[0] > _month_index(newest.year, newest.month):
            problems.append(f"quality (sources_cited): sentence {i} describes '{described[1]}', after its newest "
                            f"cited source, dated {newest.isoformat()}; describe only what the cited source's date "
                            "and content cover")
    return problems
