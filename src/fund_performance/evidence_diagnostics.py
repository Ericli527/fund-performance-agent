"""Presentation-only evidence-gap explanations from the current review's recorded inputs."""
from fund_performance.scorecard import _tracking_stats


def evidence_gap_summary(profile, factsheet, prices, calculated, reported, card, flags, intake=None,
                         extractor_status=None):
    """Explain observed gaps without claiming a document omitted a figure that extraction may have missed."""
    if profile.objective_type != 'index_tracker':
        return []
    missing = []
    mandate = card.pillars.get('Mandate')
    if mandate and mandate.rating == 'CHECK DATA' and 'R² and beta not available' in mandate.reason:
        r2, beta, _ = _tracking_stats(reported, profile.analysis_period_years)
        if r2 is None:
            missing.append('R²')
        if beta is None:
            missing.append('beta')
    performance = card.pillars.get('Performance')
    if performance and any(s.name == 'Tracking error' and s.rating == 'CHECK DATA' and
                           'tracking error not available' in s.reason.lower()
                           for s in performance.sub_ratings):
        missing.append('tracking error')
    risk_loss = any(f.check == 'extraction_risk_tables' for f in flags)
    if not missing and not risk_loss:
        return []
    result = []
    if missing:
        result.append('Not established for the rating: ' + ', '.join(missing) + '.')
    extractor_flags = [f for f in flags if f.check == 'extractor_agent']
    if any(f.level == 'blocking' or 'gave no valid answer' in f.message for f in extractor_flags):
        result.append('Document extraction did not produce valid structured figures; retry or enter source figures manually.')
    elif intake and intake.get('factsheet') is not None:
        result.append('Document extraction returned structured figures; this does not establish that every risk metric was found.')
    elif extractor_status == 'ok':
        result.append('Document extraction returned structured figures; this does not establish that every risk metric was found.')
    elif factsheet is not None:
        result.append('A structured factsheet was loaded; its risk figures may still be incomplete or require verification.')
    else:
        result.append('No structured factsheet figures were available; inspect the source or extraction result.')
    text_chars = (intake or {}).get('text_chars') or {}
    if text_chars:
        files = [f'{name} ({count} text characters)' for name, count in text_chars.items()
                 if isinstance(count, int) and count >= 0]
        if files:
            result.append('Fund documents read: ' + ', '.join(files) + '. Readable text alone does not confirm a metric was extracted.')
    series_names = {'fund_nav': 'fund NAV', 'fund_pnav': 'fund PNAV', 'index': 'benchmark'}
    series = getattr(factsheet, 'series', {}) or {}
    annualised = getattr(factsheet, 'series_annualised', {}) or {}
    present_series = [label for name, label in series_names.items()
                      if any(getattr(group.get(name), key, None) is not None
                             for group in (series, annualised) for key in ('y1', 'y3', 'y5', 'since_launch'))]
    if present_series:
        result.append('Structured return figures are available for: ' + ', '.join(present_series) +
                      '. Check their dates, basis and source before sign-off.')
    if any(f.level in ('warning', 'blocking') for f in extractor_flags) or risk_loss:
        result.append('Extraction or source-check warnings were recorded; inspect the technical details and original documents.')
    source_date = (intake['factsheet'].get('as_of_date') if intake and intake.get('factsheet')
                   else getattr(factsheet, 'as_of_date', None) if not intake else None)
    if source_date and str(source_date) != profile.as_of_date.isoformat():
        result.append('The factsheet date differs from the review date; check that the risk figures cover the intended period.')
    if missing:
        risk_fields = ('r2', 'beta', 'tracking_error')
        names = {'r2': 'R²', 'beta': 'beta', 'tracking_error': 'tracking error'}
        risk_sets = [factsheet.risk_3y, factsheet.risk_3y_nav] if factsheet else []
        present = [names[n] for n in risk_fields if any(r is not None and getattr(r, n) is not None for r in risk_sets)]
        if present:
            result.append('Structured factsheet risk figures include ' + ', '.join(present) +
                          '; verify their period, basis and eligibility for the rating.')
        elif factsheet is not None:
            result.append('The structured factsheet contains no R², beta or tracking error. Check the original document; '
                          'the figures may be absent, missed during extraction or not retained.')
        else:
            result.append('No structured factsheet risk figures are available. Check the original document and extraction result.')
        has_nav = 'nav' in prices.columns and prices['nav'].notna().any()
        if not has_nav:
            result.append('No usable fund NAV price observations were loaded. Supply the fund price history.')
        else:
            result.append('Fund NAV price observations were loaded.')
        if 'index_level' not in prices.columns:
            result.append('No benchmark price series was loaded. Supply a compatible, dated benchmark series, or provide '
                          'published risk figures with their period and basis.')
        elif prices['index_level'].notna().sum() == 0:
            result.append('A benchmark column was loaded but contains no usable observations. Supply a compatible, dated '
                          'benchmark series or published risk figures with their period and basis.')
        elif not has_nav:
            result.append('Benchmark prices were supplied, but they cannot be compared until fund NAV observations are available.')
        else:
            common = prices[['nav', 'index_level']].dropna()
            if len(common) < 2:
                result.append('The benchmark column has fewer than two common observations with fund prices. '
                              'Check dates and provide aligned fund and benchmark histories.')
            elif any(f.level == 'blocking' and f.check in ('currency_match', 'implausible_tracker_gap') for f in flags):
                result.append('A benchmark or currency data check blocks comparison. Resolve it before using relative statistics.')
            else:
                result.append('A benchmark series was loaded, but the required rating evidence was not established. '
                              'Check common dates, review-period coverage, pricing basis and calculation or selection logs.')
        if has_nav and any(k.startswith('fund.vol.') for k in calculated.figures):
            result.append('The fund price history supports fund-only risk measures; it cannot by itself establish benchmark-relative risk.')
    return result
