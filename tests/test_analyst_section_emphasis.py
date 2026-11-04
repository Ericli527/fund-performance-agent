import copy

from fund_performance.dashboard import _analyst_card


def assessment():
    return {'status': 'available', 'review_status': 'qualified_draft', 'assessment': {
        'recommendation': 'satisfied',
        'investment_thesis': 'The fund appears to meet its mandate, subject to verification. Supporting context remains visible.',
        'supporting_evidence': ['Performance: The fund follows its benchmark.', 'The fund discloses an ongoing charge.',
                                'The peer comparison is limited to an institutional share class.'],
        'investment_ratings': [{'dimension': 'Performance', 'proposed_rating': 'GREEN',
            'quantitative_scorecard_rating': 'GREEN', 'agreement': True,
            'rationale': 'The evidence supports a preliminary tracking assessment. Confirm the source figures.',
            'supporting_evidence': ['Performance: Returns are close to the benchmark.'],
            'evidence_references': ['performance:5y'], 'limitations': ['Figures are provisional.']}],
        'recommended_actions': ['Verify the source before sign-off.']}}


def test_analyst_conclusions_and_supporting_categories_are_emphasised_in_both_views():
    data = assessment()
    before = copy.deepcopy(data)
    html = _analyst_card(data)
    main, detail = html.split('<summary>Detailed AI Analysis</summary>', 1)
    for part in (main, detail):
        assert '<strong>The fund appears to meet its mandate, subject to verification.</strong>' in part
        assert '<strong>Performance:</strong>' in part
        assert '<strong>Fees:</strong>' in part and '<strong>Value for investors:</strong>' in part
        assert '<strong>The evidence supports a preliminary tracking assessment.</strong>' in part
    assert 'Qualified draft' in main and 'Satisfied' in main and 'Supporting context remains visible.' in main
    assert 'Evidence: performance:5y' in main and 'Verify the source before sign-off.' in detail
    assert data == before


def test_partial_analyst_content_keeps_status_and_escapes_untrusted_text():
    data = {'status': 'partial', 'review_status': 'requires_analyst_review', 'assessment': {
        'recommendation': None, 'supporting_evidence': ['Performance: <script>bad</script>'],
        'investment_thesis': '<img src=x onerror=bad> This is not trusted markup.'}}
    html = _analyst_card(data)
    assert 'Requires analyst review' in html and 'Recommendation requires further assessment' in html
    assert '<script>' not in html and '<img' not in html
    assert '&lt;script&gt;' in html and '&lt;img' in html
    assert '<strong>Performance:</strong>' in html
