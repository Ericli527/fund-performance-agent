from html import escape
import pandas as pd
from analysis import FundAnalysis
from charts import DONUT_COLOURS
from writer_agent import FundReport

NAVY, ACCENT, GREY, LIGHT = "#12355b", "#2e86ab", "#6b7785", "#f2f5f8"

# The first (unnamed) page template is the two-column factsheet; the review pages use "report"
FACTSHEET_CSS = f"""
@page {{
    size: a4 portrait;
    @frame fs_header_frame {{ -pdf-frame-content: fs_header; left: 0; top: 0; width: 21cm; height: 2.5cm; }}
    @frame left_frame {{ left: 1.2cm; width: 8.95cm; top: 2.9cm; height: 24.8cm; }}
    @frame right_frame {{ left: 10.85cm; width: 8.95cm; top: 2.9cm; height: 24.8cm; }}
    @frame fs_footer_frame {{ -pdf-frame-content: footer_content; left: 1.2cm; width: 18.6cm; bottom: 0.7cm; height: 0.8cm; }}
}}
#fs_header td {{ background-color: {NAVY}; color: white; padding: 0.55cm 1.2cm 0.3cm 1.2cm; }}
.fs-title {{ font-size: 16pt; font-weight: bold; }}
.fs-sub {{ font-size: 8.5pt; color: #c9d6e3; }}
.tab {{ background-color: {NAVY}; color: white; font-weight: bold; font-size: 8pt; padding: 4px 5px 1px 5px; margin: 7px 0 4px 0; -pdf-keep-with-next: true; }}
.fs {{ font-size: 7.2pt; line-height: 1.3; }}
.fs p {{ margin: 0 0 3px 0; }}
.fs li {{ margin-bottom: 1px; }}
.kv td {{ padding: 3px 2px 0px 2px; border-bottom: 0.3px solid #e3e7eb; font-size: 7pt; }}
.kv td.val {{ text-align: right; font-weight: bold; }}
.mini th {{ font-size: 6.4pt; color: {NAVY}; font-weight: bold; text-align: right; padding: 3px 2px 0px 2px; border-bottom: 0.8px solid {NAVY}; }}
.mini th.left, .mini td.left {{ text-align: left; }}
.mini td {{ font-size: 6.6pt; text-align: right; padding: 3px 2px 0px 2px; border-bottom: 0.3px solid #e3e7eb; }}
.risk td {{ text-align: center; font-weight: bold; font-size: 9pt; padding: 4px 0 1px 0; border: 0.6px solid {NAVY}; color: {NAVY}; }}
.risk td.on {{ background-color: {NAVY}; color: white; }}
.flag {{ font-size: 6.4pt; color: #b26a00; }}
.fs .small, .fs .flag {{ margin-top: 4px; }}
"""

FACT_ORDER = ["fund name", "share class", "isin", "benchmark", "asset class", "management approach", "launch date",
              "base currency", "fund size", "number of holdings", "ongoing charges", "domicile", "fund manager"]


def _tab(title: str) -> str:
    return f'<div class="tab">{escape(title)}</div>'


def _pct1(value) -> str:
    return "-" if pd.isna(value) else f"{round(value * 100, 1) + 0.0:.1f}"


def _source_note(analysis: FundAnalysis, key: str) -> str:
    source = analysis.parsed.sources.get(key, "")
    css = "flag" if "AI-extracted" in source else "small"
    return f'<p class="{css}">Source: {escape(source)}</p>' if source else ""


def _fund_facts(analysis: FundAnalysis) -> str:
    facts = list(analysis.parsed.fund_facts)
    facts.sort(key=lambda f: FACT_ORDER.index(f[0].lower()) if f[0].lower() in FACT_ORDER else len(FACT_ORDER))
    if analysis.nav is not None:
        facts.append(("Data period", analysis.period_label))
    if not facts:
        return '<p>No fund facts supplied.</p>'
    rows = "".join(f'<tr><td>{escape(f)}:</td><td class="val">{escape(v)}</td></tr>' for f, v in facts)
    return f'<table class="kv" cellspacing="0">{rows}</table>' + _source_note(analysis, "fund_facts")


def _returns_table(df: pd.DataFrame, two_row_header: bool) -> str:
    if df is None or df.empty:
        return "<p>Not enough NAV history for this table.</p>"
    if two_row_header:
        starts = "".join(f"<th>{escape(c.split(' - ')[0])}</th>" for c in df.columns)
        ends = "".join(f"<th>{escape(c.split(' - ')[1])}</th>" for c in df.columns)
        head = f'<tr><th class="left" width="16%">From</th>{starts}</tr><tr><th class="left">To</th>{ends}</tr>'
    else:
        head = '<tr><th class="left" width="16%"></th>' + "".join(f"<th>{escape(c)}</th>" for c in df.columns) + "</tr>"
    rows = "".join(f'<tr><td class="left">{name}</td>' + "".join(f"<td>{_pct1(v)}</td>" for v in row) + "</tr>"
                   for name, row in df.iterrows())
    return f'<table class="mini" cellspacing="0">{head}{rows}</table>'


def _risk_indicator(analysis: FundAnalysis) -> str:
    if analysis.srri is None:
        return "<p>Not available.</p>"
    cells = "".join(f'<td class="{"on" if i == analysis.srri else ""}">{i}</td>' for i in range(1, 8))
    return (f'<table class="mini" cellspacing="0"><tr><td class="left">Lower risk</td><td>Higher risk</td></tr></table>'
            f'<table class="risk" cellspacing="2"><tr>{cells}</tr></table><p class="small">{escape(analysis.srri_source)}</p>')


def _weights_block(analysis: FundAnalysis, df: pd.DataFrame | None, chart_key: str, source_key: str, label: str) -> str:
    if df is None:
        return f"<p>No {label.lower()} data supplied.</p>"
    rows = ""
    for i, r in enumerate(df.itertuples()):
        colour = DONUT_COLOURS[i % len(DONUT_COLOURS)]
        rows += (f'<tr><td style="background-color: {colour};"></td><td class="left">{escape(str(r.name))}</td>'
                 f'<td>{_pct1(r.fund_weight)}</td><td>{_pct1(r.benchmark_weight)}</td><td>{_pct1(r.relative)}</td></tr>')
    table = (f'<table class="mini" cellspacing="0"><tr><th width="4%"></th><th class="left" width="45%">{label}</th><th>Fund</th>'
             f'<th>Index</th><th>Relative</th></tr>{rows}</table>')
    chart = analysis.charts.get(chart_key)
    if chart:
        table = (f'<table cellspacing="0"><tr><td width="25%" valign="top"><img src="{chart}" style="width: 2.1cm;"/></td>'
                 f'<td valign="top">{table}</td></tr></table>')
    return table + _source_note(analysis, source_key)


def _holdings(analysis: FundAnalysis) -> str:
    df = analysis.parsed.holdings
    if df is None:
        return "<p>No holdings data supplied.</p>"
    rows = "".join(f'<tr><td class="left">{escape(str(r.name))}</td><td>{_pct1(r.fund_weight)}</td>'
                   f'<td>{_pct1(r.benchmark_weight)}</td><td>{_pct1(r.relative)}</td></tr>' for r in df.head(10).itertuples())
    total = df.head(10)["fund_weight"].sum()
    return (f'<table class="mini" cellspacing="0"><tr><th class="left" width="52%">Security</th><th>Fund</th><th>Index</th>'
            f'<th>Relative</th></tr>{rows}<tr><td class="left"><b>Top 10 total</b></td><td><b>{_pct1(total)}</b></td>'
            f'<td></td><td></td></tr></table>' + _source_note(analysis, "holdings"))


def _risk_measures(analysis: FundAnalysis) -> str:
    if analysis.risk is None:
        return "<p>Not available: no NAV data uploaded.</p>"
    rows = ""
    for name, r in analysis.risk.iterrows():
        fmt = _pct1 if "(%)" in name else (lambda v: "-" if pd.isna(v) else f"{v:.2f}")
        rows += f'<tr><td class="left">{escape(name)}</td><td>{fmt(r.Fund)}</td><td>{fmt(r.Benchmark)}</td></tr>'
    return (f'<table class="mini" cellspacing="0"><tr><th class="left" width="60%">Measure</th><th>Fund</th><th>Index</th></tr>'
            f'{rows}</table><p class="small">Calculated over {analysis.risk_window}. Definitions in the glossary.</p>')


def factsheet_names(report: FundReport, analysis: FundAnalysis) -> tuple[str, str]:
    """ Fund and benchmark names, preferring the supplied fund facts over the LLM's reading """
    return (analysis.fact("fund name") or report.fund_name, analysis.fact("benchmark") or report.benchmark_name)


def build_factsheet(report: FundReport, analysis: FundAnalysis) -> str:
    """ Two pages in two columns; <pdf:nextframe> moves to the next column """
    fund_name, benchmark = factsheet_names(report, analysis)
    header = (f'<div id="fs_header"><table cellspacing="0"><tr><td><span class="fs-title">{escape(fund_name)}</span><br/>'
              f'<span class="fs-sub">{analysis.as_of} Fund Factsheet &nbsp;|&nbsp; Benchmark: {escape(benchmark)}</span>'
              f'</td></tr></table></div>')
    features = "<ul>" + "".join(f"<li>{escape(f)}</li>" for f in report.product_features) + "</ul>"
    past_perf = ("Past performance is not a guide to future performance. Returns are calculated from the uploaded "
                 "NAV data and may differ from published figures.")

    page1_left = (_tab("Product features") + features + _tab("Fund facts") + _fund_facts(analysis)
                  + _tab("Benchmark description") + f"<p>{escape(report.benchmark_description)}</p>")
    page1_right = (_tab("Objective and investment policy") + f"<p>{escape(report.objective_and_policy)}</p>"
                   + f'<p class="small">{past_perf}</p>'
                   + _tab("Performance for 12-month periods (%)") + _returns_table(analysis.rolling, two_row_header=True)
                   + _tab("Performance for calendar years (%)") + _returns_table(analysis.calendar, two_row_header=False))
    if "cumulative" in analysis.charts:
        page1_right += (_tab("Cumulative performance (rebased to 100)")
                        + f'<img src="{analysis.charts["cumulative"]}" style="width: 8.9cm;"/>')
    page1_right += _tab("Risk indicator") + _risk_indicator(analysis)

    page2_left = (_tab("Top 10 holdings (%)") + _holdings(analysis)
                  + _tab("Sector exposure (%)") + _weights_block(analysis, analysis.sectors, "sectors", "sectors", "Sector"))
    page2_right = (_tab("Geographic exposure (%)")
                   + _weights_block(analysis, analysis.parsed.countries, "countries", "countries", "Country")
                   + _tab("Risk measures") + _risk_measures(analysis))
    return (header + f'<div class="fs">{page1_left}<pdf:nextframe />{page1_right}<pdf:nextpage />'
            f'{page2_left}<pdf:nextframe />{page2_right}</div>')
