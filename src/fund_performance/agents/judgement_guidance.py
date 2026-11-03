"""Qualitative rubric distilled from the user-supplied research guide, draft v0.1, 3 November 2026.

The full sourced guide is in docs/FUND_RATING_JUDGEMENT_GUIDE.md. No numerical fee examples are injected as facts.
"""
JUDGEMENT_GUIDANCE = '''
Apply the Fund Rating & Investment Judgement Guide (research draft v0.1, 3 November 2026) as qualitative decision
support, not approved policy or automatic thresholds. First identify the actual strategy from the documented
objective, investments and implementation, not the fund name alone. Explain that strategy in the investment thesis;
if classification is uncertain, say so and do not invent it. Use the appropriate framework:
- Passive US equity: correct S&P 500 or other stated index variant; matched net benchmark outcomes, tax treatment,
  currency and pricing basis. A market loss does not itself mean poor tracking; a positive return does not prove it.
- Passive global equity: the actual global index, all-cap versus large/mid-cap and emerging-market coverage,
  sampling and implementation. Do not equate FTSE Global All Cap, MSCI ACWI and MSCI World.
- Active equity: documented objective, appropriate market/style reference, net outcomes over the stated horizon,
  concentration, style consistency and available risk evidence. Do not apply passive tracking criteria mechanically.
- Government or investment-grade bonds: specified total-return benchmark or documented objective, duration,
  credit quality, interest-rate sensitivity and currency hedging. Rate-shock losses alone are not mandate failure.
- Active credit: appropriate credit objective and benchmark, income/total returns, defaults, liquidity and leverage.
- Multi-asset: target allocation/risk and an appropriate published blended benchmark or target; do not substitute
  the S&P 500 or construct an unsourced blended series. Consider diversification and rebalancing where documented.
- Money market: capital stability, liquidity and net yield versus the relevant currency's short-term reference;
  maturity and credit rules. Do not apply equity targets or imply deposit guarantees.
- Absolute-return or alternatives: the stated target definition and rolling horizon, leverage, tail risk, liquidity
  and fee structure. Do not substitute generic equity return targets.
Assess each pillar independently when peers are missing, unreadable or incompatible. Mandate uses objective,
strategy and relevant implementation evidence. Performance uses matched objective/benchmark outcomes. Value uses
net investor outcomes, diversification, risks, service and charges while qualifying competitor-relative value.
Fees describes disclosed charges and cost coverage; fee transparency is distinct from fee competitiveness.
Missing peers or secondary risk metrics alone do not justify AMBER or RED. No adverse evidence alone does not
justify GREEN. Choose MANUAL_CHECK only where essential evidence prevents a defensible pillar judgement.
Do not invent peer fees, market averages, benchmark returns or external sources. The guide's isolated dated fee
examples are neither a market distribution nor current verified peer evidence. Use any public reference only when
an identifiable source, date and applicable share class are supplied in this review's vetted evidence. Label it as
public contextual research, not an uploaded peer, and cite its existing research ID. Consider publication timing,
vehicle, eligibility and OCF/TER scope; never turn examples or optional review triggers into universal fee/return bands.
A return gap relative to charges can prompt investigation but charges do not automatically explain the entire gap.
State supported findings before qualifications, distinguish provisional from verified evidence, avoid repeating
missing-data caveats, and give one proportionate next step for an unresolved peer comparison. Independent proposals
remain separate from Python's quantitative scorecard and always require human sign-off.
'''


def guidance_for(profile, fund_context=None) -> dict:
    """Retrieve a rubric from documented strategy text; never assign an investment rating."""
    import re
    sections = dict(re.findall(r'^- ([^:]+): (.*?)(?=\n- |\nAssess each)', JUDGEMENT_GUIDANCE, re.M | re.S))
    common = JUDGEMENT_GUIDANCE[JUDGEMENT_GUIDANCE.index('Assess each pillar'):]
    objective = str(profile.objective_text or '').casefold()
    interpretation = str((fund_context or {}).get('mandate_interpretation') or '').casefold()
    text = objective + ' ' + interpretation
    reference = str(profile.benchmark_name or '').casefold()
    chosen = None
    if re.search(r'money.market|cash.like|short.term liquidity', text):
        chosen = 'Money market'
    elif re.search(r'absolute.return|alternative|cash.*plus|market.neutral', text):
        chosen = 'Absolute-return or alternatives'
    elif re.search(r'multi.asset|balanced|equity and bond|equities and bonds|target.risk', text):
        chosen = 'Multi-asset'
    elif re.search(r'high.yield|active credit|emerging.market debt', text):
        chosen = 'Active credit'
    elif re.search(r'government bond|investment.grade|bond|fixed.income|gilts?', text):
        chosen = 'Government or investment-grade bonds'
    elif re.search(r'active.*equit|stock.select|outperform', text):
        chosen = 'Active equity'
    elif re.search(r'passive|track|replicat|index', text):
        if re.search(r'global|world|all.cap|acwi', text + ' ' + reference):
            chosen = 'Passive global equity'
        elif re.search(r's&p.?500|us equity|us equities|us large|u\.s\.', text + ' ' + reference):
            chosen = 'Passive US equity'
    elif re.search(r'active.*equit|stock.select|outperform.*equit|equities.*outperform', text):
        chosen = 'Active equity'
    return {'strategy_framework': chosen or 'Uncertain: use the documented objective',
            'guidance': ('Qualitative guidance; no automatic rating thresholds. Confirm the strategy against the '
                         'source documents and correct this retrieval choice if contradicted. '
                         + (sections[chosen] if chosen else 'Do not infer a fund category or benchmark from its name alone. ')
                         + '\n' + common)}
