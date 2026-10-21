from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from file_parser import ParsedFiles, weights_table
from calculator import (performance_metrics, brinson_attribution, period_returns, status_rating, top_and_bottom,
                        rolling_12m_returns, calendar_year_returns, risk_measures, risk_indicator,
                        metrics_to_markdown, attribution_to_markdown, period_returns_to_markdown, fmt_pct)
from charts import growth_chart, drawdown_chart, attribution_chart, cumulative_chart, donut_chart
from extractor_agent import FactsheetExtract

AI_SOURCE = "AI-extracted from {docs}, please verify"


def merge_extract(parsed: ParsedFiles, extract: FactsheetExtract, doc_names: list[str]) -> None:
    """ Fill only the gaps the CSVs left, checking extracted weights before using them """
    source = AI_SOURCE.format(docs=", ".join(doc_names))
    if not parsed.fund_facts and extract.fund_facts:
        parsed.fund_facts = [(f.field, f.value) for f in extract.fund_facts]
        parsed.sources["fund_facts"] = source
        parsed.notes.append(f"Fund facts: {len(parsed.fund_facts)} items {source}")
    for attr in ("holdings", "sectors", "countries"):
        items = getattr(extract, attr)
        if getattr(parsed, attr) is not None or not items:
            continue
        if attr == "sectors" and parsed.attribution is not None:
            continue  # sector weights from the attribution file take priority
        df = pd.DataFrame([i.model_dump() for i in items])
        weights = df["fund_weight"]
        if weights.min() < 0 or weights.max() > 100 or weights.sum() > 105:
            parsed.notes.append(f"{attr.capitalize()}: extracted weights failed checks, not used")
            continue
        df["fund_weight"] = df["fund_weight"] / 100
        df["benchmark_weight"] = pd.to_numeric(df["benchmark_weight"], errors="coerce") / 100
        df["relative"] = df["fund_weight"] - df["benchmark_weight"]
        setattr(parsed, attr, df[["name", "fund_weight", "benchmark_weight", "relative"]])
        parsed.sources[attr] = source
        parsed.notes.append(f"{attr.capitalize()}: {len(df)} rows {source}")


def missing_factsheet_data(parsed: ParsedFiles) -> bool:
    no_sectors = parsed.sectors is None and parsed.attribution is None
    return not parsed.fund_facts or parsed.holdings is None or parsed.countries is None or no_sectors


def _sort_weights(df: pd.DataFrame) -> pd.DataFrame:
    """ Largest weight first, with any 'Other' bucket kept at the bottom """
    is_other = df["name"].astype(str).str.strip().str.lower().isin(["other", "others", "cash and other"])
    df = df.assign(_other=is_other).sort_values(["_other", "fund_weight"], ascending=[True, False])
    return df.drop(columns="_other").reset_index(drop=True)


@dataclass
class FundAnalysis:
    """ Numbers and charts calculated in Python, so the LLM never does arithmetic """
    parsed: ParsedFiles
    nav: pd.DataFrame | None = None
    metrics: pd.DataFrame | None = None
    periods: pd.DataFrame | None = None
    rolling: pd.DataFrame | None = None
    calendar: pd.DataFrame | None = None
    risk: pd.DataFrame | None = None
    risk_window: str = ""
    srri: int | None = None
    srri_source: str = ""
    attribution: pd.DataFrame | None = None
    sectors: pd.DataFrame | None = None
    charts: dict[str, str] = field(default_factory=dict)
    status: tuple[str, str, str] | None = None

    @classmethod
    def build(cls, parsed: ParsedFiles, out_dir: Path) -> "FundAnalysis":
        a = cls(parsed=parsed)
        if parsed.nav is not None and len(parsed.nav) >= 3:
            a.nav = parsed.nav
            a.metrics = performance_metrics(a.nav)
            a.periods = period_returns(a.nav)
            a.rolling = rolling_12m_returns(a.nav)
            a.calendar = calendar_year_returns(a.nav)
            a.risk, a.risk_window = risk_measures(a.nav)
            a.charts["cumulative"] = cumulative_chart(a.nav, str(out_dir / "cumulative.png"))
            a.charts["growth"] = growth_chart(a.nav, str(out_dir / "growth.png"))
            a.charts["drawdown"] = drawdown_chart(a.nav, str(out_dir / "drawdown.png"))
            a.status = status_rating(a.metrics.at["Excess return (annualised)", "Relative"])
        if parsed.attribution is not None:
            a.attribution = brinson_attribution(parsed.attribution)
            a.charts["attribution"] = attribution_chart(a.attribution, str(out_dir / "attribution.png"))
            if a.status is None:
                a.status = status_rating(a.attribution["Total"].iloc[-1])

        a.sectors = parsed.sectors
        if a.sectors is None and parsed.attribution is not None:
            # Attribution data already holds sector weights, so reuse them
            weights = parsed.attribution.rename(columns={"sector": "name"})[["name", "fund_weight", "benchmark_weight"]]
            a.sectors = weights_table(weights)
            parsed.sources["sectors"] = "attribution data"
        if a.sectors is not None:
            a.sectors = _sort_weights(a.sectors)
            a.charts["sectors"] = donut_chart(a.sectors, str(out_dir / "sectors.png"))
        if parsed.countries is not None:
            parsed.countries = _sort_weights(parsed.countries)
            a.charts["countries"] = donut_chart(parsed.countries, str(out_dir / "countries.png"))

        given = a.fact("risk indicator") or a.fact("srri") or a.fact("sri")
        if given and given.strip()[:1].isdigit() and 1 <= int(given.strip()[0]) <= 7:
            a.srri, a.srri_source = int(given.strip()[0]), "As stated in the fund documents."
        elif a.nav is not None:
            a.srri = risk_indicator(a.nav)
            a.srri_source = "Estimated from up to 5 years of fund volatility (SRRI bands), not an official rating."
        return a

    def fact(self, name: str) -> str | None:
        """ Look up a fund fact by name, ignoring case """
        return next((v for f, v in self.parsed.fund_facts if f.strip().lower() == name), None)

    @property
    def period_label(self) -> str:
        if self.nav is None:
            return "Period not given"
        return f"{self.nav['date'].iloc[0]:%d %b %Y} to {self.nav['date'].iloc[-1]:%d %b %Y}"

    @property
    def as_of(self) -> str:
        return f"{self.nav['date'].iloc[-1]:%d.%m.%Y}" if self.nav is not None else ""

    def facts_markdown(self) -> str:
        """ All calculated and supplied facts, for the planner and writer agents """
        parts = []
        if self.parsed.fund_facts:
            parts.append("### Fund facts\n\n" + "\n".join(f"- {f}: {v}" for f, v in self.parsed.fund_facts))
        if self.status:
            parts.append(f"Status (rule-based): {self.status[0]}. {self.status[2]}")
        if self.metrics is not None:
            parts.append(f"### Period: {self.period_label}")
            parts.append("### Returns by period\n\n" + period_returns_to_markdown(self.periods))
            parts.append("### Risk and return\n\n" + metrics_to_markdown(self.metrics))
            parts.append("### 12-month periods\n\n" + period_returns_to_markdown(self.rolling))
            if not self.calendar.empty:
                parts.append("### Calendar years\n\n" + period_returns_to_markdown(self.calendar))
        if self.attribution is not None:
            parts.append("### Attribution (Brinson-Fachler)\n\n" + attribution_to_markdown(self.attribution))
            top, bottom = top_and_bottom(self.attribution)
            parts.append("Top contributors: " + ", ".join(f"{r.Segment} ({fmt_pct(r.Total, True)})" for r in top.itertuples()))
            parts.append("Top detractors: " + ", ".join(f"{r.Segment} ({fmt_pct(r.Total, True)})" for r in bottom.itertuples()))
        for title, df in (("Top holdings", self.parsed.holdings), ("Sector exposure", self.sectors),
                          ("Country exposure", self.parsed.countries)):
            if df is not None:
                parts.append(f"### {title} (fund weight, relative to benchmark)\n\n" + "\n".join(
                    f"- {r.name}: {fmt_pct(r.fund_weight)} ({fmt_pct(r.relative, True)})" for r in df.head(10).itertuples()))
        return "\n\n".join(parts) or "No fund data was uploaded."

    def documents_text(self) -> str:
        return "\n\n".join(f"--- {name} ---\n{text}" for name, text in self.parsed.documents) or "None"
