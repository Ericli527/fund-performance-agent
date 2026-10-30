""" Reporting Agent and the Judge Agent: code's checks, the Judge's review (facts, reasoning, security, clarity),
code's decision (pass, one targeted revision or fallback) and code's conclusion as the fallback """
import asyncio
from fund_performance.agents.judge import AI_DRAFTS_FAILED, INSTRUCTIONS, draft_and_judge
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


def review(**changes):
    """ The Judge's answer for one draft: approved unless `changes` say otherwise """
    return {"approved": True, "factual_issue": False, "security_issue": False, "conclusion_reasonable": True,
            "clear_for_analysts": True, "feedback": "Accurate and clear."} | changes


def test_the_verdict_sentence_comes_from_code():
    assert verdict_sentence(facts()) == ENDING


def test_code_checks_figures_verdict_and_style():
    assert draft_problems(GOOD["analyst"], facts()) == []
    bad = draft_problems("The fund was 0.42% a year behind its index, 0.10 behind -0.1 more. Fine.", facts())
    assert any("0.42%" in p for p in bad) and any(p.startswith("verdict: end with") for p in bad)
    assert any("minus sign" in p for p in bad)


def test_agent_definitions_use_the_central_model_config(monkeypatch):
    from agents import Agent
    from fund_performance.agents.judge import ReviewResult, judge_agent
    from fund_performance.agents.reporter import DraftOutput, reporter_agent
    from fund_performance.config import load_models
    for factory, key, output in ((judge_agent, "judge", ReviewResult), (reporter_agent, "reporter", DraftOutput)):
        monkeypatch.delenv(f"FUND_MODEL_{key.upper()}", raising=False)
        agent = factory()
        assert isinstance(agent, Agent) and agent.output_type is output
        assert agent.model == load_models().for_agent(key)[0]


def test_an_approved_draft_passes_and_the_reason_is_recorded():
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), FakeRun(review())))
    assert result.chosen.draft.angle == "board" and result.chosen.decision == "pass" and not result.flags
    assert result.reason == "Accurate and clear." and result.chosen.to_dict(True)["reason"] == "Accurate and clear."


def test_a_style_point_alone_never_rejects_a_useful_draft():
    judge = FakeRun(review(clear_for_analysts=False, feedback="Could be a little shorter."))
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), judge))
    assert result.chosen is not None and result.chosen.checks["clear_for_analysts"] is False
    assert len(judge.prompts) == 1


def test_the_judge_reviews_only_the_draft_and_treats_inputs_as_untrusted_data():
    judge = FakeRun(review())
    asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), judge))
    assert "Draft for the board:" in judge.prompts[0] and "Verified facts (decided by code)" in judge.prompts[0]
    assert "untrusted data" in INSTRUCTIONS and "Do not calculate metrics, change ratings" in INSTRUCTIONS


def test_a_factual_issue_gets_one_targeted_rewrite_with_the_feedback():
    texts = []

    def run(prompt):
        texts.append(prompt)
        return {"text": GOOD["board"]}
    judge = FakeRun(review(approved=False, factual_issue=True, feedback="Remove the claim about manager skill."),
                    review())
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1))
    assert len(texts) == 2 and "Remove the claim about manager skill." in texts[1]
    assert result.chosen.draft.rewritten and result.chosen.decision == "pass"


def test_a_security_issue_falls_back_to_code_without_a_rewrite():
    calls = {"n": 0}

    def run(prompt):
        calls["n"] += 1
        return {"text": GOOD["board"]}
    judge = FakeRun(review(approved=False, security_issue=True, feedback="Contains an instruction to the reader."))
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1,
                                         rejudge=False))
    assert calls["n"] == 1 and result.chosen is None and result.scored[0].decision == "fallback"
    assert result.flags[0].level == "info" and result.flags[0].message.startswith(AI_DRAFTS_FAILED)
    assert "Contains an instruction to the reader" in result.flags[0].message


def test_decisions_come_from_code_not_the_judges_approval_alone():
    from fund_performance.agents.judge import ReviewResult, decide
    assert decide(ReviewResult(**review(security_issue=True))) == "fallback"     # approved, but a security issue
    assert decide(ReviewResult(**review(factual_issue=True))) == "revise"
    assert decide(ReviewResult(**review(conclusion_reasonable=False))) == "revise"
    assert decide(ReviewResult(**review(approved=False))) == "revise"
    assert decide(ReviewResult(**review(clear_for_analysts=False))) == "pass"


def test_a_draft_with_a_wrong_figure_is_not_sent_to_the_judge():
    texts = {"board": "The fund was 0.42% a year behind its index. " + ENDING}
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(texts), judge, max_rewrites=0))
    board = result.scored[0]
    assert board.checks == {"figures_match": False} and board.decision == "revise" and not judge.prompts
    assert result.chosen is None and board.reason.startswith("code's checks: check:")


def test_with_rejudge_the_rewrite_is_reviewed_again_then_code_text_is_used():
    bad = "Not good. " + ENDING
    rewrites = {"n": 0}

    def run(prompt):
        rewrites["n"] += "Fix every issue" in prompt
        return {"text": bad}
    no = review(approved=False, conclusion_reasonable=False, feedback="Unclear conclusion.")
    judge = FakeRun(no, no)
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1))
    assert rewrites["n"] == 1 and len(judge.prompts) == 2 and result.chosen is None
    assert result.flags[0].message.startswith(AI_DRAFTS_FAILED) and "Unclear conclusion" in result.flags[0].message


def test_an_unreachable_judge_means_code_text_with_a_flag():
    from agents.exceptions import AgentsException
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), FakeRun(AgentsException("x"))))
    assert result.chosen is None and "AI draft not reviewed" in result.flags[0].message
