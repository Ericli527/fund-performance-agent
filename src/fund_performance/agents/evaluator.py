""" Evaluator Agent (spec Section 8.4): a quality check on the Oversight Analyst's draft, after code's checks pass

It checks the draft against a fixed rubric and returns JSON only: {"pass": ..., "issues": [{check, detail}]}.
It never writes or edits the text and never changes a rating; its output has no text field to do so. It has its
own system prompt and its own model (config/models.yaml), so the Analyst's work is not graded by itself.

Only public data reaches it: the facts JSON (from public documents and calculations), the numbered search
summaries (without URLs) and the draft.
"""
from dataclasses import dataclass, field
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fund_performance.agents.base import RunFn, build_agent, run_structured

Check = Literal["rating_explained", "no_rating_change", "supported_claims", "sources_cited", "check_data_handled",
                "plain_english"]

INSTRUCTIONS = """
You are a strict quality checker for a draft investment oversight review. You do not write or edit text,
and you never suggest a different rating or verdict. You check the draft against the rubric below and
return JSON only: "pass" (true only if every check passes) and "issues" (one entry per problem found,
empty when pass is true). Each issue names its check and gives a short, specific detail that the writer
can fix, quoting the words at fault.

Ratings and verdict were decided by code and are correct by definition. Judge the draft only against the
facts and sources given.

Rubric (each must pass):
1. rating_explained: each of the 4 ratings (Mandate, Performance, Value for investors, Fees) is mentioned in
   the findings, and what is said about it is consistent with the scorecard reason. Several ratings may share
   a sentence (e.g. "Value for investors and fees need a peer fund").
2. no_rating_change: the text never states or suggests a different rating or verdict, or softens one
   (e.g. "broadly Green", "close to Review").
3. supported_claims: every claim is supported by the facts or by a cited source. Each figure is described as
   what it is in the facts: a number called a tracking difference must be the tracking difference, a
   cumulative gap must not be called a yearly one, periods must match. Each action keeps the task and timing
   of the candidate action it names.
4. sources_cited: every statement about markets or news cites a numbered source such as [1].
5. check_data_handled: any CHECK DATA item is explained as needing a check, not used for a conclusion.
   A MANUAL CHECK item says what the reviewer must check.
6. plain_english: short sentences; each technical term has a short explanation in brackets the first time
   it is used (e.g. "R² 1.00 (how closely fund and index move together)"); no unexplained abbreviations.

Do not raise an issue about style choices the rubric does not cover.
"""


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: Check
    detail: str


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    passed: bool = Field(alias="pass", description="True only if every rubric check passes")
    issues: list[Issue] = Field(description="One entry per problem; empty when pass is true")


@dataclass
class Review:
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    error: str | None = None                  # the Evaluator gave no valid result
    unreachable: bool = False                 # ... because the call failed (network, key, quota), not bad output

    @property
    def failed_checks(self) -> list[str]:
        return list(dict.fromkeys(i.check for i in self.issues))

    def problems(self) -> list[str]:
        """ The issues as a problem list for the Analyst's one rewrite """
        return [f"quality ({i.check}): {i.detail}" for i in self.issues]


def evaluator_agent():
    return build_agent("Evaluator Agent", INSTRUCTIONS, EvaluatorOutput, "evaluator")


def evaluator_input(facts: dict, sources: list[dict], draft: dict) -> str:
    """ The facts, the numbered sources (no URLs) and the draft """
    numbered = [{"source": f"[{s['number']}]", "query": s["query"], "date": s.get("date"),
                 "summary": s["summary"]} for s in sources]
    return ("Facts (decided by code):\n" + json.dumps(facts, indent=1, ensure_ascii=False)
            + "\n\nSources:\n" + (json.dumps(numbered, indent=1, ensure_ascii=False) if numbered else "none")
            + "\n\nDraft to check:\n" + json.dumps(draft, indent=1, ensure_ascii=False))


def _consistent(out: EvaluatorOutput) -> EvaluatorOutput:
    if not out.passed and not out.issues:
        raise ValueError("pass is false but no issues are given")
    return out


async def review(facts: dict, sources: list[dict], draft: dict, run: RunFn | None = None) -> Review:
    """ Check one draft; invalid output is retried once. Issues with pass true still count as a fail, so a
    problem the Evaluator names is never ignored """
    result = await run_structured(evaluator_agent(), evaluator_input(facts, sources, draft), EvaluatorOutput,
                                  convert=_consistent, run=run)
    if not result.ok:
        return Review(False, error="; ".join(result.errors), unreachable=any("call failed" in e for e in result.errors))
    out = result.output
    return Review(out.passed and not out.issues, out.issues)
