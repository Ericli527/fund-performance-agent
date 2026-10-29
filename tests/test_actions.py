""" Actions (code): built from the ratings and flags, used in the report exactly as written; no AI writes them """
import asyncio
from fund_performance.actions import candidate_actions, default_actions
from fund_performance.agents.analyst import AnalystDraft, code_actions, write_narrative
from conftest import FakeRun, requires_test1


def facts_with(*pillars, flags=()):
    return {"scorecard": {"verdict": "x", "verdict_reason": "x",
                          "pillars": [{"name": n, "rating": r, "reason": why, "summary": summary}
                                      for n, r, why, summary in pillars]},
            "data_flags": list(flags), "figures": []}


NO_PEER = facts_with(("Mandate", "GREEN", "R² 1.00", None), ("Performance", "GREEN", "TD -0.10 pp (5y)", None),
                     ("Value for investors", "AMBER", "no comparison available", "Add peer"),
                     ("Fees", "AMBER", "no comparison available", "Add peer"))


def ids(facts):
    return [c["id"] for c in candidate_actions(facts)]


def test_test1_shape_gives_add_peer_as_the_only_required_action():
    cands = candidate_actions(NO_PEER)
    assert [c["id"] for c in cands] == ["add_peer", "record_decision", "read_sources"]
    assert [c["required"] for c in cands] == [True, False, False]
    assert default_actions(cands, 2, 3) == [("add_peer", cands[0]["action"]), ("record_decision", cands[1]["action"])]


def test_candidates_follow_the_ratings_and_flags_in_priority_order():
    facts = facts_with(("Mandate", "MANUAL CHECK", "Style and holdings need a reviewer check", None),
                       ("Performance", "CHECK DATA", "currency mismatch", None),
                       ("Value for investors", "RED", "peer did better by 1.20 pp a year (5y)", None),
                       ("Fees", "AMBER", "fee 0.15 pp above the peer's", None),
                       flags=[{"check": "missing_values", "level": "warning", "message": "2 index values missing"},
                              {"check": "x", "level": "info", "message": "for the record"}])
    assert ids(facts) == ["check_data_performance", "red_value_for_investors", "manual_check_mandate", "amber_fees",
                          "warning_1", "record_decision", "read_sources"]
    red = candidate_actions(facts)[1]["action"]
    assert "(5 years)" in red and "5y" not in red                             # periods in words
    assert len(default_actions(candidate_actions(facts), 2, 3)) == 3          # 3 required: all used


def test_each_candidate_has_its_own_fixed_timing():
    cands = {c["id"]: c for c in candidate_actions(NO_PEER)}
    assert cands["add_peer"]["when"] == "before the next quarterly review"
    assert cands["record_decision"]["when"] == "at this review"
    assert cands["read_sources"]["when"] == "before signing off this review"
    assert all(c["when"] in c["action"] for c in cands.values())


def test_the_ai_never_writes_actions():
    """ The AI's output has no actions field; the report's actions are code's, word for word """
    assert "actions" not in AnalystDraft.model_fields
    draft = {"findings": ["Value and fees need a peer fund.", "The figures are on pages 2 and 3."],
             "market_context": None}
    result = asyncio.run(write_narrative(NO_PEER, run=FakeRun(draft)))
    assert result.source == "ai"
    assert result.output.action_texts == [c["action"] for c in candidate_actions(NO_PEER)[:2]]
    assert [a.candidate for a in result.output.actions] == [a.candidate for a in code_actions(NO_PEER)]


@requires_test1
def test_test1_facts_carry_the_candidate_actions():
    from test_agent_analyst import _test1_facts
    facts = _test1_facts()
    assert [c["id"] for c in facts["candidate_actions"]] == ["add_peer", "record_decision", "read_sources"]
