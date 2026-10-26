""" Oversight scoring: mandate, performance, value and fees, each rated Green / Amber / Red by fixed rules """
from dataclasses import dataclass, field
import os
import re
import numpy as np
import pandas as pd
from analysis import FundAnalysis
from calculator import fmt_pct

RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.0))
GREEN, AMBER, RED, NOT_ASSESSED, CHECK_DATA = "Green", "Amber", "Red", "Not assessed", "Check data"
FEE_HORIZON_YEARS = 5
FEE_EXAMPLE_AMOUNT = 10_000
PEER_PERIODS = ("5Y p.a.", "3Y p.a.", "1Y")

# The rules, shown in the report so anyone can check how a rating was reached
RULES = [
    "Data: the fund manager's official reported returns are used when supplied; returns calculated from prices are the fallback.",
    "Mandate (index fund): tracking difference (fund minus index) over the longest period up to 5 years: within 0.30 pp "
    "a year = Green, within 0.75 pp = Amber, otherwise Red.",
    "Mandate (active fund): excess return over the longest period up to 5 years at least 0% a year = Green, "
    "at least -1% a year = Amber, otherwise Red.",
    "Performance (index fund): 1-year tracking difference from official figures, same limits as the mandate; "
    "from prices only, tracking error up to 1% = Green, up to 2% = Amber, otherwise Red.",
    "Performance (active fund): 1-year excess return at least 0% = Green, at least -3% = Amber, otherwise Red.",
    "Data check (index fund, prices only): a result outside the Green limit is shown as Check data instead of a rating, "
    "because downloaded fund and benchmark prices are often taken at different times. Confirm it with the fund's factsheet.",
    "Value: the fund's return after fees against the peer's, over the longest period both report (up to 5 years): "
    "at least equal = Green, within 0.50% a year = Amber, otherwise Red. With prices only, the risk-adjusted return "
    "(Sharpe ratio) over the same months is used instead: at least equal = Green, within 0.10 = Amber, otherwise Red.",
    "Fees: fee no higher than the peer = Green; higher, but the fund's return after fees beat the peer's = Green "
    "(fee justified); higher and up to 1% a year behind = Amber; otherwise Red.",
    "Verdict: any Red = Review; any Amber, Not assessed or Check data = Monitor; otherwise Retain. If fewer than two "
    "questions could be rated, the verdict is Incomplete data. A human must approve the verdict.",
]


@dataclass
class Pillar:
    name: str
    rating: str
    evidence: str


@dataclass
class OversightResult:
    fund_type: str
    fund_ocf: float | None
    pillars: list[Pillar] = field(default_factory=list)
    peer: dict | None = None
    comparison: pd.DataFrame | None = None
    comparison_period: str = ""
    fee_costs: dict = field(default_factory=dict)
    fee_justified: bool | None = None
    verdict: str = ""

    def facts_markdown(self) -> str:
        """ The scoring results, for the Oversight Analyst agent (it explains them, it cannot change them) """
        lines = ["### Oversight scoring (rule-based, final)", f"Fund type: {self.fund_type}. Verdict: {self.verdict}."]
        lines += [f"- {p.name}: {p.rating}. Evidence: {p.evidence}" for p in self.pillars]
        if self.peer:
            fee = "not given" if self.peer.get("ocf") is None else fmt_pct(self.peer["ocf"])
            lines.append(f"Peer: {self.peer['name']}, fee {fee}. Fund fee: "
                         + ("not given" if self.fund_ocf is None else fmt_pct(self.fund_ocf)) + ".")
        if self.comparison is not None:
            lines.append(f"\n### Fund vs peer, {self.comparison_period}\n\n" + comparison_markdown(self.comparison))
        if self.fee_costs:
            lines.append("\nFees on " + f"£{FEE_EXAMPLE_AMOUNT:,} over {FEE_HORIZON_YEARS} years, ignoring growth: "
                         + "; ".join(f"{k} £{v:,.0f}" for k, v in self.fee_costs.items()))
        return "\n".join(lines)


def parse_percent(text: str | None) -> float | None:
    """ '0.65%' or '0.65' -> 0.0065 """
    if not text:
        return None
    match = re.search(r"-?\d+(\.\d+)?", str(text))
    return float(match.group()) / 100 if match else None


def fund_ocf(analysis: FundAnalysis) -> float | None:
    for name in ("ongoing charges", "ongoing charge", "ocf", "ongoing charges figure", "share class ongoing charges",
                 "total expense ratio", "ter", "annual management fee", "management fee"):
        if (value := analysis.fact(name)) is not None:
            return parse_percent(value)
    return None


def _rate(value: float, green: float, amber: float, higher_is_better: bool = True) -> str:
    if not higher_is_better:
        value, green, amber = -value, -green, -amber
    return GREEN if value >= green else AMBER if value >= amber else RED


def _longest_excess(analysis: FundAnalysis) -> tuple[float, str]:
    """ Annualised excess return over the longest standard period up to 5 years """
    periods = analysis.periods
    for label in ("5Y p.a.", "3Y p.a.", "Since launch p.a.", "Since start p.a.", "1Y", "Since start"):
        if label in periods.columns:
            return periods.at["Relative", label], label
    return float("nan"), ""


def _stats(levels: pd.Series) -> dict:
    """ Annualised return, volatility and Sharpe ratio from month-end levels """
    returns = levels.pct_change().dropna()
    years = len(returns) / 12
    ann = (levels.iloc[-1] / levels.iloc[0]) ** (1 / years) - 1
    vol = returns.std() * np.sqrt(12)
    one_year = levels.iloc[-1] / levels.iloc[-13] - 1 if len(levels) > 12 else float("nan")
    return {"Annualised return": ann, "1-year return": one_year, "Volatility": vol,
            "Sharpe ratio": (ann - RISK_FREE_RATE) / vol if vol else float("nan")}


def comparison_cell(column: str, value: float) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value:.2f}" if column == "Sharpe ratio" else fmt_pct(value)


def comparison_markdown(df: pd.DataFrame) -> str:
    lines = ["| | " + " | ".join(df.columns) + " |", "|---|" + "---|" * len(df.columns)]
    for name, r in df.iterrows():
        lines.append(f"| {name} | " + " | ".join(comparison_cell(c, r[c]) for c in df.columns) + " |")
    return "\n".join(lines)


def _official_peer_period(analysis: FundAnalysis) -> str | None:
    """ The longest period with official returns for both the fund and the peer """
    perf = analysis.parsed.performance
    if perf is None or "peer" not in perf.columns:
        return None
    return next((p for p in PEER_PERIODS if p in perf.index and pd.notna(perf.at[p, "peer"])), None)


def _checked(name: str, rating: str, evidence: str, analysis: FundAnalysis) -> Pillar:
    """ An index fund far from its index on price data alone is more often a data problem than a real one """
    if rating == GREEN or analysis.official:
        return Pillar(name, rating, evidence)
    return Pillar(name, CHECK_DATA, evidence + " This is unusual for an index fund: the fund and benchmark prices may be "
                  "taken at different times. Confirm with the fund's factsheet before rating.")


def _fees(result: OversightResult, fund_name: str, peer: dict, fund_fee: float, peer_fee: float, return_gap: float) -> None:
    """ Is the fee justified? A higher fee is, if the fund still returned more than the peer after fees """
    if pd.isna(fund_fee) or pd.isna(peer_fee):
        result.pillars.append(Pillar("Fees", NOT_ASSESSED, "Fee missing for the fund or the peer."))
        return
    for name, fee in ((fund_name, fund_fee), (peer["name"], peer_fee)):
        result.fee_costs[name] = FEE_EXAMPLE_AMOUNT * fee * FEE_HORIZON_YEARS
    if fund_fee <= peer_fee:
        rating, why = GREEN, "no higher than the peer's"
    else:
        result.fee_justified = return_gap >= 0
        rating = GREEN if result.fee_justified else _rate(return_gap * 100, 0.0, -1.0)
        why = ("higher than the peer's, but the fund's return after fees was higher, so the extra fee paid for itself"
               if result.fee_justified else "higher than the peer's, and the fund's return after fees was lower")
    result.pillars.append(Pillar("Fees", rating, f"Fee {fmt_pct(fund_fee)} vs peer {fmt_pct(peer_fee)}: {why} "
                                                 f"(return gap {fmt_pct(return_gap, True)} a year)."))


def assess(analysis: FundAnalysis, fund_type: str, fund_name: str, peer: dict | None,
           peer_levels: pd.Series | None) -> OversightResult:
    """ Score the four oversight questions; fund_type is 'passive' or 'active' """
    result = OversightResult(fund_type=fund_type, fund_ocf=fund_ocf(analysis), peer=peer)
    passive = fund_type == "passive"
    source = ", official figures" if analysis.official else f", prices {analysis.period_label}"

    # 1. Mandate: is the fund doing what it promised?
    if analysis.periods is None:
        result.pillars.append(Pillar("Mandate", NOT_ASSESSED, "No performance data to test the objective."))
    else:
        excess, label = _longest_excess(analysis)
        if passive:
            rating = _rate(abs(excess) * 100, 0.30, 0.75, higher_is_better=False)
            evidence = f"Objective is to track the index; tracking difference {fmt_pct(excess, True)} ({label}{source})."
            result.pillars.append(_checked("Mandate", rating, evidence, analysis))
        else:
            result.pillars.append(Pillar("Mandate", _rate(excess * 100, 0.0, -1.0),
                                         f"Excess return vs benchmark {fmt_pct(excess, True)} ({label}{source})."))

    # 2. Performance vs benchmark
    if analysis.periods is None:
        result.pillars.append(Pillar("Performance", NOT_ASSESSED, "No performance data."))
    elif passive and analysis.official and "1Y" in analysis.periods.columns:
        td = analysis.periods.at["Relative", "1Y"]
        result.pillars.append(Pillar("Performance", _rate(abs(td) * 100, 0.30, 0.75, higher_is_better=False),
                                     f"1-year return {fmt_pct(analysis.periods.at['Fund', '1Y'])} vs index "
                                     f"{fmt_pct(analysis.periods.at['Benchmark', '1Y'])}: tracking difference "
                                     f"{fmt_pct(td, True)}{source}."))
    elif passive and analysis.metrics is not None:
        te = analysis.metrics.at["Tracking error", "Relative"]
        rating = _rate(te * 100, 1.0, 2.0, higher_is_better=False)
        result.pillars.append(_checked("Performance", rating, f"Tracking error {fmt_pct(te)} (prices {analysis.period_label}).", analysis))
    elif passive:
        result.pillars.append(Pillar("Performance", NOT_ASSESSED, "No 1-year figure or price data."))
    else:
        label = "1Y" if "1Y" in analysis.periods.columns else analysis.periods.columns[-1]
        excess = analysis.periods.at["Relative", label]
        result.pillars.append(Pillar("Performance", _rate(excess * 100, 0.0, -3.0),
                                     f"{label} return {fmt_pct(analysis.periods.at['Fund', label])} vs benchmark "
                                     f"{fmt_pct(analysis.periods.at['Benchmark', label])} ({fmt_pct(excess, True)}{source})."))

    # 3 and 4. Value and fees against the peer: official returns first, then prices over the months both have
    if peer is not None and (label := _official_peer_period(analysis)) is not None:
        perf = analysis.parsed.performance
        periods = [p for p in reversed(PEER_PERIODS) if p in perf.index and pd.notna(perf.at[p, "peer"])]
        df = pd.DataFrame({p: [perf.at[p, "fund"], perf.at[p, "peer"]] for p in periods}, index=[fund_name, peer["name"]])
        df.insert(0, "Fee", [result.fund_ocf, peer.get("ocf")])
        result.comparison = df
        result.comparison_period = f"official figures to {analysis.as_of}" if analysis.as_of else "official figures"
        return_gap = df.iloc[0][label] - df.iloc[1][label]
        result.pillars.append(Pillar("Value for investors", _rate(return_gap * 100, 0.0, -0.50),
                                     f"Return after fees {fmt_pct(df.iloc[0][label])} vs peer {fmt_pct(df.iloc[1][label])} "
                                     f"({label}, official figures; gap {fmt_pct(return_gap, True)} a year)."))
        _fees(result, fund_name, peer, df.iloc[0]["Fee"], df.iloc[1]["Fee"], return_gap)
    elif peer is None or peer_levels is None or analysis.nav is None:
        reason = "No peer price data or reported peer returns." if peer else "No peer supplied."
        result.pillars += [Pillar("Value for investors", NOT_ASSESSED, reason), Pillar("Fees", NOT_ASSESSED, reason)]
    else:
        fund_levels = analysis.nav.set_index("date")["fund"]
        both = pd.concat({"fund": fund_levels, "peer": peer_levels}, axis=1).dropna()
        if len(both) < 13:
            reason = f"Only {len(both) - 1} months of overlapping fund and peer prices; at least 12 are needed."
            result.pillars += [Pillar("Value for investors", NOT_ASSESSED, reason), Pillar("Fees", NOT_ASSESSED, reason)]
        else:
            stats = {fund_name: _stats(both["fund"]), peer["name"]: _stats(both["peer"])}
            df = pd.DataFrame(stats).T
            df.insert(0, "Fee", [result.fund_ocf, peer.get("ocf")])
            result.comparison = df
            result.comparison_period = f"{both.index[0]:%b %Y} to {both.index[-1]:%b %Y}"
            f, p = df.iloc[0], df.iloc[1]
            sharpe_gap = f["Sharpe ratio"] - p["Sharpe ratio"]
            result.pillars.append(Pillar("Value for investors", _rate(sharpe_gap, 0.0, -0.10),
                                         f"Sharpe ratio {f['Sharpe ratio']:.2f} vs peer {p['Sharpe ratio']:.2f} "
                                         f"({result.comparison_period})."))
            _fees(result, fund_name, peer, f["Fee"], p["Fee"], f["Annualised return"] - p["Annualised return"])

    ratings = [p.rating for p in result.pillars]
    if sum(r in (GREEN, AMBER, RED) for r in ratings) < 2:
        result.verdict = "Incomplete data"
    elif RED in ratings:
        result.verdict = "Review"
    else:
        result.verdict = "Monitor" if any(r in (AMBER, NOT_ASSESSED, CHECK_DATA) for r in ratings) else "Retain"
    return result
