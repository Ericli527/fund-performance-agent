""" The PDF report (spec Section 9): 4 main pages and an appendix, 5 pages at most

Page 1 Summary (stands on its own), page 2 Evidence dashboard (charts and statistics, code only), page 3 Mandate
and performance, page 4 Value, fees and Assessment of Value, then the appendix. Every figure shows its source; AI-extracted figures say "(please verify)". If the
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
from fund_performance.evidence import Evidence
from fund_performance.peers import PeerComparison, as_list
from fund_performance.plain import plain_peer_reason
from fund_performance.presentation import (NOT_RELIABLE, UNRELIABLE, UNRELIABLE_MARK, comparison_problems,
                                           missing_evidence,
                                           is_comparative)
from fund_performance.precedence import ReportedFigures
from fund_performance.scorecard import AMBER, CHECK_DATA, GREEN, MANUAL_CHECK, RED, Scorecard

APPENDIX_TITLES = ("Appendix A: Evidence dashboard", "Appendix B: Mandate and performance",
                   "Appendix C: Value, fees and Assessment of Value", "Appendix D: Data quality, sources and audit")
PAGE_TITLES = ("Overview", "Comparisons and decision") + APPENDIX_TITLES
NAVY = "#1f3a5f"
RATING_COLOURS = {GREEN: "#2e7d32", AMBER: "#d18f00", RED: "#c62828", CHECK_DATA: "#6d4c9f", MANUAL_CHECK: "#546e7a"}
RATING_WORDS = {GREEN: "Green", AMBER: "Amber", RED: "Red", CHECK_DATA: "Check data", MANUAL_CHECK: "Manual check"}
SOURCE_WORDS = {"factsheet": "Factsheet", "calculated": "Calculated", "calculated_provisional": "Calculated from AI-extracted figures (please verify)", "ai_extracted": "AI-extracted (please verify)",
                "user": "Entered by user",
                "web": "Web"}
AOV_DISCLAIMER = ("This is an indicative assessment from public data. It does not replace the AFM's formal "
                  "Assessment of Value.")
KNOWN_LIMITATIONS = [
    "Web figures are checked against the factsheet only when described as a return or performance with a "
    "period (e.g. \"returned 17.1% over 1 year\"). Other figures in web text (fees, tax rates, returns with no "
    "period) are not checked; the AI text may still quote only figures from the factsheet and calculations.",
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
    web_sources: list[dict] | None = None   # numbered sources from the run log (step 10); else the narrative's
    entered_by_user: list[str] = field(default_factory=list)   # documents route: figures corrected on the page
    promises: list[str] = field(default_factory=list)
    peer: Peer | None = None                # one peer (older callers); `peers` takes a list
    peers: list[Peer] = field(default_factory=list)
    peer_comparison: PeerComparison | None = None
    evidence: Evidence | None = None
    sector_ocf: dict | None = None          # config/peers.yaml sector_average_ocf: value_pct, source, date
    prices: pd.DataFrame | None = None
    run_note: str | None = None             # e.g. "Offline run: AI steps skipped"
    prepared: date = field(default_factory=date.today)

    def __post_init__(self):
        self.peers = self.peers or as_list(self.peer)


# --- Figures ----------------------------------------------------------------------------------------------------

def fmt(name: str, fig: Figure | None, verify: bool = True) -> str:
    """ 1 d.p., or 2 d.p. for tracking error, tracking difference, alpha, beta, R² and the information ratio.
    An AI-extracted figure says "(please verify)"; in a table (verify=False) its row or group source says it """
    if fig is None:
        return "–"
    two_dp = any(part in TWO_DP for part in name.split("."))
    text = fig.display(percent_decimals=2 if two_dp else 1, ratio_decimals=2).replace("-", "−")
    return text + (" (please verify)" if verify and fig.needs_verification else "")


def source_of(*figs: Figure | None) -> str:
    sources = sorted({SOURCE_WORDS.get(f.source, f.source) for f in figs if f is not None})
    return ", ".join(sources) or "–"


def _f(inp: ReportInputs, name: str) -> Figure | None:
    return inp.reported.figures.get(name)


def _years(inp: ReportInputs) -> int:
    return inp.profile.analysis_period_years


# --- Plain-English one-line reasons for page 1 ---------------------------------------------------------------

def _profile_source(p: FundProfile, key: str, default: str) -> str:
    """ Documents route: who gave a profile value (AI-extracted, entered by user, derived by code) """
    return {"ai_extracted": "AI-extracted (please verify)", "user": "Entered by user",
            "code": "Derived by code (please verify)"}.get(p.field_sources.get(key, ""), default)


def plain_reason(inp: ReportInputs, name: str) -> str:
    pillar = inp.card.pillars[name]
    n = _years(inp)
    if pillar.summary == "Add peer":
        what = "value for investors" if name.startswith("Value") else "the fee"
        why = "no comparison fund was supplied" if not inp.peers else "no peer's returns could be compared"
        return f"Add peer: {why}, so {what} cannot be judged."
    if pillar.rating == CHECK_DATA and (missing := missing_evidence(inp.facts).get(name)):
        return f"Not rated: {missing}."
    if pillar.rating in (MANUAL_CHECK, CHECK_DATA):
        return pillar.reason.replace(f"{n}y", f"{n} years")
    if (peer_reason := plain_peer_reason(name, pillar.values)):
        return peer_reason[:1].upper() + peer_reason[1:] + "."
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

def _in_full(inp: ReportInputs) -> str:
    """ Everything the executive pages select from, in full: all findings, points for judgement and questions """
    facts = inp.facts
    out = inp.narrative.output if inp.narrative else None
    parts = [("Key findings", list(out.key_findings) if out else []),
             ("Points for your judgement", facts.get("judgement_points", [])),
             ("Questions to ask the manager", facts.get("manager_questions", []))]
    return "".join(f"<h3>{title}</h3><ul class='tight'>" + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul>"
                   for title, items in parts if items)


def _returns_table(inp: ReportInputs) -> str:
    cols = [("1 year", "cum.1y"), ("3 years", "cum.3y"), ("5 years", "cum.5y"),
            ("3 years, a year", "ann.3y"), ("5 years, a year", "ann.5y")]
    rows = ""
    for label, series in (("Fund, noon price (NAV)", "fund_nav"), ("Fund, market-close price (PNAV)", "fund_pnav"),
                          ("Index", "index")):
        label = _marked(inp, label, series == "index")
        figs = [_f(inp, f"{series}.{c}") for _, c in cols]
        if any(figs):
            rows += (f"<tr><td class='l'>{label}</td>" + "".join(f"<td>{fmt(series, f, False)}</td>" for f in figs)
                     + f"<td class='src'>{source_of(*figs)}</td></tr>")
    basis = next((f.basis for k, f in inp.reported.figures.items() if k.startswith("comparison.td")), None)
    gap = [_f(inp, f"comparison.excess_cum.{c[-2:]}") if c.startswith("cum") else _f(inp, f"comparison.td.{c[-2:]}")
           for _, c in cols]
    if any(gap):
        who = "PNAV" if basis == "fund_pnav" else "NAV"
        rows += (f"<tr class='total'><td class='l'>{_marked(inp, f'Gap to index ({who} vs index, pp)')}</td>"
                 + "".join(f"<td>{fmt('comparison.td' if i >= 3 else 'comparison.excess_cum', g, False)}</td>"
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
        label = _marked(inp, label, series == "index")
        figs = [_f(inp, f"{series}.calendar.{y}") for y in years]
        if any(figs):
            rows += (f"<tr><td class='l'>{label}</td>" + "".join(f"<td>{fmt(series, f, False)}</td>" for f in figs)
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
                shown = _marked(inp, label, is_comparative(fund_name))
                body += (f"<tr><td class='l'>{shown}</td><td>{fmt(fund_name, _f(inp, fund_name), False)}</td>"
                         f"<td>{fmt(index_name, index, False) if index else '–'}</td></tr>")
        return ("<table class='grid num tiny'><tr><th class='l' width='54%'>Risk measure</th><th>Fund</th>"
                f"<th>{_marked(inp, 'Index')}</th></tr>{body}</table>")
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
    return f'<img src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}" width="280"/>'


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


# --- Evidence dashboard (Phase C): charts and statistics, code only ------------------------------------------------

SERIES_WORDS = {"fund_pnav": "market-close price (PNAV)", "fund_nav": "noon price (NAV)"}


def _risk_vol(inp: ReportInputs) -> tuple[str, float | None, float | None]:
    """ (fund series, fund volatility, index volatility), 3 years, from the factsheet's risk table """
    for basis, series in (("pnav", "fund_pnav"), ("unspecified", "fund_nav"), ("nav", "fund_nav")):
        fund = inp.reported.value(f"risk.{basis}.fund_vol.3y")
        if fund is not None and inp.reported.value(f"{series}.ann.3y") is not None:
            return series, fund, inp.reported.value(f"risk.{basis}.index_vol.3y")
    return "fund_nav", None, None


def _dashboard_charts(inp: ReportInputs, out_dir: Path) -> list[tuple[Path | None, str]]:
    """ (chart, caption) for each chart; a chart that lacks data is None and its caption says why """
    p, ev, n = inp.profile, inp.evidence, _years(inp)
    out = []
    index_fund = p.objective_type == "index_tracker"
    if ev and ev.gaps:
        years = list(ev.gaps)
        pi = inp.thresholds.performance_index
        kwargs = ({"ocf": p.ocf_pct, "green": p.ocf_pct + pi.green_td_margin_over_ocf_pp,
                   "amber": p.ocf_pct + pi.amber_td_margin_over_ocf_pp} if index_fund and p.ocf_pct is not None else {})
        what = "Yearly tracking difference" if index_fund else "Yearly excess return"
        chart = charts.yearly_gap_chart(years, list(ev.gaps.values()), out_dir / "dash_gaps.png",
                                        f"{what}, {years[0]}–{years[-1]}", **kwargs)
        bands = (f" Bands: Performance limits for the size of the gap (fee + {pi.green_td_margin_over_ocf_pp:.2f} "
                 f"and + {pi.amber_td_margin_over_ocf_pp:.2f} pp); dashed line: the fee." if index_fund and p.ocf_pct is not None else "")
        out.append((chart, f"Fund {SERIES_WORDS[ev.series]} minus index, each calendar year {years[0]}–{years[-1]}. "
                           f"Source: factsheet; gaps calculated.{bands}"))
    else:
        out.append((None, "Yearly gap chart left out: the factsheet has no calendar-year returns for the fund and "
                          "the index."))
    limits = [lim for pillar in inp.card.pillars.values() for lim in (pillar.values or {}).get("limits", [])]
    if limits:
        out.append((charts.limits_chart(limits, out_dir / "dash_limits.png", "Distance to each limit"),
                    "Each rated figure (◆) against its Green, Amber and Red zones (config/thresholds.yaml). "
                    f"Source: the scorecard (calculated), main period {n} years or as rated."))
    else:
        out.append((None, "Distance-to-limit chart left out: no rated figure has a numeric limit."))
    used = inp.peer_comparison.used if inp.peer_comparison else []
    if used:
        first = used[0]
        label = "Fund (PNAV)" if first.fund_series == "fund_pnav" else "Fund (NAV)"
        series = {label: [first.fund_returns[k] for k in (1, 3, 5)]}
        matching = [r for r in used if r.basis == first.basis and r.fund_series == first.fund_series]
        series |= {r.peer.name[:28]: [r.returns[k] for k in (1, 3, 5)] for r in matching}
        out.append((charts.peer_returns_chart(["1 year", "3 years", "5 years"], series, out_dir / "dash_peers.png",
                                              "Fund vs comparable peers"),
                    f"Returns a year to {p.as_of_date:%d %b %Y} (1 year: the 1-year return). Source: factsheets "
                    f"(fund and peers). Only peers with returns in {p.currency} on the {first.basis} basis are shown."))
    else:
        out.append((None, f"Fund vs peers chart left out: no peer with returns in {p.currency}."))
    series, fund_vol, index_vol = _risk_vol(inp)
    points = []
    if fund_vol is not None:
        points.append(("Fund", fund_vol, inp.reported.value(f"{series}.ann.3y")))
        if index_vol is not None and inp.reported.value("index.ann.3y") is not None:
            points.append(("Index", index_vol, inp.reported.value("index.ann.3y")))
        points += [(r.peer.name[:24], r.peer.vol_3y, r.returns[3]) for r in used
                   if r.peer.vol_3y is not None and r.returns[3] is not None]
    if len(points) >= 2:
        out.append((charts.scatter_chart(points, out_dir / "dash_scatter.png", "Return vs volatility, 3 years"),
                    f"Return a year against volatility, 3 years to {p.as_of_date:%d %b %Y}. Source: factsheets "
                    f"(fund {SERIES_WORDS[series]}, index and peers where given)."))
    else:
        out.append((None, "Return vs volatility chart left out: the factsheets give no 3-year volatility."))
    return out


def _signed(value: float) -> str:
    return f"{value:+.2f} pp".replace("-", "−")


def _statistics(inp: ReportInputs) -> str:
    ev = inp.evidence
    if ev is None or not ev.gaps:
        return "<p class='small'>No statistics: the factsheet has no calendar-year returns.</p>"
    years = f"{list(ev.gaps)[0]}–{list(ev.gaps)[-1]}"
    if ev.hit_rate is None:
        hit_text = "Not available: ongoing charge not established"
    else:
        hits, total = ev.hit_rate
        hit_text = (f"{hits} of {total} years within {ev.hit_margin_pp:.2f} pp (fee + margin)" if ev.hit_margin_pp is not None
                    else f"{hits} of {total} years at or above the benchmark")
    twelve = _f(inp, "comparison.hit_rate")
    rows = [("Hit rate, calendar years", hit_text),
            *([("Hit rate, 12-month windows", fmt("comparison.hit_rate", twelve, False))] if twelve else []),
            ("Average yearly gap", _signed(ev.average)),
            ("Best year", f"{ev.best[0]}: {_signed(ev.best[1])}"), ("Worst year", f"{ev.worst[0]}: {_signed(ev.worst[1])}")]
    stats = "".join(f"<tr><td class='l'>{a}</td><td class='l'>{escape(b)}</td></tr>" for a, b in rows)
    test = ev.test
    if test and test.t is not None:
        p_text = "< 0.001" if test.p < 0.001 else f"{test.p:.3f}"
        test_row = (f"<tr><td class='l'>{escape(test.what)}</td><td>{test.n}</td><td>{_signed(test.mean)}</td>"
                    f"<td>{test.t:.2f}</td><td>{p_text}</td><td class='l'>{escape(test.result)}</td></tr>")
    else:
        test_row = (f"<tr><td class='l'>{escape(test.what if test else '')}</td><td>{test.n if test else 0}</td>"
                    f"<td>–</td><td>–</td><td>–</td><td class='l'>{escape(test.result if test else 'Not run')}</td></tr>")
    level = f"{inp_level(inp):.0%}"
    pct = ""
    if ev.percentile:
        q = ev.percentile
        pct = (f"<p class='small'><b>Peer percentile:</b> the fund did better than {q['beaten']} of {q['peers']} peers over "
               f"{q['years']} years ({q['percentile']}th percentile). Source: factsheets; calculated.</p>")
    return (f"<h3>Statistics, {years}</h3><table class='grid tiny' width='60%'>{stats}</table>"
            f"<p class='small'>Source: factsheet calendar-year returns; calculated.</p>"
            f"<h3>Significance test (one-sample t-test against zero, {level} level)</h3>"
            f"<table class='grid num tiny'><tr><th class='l' width='26%'>What is tested</th><th width='7%'>Years</th>"
            f"<th width='10%'>Mean</th><th width='10%'>t-statistic</th><th width='9%'>p-value</th>"
            f"<th class='l'>Result</th></tr>{test_row}</table>{pct}")


def inp_level(inp: ReportInputs) -> float:
    from fund_performance.config import load_settings
    return load_settings().statistics.significance_level


def _marked(inp: ReportInputs, label: str, comparative: bool = True) -> str:
    """ A table label for a fund-vs-index figure, marked while a currency or benchmark mismatch is unresolved """
    return f"{label} ({UNRELIABLE_MARK})" if comparative and comparison_problems(inp.flags) else label


def _not_reliable(inp: ReportInputs) -> str:
    """ A warning above charts that compare the fund with an index the data checks found mismatched """
    if not comparison_problems(inp.flags):
        return ""
    return f"<table class='callout'><tr><td><b>Read with care.</b> {escape(NOT_RELIABLE)}</td></tr></table>"


def _dashboard(inp: ReportInputs, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    cells, left_out = [], []
    for chart, caption in _dashboard_charts(inp, out_dir):
        if chart is None:
            left_out.append(caption)
            continue
        image = f'<img src="data:image/png;base64,{base64.b64encode(chart.read_bytes()).decode()}" width="290"/>'
        cells.append(f"<td width='50%' valign='top' align='center'>{image}<p class='small'>{escape(caption)}</p></td>")
    if len(cells) % 2:
        cells.append("<td width='50%'></td>")
    grid = "".join(f"<tr>{''.join(cells[i:i + 2])}</tr>" for i in range(0, len(cells), 2))
    grid += "".join(f"<tr><td colspan='2'><p class='small'>{escape(x)}</p></td></tr>" for x in left_out)
    return f"""
<h1>Appendix A: Evidence dashboard</h1>
<p class="small">Charts and statistics are calculated by code from the sources shown under each one. No AI.</p>
{_not_reliable(inp)}
<table width="100%">{grid}</table>
{_statistics(inp)}
"""


def _page2(inp: ReportInputs, out_dir: Path) -> str:
    path = "".join(f"<li>{escape(step)}</li>" for step in plain_path(inp.card.path))
    promises = ("".join(f"<li>{escape(x)}</li>" for x in inp.promises) if inp.promises
                else "<li>Not read: the Mandate Agent was not run.</li>")
    mark = f"{UNRELIABLE} ({UNRELIABLE_MARK.split(': ')[1]}): " if comparison_problems(inp.flags) else ""
    notes = "".join(f"<li>{mark}{escape(plain_note(n))}<br/><span class='small'>{escape(note_source_line(n))}</span></li>"
                    for n in inp.facts.get("data_notes", []))
    growth, yearly, caption = _chart_images(inp, out_dir)
    return f"""
<h1>Appendix B: Mandate and performance</h1>
{_not_reliable(inp)}
{_in_full(inp)}
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
    fee = ("performance fee: yes" if p.performance_fee else "no performance fee" if p.performance_fee is False
           else "performance fee: not established in the documents (missing evidence)")
    size = f"fund size £{p.fund_size_gbp_m:,.0f}m" if p.fund_size_gbp_m else "fund size not given"
    fees = pillars["Fees"]
    ocf = f"{p.ocf_pct:.2f}%" if p.ocf_pct is not None else "not established"
    return [
        ("1. Quality of service", "Not public: requires internal data.", "Not assessed"),
        ("2. Performance", f"Mandate {RATING_WORDS[pillars['Mandate'].rating]}, Performance "
                           f"{RATING_WORDS[pillars['Performance'].rating]} (page 3).", "Covered"),
        ("3. AFM costs", f"Ongoing charge (OCF) {ocf}; {tx}; {fee}.",
         "Partly" if p.transaction_cost_pct is None or p.ocf_pct is None else "Covered"),
        ("4. Economies of scale", f"{size.capitalize()}; requires OCF history.", "Partly"),
        ("5. Comparable market rates", "No comparable peer." if fees.summary == "Add peer"
         else f"Fees {RATING_WORDS[fees.rating]}: {plain_reason(inp, 'Fees')}",
         "Not assessed" if fees.summary == "Add peer" else "Covered"),
        ("6. Comparable services", "Requires internal data (other mandates of the same manager).", "Not assessed"),
        ("7. Classes of units", "Requires share class data.", "Not assessed"),
    ]


STATUS_COLOURS = {"Covered": RATING_COLOURS[GREEN], "Partly": RATING_COLOURS[AMBER], "Not assessed": "#8a96a3"}


def _pct(value: float | None, decimals: int = 1) -> str:
    return "–" if value is None else f"{value:.{decimals}f}%".replace("-", "−")


def _peers_table(inp: ReportInputs) -> str:
    p, comp = inp.profile, inp.peer_comparison
    if not inp.peers:
        return ("<table class='callout'><tr><td><b>Add peer.</b> No comparison fund was supplied, and there is no "
                "approved peer for this benchmark, so value for investors and the fee cannot be judged. Add comparable "
                "funds' factsheets (or their name, ongoing charge and 1, 3 and 5-year returns).</td></tr></table>")
    fund = [_f(inp, "fund_nav.cum.1y"), _f(inp, "fund_nav.ann.3y"), _f(inp, "fund_nav.ann.5y")]
    head = ("<tr><th class='l' width='25%'>Fund</th><th class='l'>Share class</th><th class='l'>Currency, pricing"
            "</th><th>Fee (OCF)</th><th>1 year</th><th>3 years, a year</th><th>5 years, a year</th>"
            "<th class='l'>Used for</th></tr>")
    rows = (f"<tr class='total'><td class='l'>{escape(p.fund_name)}</td><td class='l'>{escape(p.share_class)}, "
            f"{p.distribution}</td><td class='l'>{p.currency}, {PRICING_TIME.get(p.pricing_point, 'pricing time not stated')}</td><td>{_pct(p.ocf_pct, 2)}</td>"
            + "".join(f"<td>{f.display(percent_decimals=2).replace('-', '−') if f else '–'}</td>" for f in fund)
            + "<td class='l'>This fund (NAV)</td></tr>")
    notes = []
    for r in comp.rows if comp else []:
        peer = r.peer
        kind = ", ".join(x for x in (peer.investor_type, peer.distribution) if x)
        minimum = f"; min {peer.minimum_investment}" if peer.minimum_investment else ""
        used = f"Fees and returns ({r.basis})" if r.used_for_returns else f"Fees only: {r.excluded}"
        rows += (f"<tr><td class='l'>{escape(peer.name)}</td><td class='l'>{escape(peer.share_class)}"
                 f"{', ' + kind if kind else ''}{escape(minimum)}</td><td class='l'>{peer.currency}"
                 f"{', ' + PRICING_TIME[peer.pricing_point] if peer.pricing_point else ''}</td><td>{peer.ocf_pct:.2f}%</td>"
                 + "".join(f"<td>{_pct(r.returns[k], 2)}</td>" for k in (1, 3, 5)) + f"<td class='l'>{escape(used)}</td></tr>")
        notes += [f"{peer.name}: {x}." for x in r.notes]
    value, fees = inp.card.pillars["Value for investors"].values, inp.card.pillars["Fees"].values
    if len(inp.peers) > 1:
        avg = [None, None, None]
        used = comp.used if comp else []
        if used:
            avg = [sum(r.returns[k] for r in used if r.returns[k] is not None) / max(1, sum(r.returns[k] is not None for r in used))
                   for k in (1, 3, 5)]
        rows += (f"<tr class='total'><td class='l'>Peer average</td><td class='l'>{len(inp.peers)} peers (fees), "
                 f"{len(used)} (returns)</td><td></td><td>{fees.get('peer_ocf', 0):.2f}%</td>"
                 + "".join(f"<td>{_pct(a, 2)}</td>" for a in avg) + "<td class='l'>The ratings</td></tr>")
    if inp.sector_ocf:
        s = inp.sector_ocf
        rows += (f"<tr><td class='l'>Sector average (context only)</td><td class='l' colspan='2'>{escape(s['source'])}, "
                 f"{escape(str(s['date']))}</td><td>{s['value_pct']:.2f}%</td><td colspan='4'></td></tr>")
    gap = (f"Value: {plain_reason(inp, 'Value for investors')} " if value else "")
    source = ("Source: factsheets (peers: " + ", ".join(sorted({ORIGIN_WORDS[x.origin] for x in inp.peers}))
              + "); returns a year, net of fees; averages and gaps calculated.")
    note_list = "".join(f"<li>{escape(x)}</li>" for x in dict.fromkeys(notes))
    return (f"<table class='grid num tiny'>{head}{rows}</table><p class='small'>{escape(gap)}{escape(source)}</p>"
            + (f"<ul class='tight small'>{note_list}</ul>" if note_list else ""))


PRICING_TIME = {"midday": "noon", "market_close": "market close"}
ORIGIN_WORDS = {"approved": "approved peers, config/peers.yaml, read by the Extractor Agent",
                "uploaded": "uploaded, read by the Extractor Agent", "typed": "peer.json"}


def _page3(inp: ReportInputs) -> str:
    p = inp.profile
    peer = _peers_table(inp)
    ocf = f"{p.ocf_pct:.2f}% a year" if p.ocf_pct is not None else "Not available"
    fees = (f"<table class='grid'><tr><th class='l'>Charge</th><th class='l'>This fund</th><th class='l'>Source</th></tr>"
            f"<tr><td class='l'>Ongoing charge (OCF)</td><td class='l'>{ocf}</td><td class='l src'>"
            f"{_profile_source(p, 'ocf_pct', 'Factsheet / KID (profile)')}</td></tr>"
            f"<tr><td class='l'>Transaction costs</td><td class='l'>"
            f"{'Not disclosed in the documents provided' if p.transaction_cost_pct is None else f'{p.transaction_cost_pct:.2f}%'}"
            f"</td><td class='l src'>Profile</td></tr>"
            f"<tr><td class='l'>Performance fee</td><td class='l'>{'Yes' if p.performance_fee else 'None' if p.performance_fee is False else 'Not established in the documents'}</td>"
            f"<td class='l src'>KID (profile)</td></tr></table>")
    aov = "".join(f"<tr><td class='l'><b>{a}</b></td><td class='l'>{escape(b)}</td>"
                  f"<td class='chip' style='background-color:{STATUS_COLOURS[c]}'>{c}</td></tr>" for a, b, c in _aov_rows(inp))
    context = inp.narrative.output.market_context
    analytical = (inp.facts.get("suggested_conclusion") or {}).get("detailed_analysis") or []
    analytical_html = ("<h3>Investment analysis</h3>" + "".join(f"<p>{escape(p)}</p>" for p in analytical)
                       if analytical else "")
    market = (f"<p>{escape(context)}</p><p class='small'>Written by AI from the cited sources; sources [n] are listed "
              "in the appendix.</p>" if context else
              "<p class='small'>No market context: " + (
                  "the AI steps were not run." if inp.run_note else
                  "the AI text did not pass its checks (see the appendix)." if inp.narrative.source == "template" else
                  "no web source passed the date, relevance and figure checks.") + "</p>")
    return f"""
<h1>Appendix C: Value, fees and Assessment of Value</h1>
{analytical_html}
<h3>Comparison with peer funds</h3>{peer}
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
        "Suggested verdict: any Red = Action needed (investigate and engage the manager); any Amber = Monitor (keep a "
        "close eye on it); all Green = Satisfied (no action needed); Check data on Mandate or Performance = Pending "
        "data check. Several peers: the average return gap and the average fee are rated.",
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


ANGLE_WORDS = {"board": "board", "analyst": "oversight analyst", "manager_meeting": "meeting with the manager"}
JUDGE_WORDS = {"pass": "approved by the Judge", "revise": "sent back for one revision",
               "fallback": "not used (security or factual concern)"}
REPORT_TYPE_WORDS = {"quarterly_review": "quarterly oversight review", "fee_question": "fee question",
                     "performance_question": "performance question", "mandate_question": "mandate question"}


def _plan_and_drafts(facts: dict, compact: bool = False) -> str:
    """ The Task Planner's plan and the drafts with the Judge's checklist and code's score """
    plan = facts.get("plan") or {}
    lines = []
    if plan:
        who = "Task Planner Agent" if plan.get("source") == "planner" else plan.get("source", "default")
        lines.append(f"Plan ({who}): {REPORT_TYPE_WORDS.get(plan.get('report_type'), plan.get('report_type'))}; "
                     f"focus {', '.join(plan.get('focus', [])[:2])}; market context "
                     f"{'yes' if plan.get('market_context') else 'no'}; drafts for "
                     + ", ".join(ANGLE_WORDS.get(a, a) for a in plan.get("angles", [])) + ".")
    for d in facts.get("drafts", []):
        failed = [k.replace("_", " ") for k, v in d["checks"].items() if not v]
        lines.append(f"Draft for the {ANGLE_WORDS.get(d['angle'], d['angle'])}: "
                     f"{JUDGE_WORDS.get(d.get('decision'), 'reviewed')}{' (rewritten once)' if d.get('rewritten') else ''}"
                     + (f"; reason: {d['reason'].rstrip('.')}" if d.get("reason") else "")
                     + (f"; not passed: {', '.join(failed)}" if failed else "") + ("; chosen" if d["chosen"] else "") + ".")
    if facts.get("drafts") and not any(d["chosen"] for d in facts["drafts"]):
        lines.append("The draft was not used after the Judge's review, so code's conclusion is used.")
    if compact and len(lines) > 2:                       # the plan and the chosen draft (or the fallback) only
        lines = lines[:1] + [x for x in lines[1:] if x.endswith("chosen.") or x.startswith("The draft was not")][:1]
    return "".join(f"<li>{escape(x)}</li>" for x in lines)


def plain_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _appendix(inp: ReportInputs, compact: bool, main_text: str = "") -> str:
    flags = list({(f.level, f.message): f for f in inp.flags}.values())
    excluded = [f for f in flags if f.check == "research" and "excluded" in f.message]
    checks = [f for f in flags if f not in excluded]
    by_level = ""
    for level, title in (("blocking", "Blocking (Check data)"), ("warning", "Warnings"), ("info", "For the record")):
        items = [f for f in checks if f.level == level]
        more = len(items) - 6 if compact and level in ("info", "warning") else 0
        if more > 0:
            items = items[:6]
        if items:
            by_level += (f"<p class='small'><b>{title}</b></p><ul class='tight small'>"
                         + "".join(f"<li>{escape(f.message)}</li>" for f in items)
                         + (f"<li>… and {more} more (full list in run_log.txt)</li>" if more > 0 else "") + "</ul>")
    sources = "".join(f"<li>Input file: {escape(x)}</li>" for x in inp.input_files)
    if inp.profile.field_sources:
        sources += ("<li>Fund details and factsheet figures were read by the Extractor Agent (AI-extracted) and "
                    "checked by code against the documents (any not found are flagged above)."
                    + (" Entered by user: " + escape(", ".join(inp.entered_by_user)) + "." if inp.entered_by_user else "")
                    + "</li>")
    sources += "".join(
        f"<li>[{s['number']}] {escape(s['query'])} · {'as at' if s.get('date_basis') == 'as_at' else 'published'} "
        f"{s['date']} · {escape(s['url'])}"
        f"{' · uploaded document and date supplied by analyst; verify against original' if s.get('source_type') == 'uploaded_document' else ''}</li>"
        for s in (inp.web_sources if inp.web_sources is not None else inp.narrative.sources))
    excl = ("".join(f"<li>{escape(f.message)}</li>" for f in excluded) or "<li>None.</li>")
    thresholds = "".join(f"<li>{escape(line)}</li>" for line in _threshold_lines(inp.thresholds)[: 4 if compact else None])
    limits = "".join(f"<li>{escape(x)}</li>" for x in KNOWN_LIMITATIONS)
    sharpe = _calculated_sharpe(inp)
    plan = _plan_and_drafts(inp.facts, compact)
    rest = f"{by_level}{excl}{sources}{sharpe}{thresholds}{limits}{PUBLIC_DATA_NOTE}{DISCLAIMER}"
    glossary = "".join(f"<li><b>{escape(term)}</b>: {escape(text)}</li>"
                       for term, text in used_in(main_text + plain_text(rest)).items())
    return f"""
<h1>Appendix D: Data quality, sources and audit</h1>
<h3>Data checks and flags</h3>{by_level or '<p class="small">No flags.</p>'}
<h3>Excluded web sources</h3><ul class="tight small">{excl}</ul>
<h3>Sources</h3><ul class="tight small">{sources}</ul>
{f'<h3>Plan and drafts</h3><ul class="tight small">{plan}</ul>' if plan else ''}
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
body {{ font-family: DejaVu; font-size: 8.8pt; line-height: 1.35; color: #1d2733; }}
h1 {{ font-size: 14pt; color: {NAVY}; border-bottom: 1.5px solid {NAVY}; padding-bottom: 2px; margin: 4px 0 7px 0; }}
h2 {{ font-size: 10.8pt; color: {NAVY}; margin: 10px 0 4px 0; }}
h3 {{ font-size: 9pt; color: {NAVY}; margin: 7px 0 3px 0; }}
p {{ margin: 0 0 3px 0; }} ul, ol {{ margin: 0 0 3px 0; }} li {{ margin-bottom: 1px; }}
.small {{ font-size: 7.6pt; color: #4c5966; }}
.banner td {{ background-color: {NAVY}; color: white; padding: 7px 9px; }}
.kicker {{ font-size: 6.8pt; color: #b9cbe0; }} .fund {{ font-size: 14pt; font-weight: bold; }} .meta {{ font-size: 7.5pt; color: #dce6f1; }}
.facts td {{ padding: 2px 4px; vertical-align: top; }} .facts .label {{ width: 18%; color: #4c5966; font-weight: bold; }}
.verdict td {{ padding: 6px 8px; }} .vlabel {{ width: 22%; color: white; font-weight: bold; font-size: 10pt; text-align: center; }}
.vtext {{ background-color: #f1f4f8; font-size: 10pt; }}
.grid th {{ background-color: {NAVY}; color: white; padding: 2px 3px 1px 3px; font-size: 7.5pt; }}
.grid td {{ padding: 2px 3px 1px 3px; border-bottom: 0.5px solid #d5dbe1; vertical-align: top; }}
.num td, .num th {{ text-align: right; }} .num td.l, .num th.l, .l {{ text-align: left; }}
.tiny td, .tiny th {{ font-size: 7pt; }}
.src {{ color: #4c5966; font-size: 7.4pt; }}
.total td {{ font-weight: bold; background-color: #f1f4f8; }}
.chip {{ color: white; font-weight: bold; text-align: center; vertical-align: middle; }}
.ratings td {{ padding: 4px 4px 3px 4px; }} .q {{ width: 27%; }}
.approval td {{ padding: 4px 4px 2px 4px; }} .line {{ border-bottom: 0.8px solid #1d2733; }}
.ticks td {{ padding: 2px 4px; }} .box {{ border: 0.8px solid #1d2733; width: 10px; }}
.callout td {{ background-color: #fff6e0; border-left: 3px solid {RATING_COLOURS[AMBER]}; padding: 6px 8px; }}
.tight li {{ margin-bottom: 0; }}
.concl {{ background-color: #f1f4f8; padding: 4px 6px; margin: 4px 0; }}
.grid td.sub {{ background-color: #e8edf3; color: {NAVY}; font-weight: bold; font-size: 6.8pt; text-align: left; }}
#footer {{ font-size: 7.2pt; color: #4c5966; border-top: 0.5px solid #d5dbe1; padding-top: 2px; }}
"""


def build_html(inp: ReportInputs, out_dir: Path) -> str:
    """ The Detailed Report: the two Executive Report pages, then Appendices A to D, each from a new page """
    from fund_performance.executive import EXEC_CSS, executive_html, long_commentary
    footer = (f'<div id="footer">{escape(inp.profile.fund_name)} · Detailed Report (draft) · figures to '
              f'{inp.profile.as_of_date:%d %b %Y} · Public data only · Page <pdf:pagenumber> of <pdf:pagecount></div>')
    p1, p2 = executive_html(inp, out_dir)
    appendices = [_dashboard(inp, out_dir), _page2(inp, out_dir), _page3(inp)]
    appendices.append(_appendix(inp, False, plain_text("".join([p1, p2] + appendices))))
    separator = '' if long_commentary(inp.facts) else '<div style="page-break-before: always"></div>'
    body = p1 + separator + p2 + '<div style="page-break-before: always"></div>' + \
        '<div style="page-break-before: always"></div>'.join(appendices)
    return f"<html><head><meta charset='utf-8'/><style>{CSS}{EXEC_CSS}</style></head><body>{footer}{body}</body></html>"


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
    """ The Detailed Report: the executive pages first, then each appendix from a new page, in order. Every part may
    run to any length here (nothing is cut); the two-page limit applies to the Executive Report itself """
    texts = page_texts(path)
    problems = [] if texts and PAGE_TITLES[0] in texts[0] else ["the overview is not on page 1"]
    if texts and all(t in texts[0] for t in PAGE_TITLES[:2]) and texts[0].index(PAGE_TITLES[1]) < texts[0].index(PAGE_TITLES[0]):
        problems.append("the comparisons section precedes the overview")
    start = 0
    for title in PAGE_TITLES[1:]:
        page = next((i for i in range(start, len(texts)) if title in texts[i]), None)
        if page is None:
            problems.append(f"'{title}' is missing or out of order")
            continue
        start = page + 1
    return problems


def build_report(inp: ReportInputs, out_dir: Path, name: str = "report.pdf") -> Path:
    """ The Detailed Report (report.pdf). Nothing is shortened; a layout problem is an error """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    _render(build_html(inp, out_dir), path)
    problems = layout_problems(path)
    if problems:
        raise ReportLayoutError("Detailed Report: " + "; ".join(problems))
    return path
