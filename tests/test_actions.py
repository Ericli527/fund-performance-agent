""" Candidate actions (code): built from the ratings and flags; the Analyst may only choose from and reword them """
import asyncio
import pytest
from fund_performance.actions import action_problems, candidate_actions, default_actions
from fund_performance.agents.analyst import problems, template, write_narrative
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
    assert len(default_actions(candidate_actions(facts), 2, 3)) == 3          # 3 required: all chosen


@pytest.mark.parametrize("chosen, problem", [
    ([("add_peer", "Add a comparable peer fund before the next quarterly review."),
      ("check_pricing", "Check this review uses market-close prices before signing off this review.")],
     "candidate 'check_pricing', which is not in the candidate actions"),
    ([("add_peer", "Add a comparable peer fund before the next quarterly review."),
      ("read_sources", "Check this review uses market-close PNAV for its sources before signing off this review.")],
     "adds 'PNAV, market-close'"),
    ([("record_decision", "Record the decision at this review."),
      ("read_sources", "Read the sources before signing off this review.")],
     "required candidate actions left out: add_peer"),
    ([("add_peer", "Add a comparable fund before the next quarterly review."),
      ("record_decision", "Record the decision at this review.")], "leaves out 'peer'"),
    ([("add_peer", "Add a comparable peer fund soon."),
      ("record_decision", "Record the decision at this review.")],
     "must keep its timing word for word: 'before the next quarterly review'"),
    ([("add_peer", "Add a peer before the next quarterly review."),
      ("add_peer", "Add a peer fund before the next quarterly review.")], "the same candidate is chosen twice"),
])
def test_action_problems(chosen, problem):
    found = action_problems(chosen, candidate_actions(NO_PEER), 3)
    assert len(found) == 1 and problem in found[0], found


def test_a_reworded_candidate_passes():
    chosen = [("add_peer", "Add a comparable peer fund before the next quarterly review, so value and fees can be judged."),
              ("record_decision", "Record the decision and its reasons in the approval box at this review.")]
    assert action_problems(chosen, candidate_actions(NO_PEER), 3) == []


def test_a_new_action_triggers_the_rewrite_then_the_template():
    new = {"key_findings": ["a", "b", "c"], "market_context": None,
           "actions": [{"candidate": "add_peer", "text": "Add a peer fund before the next quarterly review."},
                       {"candidate": "check_periods", "text": "Check the periods used before signing off this review."}]}
    result = asyncio.run(write_narrative(NO_PEER, run=FakeRun(new, new)))
    assert result.source == "template" and "wording" in result.flags[0].message
    assert [a.candidate for a in result.output.actions] == ["add_peer", "record_decision"]
    assert problems(template(NO_PEER), NO_PEER) == []


@requires_test1
def test_test1_facts_carry_the_candidate_actions():
    from test_agent_analyst import _test1_facts
    facts = _test1_facts()
    assert [c["id"] for c in facts["candidate_actions"]] == ["add_peer", "record_decision", "read_sources"]


def test_each_candidate_has_its_own_fixed_timing():
    cands = {c["id"]: c for c in candidate_actions(NO_PEER)}
    assert cands["add_peer"]["when"] == "before the next quarterly review"
    assert cands["record_decision"]["when"] == "at this review"
    assert cands["read_sources"]["when"] == "before signing off this review"
    assert all(c["when"] in c["action"] for c in cands.values())


def test_another_candidates_timing_is_rejected_with_the_candidates_own_timing_as_the_hint():
    """ From the full run: a generic hint ('before signing off this review') conflicted with add_peer's timing """
    chosen = [("add_peer", "Add a comparable peer fund before signing off this review."),
              ("record_decision", "Record the decision at this review.")]
    found = action_problems(chosen, candidate_actions(NO_PEER), 3)
    assert found == ["action: action 1 (add_peer) must keep its timing word for word: 'before the next quarterly review'"]
    assert "before signing off" not in found[0]
