""" Candidate actions (code, not AI): built from the ratings and the data flags. The Oversight Analyst may only
choose from these and reword them; it may not add an action (e.g. about the report's method or periods).

Each candidate has an id, a default wording that says what to do and when, the words a rewording must keep,
and whether it is required (a required action must be chosen while there is room for it). The template
narrative uses the default wording.
"""
import re

WHEN = re.compile(r"\bbefore (signing off|the next)|\bat (this|the next) (quarterly )?review\b|\bwithin \w+ (days|weeks)\b",
                  re.IGNORECASE)
# Words about the report's method or periods: an action may use them only if its candidate does
METHOD_WORDS = re.compile(r"\b(PNAV|NAV|noon|market[- ]close|pricing|method(ology)?|basis|periods?|calculat\w*)\b",
                          re.IGNORECASE)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z]+", "_", name.lower()).strip("_")


def _action(id_: str, text: str, keep: list[str], required: bool) -> dict:
    # Periods in words, as in all report text ("5y" -> "5 years")
    text = re.sub(r"\b(\d+)y\b", lambda m: f"{m.group(1)} year{'s' if m.group(1) != '1' else ''}", text)
    return {"id": id_, "action": text, "keep_words": keep, "required": required}


def candidate_actions(facts: dict) -> list[dict]:
    """ In priority order: data checks, Red ratings, manual checks, adding a peer, Amber ratings, data warnings,
    then two general actions so there are always at least two to choose from """
    pillars = facts.get("scorecard", {}).get("pillars", [])
    found: list[dict] = []
    for p in pillars:
        if p["rating"] == "CHECK DATA":
            found.append(_action(f"check_data_{_slug(p['name'])}",
                                 f"Resolve the data check on {p['name']} before signing off this review: {p['reason']}.",
                                 [p["name"].split()[0].lower()], True))
    for p in pillars:
        if p["rating"] == "RED":
            found.append(_action(f"red_{_slug(p['name'])}",
                                 f"Discuss the Red {p['name']} rating with the fund manager before the next quarterly "
                                 f"review: {p['reason']}.", [p["name"].split()[0].lower(), "manager"], True))
    for p in pillars:
        if p["rating"] == "MANUAL CHECK":
            found.append(_action(f"manual_check_{_slug(p['name'])}",
                                 "Check the fund's style and holdings against its stated policy before signing off "
                                 "this review.", ["holdings"], True))
    if any(p.get("summary") == "Add peer" for p in pillars):
        found.append(_action("add_peer", "Add a comparable peer fund (name, ongoing charge and 1, 3 and 5-year returns) "
                                         "before the next quarterly review, so value for investors and fees can be judged.",
                             ["peer"], True))
    for p in pillars:
        if p["rating"] == "AMBER" and p.get("summary") != "Add peer":
            found.append(_action(f"amber_{_slug(p['name'])}",
                                 f"Recheck {p['name']} at the next quarterly review: {p['reason']}.",
                                 [p["name"].split()[0].lower()], False))
    for i, f in enumerate(x for x in facts.get("data_flags", []) if x.get("level") == "warning"):
        found.append(_action(f"warning_{i + 1}", f"Check this data warning before signing off this review: "
                                                 f"{f['message'].rstrip('.')}.", [], False))
    found.append(_action("record_decision", "Record the decision and its reasons in the approval box at this review.",
                         ["record"], False))
    found.append(_action("read_sources", "Read the figures and their sources on pages 2 and 3 before signing off "
                                         "this review.", ["sources"], False))
    return found


def action_problems(chosen: list[tuple[str, str]], candidates: list[dict], max_actions: int) -> list[str]:
    """ Code checks on the Analyst's actions, given as (candidate id, reworded text) """
    by_id = {c["id"]: c for c in candidates}
    found = []
    ids = [i for i, _ in chosen]
    for n, (id_, text) in enumerate(chosen, start=1):
        cand = by_id.get(id_)
        if cand is None:
            found.append(f"action: action {n} has candidate '{id_}', which is not in the candidate actions; "
                         "choose from the list only")
            continue
        missing = [w for w in cand["keep_words"] if w.lower() not in text.lower()]
        if missing:
            found.append(f"action: action {n} ({id_}) leaves out '{', '.join(missing)}'; keep the candidate's task")
        if not WHEN.search(text):
            found.append(f"action: action {n} ({id_}) does not say when, e.g. 'before signing off this review'")
        added = {m.group(0) for m in METHOD_WORDS.finditer(text)} - {m.group(0) for m in METHOD_WORDS.finditer(cand["action"])}
        if added:
            found.append(f"action: action {n} ({id_}) adds '{', '.join(sorted(added))}': no new actions about the "
                         "report's method or periods")
    if len(set(ids)) < len(ids):
        found.append("action: the same candidate is chosen twice")
    required = [c["id"] for c in candidates if c["required"]][:max_actions]
    left_out = [r for r in required if r not in ids]
    if left_out:
        found.append(f"action: required candidate actions left out: {', '.join(left_out)}")
    return found


def default_actions(candidates: list[dict], min_actions: int, max_actions: int) -> list[tuple[str, str]]:
    """ The template's actions: required ones first, then the rest in priority order """
    ordered = [c for c in candidates if c["required"]] + [c for c in candidates if not c["required"]]
    count = max(min_actions, min(max_actions, sum(c["required"] for c in candidates)))
    return [(c["id"], c["action"]) for c in ordered[:count]]
