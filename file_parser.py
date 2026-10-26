from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from docx import Document

MAX_DOC_CHARS = 15000

# Each table type: required columns (standard name -> accepted names), then optional columns
NAV_ALIASES = {
    "date": ["date", "as_of", "as_of_date"],
    "fund": ["fund", "fund_nav", "nav", "fund_price"],
    "benchmark": ["benchmark", "benchmark_nav", "index", "benchmark_price"],
}
ATTRIBUTION_ALIASES = {
    "sector": ["sector", "segment", "asset_class", "region"],
    "fund_weight": ["fund_weight", "portfolio_weight", "wp"],
    "benchmark_weight": ["benchmark_weight", "wb"],
    "fund_return": ["fund_return", "portfolio_return", "rp"],
    "benchmark_return": ["benchmark_return", "rb"],
}
WEIGHT_OPTIONAL = {"benchmark_weight": ["benchmark_weight", "index_weight", "wb"]}
EXPOSURE_ALIASES = {
    "category": ["category", "type", "exposure_type"],
    "name": ["name", "item", "label"],
    "fund_weight": ["fund_weight", "portfolio_weight", "weight"],
}
SECTOR_ALIASES = {"name": ["sector", "industry"], "fund_weight": ["fund_weight", "portfolio_weight", "weight"]}
COUNTRY_ALIASES = {"name": ["country", "region", "geography"], "fund_weight": ["fund_weight", "portfolio_weight", "weight"]}
HOLDINGS_ALIASES = {
    "name": ["security", "holding", "security_name", "name", "company"],
    "fund_weight": ["fund_weight", "portfolio_weight", "weight"],
}
FACTS_ALIASES = {"field": ["field", "item", "label", "key"], "value": ["value"]}
PEER_ALIASES = {"name": ["peer", "peer_name", "name"], "ticker": ["ticker", "symbol", "isin"]}


@dataclass
class ParsedFiles:
    nav: pd.DataFrame | None = None
    attribution: pd.DataFrame | None = None
    attribution_period: str = ""
    holdings: pd.DataFrame | None = None
    sectors: pd.DataFrame | None = None
    countries: pd.DataFrame | None = None
    peers: pd.DataFrame | None = None
    fund_facts: list[tuple[str, str]] = field(default_factory=list)
    documents: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


def _match_columns(df: pd.DataFrame, aliases: dict[str, list[str]],
                   optional: dict[str, list[str]] | None = None) -> pd.DataFrame | None:
    """ Rename columns to standard names, or return None if any required column is missing """
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    mapping = {}
    for standard, options in aliases.items():
        found = next((c for c in options if c in df.columns), None)
        if found is None:
            return None
        mapping[found] = standard
    for standard, options in (optional or {}).items():
        found = next((c for c in options if c in df.columns), None)
        if found is not None:
            mapping[found] = standard
    return df[list(mapping)].rename(columns=mapping)


def weights_table(df: pd.DataFrame) -> pd.DataFrame:
    """ Clean a name/weight table: weights as decimals, benchmark column always present """
    df = df.copy()
    if "benchmark_weight" not in df.columns:
        df["benchmark_weight"] = float("nan")
    df["fund_weight"] = pd.to_numeric(df["fund_weight"], errors="coerce")
    df["benchmark_weight"] = pd.to_numeric(df["benchmark_weight"], errors="coerce")
    df = df.dropna(subset=["fund_weight"])
    # Weights summing to more than 1.5 are in percent
    if df["fund_weight"].sum() > 1.5:
        df[["fund_weight", "benchmark_weight"]] = df[["fund_weight", "benchmark_weight"]] / 100
    df["relative"] = df["fund_weight"] - df["benchmark_weight"]
    return df[["name", "fund_weight", "benchmark_weight", "relative"]].reset_index(drop=True)


def _classify_table(df: pd.DataFrame, name: str, parsed: ParsedFiles) -> None:
    """ Decide what kind of table this is, checking the most specific formats first """
    if (nav := _match_columns(df, NAV_ALIASES)) is not None:
        nav["date"] = pd.to_datetime(nav["date"])
        parsed.nav = nav.sort_values("date").dropna().reset_index(drop=True)
        parsed.notes.append(f"{name}: read as NAV series ({len(parsed.nav)} rows)")
    elif (attr := _match_columns(df, ATTRIBUTION_ALIASES, {"period": ["period", "attribution_period"]})) is not None:
        if "period" in attr.columns:
            # An optional period column (e.g. "Q3 2026") says what time the effects cover
            periods = attr.pop("period").dropna().astype(str).unique()
            parsed.attribution_period = periods[0] if len(periods) else ""
        parsed.attribution = attr.dropna().reset_index(drop=True)
        parsed.notes.append(f"{name}: read as attribution data ({len(parsed.attribution)} segments)")
    elif (exp := _match_columns(df, EXPOSURE_ALIASES, WEIGHT_OPTIONAL)) is not None:
        category = exp["category"].astype(str).str.lower()
        for attr_name, words in (("sectors", ("sector", "industry")), ("countries", ("country", "region", "geograph"))):
            rows = exp[category.str.contains("|".join(words))]
            if not rows.empty:
                setattr(parsed, attr_name, weights_table(rows))
                parsed.sources[attr_name] = name
        parsed.notes.append(f"{name}: read as exposure data")
    elif (peers := _match_columns(df, PEER_ALIASES, {"ocf": ["ocf", "ongoing_charge", "ongoing_charges", "fee"]})) is not None:
        if "ocf" not in peers.columns:
            peers["ocf"] = float("nan")
        peers["ocf"] = pd.to_numeric(peers["ocf"].astype(str).str.rstrip("%"), errors="coerce")
        parsed.peers = peers.dropna(subset=["ticker"]).reset_index(drop=True)
        parsed.notes.append(f"{name}: read as peer list ({len(parsed.peers)} peer(s))")
    elif (holdings := _match_columns(df, HOLDINGS_ALIASES, WEIGHT_OPTIONAL)) is not None and "sector" not in df.columns:
        parsed.holdings = weights_table(holdings).sort_values("fund_weight", ascending=False).reset_index(drop=True)
        parsed.sources["holdings"] = name
        parsed.notes.append(f"{name}: read as holdings ({len(parsed.holdings)} rows)")
    elif (sectors := _match_columns(df, SECTOR_ALIASES, WEIGHT_OPTIONAL)) is not None:
        parsed.sectors = weights_table(sectors)
        parsed.sources["sectors"] = name
        parsed.notes.append(f"{name}: read as sector exposure")
    elif (countries := _match_columns(df, COUNTRY_ALIASES, WEIGHT_OPTIONAL)) is not None:
        parsed.countries = weights_table(countries)
        parsed.sources["countries"] = name
        parsed.notes.append(f"{name}: read as country exposure")
    elif (facts := _match_columns(df, FACTS_ALIASES)) is not None:
        parsed.fund_facts = [(str(r.field), str(r.value)) for r in facts.dropna().itertuples()]
        parsed.sources["fund_facts"] = name
        parsed.notes.append(f"{name}: read as fund facts ({len(parsed.fund_facts)} items)")
    else:
        # Unknown table: pass it to the writer as text instead
        parsed.documents.append((name, df.head(50).to_string()))
        parsed.notes.append(f"{name}: table not recognised, used as a reference document")


def parse_files(paths: list[str] | None) -> ParsedFiles:
    """ Read uploaded CSV, Excel, PDF, Word and text files """
    parsed = ParsedFiles()
    for path in paths or []:
        p = Path(path)
        suffix = p.suffix.lower()
        try:
            if suffix == ".csv":
                _classify_table(pd.read_csv(p), p.name, parsed)
            elif suffix in (".xlsx", ".xls"):
                for sheet, df in pd.read_excel(p, sheet_name=None).items():
                    _classify_table(df, f"{p.name} [{sheet}]", parsed)
            elif suffix == ".pdf":
                text = "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)
                parsed.documents.append((p.name, text[:MAX_DOC_CHARS]))
                parsed.notes.append(f"{p.name}: read as a document")
            elif suffix == ".docx":
                text = "\n".join(para.text for para in Document(p).paragraphs)
                parsed.documents.append((p.name, text[:MAX_DOC_CHARS]))
                parsed.notes.append(f"{p.name}: read as a document")
            elif suffix in (".txt", ".md"):
                parsed.documents.append((p.name, p.read_text(errors="ignore")[:MAX_DOC_CHARS]))
                parsed.notes.append(f"{p.name}: read as a document")
            else:
                parsed.notes.append(f"{p.name}: file type not supported, skipped")
        except Exception as e:
            parsed.notes.append(f"{p.name}: could not be read ({e})")
    return parsed
