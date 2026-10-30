""" Page 1's suggested conclusion, points for the analyst's judgement and questions for the manager (B4 to B6)

All written by code from templates, filled from the facts (the scorecard, data notes, flags, peers and the
dashboard's statistics). No AI writes or rewords them in v1. The conclusion goes through the same number, label
and rating checks as AI text; a sentence that fails is left out (the verdict sentence always stays).
"""
from fund_performance.number_guard import check_labels, check_numbers, check_ratings
from fund_performance.plain import VERDICT_NAMES, verdict_meaning

MAX_POINTS = 4
MIN_QUESTIONS, MAX_QUESTIONS = 2, 4
HEADING = "Suggested conclusion (draft for the analyst)"
SHORT = {"Mandate": "the mandate", "Performance": "performance against the index",
         "Value for investors": "value for investors", "Fees": "the fee"}


def _pillars(facts: dict) -> dict:
    return {p["name"]: p for p in facts["scorecard"]["pillars"]}


def _figure(facts: dict, name: str) -> dict | None:
    return next((f for f in facts.get("figures", []) if f["name"] == name), None)


def _note(facts: dict, kind: str) -> dict | None:
    return next((n for n in facts.get("data_notes", []) if n.get("kind") == kind), None)


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# --- The suggested conclusion (B4) ------------------------------------------------------------------------------

def _aim(fund: dict) -> str:
    benchmark = fund.get("benchmark_name") or "its benchmark"
    return {"index_tracker": f"It aims to track the {benchmark}",
            "active_target": f"It aims to beat the {benchmark}",
            "active_comparator": f"It aims to do better than similar funds (compared with the {benchmark})",
            "active_constraint": f"It aims to beat the {benchmark} within its limits",
            "income_target": "It aims to pay its target income",
            "absolute_return": "It aims to deliver a positive return whatever the market does",
            }.get(fund.get("objective_type"), f"It aims to meet its objective ({benchmark})")


def _result(facts: dict) -> str | None:
    """ Whether it did it: the main figure over the main period """
    fund = facts["fund"]
    n = fund.get("time_horizon_years", 5)
    if fund.get("objective_type") == "index_tracker":
        td = _figure(facts, f"comparison.td.{n}y")
        if td is None:
            return None
        fee = _note(facts, "fee")
        unit = "%" if fee else " pp"                      # the fee note states the gap in % a year too
        value = td["value"]
        if abs(value) < 0.005:
            return f"over {n} years it was in line with its index"
        if value > 0:
            return f"over {n} years it was {value:.2f}{unit} a year ahead of its index"
        text = f"over {n} years it was {abs(value):.2f}{unit} a year behind its index"
        if fee:
            how = "mostly explained" if fee["note"].startswith("Most") else "only partly explained"
            text += f", {how} by its {fund['ocf_pct']:.2f}% yearly fee"
        return text
    fund_ann, index_ann = _figure(facts, f"fund_nav.ann.{n}y"), _figure(facts, f"index.ann.{n}y")
    if fund_ann is None or index_ann is None:
        return None
    gap = round(fund_ann["value"] - index_ann["value"], 2)
    side = "more" if gap >= 0 else "less"
    return f"over {n} years it returned {abs(gap):.2f} pp a year {side} than its benchmark"


def _peers(facts: dict) -> str:
    pillars = _pillars(facts)
    value, fees = pillars.get("Value for investors", {}), pillars.get("Fees", {})
    index_fund = facts["fund"].get("objective_type") == "index_tracker"
    count = (value.get("values") or {}).get("count", 1)
    other = ("a comparable tracker" if count == 1 else "comparable trackers") if index_fund else \
        ("a comparable fund" if count == 1 else "comparable funds")
    gap = (value.get("values") or {}).get("gap_pp")
    if value.get("summary") == "Add peer":
        part1 = "There was no comparable fund with returns to compare against"
    elif value.get("rating") == "CHECK DATA" or gap is None:
        part1 = "Its returns could not be compared reliably with similar funds"
    elif value["rating"] == "GREEN":
        green = next((lim["green"] for lim in value["values"].get("limits", [])), 0.10)
        part1 = f"Its returns were {'ahead of' if gap < -green else 'in line with'} {other}"
    elif value["rating"] == "AMBER":
        part1 = f"Its returns were slightly behind {other}"
    else:
        part1 = f"Its returns were behind {other}"
    part2 = {"GREEN": "its fee is competitive with similar funds",
             "AMBER": "its fee is somewhat higher than similar funds'",
             "RED": "its fee is high compared with similar funds'"}.get(
        fees.get("rating"), "its fee could not be compared with similar funds")
    if fees.get("summary") == "Add peer":
        part2 = "its fee could not be compared with similar funds"
    return f"{part1}, and {part2}."


def _verdict_sentence(facts: dict) -> str:
    card = facts["scorecard"]
    code = card["verdict"]
    pillars = _pillars(facts)
    name = next(n for key, (n, _) in VERDICT_NAMES.items() if code.startswith(key))
    meaning = verdict_meaning(code).lower()
    if code.startswith("Review"):
        red = [SHORT[n] for n, p in pillars.items() if p["rating"] == "RED"]
        return f"Suggested verdict: {name}, {meaning} about {_join(red)}." if red else f"Suggested verdict: {name}, {meaning}."
    if code.startswith("Pending"):
        checks = [SHORT[n] for n, p in pillars.items() if p["rating"] == "CHECK DATA"]
        return f"Suggested verdict: {name}: resolve the data check on {_join(checks)} before deciding."
    if code.startswith("Monitor (data check"):
        checks = [SHORT[n] for n, p in pillars.items() if p["rating"] == "CHECK DATA"]
        return f"Suggested verdict: {name}, {meaning} until the data check on {_join(checks)} is resolved."
    if code.startswith("Monitor until"):
        return f"Suggested verdict: {name}, {meaning} until a comparable fund is added."
    if code.startswith("Monitor"):
        amber = [SHORT[n] for n, p in pillars.items() if p["rating"] == "AMBER"]
        return f"Suggested verdict: {name}, {meaning}, especially {_join(amber)}." if amber else \
            f"Suggested verdict: {name}, {meaning}."
    return f"Suggested verdict: {name}, {meaning}."


OPENINGS = {"Retain": "The evidence suggests the fund has delivered what it promised.",
            "Monitor until": "The evidence suggests the fund has done what it promised against its index, but it "
                             "could not yet be compared with similar funds.",
            "Monitor": "The evidence suggests the fund has broadly delivered what it promised, but some points need "
                       "watching.",
            "Review": "The evidence suggests the fund has not fully delivered what it promised.",
            "Pending": "The evidence is not yet complete, so the fund cannot be judged yet."}


def text_problems(text: str, facts: dict) -> list[str]:
    """ The number, label and rating checks the AI's text also goes through """
    return ([f"number: {n}" for n in check_numbers(text, facts)] + check_labels(text, facts)
            + check_ratings(text, facts["scorecard"]))


def suggested_conclusion(facts: dict) -> tuple[str, list[str]]:
    """ 3 to 4 plain sentences ending with the suggested verdict, and what was left out (a sentence that failed
    a check) """
    code = facts["scorecard"]["verdict"]
    opening = next(text for key, text in OPENINGS.items() if code.startswith(key))
    performance = _pillars(facts).get("Performance", {})
    result = _result(facts) if performance.get("rating") != "CHECK DATA" else None
    middle = [f"{_aim(facts['fund'])}, and {result}." if result else f"{_aim(facts['fund'])}."]
    if not code.startswith("Pending"):
        middle.append(_peers(facts))
    kept, dropped = [opening], []
    for sentence in middle:
        problems = text_problems(sentence, facts)
        if problems:
            dropped.append(f"'{sentence}' left out: {'; '.join(problems)}")
        else:
            kept.append(sentence)
    return " ".join(kept + [_verdict_sentence(facts)]), dropped


# --- Points for your judgement (B5) ------------------------------------------------------------------------------

def _near(limit: dict) -> str | None:
    """ "close to its Green limit" when a rated value is near the edge of its band """
    value, kind = limit["value"], limit["kind"]
    if kind == "range":
        edges = [e for pair in (limit["green"], limit["amber"]) for e in pair]
        tolerance = 0.01
    elif kind == "min":
        edges = [limit["green"], limit["amber"]]
        tolerance = 0.005
    else:
        edges = [limit["green"], limit["amber"]]
        tolerance = None
    for edge, band in zip(edges, ("Green", "Green", "Amber", "Amber") if kind == "range" else ("Green", "Amber")):
        margin = tolerance if tolerance is not None else max(0.01, 0.2 * abs(edge))
        if abs(value - edge) <= margin:
            return band
    return None


def _short(text: str, limit: int = 110) -> str:
    """ A long message cut at a word, pointing to the appendix for the rest """
    text = text.rstrip(".")
    if len(text) <= limit:
        return text + "."
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " … (full text in the appendix)."


def judgement_points(facts: dict) -> list[str]:
    """ At most 4 points the analyst should weigh, built from the flags, the limits, the peers and the statistics """
    points: list[str] = []
    for f in facts.get("data_flags", []):
        if f["level"] == "blocking":
            points.append(_short(f"Resolve this data check first: {f['message']}"))
    for p in facts["scorecard"]["pillars"]:
        for limit in (p.get("values") or {}).get("limits", []):
            band = _near(limit)
            if band:
                points.append(f"{limit['metric']} is close to its {band} limit, so a small change could move the "
                              f"{p['name']} rating.")
    for p in facts["scorecard"]["pillars"]:
        if p["rating"] == "MANUAL CHECK":
            points.append(_short(f"{p['name']} needs your check: {p['reason']}"))
    for row in facts.get("peers", []):
        if row.get("excluded", "").startswith("returns in"):
            points.append(f"{row['name']}'s returns are in {row['currency']}, so only its fee is compared.")
        if row.get("investor_type") == "institutional":
            minimum = f" (minimum {row['minimum_investment']})" if row.get("minimum_investment") else ""
            points.append(f"{row['name']} is an institutional share class{minimum}: its fee is lower than retail "
                          "investors could get.")
    test = (facts.get("evidence") or {}).get("test")
    if test and test.get("significant") and facts["fund"].get("objective_type") == "index_tracker":
        points.append("The gap to the index after the fee is statistically significant: it is unlikely to be chance.")
    elif test and test.get("result", "").startswith("Not reliable"):
        points.append("The yearly figures are rounded and few, so the significance test is not reliable.")
    if any(f.get("source") == "ai_extracted" for f in facts.get("figures", [])):
        points.append("Some figures were read from the documents by AI: check them against the factsheet.")
    for f in facts.get("data_flags", []):
        if f["level"] == "warning":
            points.append(_short(f"Data warning: {f['message']}"))
    points.append("The limits used are illustrative and not yet agreed with the oversight team.")
    return list(dict.fromkeys(points))[:MAX_POINTS]


# --- Questions to ask the manager (B6) ------------------------------------------------------------------------------

def manager_questions(facts: dict) -> list[str]:
    """ 2 to 4 questions for the fund manager, built from the findings """
    pillars = _pillars(facts)
    n = facts["fund"].get("time_horizon_years", 5)
    index_fund = facts["fund"].get("objective_type") == "index_tracker"
    found: list[str] = []
    perf = pillars.get("Performance", {}).get("rating")
    if perf in ("RED", "AMBER"):
        found.append(f"What caused the gap to the {'index' if index_fund else 'benchmark'} over {n} years, and what "
                     "is being done about it?")
    fees = pillars.get("Fees", {})
    if fees.get("summary") == "Add peer":
        # No valid peer comparison: never claim the fee is higher; ask for the peers that would settle it
        found.append("Which comparable funds (same index, currency and share class type) do you consider the fund's "
                     "peers, and can you share their factsheets so fees and returns can be compared?")
    elif fees.get("rating") in ("RED", "AMBER"):
        found.append("Why is the fee higher than comparable funds', and is a cheaper share class available?")
    if pillars.get("Value for investors", {}).get("rating") in ("RED", "AMBER") and \
            pillars["Value for investors"].get("summary") != "Add peer":
        found.append(f"Why did the fund return less than comparable funds over {n} years?")
    fee = _note(facts, "fee")
    if fee and not fee["note"].startswith("Most"):
        found.append("What explains the part of the yearly gap to the index that the fee does not?")
    test = (facts.get("evidence") or {}).get("test")
    if index_fund and test and test.get("significant"):
        found.append("The gap after the fee is statistically significant: what are its main causes (for example tax "
                     "on dividends, cash held or sampling)?")
    if _note(facts, "timing"):
        found.append("Can you publish market-close (PNAV) returns, so the gap to the index can be measured fairly?")
    if facts["fund"].get("transaction_cost_pct", 0) is None:
        found.append("What were the fund's transaction costs over the last year?")
    if any(f["check"].startswith("repeated") for f in facts.get("data_flags", [])):
        found.append("Can you confirm the prices on the dates flagged in the data checks?")
    found += ["How are savings from the fund's size passed on to investors?",
              "Are any changes planned to the fee or to the share classes offered?"]
    found = list(dict.fromkeys(found))
    return found[:max(MIN_QUESTIONS, min(MAX_QUESTIONS, len(found)))]
