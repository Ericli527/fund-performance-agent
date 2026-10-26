from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from file_parser import ParsedFiles, weights_table, performance_table
from calculator import (performance_metrics, brinson_attribution, period_returns, top_and_bottom,
                        metrics_to_markdown, attribution_to_markdown, period_returns_to_markdown, fmt_pct)
from charts import growth_chart, attribution_chart, calendar_chart
from extractor_agent import FactsheetExtract

AI_SOURCE = "AI-extracted from {docs}, please verify"


def merge_extract(parsed: ParsedFiles, extract: FactsheetExtract, doc_names: list[str]) -> None:
    """ Fill only the gaps the CSVs left, checking extracted weights before using them """
    source = AI_SOURCE.format(docs=", ".join(doc_names))
    if not parsed.fund_facts and extract.fund_facts:
        parsed.fund_facts = [(f.field, f.value) for f in extract.fund_facts]
        parsed.sources["fund_facts"] = source
        parsed.notes.append(f"Fund facts: {len(parsed.fund_facts)} items {source}")
    if parsed.performance is None and parsed.nav is None and extract.performance:
        df = performance_table(pd.DataFrame([i.model_dump() for i in extract.performance]))
        if df.empty or df.abs().max().max() > 10:  # a return above 1,000% is a misread
            parsed.notes.append("Performance: extracted figures failed checks, not used")
        else:
            parsed.performance = df
            parsed.performance_as_of = extract.performance_as_of
            parsed.sources["performance"] = source
            parsed.notes.append(f"Performance: {len(df)} periods {source}")
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
    calendar: pd.DataFrame | None = None
    official: bool = False
    attribution: pd.DataFrame | None = None
    sectors: pd.DataFrame | None = None
    charts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, parsed: ParsedFiles, out_dir: Path) -> "FundAnalysis":
        a = cls(parsed=parsed)
        if parsed.nav is not None and len(parsed.nav) >= 3:
            a.nav = parsed.nav
            a.metrics = performance_metrics(a.nav)
            a.periods = period_returns(a.nav)
            a.charts["growth"] = growth_chart(a.nav, str(out_dir / "growth.png"))
        if parsed.performance is not None:
            # The fund manager's reported figures take priority over returns calculated from downloaded prices
            perf = parsed.performance
            is_year = perf.index.str.fullmatch(r"\d{4}")
            if (~is_year).any():
                a.periods = cls._rows(perf[~is_year])
                a.official = True
            if is_year.any():
                a.calendar = cls._rows(perf[is_year].sort_index())
                a.charts["calendar"] = calendar_chart(a.calendar, str(out_dir / "calendar.png"))
        if parsed.attribution is not None:
            a.attribution = brinson_attribution(parsed.attribution)
            a.charts["attribution"] = attribution_chart(a.attribution, str(out_dir / "attribution.png"))
        a.sectors = parsed.sectors
        if a.sectors is None and parsed.attribution is not None:
            # Attribution data already holds sector weights, so reuse them
            weights = parsed.attribution.rename(columns={"sector": "name"})[["name", "fund_weight", "benchmark_weight"]]
            a.sectors = weights_table(weights)
        if a.sectors is not None:
            a.sectors = _sort_weights(a.sectors)
        return a

    @staticmethod
    def _rows(perf: pd.DataFrame) -> pd.DataFrame:
        """ Periods as columns with Fund, Benchmark and Relative rows, the same shape as calculated returns """
        df = perf[["fund", "benchmark"]].T.rename(index={"fund": "Fund", "benchmark": "Benchmark"})
        df.loc["Relative"] = df.loc["Fund"] - df.loc["Benchmark"]
        df.columns.name = None
        return df

    @property
    def as_of(self) -> str:
        """ Date the data runs to """
        if self.official and self.parsed.performance_as_of:
            return self.parsed.performance_as_of
        return f"{self.nav['date'].iloc[-1]:%d %b %Y}" if self.nav is not None else ""

    @property
    def data_label(self) -> str:
        """ What the performance figures are, for the report header """
        if self.official:
            return f"Official figures to {self.as_of}" if self.as_of else "Official figures"
        return self.period_label

    def fact(self, name: str) -> str | None:
        """ Look up a fund fact by name, ignoring case """
        return next((v for f, v in self.parsed.fund_facts if f.strip().lower() == name), None)

    @property
    def period_label(self) -> str:
        if self.nav is None:
            return "Period not given"
        return f"{self.nav['date'].iloc[0]:%d %b %Y} to {self.nav['date'].iloc[-1]:%d %b %Y}"

    @property
    def attribution_period(self) -> str:
        return self.parsed.attribution_period or "not stated in the data"

    def facts_markdown(self) -> str:
        """ All calculated and supplied facts, for the planner and analyst agents """
        parts = []
        if self.parsed.fund_facts:
            parts.append("### Fund facts\n\n" + "\n".join(f"- {f}: {v}" for f, v in self.parsed.fund_facts))
        if self.official:
            parts.append(f"### Official returns reported by the fund manager ({self.data_label}; "
                         "periods over 1 year are a year)\n\n" + period_returns_to_markdown(self.periods))
            if self.calendar is not None:
                parts.append("### Calendar-year returns (official)\n\n" + period_returns_to_markdown(self.calendar))
        if self.metrics is not None:
            parts.append(f"### Period of downloaded or uploaded prices: {self.period_label}")
            if not self.official:
                parts.append("### Returns by period\n\n" + period_returns_to_markdown(self.periods))
            parts.append(f"### Risk and return (full period, {self.period_label})\n\n" + metrics_to_markdown(self.metrics))
        if self.attribution is not None:
            parts.append(f"### Attribution (Brinson-Fachler), period: {self.attribution_period}\n\n"
                         + attribution_to_markdown(self.attribution))
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
