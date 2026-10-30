""" Reporting Agents and the Judge Agent: drafts from different angles, code's checks, the checklist, code's pick,
one send-back, and code's conclusion as the fallback """
import asyncio
from fund_performance.agents.judge import AI_DRAFTS_FAILED, MAX_SCORE, draft_and_judge
from fund_performance.agents.reporter import draft_problems, verdict_sentence
from conftest import FakeRun, FakeRunBy
from test_conclusion import facts as base_facts

ENDING = "Suggested verdict: Satisfied, no action needed."


def facts():
    data = base_facts()
    data["suggested_conclusion"] = {"text": "x. " + ENDING, "code_text": "x. " + ENDING}
    return data


GOOD = {"board": "The evidence suggests the fund did what it promised: it tracked its index closely and its fee is "
                 "competitive. " + ENDING,
        "analyst": "The evidence suggests the fund tracked its index, 0.10% a year behind it over 5 years, mostly "
                   "because of its 0.06% yearly fee. " + ENDING,
        "manager_meeting": "The evidence suggests the fund delivered; ask about transaction costs. " + ENDING}


def reporter(texts):
    return FakeRunBy(lambda prompt: {"text": next(t for a, t in texts.items() if f"Angle: {_brief(a)}" in prompt)})


def _brief(angle):
    from fund_performance.agents.reporter import ANGLE_BRIEFS
    return ANGLE_BRIEFS[angle]


def judged(changes=None, preferred=2):
    """ The Judge's answer for 3 drafts; `changes` maps a draft number to the items it changes """
    def item(i):
        return {"draft": i, "key_points_covered": True, "conclusion_clear": True, "plain_english": True,
                "no_rating_change": True, "supported_by_facts": True, "issues": []} | (changes or {}).get(i, {})
    return {"drafts": [item(i) for i in (1, 2, 3)], "preferred": preferred}


def test_the_verdict_sentence_comes_from_code():
    assert verdict_sentence(facts()) == ENDING


def test_code_checks_figures_verdict_and_style():
    assert draft_problems(GOOD["analyst"], facts()) == []
    bad = draft_problems("The fund was 0.42% a year behind its index, 0.10 behind -0.1 more. Fine.", facts())
    assert any("0.42%" in p for p in bad) and any(p.startswith("verdict: end with") for p in bad)
    assert any("minus sign" in p for p in bad)


def test_three_drafts_the_judge_checks_and_code_picks():
    result = asyncio.run(draft_and_judge(facts(), ["board", "analyst", "manager_meeting"], ["Fees"],
                                         reporter(GOOD), FakeRun(judged(preferred=2))))
    assert result.chosen.draft.angle == "analyst" and result.chosen.score == MAX_SCORE    # tie: the Judge's choice
    assert [s.draft.angle for s in result.scored] == ["board", "analyst", "manager_meeting"] and not result.flags


def test_a_failed_checklist_item_loses_even_if_the_judge_prefers_it():
    result = asyncio.run(draft_and_judge(facts(), ["board", "analyst", "manager_meeting"], ["Fees"], reporter(GOOD),
                                         FakeRun(judged({2: {"plain_english": False, "issues": ["long"]}}))))
    assert result.chosen.draft.angle == "board"
    assert next(s for s in result.scored if s.draft.angle == "analyst").issues == ["judge: long"]


def test_a_draft_with_a_wrong_figure_is_not_sent_to_the_judge():
    texts = GOOD | {"board": "The fund was 0.42% a year behind its index. " + ENDING}
    judge = FakeRun({"drafts": [{"draft": 1, "key_points_covered": True, "conclusion_clear": True,
                                 "plain_english": True, "no_rating_change": True, "supported_by_facts": True,
                                 "issues": []}, {"draft": 2, "key_points_covered": True, "conclusion_clear": True,
                                                 "plain_english": True, "no_rating_change": True,
                                                 "supported_by_facts": True, "issues": []}], "preferred": 1})
    result = asyncio.run(draft_and_judge(facts(), ["board", "analyst", "manager_meeting"], ["Fees"], reporter(texts),
                                         judge))
    board = next(s for s in result.scored if s.draft.angle == "board")
    assert board.checks == {"figures_match": False} and "Draft 1" not in judge.prompts[0].split("Drafts:")[0]
    assert '"reader": "board"' not in judge.prompts[0] and result.chosen.draft.angle == "analyst"


def test_none_passes_so_the_drafts_go_back_once_then_code_text_is_used():
    bad = {a: "Not good. " + ENDING for a in GOOD}
    rewrites = {"n": 0}

    def run(prompt):
        rewrites["n"] += "Fix every issue" in prompt
        return {"text": bad["board"]}
    fail_all = judged({i: {"conclusion_clear": False, "issues": ["unclear"]} for i in (1, 2, 3)}, None)
    result = asyncio.run(draft_and_judge(facts(), ["board", "analyst", "manager_meeting"], ["Fees"], FakeRunBy(run),
                                         FakeRun(fail_all, fail_all), max_rewrites=1))
    assert rewrites["n"] == 3 and result.chosen is None
    assert result.flags[0].message.startswith(AI_DRAFTS_FAILED) and "conclusion clear" in result.flags[0].message
    assert all(s.draft.rewritten for s in result.scored)


def test_an_unreachable_judge_means_code_text_with_a_flag():
    from agents.exceptions import AgentsException
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), FakeRun(AgentsException("x"))))
    assert result.chosen is None and "AI drafts not judged" in result.flags[0].message
