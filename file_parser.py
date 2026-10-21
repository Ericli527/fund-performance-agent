from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from docx import Document

MAX_DOC_CHARS = 15000

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


@dataclass
class ParsedFiles:
    nav: pd.DataFrame | None = None
    attribution: pd.DataFrame | None = None
    documents: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _match_columns(df: pd.DataFrame, aliases: dict[str, list[str]]) -> pd.DataFrame | None:
    """ Rename columns to standard names, or return None if any required column is missing """
    df = df.rename(columns=lambda c: str(c).strip().lower().replace(" ", "_"))
    mapping = {}
    for standard, options in aliases.items():
        found = next((c for c in options if c in df.columns), None)
        if found is None:
            return None
        mapping[found] = standard
    return df[list(mapping)].rename(columns=mapping)


def _classify_table(df: pd.DataFrame, name: str, parsed: ParsedFiles) -> None:
    """ Decide whether a table is a NAV series or attribution data """
    nav = _match_columns(df, NAV_ALIASES)
    if nav is not None:
        nav["date"] = pd.to_datetime(nav["date"])
        parsed.nav = nav.sort_values("date").dropna().reset_index(drop=True)
        parsed.notes.append(f"{name}: read as NAV series ({len(parsed.nav)} rows)")
        return
    attribution = _match_columns(df, ATTRIBUTION_ALIASES)
    if attribution is not None:
        parsed.attribution = attribution.dropna().reset_index(drop=True)
        parsed.notes.append(f"{name}: read as attribution data ({len(parsed.attribution)} segments)")
        return
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
            elif suffix == ".docx":
                text = "\n".join(para.text for para in Document(p).paragraphs)
                parsed.documents.append((p.name, text[:MAX_DOC_CHARS]))
            elif suffix in (".txt", ".md"):
                parsed.documents.append((p.name, p.read_text(errors="ignore")[:MAX_DOC_CHARS]))
            else:
                parsed.notes.append(f"{p.name}: file type not supported, skipped")
        except Exception as e:
            parsed.notes.append(f"{p.name}: could not be read ({e})")
    return parsed
