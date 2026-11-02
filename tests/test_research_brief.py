"""Research PDF uses existing review evidence and never invents missing research."""
import asyncio
from pathlib import Path

from fund_performance.research_brief import build_research_brief
from fund_performance.report import page_texts
from test_report import made_up_inputs


def test_research_brief_uses_dated_sources_and_questions(tmp_path):
    inp = made_up_inputs()
    inp.presentation_context = {
        'research': [{'summary': 'The benchmark provider changed its methodology.',
                      'url': 'https://example.org/index', 'date': '2026-10-15',
                      'relevance': 'The fund follows this benchmark.', 'limitations': 'Post-review source.'}],
        'investment_assessment': {'status': 'available', 'assessment': {
            'investment_thesis': 'Monitor benchmark changes.',
            'manager_questions': ['How will the index change affect tracking?']}}}
    path, count = build_research_brief(inp, tmp_path)
    text = ' '.join(page_texts(path))
    assert count == 1 and 'Research Brief' in text
    assert '2026-10-15' in text and 'source date after review' in text
    assert 'How will the index change affect tracking?' in text
    from pypdf import PdfReader
    annotations = PdfReader(path).pages[0].get('/Annots') or []
    assert any('https://example.org/index' in str(ref.get_object()) for ref in annotations)


def test_research_brief_without_sources_is_explicit(tmp_path):
    path, count = build_research_brief(made_up_inputs(), tmp_path)
    assert count == 1 and 'No vetted research was available' in ' '.join(page_texts(path))


def test_research_brief_keeps_references_beyond_the_first_three(tmp_path):
    inp = made_up_inputs()
    inp.facts['suggested_conclusion']['research_narrative'] = ['A later source provides context [4].']
    inp.presentation_context = {'research': [
        {'summary': f'Source {i} discusses the market.', 'url': f'https://example.org/{i}', 'date': '2026-09-01'}
        for i in range(1, 5)]}
    path, _ = build_research_brief(inp, tmp_path)
    text = ' '.join(page_texts(path))
    assert '[4]' in text and 'Sources and limitations' in text


def test_long_fund_name_and_manager_question_remain_in_research_brief(tmp_path):
    inp = made_up_inputs()
    inp.profile = inp.profile.model_copy(update={'fund_name': 'Global Investment Fund ' * 5})
    question = 'How does the manager control benchmark rebalancing and trading risk across the portfolio? ' * 3
    inp.facts['manager_questions'] = [question]
    path, _ = build_research_brief(inp, tmp_path)
    text = ' '.join(' '.join(page_texts(path)).split())
    assert 'Global Investment Fund Global Investment Fund' in text
    assert 'How does the manager control benchmark rebalancing' in text


def test_research_failure_does_not_prevent_other_reports(tmp_path, monkeypatch):
    from fund_performance.controller import run_review
    import fund_performance.research_brief as brief
    def fail(*args, **kwargs):
        raise RuntimeError('failure')
    monkeypatch.setattr(brief, 'build_research_brief', fail)
    sample = Path(__file__).parents[1] / 'demo' / 'sample_index_fund'
    result = asyncio.run(run_review(sample, out_root=tmp_path, offline=True))
    assert result.pdf.is_file() and result.executive_pdf.is_file() and result.research_pdf is None
    assert any('Research Brief could not be generated' in f.message for f in result.flags)
