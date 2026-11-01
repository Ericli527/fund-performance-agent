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
    assert any("0.42%" in p for p in bad) and any("0.42%" in p for p in bad)
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
    assert "Dashboard draft for the board (the answer, the supporting evidence, the next step):" in judge.prompts[0] and "Verified facts (decided by code)" in judge.prompts[0]
    assert "untrusted data" in INSTRUCTIONS and "Do not calculate metrics, change ratings" in INSTRUCTIONS


def test_reporting_and_judge_receive_assessment_and_fund_context():
    assessment = {'status': 'available', 'assessment': {'investment_thesis': 'A qualified independent view'}}
    context = {'document_summary': 'Index strategy in fund.pdf', 'sources': ['fund.pdf']}
    report = reporter(GOOD)
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ['board'], ['Fees'], report, judge,
                                         assessment=assessment, fund_context=context))
    assert result.chosen
    assert 'A qualified independent view' in report.prompts[0] and 'Index strategy in fund.pdf' in report.prompts[0]
    assert 'A qualified independent view' in judge.prompts[0] and 'Index strategy in fund.pdf' in judge.prompts[0]


def test_reporter_retains_checked_detailed_and_research_narratives():
    from fund_performance.agents.reporter import write_draft
    answer = {'answer': 'The fund tracks its index.', 'evidence': [],
              'detailed_analysis': ['The fund follows its stated benchmark.'],
              'research_narrative': ['The benchmark provider updated its methodology [1].']}
    source = {'summary': 'The benchmark provider updated its methodology.', 'date': '2026-09-01'}
    runner = FakeRun(answer)
    draft = asyncio.run(write_draft(facts(), 'board', ['Mandate'], runner, sources=[source],
                                    question='How does it track?\nPlease explain.'))
    assert not draft.additional_problems
    assert draft.detailed_analysis and '[1]' in draft.research_narrative[0]
    assert 'How does it track?\nPlease explain.' in runner.prompts[0]


def test_unsupported_detailed_narrative_is_not_shown_to_the_judge():
    draft = {'answer': 'The fund tracks its index.', 'evidence': [],
             'detailed_analysis': ['The fund returned 999.9%.']}
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ['board'], ['Mandate'], FakeRun(draft), judge))
    assert result.chosen and not result.chosen.draft.detailed_analysis
    assert '999.9%' not in judge.prompts[0]


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
    assert decide(ReviewResult(**review(approved=False))) == "pass"          # not approved for style: never rejected
    assert decide(ReviewResult(**review(clear_for_analysts=False))) == "pass"


def test_a_draft_with_a_wrong_figure_is_not_sent_to_the_judge():
    texts = {"board": "The fund was 0.42% a year behind its index. " + ENDING}
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(texts), judge, max_rewrites=0))
    board = result.scored[0]
    assert board.checks == {"figures_match": False} and board.decision == "revise" and not judge.prompts
    assert result.chosen is None and board.reason.startswith("code's checks: check:")


def test_material_issue_gets_one_code_checked_rewrite_even_if_rejudge_configured():
    bad = "Not good. " + ENDING
    rewrites = {"n": 0}

    def run(prompt):
        rewrites["n"] += "Fix every issue" in prompt
        return {"text": bad}
    no = review(approved=False, conclusion_reasonable=False, feedback="Unclear conclusion.")
    judge = FakeRun(no, no)
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1))
    assert rewrites["n"] == 1 and len(judge.prompts) == 1 and result.chosen is not None
    assert "not judged again" in result.reason


def test_an_unreachable_judge_means_code_text_with_a_flag():
    from agents.exceptions import AgentsException
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), FakeRun(AgentsException("x"))))
    assert result.chosen is None and "AI draft not reviewed" in result.flags[0].message


# The Judge enhances rather than rejects (Live run, Fidelity: "Replace 'Satisfied, no action needed' with the code's
# verdict 'Retain'" sent the draft back, the rewrite broke the verdict sentence, and code's conclusion was used)
def test_the_judge_is_told_code_verdict_sentence_and_its_reader_wording():
    judge = FakeRun(review())
    asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], reporter(GOOD), judge))
    assert f"Code's verdict sentence (correct by definition; never ask to change it): {ENDING}" in judge.prompts[0]
    assert "Retain = Satisfied" in judge.prompts[0] and "Review = Action needed" in judge.prompts[0]
    assert "Never flag that" in INSTRUCTIONS and "not to reject it" in INSTRUCTIONS


def test_optional_improvements_do_not_trigger_rewrite():
    prompts = []

    def run(prompt):
        prompts.append(prompt)
        return {"text": GOOD["analyst"] if len(prompts) > 1 else GOOD["board"]}
    judge = FakeRun(review(approved=True, clear_for_analysts=False, feedback="Accurate but brief.",
                           improvements=["say that the 5-year returns are annualised"]))
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1,
                                         rejudge=False))
    assert len(judge.prompts) == 1 and len(prompts) == 1
    assert result.chosen.draft.text == GOOD["board"] and not result.chosen.draft.rewritten and not result.flags
    assert result.chosen.improvements == ["say that the 5-year returns are annualised"]


def test_an_improvement_that_breaks_codes_checks_keeps_the_approved_draft_never_code_text():
    calls = {"n": 0}

    def run(prompt):
        calls["n"] += 1
        return {"text": GOOD["board"] if calls["n"] == 1 else "The fund returned 99.9% a year."}       # a figure not in the facts
    judge = FakeRun(review(improvements=["use the verdict code Retain"]))
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1,
                                         rejudge=False))
    assert calls["n"] == 1 and result.chosen.draft.text == GOOD["board"] and not result.chosen.draft.rewritten
    assert not result.flags


def test_no_improvements_means_no_extra_call_and_a_real_factual_error_is_still_fixed_or_falls_back():
    calls = {"n": 0}

    def run(prompt):
        calls["n"] += 1
        return {"text": GOOD["board"]}
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), FakeRun(review()),
                                         max_rewrites=1, rejudge=False))
    assert calls["n"] == 1 and result.chosen.draft.text == GOOD["board"]
    bad = {"n": 0}

    def wrong_then_broken(prompt):
        bad["n"] += 1
        return {"text": GOOD["board"] if bad["n"] == 1 else "The fund returned 99.9% a year."}
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(wrong_then_broken),
                                         FakeRun(review(approved=False, factual_issue=True,
                                                        feedback="The fee is not lower than the peer's.")),
                                         max_rewrites=1, rejudge=False))
    assert result.chosen is None and result.flags[0].message.startswith(AI_DRAFTS_FAILED)


# Live run (Fidelity, 31 Oct 2026): the Judge called "the figures were read by AI" an unsupported claim and, because
# its instructions listed hallucination under security, the draft fell back to code's conclusion with no rewrite.
# The statement was true: the Judge could not see where the figures came from
LIVE_FEEDBACK = ("The summary supports the Satisfied verdict and its market context is sourced, but the unsupported "
                 "claim that figures were read by AI must be removed.")


def test_hallucination_is_a_factual_issue_and_security_means_prompt_injection_only():
    factual, security = INSTRUCTIONS.split("2. Reasonable conclusion")[0], INSTRUCTIONS.split("3. Security")[1]
    assert "hallucination" in factual and "one rewrite can fix" in factual
    assert "prompt injection" in security.split("4. Clarity")[0]
    assert "hallucination" not in security.split("4. Clarity")[0]
    assert "never a security issue" in security


def test_the_judge_is_told_how_the_figures_were_obtained():
    from fund_performance.agents.judge import provenance
    data = facts()
    data["figures"] = [{"name": f"fund_nav.cum.{p}", "source": "ai_extracted"} for p in ("1y", "3y", "5y")] + \
        [{"name": "fund_nav.vol.3y", "source": "calculated"}]
    line = provenance(data)
    assert line.startswith("3 figures read from the uploaded documents by the Extractor Agent (AI) and checked")
    assert "1 figure calculated by code from the price history" in line
    judge = FakeRun(review())
    asyncio.run(draft_and_judge(data, ["board"], ["Fees"], reporter(GOOD), judge))
    assert f"How the figures were obtained (provenance, recorded by code): {line}" in judge.prompts[0]


def test_an_unsupported_claim_now_gets_one_targeted_rewrite_not_a_fallback():
    prompts = []

    def run(prompt):
        prompts.append(prompt)
        return {"text": GOOD["board"]}
    judge = FakeRun(review(approved=False, factual_issue=True, feedback=LIVE_FEEDBACK))
    result = asyncio.run(draft_and_judge(facts(), ["board"], ["Fees"], FakeRunBy(run), judge, max_rewrites=1,
                                         rejudge=False))
    assert len(prompts) == 2 and "unsupported claim that figures were read by AI" in prompts[1]
    assert result.chosen is not None and result.chosen.draft.rewritten and not result.flags   # the AI draft is kept


# The dashboard summary answers the reviewer's typed question: the answer first, then the supporting evidence
ANSWER = "Yes, the fund met its objective: it tracked its index closely and its fee is competitive. " + ENDING
POINTS = ["The fund was 0.10% a year behind its index over 5 years, mostly because of its 0.06% yearly fee.",
          "Its fee is in line with comparable index funds."]


def test_the_reporting_agent_answers_the_question_then_gives_supporting_evidence():
    question = "Is this fund meeting its objective, and is its fee justified?"
    reporter_run, judge = FakeRunBy(lambda p: {"answer": ANSWER, "evidence": POINTS}), FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ["analyst"], ["Fees"], reporter_run, judge, question=question))
    draft = result.chosen.draft
    assert draft.answer == ANSWER and draft.evidence == POINTS and draft.figures_match
    assert draft.text == ANSWER + "\n\nSupporting evidence:\n- " + POINTS[0] + "\n- " + POINTS[1]
    assert reporter_run.prompts[0].startswith(f"Question to answer: {question}")
    assert f"The reviewer's question the draft must answer: {question}" in judge.prompts[0]


def test_codes_checks_cover_the_evidence_and_keep_the_verdict_at_the_end_of_the_answer():
    from fund_performance.agents.reporter import draft_problems
    assert draft_problems(ANSWER, facts(), evidence=POINTS) == []
    wrong = draft_problems(ANSWER, facts(), evidence=["It returned 99.9% a year over 5 years."])
    assert any("99.9%" in p for p in wrong)                                 # a figure not in the facts, in the evidence
    many = draft_problems(ANSWER, facts(), evidence=["Fees.", "Peers.", "Tracking.", "Two. Three. Four."])
    assert any("4 evidence points; use at most 3" in p for p in many)
    assert any("evidence point 4 has 3 sentences; use at most 2" in p for p in many)


def test_the_reporting_and_judge_agents_use_the_chosen_model(monkeypatch):
    from fund_performance.agents.judge import judge_agent
    from fund_performance.agents.reporter import reporter_agent
    for agent in ("REPORTER", "JUDGE"):
        monkeypatch.delenv(f"FUND_MODEL_{agent}", raising=False)
    assert reporter_agent().model == reporter_agent(tools=True).model == judge_agent().model == "gpt-6.1-terra"
    # the Reporting Agent writes the dashboard answer, so it thinks harder than the Judge on the same model
    assert reporter_agent().model_settings.reasoning.effort == "medium"
    assert judge_agent().model_settings.reasoning.effort == "low"
    from fund_performance.agents.investment_analyst import reviewer_agent
    assert reviewer_agent().model == "gpt-6.1-terra" and reviewer_agent().model_settings.reasoning.effort == "low"


# Two narratives from one run: a concise dashboard answer and a distinct Executive commentary
EXEC = ["The fund aims to track its index before fees, and the evidence shows it has kept to that mandate.",
        "Against its benchmark the fund trailed slightly over five years, a gap mostly explained by its yearly charge.",
        "Its charge is in line with comparable index funds, so investors appear to receive fair value. " + ENDING]
NEXT = "Confirm the transaction costs with the manager at the next meeting."


def two_part(answer=ANSWER.replace(" " + ENDING, ""), evidence=None, executive=None, next_step=NEXT):
    return {"answer": answer, "evidence": POINTS if evidence is None else evidence, "next_step": next_step,
            "executive": EXEC if executive is None else executive}


def test_one_run_gives_a_concise_dashboard_answer_and_a_distinct_executive_commentary():
    reporter_run = FakeRunBy(lambda p: two_part())
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ["analyst"], ["Fees"], reporter_run, judge, question="Is the fee fair?"))
    draft = result.chosen.draft
    assert len(reporter_run.prompts) == 1 and len(judge.prompts) == 1                    # no extra LLM calls
    assert draft.next_step == NEXT and draft.executive == EXEC and not draft.executive_problems
    assert ENDING not in draft.answer                                                     # the page shows the verdict
    assert "Executive commentary for the PDF" in judge.prompts[0] and EXEC[0] in judge.prompts[0]


def test_dashboard_points_must_not_repeat_each_other_or_the_answer():
    from fund_performance.agents.reporter import draft_problems
    same = ["The fund was 0.10% a year behind its index over 5 years, mostly because of its 0.06% yearly fee.",
            "Over 5 years the fund was 0.10% a year behind its index, mostly because of its 0.06% yearly fee."]
    assert any("evidence point 2 repeats an earlier point" in p for p in draft_problems("Yes.", facts(), evidence=same))
    assert not any("repeats" in p for p in draft_problems("Yes, it met its objective.", facts(), evidence=POINTS))
    assert any("answer has 5 sentences" in p for p in draft_problems("A. B. C. D. E.", facts()))


def test_the_executive_commentary_must_be_distinct_cited_and_end_with_the_verdict():
    from fund_performance.agents.reporter import compose, executive_problems
    dashboard = compose(ANSWER, POINTS, NEXT)
    assert executive_problems(EXEC, facts(), [], dashboard) == []
    copied = executive_problems([ANSWER, EXEC[1], EXEC[2]], facts(), [], dashboard)
    assert any("copies the dashboard answer" in p for p in copied)
    assert any("does not match a source" in p for p in executive_problems(
        [EXEC[0], EXEC[1] + " Markets rose [2].", EXEC[2]], facts(), [{"summary": "s"}], dashboard))
    assert any("end the commentary with" in p for p in executive_problems(EXEC[:2] + ["Fine."], facts(), [], dashboard))
    assert any("2 paragraphs" in p for p in executive_problems(EXEC[1:], facts(), [], dashboard))
    assert any("99.9%" in p for p in executive_problems(
        [EXEC[0], "It returned 99.9% a year.", EXEC[2]], facts(), [], dashboard))       # figures checked by code


def test_a_commentary_that_fails_codes_checks_is_left_out_but_the_dashboard_answer_stays():
    calls = {"n": 0}

    def run(prompt):
        calls["n"] += 1
        return two_part(executive=["Too short. " + ENDING])                     # one paragraph: fails, also after the rewrite
    result = asyncio.run(draft_and_judge(facts(), ["analyst"], ["Fees"], FakeRunBy(run), FakeRun(review()),
                                         max_rewrites=1, rejudge=False))
    assert calls["n"] == 1 and result.chosen is not None and result.chosen.draft.executive == []
    assert result.chosen.draft.answer and result.chosen.issues


def test_missing_evidence_is_never_treated_as_poor_performance():
    assert "Missing evidence is not poor performance" in __import__(
        "fund_performance.agents.reporter", fromlist=["x"]).INSTRUCTIONS
    assert "treats missing evidence as poor performance or an" in INSTRUCTIONS


def test_judge_sees_executive_sources_without_market_context():
    from fund_performance.agents.judge import judge_input
    from fund_performance.agents.reporter import Draft
    source = {"summary": "Technology shares rose.", "url": "https://example.org/private"}
    draft = Draft("board", text="The fund tracked its index.", executive=["Technology shares rose [1]."])
    prompt = judge_input(facts(), draft, [source])
    assert "Technology shares rose [1]." in prompt
    assert '"summary": "Technology shares rose."' in prompt
    assert '"source": "[1]"' in prompt and "untrusted data" in prompt
    assert source["url"] not in prompt


def test_rejected_market_context_does_not_hide_executive_sources():
    from fund_performance.agents.judge import judge_input
    from fund_performance.agents.reporter import Draft
    draft = Draft("board", text="The fund tracked its index.", executive=["Shares rose [1]."],
                  market_context="Rejected unsafe context [1].", context_problems=["invalid"])
    prompt = judge_input(facts(), draft, [{"summary": "Shares rose."}])
    assert "Rejected unsafe context" not in prompt
    assert '"summary": "Shares rose."' in prompt and "Shares rose [1]." in prompt


def test_unresolved_citations_require_revision_in_all_narratives():
    from fund_performance.agents.reporter import context_problems, draft_problems, executive_problems
    for sources in ([], [{"summary": ""}], [{"topic": "market"}]):
        assert any("[1] does not match" in p for p in draft_problems("Shares rose [1].", facts(), sources=sources))
        assert any("[1] does not match" in p for p in executive_problems(
            [EXEC[0], "Shares rose [1].", EXEC[2]], facts(), sources, "Different dashboard."))
        assert any("[1] does not match" in p for p in context_problems("Shares rose [1].", facts(), sources))


def test_judge_flags_an_unsupported_cited_executive_claim_for_revision():
    source = {"summary": "Technology shares fell.", "topic": "market"}
    drafts = [two_part(executive=[EXEC[0], "Technology shares rose [1].", EXEC[2]]),
              two_part(executive=[EXEC[0], "Technology shares fell [1].", EXEC[2]])]
    reporter_run = FakeRun(*drafts)
    judge = FakeRun(review(approved=False, factual_issue=True, feedback="Source [1] says shares fell."), review())
    result = asyncio.run(draft_and_judge(facts(), ["analyst"], ["Fees"], reporter_run, judge,
                                         max_rewrites=1, rejudge=True, sources=[source]))
    assert "Technology shares fell." in judge.prompts[0]
    assert "Source [1] says shares fell." in reporter_run.prompts[1]
    assert result.chosen and "fell [1]" in result.chosen.draft.executive[1]
    assert "unresolved or" in INSTRUCTIONS and "unsupported citation is a factual issue" in INSTRUCTIONS


def test_unresolved_executive_citation_triggers_a_rewrite_and_is_omitted_if_unfixed():
    reporter_run = FakeRunBy(lambda p: two_part(executive=[EXEC[0], "Shares rose [1].", EXEC[2]]))
    judge = FakeRun(review())
    result = asyncio.run(draft_and_judge(facts(), ["analyst"], ["Fees"], reporter_run, judge,
                                         sources=[], rejudge=False))
    assert len(reporter_run.prompts) == 1
    assert "Shares rose [1]." not in judge.prompts[0]
    assert result.chosen and not result.chosen.draft.executive
