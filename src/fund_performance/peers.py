""" Peer funds (B1 and B2): which peers are used, and how each is compared with the fund. All code, no AI

- Approved peers: config/peers.yaml lists peers per benchmark; their factsheets are in data/peers/ (gitignored).
  They are used when the user gives no peer. The fund itself is never its own peer.
- Currency: a peer's returns are used only if they are in the fund's currency. Its ongoing charge is always used,
  since a fee is a percentage and does not depend on the currency.
- Pricing time: noon prices are compared with the fund's noon NAV, market-close prices with the fund's PNAV
  (market close). The basis used is shown.
- Share class: the type (retail or institutional) and the minimum investment are recorded; an institutional class
  is kept with a note, because its fee is lower than retail investors could get.
- Income vs accumulation: comparable on a total-return basis; the type is shown.
- Several peers: Value uses the average gap over the peers whose returns can be used; Fees uses the average fee.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
import os
from pathlib import Path
import re
from fund_performance.calc import annualise
from fund_performance.config import PEER_FOLDER, ApprovedPeer, BenchmarkPeers, PeersConfig
from fund_performance.models import DataFlag, FundProfile, Peer
from fund_performance.precedence import PRICE_SERIES, ReportedFigures

INSTITUTIONAL_NOTE = "institutional share class: its fee is lower than retail investors could get"
PERIODS = (1, 3, 5)
DOC_SUFFIXES = (".pdf", ".docx")


def two_dp(value: float) -> float:
    """ Rounded half up to the stored 2 d.p. (0.045 -> 0.05; plain round() gives 0.04 in floating point) """
    return float(Decimal(repr(round(value, 9))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- Approved peers (config/peers.yaml) ------------------------------------------------------------------------

def _text_of(path: Path) -> str:
    from fund_performance.io import read_document
    try:
        return read_document(path)
    except Exception:                               # noqa: BLE001 - an unreadable file is simply not a match
        return ""


def peer_folder() -> Path:
    """ data/peers/, or the folder in FUND_PEER_FOLDER (tests point it at an empty folder) """
    return Path(os.environ["FUND_PEER_FOLDER"]) if os.getenv("FUND_PEER_FOLDER") else PEER_FOLDER


def find_factsheet(peer: ApprovedPeer, folder: Path) -> Path | None:
    """ The peer's factsheet in data/peers/: the configured file, else a file whose name or text has the ISIN """
    if not folder.is_dir():
        return None
    if peer.factsheet and (folder / peer.factsheet).is_file():
        return folder / peer.factsheet
    docs = sorted(p for p in folder.iterdir() if p.suffix.lower() in DOC_SUFFIXES)
    isin = peer.isin.lower()
    return (next((p for p in docs if isin in p.name.lower()), None)
            or next((p for p in docs if isin in _text_of(p).lower()), None))


@dataclass
class ApprovedPeers:
    group: BenchmarkPeers | None
    files: list[tuple[ApprovedPeer, Path]] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)


def approved_peers(config: PeersConfig, benchmark_name: str | None, fund_isin: str | None = None,
                   folder: Path | None = None) -> ApprovedPeers:
    """ The approved peers for the fund's benchmark whose factsheets were found (the fund itself left out) """
    group = config.for_benchmark(benchmark_name)
    folder = folder or peer_folder()
    out = ApprovedPeers(group)
    if group is None:
        return out
    for peer in group.peers:
        if fund_isin and peer.isin.upper() == fund_isin.upper():
            continue
        path = find_factsheet(peer, folder)
        if path is None:
            out.flags.append(DataFlag(check="peers", level="info", message=(
                f"Approved peer {peer.name} ({peer.isin}): factsheet not found in data/peers/, so it is left out")))
        else:
            out.files.append((peer, path))
    return out


def investor_type(share_class: str | None, minimum_investment: str | None) -> str | None:
    """ "institutional" if the share class name says so or the minimum investment is £1m or more (code) """
    name = (share_class or "").lower()
    if re.search(r"\binst(itutional)?\b|\binst\.", name):
        return "institutional"
    amount = _amount(minimum_investment)
    if amount is not None:
        return "institutional" if amount >= 1_000_000 else "retail"
    return "retail" if name else None


def _amount(text: str | None) -> float | None:
    """ '£10m' -> 10000000, '£1,000' -> 1000, 'USD 5 million' -> 5000000 """
    if not text:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(m\b|mn\b|million|k\b|bn\b|billion)?", text.lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    return value * {"m": 1e6, "mn": 1e6, "million": 1e6, "k": 1e3, "bn": 1e9, "billion": 1e9}.get(m.group(2) or "", 1)


# --- Comparing each peer with the fund ---------------------------------------------------------------------------

PRICING_WORDS = {"midday": "noon", "market_close": "market close"}


@dataclass
class PeerRow:
    peer: Peer
    returns: dict[int, float | None]           # the peer's annualised returns, % a year (1 year: the 1-year return)
    fund_series: str                           # the fund series it is compared with: fund_nav or fund_pnav
    fund_returns: dict[int, float | None]
    basis: str                                 # e.g. "noon NAV vs noon NAV"
    used_for_returns: bool
    excluded: str | None = None                # why its returns are not used
    notes: list[str] = field(default_factory=list)

    @property
    def gap(self) -> float | None:
        """ Peer minus fund over the main period, % a year (positive: the peer did better) """
        return None if not self.used_for_returns else self._gap

    _gap: float | None = None


@dataclass
class PeerComparison:
    rows: list[PeerRow]
    years: int
    flags: list[DataFlag] = field(default_factory=list)

    @property
    def used(self) -> list[PeerRow]:
        return [r for r in self.rows if r.used_for_returns]

    @property
    def average_gap(self) -> float | None:
        gaps = [r.gap for r in self.used]
        return two_dp(sum(gaps) / len(gaps)) if gaps else None

    @property
    def average_ocf(self) -> float | None:
        fees = [r.peer.ocf_pct for r in self.rows]
        return two_dp(sum(fees) / len(fees)) if fees else None

    @property
    def notes(self) -> list[str]:
        return [f"{r.peer.name}: {n}" for r in self.rows for n in r.notes]


def peer_annualised(peer: Peer, years: int) -> float | None:
    """ The official annualised figure when given, else annualised from the cumulative one """
    if peer.returns_annualised is not None and getattr(peer.returns_annualised, f"y{years}") is not None:
        return getattr(peer.returns_annualised, f"y{years}")
    value = getattr(peer.returns, f"y{years}")
    if value is None:
        return None
    return value if peer.returns.basis == "annualised" or years == 1 else annualise(value, years)


def _fund_return(reported: ReportedFigures, series: str, years: int) -> float | None:
    return reported.value(f"{series}.cum.1y" if years == 1 else f"{series}.ann.{years}y")


def _basis(peer: Peer, profile: FundProfile, reported: ReportedFigures, years: int) -> tuple[str, str, list[str]]:
    """ (fund series, basis in words, notes): noon with noon, market close with the fund's PNAV """
    fund_time, peer_time = profile.pricing_point, peer.pricing_point
    if peer_time is None:
        return PRICE_SERIES, f"fund {PRICING_WORDS[fund_time]} NAV; peer pricing time not stated", [
            "pricing time not stated, so the timing may differ"]
    if peer_time == fund_time:
        words = PRICING_WORDS[fund_time]
        return PRICE_SERIES, f"{words} NAV vs {words} NAV" if fund_time == "midday" else "market close vs market close", []
    if peer_time == "market_close":
        if _fund_return(reported, "fund_pnav", years) is not None:
            return "fund_pnav", "market close: fund PNAV vs peer", []
        return PRICE_SERIES, "fund noon NAV vs peer market close (no PNAV)", [
            "priced at market close and the fund has no market-close figures, so the timing differs"]
    return PRICE_SERIES, "fund market close vs peer noon", ["priced at noon and the fund at market close"]


def compare_peers(peers: list[Peer], profile: FundProfile, reported: ReportedFigures) -> PeerComparison:
    years = profile.time_horizon_years
    out = PeerComparison([], years)
    for peer in peers:
        series, basis, notes = _basis(peer, profile, reported, years)
        row = PeerRow(peer, {n: peer_annualised(peer, n) for n in PERIODS}, series,
                      {n: _fund_return(reported, series, n) for n in PERIODS}, basis, True, notes=list(notes))
        if peer.currency.upper() != profile.currency.upper():
            row.used_for_returns = False
            row.excluded = f"returns in {peer.currency.upper()}, not {profile.currency.upper()}"
            out.flags.append(DataFlag(check="peers", level="info", message=(
                f"Peer {peer.name}: its returns are in {peer.currency.upper()} and the fund's in "
                f"{profile.currency.upper()}, so they are left out of the value comparison; its ongoing charge "
                f"({peer.ocf_pct:.2f}%) is still used for fees")))
        elif row.returns.get(years) is None or row.fund_returns.get(years) is None:
            row.used_for_returns = False
            row.excluded = f"no {years}-year return for the {'peer' if row.returns.get(years) is None else 'fund'}"
        else:
            row._gap = row.returns[years] - row.fund_returns[years]
        if peer.investor_type == "institutional":
            row.notes.append(INSTITUTIONAL_NOTE)
        if peer.distribution and peer.distribution != profile.distribution:
            row.notes.append(f"{peer.distribution} share class: compared on a total-return basis")
        if peer.benchmark_name and _plain_name(peer.benchmark_name) != _plain_name(profile.benchmark_name):
            row.notes.append(f"follows {peer.benchmark_name}, a different benchmark variant from the fund's "
                             f"{profile.benchmark_name} (for information: the comparison and ratings are unchanged)")
        out.rows.append(row)
    return out


def _plain_name(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def as_list(peers) -> list[Peer]:
    """ None, one peer or a list of peers, as a list """
    if peers is None:
        return []
    return list(peers) if isinstance(peers, (list, tuple)) else [peers]
