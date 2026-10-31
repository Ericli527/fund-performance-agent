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


# HSBC American Index Fund Acc C, typed from its public factsheet (30 Sep 2026): GBP, accumulation, valued at 12:00 UK,
# minimum initial investment GBP 1,000,000. The share class type is left out on purpose: code derives it
HSBC_ACC_C = dict(name="HSBC American Index Fund Acc C", isin="GB00B80QG615", ocf_pct=0.07, currency="GBP",
                  share_class="Acc C", pricing_point="midday", distribution="accumulation",
                  minimum_investment="GBP 1,000,000", vol_3y=13.17, origin="uploaded",
                  returns={"1y": 17.42, "basis": "cumulative"},
                  returns_annualised={"1y": 17.42, "3y": 19.23, "5y": 13.47, "basis": "annualised"})


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


def test_a_typed_peer_with_a_1m_minimum_is_institutional(tmp_path):
    """ Stage 3.1: peer.json gets the share class type from the minimum investment, as an uploaded factsheet does """
    from fund_performance.io import read_peers
    path = tmp_path / "peer.json"
    path.write_text(json.dumps([HSBC_ACC_C, {k: v for k, v in HSBC_ACC_C.items() if k != "minimum_investment"}]))
    with_minimum, without = read_peers(path)
    assert with_minimum.investor_type == "institutional" and without.investor_type is None


@requires_test1
def test_fidelity_with_the_hsbc_acc_c_peer(tmp_path):
    """ Stage 3.1: Fidelity Index US Fund P Acc against HSBC American Index Fund Acc C, both GBP accumulation classes
    priced at noon UK: returns compared noon NAV with noon NAV over 1, 3 and 5 years; fees 0.06% vs 0.07%; the GBP 1m
    minimum is flagged as an institutional class. Ratings from the unchanged thresholds """
    from fund_performance.controller import run_review
    from fund_performance.report import page_texts
    folder = tmp_path / "in"
    shutil.copytree(TEST1, folder, ignore=shutil.ignore_patterns("*.pdf", "golden"))
    (folder / "peer.json").write_text(json.dumps(HSBC_ACC_C))
    result = asyncio.run(run_review(folder, out_root=tmp_path / "runs", offline=True))
    pillars = {p["name"]: p for p in result.facts["scorecard"]["pillars"]}
    assert (pillars["Value for investors"]["rating"], pillars["Fees"]["rating"]) == ("GREEN", "GREEN")
    assert result.facts["scorecard"]["verdict"] == "Retain"
    peer = result.facts["peers"][0]
    assert peer["used_for_returns"] and peer["basis"] == "noon NAV vs noon NAV" and peer["currency"] == "GBP"
    assert peer["returns_pct_a_year"] == {"1y": 17.42, "3y": 19.23, "5y": 13.47}
    assert peer["investor_type"] == "institutional" and peer["notes"] == [INSTITUTIONAL_NOTE]
    value = pillars["Value for investors"]["values"]
    assert (value["fund_ann"], value["peer_ann"], value["gap_pp"]) == (13.5, 13.47, -0.03)
    assert not any("fee higher" in q for q in result.facts["manager_questions"])
    p2 = " ".join(page_texts(result.executive_pdf)[1].split())
    assert "This fund, noon price (NAV): compared with peers 17.5% 19.1% 13.5% 0.06%" in p2
    assert "HSBC American Index Fund Acc C 17.4% 19.2% 13.5% 0.07%" in p2
    assert "minimum investment GBP 1,000,000; pricing: noon NAV vs noon NAV" in p2


def test_a_peer_benchmark_variant_is_disclosed_for_information_only():
    """ Stage 4B: an optional benchmark name on the peer; a different variant gets a note, nothing else changes """
    from fund_performance.facts import peer_rows
    plain = Peer.model_validate(HSBC_ACC_C)
    named = Peer.model_validate(HSBC_ACC_C | {"benchmark_name": "S&P 500 Index (GBP)"})
    same = Peer.model_validate(HSBC_ACC_C | {"benchmark_name": "S&P 500 index nuk"})
    p = profile(benchmark_name="S&P 500 Index NUK", pricing_point="midday")
    base, disclosed, matching = (compare_peers([x], p, reported()) for x in (plain, named, same))
    assert disclosed.rows[0].notes[-1] == ("follows S&P 500 Index (GBP), a different benchmark variant from the "
                                           "fund's S&P 500 Index NUK (for information: the comparison and ratings are "
                                           "unchanged)")
    assert matching.rows[0].notes == base.rows[0].notes
    assert (disclosed.average_gap, disclosed.average_ocf, disclosed.rows[0].used_for_returns) == \
        (base.average_gap, base.average_ocf, base.rows[0].used_for_returns)
    assert "benchmark_name" not in peer_rows(base)[0] and peer_rows(disclosed)[0]["benchmark_name"] == "S&P 500 Index (GBP)"


# A peer whose figures are dated differently from the fund's (e.g. the latest verified report is months older): its
# returns cover different periods and are left out; its fee is still compared. A made-up peer
def test_a_peer_dated_differently_from_the_fund_gives_fees_only():
    from datetime import date
    prof = profile(currency="GBP", pricing_point="midday", ocf_pct=0.20, objective_type="index_tracker")
    older = Peer(**HSBC_ACC_C | {"name": "Made-up Peer Acc C", "ocf_pct": 0.10, "as_of_date": "2026-05-31"})
    comp = compare_peers([older], prof, reported())
    row = comp.rows[0]
    assert not row.used_for_returns and row.excluded == "returns as at 31 May 2026, not 30 Sep 2026"
    assert "different periods" in comp.flags[0].message and "(0.10%) is still used for fees" in comp.flags[0].message
    value = sc.value_rating(reported(), prof, T, [older])
    assert "returns as at 31 May 2026" in value.reason and "gap_pp" not in (value.values or {})
    fees = sc.fees_rating(prof, T, [older], value.rating)
    assert fees.values["peer_ocf"] == 0.10 and fees.values["gap_pp"] == 0.10      # the fee is compared
    same_day = Peer(**HSBC_ACC_C | {"as_of_date": date(2026, 9, 30)})
    assert compare_peers([same_day], prof, reported()).rows[0].used_for_returns    # same date: returns used
    assert compare_peers([Peer(**HSBC_ACC_C)], prof, reported()).rows[0].used_for_returns   # no date given: as before


def test_an_uploaded_peer_factsheet_carries_its_date_into_the_peer():
    from fund_performance.intake import peer_record
    record = peer_record({"name": "P", "ocf_pct": 0.1, "currency": "GBP", "share_class": "C",
                          "as_of_date": "2026-05-31", "1y": 1.0}, "uploaded")
    assert str(Peer.model_validate(record).as_of_date) == "2026-05-31"
