import copy
from html import unescape
import re

from fund_performance.presentation import categorised_finding, emphasised_answer
from fund_performance.dashboard import _summary
from fund_performance.presentation import EvidenceQuality
from test_investment_analyst import FACTS


def test_emphasis_preserves_decimal_figures_and_qualifications():
    text = 'The fund returned 13.8% a year, subject to verification. This supports a preliminary view.'
    html = emphasised_answer(text)
    assert html.startswith('<strong>The fund returned 13.8% a year, subject to verification.</strong>')
    assert unescape(re.sub('<[^>]+>', '', html)) == text


def test_labels_are_bold_and_existing_findings_are_categorised_safely():
    assert categorised_finding('Performance: The fund tracked closely.') == '<strong>Performance:</strong> The fund tracked closely.'
    assert categorised_finding('Over five years the fund was 0.10% behind its index.').startswith('<strong>Performance:</strong>')
    assert categorised_finding('The peer returned less.').startswith('<strong>Value for investors:</strong>')
    for text in ['Performance: <script>alert(1)</script>', '<img src=x onerror=alert(1)>']:
        assert '<script>' not in categorised_finding(text) and '<img' not in emphasised_answer(text)


def test_answer_and_findings_render_with_emphasis_without_mutating_evidence():
    facts = copy.deepcopy(FACTS)
    facts['suggested_conclusion'] = {'source': 'ai', 'answer': 'A qualified conclusion. Supporting context.\n\nA material risk. Take action.',
                                    'evidence': ['Performance: The fund tracked its index.', 'Fees: The charge is disclosed.']}
    before = copy.deepcopy(facts)
    html = _summary({'facts': facts, 'reasons': {}}, EvidenceQuality('clear', 'Clear', ''), concise=True)
    assert '<strong>A qualified conclusion.</strong>' in html
    assert '<strong>A material risk.</strong>' in html
    assert '<strong>Performance:</strong>' in html and '<strong>Fees:</strong>' in html
    assert facts == before
