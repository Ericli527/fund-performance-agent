"""One provenance notice; evidence limits describe specific gaps, not repeated AI boilerplate."""
import re

FOOTER = ('*Data extracted using AI. AI explanation for human review, not professional investment advice; '
          'analyst judgement and sign-off are required.*')
_GENERIC = re.compile(
    r'^(?:AI[- ]extracted (?:figures|data|information)|(?:the |these )?(?:extracted )?(?:figures|data|information)) '
    r'(?:(?:are |remain )?provisional(?: and )?)?'
    r'(?:(?:should |must |still )?(?:be )?(?:checked|verified)|(?:require|requires|need|needs) (?:source )?verification)'
    r'(?: against (?:the |their )?source documents?| before sign-off| against (?:the )?factsheet|[ .])*$', re.I)
_PROVENANCE = re.compile(
    r'^(?:(?:AI[- ]extracted (?:figures|data|information)|(?:the |these )?(?:extracted |source )?(?:figures|data|information)) '
    r'(?:are|remain) provisional|AI extraction and text matching are not independent (?:source )?verification)[ .]*$', re.I)


def specific_limits(text: str) -> str:
    """Remove only recognised, stand-alone provenance clauses; keep substantive qualifications intact."""
    # Some drafts put category bullets inline; ordinary dashes and negative figures are unchanged.
    text = re.sub(r'[ \t]+[-•][ \t]+(?=\*\*[^*\n]{1,80}:\*\*)', '\n- ', text)
    lines = []
    for line in text.split('\n'):
        clauses = re.split(r'(?<=[.!?;])[ \t]+', line)
        kept = [part for part in clauses if not (_GENERIC.fullmatch(part.strip(' ;')) or _PROVENANCE.fullmatch(part.strip(' ;')))]
        lines.append(' '.join(kept))
    return '\n'.join(lines).strip()


_SCOPE_WORDS = set('the table tables label labels labelled labeled and accompanying note notes leave leaves '
                   'some uncertainty uncertain over fund versus vs index attribution composition their '
                   'there is remains about of for between a an although describe describes as'.split())


def additional_context(answer: str, limitations: list[str]) -> list[str]:
    """Omit repeated sentences and generic scope warnings already explained in the answer.

    Novel qualifications, numbers and concrete evidence gaps are never removed as scope duplicates.
    """
    def normal(text):
        return ' '.join(re.findall(r'\w+', text.casefold()))
    sentences = re.split(r'(?<=[.!?;])\s+', answer)
    seen = {normal(sentence) for sentence in sentences}
    scope_explained = (re.search(r'\bfund\b', answer, re.I) and re.search(r'\bindex\b', answer, re.I)
                       and re.search(r'\b(table|tables|labels|labelled|labeled|note)\b', answer, re.I)
                       and re.search(r'\b(although|uncertainty|uncertain|provisional|conflict)\b', answer, re.I))
    result = []
    for limitation in limitations:
        kept = []
        for sentence in re.split(r'(?<=[.!?;])\s+', specific_limits(limitation)):
            words = set(re.findall(r'[a-z]+', sentence.casefold()))
            scope_only = ({'fund', 'index'} <= words and bool(words & {'uncertainty', 'uncertain', 'attribution'})
                          and words <= _SCOPE_WORDS and not re.search(r'\d', sentence))
            key = normal(sentence)
            if not key or key in seen or (scope_explained and scope_only):
                continue
            kept.append(sentence)
            seen.add(key)
        if kept:
            result.append(' '.join(kept))
    return result
