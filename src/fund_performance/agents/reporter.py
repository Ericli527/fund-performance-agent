""" Reporting Agents: draft the suggested conclusion from different angles, in parallel (framework point 1)

One agent per angle in the plan (board, analyst, meeting with the manager). Each writes 3 to 5 plain sentences
from the facts JSON only, ending with the suggested verdict sentence code gives it, word for word. Code checks every
draft like all AI text: figures must be in the facts (number guard), labels and ratings must match the scorecard,
no web addresses, no minus sign after "behind" or "below", at most 5 sentences, and the verdict sentence at the
end. The Judge Agent then scores the drafts that pass (judge.py).
"""
from dataclasses import dataclass, field
import json
import re
from pydantic import BaseModel, ConfigDict
from fund_performance.agents.base import RunFn, build_agent, run_structured
from fund_performance.agents.analyst import sentences
from fund_performance.conclusion import text_problems

MAX_SENTENCES = 5
MAX_SUMMARY_CHARS = 700     # what Executive page 1 holds with room to spare (settings.yaml drafting)
ANGLE_BRIEFS = {
    "board": "For the board: the outcome in plain words, whether the fund did what it promised, and whether any "
             "action is needed. Short; no technical terms.",
    "analyst": "For the oversight analyst: the evidence behind each of the four ratings and the one or two points "
               "most worth checking before signing.",
    "manager_meeting": "For a meeting with the fund manager: what went well and what to raise with the manager.",
}

INSTRUCTIONS = """
You write the suggested conclusion of a fund oversight review, from one reader's angle. Code has already measured
the fund and decided every rating and the suggested verdict; you only put them into words.
Rules:
- Use only the facts JSON. Quote a figure only if it is in the facts, exactly as shown there (same rounding and
  unit). Never calculate a new figure.
- Never state a rating or verdict different from the scorecard. Do not use the words Green, Amber or Red.
- Plain English, 3 to 5 short sentences, written as evidence ("The evidence suggests ..."); keep it short: code checks the length.
- Write a gap to the index as "0.10% a year behind its index", never with a minus sign after "behind".
- No web addresses, no citations, no headings, no lists.
- End with the verdict sentence you are given, word for word.
"""


class DraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


@dataclass
class Draft:
    angle: str
    text: str = ""
    problems: list[str] = field(default_factory=list)      # code's checks
    error: str | None = None                               # no valid answer from the agent
    rewritten: bool = False

    @property
    def figures_match(self) -> bool:
        return bool(self.text) and self.error is None and not self.problems


_URL = re.compile(r"https?://|\bwww\.")
_MINUS_AFTER = re.compile(r"\b(behind|below)\b(\s+\w+){0,3}?\s*[-−–]\s?\d", re.IGNORECASE)


def verdict_sentence(facts: dict) -> str:
    """ The last sentence of code's own conclusion: "Suggested verdict: ..." """
    text = (facts.get("suggested_conclusion") or {}).get("code_text") or \
        (facts.get("suggested_conclusion") or {}).get("text", "")
    i = text.rfind("Suggested verdict:")
    return text[i:].strip() if i >= 0 else ""


def draft_problems(text: str, facts: dict, max_chars: int = MAX_SUMMARY_CHARS) -> list[str]:
    """ Code's checks on a draft. Its length is checked too: the chosen draft is page 1's summary, and a summary
    that does not fit would stop the Executive Report being made """
    found = [f"check: {p}" for p in text_problems(text, facts)]
    found += ["style: no web addresses" for _ in _URL.findall(text)][:1]
    found += [f"style: minus sign after '{m.group(1)}'; write 'behind by 0.10%'" for m in _MINUS_AFTER.finditer(text)]
    if sentences(text) > MAX_SENTENCES:
        found.append(f"style: {sentences(text)} sentences; use at most {MAX_SENTENCES}")
    if len(text) > max_chars:
        found.append(f"style: {len(text)} characters; use at most {max_chars} (shorter sentences)")
    ending = verdict_sentence(facts)
    if ending and not text.strip().endswith(ending):
        found.append(f"verdict: end with this sentence, word for word: {ending}")
    return found


def reporter_agent():
    return build_agent("Reporting Agent", INSTRUCTIONS, DraftOutput, "reporter")


def reporter_input(facts: dict, angle: str, focus: list[str], issues: list[str] | None = None,
                   previous: str | None = None) -> str:
    keep = {k: facts[k] for k in ("fund", "scorecard", "data_notes", "peers", "evidence", "judgement_points",
                                  "figures") if k in facts}
    prompt = (f"Angle: {ANGLE_BRIEFS[angle]}\nFocus first on: {', '.join(focus[:2])}\n"
              f"Verdict sentence to end with: {verdict_sentence(facts)}\n\nFacts JSON:\n"
              + json.dumps(keep, ensure_ascii=False))
    if issues:
        prompt += ("\n\nYour previous draft:\n" + (previous or "") + "\n\nFix every issue below and keep everything "
                   "else that was right:\n" + "\n".join(f"- {i}" for i in issues))
    return prompt


async def write_draft(facts: dict, angle: str, focus: list[str], run: RunFn | None = None,
                      issues: list[str] | None = None, previous: str | None = None,
                      max_chars: int = MAX_SUMMARY_CHARS) -> Draft:
    result = await run_structured(reporter_agent(), reporter_input(facts, angle, focus, issues, previous),
                                  DraftOutput, run=run)
    if not result.ok:
        return Draft(angle, error="; ".join(result.errors)[:300], rewritten=bool(issues))
    text = " ".join(result.output.text.split())
    return Draft(angle, text, draft_problems(text, facts, max_chars), rewritten=bool(issues))
