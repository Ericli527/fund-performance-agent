""" Judge Agent: checks the reporting drafts against a checklist (framework point 2)

The Judge marks each draft pass or fail on five checklist items and may name the draft it prefers. It never writes
or edits text, never gives a number and never changes a rating. Code decides everything else:
- "Figures match the source data" is code's number, label and rating check, not the Judge's opinion.
- A draft's score = figures match (code) + the checklist items the Judge passed, out of 6.
- Code picks the best draft: only drafts that pass every item can win; on a tie, the Judge's preferred draft, then
  the plan's angle order. If none passes, every draft is sent back once with its issues (Reporting Agents rewrite),
  then judged again. If still none passes, code's own conclusion is used, with a flag.
"""
from dataclasses import dataclass, field
import asyncio
import json
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.agents.reporter import MAX_SUMMARY_CHARS, Draft, write_draft
from fund_performance.models import DataFlag

CHECKLIST = ("key_points_covered", "conclusion_clear", "plain_english", "no_rating_change", "supported_by_facts")
CHECK_WORDS = {"figures_match": "figures match the source data (code)", "key_points_covered": "key points covered",
               "conclusion_clear": "conclusion clear", "plain_english": "plain English",
               "no_rating_change": "no rating change", "supported_by_facts": "supported by the facts"}
MAX_SCORE = len(CHECKLIST) + 1
AI_DRAFTS_FAILED = "AI drafts failed the checklist"

INSTRUCTIONS = """
You are a strict judge of draft conclusions for a fund oversight review. You do not write or edit text and you
never suggest a different rating or verdict (code decided them). For each numbered draft, mark each item true or
false, and list short, specific issues (quote the words at fault) for every false item:
- key_points_covered: says what the fund aims to do, whether it did it, how it compares with peers and its fee (as
  far as the facts allow), and the suggested verdict.
- conclusion_clear: a reader knows the suggested verdict and what happens next.
- plain_english: short sentences; technical terms explained or avoided.
- no_rating_change: never states or suggests a rating or verdict other than the scorecard's.
- supported_by_facts: every statement is supported by the facts JSON.
Then name the draft you prefer for its reader (its number), or null if none is good enough.
"""


class DraftCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: int
    key_points_covered: bool
    conclusion_clear: bool
    plain_english: bool
    no_rating_change: bool
    supported_by_facts: bool
    issues: list[str]


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drafts: list[DraftCheck]
    preferred: int | None


def judge_agent():
    return build_agent("Judge Agent", INSTRUCTIONS, JudgeOutput, "judge")


def judge_input(facts: dict, drafts: list[Draft]) -> str:
    keep = {k: facts[k] for k in ("fund", "scorecard", "data_notes", "peers", "evidence") if k in facts}
    numbered = [{"draft": i + 1, "reader": d.angle, "text": d.text} for i, d in enumerate(drafts)]
    return "Facts JSON (decided by code):\n" + json.dumps(keep, ensure_ascii=False) + \
        "\n\nDrafts:\n" + json.dumps(numbered, ensure_ascii=False)


@dataclass
class Scored:
    draft: Draft
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(self.checks.values())

    @property
    def passes(self) -> bool:
        return len(self.checks) == MAX_SCORE and all(self.checks.values())

    def to_dict(self, chosen: bool) -> dict:
        return {"angle": self.draft.angle, "text": self.draft.text, "checks": self.checks, "score": self.score,
                "max_score": MAX_SCORE, "issues": self.issues, "rewritten": self.draft.rewritten, "chosen": chosen}


@dataclass
class DraftResult:
    chosen: Scored | None = None
    scored: list[Scored] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


async def _judge(facts: dict, drafts: list[Draft], run: RunFn | None) -> tuple[list[Scored], int | None, str | None]:
    """ Code's check plus the Judge's checklist for each draft; drafts that fail code's checks are not sent """
    scored = [Scored(d, {"figures_match": d.figures_match}, list(d.problems) + ([d.error] if d.error else []))
              for d in drafts]
    sent = [s for s in scored if s.draft.figures_match]
    if not sent:
        return scored, None, None
    result = await run_structured(judge_agent(), judge_input(facts, [s.draft for s in sent]), JudgeOutput, run=run)
    if not result.ok:
        return scored, None, "; ".join(result.errors)[:300]
    by_number = {c.draft: c for c in result.output.drafts}
    for i, s in enumerate(sent, start=1):
        check = by_number.get(i)
        if check is None:
            s.checks |= {item: False for item in CHECKLIST}
            s.issues.append("judge: no verdict for this draft")
            continue
        s.checks |= {item: getattr(check, item) for item in CHECKLIST}
        s.issues += [f"judge: {x}" for x in check.issues]
    preferred = result.output.preferred
    return scored, (sent[preferred - 1].draft.angle if preferred and 1 <= preferred <= len(sent) else None), None


def pick(scored: list[Scored], preferred: str | None, order: list[str]) -> Scored | None:
    """ Code's pick: the highest score among drafts that pass everything; tie -> the Judge's preferred, then the
    plan's angle order """
    passing = [s for s in scored if s.passes]
    if not passing:
        return None
    rank = {a: i for i, a in enumerate(order)}
    return min(passing, key=lambda s: (-s.score, s.draft.angle != preferred, rank.get(s.draft.angle, 99)))


async def draft_and_judge(facts: dict, angles: list[str], focus: list[str], run_reporter: RunFn | None = None,
                          run_judge: RunFn | None = None, max_rewrites: int = 1,
                          max_chars: int = MAX_SUMMARY_CHARS) -> DraftResult:
    out = DraftResult()
    drafts = list(await asyncio.gather(*(write_draft(facts, a, focus, run_reporter, max_chars=max_chars)
                                         for a in angles)))
    for attempt in range(max_rewrites + 1):
        scored, preferred, error = await _judge(facts, drafts, run_judge)
        out.scored = scored
        out.log.append(f"Drafts, round {attempt + 1}: " + "; ".join(
            f"{s.draft.angle} {s.score}/{MAX_SCORE}" for s in scored) + (f" (Judge: {error})" if error else ""))
        if error:
            out.flags.append(DataFlag(check="judge", level="warning", message=(
                f"AI drafts not judged: the Judge Agent gave no valid answer ({error[:150]}); code's conclusion used")))
            return out
        out.chosen = pick(scored, preferred, angles)
        if out.chosen or attempt == max_rewrites:
            break
        # None passed: send every draft back once, with all its issues
        drafts = list(await asyncio.gather(*(
            write_draft(facts, s.draft.angle, focus, run_reporter, s.issues or ["make it pass the checklist"],
                        s.draft.text, max_chars) for s in scored)))
    if out.chosen is None:
        failed = sorted({CHECK_WORDS[k] for s in out.scored for k, v in s.checks.items() if not v})
        out.flags.append(DataFlag(check="judge", level="warning", message=(
            f"{AI_DRAFTS_FAILED} ({', '.join(failed) or 'no valid draft'}); code's conclusion used")))
    return out
