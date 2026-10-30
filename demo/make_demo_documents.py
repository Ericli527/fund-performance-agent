""" Builds the made-up demo documents from the demo price file, so the example files hang together:

- factsheet.pdf and factsheet_performance.json: the fund's 1, 3 and 5-year returns, calculated from prices.csv
  (rounded to 1 d.p., as a factsheet prints them);
- peer_factsheet.pdf: the made-up peer in peer.json.

Everything here is made up ("Sample World"), so it is safe in the public repository. Run from the repository root:

    PYTHONPATH=src python demo/make_demo_documents.py
"""
import json
from pathlib import Path
from xhtml2pdf import pisa
from fund_performance.calc import calculate
from fund_performance.config import load_thresholds
from fund_performance.io import read_json, read_prices

DEMO = Path(__file__).resolve().parent / "sample_index_fund"
STYLE = ("body { font-family: Helvetica; font-size: 10pt; color: #1d2733; } h1 { color: #1f3a5f; font-size: 16pt; } "
         "td, th { padding: 3px 8px; border-bottom: 0.5px solid #ccc; } .note { color: #a33; font-weight: bold; }")


def _pdf(html: str, path: Path) -> None:
    with open(path, "wb") as f:
        pisa.CreatePDF(f"<html><head><style>{STYLE}</style></head><body>{html}</body></html>", dest=f)


def main() -> None:
    profile = read_json(DEMO / "fund_profile.json")
    peer = read_json(DEMO / "peer.json")
    calc = calculate(read_prices(DEMO / "prices.csv").prices, profile, load_thresholds())
    cum = {s: {p: round(calc.figures[f"{s}.cum.{p}"].exact, 1) for p in ("1y", "3y", "5y")} for s in ("fund", "index")}
    ann5 = {s: round(calc.figures[f"{s}.ann.5y"].exact, 1) for s in ("fund", "index")}

    factsheet = {"as_of_date": profile.as_of_date.isoformat(), "currency": profile.currency, "source": "factsheet",
                 "entered_by": "manual",
                 "series": {"fund_nav": cum["fund"] | {"basis": "cumulative", "pricing": "market_close"},
                            "index": cum["index"] | {"basis": "cumulative"}}}
    (DEMO / "factsheet_performance.json").write_text(json.dumps(factsheet, indent=2) + "\n")

    rows = "".join(f"<tr><td>{p[:-1]} year{'s' if p != '1y' else ''}</td><td>{cum['fund'][p]:.1f}%</td>"
                   f"<td>{cum['index'][p]:.1f}%</td></tr>" for p in ("1y", "3y", "5y"))
    _pdf(f"""<p class="note">MADE-UP EXAMPLE FOR THE DEMO. NOT A REAL FUND.</p>
<h1>{profile.fund_name}</h1>
<p>Factsheet as at 30 September 2026 · ISIN {profile.isin} · Share class {profile.share_class} · Currency {profile.currency}
· Accumulation · Not currency hedged</p>
<p><b>Objective:</b> {profile.objective_text}</p>
<p><b>Benchmark:</b> {profile.benchmark_name}. <b>Share class launch:</b> 2 January 2018.
<b>Pricing:</b> the fund is priced at market close.</p>
<p><b>Ongoing charges (OCF):</b> {profile.ocf_pct:.2f}% a year. <b>Performance fee:</b> none.</p>
<h3>Cumulative performance to 30 September 2026</h3>
<table><tr><th>Period</th><th>Fund</th><th>Index</th></tr>{rows}</table>
<p>5 years annualised: fund {ann5['fund']:.1f}%, index {ann5['index']:.1f}%.</p>""", DEMO / "factsheet.pdf")

    r = peer.returns
    cum_peer = {p: ((1 + v / 100) ** int(p[0]) - 1) * 100 for p, v in (("1y", r.y1), ("3y", r.y3), ("5y", r.y5))}
    _pdf(f"""<p class="note">MADE-UP EXAMPLE FOR THE DEMO. NOT A REAL FUND.</p>
<h1>{peer.name}</h1>
<p>Factsheet as at 30 September 2026 · Share class {peer.share_class} · Currency {peer.currency}</p>
<p><b>Ongoing charges (OCF):</b> {peer.ocf_pct:.2f}% a year.</p>
<h3>Performance to 30 September 2026</h3>
<table><tr><th>Period</th><th>Cumulative</th><th>Annualised</th></tr>
<tr><td>1 year</td><td>{cum_peer['1y']:.1f}%</td><td>{r.y1:.1f}%</td></tr>
<tr><td>3 years</td><td>{cum_peer['3y']:.1f}%</td><td>{r.y3:.1f}%</td></tr>
<tr><td>5 years</td><td>{cum_peer['5y']:.1f}%</td><td>{r.y5:.1f}%</td></tr></table>""", DEMO / "peer_factsheet.pdf")
    print("Wrote factsheet_performance.json, factsheet.pdf and peer_factsheet.pdf in", DEMO)


if __name__ == "__main__":
    main()
