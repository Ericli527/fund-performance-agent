""" File reader (spec Section 3.1): detects each file's type and reads price files carefully

Dates are parsed with an explicit format that is logged; an ambiguous file stops with an error
instead of being guessed. Trailing empty columns are removed, '-' and blanks become missing values,
and prices are sorted ascending by date.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import csv
import json
import re
from typing import Literal
import pandas as pd
from pypdf import PdfReader
from docx import Document
from fund_performance.models import FactsheetPerformance, FundProfile, Peer

FileType = Literal["prices", "factsheet_performance", "fund_profile", "peer", "document", "unknown"]
Frequency = Literal["daily", "monthly", "unknown"]

MISSING_TOKENS = {"", "-", "–", "—", "n/a", "na", "nan", "null"}
DATE_ALIASES = ["date", "as_of", "as_of_date", "price_date", "valuation_date"]
NAV_ALIASES = ["nav", "price", "nav_price", "fund_nav", "close"]
INDEX_ALIASES = ["index_level", "index", "benchmark", "benchmark_level"]
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}

# Day/month order, named as people write them
DMY, MDY, YMD = "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"


class AmbiguousDatesError(ValueError):
    """ Both day/month orders fit the data; the user must say which one is right """


@dataclass
class PriceData:
    """ A price file after reading: one row per date with 'nav' and, if supplied, 'index_level' """
    prices: pd.DataFrame
    source_file: str
    date_format: str
    log: list[str] = field(default_factory=list)

    @property
    def has_index(self) -> bool:
        return "index_level" in self.prices.columns

    @property
    def frequency(self) -> Frequency:
        return detect_frequency(self.prices["date"])


def _normalise(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def detect_frequency(dates: pd.Series) -> Frequency:
    """ Daily or monthly, from the typical gap between observations """
    if len(dates) < 2:
        return "unknown"
    gap = dates.sort_values().diff().dt.days.median()
    if gap <= 7:
        return "daily"
    if 25 <= gap <= 35:
        return "monthly"
    return "unknown"


def _one_per_month_in_order(dates: pd.Series) -> bool:
    months = dates.dt.year * 12 + dates.dt.month
    return bool(dates.is_monotonic_increasing and months.is_unique)


def parse_dates(values: pd.Series) -> tuple[pd.Series, str, str]:
    """ Parse date strings with an explicit format. Returns (dates, format, reason) """
    text = values.astype(str).str.strip()
    if text.str.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}").all():
        return pd.to_datetime(text, format="%Y-%m-%d"), YMD, "ISO dates"
    parts = text.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$")
    if parts.isna().any().any():
        bad = text[parts.isna().any(axis=1)].head(3).tolist()
        raise ValueError(f"Dates not in a recognised format, e.g. {bad}")
    first, second = parts[0].astype(int), parts[1].astype(int)
    year = "%Y" if parts[2].str.len().eq(4).all() else "%y"
    sep = re.search(r"[/.\-]", text.iloc[0]).group()
    formats = {DMY: f"%d{sep}%m{sep}{year}", MDY: f"%m{sep}%d{sep}{year}"}
    if (first > 12).any() and (second > 12).any():
        raise ValueError("Dates have values above 12 in both the first and second position")
    if (first > 12).any():
        return pd.to_datetime(text, format=formats[DMY]), DMY, "a value above 12 appears in the first position"
    if (second > 12).any():
        return pd.to_datetime(text, format=formats[MDY]), MDY, "a value above 12 appears in the second position"
    # Every value is 12 or below: keep the order that gives one price per month in date order
    fits = {}
    for name, fmt in formats.items():
        try:
            dates = pd.to_datetime(text, format=fmt)
        except ValueError:
            continue
        if _one_per_month_in_order(dates):
            fits[name] = dates
    if len(fits) == 1:
        name, dates = fits.popitem()
        return dates, name, "only this order gives one price per month in date order"
    raise AmbiguousDatesError(
        "Cannot tell whether dates are DD/MM/YYYY or MM/DD/YYYY: "
        + ("both orders fit" if fits else "neither order gives one price per month")
        + ". Please confirm the date format.")


def _to_number(values: pd.Series, column: str) -> pd.Series:
    """ Numbers as floats; '-' and blanks become missing; anything else unreadable stops the run """
    text = values.astype(str).str.strip()
    missing = text.str.lower().isin(MISSING_TOKENS) | values.isna()
    numbers = pd.to_numeric(text.where(~missing), errors="coerce")
    bad = text[numbers.isna() & ~missing]
    if not bad.empty:
        raise ValueError(f"Column '{column}' has values that are not numbers: {bad.head(3).tolist()}")
    return numbers


def _find(columns: list[str], aliases: list[str]) -> str | None:
    return next((c for c in aliases if c in columns), None)


def _read_csv(path: Path, log: list[str]) -> pd.DataFrame:
    """ Read a CSV as text. Rows ending with a comma carry an extra empty field; it is removed and logged.
    (pandas would otherwise shift every column by one, or drop the field without saying so.) """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if any(cell.strip() for cell in r)]
    header, body = rows[0], rows[1:]
    while header and not header[-1].strip():
        header = header[:-1]
    width = len(header)
    extra = [r[width:] for r in body if len(r) > width]
    if any(cell.strip() for cells in extra for cell in cells):
        raise ValueError(f"{path.name}: some rows have more values than there are column names")
    if extra:
        log.append(f"Trailing comma: removed an empty extra field from {len(extra)} row(s)")
    return pd.DataFrame([(r + [""] * width)[:width] for r in body], columns=header, dtype=str)


def _read_table(path: Path, log: list[str] | None = None) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return _read_csv(path, log if log is not None else [])
    return pd.read_excel(path, dtype=object)


def read_prices(path: str | Path) -> PriceData:
    """ Read a CSV or Excel price file with columns date, nav and optional index_level (spec 3.1) """
    path = Path(path)
    log: list[str] = []
    raw = _read_table(path, log)

    # Strip columns with no name and no values (e.g. a trailing empty column in Excel)
    empty = [c for c in raw.columns if (str(c).strip() == "" or str(c).startswith("Unnamed"))
             and (raw[c].isna() | raw[c].astype(str).str.strip().eq("")).all()]
    if empty:
        raw = raw.drop(columns=empty)
        log.append(f"Removed {len(empty)} empty column(s)")
    raw.columns = [_normalise(c) for c in raw.columns]
    columns = list(raw.columns)

    date_col, nav_col = _find(columns, DATE_ALIASES), _find(columns, NAV_ALIASES)
    if date_col is None or nav_col is None:
        raise ValueError(f"{path.name}: needs a date column and a NAV column; found {columns}")
    index_col = _find([c for c in columns if c != nav_col], INDEX_ALIASES)

    if pd.api.types.is_datetime64_any_dtype(raw[date_col]) or raw[date_col].map(
            lambda v: isinstance(v, datetime)).all():
        dates, fmt, why = pd.to_datetime(raw[date_col]), "Excel date", "dates stored as dates in the spreadsheet"
    else:
        dates, fmt, why = parse_dates(raw[date_col])
    log.append(f"Date format: {fmt} ({why})")

    prices = pd.DataFrame({"date": dates, "nav": _to_number(raw[nav_col], nav_col)})
    if index_col is not None:
        prices["index_level"] = _to_number(raw[index_col], index_col)
    n_missing = int(prices.drop(columns="date").isna().sum().sum())
    if n_missing:
        log.append(f"{n_missing} '-' or blank value(s) read as missing")

    if prices["date"].duplicated().any():
        repeated = prices.loc[prices["date"].duplicated(), "date"].dt.date.tolist()
        raise ValueError(f"{path.name}: the same date appears more than once: {repeated[:3]}")
    if not prices["date"].is_monotonic_increasing:
        log.append("Rows sorted into date order")
    prices = prices.sort_values("date").reset_index(drop=True)
    log.append(f"{len(prices)} rows, {prices['date'].iloc[0]:%Y-%m-%d} to {prices['date'].iloc[-1]:%Y-%m-%d}")
    return PriceData(prices=prices, source_file=path.name, date_format=fmt, log=log)


def detect_file_type(path: str | Path) -> FileType:
    """ What kind of input a file is, from its name and content """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):           # peer.json may hold several peers
            ok = data and all(isinstance(d, dict) and {"ocf_pct", "returns"} <= set(d) for d in data)
            return "peer" if ok else "unknown"
        keys = set(data)
        if "series" in keys:
            return "factsheet_performance"
        if {"objective_type", "objective_text"} & keys:
            return "fund_profile"
        if {"ocf_pct", "returns"} <= keys:
            return "peer"
        return "unknown"
    if suffix in TABLE_SUFFIXES:
        columns = [_normalise(c) for c in _read_table(path).columns]
        return "prices" if _find(columns, DATE_ALIASES) and _find(columns, NAV_ALIASES) else "unknown"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    return "unknown"


def read_json(path: str | Path) -> FactsheetPerformance | FundProfile | Peer:
    """ Read and validate one of the JSON inputs from spec Section 2 """
    models = {"factsheet_performance": FactsheetPerformance, "fund_profile": FundProfile, "peer": Peer}
    kind = detect_file_type(path)
    if kind not in models:
        raise ValueError(f"{Path(path).name}: not a fund profile, factsheet performance or peer file")
    return models[kind].model_validate_json(Path(path).read_text(encoding="utf-8"))


def read_peers(path: str | Path) -> list[Peer]:
    """ peer.json: one peer, or a list of peers """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Peer.model_validate(d) for d in (data if isinstance(data, list) else [data])]


def read_document(path: str | Path) -> str:
    """ Plain text from a PDF, Word or text document """
    return "\n".join(read_document_pages(path))


def _docx_text(path: Path) -> str:
    """ A Word document's paragraphs and tables, in document order (factsheets keep their figures in tables) """
    doc = Document(path)
    parts = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append("".join(t.text or "" for t in block.iter() if t.tag.endswith("}t")))
        elif tag == "tbl":
            for row in block.iter():
                if row.tag.endswith("}tr"):
                    cells = ["".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t"))
                             for cell in row if cell.tag.endswith("}tc")]
                    parts.append(" | ".join(c.strip() for c in cells))
    return "\n".join(p for p in parts if p.strip())


def read_document_pages(path: str | Path) -> list[str]:
    """ The text of each page (a PDF), or of the whole document as one page (Word, text) """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return [page.extract_text() or "" for page in PdfReader(path).pages]
    if suffix == ".docx":
        return [_docx_text(path)]
    if suffix in (".txt", ".md"):
        return [path.read_text(encoding="utf-8", errors="ignore")]
    raise ValueError(f"{path.name}: not a supported document type (PDF, Word .docx or text)")
