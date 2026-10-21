from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from file_parser import ParsedFiles
from calculator import (performance_metrics, brinson_attribution, period_returns, status_rating, top_and_bottom,
                        metrics_to_markdown, attribution_to_markdown, period_returns_to_markdown, fmt_pct)
from charts import growth_chart, drawdown_chart, attribution_chart


@dataclass
class FundAnalysis:
    """ Numbers and charts calculated in Python, so the LLM never does arithmetic """
    parsed: ParsedFiles
    nav: pd.DataFrame | None = None
    metrics: pd.DataFrame | None = None
    periods: pd.DataFrame | None = None
    attribution: pd.DataFrame | None = None
    charts: dict[str, str] = field(default_factory=dict)
    status: tuple[str, str, str] | None = None

    @classmethod
    def build(cls, parsed: ParsedFiles, out_dir: Path) -> "FundAnalysis":
        a = cls(parsed=parsed)
        if parsed.nav is not None and len(parsed.nav) >= 3:
            a.nav = parsed.nav
            a.metrics = performance_metrics(a.nav)
            a.periods = period_returns(a.nav)
            a.charts["growth"] = growth_chart(a.nav, str(out_dir / "growth.png"))
            a.charts["drawdown"] = drawdown_chart(a.nav, str(out_dir / "drawdown.png"))
            a.status = status_rating(a.metrics.at["Excess return (annualised)", "Relative"])
        if parsed.attribution is not None:
            a.attribution = brinson_attribution(parsed.attribution)
            a.charts["attribution"] = attribution_chart(a.attribution, str(out_dir / "attribution.png"))
            if a.status is None:
                a.status = status_rating(a.attribution["Total"].iloc[-1])
        return a

    @property
    def period_label(self) -> str:
        if self.nav is None:
            return "Period not given"
        return f"{self.nav['date'].iloc[0]:%d %b %Y} to {self.nav['date'].iloc[-1]:%d %b %Y}"

    def facts_markdown(self) -> str:
        """ All calculated facts, for the planner and writer agents """
        parts = []
        if self.status:
            parts.append(f"Status (rule-based): {self.status[0]}. {self.status[2]}")
        if self.metrics is not None:
            parts.append(f"### Period: {self.period_label}")
            parts.append("### Returns by period\n\n" + period_returns_to_markdown(self.periods))
            parts.append("### Risk and return\n\n" + metrics_to_markdown(self.metrics))
        if self.attribution is not None:
            parts.append("### Attribution (Brinson-Fachler)\n\n" + attribution_to_markdown(self.attribution))
            top, bottom = top_and_bottom(self.attribution)
            parts.append("Top contributors: " + ", ".join(f"{r.Segment} ({fmt_pct(r.Total, True)})" for r in top.itertuples()))
            parts.append("Top detractors: " + ", ".join(f"{r.Segment} ({fmt_pct(r.Total, True)})" for r in bottom.itertuples()))
        return "\n\n".join(parts) or "No NAV or attribution data was uploaded."

    def documents_text(self) -> str:
        return "\n\n".join(f"--- {name} ---\n{text}" for name, text in self.parsed.documents) or "None"
