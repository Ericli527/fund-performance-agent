""" Documents in, inputs out (step 11 update): the main route on the page

The user uploads a price file and the fund's factsheet (and, optionally, the KID or prospectus and peer funds'
factsheets; without them, the approved peers for the fund's benchmark in config/peers.yaml are read). The Extractor Agent reads the documents, the Mandate Agent reads the objective, and code turns their
answers into a table of values for a person to check. Each value shows where it was found (document and page,
found by code) and is marked "AI-extracted (please verify)". The person corrects anything wrong and confirms;
code then writes fund_profile.json, factsheet_performance.json and peer.json (a list of peers), marking corrected
values "entered by user". A required value that is missing blocks the run until it is filled in.

AI agents read; code decides where each value was found, what is missing, and what was changed.
"""
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import re
from fund_performance.agents.base import RunFn, run_structured
from fund_performance.agents.extractor import ExtractionResult, extract
from fund_performance.agents.mandate import MandateOutput, mandate_agent
from fund_performance.calc import annualise
from fund_performance.config import PeersConfig, load_peers
from fund_performance.io import read_document_pages
from fund_performance.models import FactsheetPerformance, FundProfile, Peer
from fund_performance.peers import approved_peers, investor_type, peer_folder

AI = "AI-extracted (please verify)"
CODE = "Derived by code (please verify)"
MISSING = "⚠ Missing: please fill in"
OPTIONAL = "Not found (optional)"
USER = "Entered by user"
NOT_FOUND = "not found in the documents"
PERFORMANCE_FEE_MISSING = ("Missing evidence: the documents do not say whether the fund charges a performance fee. "
                           "It is not assumed to be none: Fees is not rated Green until it is established")


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str                 # text, number, int, date, bool, choice
    required: bool = True
    choices: tuple[str, ...] = ()


PROFILE_FIELDS = (
    FieldSpec("fund_name", "Fund name", "text"),
    FieldSpec("isin", "ISIN", "text"),
    FieldSpec("share_class", "Share class", "text"),
    FieldSpec("currency", "Currency (e.g. GBP)", "text"),
    FieldSpec("benchmark_name", "Benchmark", "text"),
    FieldSpec("objective_type", "Objective type", "choice",
              choices=("index_tracker", "active_target", "active_comparator", "active_constraint", "income_target",
                       "absolute_return")),
    FieldSpec("time_horizon_years", "Time horizon (years)", "int", False),
    FieldSpec("ocf_pct", "Ongoing charge (OCF), % a year", "number", False),
    FieldSpec("as_of_date", "Figures to (YYYY-MM-DD)", "date"),
    FieldSpec("launch_date", "Share class launch date (YYYY-MM-DD)", "date"),
    FieldSpec("pricing_point", "Pricing point", "choice", False, choices=("midday", "market_close")),
    FieldSpec("distribution", "Distribution", "choice", choices=("accumulation", "income")),
    FieldSpec("hedged", "Currency hedged (yes / no)", "bool"),
    FieldSpec("benchmark_role", "Benchmark role", "choice", choices=("target", "comparator", "constraint", "none")),
    FieldSpec("performance_fee", "Performance fee (yes / no)", "bool", False),   # may be not established
    FieldSpec("objective_text", "Objective (as written)", "text"),
)
SERIES = (("fund_nav", "Fund (NAV)", False), ("fund_pnav", "Fund (PNAV, market close)", False), ("index", "Index", False))
RETURN_FIELDS = tuple(FieldSpec(f"series.{name}.{p}", f"{label}: {p[:-1]}-year return, cumulative %", "number", required)
                      for name, label, required in SERIES for p in ("1y", "3y", "5y"))
PEER_FIELDS = (                # one set per peer; the key "peer.<field>" becomes "peer1.<field>", "peer2.<field>", ...
    FieldSpec("peer.name", "fund name", "text"),
    FieldSpec("peer.isin", "ISIN", "text", False),
    FieldSpec("peer.share_class", "share class", "text"),
    FieldSpec("peer.currency", "currency", "text"),
    FieldSpec("peer.ocf_pct", "ongoing charge (OCF), % a year", "number"),
    FieldSpec("peer.pricing_point", "pricing point", "choice", False, ("midday", "market_close")),
    FieldSpec("peer.distribution", "distribution", "choice", False, ("accumulation", "income")),
    FieldSpec("peer.investor_type", "share class type", "choice", False, ("retail", "institutional")),
    FieldSpec("peer.minimum_investment", "minimum investment", "text", False),
    FieldSpec("peer.1y", "1-year return, %", "number", False),
    FieldSpec("peer.3y", "3-year return, % a year", "number", False),
    FieldSpec("peer.5y", "5-year return, % a year", "number", False),
    FieldSpec("peer.vol_3y", "3-year volatility, %", "number", False),
    FieldSpec("peer.as_of_date", "figures as at (YYYY-MM-DD)", "date", False),
)
COLUMNS = ["Field", "Value", "Status", "Source"]


@dataclass
class Built:
    """ The inputs written from the confirmed table, or the problems that stop the run """
    problems: list[str] = field(default_factory=list)
    profile: dict | None = None
    factsheet: dict | None = None
    peers: list[dict] = field(default_factory=list)
    user_entered: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)       # the confirmed table, with final statuses (for the log)
    flags: list[dict] = field(default_factory=list)      # code's self-check on the values (self_check)


# --- Where a value was found (code) ---------------------------------------------------------------------------

def _number_pattern(value: float) -> re.Pattern:
    variants = {f"{abs(value):.2f}", f"{abs(value):.1f}", f"{abs(value):g}"}
    # "0.07" is also printed "0.070" or "0.0700": trailing zeros after the decimal point are allowed
    alts = "|".join(re.escape(v) + ("0*" if "." in v else "") for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![\d.])(?:{alts})(?![\d])")


# Values the documents print in other words: a choice is found by any of its usual wordings
WORDINGS = {"midday": ("midday", "12:00", "12.00", "noon"), "market_close": ("market close", "market-close", "close of"),
            "accumulation": ("accumulat", " acc "), "income": ("income", "distribut")}


def _date_variants(value: str) -> list[str]:
    """ "2026-09-30" as factsheets print it: 30.09.26, 30.09.2026, 30/09/2026, 30 September 2026, 30 Sep 2026 """
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return []
    return [f"{d:%d.%m.%y}", f"{d:%d.%m.%Y}", f"{d:%d/%m/%Y}", f"{d:%d/%m/%y}", f"{d.day} {d:%B %Y}",
            f"{d:%d %B %Y}", f"{d.day} {d:%b %Y}", f"{d:%d %b %Y}", value]


def locate(value, pages: dict[str, list[str]]) -> str:
    """ "factsheet.pdf, page 2": the first page that shows the value, or "not found in the documents" """
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "read from the documents"
    if isinstance(value, (int, float)):
        pattern = _number_pattern(float(value))
        match = lambda text: pattern.search(text.replace("−", "-"))          # noqa: E731
    else:
        text_value = str(value).strip()
        needles = [n.lower() for n in (_date_variants(text_value) or WORDINGS.get(text_value) or [text_value[:40]])]
        match = lambda text: any(n and n in f" {' '.join(text.lower().split())} " for n in needles)  # noqa: E731
    for name, doc_pages in pages.items():
        for i, text in enumerate(doc_pages, start=1):
            if match(text):
                return f"{name}, page {i}" if len(doc_pages) > 1 or name.lower().endswith(".pdf") else name
    return NOT_FOUND


# --- Performance fee: read by code from explicit statements, with the words as evidence --------------------------

# "Performance fee N/A" (KID charges table), "Performance fee: None", "0.00%": none. "Performance fee 20% of ...",
# "Performance fee: Yes", "the fund charges a performance fee": one. Wording such as "excludes performance fees
# (where applicable)" is not a statement about this fund, so it is not evidence either way
_FEE_NONE = re.compile(r"performance fees?\s*[:\-–]?\s*(?:none|n/?a|nil|not applicable|no|0(?:\.0+)?\s*%)(?![a-z0-9])")
_FEE_YES = re.compile(r"performance fees?\s*[:\-–]?\s*(?:yes|applies|(?!0(?:\.0+)?\s*%)\d+(?:\.\d+)?\s*%)(?![a-z])"
                      r"|(?:charges|pays|may charge|is subject to) a performance fee")


def performance_fee_evidence(pages: dict[str, list[str]]) -> tuple[bool | None, str]:
    """ (True / False / None, evidence): None when the documents say nothing explicit, or contradict each other """
    found: dict[bool, str] = {}
    for name, doc_pages in pages.items():
        for i, text in enumerate(doc_pages, start=1):
            flat = " ".join(text.split())
            for value, pattern in ((False, _FEE_NONE), (True, _FEE_YES)):
                if value not in found and (m := pattern.search(flat.lower())):
                    where = f"{name}, page {i}" if len(doc_pages) > 1 or name.lower().endswith(".pdf") else name
                    found[value] = f"{where}: \"{flat[m.start():m.end()]}\""
    if len(found) == 1:
        (value, evidence), = found.items()
        return value, evidence
    return None, ("the documents state both: " + "; ".join(found.values())) if found else ""


# --- Reading the documents (AI) and building the table (code) -------------------------------------------------

def _performance_fee(ai_value: bool | None, docs: dict[str, list[str]], flags: list[dict]):
    """ (value, status, source) for the performance fee: the documents' explicit words decide, with the quote as
    evidence; an AI answer without such words is kept but shown as not found (a warning); nothing explicit and no
    answer stays empty: never taken as no fee """
    value, evidence = performance_fee_evidence(docs)
    if value is not None:
        if ai_value is not None and ai_value != value:
            flags.append({"check": "self_check", "level": "warning", "message": (
                f"Performance fee: the Extractor Agent read {'yes' if ai_value else 'no'}, but the documents say "
                f"{evidence}; the documents' words are used")})
        return value, CODE, evidence
    if evidence:                                     # contradictory statements: not established
        flags.append({"check": "self_check", "level": "warning", "message": f"Performance fee not established: {evidence}"})
        return None, AI, ""
    return ai_value, AI, (NOT_FOUND if ai_value is not None else "")


def _shown(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _row(spec: FieldSpec, value, status: str, source: str) -> dict:
    shown = _shown(value)
    if not shown:
        status = MISSING if spec.required else OPTIONAL
    return {"key": spec.key, "label": spec.label, "value": shown, "status": status, "source": source,
            "required": spec.required, "kind": spec.kind, "choices": list(spec.choices)}


def peer_values(extracted: ExtractionResult) -> dict:
    """ A peer's values from the Extractor's answer on its factsheet, keyed by field ("name", "5y", ...), with the
    ones code derived (annualised returns, share class type) listed under "_derived" """
    draft, fs = extracted.profile_draft, extracted.factsheet
    values: dict = {"name": draft.get("fund_name"), "isin": draft.get("isin"), "share_class": draft.get("share_class"),
                    "currency": draft.get("currency") or (fs.currency if fs else None), "ocf_pct": draft.get("ocf_pct"),
                    "pricing_point": draft.get("pricing_point"), "distribution": draft.get("distribution"),
                    "minimum_investment": draft.get("minimum_investment"),
                    "as_of_date": fs.as_of_date.isoformat() if fs and fs.as_of_date else None, "_derived": {}}
    if fs and values["pricing_point"] is None:
        nav = fs.series.get("fund_nav")
        values["pricing_point"] = nav.pricing if nav else None
    annual = fs.series_annualised.get("fund_nav") if fs else None
    cumulative = fs.series.get("fund_nav") if fs else None
    for n in (1, 3, 5):
        value = getattr(annual, f"y{n}") if annual else None
        if value is None and cumulative is not None and getattr(cumulative, f"y{n}") is not None:
            cum = getattr(cumulative, f"y{n}")
            value = cum if n == 1 else round(annualise(cum, n), 2)
            if n > 1:
                values["_derived"][f"{n}y"] = f"annualised by code from the {n}-year cumulative {cum:g}%"
        values[f"{n}y"] = value
    risk = fs.risk_3y if fs else None
    values["vol_3y"] = risk.fund_vol if risk else None
    values["investor_type"] = investor_type(values["share_class"], values["minimum_investment"])
    if values["investor_type"]:
        values["_derived"]["investor_type"] = "from the share class name and minimum investment"
    return values


def peer_record(values: dict, origin: str) -> dict:
    """ peer.json for one peer, from its values keyed by field """
    return {"name": values.get("name"), "isin": values.get("isin"), "ocf_pct": values.get("ocf_pct"),
            "currency": values.get("currency"), "share_class": values.get("share_class"),
            "pricing_point": values.get("pricing_point"), "distribution": values.get("distribution"),
            "investor_type": values.get("investor_type"), "minimum_investment": values.get("minimum_investment"),
            "vol_3y": values.get("vol_3y"), "as_of_date": values.get("as_of_date"), "origin": origin,
            "returns": {"1y": values.get("1y"), "3y": None, "5y": None, "basis": "cumulative"},
            "returns_annualised": {"1y": values.get("1y"), "3y": values.get("3y"), "5y": values.get("5y"),
                                   "basis": "annualised"}}


async def read_peer(path: Path, run: RunFn | None = None) -> tuple[dict, ExtractionResult, list[str]]:
    """ One peer factsheet read by the Extractor Agent: its values, the raw result and the pages """
    pages = read_document_pages(path)
    extracted = await extract("\n".join(pages), run, peer=True)
    return peer_values(extracted), extracted, pages


async def read_documents(factsheet: Path, kid: Path | None = None, peer_factsheets: list[Path] | Path | None = None,
                         run_extractor: RunFn | None = None, run_mandate: RunFn | None = None,
                         run_peer: RunFn | None = None, peers_config: PeersConfig | None = None,
                         supporting_documents: list[Path] | None = None) -> dict:
    """ Read the documents with the Extractor and Mandate agents; return the table to confirm and what else the run
    needs (a plain dict, so the page can keep it between the two clicks). Without peer factsheets, the approved
    peers for the fund's benchmark (config/peers.yaml) are read """
    paths = [p for p in (factsheet, kid) if p] + list(supporting_documents or [])
    docs = {}
    for path in paths:
        name = path.name
        if name in docs:
            raise ValueError(f"Duplicate document name: {name}; rename the files to preserve source references")
        docs[name] = read_document_pages(path)
    text = "\n\n".join(f"=== Document: {name} ===\n" + "\n".join(pages) for name, pages in docs.items())
    extracted: ExtractionResult = await extract(text, run_extractor)
    from fund_performance.fund_context import build_fund_context, recover_returns
    from fund_performance.portfolio import source_checked_exposures
    fs, recovered = recover_returns(extracted.factsheet, extracted.return_evidence, docs)
    draft = dict(extracted.profile_draft)
    exposures = source_checked_exposures(extracted.exposures, docs)
    context = build_fund_context(extracted.document_summary, draft, fs, exposures, list(docs), recovered=recovered)
    log = [f"Extractor Agent read: {', '.join(docs)}"]

    mandate: MandateOutput | None = None
    objective = draft.get("objective_text")
    if objective:
        from fund_performance.agents.mandate import mandate_prompt
        result = await run_structured(mandate_agent(), mandate_prompt(objective, context), MandateOutput, run=run_mandate)
        mandate = result.output if result.ok else None
        log.append("Mandate Agent read the objective" if mandate else
                   "Mandate Agent gave no valid answer: " + "; ".join(result.errors))

    rows, fee_flags = [], []
    objective_source = locate(objective, docs) if objective else ""
    values = draft | {"as_of_date": fs.as_of_date.isoformat() if fs else None}
    if fs and not values.get("currency"):
        values["currency"] = fs.currency
    if mandate:
        values |= {"objective_type": mandate.objective_type, "time_horizon_years": mandate.time_horizon_years,
                   "benchmark_role": mandate.benchmark_role}
    for spec in PROFILE_FIELDS:
        value = values.get(spec.key)
        status, source = AI, locate(value, docs)
        if spec.key in ("objective_type", "time_horizon_years", "benchmark_role") and value is not None:
            source = f"Mandate Agent, from the objective ({objective_source})"
        if spec.key == "distribution" and value is None and draft.get("share_class"):
            # Code reads it from the share class name: "Acc" = accumulation, "Inc" = income
            name = draft["share_class"].lower()
            value = "accumulation" if "acc" in name else "income" if "inc" in name else None
            status, source = CODE, f"from the share class name '{draft['share_class']}'"
        if spec.key == "hedged" and value is None:
            value, status, source = _hedged(draft, docs)
        if spec.key == "pricing_point" and value is None and fs:
            nav = fs.series.get("fund_nav")
            value = nav.pricing if nav else None
        if spec.key == "performance_fee":
            value, status, source = _performance_fee(value, docs, fee_flags)
        rows.append(_row(spec, value, status, source))
    for spec in RETURN_FIELDS:
        _, name, period = spec.key.split(".")
        series = fs.series.get(name) if fs else None
        value = getattr(series, f"y{period[0]}") if series else None
        recovered_source = next((r['source'] for r in recovered if r['series'] == name and r['period'] == period
                                 and r['basis'] == 'cumulative'), None)
        rows.append(_row(spec, value, AI, recovered_source or locate(value, docs)))

    if mandate:
        context['mandate_interpretation'] = mandate.interpretation or None
    flags = [f.model_dump() for f in extracted.flags] + fee_flags
    if recovered:
        flags.append({'check': 'provisional_returns', 'level': 'warning', 'message':
                      'Returns recovered from document quotations are provisional; verify them and any derived comparisons.'})
    uploaded = [peer_factsheets] if isinstance(peer_factsheets, Path) else list(peer_factsheets or [])
    peer_docs = [(p, "uploaded", "") for p in uploaded]
    if not peer_docs:
        approved = approved_peers(peers_config or load_peers(), draft.get("benchmark_name"), draft.get("isin"),
                                  peer_folder())
        peer_docs = [(path, "approved", f"approved peer ({approved.group.benchmark}, config/peers.yaml): ")
                     for _, path in approved.files]
        flags += [f.model_dump() for f in approved.flags]
        if approved.files:
            log.append(f"Approved peers for {approved.group.benchmark}: " + ", ".join(p.name for p, _ in approved.files))
    origins = []
    for i, (path, origin, where) in enumerate(peer_docs, start=1):
        values, peer_result, pages = await read_peer(path, run_peer)
        doc = {path.name: pages}
        for spec in PEER_FIELDS:
            name = spec.key.removeprefix("peer.")
            numbered = FieldSpec(f"peer{i}.{name}", f"Peer {i}: {spec.label}", spec.kind, spec.required, spec.choices)
            value = values.get(name)
            derived = values["_derived"].get(name)
            status, source = (CODE, where + derived) if derived and value is not None else (AI, where + locate(value, doc))
            rows.append(_row(numbered, value, status, source))
        origins.append(origin)
        # A peer that cannot be read does not block the fund's review: its flags are warnings, named by file
        flags += [f.model_dump() | {"level": "warning" if f.level == "blocking" else f.level,
                                    "message": f"Peer factsheet {path.name}: {f.message}"} for f in peer_result.flags]
        log.append(f"Extractor Agent read the {'approved ' if origin == 'approved' else ''}peer factsheet: {path.name}")

    return {"rows": rows, "documents": list(docs) + [p.name for p, _, _ in peer_docs],
            "portfolio_exposures": exposures, "fund_context": context,
            "text_chars": {name: sum(len(x) for x in pages) for name, pages in docs.items()},
            "factsheet": fs.model_dump(mode="json", by_alias=True) if fs else None,
            "promises": mandate.promises if mandate else [],
            "secondary_objective": mandate.secondary_objective if mandate else None,
            "peer_origins": origins, "flags": flags, "log": log}


_NOT_HEDGED = re.compile(r"\b(un-?hedged|not (currency[- ])?hedged|no (currency )?hedging|does not hedge)\b", re.I)


def _hedged(draft: dict, docs: dict[str, list[str]]):
    """ Code decides currency hedging when the Extractor did not: "hedged" in the share class or fund name = yes;
    the documents saying it is not hedged, or not mentioning hedging = no. Mentioned but unclear = no, with a
    warning in the report """
    names = f"{draft.get('fund_name', '')} {draft.get('share_class', '')}".lower()
    if "hedged" in names and not _NOT_HEDGED.search(names):
        return True, CODE, "'hedged' in the share class name"
    text = " ".join(t for pages in docs.values() for t in pages)
    if _NOT_HEDGED.search(text):
        return False, CODE, "the documents say it is not hedged"
    if "hedged" not in text.lower():
        return False, CODE, "no hedging mentioned in the documents"
    return False, CODE, UNCLEAR_HEDGING


UNCLEAR_HEDGING = "hedging is mentioned but not stated for this share class: taken as not hedged"


def self_check(intake: dict) -> Built:
    """ The documents route without a person checking the table: code takes the values as read, checks each one
    against the documents, and flags what it could not confirm. A required value nobody could read stops the run """
    built = build_inputs(intake, [r["value"] for r in intake["rows"]])
    horizon = next((r for r in intake["rows"] if r["key"] == "time_horizon_years"), None)
    if horizon is not None and not horizon["value"]:
        from fund_performance.availability import HORIZON_MISSING
        built.flags.append({"check": "fund_horizon", "level": "warning", "message": HORIZON_MISSING})
    fee = next((r for r in intake["rows"] if r["key"] == "ocf_pct"), None)
    if fee is not None and not fee["value"]:
        built.flags.append({"check": "ongoing_charge", "level": "warning",
                            "message": "Ongoing charge not established; fee-dependent comparisons are unavailable."})
    for r in intake["rows"]:
        if not r["value"]:
            continue
        if r["source"].endswith(NOT_FOUND):
            built.flags.append({"check": "self_check", "level": "warning", "message": (
                f"Read by the Extractor Agent but not found in the documents: {r['label']} = {r['value']}")})
        if r["source"] == UNCLEAR_HEDGING:
            built.flags.append({"check": "self_check", "level": "info", "message": (
                "Currency hedging: the documents mention hedging but do not state it for this share class; "
                "taken as not hedged")})
    fee = next((r for r in intake["rows"] if r["key"] == "performance_fee"), None)
    if fee is not None and not fee["value"]:
        built.flags.append({"check": "performance_fee", "level": "warning", "message": PERFORMANCE_FEE_MISSING})
    found = sum(1 for r in intake["rows"] if r["value"] and not r["source"].endswith(NOT_FOUND))
    built.flags.append({"check": "self_check", "level": "info", "message": (
        f"Code checked the values the Extractor Agent read: {found} of "
        f"{sum(1 for r in intake['rows'] if r['value'])} found in the documents (document and page in log.json)")})
    built.problems = [p.replace(": required, please fill it in", ": not found in the documents") for p in built.problems]
    return built


def table(intake: dict) -> list[list[str]]:
    """ The rows as shown on the page: Field, Value, Status, Source """
    return [[r["label"], r["value"], r["status"], r["source"]] for r in intake["rows"]]


def missing(intake: dict, values: list[str] | None = None) -> list[str]:
    """ Labels of required values that are still empty """
    values = values if values is not None else [r["value"] for r in intake["rows"]]
    return [r["label"] for r, v in zip(intake["rows"], values) if r["required"] and not str(v or "").strip()]


# --- From the confirmed table to the input files (code) -------------------------------------------------------

def _parse(row: dict, text: str):
    text = text.strip()
    kind = row["kind"]
    if kind == "number":
        return float(text.replace("%", "").replace("−", "-").replace(",", ""))
    if kind == "int":
        return int(float(text))
    if kind == "date":
        return date.fromisoformat(text).isoformat()
    if kind == "bool":
        if text.lower() in ("yes", "y", "true"):
            return True
        if text.lower() in ("no", "n", "false"):
            return False
        raise ValueError("write yes or no")
    if kind == "choice":
        if text not in row["choices"]:
            raise ValueError(f"one of {', '.join(row['choices'])}")
        return text
    return text


def build_inputs(intake: dict, values: list[str]) -> Built:
    """ Check and convert the confirmed values; corrected values are marked "entered by user" """
    out = Built()
    parsed: dict = {}
    for row, text in zip(intake["rows"], values):
        text = str(text or "").strip()
        changed = text != row["value"]
        status = USER if changed and text else row["status"] if text else (MISSING if row["required"] else OPTIONAL)
        out.rows.append({"key": row["key"], "label": row["label"], "value": text, "status": status,
                         "source": "entered on the page" if changed and text else row["source"]})
        if not text:
            if row["required"]:
                out.problems.append(f"{row['label']}: required, please fill it in")
            continue
        try:
            parsed[row["key"]] = _parse(row, text)
        except ValueError as e:
            out.problems.append(f"{row['label']}: '{text}' is not valid ({e})")
            continue
        if changed:
            out.user_entered.append(row["key"])
    if out.problems:
        return out

    profile_keys = [s.key for s in PROFILE_FIELDS]
    profile = {k: parsed[k] for k in profile_keys if k in parsed}
    status = {r["key"]: r["status"] for r in intake["rows"]}
    profile["field_sources"] = {k: "user" if k in out.user_entered else "code" if status[k] == CODE else "ai_extracted"
                                for k in list(profile)}
    profile["secondary_objective"] = intake.get("secondary_objective")
    profile.setdefault("performance_fee", None)          # not established: recorded as null, never as no fee

    fs = dict(intake.get("factsheet") or {})
    series = {}
    for name, _, _ in SERIES:
        returns = {p: parsed.get(f"series.{name}.{p}") for p in ("1y", "3y", "5y")}
        if any(v is not None for v in returns.values()):
            old = (fs.get("series") or {}).get(name, {})
            series[name] = {**returns, "since_launch": old.get("since_launch"), "basis": "cumulative",
                            "pricing": old.get("pricing")}
    annualised = dict(fs.get("series_annualised") or {})
    for key in out.user_entered:
        if key.startswith("series."):
            annualised.pop(key.split(".")[1], None)    # a corrected cumulative return: code derives the annualised one
    factsheet = {**fs, "as_of_date": profile.get("as_of_date"), "currency": profile.get("currency"),
                 "series": series, "series_annualised": annualised, "source": "ai_extracted", "entered_by": "extractor",
                 "user_entered": [k.removeprefix("series.") for k in out.user_entered if k.startswith("series.")]}

    peers = []
    for i, origin in enumerate(intake.get("peer_origins", []), start=1):
        values = {k.split(".", 1)[1]: v for k, v in parsed.items() if k.startswith(f"peer{i}.")}
        if values.get("currency"):
            values["currency"] = values["currency"].upper()
        peers.append(peer_record(values, origin))
    try:
        FundProfile.model_validate(profile)
        FactsheetPerformance.model_validate(factsheet)
        for peer in peers:
            Peer.model_validate(peer)
    except ValueError as e:
        out.problems.append(f"The values do not fit together: {str(e)[:300]}")
        return out
    out.profile, out.factsheet, out.peers = profile, factsheet, peers
    return out


def write_inputs(built: Built, folder: Path) -> list[str]:
    """ Write the confirmed inputs as the JSON files the controller reads """
    folder.mkdir(parents=True, exist_ok=True)
    files = {"fund_profile.json": built.profile, "factsheet_performance.json": built.factsheet,
             "peer.json": built.peers or None}
    written = []
    for name, data in files.items():
        if data is not None:
            (folder / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            written.append(name)
    return written


# --- Checking the reading step against typed files (live test, CLI) --------------------------------------------

def _same(extracted: str, typed) -> bool:
    if typed is None:
        return extracted == ""
    if isinstance(typed, bool):
        return extracted == ("yes" if typed else "no")
    if isinstance(typed, (int, float)):
        try:
            return abs(float(extracted) - float(typed)) < 0.005
        except ValueError:
            return False
    return " ".join(str(extracted).lower().split()) == " ".join(str(typed).lower().split())


def differences(intake: dict, profile: dict, factsheet: dict) -> list[tuple[str, str, str]]:
    """ (field, what the agents read, what was typed) for every value that differs from the typed JSON files """
    out = []
    for row in intake["rows"]:
        key = row["key"]
        if key.startswith("series."):
            _, name, period = key.split(".")
            typed = (factsheet.get("series", {}).get(name) or {}).get(period)
        elif key.startswith("peer"):
            continue
        else:
            typed = profile.get(key)
        if not _same(row["value"], typed):
            out.append((row["label"], row["value"] or "(empty)", "" if typed is None else str(typed)))
    return out
