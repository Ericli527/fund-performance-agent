""" The real-fund demo library (Stage 4B), tested with a made-up library: the manifests, missing private files,
the Quick/Live inputs, how a demo is recognised, the return check and the page. The real demos (private files) are
tested at the end and skip when their files are absent """
import asyncio
import json
import re
from pathlib import Path
import shutil
import pytest
import yaml
from fund_performance import demos as lib
from fund_performance.demos import find_demo, load_demos, matching_demo, return_checks

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "demo" / "sample_index_fund"
MANIFEST = {"id": "sample", "order": 1, "title": "Sample World", "subtitle": "A made-up tracker",
            "fund_name": "Sample World Index Fund A Acc", "share_class": "A Acc", "isin": "XX0000000001",
            "benchmark": "Sample World Index", "peer": "Sample World Index Tracker B", "review_date": "2026-09-30",
            "quick": {"prices": "quick/prices.csv",
                      "json": ["quick/fund_profile.json", "quick/factsheet_performance.json", "quick/peer.json"]},
            "live": {"prices": "quick/prices.csv", "factsheet": "documents/factsheet.pdf", "kid": None,
                     "peers": ["documents/peer_factsheet.pdf"]},
            "sources": [{"publisher": "Nobody", "title": "Made-up factsheet", "date": "30 Sep 2026", "used": "all"}],
            "disclosures": ["A made-up fund for tests."]}


@pytest.fixture
def library(tmp_path, monkeypatch):
    """ A library with one made-up demo whose private files are in place, and one whose files are missing """
    manifests, data = tmp_path / "library", tmp_path / "data"
    manifests.mkdir()
    (manifests / "sample.yaml").write_text(yaml.safe_dump(MANIFEST))
    (manifests / "absent.yaml").write_text(yaml.safe_dump(MANIFEST | {"id": "absent", "order": 2, "title": "Absent"}))
    for sub, names in (("quick", ["prices.csv", "fund_profile.json", "factsheet_performance.json", "peer.json"]),
                       ("documents", ["factsheet.pdf", "peer_factsheet.pdf"])):
        (data / "sample" / sub).mkdir(parents=True)
        for name in names:
            shutil.copy(SAMPLE / name, data / "sample" / sub / name)
    monkeypatch.setattr(lib, "LIBRARY", manifests)
    monkeypatch.setenv(lib.DATA_ENV, str(data))
    return data


def test_the_committed_manifests_hold_metadata_only():
    """ The two real demos are described in the repository without any figure from their documents """
    demos = [d for d in load_demos(data=Path("/nonexistent")) if not d.fallback]
    assert [d.id for d in demos] == ["fidelity_us", "vanguard_global"]
    fidelity, vanguard = demos
    assert (fidelity.isin, vanguard.isin, vanguard.ticker) == ("GB00BJS8SH10", "GB00BD3RZ582", "VAFTGAG")
    assert {str(d.review_date) for d in demos} == {"2026-09-30"} and {d.return_check_tolerance_pp for d in demos} == {0.05}
    assert "GB00B80QG615" in fidelity.peer and vanguard.live["peers"] == []
    for path in (ROOT / "demo" / "library").glob("*.yaml"):
        text = path.read_text()
        assert not re.search(r"\d+\.\d+\s*%", text), path.name           # no percentage figure of any kind
        for figure in _private_figures():                                # nor any figure typed from the documents
            assert figure not in text, (path.name, figure)
    assert not any(d.available for d in demos)                           # no private folder: shown as unavailable


def _private_figures() -> set[str]:
    """ The figures in the private quick inputs (when installed), read at test time: never written in a test """
    out = set()
    for path in (ROOT / "data" / "demos").glob("*/quick/*.json"):
        def walk(x):
            if isinstance(x, dict):
                [walk(v) for v in x.values()]
            elif isinstance(x, list):
                [walk(v) for v in x]
            elif isinstance(x, float) and abs(x) >= 1:
                out.add(f"{x:.2f}")
        walk(json.loads(path.read_text()))
    return out


def test_missing_private_files_make_a_demo_unavailable_not_an_error(library):
    sample, absent = load_demos()
    assert sample.available and not absent.available
    assert absent.missing() == ["quick/prices.csv", "quick/fund_profile.json", "quick/factsheet_performance.json",
                                "quick/peer.json", "documents/factsheet.pdf", "documents/peer_factsheet.pdf"]
    assert matching_demo(SAMPLE / "prices.csv", [], [absent]) is None


def test_a_demo_is_recognised_only_from_its_exact_quick_inputs(library, tmp_path):
    files = find_demo("sample").quick_files
    assert matching_demo(files["price"], files["json"]).id == "sample"
    assert matching_demo(files["price"], files["json"][::-1]).id == "sample"         # any order
    assert matching_demo(files["price"], files["json"][:2]) is None                   # one missing
    edited = tmp_path / "fund_profile.json"
    edited.write_text(files["json"][0].read_text().replace("Sample World", "Edited"))
    assert matching_demo(files["price"], [edited, *files["json"][1:]]) is None        # an edited file


def test_the_return_check_compares_price_returns_with_the_factsheet(library):
    checks = return_checks(find_demo("sample"))
    assert [c.period for c in checks] == ["1y", "3y", "5y"] and all(c.calculated is not None for c in checks)
    for c in checks:
        assert c.ok == (abs(c.calculated - c.published) <= 0.05)
    bad = find_demo("sample")
    fs = bad.quick_files["json"][1]
    data = json.loads(fs.read_text())
    data["series"]["fund_nav"]["5y"] = data["series"]["fund_nav"]["5y"] + 1
    fs.write_text(json.dumps(data))
    assert not next(c for c in return_checks(bad) if c.period == "5y").ok


# The page
def test_picking_a_demo_fills_the_quick_inputs_and_runs_offline(library):
    from fund_performance import web
    ui = web.build_ui()
    cards = next(c for c in ui.blocks.values() if "fp-demo-cards" in (getattr(c, "elem_classes", None) or []))
    assert [v for _, v in cards.choices] == ["sample", "absent", web.UPLOAD_OWN]     # an uninstalled case stays listed
    on_demo = web.on_demo
    price, factsheet, kid, peers, json_files, options, info = on_demo("sample", web.QUICK)
    demo = find_demo("sample")
    assert price == str(demo.quick_files["price"]) and factsheet is None and kid is None and peers is None
    assert json_files == [str(p) for p in demo.quick_files["json"]] and options["open"] is True
    assert web.run_offline(price, json_files)                                         # code decides: no AI
    assert "Prevalidated inputs." in info and "Historical data" in info and "Return check" in info
    assert "Made-up factsheet" in info and "A made-up fund for tests." in info
    assert "Documents loaded:</b> prices.csv, fund_profile.json, factsheet_performance.json, peer.json" in info
    assert "Review date: 30 Sep 2026" in info
    assert web.demo_tag(price, json_files, "sample", web.QUICK).startswith("**Quick Demo: Sample World Index Fund")


def test_the_live_demo_is_offered_only_when_ai_runs_are_on(library, monkeypatch):
    from fund_performance import web
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not web.live_demo_allowed()
    on_demo = web.on_demo
    assert on_demo("sample", web.LIVE)[4] is not None                  # without AI the quick inputs are loaded
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv(web.OFFLINE_ENV, raising=False)
    assert web.live_demo_allowed()
    monkeypatch.setenv("PORT", "10000")                                # a server without a login: AI is off
    monkeypatch.delenv("APP_USERNAME", raising=False)
    assert not web.live_demo_allowed()
    monkeypatch.delenv("PORT")
    price, factsheet, kid, peers, json_files, options, info = on_demo("sample", web.LIVE)
    demo = find_demo("sample")
    assert (price, factsheet, json_files) == (str(demo.live_files["price"]), str(demo.live_files["factsheet"]), None)
    assert peers == [str(p) for p in demo.live_files["peers"]] and "AI-extracted evidence." in info
    assert not web.run_offline(price, json_files)                     # the documents route: AI, with the run limit
    assert web.demo_tag(price, json_files, "sample", web.LIVE).startswith("**Live AI Demo:")


def test_a_live_demo_respects_the_ai_run_limit(library, tmp_path):
    from fund_performance import web
    from fund_performance.config import WebSettings
    limits = web.AiLimits(WebSettings(max_ai_runs_per_day=1, max_ai_runs_at_once=1), tmp_path / "count.json")
    limits.start()
    limits.finish()                                                    # today's one AI run is used up
    demo = find_demo("sample")
    live = demo.live_files
    out = asyncio.run(web.start_review("q", str(live["price"]), str(live["factsheet"]), None,
                                       [str(p) for p in live["peers"]], None, False, limits, out_root=tmp_path))
    assert out.message == web.LIMIT_REACHED and out.data is None


def test_without_the_private_files_the_real_cases_are_listed_but_never_replaced_by_made_up_data(tmp_path, monkeypatch):
    """ Version 1 test cases on a server without the real-fund files (Render without its case folder): the synthetic
    demo works; Fidelity and Vanguard stay listed, name their missing files and fill in nothing """
    from fund_performance import web
    monkeypatch.setenv(lib.DATA_ENV, str(tmp_path / "nothing"))
    ui = web.build_ui()
    cards = next(c for c in ui.blocks.values() if "fp-demo-cards" in (getattr(c, "elem_classes", None) or []))
    assert [v for _, v in cards.choices] == ["sample_index_fund", "fidelity_us", "vanguard_global", web.UPLOAD_OWN]
    assert [label.split("\n")[0] for label, _ in cards.choices] == [
        "Synthetic Demo", "Fidelity Index US P Acc GBP", "Vanguard FTSE Global All Cap Index Fund GBP Acc",
        "Upload Your Own Fund"]
    on_demo = web.on_demo
    price, _, _, _, json_files, _, info = on_demo("sample_index_fund", web.QUICK)
    assert web.run_offline(price, json_files) and "made-up data" in info and "every figure is invented" in info
    banner = web.demo_banner(price, json_files, "sample_index_fund", web.QUICK)
    assert banner["label"] == "Quick Demo" and "invented" in banner["notice"]
    for case in ("fidelity_us", "vanguard_global"):
        price, factsheet, kid, peers, json_files, _, info = on_demo(case, web.LIVE)
        assert (price, factsheet, kid, peers, json_files) == (None,) * 5        # nothing filled in, nothing substituted
        assert "Not installed on this server" in info and "no made-up data is used instead" in info
        assert "Sample World" not in info and "documents/" in info               # names the missing files


def test_upload_your_own_fund_empties_the_boxes_and_a_mode_switch_never_clears_your_files(library):
    from fund_performance import web
    ui = web.build_ui()
    fns = {f.name: f.fn for f in ui.fns.values()}
    out = web.on_demo(web.UPLOAD_OWN, web.QUICK)
    assert out[:5] == (None,) * 5 and "Upload your own fund" in out[6] and "not shared with other users" in out[6]
    assert all(x == {"__type__": "update"} for x in fns["on_mode"](web.UPLOAD_OWN, web.LIVE))


def test_a_real_case_runs_the_live_ai_workflow_by_default_where_ai_runs_are_on(library, monkeypatch):
    from fund_performance import web
    real = lib.Demo(**{**MANIFEST, "id": "sample", "review_date": lib.date(2026, 9, 30)}, folder=library / "sample")
    monkeypatch.setattr(web, "find_demo", lambda demo_id: real if demo_id == "sample" else None)
    on_case = next(f for f in web.build_ui().fns.values() if f.name == "on_case").fn
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv(web.OFFLINE_ENV, raising=False)
    *boxes, mode = on_case("sample", web.QUICK)
    assert mode == web.LIVE and boxes[1] is not None and boxes[4] is None       # the documents, read by the agents
    assert not web.run_offline(boxes[0], boxes[4])
    monkeypatch.delenv("OPENAI_API_KEY")
    *boxes, mode = on_case("sample", web.LIVE)
    assert mode == web.QUICK and boxes[4] is not None                           # AI off: the prevalidated inputs
    synthetic = lib.Demo(**{**MANIFEST, "id": "sample", "fallback": True, "review_date": lib.date(2026, 9, 30)},
                         folder=library / "sample")
    monkeypatch.setattr(web, "find_demo", lambda demo_id: synthetic)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    assert on_case("sample", web.LIVE)[-1] == web.QUICK                         # the synthetic demo: no AI by default


# The real demos: private files, local only
REAL = load_demos()
requires_demo = {d.id: pytest.mark.skipif(not d.available, reason="private demo files are not in data/demos "
                                                                   "(they are kept out of the public repo)")
                 for d in REAL}


def run_demo(demo_id, tmp_path):
    from fund_performance.controller import run_review
    demo = find_demo(demo_id)
    folder = tmp_path / "in"
    folder.mkdir()
    for p in [demo.quick_files["price"], *demo.quick_files["json"]]:
        shutil.copy(p, folder)
    return asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))


@requires_demo["fidelity_us"]
def test_real_fidelity_demo(tmp_path):
    from fund_performance.report import page_texts
    assert all(c.ok for c in return_checks(find_demo("fidelity_us")))
    r = run_demo("fidelity_us", tmp_path)
    ratings = {p["name"]: p["rating"] for p in r.facts["scorecard"]["pillars"]}
    assert r.facts["scorecard"]["verdict"] == "Retain" and set(ratings.values()) == {"GREEN"}
    peer = r.facts["peers"][0]
    assert peer["isin"] == "GB00B80QG615" and peer["investor_type"] == "institutional"
    assert peer["benchmark_name"] == "S&P 500 Index (GBP)" and "different benchmark variant" in peer["notes"][-1]
    assert len(page_texts(r.executive_pdf)) == 2 and r.pdf.is_file()


@requires_demo["vanguard_global"]
def test_real_vanguard_demo(tmp_path):
    from fund_performance.report import page_texts
    checks = return_checks(find_demo("vanguard_global"))
    assert all(c.ok for c in checks) and all(abs(c.difference) <= 0.05 for c in checks)
    assert any("left out (01 Oct 2026 to 29 Oct 2026)" in n for n in checks[0].notes)   # October prices not used
    r = run_demo("vanguard_global", tmp_path)
    facts = r.facts
    assert facts["scorecard"]["verdict"] == "Pending data check"                          # preserved, scoring unchanged
    assert any(f.check == "review_date_cutoff" for f in r.flags)
    assert any(f.check == "pricing_point" and "not stated" in f.message for f in r.flags)       # not guessed
    names = {f["name"] for f in facts["figures"]}
    assert not any(n.startswith(("relative.", "risk.")) for n in names)                   # no TE, beta, R² made up
    assert facts["peers"] == []
    figs = {f["name"]: f for f in facts["figures"]}
    typed = json.loads(find_demo("vanguard_global").quick_files["json"][1].read_text())["series"]
    assert (figs["fund_nav.ann.5y"]["value"], figs["index.ann.5y"]["value"]) == \
        (typed["fund_nav"]["5y"], typed["index"]["5y"])                     # the GBP figures, as typed (annualised)
    assert figs["fund_nav.cum.5y"]["source"] == "calculated" and figs["fund_nav.cum.5y"]["value"] > 60
    text = " ".join(" ".join(page_texts(r.executive_pdf)).split())
    assert len(page_texts(r.executive_pdf)) == 2
    assert "Evidence missing" in text and "R² and beta are not in the documents provided" in text
    assert "resolve the data check" not in text.lower() and "CHECK DATA" not in text


def test_the_case_check_script_reports_missing_files_without_their_content(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_test_cases", lib.ROOT / "scripts" / "check_test_cases.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(str(tmp_path / "empty")) == 1                    # the real cases are not installed there
    out = capsys.readouterr().out
    assert "Synthetic Demo (sample_index_fund): ready" in out
    assert "Fidelity Index US P Acc GBP (fidelity_us): NOT INSTALLED" in out and "missing: quick/" in out
