from html import unescape
import re

from pypdf import PdfReader

from fund_performance.executive import _summary_html, _findings_list
from fund_performance.report import _render


COMMENTARY = ['The fund appears to have met its mandate, subject to verification. The assessment remains a draft.',
              'Over five years, the fund returned 13.8% a year. The benchmark comparison uses a matched basis.']


def test_report_commentary_emphasis_preserves_complete_sentences_and_escapes_text():
    html = _summary_html({'source': 'ai', 'executive': COMMENTARY})
    assert '<strong>The fund appears to have met its mandate, subject to verification.</strong>' in html
    assert '<strong>Over five years, the fund returned 13.8% a year.</strong>' in html
    assert 'The assessment remains a draft.' in html
    assert '<script>' not in _summary_html({'text': '<script>bad</script>'})
    assert all(p in unescape(re.sub('<[^>]+>', '', html)) for p in COMMENTARY)


def test_pdf_renderer_uses_bold_fonts_for_conclusions_and_category_labels(tmp_path):
    path = tmp_path / 'emphasis.pdf'
    body = _summary_html({'source': 'ai', 'executive': COMMENTARY})
    body += _findings_list(['Performance: A small return gap.', 'Fees: Charges require source confirmation.'])
    _render('<html><body><h2>Oversight commentary</h2>' + body + '</body></html>', path)
    spans = []
    reader = PdfReader(path)
    reader.pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size: spans.append(
        (text, str((font or {}).get('/BaseFont', '')))))
    bold = ''.join(text for text, font in spans if 'Bold' in font)
    assert 'The fund appears to have met its mandate' in bold
    assert 'Performance:' in bold and 'Fees:' in bold
    full = ''.join(text for text, _ in spans)
    assert 'The assessment remains a draft.' in full and 'Charges require source confirmation.' in full
