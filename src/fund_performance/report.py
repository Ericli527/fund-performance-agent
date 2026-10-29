""" The PDF report (spec Section 9): 3 main pages and an appendix, 4 pages in total and 5 at most

Page 1 Summary (stands on its own), page 2 Mandate and performance, page 3 Value, fees and Assessment of
Value, then the appendix. Every figure shows its source; AI-extracted figures say "(please verify)". If the
report runs over 5 pages, the appendix is shortened first; a main page that overflows is an error.
"""
import base64
import re
from dataclasses import dataclass, field
import shutil
from datetime import date
from html import escape
from pathlib import Path
import matplotlib
import pandas as pd
from pypdf import PdfReader
from xhtml2pdf import pisa
from fund_performance import charts
from fund_performance.agents.analyst import Narrative
from fund_performance.config import Thresholds
from fund_performance.facts import TWO_DP
from fund_performance.glossary import used_in
from fund_performance.mandate import DecisionPath
from fund_performance.models import DataFlag, Figure, FundProfile, Peer
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import AMBER, CHECK_DATA, GREEN, MANUAL_CHECK, RED, Scorecard

MAX_PAGES = 5
PAGE_TITLES = ("Summary", "Mandate and performance", "Value, fees and Assessment of Value", "Appendix")
NAVY = "#1f3a5f"
RATING_COLOURS = {GREEN: "#2e7d32", AMBER: "#d18f00", RED: "#c62828", CHECK_DATA: "#6d4c9f", MANUAL_CHECK: "#546e7a"}
VERDICT_COLOURS = {"Retain": GREEN, "Monitor": AMBER, "Review": RED, "Pending": CHECK_DATA}
RATING_WORDS = {GREEN: "Green", AMBER: "Amber", RED: "Red", CHECK_DATA: "Check data", MANUAL_CHECK: "Manual check"}
SOURCE_WORDS = {"factsheet": "Factsheet", "calculated": "Calculated", "ai_extracted": "AI-extracted", "web": "Web"}
AOV_DISCLAIMER = ("This is an indicative assessment from public data. It does not replace the AFM's formal "
                  "Assessment of Value.")
KNOWN_LIMITATIONS = [
    "A web figure with no stated period is compared with all of the factsheet's periods for that series, so a "
    "wrong figure could pass by matching another period. Figures with a stated period are compared with that "
    "period only.",
    "Relevance checks match names and the ISIN in the summary text; a summary that names the fund another way "
    "(e.g. only by a ticker) is excluded.",
]
PUBLIC_DATA_NOTE = ("Public data only: this review uses published documents and public web sources. The AI service "
                    "used has data sharing on, so no confidential or client data is uploaded.")
DISCLAIMER = ("Draft for oversight review, prepared with AI assistance. All figures and ratings come from code using "
              "the sources listed; AI text is checked against them. Thresholds are illustrative. Not investment "
              "advice. The verdict is final only when signed by the reviewer.")
FONT = Path(matplotlib.get_data_path()) / "fonts" / "ttf"


class ReportLayoutError(RuntimeError):
    """ A main page ran over one page """


@dataclass
class ReportInputs:
    profile: FundProfile
    question: str
    reported: ReportedFigures
    card: Scorecard
    facts: dict
    narrative: Narrative
    thresholds: Thresholds
    flags: list[DataFlag] = field(default_factory=list)
    input_files: list[str] = field(default_factory=list)
    promises: list[str] = field(default_factory=list)
    peer: Peer | None = None
    prices: pd.DataFrame | None = None
    run_note: str | None = None             # e.g. "Offline run: AI steps skipped"
    prepared: date = field(default_factory=date.today)


# --- Figures ----------------------------------------------------------------------------------------------------

def fmt(name: str, fig: Figure | None) -> str:
    """ 1 d.p., or 2 d.p. for tracking error, tracking difference, alpha, beta, R² and the information ratio """
    if fig is None:
        return "–"
    two_dp = any(part in TWO_DP for part in name.split("."))
    text = fig.display(percent_decimals=2 if two_dp else 1, ratio_decimals=2).replace("-", "−")
    return text + (" (please verify)" if fig.source == "ai_extracted" else "")


def source_of(*figs: Figure | None) -> str:
    sources = sorted({SOURCE_WORDS.get(f.source, f.source) for f in figs if f is not None})
    return ", ".join(sources) or "–"


def _f(inp: ReportInputs, name: str) -> Figure | None:
    return inp.reported.figures.get(name)


def _chip(rating: str) -> str:
    colour = RATING_COLOURS.get(rating, "#777777")
    return f'<td class="chip" style="background-color:{colour}">{RATING_WORDS.get(rating, rating)}</td>'


def _verdict_colour(verdict: str) -> str:
    key = next((k for k in VERDICT_COLOURS if verdict.startswith(k)), "Monitor")
    return RATING_COLOURS[VERDICT_COLOURS[key]]


def _years(inp: ReportInputs) -> int:
    return inp.profile.time_horizon_years


# --- Plain-English one-line reasons for page 1 ---------------------------------------------------------------

def plain_reason(inp: ReportInputs, name: str) -> str:
    pillar = inp.card.pillars[name]
    n = _years(inp)
    if pillar.summary == "Add peer":
        what = "value for investors" if name.startswith("Value") else "the fee"
        return f"Add peer: no comparison fund was supplied, so {what} cannot be judged."
    if pillar.rating in (MANUAL_CHECK, CHECK_DATA):
        return pillar.reason.replace(f"{n}y", f"{n} years")
    if name == "Mandate" and inp.profile.objective_type == "index_tracker":
        r2 = _f(inp, f"relative.r2.{n}y") or _f(inp, "risk.pnav.r2.3y")
        beta = _f(inp, f"relative.beta.{n}y") or _f(inp, "risk.pnav.beta.3y")
        if r2 and beta:
            basis = f"{n} years, calculated" if _f(inp, f"relative.r2.{n}y") else "3 years, factsheet"
            moves = "Moves in line with its index" if pillar.rating == GREEN else "Does not move fully in line with its index"
            return f"{moves} (R² {fmt('x.r2', r2)}, beta {fmt('x.beta', beta)}; {basis})."
    if name == "Performance" and inp.profile.objective_type == "index_tracker":
        td = _f(inp, f"comparison.td.{n}y")
        te = _f(inp, f"relative.tracking_error.{n}y") or _f(inp, "risk.pnav.tracking_error.3y")
        if td is not None:
            side = "behind" if td.value < 0 else "ahead of"
            close = "Stays close to its index" if pillar.rating == GREEN else "Does not track its index closely enough"
            te_text = (f"; tracking error {fmt('x.tracking_error', te)} "
                       f"({f'{n} years, calculated' if _f(inp, f'relative.tracking_error.{n}y') else '3 years, factsheet'})"
                       if te else "")
            return (f"{close}: {side} it by {abs(td.exact):.2f}% a year over {n} years "
                    f"(tracking difference {fmt('comparison.td', td)}){te_text}.")
    return pillar.reason.replace(f"{n}y", f"{n} years").replace("fund_pnav", "PNAV").replace("fund_nav", "NAV")


# --- Pages ---------------------------------------------------------------------------------------------------------

def _page1(inp: ReportInputs) -> str:
    p, card = inp.profile, inp.card
    rows = "".join(
        f'<tr><td class="q"><b>{escape(name)}</b><br/><span class="small">{QUESTIONS[name]}</span></td>'
        f'{_chip(pillar.rating)}<td>{escape(plain_reason(inp, name))}</td></tr>'
        for name, pillar in card.pillars.items())
    findings = "".join(f"<li>{escape(t)}</li>" for t in inp.narrative.output.key_findings)
    actions = "".join(f"<li>{escape(t)}</li>" for t in inp.narrative.output.actions)
    origin = ("Written by AI and checked by code against the figures, ratings and wording rules."
              if inp.narrative.source == "ai" else
              "Written by code from the figures (template text)." + (f" {inp.run_note}." if inp.run_note else
                                                                    " The AI text did not pass its checks."))
    manual = "".join(f'<tr><td class="box">&nbsp;</td><td>Manual check done: {escape(m.name)}: {escape(m.reason)}</td></tr>'
                     for m in card.manual_checks)
    return f"""
<table class="banner"><tr><td>
  <span class="kicker">FUND PERFORMANCE REVIEW · DRAFT FOR OVERSIGHT</span><br/>
  <span class="fund">{escape(p.fund_name)}</span><br/>
  <span class="meta">ISIN {escape(p.isin)} · {escape(p.share_class)} · {escape(p.currency)} · Benchmark: {escape(p.benchmark_name)}</span>
</td></tr></table>
<h1>Summary</h1>
<table class="facts">
<tr><td class="label">Question</td><td>{escape(inp.question)}</td></tr>
<tr><td class="label">Review date</td><td>Figures to {p.as_of_date:%d %B %Y} · prepared {inp.prepared:%d %B %Y}</td></tr>
</table>
<table class="verdict"><tr><td class="vlabel" style="background-color:{_verdict_colour(card.verdict)}">Draft verdict</td>
<td class="vtext"><b>{escape(card.verdict)}</b><br/><span class="small">Ratings and verdict decided by fixed rules; final only when signed below.</span></td></tr></table>
<h2>The four oversight questions</h2>
<table class="grid ratings"><tr><th width="27%">Question</th><th width="13%">Rating</th><th>Why</th></tr>{rows}</table>
<h2>Key findings</h2><ul>{findings}</ul>
<h2>Recommended actions</h2><ul>{actions}</ul>
<p class="small">{escape(origin)}</p>
<h2>Approval</h2>
<table class="approval">
<tr><td width="18%">Reviewer name</td><td class="line">&nbsp;</td><td width="10%">Date</td><td class="line" width="22%">&nbsp;</td></tr>
<tr><td>Decision</td><td colspan="3"><table class="ticks"><tr><td class="box">&nbsp;</td><td>Retain</td><td class="box">&nbsp;</td><td>Monitor</td><td class="box">&nbsp;</td><td>Review</td></tr></table></td></tr>
<tr><td>Signature</td><td class="line" colspan="3">&nbsp;</td></tr>
</table>
{f'<table class="ticks">{manual}</table>' if manual else ''}
"""


QUESTIONS = {"Mandate": "Is the fund doing what it promised?", "Performance": "How did it do against its index?",
             "Value for investors": "Did investors get a fair outcome?", "Fees": "Is the fee justified?"}


def _returns_table(inp: ReportInputs) -> str:
    cols = [("1 year", "cum.1y"), ("3 years", "cum.3y"), ("5 years", "cum.5y"),
            ("3 years, a year", "ann.3y"), ("5 years, a year", "ann.5y")]
    rows = ""
    for label, series in (("Fund, noon price (NAV)", "fund_nav"), ("Fund, market-close price (PNAV)", "fund_pnav"),
                          ("Index", "index")):
        figs = [_f(inp, f"{series}.{c}") for _, c in cols]
        if any(figs):
            rows += (f"<tr><td class='l'>{label}</td>" + "".join(f"<td>{fmt(series, f)}</td>" for f in figs)
                     + f"<td class='src'>{source_of(*figs)}</td></tr>")
    basis = next((f.basis for k, f in inp.reported.figures.items() if k.startswith("comparison.td")), None)
    gap = [_f(inp, f"comparison.excess_cum.{c[-2:]}") if c.startswith("cum") else _f(inp, f"comparison.td.{c[-2:]}")
           for _, c in cols]
    if any(gap):
        who = "PNAV" if basis == "fund_pnav" else "NAV"
        rows += (f"<tr class='total'><td class='l'>Gap to index ({who} vs index, pp)</td>"
                 + "".join(f"<td>{fmt('comparison.td' if i >= 3 else 'comparison.excess_cum', g)}</td>"
                           for i, g in enumerate(gap)) + "<td class='src'>Calculated from the factsheet</td></tr>")
    head = "".join(f"<th>{c}</th>" for c, _ in cols)
    return (f"<table class='grid num'><tr><th class='l' width='31%'>Return</th>{head}<th width='14%'>Source</th></tr>"
            f"{rows}</table><p class='small'>Cumulative gaps to 1 d.p., yearly gaps to 2 d.p.</p>")


def _calendar_table(inp: ReportInputs) -> str:
    years = sorted({k.rsplit(".", 1)[1] for k in inp.reported.figures if ".calendar." in k and k[-1].isdigit()})[-10:]
    if not years:
        return "<p>No calendar-year figures.</p>"
    rows = ""
    for label, series in (("Fund (NAV)", "fund_nav"), ("Fund (PNAV)", "fund_pnav"), ("Index", "index")):
        figs = [_f(inp, f"{series}.calendar.{y}") for y in years]
        if any(figs):
            rows += (f"<tr><td class='l'>{label}</td>" + "".join(f"<td>{fmt(series, f)}</td>" for f in figs)
                     + f"<td class='src'>{source_of(*figs)}</td></tr>")
    return ("<table class='grid num tiny'><tr><th class='l' width='13%'>Calendar year</th>"
            + "".join(f"<th>{y}</th>" for y in years) + f"<th>Source</th></tr>{rows}</table>")


PRICE_WORDS = {"pnav": "market-close price (PNAV)", "nav": "noon price (NAV)"}


def _risk_groups(inp: ReportInputs) -> list[tuple[str, list[tuple[str, str, str | None]]]]:
    """ Risk rows grouped by period and price basis; each group's source is read from its figures """
    n = _years(inp)
    groups = [(f"3 years, {PRICE_WORDS[b]}", [
        ("Volatility, a year", f"risk.{b}.fund_vol.3y", f"risk.{b}.index_vol.3y"),
        ("Tracking error", f"risk.{b}.tracking_error.3y", None),
        ("Beta", f"risk.{b}.beta.3y", None),
        ("R²", f"risk.{b}.r2.3y", None),
        ("Sharpe ratio", f"risk.{b}.sharpe_fund.3y", f"risk.{b}.sharpe_index.3y"),
        ("Information ratio", f"risk.{b}.info_ratio.3y", None),
        ("Alpha, a year", f"risk.{b}.alpha.3y", None),
    ]) for b in ("pnav", "nav")]
    groups.append((f"{n} years, {PRICE_WORDS['nav']}", [
        ("Tracking error", f"relative.tracking_error.{n}y", None),
        ("Volatility, a year", f"fund_nav.vol.{n}y", f"index.vol.{n}y"),
        ("Largest fall from a peak", f"fund_nav.mdd.{n}y", f"index.mdd.{n}y"),
    ]))
    return [(title, [r for r in rows if _f(inp, r[1]) is not None]) for title, rows in groups]


def _risk_table(inp: ReportInputs) -> str:
    """ One subheading per source, period and price basis, so no measure appears without its context. The
    calculated Sharpe ratio (risk-free rate 0) is in the appendix, as it is not comparable """
    def table(groups) -> str:
        body = ""
        for title, rows in groups:
            figs = [_f(inp, name) for _, f_name, i_name in rows for name in (f_name, i_name) if name]
            body += f"<tr><td class='sub' colspan='3'>{source_of(*figs)} · {title}</td></tr>"
            for label, fund_name, index_name in rows:
                index = _f(inp, index_name) if index_name else None
                body += (f"<tr><td class='l'>{label}</td><td>{fmt(fund_name, _f(inp, fund_name))}</td>"
                         f"<td>{fmt(index_name, index) if index else '–'}</td></tr>")
        return ("<table class='grid num tiny'><tr><th class='l' width='54%'>Risk measure</th><th>Fund</th>"
                f"<th>Index</th></tr>{body}</table>")
    groups = [g for g in _risk_groups(inp) if g[1]]
    if len(groups) < 2:
        return table(groups) if groups else "<p class='small'>No risk figures.</p>"
    # The first group on the left, the rest on the right, so the table takes half the height
    return (f"<table width='100%'><tr><td width='49%' valign='top'>{table(groups[:1])}</td><td width='2%'></td>"
            f"<td width='49%' valign='top'>{table(groups[1:])}</td></tr></table>")


def _chart_images(inp: ReportInputs, out_dir: Path) -> tuple[Path | None, Path | None, str]:
    """ Growth of 100 and yearly returns, fund vs index. With an index price series, growth is monthly from
    prices; otherwise it is built from the factsheet's calendar-year returns """
    out_dir.mkdir(parents=True, exist_ok=True)
    figs = inp.reported.figures
    basis = next((f.basis for k, f in figs.items() if k.startswith("comparison.td")), None) or "fund_nav"
    fund_label = "Fund (PNAV)" if basis == "fund_pnav" else "Fund (NAV)"
    growth = yearly = None
    caption = ""
    if inp.prices is not None and "index_level" in inp.prices.columns:
        p = inp.prices.dropna(subset=["nav", "index_level"])
        p = p[p["date"] >= p["date"].iloc[-1] - pd.DateOffset(years=_years(inp))]
        growth = charts.growth_chart([f"{d:%b %y}" for d in p["date"]], list(p["nav"] / p["nav"].iloc[0] * 100),
                                     list(p["index_level"] / p["index_level"].iloc[0] * 100), out_dir / "growth.png",
                                     "Fund (NAV)", "Index", f"Growth of 100 over {_years(inp)} years")
        caption = "Growth of 100: monthly prices from the price file (calculated)."
    else:
        years = sorted({k.rsplit(".", 1)[1] for k in figs if k.startswith(f"{basis}.calendar.") and k[-1].isdigit()}
                       & {k.rsplit(".", 1)[1] for k in figs if k.startswith("index.calendar.") and k[-1].isdigit()})[-10:]
        if years:
            fund = charts.rebase([figs[f"{basis}.calendar.{y}"].exact for y in years])
            index = charts.rebase([figs[f"index.calendar.{y}"].exact for y in years])
            labels = [str(int(years[0]) - 1)] + years
            growth = charts.growth_chart(labels, fund, index, out_dir / "growth.png", fund_label, "Index",
                                         "Growth of 100, calendar years")
            caption = (f"Growth of 100 from the factsheet's calendar-year returns ({fund_label} vs index, end "
                       f"{labels[0]} = 100); the price file has no index series.")
    ends = sorted({k.rsplit(".", 1)[1] for k in figs if k.startswith(f"{basis}.discrete_12m.")}
                  & {k.rsplit(".", 1)[1] for k in figs if k.startswith("index.discrete_12m.")})
    if ends:
        yearly = charts.yearly_returns_chart(
            [f"to {e[5:7]}/{e[2:4]}" for e in ends], [figs[f"{basis}.discrete_12m.{e}"].exact for e in ends],
            [figs[f"index.discrete_12m.{e}"].exact for e in ends], out_dir / "yearly.png", fund_label, "Index",
            "12-month returns (%)")
        caption += f" 12-month returns: {source_of(*[figs[f'{basis}.discrete_12m.{e}'] for e in ends])}."
    return growth, yearly, caption


def _img(path: Path | None) -> str:
    if path is None:
        return "<p class='small'>Not enough data for this chart.</p>"
    return f'<img src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}" width="245"/>'


OBJECTIVE_WORDS = {
    "index_tracker": ("Index fund", "how closely it tracks its index: the yearly gap (tracking difference), the gap "
                                    "after the fee, how much the gap varies (tracking error) and how closely they move "
                                    "together (R²)"),
    "active_target": ("Active fund with a return target", "its yearly return above the target over the main period"),
    "active_comparator": ("Active fund compared with similar funds",
                          "its ranking among similar funds (quartile) and its return above the comparator"),
    "active_constraint": ("Active fund with a benchmark limit",
                          "its return above the benchmark and whether it stays within its limits"),
    "income_target": ("Income fund", "its income (yield) against its target and whether it keeps its capital"),
    "absolute_return": ("Absolute return fund", "its return against its stated target and its largest fall"),
}


def plain_path(path: DecisionPath) -> list[str]:
    """ The decision path in plain words, built from its answers (no code names) """
    kind, judged = OBJECTIVE_WORDS.get(path.objective_type, (path.objective_type, "its objective"))
    steps = [f"{kind}, so it is judged on {judged}."]
    if path.secondary_objective:
        second = OBJECTIVE_WORDS.get(path.secondary_objective)
        steps.append(f"Two objectives: the second is judged as an {second[0].lower()}. Each is rated separately; "
                     "Performance takes the weaker rating." if second else
                     f"Two objectives: the second ({path.secondary_objective}) is not a known type, so code cannot rate it.")
    else:
        steps.append("One objective only.")
    steps.append("Track record shorter than the main test period: since-launch figures are used, and Performance "
                 "is at least Amber, never Red on history alone." if path.short_history else
                 "Track record long enough for the main test period.")
    steps.append(f"Main test period: {path.main_period_years} years; 1 and 3 years are shown as the trend.")
    steps.append("Data checks: " + ("; ".join(f.message for f in path.blocking) + ", so the ratings wait for a data check."
                                    if path.blocking else "nothing blocks the ratings."))
    return steps


NOTE_SOURCES = {"fee": "Source: factsheet returns, ongoing charge from the fund profile; gaps calculated.",
                "pricing": "Source: factsheet; gaps calculated.", "timing": "Source: factsheet; gaps calculated."}
_PERIOD = re.compile(r"^(\d+)y$")


def note_source_line(note: dict) -> str:
    """ A data note's figures and source in one short line, e.g. "5 years: Fund noon price 88.3% · Index 91.6% ·
    ... Source: factsheet; gaps calculated." (the plain-terms repeats are left out) """
    shown = [f for f in note["figures"] if "in plain terms" not in f["label"]]
    periods = {m.group(1) for f in shown for m in [_PERIOD.match(f["label"].rsplit(", ", 1)[-1])] if m}
    parts = []
    for f in shown:
        name = re.sub(r"\s*\([^)]*\)", "", f["label"].split(", ")[0])
        yearly = " a year" if ", a year" in f["label"] else ""
        parts.append(f"{name} {f['display'].replace('-', '−')}{yearly}")
    prefix = f"{periods.pop()} years: " if len(periods) == 1 else ""
    return f"{prefix}{' · '.join(parts)}. {NOTE_SOURCES.get(note.get('kind'), 'Source: factsheet.')}"


def plain_note(note: dict) -> str:
    """ A data note's sentences for the report. The fee note is reworded in plain terms from its own figures
    (facts.json and the Analyst keep the original wording) """
    if note.get("kind") != "fee":
        return note["note"]
    fig = {f["label"].split(",")[0]: f["value"] for f in note["figures"]}
    ocf, ex_cost = fig.get("Ongoing charge (OCF)"), fig.get("Cost-adjusted gap")
    most = note["note"].startswith("Most")
    first = "Most of the yearly gap is the fee." if most else "The fee explains only part of the yearly gap."
    if ocf is None or ex_cost is None:
        return first
    if ex_cost == 0:
        where = "would match its index"
    else:
        where = (f"would be {'only ' if most else ''}{abs(ex_cost):.2f}% a year "
                 f"{'behind' if ex_cost < 0 else 'ahead of'} its index")
    return f"{first} Without the {ocf:.2f}% yearly fee, the fund {where}."


def _page2(inp: ReportInputs, out_dir: Path) -> str:
    path = "".join(f"<li>{escape(step)}</li>" for step in plain_path(inp.card.path))
    promises = ("".join(f"<li>{escape(x)}</li>" for x in inp.promises) if inp.promises
                else "<li>Not read: the Mandate Agent was not run.</li>")
    notes = "".join(f"<li>{escape(plain_note(n))}<br/><span class='small'>{escape(note_source_line(n))}</span></li>"
                    for n in inp.facts.get("data_notes", []))
    growth, yearly, caption = _chart_images(inp, out_dir)
    return f"""
<h1>Mandate and performance</h1>
<table class="facts"><tr><td class="label">Objective</td><td>{escape(inp.profile.objective_text)}</td></tr></table>
<table width="100%"><tr><td width="50%" valign="top"><h3>What the fund promises</h3><ul class="tight">{promises}</ul></td>
<td valign="top"><h3>How it was judged (decision path)</h3><ol class="tight small">{path}</ol></td></tr></table>
<h3>Returns to {inp.profile.as_of_date:%d %b %Y}</h3>{_returns_table(inp)}
<h3>Calendar-year returns</h3>{_calendar_table(inp)}
<h3>Risk</h3>{_risk_table(inp)}
<h3>Below the surface</h3><ul class="tight">{notes or '<li>No data notes.</li>'}</ul>
<table width="100%"><tr><td align="center">{_img(growth)}</td><td align="center">{_img(yearly)}</td></tr></table>
<p class="small">{escape(caption)}</p>
"""


def _aov_rows(inp: ReportInputs) -> list[tuple[str, str, str]]:
    p, pillars = inp.profile, inp.card.pillars
    tx = ("transaction costs: not disclosed in the documents provided" if p.transaction_cost_pct is None
          else f"transaction costs {p.transaction_cost_pct:.2f}%")
    fee = "performance fee: yes" if p.performance_fee else "no performance fee"
    size = f"fund size £{p.fund_size_gbp_m:,.0f}m" if p.fund_size_gbp_m else "fund size not given"
    fees = pillars["Fees"]
    return [
        ("1. Quality of service", "Not public: requires internal data.", "Not assessed"),
        ("2. Performance", f"Mandate {RATING_WORDS[pillars['Mandate'].rating]}, Performance "
                           f"{RATING_WORDS[pillars['Performance'].rating]} (page 2).", "Covered"),
        ("3. AFM costs", f"Ongoing charge (OCF) {p.ocf_pct:.2f}%; {tx}; {fee}.",
         "Partly" if p.transaction_cost_pct is None else "Covered"),
        ("4. Economies of scale", f"{size.capitalize()}; requires OCF history.", "Partly"),
        ("5. Comparable market rates", "No peer supplied." if fees.summary == "Add peer"
         else f"Fees {RATING_WORDS[fees.rating]}: {plain_reason(inp, 'Fees')}",
         "Not assessed" if fees.summary == "Add peer" else "Covered"),
        ("6. Comparable services", "Requires internal data (other mandates of the same manager).", "Not assessed"),
        ("7. Classes of units", "Requires share class data.", "Not assessed"),
    ]


STATUS_COLOURS = {"Covered": RATING_COLOURS[GREEN], "Partly": RATING_COLOURS[AMBER], "Not assessed": "#8a96a3"}


def _page3(inp: ReportInputs) -> str:
    p, n = inp.profile, _years(inp)
    if inp.peer is None:
        peer = ("<table class='callout'><tr><td><b>Add peer.</b> No comparison fund was supplied, so value for investors "
                "and the fee cannot be judged. Add a comparable fund (name, ongoing charge and 1, 3 and 5-year returns) "
                "to complete these two questions.</td></tr></table>")
    else:
        fund_ann = _f(inp, f"fund_nav.ann.{n}y")
        peer_ret = getattr(inp.peer.returns, f"y{n}")
        peer = (f"<table class='grid num'><tr><th class='l'>Fund</th><th>Ongoing charge</th><th>{n} years, a year</th>"
                f"<th>Source</th></tr><tr><td class='l'>{escape(p.fund_name)}</td><td>{p.ocf_pct:.2f}%</td>"
                f"<td>{fmt('x', fund_ann)}</td><td class='src'>Profile, {source_of(fund_ann)}</td></tr>"
                f"<tr><td class='l'>{escape(inp.peer.name)}</td><td>{inp.peer.ocf_pct:.2f}%</td>"
                f"<td>{'–' if peer_ret is None else f'{peer_ret:.1f}%'}</td><td class='src'>Peer file</td></tr></table>")
    fees = (f"<table class='grid'><tr><th class='l'>Charge</th><th class='l'>This fund</th><th class='l'>Source</th></tr>"
            f"<tr><td class='l'>Ongoing charge (OCF)</td><td class='l'>{p.ocf_pct:.2f}% a year</td><td class='l src'>Factsheet / KID (profile)</td></tr>"
            f"<tr><td class='l'>Transaction costs</td><td class='l'>"
            f"{'Not disclosed in the documents provided' if p.transaction_cost_pct is None else f'{p.transaction_cost_pct:.2f}%'}"
            f"</td><td class='l src'>Profile</td></tr>"
            f"<tr><td class='l'>Performance fee</td><td class='l'>{'Yes' if p.performance_fee else 'None'}</td>"
            f"<td class='l src'>KID (profile)</td></tr></table>")
    aov = "".join(f"<tr><td class='l'><b>{a}</b></td><td class='l'>{escape(b)}</td>"
                  f"<td class='chip' style='background-color:{STATUS_COLOURS[c]}'>{c}</td></tr>" for a, b, c in _aov_rows(inp))
    context = inp.narrative.output.market_context
    market = (f"<p>{escape(context)}</p><p class='small'>Sources [n] are listed in the appendix.</p>" if context else
              "<p class='small'>No market context: " + ("the AI steps were not run." if inp.run_note else
                                                       "no web source passed the date, relevance and figure checks.")
              + "</p>")
    return f"""
<h1>Value, fees and Assessment of Value</h1>
<h3>Comparison with a peer fund</h3>{peer}
<h3>Fees</h3>{fees}
<h3>Assessment of Value: the 7 FCA factors (COLL 6.6.20R)</h3>
<table class="grid"><tr><th class="l" width="27%">Factor</th><th class="l">What this review found</th><th width="15%">Status</th></tr>{aov}</table>
<p class="small"><b>{AOV_DISCLAIMER}</b></p>
<h3>Market context</h3>{market}
"""


def _threshold_lines(t: Thresholds) -> list[str]:
    m, pi, pa, v, f, d = t.mandate_index, t.performance_index, t.performance_active_target, t.value, t.fees_index, t.data_checks
    return [
        f"Mandate (index fund): Green if R² at least {m.green_min_r2} and beta {m.green_beta_range[0]}–{m.green_beta_range[1]}; "
        f"Amber if R² at least {m.amber_min_r2} and beta {m.amber_beta_range[0]}–{m.amber_beta_range[1]}; else Red.",
        f"Performance (index fund): tracking difference Green within OCF + {pi.green_td_margin_over_ocf_pp:.2f} pp, Amber "
        f"within OCF + {pi.amber_td_margin_over_ocf_pp:.2f} pp; tracking error Green up to {pi.green_max_te_pct:.2f}%, "
        f"Amber up to {pi.amber_max_te_pct:.2f}%; the weaker of the two counts.",
        f"Performance (active, target): Green if excess return at least {pa.green_min_excess_pct:.1f}% a year and hit "
        f"rate at least {pa.min_hit_rate} of {pa.hit_rate_windows}; Red below {pa.red_below_excess_pct:.1f}%.",
        f"Value: Green if the peer did better by at most {v.green_max_peer_outperformance_pp:.2f} pp a year, Amber up to "
        f"{v.amber_max_peer_outperformance_pp:.2f} pp; no peer = Amber (Add peer).",
        f"Fees (index fund): Green if the fee is at most {f.green_max_ocf_over_peer_pp:.2f} pp above the peer's, Amber up "
        f"to {f.amber_max_ocf_over_peer_pp:.2f} pp.",
        f"Data checks: calculated vs factsheet returns within {d.cross_check_tolerance_pp} pp; index fund on prices only "
        f"with a gap over {d.implausible_tracker_gap_pct}% a year = Check data; web figures within 0.5 pp of the factsheet.",
        "Verdict: any Red = Review; any Amber = Monitor; Check data on Mandate or Performance = Pending data check.",
    ]


def _calculated_sharpe(inp: ReportInputs) -> str:
    n = _years(inp)
    fund, index = _f(inp, f"fund_nav.sharpe.{n}y"), _f(inp, f"index.sharpe.{n}y")
    if fund is None:
        return ""
    index_text = f", index {fmt('x', index)}" if index else ""
    return (f"<h3>Calculated Sharpe ratio</h3><p class='small'>Fund {fmt('x', fund)}{index_text} "
            f"({n} years, noon price (NAV), calculated from prices with a risk-free rate of 0). It is not "
            f"comparable with the factsheet Sharpe ratio on page 2, which uses its own risk-free rate and period.</p>")


def plain_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _appendix(inp: ReportInputs, compact: bool, main_text: str = "") -> str:
    flags = list({(f.level, f.message): f for f in inp.flags}.values())
    excluded = [f for f in flags if f.check == "research" and "excluded" in f.message]
    checks = [f for f in flags if f not in excluded]
    by_level = ""
    for level, title in (("blocking", "Blocking (Check data)"), ("warning", "Warnings"), ("info", "For the record")):
        items = [f for f in checks if f.level == level]
        more = len(items) - 6 if compact and level == "info" else 0
        if more > 0:
            items = items[:6]
        if items:
            by_level += (f"<p class='small'><b>{title}</b></p><ul class='tight small'>"
                         + "".join(f"<li>{escape(f.message)}</li>" for f in items)
                         + (f"<li>… and {more} more (full list in run_log.txt)</li>" if more > 0 else "") + "</ul>")
    sources = "".join(f"<li>Input file: {escape(x)}</li>" for x in inp.input_files)
    sources += "".join(
        f"<li>[{s['number']}] {escape(s['query'])} · {'as at' if s.get('date_basis') == 'as_at' else 'published'} "
        f"{s['date']} · {escape(s['url'])}</li>" for s in inp.narrative.sources)
    excl = ("".join(f"<li>{escape(f.message)}</li>" for f in excluded) or "<li>None.</li>")
    thresholds = "".join(f"<li>{escape(line)}</li>" for line in _threshold_lines(inp.thresholds)[: 4 if compact else None])
    limits = "".join(f"<li>{escape(x)}</li>" for x in KNOWN_LIMITATIONS)
    sharpe = _calculated_sharpe(inp)
    rest = f"{by_level}{excl}{sources}{sharpe}{thresholds}{limits}{PUBLIC_DATA_NOTE}{DISCLAIMER}"
    glossary = "".join(f"<li><b>{escape(term)}</b>: {escape(text)}</li>"
                       for term, text in used_in(main_text + plain_text(rest)).items())
    return f"""
<h1>Appendix</h1>
<h3>Data checks and flags</h3>{by_level or '<p class="small">No flags.</p>'}
<h3>Excluded web sources</h3><ul class="tight small">{excl}</ul>
<h3>Sources</h3><ul class="tight small">{sources}</ul>
{sharpe}<h3>Thresholds used (illustrative, to be agreed with the oversight team)</h3><ul class="tight small">{thresholds}</ul>
<h3>Glossary (terms used in this report)</h3><ul class="tight small">{glossary}</ul>
<h3>Known limitations</h3><ul class="tight small">{limits}</ul>
<p class="small"><b>{PUBLIC_DATA_NOTE}</b></p>
<p class="small">{DISCLAIMER}</p>
"""


CSS = f"""
@font-face {{ font-family: DejaVu; src: url("fonts/DejaVuSans.ttf"); }}
@font-face {{ font-family: DejaVu; src: url("fonts/DejaVuSans-Bold.ttf"); font-weight: bold; }}
@page {{ size: a4 portrait; margin: 1.3cm 1.5cm 1.7cm 1.5cm;
  @frame footer {{ -pdf-frame-content: footer; left: 1.5cm; width: 18cm; bottom: 0.6cm; height: 0.8cm; }} }}
body {{ font-family: DejaVu; font-size: 8.2pt; line-height: 1.3; color: #1d2733; }}
h1 {{ font-size: 13pt; color: {NAVY}; border-bottom: 1.5px solid {NAVY}; padding-bottom: 2px; margin: 4px 0 6px 0; }}
h2 {{ font-size: 10pt; color: {NAVY}; margin: 8px 0 3px 0; }}
h3 {{ font-size: 9pt; color: {NAVY}; margin: 7px 0 3px 0; }}
p {{ margin: 0 0 3px 0; }} ul, ol {{ margin: 0 0 3px 0; }} li {{ margin-bottom: 1px; }}
.small {{ font-size: 7pt; color: #4c5966; }}
.banner td {{ background-color: {NAVY}; color: white; padding: 7px 9px; }}
.kicker {{ font-size: 6.8pt; color: #b9cbe0; }} .fund {{ font-size: 14pt; font-weight: bold; }} .meta {{ font-size: 7.5pt; color: #dce6f1; }}
.facts td {{ padding: 2px 4px; vertical-align: top; }} .facts .label {{ width: 18%; color: #4c5966; font-weight: bold; }}
.verdict td {{ padding: 6px 8px; }} .vlabel {{ width: 22%; color: white; font-weight: bold; font-size: 10pt; text-align: center; }}
.vtext {{ background-color: #f1f4f8; font-size: 10pt; }}
.grid th {{ background-color: {NAVY}; color: white; padding: 2px 3px 1px 3px; font-size: 7.5pt; }}
.grid td {{ padding: 2px 3px 1px 3px; border-bottom: 0.5px solid #d5dbe1; vertical-align: top; }}
.num td, .num th {{ text-align: right; }} .num td.l, .num th.l, .l {{ text-align: left; }}
.tiny td, .tiny th {{ font-size: 7pt; }}
.src {{ color: #4c5966; font-size: 6.8pt; }}
.total td {{ font-weight: bold; background-color: #f1f4f8; }}
.chip {{ color: white; font-weight: bold; text-align: center; vertical-align: middle; }}
.ratings td {{ padding: 4px 4px 3px 4px; }} .q {{ width: 27%; }}
.approval td {{ padding: 6px 4px 3px 4px; }} .line {{ border-bottom: 0.8px solid #1d2733; }}
.ticks td {{ padding: 2px 4px; }} .box {{ border: 0.8px solid #1d2733; width: 10px; }}
.callout td {{ background-color: #fff6e0; border-left: 3px solid {RATING_COLOURS[AMBER]}; padding: 6px 8px; }}
.tight li {{ margin-bottom: 0; }}
.grid td.sub {{ background-color: #e8edf3; color: {NAVY}; font-weight: bold; font-size: 6.8pt; text-align: left; }}
#footer {{ font-size: 6.8pt; color: #4c5966; border-top: 0.5px solid #d5dbe1; padding-top: 2px; }}
"""


def build_html(inp: ReportInputs, out_dir: Path, compact: bool = False) -> str:
    footer = (f'<div id="footer">{escape(inp.profile.fund_name)} · Fund performance review (draft) · figures to '
              f'{inp.profile.as_of_date:%d %b %Y} · Public data only · Page <pdf:pagenumber> of <pdf:pagecount></div>')
    main = [_page1(inp), _page2(inp, out_dir), _page3(inp)]
    pages = main + [_appendix(inp, compact, plain_text("".join(main)))]
    body = '<div style="page-break-before: always"></div>'.join(pages)
    return f"<html><head><meta charset='utf-8'/><style>{CSS}</style></head><body>{footer}{body}</body></html>"


FONT_FILES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")


def _render(html: str, path: Path) -> None:
    """ xhtml2pdf reads files only from the folder it renders in, so the fonts (shipped with matplotlib, on any
    machine) are copied next to the report; DejaVu Sans draws R², the minus sign and the tick boxes """
    fonts = path.parent / "fonts"
    fonts.mkdir(exist_ok=True)
    for name in FONT_FILES:
        if not (fonts / name).exists():
            shutil.copy(FONT / name, fonts / name)
    with open(path, "wb") as f:
        result = pisa.CreatePDF(html, dest=f, encoding="utf-8", path=str(path))
    if result.err:
        raise RuntimeError("PDF generation failed")


def page_texts(path: Path) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(path).pages]


def layout_problems(path: Path) -> list[str]:
    """ Pages 1-3 must each hold exactly one main section, and the appendix starts on page 4 """
    texts = page_texts(path)
    problems = []
    for i, title in enumerate(PAGE_TITLES):
        if i >= len(texts) or title not in texts[i]:
            problems.append(f"'{title}' is not at the top of page {i + 1}: the page before it ran over")
    if len(texts) > MAX_PAGES:
        problems.append(f"{len(texts)} pages; at most {MAX_PAGES}")
    return problems


def build_report(inp: ReportInputs, out_dir: Path, name: str = "report.pdf") -> Path:
    """ Build the PDF; if it runs over 5 pages, shorten the appendix first """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    _render(build_html(inp, out_dir), path)
    if len(page_texts(path)) > MAX_PAGES:
        _render(build_html(inp, out_dir, compact=True), path)
    problems = layout_problems(path)
    if problems:
        raise ReportLayoutError("; ".join(problems))
    return path
