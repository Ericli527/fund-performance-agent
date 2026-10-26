""" Oversight scoring: mandate, performance, value and fees, each rated Green / Amber / Red by fixed rules """
from dataclasses import dataclass, field
import os
import re
import numpy as np
import pandas as pd
from analysis import FundAnalysis
from calculator import fmt_pct

RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.0))
GREEN, AMBER, RED, NOT_ASSESSED = "Green", "Amber", "Red", "Not assessed"
FEE_HORIZON_YEARS = 5
FEE_EXAMPLE_AMOUNT = 10_000

# The rules, shown in the report so anyone can check how a rating was reached
RULES = [
    "Mandate (index fund): 1-year tracking difference within 0.30 pp = Green, within 0.75 pp = Amber, otherwise Red.",
    "Mandate (active fund): excess return over the longest period up to 5 years at least 0% a year = Green, "
    "at least -1% a year = Amber, otherwise Red.",
    "Performance (index fund): tracking error up to 1% = Green, up to 2% = Amber, otherwise Red.",
    "Performance (active fund): 1-year excess return at least 0% = Green, at least -3% = Amber, otherwise Red.",
    "Value: risk-adjusted return (Sharpe ratio) against the peer over the same months: at least equal = Green, "
    "within 0.10 = Amber, otherwise Red.",
    "Fees: fee no higher than the peer = Green; higher, but the fund's return after fees beat the peer's = Green "
    "(fee justified); higher and up to 1% a year behind = Amber; otherwise Red.",
    "Verdict: any Red = Review; any Amber = Monitor; otherwise Retain. If fewer than two questions could be assessed, "
    "the verdict is Incomplete data. A human must approve the verdict.",
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
    for name in ("ongoing charges", "ongoing charge", "ocf", "ongoing charges figure", "share class ongoing charges"):
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
    for label in ("5Y p.a.", "3Y p.a.", "Since start p.a.", "Since start", "1Y"):
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


def comparison_markdown(df: pd.DataFrame) -> str:
    lines = ["| | Fee (OCF) | Annualised return | 1-year return | Volatility | Sharpe |", "|---|---|---|---|---|---|"]
    for name, r in df.iterrows():
        fee = "n/a" if pd.isna(r["Fee"]) else fmt_pct(r["Fee"])
        lines.append(f"| {name} | {fee} | {fmt_pct(r['Annualised return'])} | {fmt_pct(r['1-year return'])} | "
                     f"{fmt_pct(r['Volatility'])} | {r['Sharpe ratio']:.2f} |")
    return "\n".join(lines)


def assess(analysis: FundAnalysis, fund_type: str, fund_name: str, peer: dict | None,
           peer_levels: pd.Series | None) -> OversightResult:
    """ Score the four oversight questions; fund_type is 'passive' or 'active' """
    result = OversightResult(fund_type=fund_type, fund_ocf=fund_ocf(analysis), peer=peer)
    passive = fund_type == "passive"

    # 1. Mandate: is the fund doing what it promised?
    if analysis.periods is None:
        result.pillars.append(Pillar("Mandate", NOT_ASSESSED, "No price data to test the objective."))
    elif passive:
        td = analysis.periods.at["Relative", "1Y"] if "1Y" in analysis.periods.columns else _longest_excess(analysis)[0]
        result.pillars.append(Pillar("Mandate", _rate(abs(td) * 100, 0.30, 0.75, higher_is_better=False),
                                     f"Objective is to track the index; 1-year tracking difference {fmt_pct(td, True)}."))
    else:
        excess, label = _longest_excess(analysis)
        result.pillars.append(Pillar("Mandate", _rate(excess * 100, 0.0, -1.0),
                                     f"Excess return vs benchmark {fmt_pct(excess, True)} ({label})."))

    # 2. Performance vs benchmark
    if analysis.periods is None:
        result.pillars.append(Pillar("Performance", NOT_ASSESSED, "No price data."))
    elif passive:
        te = analysis.metrics.at["Tracking error", "Relative"]
        result.pillars.append(Pillar("Performance", _rate(te * 100, 1.0, 2.0, higher_is_better=False),
                                     f"Tracking error {fmt_pct(te)} (full period)."))
    else:
        label = "1Y" if "1Y" in analysis.periods.columns else analysis.periods.columns[-1]
        excess = analysis.periods.at["Relative", label]
        result.pillars.append(Pillar("Performance", _rate(excess * 100, 0.0, -3.0),
                                     f"{label} return {fmt_pct(analysis.periods.at['Fund', label])} vs benchmark "
                                     f"{fmt_pct(analysis.periods.at['Benchmark', label])} ({fmt_pct(excess, True)})."))

    # 3 and 4. Value and fees, against the peer over the months both have prices
    if peer is None or peer_levels is None or analysis.nav is None:
        reason = "No peer price data." if peer else "No peer supplied."
        result.pillars += [Pillar("Value for investors", NOT_ASSESSED, reason), Pillar("Fees", NOT_ASSESSED, reason)]
    else:
        fund_levels = analysis.nav.set_index("date")["fund"]
        both = pd.concat({"fund": fund_levels, "peer": peer_levels}, axis=1).dropna()
        if len(both) < 13:
            result.pillars += [Pillar("Value for investors", NOT_ASSESSED, "Less than 12 months of overlapping prices."),
                               Pillar("Fees", NOT_ASSESSED, "Less than 12 months of overlapping prices.")]
        else:
            stats = {fund_name: _stats(both["fund"]), peer["name"]: _stats(both["peer"])}
            df = pd.DataFrame(stats).T
            df["Fee"] = [result.fund_ocf, peer.get("ocf")]
            result.comparison = df
            result.comparison_period = f"{both.index[0]:%b %Y} to {both.index[-1]:%b %Y}"
            f, p = df.iloc[0], df.iloc[1]

            sharpe_gap = f["Sharpe ratio"] - p["Sharpe ratio"]
            result.pillars.append(Pillar("Value for investors", _rate(sharpe_gap, 0.0, -0.10),
                                         f"Sharpe ratio {f['Sharpe ratio']:.2f} vs peer {p['Sharpe ratio']:.2f} "
                                         f"({result.comparison_period})."))

            return_gap = f["Annualised return"] - p["Annualised return"]
            if pd.isna(f["Fee"]) or pd.isna(p["Fee"]):
                result.pillars.append(Pillar("Fees", NOT_ASSESSED, "Fee missing for the fund or the peer."))
            else:
                for name, fee in ((fund_name, f["Fee"]), (peer["name"], p["Fee"])):
                    result.fee_costs[name] = FEE_EXAMPLE_AMOUNT * fee * FEE_HORIZON_YEARS
                if f["Fee"] <= p["Fee"]:
                    rating, why = GREEN, "no higher than the peer's"
                else:
                    result.fee_justified = return_gap >= 0
                    rating = GREEN if result.fee_justified else _rate(return_gap * 100, 0.0, -1.0)
                    why = ("higher than the peer's, but the fund's return after fees was higher, so the extra fee paid for itself"
                           if result.fee_justified else "higher than the peer's, and the fund's return after fees was lower")
                result.pillars.append(Pillar("Fees", rating, f"Fee {fmt_pct(f['Fee'])} vs peer {fmt_pct(p['Fee'])}: {why} "
                                                             f"(return gap {fmt_pct(return_gap, True)} a year)."))

    ratings = [p.rating for p in result.pillars]
    if len(ratings) - ratings.count(NOT_ASSESSED) < 2:
        result.verdict = "Incomplete data"
    else:
        result.verdict = "Review" if RED in ratings else "Monitor" if AMBER in ratings or NOT_ASSESSED in ratings else "Retain"
    return result
