""" Documents route (step 11 update): reading the documents (agents mocked), the table to confirm, and the inputs
written from it, with corrected values marked "entered by user" """
import asyncio
import json
from pathlib import Path
from fund_performance.intake import (AI, CODE, MISSING, NOT_FOUND, USER, build_inputs, locate, missing,
                                     read_documents, table, write_inputs)
from fund_performance.models import FactsheetPerformance, FundProfile, Peer
import pytest
from conftest import TEST1, FakeRun, requires_test1
from test_agent_extractor import output

FACTSHEET = """Sample Fund A Acc factsheet, 30.09.2026. ISIN XX0000000001. Ongoing charges 0.10%.
The fund aims to track the Sample World Index over 5 years or more.
Cumulative growth (%): Fund NAV 1yr 10.0 3yr 30.0 5yr 50.0. Index 1yr 10.1 3yr 30.4 5yr 50.8."""
PEER_SHEET = "Peer Tracker B Acc factsheet. Ongoing charges 0.05%. Cumulative: 1yr 9.9 3yr 29.0 5yr 48.0."
MANDATE = {"objective_type": "index_tracker", "benchmark_role": "target", "time_horizon_years": 5,
           "secondary_objective": None, "secondary_objective_unclassified": None,
           "promises": ["Track the Sample World Index"]}


def extractor_answer(**profile):
    base = output()
    base["profile"] |= {"isin": "XX0000000001", "launch_date": "2018-01-02", "benchmark_name": "Sample World Index",
                        "objective_text": "The fund aims to track the Sample World Index over 5 years or more.",
                        "performance_fee": False, "pricing_point": "market_close"} | profile
    return base


def peer_answer():
    data = output()
    data["series"] = [{"name": "fund_nav", "basis": "cumulative", "pricing": None, "y1": 9.9, "y3": 29.0, "y5": 48.0,
                       "since_launch": None}]
    data["profile"] |= {"fund_name": "Peer Tracker B Acc", "share_class": "B Acc", "ocf_pct": 0.05}
    return data


def docs(tmp_path):
    (tmp_path / "factsheet.txt").write_text(FACTSHEET)
    (tmp_path / "peer_factsheet.txt").write_text(PEER_SHEET)
    return tmp_path / "factsheet.txt", tmp_path / "peer_factsheet.txt"


def read(tmp_path, peer=True, **profile):
    factsheet, peer_doc = docs(tmp_path)
    return asyncio.run(read_documents(factsheet, None, peer_doc if peer else None,
                                      run_extractor=FakeRun(extractor_answer(**profile)), run_mandate=FakeRun(MANDATE),
                                      run_peer=FakeRun(peer_answer())))


def by_key(intake):
    return {r["key"]: r for r in intake["rows"]}


def test_the_table_shows_what_the_agents_read_and_where(tmp_path):
    rows = by_key(read(tmp_path))
    assert rows["fund_name"]["value"] == "Sample Fund A Acc" and rows["fund_name"]["status"] == AI
    assert rows["isin"]["source"] == "factsheet.txt"
    assert rows["ocf_pct"]["value"] == "0.1"
    assert rows["objective_type"]["value"] == "index_tracker"
    assert rows["objective_type"]["source"].startswith("Mandate Agent, from the objective")
    assert rows["series.index.5y"]["value"] == "50.8"
    assert rows["series.fund_pnav.5y"]["status"] == "Not found (optional)"           # PNAV is optional
    assert rows["hedged"]["value"] == "no" and rows["hedged"]["status"] == CODE       # no hedging mentioned
    assert rows["peer.ocf_pct"]["value"] == "0.05" and rows["peer.5y"]["value"] == "48"


def test_a_missing_required_value_is_highlighted_and_blocks_the_run(tmp_path):
    intake = read(tmp_path, isin=None)
    assert by_key(intake)["isin"]["status"] == MISSING
    assert missing(intake) == ["ISIN"]
    built = build_inputs(intake, [r["value"] for r in intake["rows"]])
    assert built.profile is None and built.problems == ["ISIN: required, please fill it in"]


def test_corrected_values_are_marked_entered_by_user(tmp_path):
    intake = read(tmp_path, isin=None)
    values = [r["value"] for r in intake["rows"]]
    keys = [r["key"] for r in intake["rows"]]
    values[keys.index("isin")] = "XX0000000001"
    values[keys.index("ocf_pct")] = "0.12"
    values[keys.index("series.index.5y")] = "51.0"
    built = build_inputs(intake, values)
    assert built.problems == [] and sorted(built.user_entered) == ["isin", "ocf_pct", "series.index.5y"]
    profile = FundProfile.model_validate(built.profile)
    assert profile.ocf_pct == 0.12 and profile.field_sources["ocf_pct"] == "user"
    assert profile.field_sources["fund_name"] == "ai_extracted" and profile.field_sources["hedged"] == "code"
    fs = FactsheetPerformance.model_validate(built.factsheet)
    assert fs.user_entered == ["index.5y"] and fs.series["index"].y5 == 51.0 and fs.source == "ai_extracted"
    assert {r["key"]: r["status"] for r in built.rows}["ocf_pct"] == USER
    assert Peer.model_validate(built.peer).returns.y5 == 48.0


def test_a_value_that_is_not_valid_is_reported(tmp_path):
    intake = read(tmp_path)
    values = [r["value"] for r in intake["rows"]]
    keys = [r["key"] for r in intake["rows"]]
    values[keys.index("ocf_pct")] = "cheap"
    values[keys.index("objective_type")] = "tracker"
    built = build_inputs(intake, values)
    assert built.profile is None
    assert any(p.startswith("Ongoing charge (OCF), % a year: 'cheap' is not valid") for p in built.problems)
    assert any(p.startswith("Objective type: 'tracker' is not valid (one of index_tracker") for p in built.problems)


def test_a_corrected_cumulative_return_drops_the_extracted_annualised_one(tmp_path):
    intake = read(tmp_path)
    values = [r["value"] for r in intake["rows"]]
    keys = [r["key"] for r in intake["rows"]]
    values[keys.index("series.fund_nav.5y")] = "49.0"
    built = build_inputs(intake, values)
    assert "fund_nav" not in built.factsheet["series_annualised"]


def test_the_inputs_written_run_through_the_controller_with_user_marks(tmp_path):
    from fund_performance.controller import run_review
    intake = read(tmp_path)
    values = [r["value"] for r in intake["rows"]]
    keys = [r["key"] for r in intake["rows"]]
    values[keys.index("series.index.5y")] = "51.0"
    built = build_inputs(intake, values)
    folder = tmp_path / "in"
    assert write_inputs(built, folder) == ["fund_profile.json", "factsheet_performance.json", "peer.json"]
    prices = Path(__file__).parent.parent / "demo" / "sample_index_fund" / "prices.csv"
    (folder / "prices.csv").write_bytes(prices.read_bytes())
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))
    figures = {f["name"]: f for f in result.facts["figures"]}
    assert figures["index.cum.5y"]["source"] == "user" and figures["fund_nav.cum.5y"]["source"] == "ai_extracted"
    assert json.loads((folder / "fund_profile.json").read_text())["field_sources"]["isin"] == "ai_extracted"


def test_locate_finds_the_page_or_says_not_found():
    pages = {"factsheet.pdf": ["Cover page", "5yr 88.30 and OCF 0.06%"]}
    assert locate(88.3, pages) == "factsheet.pdf, page 2" and locate(0.06, pages) == "factsheet.pdf, page 2"
    assert locate(91.6, pages) == NOT_FOUND and locate("cover PAGE", pages) == "factsheet.pdf, page 1"


def test_table_columns(tmp_path):
    rows = table(read(tmp_path, peer=False))
    assert rows[0] == ["Fund name", "Sample Fund A Acc", AI, "factsheet.txt"]
    assert not any(r[0].startswith("Peer") for r in rows)


def test_the_controller_uses_the_confirmation_and_reports_progress(tmp_path):
    """ The agents already ran before the run: they are not called again; the confirmed table is logged """
    from fund_performance.controller import Runners, run_review
    intake = read(tmp_path)
    values = [r["value"] for r in intake["rows"]]
    values[[r["key"] for r in intake["rows"]].index("ocf_pct")] = "0.12"
    built = build_inputs(intake, values)
    folder = tmp_path / "in"
    write_inputs(built, folder)
    prices = Path(__file__).parent.parent / "demo" / "sample_index_fund" / "prices.csv"
    (folder / "prices.csv").write_bytes(prices.read_bytes())
    confirmed = intake | {"rows": built.rows}
    messages = []
    runners = Runners(mandate=FakeRun(), extractor=FakeRun(), planner=FakeRun({"searches": []}),
                      http_get=lambda url, s: (403, ""))              # FakeRun() fails if it is called
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", runners=runners, intake=confirmed,
                                    on_step=messages.append))
    log = json.loads((result.run_dir / "log.json").read_text())
    steps = {s["step"]: s for s in log["steps"]}
    assert steps["confirmation"]["outputs"]["entered_by_user"] == ["Ongoing charge (OCF), % a year"]
    assert steps["mandate"]["notes"] == ["Mandate Agent read the objective before the run; its answer was confirmed on the page"]
    assert steps["extractor"]["status"] == "skipped"
    assert "factsheet.txt (read by the Extractor Agent; values confirmed on the page)" in log["sources"]["input_files"]
    assert messages[:3] == ["Checking the files…", "Reading the documents…", "Checking the data…"]
    assert "Scoring…" in messages and messages[-1] == "Writing the report…"


# The documents route from the command line, and the live check that it matches the JSON route
def _ratings(result):
    card = result.facts["scorecard"]
    return {p["name"]: p["rating"] for p in card["pillars"]}, card["verdict"]


def test_document_roles_come_from_the_file_names():
    from fund_performance.run_report import document_roles
    roles = document_roles([Path("Monthly_FactSheet.pdf"), Path("Key_Investor_Info.pdf"), Path("peer_factsheet.pdf")])
    assert (roles["factsheet"].name, roles["kid"].name, roles["peer"].name) == (
        "Monthly_FactSheet.pdf", "Key_Investor_Info.pdf", "peer_factsheet.pdf")


def test_demo_documents_route_matches_the_json_route_with_the_agents_mocked(tmp_path):
    """ The extractor's answer is made from the demo's typed files, so the two routes must agree exactly """
    from fund_performance.controller import run_review
    from fund_performance.run_report import from_documents
    demo = Path(__file__).parent.parent / "demo" / "sample_index_fund"
    profile = json.loads((demo / "fund_profile.json").read_text())
    fs = json.loads((demo / "factsheet_performance.json").read_text())
    peer = json.loads((demo / "peer.json").read_text())
    answer = output(series=[{"name": n, "basis": "cumulative", "pricing": s.get("pricing"), "y1": s["1y"],
                             "y3": s["3y"], "y5": s["5y"], "since_launch": None} for n, s in fs["series"].items()],
                    calendar_years=[], risk=[])
    answer["profile"] |= {k: profile[k] for k in ("fund_name", "isin", "share_class", "currency", "distribution",
                                                  "hedged", "launch_date", "objective_text", "benchmark_name",
                                                  "ocf_pct", "performance_fee", "pricing_point")}
    peer_out = output(series=[{"name": "fund_nav", "basis": "cumulative", "pricing": None, "since_launch": None,
                               **{f"y{p}": round(((1 + peer["returns"][f"{p}y"] / 100) ** p - 1) * 100, 1)
                                  for p in (1, 3, 5)}}], calendar_years=[], risk=[])
    peer_out["profile"] |= {"fund_name": peer["name"], "share_class": peer["share_class"], "ocf_pct": peer["ocf_pct"]}

    async def reader(factsheet, kid, peer_doc):
        return await read_documents(factsheet, kid, peer_doc, run_extractor=FakeRun(answer),
                                    run_mandate=FakeRun(MANDATE), run_peer=FakeRun(peer_out))
    docs_route, text = asyncio.run(from_documents(demo, "q", tmp_path / "a", scoring_offline=True, reader=reader))
    json_route = asyncio.run(run_review(demo, out_root=tmp_path / "b", offline=True))
    assert _ratings(docs_route) == _ratings(json_route)
    assert "Compared with the typed JSON files: 0 value(s) differ" in text
    assert (docs_route.run_dir / "extraction_check.txt").exists()


@pytest.mark.live
@requires_test1
def test_live_test1_documents_route_matches_the_json_route(tmp_path):
    """ Test 1 from the CSV and the two PDFs only: same ratings and verdict as the typed JSON route. Prints what the
    Extractor read and every value that differs from the typed files (record them in tests/RESULTS.md) """
    from fund_performance.controller import run_review
    from fund_performance.run_report import from_documents
    docs_route, text = asyncio.run(from_documents(TEST1, "q", tmp_path / "docs", scoring_offline=True))
    print("\n" + text)
    assert docs_route is not None, "a required value was not read from the documents"
    json_route = asyncio.run(run_review(TEST1, out_root=tmp_path / "json", offline=True))
    print("Documents route:", _ratings(docs_route), "\nJSON route:     ", _ratings(json_route))
    assert _ratings(docs_route) == _ratings(json_route)
