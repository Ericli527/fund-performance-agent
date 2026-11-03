# Fund Rating & Investment Judgement Guide

**Version:** Research draft v0.1 — 3 November 2026  
**Purpose:** Decision support for a human-reviewed fund oversight demonstration, including cases without an uploaded peer factsheet.  
**Authority:** A qualitative research guide, **not** a regulatory standard, approved investment policy, forecast, universal acceptable-return table, or replacement for the deterministic financial engine.  
**Review cadence:** Revalidate external sources, share-class figures and any internal trigger levels before relying on them.

## 1. Decision principles

1. **Use the actual mandate first.** Classify the fund using its objective, strategy and investments (passive index, active equity, bond, mixed-asset, cash/money market, absolute return, etc.). Do not classify on a fund name alone.
2. **Absolute return is not a universal rating threshold.** A US equity tracker delivering 20% when its comparable benchmark delivers 25% may have performed poorly. A tracker delivering -14.9% when its index delivers -15% may have tracked well despite a negative absolute return. Avoid fixed S&P 500 bands such as “10–20% acceptable; above 20% excellent”.
3. **Benchmark-relative outcomes over matched horizons are primary where appropriate.** Validate currency, pricing point, distribution/reinvestment, withholding-tax basis, share class, index variant and dates before claiming an exact gap.
4. **Benchmark versus peer are different.** Missing peer documents should not block mandate or benchmark-relative performance judgements, but must limit claims about **relative market competitiveness** or **best value**.
5. **Separate investment outcome and evidence completeness.** A missing metric does not by itself demonstrate poor performance. A high return does not by itself demonstrate value. Where a claim cannot be supported, qualify the relevant pillar without falsely condemning the investment.
6. **Fees are strategy-dependent.** Compare OCF/TER only when the scope of the charge, vehicle, share-class eligibility and services are understood. Higher charges need a defensible reason; low charges alone cannot prove good investor value.
7. **The AI proposes; independent review challenges; humans approve.** Python computes financial figures and deterministic scorecards. The LLM uses this guide to reason, cite evidence and propose ratings. Never imply regulatory or committee approval.

## 2. Rating interpretation, independent of data completeness

- **GREEN — Satisfactory on available, relevant evidence.** The outcome and strategy appear consistent with the objective and material risks/costs are reasonable *given the evidence*. State key qualifications.
- **AMBER — Substantive concern needing monitoring.** Examples include materially persistent unexplained benchmark lag, cost materially high relative to comparable alternatives, or strategy drift. Cite the concern; do not use Amber only because a peer or secondary statistic is missing.
- **RED — Material adverse evidence.** Examples include persistent significant underperformance against an appropriate objective, material mandate breach or unjustified costs with credible comparator evidence. Avoid classifying a normal market downturn as failure of a tracker.
- **MANUAL_CHECK — A pillar cannot be rated defensibly.** Use when essential evidence is unavailable or materially incomparable. Explain precisely what prevents a judgement and what can still be said.

Maintain separate evidence completeness: `sufficient`, `partial`, `insufficient`, and provenance such as `calculated`, `published`, `ai_extracted`, `unavailable`. A provisional source can support a **qualified draft**, not an unqualified certified finding.

## 3. Fund-type guidance (do not apply as fixed numeric rules)

| Fund type | Mandate / performance test | Value and fees without uploaded peer | Key risk / limitation |
| --- | --- | --- | --- |
| **US large-cap passive / S&P 500 tracker** | Does it track the *correct S&P 500 index variant* net of appropriate costs? Compare matched 1/3/5-year net returns; examine persistent return gap and tracking error where available. The benchmark may have negative returns. | State disclosed OCF and compare against **dated public reference products only** if a credible source/compatible share class is available; do not infer competitiveness from annual return alone. | GBP/USD, dividend withholding-tax variant, noon vs US close, replication, cash drag, fee drag. |
| **Global developed/all-cap equity passive** | Evaluate tracking of FTSE Global All Cap, MSCI ACWI, MSCI World or the *fund's actual index*; avoid equating benchmarks with different small-cap/emerging-market coverage. | Discuss net benchmark tracking, broad exposure, OCF and the product's implementation costs; public comparison is contextual, not a true matched peer if index coverage differs. | Sampling, emerging markets, small caps, pricing and currency. |
| **Active equity** | Judge against the declared investment objective and appropriate broad market or style benchmark over a full cycle. Check net-of-fees and risk-adjusted outcomes, concentration and style consistency. | Without peer, describe the cost structure, investment process and benchmark-relative evidence; do **not** assert outperformance or good value solely from a positive absolute return. | Style drift, concentration, drawdown, turnover, active risk, manager changes. |
| **Investment-grade / government bond passive** | Compare matched total returns against the specified bond index. Consider duration, yield sensitivity, credit composition and hedging. A negative return in a rate shock is not automatically tracking failure. | Describe OCF with comparison to verified, relevant bond-fund references if available; do not transfer US equity fee bands. | Duration, credit, currency/hedging, yield curve, inflation. |
| **Active credit / high yield / emerging-market debt** | Assess objective, total return and income against appropriate credit benchmark, including drawdown/default/illiquidity evidence where available. | Explain credit and liquidity risk and charges; avoid an arbitrary universal expected return or fee range. | Default risk, credit spread, liquidity, derivatives and leverage. |
| **Multi-asset / target risk / balanced** | Assess whether actual allocation and volatility are consistent with target; compare performance with an appropriately constructed and dated blended reference or published target, not with the S&P 500 alone. | Consider asset allocation quality, diversification, service and fees; comparable mixed-asset references must match equity/bond exposure. | Equity weight, duration, rebalancing, currency exposure. |
| **Money-market / cash-like** | Evaluate capital stability, liquidity, yield against appropriate short-term rate/benchmark and the mandated maturity/quality rules. Do not compare with equity return targets. | Evaluate net yield and fees in the relevant currency and rate environment; demand liquidity and credit disclosures. | Credit, liquidity, rate changes, variable yields, not deposit-guaranteed. |
| **Absolute-return / alternatives** | Assess the *stated* target (e.g., cash rate plus spread or positive returns over rolling horizon) using the target's own definition and appropriate risk measures. | Avoid generic equity indices when inappropriate. Examine leverage, liquidity, fees and realised objective delivery. | Tail risk, leverage, derivatives, illiquidity, complex fee structure. |

## 4. Dated fee-reference examples — context, NOT acceptable-range thresholds

Public UK fund/product pages observed during research as of November 2026:

| Product | Objective / type | Published OCF / TER | What it does—and does not—show |
| --- | --- | ---: | --- |
| Fidelity Index US Fund **P Acc** (GB00BJS8SH10) | S&P 500 NUK tracker (UK OEIC) | **0.06% OCF** | Illustrates a very low-cost share class tracking a specific tax-adjusted S&P 500 variant. |
| Vanguard S&P 500 UCITS ETF (VUSA / VUAG) | S&P 500 ETF | **0.07% OCF** | Different vehicle and cost components; dealing spreads/platform costs may apply. |
| Vanguard FTSE Global All Cap Index Fund GBP Acc | All-cap developed + emerging passive equity | **0.23% OCF** | Different exposure and sampling complexity from an S&P 500-only product. |
| Vanguard Global Bond Index Fund GBP Hedged Acc | Hedged global investment-grade bond tracker | **0.15% OCF** | Credit/duration/hedging exposure differs from equity. |
| Vanguard UK Government Bond Index Fund GBP Acc | UK government bond index tracker | **0.12% OCF** | Applies to the relevant gilt product, not all bonds. |
| Vanguard LifeStrategy 60% Equity Fund GBP Acc | Mixed-asset allocation | **0.20% OCF** | Different service, risk and asset allocation from single-asset trackers. |

**Do not treat these isolated product observations as a statistical market distribution.** Their minimum, maximum or midpoint is not a calibrated `GREEN` fee threshold. Before comparing, establish product type, fee definition, share-class access, currency and observation date. If a comparison fails, describe the fund's own fee and label *relative fee competitiveness not established*.

**S&P 500 worked example**: An index tracker returning **20%** in a period when its matched benchmark returns **25%** should raise a substantive benchmark-relative performance question; 20% alone does not prove good tracking or good value. Likewise, **0.5–1.0%** charges might be common in some active products but are **not** a defensible “acceptable” default for a plain passive S&P 500 tracker when observed passive products report 0.06–0.07%. Do not automatically rate either case from the number alone: examine comparable share class, fees, objective and period.

## 5. Missing or unreadable peer-factsheet fallback

1. Record peer status as `not_supplied`, `unreadable`, `extracted_but_unverified`, `incompatible`, or `usable`; retain exact document and error provenance where available.
2. **Never create peer performance, cost, rating or ranking.** Do not silently treat an internal hypothetical comparator as an actual peer.
3. Use the fund's mandate, dated factsheet/KID, validated history, benchmark and charges for mandate and performance analysis.
4. For fees, state the fund's exact published OCF/TER and which additional charges are excluded. If the environment has a **sourced, dated, applicable public reference**, use it as contextual evidence labelled `public_reference`, not `uploaded_peer`; otherwise do not assert market-relative competitiveness.
5. For value, give a bounded assessment of delivered objective, net outcomes, risk and charges, then explicitly state that **relative value versus competitors is not established**. Choose `MANUAL_CHECK` when a defensible overall pillar rating is impossible; do not default to `AMBER` purely because the peer is absent.
6. State a maximum of three relevant, non-overlapping qualifications in the main UI, with full audit evidence retained separately.
7. Recommend a single sensible next step—e.g., upload one share-class-comparable peer, confirm an official market fee reference, or retrieve a dated source if research is authorised.
8. If research access is disabled, do not invent external context. The guide's examples cannot replace fresh source verification.

## 6. Optional quantitative review triggers (policy proposals — NOT empirically validated)

Use **relative** quantities rather than universal annual-return bands. These are questions for further investigation, not predetermined rating decisions:

- Persistent fund–benchmark return gaps *materially larger than disclosed OCF and plausible implementation costs* merit investigation; compare multiple horizons, basis and fee treatment. No universal numerical tolerance is justified for every index and vehicle.
- A large change in tracking difference across comparable periods merits investigation, even when the fund delivered a positive absolute return.
- Fees materially above well-matched published alternatives should trigger review, with share-class access, vehicle costs, management services and implementation considered.
- For active or multi-asset funds, use the prospectus objective, appropriate benchmark, peer category and agreed oversight policy. A historical 10%, 15% or 20% annualised return cannot be declared acceptable across markets or cycles.
- If the team requests exact Green/Amber/Red bands, first collect a representative, dated distribution for **each product type and market** or formally approve illustrative internal policy thresholds. Document sample, observation date, calculation, rationale and sign-off; don't present those values as FCA mandates.

## 7. Suggested Investment Analyst judgement prompt

> Classify the fund by its documented mandate and product type. Apply this guidance as a qualitative interpretation framework, not a fixed return or charge score. Use Python-calculated figures and source-matched published facts; do not compute new financial statistics. Rate Mandate, Performance, Value and Fees separately. Explain the objective, what actually happened versus the appropriate benchmark, the meaning for investors, and the most important next action. When a peer document is missing or unreadable, do not abandon valid mandate and performance assessments. Distinguish fund-level value from unverified comparative value. Choose GREEN/AMBER/RED only when the evidence supports the interpretation; otherwise MANUAL_CHECK. State up to three material caveats without drowning out supported conclusions. Every material factual claim must reference an actual input or sourced research. An LLM proposal is never human approval.

## 8. Source list and verification

1. **FCA Handbook COLL 6.6.20R–6.6.21R** — assessment of value (service, performance, costs, scale, comparable market rates/services, share classes): https://handbook.fca.org.uk/handbook/coll6/coll6s6
2. **FCA, Authorised fund managers’ assessments of funds’ value (2021; historical review updated Aug 2025)** — positive returns do not imply good value; objective/strategy/charges context: https://www.fca.org.uk/publications/multi-firm-reviews/authorised-fund-managers-assessments-their-funds-value
3. **FCA, AoV multi-firm review 2023** — peer fee comparison alone is not a complete value assessment: https://www.fca.org.uk/publications/multi-firm-reviews/authorised-fund-managers-assessments-fund-value-2023
4. **Investment Association, Value Assessment Guidance** — comparator selection depends on objective, active/passive strategy, fee structure: https://www.theia.org/sites/default/files/2022-01/IA%20Value%20Assessment%20Guidance_Jan2022update.pdf
5. **Fidelity Index US P Acc, official provider**: https://www.fidelity.co.uk/factsheet-data/factsheet/GB00BJS8SH10-fidelity-index-us-fund-p-acc/charges-and-key-documents
6. **Vanguard S&P 500 ETF, official provider**: https://www.vanguard.co.uk/professional/product/etf/equity/9503/s-p-500-ucits-etf-usd-distributing
7. **Vanguard Global All Cap, official provider**: https://www.vanguard.co.uk/professional/product/fund/equity/8617/ftse-global-all-cap-index-fund-gbp-acc
8. **Vanguard Global Bond Index GBP Hedged, official provider**: https://www.vanguardinvestor.co.uk/investments/vanguard-global-bond-index-fund-gbp-hedged-acc/overview
9. **Vanguard UK Government Bond Index, official provider**: https://www.vanguard.co.uk/professional/product/fund/bond/9148/vanguard-uk-government-bond-index-fund-gbp-acc
10. **Vanguard LifeStrategy 60% Equity, official provider**: https://www.vanguard.co.uk/professional/product/mf/lifestrategy/9241/lifestrategyr-60-equity-fund-gbp-acc

**Important:** This research covers general UK-retail accessible examples and regulatory principles; it does **not** establish comprehensive or current statistical return/fee acceptance bands across all fund categories. Such ranges require representative fund-universe data and explicit review-policy approval.

## Application integration

The Analyst and Quality Reviewer receive only the rubric selected from the documented objective and mandate
interpretation, plus common judgement safeguards. Selection is retrieval guidance, not a financial rating; the LLM
must check it against the source evidence. Unclear strategy receives the common framework without an invented
category. The full guide remains a human-readable research reference. Product examples are not added as numerical
authority. The Reporting Agent distinguishes supported AI conclusions from the quantitative scorecard and evidence
completeness, and targets a concise 2–3 paragraph answer without manufacturing content to reach a word count.
