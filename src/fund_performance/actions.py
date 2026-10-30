""" Actions (code, not AI): built from the ratings and the data flags, and used in the report exactly as written
here. No AI agent writes or rewords an action.

Each candidate has an id, its wording, its own fixed timing ("when", part of the wording), and whether it is
required (a required action is always used while there is room for it).
"""
import re

SIGN_OFF = "before signing off this review"
NEXT_REVIEW = "before the next quarterly review"
AT_NEXT_REVIEW = "at the next quarterly review"
THIS_REVIEW = "at this review"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z]+", "_", name.lower()).strip("_")


def _action(id_: str, text: str, when: str, required: bool) -> dict:
    # Periods in words, as in all report text ("5y" -> "5 years")
    text = re.sub(r"\b(\d+)y\b", lambda m: f"{m.group(1)} year{'s' if m.group(1) != '1' else ''}", text)
    assert when in text, f"candidate {id_}: its wording must contain its timing"
    return {"id": id_, "action": text, "when": when, "required": required}


def candidate_actions(facts: dict) -> list[dict]:
    """ In priority order: data checks, Red ratings, manual checks, adding a peer, Amber ratings, data warnings,
    then two general actions so there are always at least two """
    pillars = facts.get("scorecard", {}).get("pillars", [])
    found: list[dict] = []
    for p in pillars:
        if p["rating"] == "CHECK DATA":
            found.append(_action(f"check_data_{_slug(p['name'])}",
                                 f"Resolve the data check on {p['name']} {SIGN_OFF}: {p['reason']}.",
                                 SIGN_OFF, True))
    for p in pillars:
        if p["rating"] == "RED":
            found.append(_action(f"red_{_slug(p['name'])}",
                                 f"Discuss the Red {p['name']} rating with the fund manager {NEXT_REVIEW}: {p['reason']}.",
                                 NEXT_REVIEW, True))
    for p in pillars:
        if p["rating"] == "MANUAL CHECK":
            found.append(_action(f"manual_check_{_slug(p['name'])}",
                                 f"Check the fund's style and holdings against its stated policy {SIGN_OFF}.",
                                 SIGN_OFF, True))
    if any(p.get("summary") == "Add peer" for p in pillars):
        found.append(_action("add_peer", "Add a comparable peer fund (name, ongoing charge and 1, 3 and 5-year returns) "
                                         f"{NEXT_REVIEW}, so value for investors and fees can be judged.",
                             NEXT_REVIEW, True))
    for p in pillars:
        if p["rating"] == "AMBER" and p.get("summary") != "Add peer":
            found.append(_action(f"amber_{_slug(p['name'])}",
                                 f"Recheck {p['name']} {AT_NEXT_REVIEW}: {p['reason']}.",
                                 AT_NEXT_REVIEW, False))
    for i, f in enumerate(x for x in facts.get("data_flags", []) if x.get("level") == "warning"):
        found.append(_action(f"warning_{i + 1}", f"Check this data warning {SIGN_OFF}: {f['message'].rstrip('.')}.",
                             SIGN_OFF, False))
    found.append(_action("record_decision", f"Record the decision and its reasons in the approval box {THIS_REVIEW}.",
                         THIS_REVIEW, False))
    found.append(_action("read_sources", f"Read the evidence and its sources on pages 2 to 4 {SIGN_OFF}.",
                         SIGN_OFF, False))
    return found


def default_actions(candidates: list[dict], min_actions: int, max_actions: int) -> list[tuple[str, str]]:
    """ The report's actions: required ones first, then the rest in priority order, 2 to 3 of them """
    ordered = [c for c in candidates if c["required"]] + [c for c in candidates if not c["required"]]
    count = max(min_actions, min(max_actions, sum(c["required"] for c in candidates)))
    return [(c["id"], c["action"]) for c in ordered[:count]]
