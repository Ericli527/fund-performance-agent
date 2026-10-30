""" The real-fund demo library (Stage 4B)

Each demo is described by a manifest in demo/library/<id>.yaml: metadata only (names, ISIN, review date, sources,
disclosures), safe to publish. Its inputs and documents are not in the public repository: they live in the private
demo folder (data/demos/<id>/, gitignored, or the folder in FUND_DEMO_DATA). A demo whose files are missing is shown
as unavailable; nothing breaks.

Two ways to run one:
- Quick Demo (default): the prevalidated inputs (price file and JSON typed from the documents, checked by code) run
  offline: no AI, the same result every time, a few seconds.
- Live AI Demo: the documents are read by the AI agents, as for an uploaded fund (needs AI runs to be switched on,
  and counts against the daily limit). Its figures are marked as read by AI.

Code also checks the quick inputs: the 1, 3 and 5-year returns calculated from the prices (to the review date) must
match the factsheet within the manifest's tolerance.
"""
from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "demo" / "library"
DATA_ENV = "FUND_DEMO_DATA"
NOTICE = ("Historical data to the review date, typed from public documents and checked by code. For demonstration "
          "only; not investment advice.")


def data_folder() -> Path:
    """ data/demos/, or the folder in FUND_DEMO_DATA """
    return Path(os.getenv(DATA_ENV) or ROOT / "data" / "demos")


@dataclass
class Demo:
    id: str
    title: str
    subtitle: str
    fund_name: str
    share_class: str
    isin: str
    benchmark: str
    peer: str
    review_date: date
    quick: dict
    live: dict
    sources: list[dict]
    disclosures: list[str]
    folder: Path
    order: int = 99
    ticker: str | None = None
    return_check_tolerance_pp: float = 0.05
    fallback: bool = False          # shown only where no real-fund demo is installed (the made-up fund)
    location: str | None = None     # a folder in the repository (public, made-up data) instead of the private one
    notice: str = NOTICE

    def path(self, relative: str) -> Path:
        return self.folder / relative

    @property
    def quick_files(self) -> dict:
        return {"price": self.path(self.quick["prices"]), "json": [self.path(p) for p in self.quick.get("json", [])]}

    @property
    def live_files(self) -> dict:
        live = self.live
        return {"price": self.path(live["prices"]), "factsheet": self.path(live["factsheet"]),
                "kid": self.path(live["kid"]) if live.get("kid") else None,
                "peers": [self.path(p) for p in live.get("peers", [])]}

    def missing(self) -> list[str]:
        """ The private files this demo needs that are not there (relative names only) """
        wanted = [self.quick["prices"], *self.quick.get("json", []), self.live["prices"], self.live["factsheet"],
                  *([self.live["kid"]] if self.live.get("kid") else []), *self.live.get("peers", [])]
        return [w for w in dict.fromkeys(wanted) if not self.path(w).is_file()]

    @property
    def available(self) -> bool:
        return not self.missing()


def load_demos(library: Path | None = None, data: Path | None = None) -> list[Demo]:
    """ Every demo in the library, in order (available or not) """
    library, data = library or LIBRARY, data or data_folder()
    demos = []
    for path in sorted(library.glob("*.yaml")):
        m = yaml.safe_load(path.read_text(encoding="utf-8"))
        m["review_date"] = date.fromisoformat(str(m["review_date"]))
        folder = ROOT / m["location"] if m.get("location") else data / m["id"]
        demos.append(Demo(folder=folder, **m))
    return sorted(demos, key=lambda d: (d.order, d.id))


def shown_demos(demos: list[Demo] | None = None) -> list[Demo]:
    """ The demos the page offers: the real ones whose private files are installed, else the made-up fallback """
    demos = load_demos() if demos is None else demos
    real = [d for d in demos if d.available and not d.fallback]
    return real or [d for d in demos if d.available and d.fallback]


def find_demo(demo_id: str, demos: list[Demo] | None = None) -> Demo | None:
    return next((d for d in (demos if demos is not None else load_demos()) if d.id == demo_id), None)


def _same_bytes(a, b: Path) -> bool:
    try:
        return a is not None and Path(a).read_bytes() == Path(b).read_bytes()
    except OSError:
        return False


def matching_demo(price, json_files, demos: list[Demo] | None = None) -> Demo | None:
    """ The available demo whose quick inputs these are, byte for byte (so an edited file is a normal review) """
    json_files = [p for p in (json_files or []) if p]
    for demo in (demos if demos is not None else load_demos()):
        if not demo.available:
            continue
        files = demo.quick_files
        if (_same_bytes(price, files["price"]) and len(json_files) == len(files["json"])
                and all(any(_same_bytes(p, ref) for p in json_files) for ref in files["json"])):
            return demo
    return None


@dataclass
class ReturnCheck:
    period: str
    calculated: float | None
    published: float | None
    basis: str                       # "a year" or "cumulative": the factsheet's own basis
    tolerance_pp: float
    notes: list[str] = field(default_factory=list)

    @property
    def difference(self) -> float | None:
        return None if self.calculated is None or self.published is None else self.calculated - self.published

    @property
    def ok(self) -> bool:
        return self.difference is not None and abs(round(self.difference, 6)) <= self.tolerance_pp


def return_checks(demo: Demo) -> list[ReturnCheck]:
    """ 1, 3 and 5-year fund returns from the prices (to the review date) vs the factsheet, on its own basis """
    from fund_performance.calc import annualise, cumulative_return
    from fund_performance.checks import after_review_date
    from fund_performance.io import read_json, read_prices
    files = demo.quick_files
    profile = next(m for m in map(read_json, files["json"]) if type(m).__name__ == "FundProfile")
    factsheet = next(m for m in map(read_json, files["json"]) if type(m).__name__ == "FactsheetPerformance")
    prices, cut = after_review_date(read_prices(files["price"]).prices, profile.as_of_date)
    levels = prices.set_index("date")["nav"]
    published = factsheet.series["fund_nav"]
    annualised = published.basis == "annualised"
    out = []
    for n in (1, 3, 5):
        cum = cumulative_return(levels, n, pd.Timestamp(profile.as_of_date))
        calc = None if cum is None else (annualise(cum, n) if annualised and n > 1 else cum)
        out.append(ReturnCheck(f"{n}y", None if calc is None else round(calc, 4), getattr(published, f"y{n}"),
                               "a year" if annualised and n > 1 else "cumulative", demo.return_check_tolerance_pp,
                               [f.message for f in cut]))
    return out

