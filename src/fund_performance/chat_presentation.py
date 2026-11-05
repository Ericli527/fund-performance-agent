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
    paragraphs = []
    for paragraph in text.split('\n\n'):
        clauses = re.split(r'(?<=[.!?;])\s+', paragraph.strip())
        kept = [part for part in clauses if not (_GENERIC.fullmatch(part.strip(' ;')) or _PROVENANCE.fullmatch(part.strip(' ;')))]
        if kept:
            paragraphs.append(' '.join(kept))
    return '\n\n'.join(paragraphs)
