""" Approved peers (config/peers.yaml) and the peer checks (B1, B2): currency, pricing time, share class, income vs
accumulation, several peers averaged. Includes Test 1 with the two approved S&P 500 peers' factsheet figures """
import asyncio
import json
import shutil
from docx import Document
import pytest
from fund_performance.config import ApprovedPeer, load_peers
from fund_performance.models import Peer
from fund_performance.peers import (INSTITUTIONAL_NOTE, approved_peers, compare_peers, find_factsheet, investor_type,
                                    two_dp)
from fund_performance import scorecard as sc
from conftest import TEST1, FakeRunBy, requires_test1
from test_scorecard import T, figures, profile

# Test 1's approved peers, as printed on their factsheets to 30 September 2026
HSBC = dict(name="HSBC American Index Fund Inst Inc", isin="GB00BYWKBM47", ocf_pct=0.02, currency="GBP",
            share_class="Inst Inc", pricing_point="midday", distribution="income", investor_type="institutional",
            minimum_investment="GBP 10,000,000", vol_3y=13.17, origin="approved",
            returns={"1y": 17.48, "basis": "cumulative"},
            returns_annualised={"1y": 17.48, "3y": 19.27, "5y": 13.51, "basis": "annualised"})
VANGUARD = dict(name="Vanguard S&P 500 UCITS ETF (USD) Accumulating", isin="IE00BFMXXD54", ocf_pct=0.07,
                currency="USD", share_class="(USD) Accumulating", pricing_point="market_close",
                distribution="accumulation", investor_type="retail", origin="approved",
                returns={"1y": 15.46, "basis": "cumulative"},
                returns_annualised={"1y": 15.46, "3y": 22.57, "5y": 13.48, "basis": "annualised"})


def test_the_config_lists_the_two_approved_sp500_peers():
    group = load_peers().for_benchmark("S&P 500 Index NUK")
    assert [p.isin for p in group.peers] == ["IE00BFMXXD54", "GB00BYWKBM47"]
    assert load_peers().for_benchmark("FTSE All-Share") is None


def _docx(path, text):
    doc = Document()
    doc.add_paragraph(text)
    doc.save(path)


def test_factsheets_are_found_by_file_name_or_by_the_isin_inside(tmp_path):
    _docx(tmp_path / "hsbc_GB00BYWKBM47.docx", "HSBC American Index Fund")
    _docx(tmp_path / "vanguard.docx", "Vanguard S&P 500 UCITS ETF. ISIN IE00BFMXXD54")
    assert find_factsheet(ApprovedPeer(name="H", isin="GB00BYWKBM47"), tmp_path).name == "hsbc_GB00BYWKBM47.docx"
    assert find_factsheet(ApprovedPeer(name="V", isin="IE00BFMXXD54"), tmp_path).name == "vanguard.docx"
    assert find_factsheet(ApprovedPeer(name="X", isin="XX0000000009"), tmp_path) is None


def test_a_missing_factsheet_is_an_info_flag_and_the_fund_is_never_its_own_peer(tmp_path):
    _docx(tmp_path / "hsbc_GB00BYWKBM47.docx", "HSBC")
    found = approved_peers(load_peers(), "S&P 500 Index NUK", "GB00BJS8SH10", tmp_path)
    assert [p.isin for p, _ in found.files] == ["GB00BYWKBM47"]
    assert found.flags[0].level == "info" and "IE00BFMXXD54" in found.flags[0].message
    itself = approved_peers(load_peers(), "S&P 500 Index NUK", "GB00BYWKBM47", tmp_path)
    assert itself.files == []


@pytest.mark.parametrize("share_class, minimum, expected", [
    ("Inst Inc", None, "institutional"), ("Institutional Acc", None, "institutional"), ("P Acc", "£1,000", "retail"),
    ("C Acc", "GBP 10,000,000", "institutional"), ("A Acc", None, "retail"), (None, None, None)])
def test_share_class_type_is_derived_by_code(share_class, minimum, expected):
    assert investor_type(share_class, minimum) == expected


def test_two_dp_rounds_half_up():
    assert two_dp(0.045) == 0.05 and two_dp(0.06 - 0.045) == 0.02 and two_dp(-0.015) == -0.02


def reported():
    return figures(fund_nav__cum__1y=17.3, fund_nav__ann__3y=19.2, fund_nav__ann__5y=13.5,
                   fund_pnav__cum__1y=17.6, fund_pnav__ann__3y=19.4, fund_pnav__ann__5y=13.9)


def test_currency_pricing_time_and_share_class_checks():
    prof = profile(currency="GBP", pricing_point="midday", distribution="accumulation", time_horizon_years=5)
    comp = compare_peers([Peer(**HSBC), Peer(**VANGUARD)], prof, reported())
    hsbc, vanguard = comp.rows
    assert hsbc.used_for_returns and hsbc.fund_series == "fund_nav" and hsbc.basis == "noon NAV vs noon NAV"
    assert hsbc.gap == pytest.approx(0.01)
    assert INSTITUTIONAL_NOTE in hsbc.notes and "income share class: compared on a total-return basis" in hsbc.notes
    assert not vanguard.used_for_returns and vanguard.excluded == "returns in USD, not GBP"
    assert vanguard.fund_series == "fund_pnav" and vanguard.basis == "market close: fund PNAV vs peer"
    assert "its ongoing charge (0.07%) is still used for fees" in comp.flags[0].message
    assert comp.average_ocf == 0.05


def test_test1_style_value_and_fees_with_the_two_peers():
    prof = profile(currency="GBP", pricing_point="midday", ocf_pct=0.06, objective_type="index_tracker")
    peers = [Peer(**VANGUARD), Peer(**HSBC)]
    value = sc.value_rating(reported(), prof, T, peers)
    assert value.rating == sc.GREEN and value.values["gap_pp"] == 0.01 and value.values["peers"] == [HSBC["name"]]
    fees = sc.fees_rating(prof, T, peers, sc.GREEN)
    assert fees.rating == sc.GREEN and fees.values["peer_ocf"] == 0.05 and fees.values["gap_pp"] == 0.01
    assert any(INSTITUTIONAL_NOTE in n for n in fees.notes)


def test_a_market_close_peer_without_fund_pnav_uses_nav_with_a_note():
    prof = profile(pricing_point="midday")
    row = compare_peers([Peer(**(VANGUARD | {"currency": "GBP"}))], prof, figures(fund_nav__ann__5y=13.5)).rows[0]
    assert row.fund_series == "fund_nav" and "no PNAV" in row.basis and "timing differs" in row.notes[0]


@requires_test1
def test_test1_with_the_approved_peers_is_satisfied(tmp_path):
    """ Expected Test 1 (B2): Value Green (HSBC 13.51% vs 13.5% a year over 5 years), Fees Green (0.06% vs 0.07% and
    0.02%, with the institutional note) -> Satisfied """
    from fund_performance.controller import run_review
    folder = tmp_path / "in"
    shutil.copytree(TEST1, folder, ignore=shutil.ignore_patterns("*.pdf"))
    (folder / "peer.json").write_text(json.dumps([VANGUARD, HSBC]))
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))
    pillars = {p["name"]: p for p in result.facts["scorecard"]["pillars"]}
    assert pillars["Value for investors"]["rating"] == "GREEN" and pillars["Fees"]["rating"] == "GREEN"
    assert result.facts["scorecard"]["verdict"] == "Retain"
    assert pillars["Value for investors"]["values"]["fund_ann"] == 13.5
    assert pillars["Value for investors"]["values"]["peer_ann"] == 13.51
    conclusion = result.facts["suggested_conclusion"]["text"]
    assert conclusion.endswith("Suggested verdict: Satisfied, no action needed.") and not result.facts[
        "suggested_conclusion"]["left_out"]
    assert any("institutional share class" in x for x in result.facts["judgement_points"])
    assert any("returns are in USD" in x for x in result.facts["judgement_points"])


def test_approved_peers_are_read_by_the_extractor_when_no_peer_is_given(tmp_path, monkeypatch):
    from fund_performance.controller import run_review
    from test_agent_extractor import output
    peers = tmp_path / "peers"
    peers.mkdir()
    _docx(peers / "hsbc.docx", "HSBC American Index Fund GB00BYWKBM47 Inst Inc. OCF 0.02%. 5y ann 13.51")
    monkeypatch.setenv("FUND_PEER_FOLDER", str(peers))
    answer = output()
    answer["series"] = [{"name": "fund_nav", "basis": "annualised", "pricing": "midday", "y1": 17.48, "y3": 19.27,
                         "y5": 13.51, "since_launch": None}]
    answer["profile"] |= {"fund_name": "HSBC American Index Fund", "isin": "GB00BYWKBM47", "share_class": "Inst Inc",
                          "currency": "GBP", "ocf_pct": 0.02, "distribution": "income",
                          "minimum_investment": "GBP 10,000,000"}
    folder = tmp_path / "in"
    folder.mkdir()
    demo = TEST1.parent.parent / "demo" / "sample_index_fund"
    for name in ("prices.csv", "fund_profile.json", "factsheet_performance.json"):
        shutil.copy(demo / name, folder / name)
    profile_json = json.loads((folder / "fund_profile.json").read_text()) | {"benchmark_name": "S&P 500 Index"}
    (folder / "fund_profile.json").write_text(json.dumps(profile_json))
    from test_controller import mocked
    runners = mocked()
    runners.extractor = FakeRunBy(lambda prompt: answer)
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", runners=runners))
    log = json.loads((result.run_dir / "log.json").read_text())
    step = next(s for s in log["steps"] if s["step"] == "peers")
    assert step["status"] == "ok" and step["outputs"]["peers"] == ["HSBC American Index Fund"]
    assert any("hsbc.docx (approved peer" in f for f in log["sources"]["input_files"])
    assert result.facts["peers"][0]["investor_type"] == "institutional"
