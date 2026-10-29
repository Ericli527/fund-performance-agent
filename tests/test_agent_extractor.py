""" Extractor Agent: AI calls are mocked; the number check runs on the real factsheet; one live test """
import asyncio
import json
import pytest
from fund_performance.agents.extractor import (NEVER_FROM_AI, ExtractedProfile, ExtractorOutput, extract,
                                               extractor_agent, profile_draft, to_factsheet, unfound_numbers)
from fund_performance.io import read_document, read_json
from conftest import TEST1, TEST1_FACTSHEET, FakeRun, requires_test1

DOC = """Sample Fund A Acc factsheet, 30.09.2026. Ongoing charges 0.10%. Fund size £ 1,250m. Risk class 4.
Cumulative growth (%): Fund NAV 1yr 10.0 3yr 30.0 5yr 50.0. Index 1yr 10.1 3yr 30.4 5yr 50.8.
Annualised: Fund NAV 5yr 8.4. Calendar years: Fund 2024 12.0, 2025 -8.6.
Risk (3 years) PNAV: tracking error 0.05, beta 1.00, R² 0.99. NAV: volatility 13.92."""


def output(**changes) -> dict:
    data = {
        "as_of_date": "2026-09-30", "currency": "GBP",
        "series": [
            {"name": "fund_nav", "basis": "cumulative", "pricing": None, "y1": 10.0, "y3": 30.0, "y5": 50.0, "since_launch": None},
            {"name": "index", "basis": "cumulative", "pricing": None, "y1": 10.1, "y3": 30.4, "y5": 50.8, "since_launch": None},
            {"name": "fund_nav", "basis": "annualised", "pricing": None, "y1": None, "y3": None, "y5": 8.4, "since_launch": None}],
        "calendar_years": [{"series": "fund_nav", "year": "2024", "value": 12.0},
                           {"series": "fund_nav", "year": "2025", "value": -8.6}],
        "discrete_12m": [],
        "risk": [{"basis": "pnav", "fund_vol": None, "index_vol": None, "tracking_error": 0.05, "beta": 1.0, "r2": 0.99,
                  "sharpe_fund": None, "sharpe_index": None, "info_ratio": None, "alpha": None},
                 {"basis": "nav", "fund_vol": 13.92, "index_vol": None, "tracking_error": None, "beta": None, "r2": None,
                  "sharpe_fund": None, "sharpe_index": None, "info_ratio": None, "alpha": None}],
        "profile": {"fund_name": "Sample Fund A Acc", "isin": None, "share_class": "A Acc", "currency": "GBP",
                    "distribution": "accumulation", "hedged": None, "launch_date": None, "objective_text": None,
                    "benchmark_name": None, "ocf_pct": 0.10, "transaction_cost_pct": None, "performance_fee": None,
                    "fund_size_gbp_m": 1250, "risk_indicator": 4, "pricing_point": None}}
    return data | changes


def test_agent_settings(monkeypatch):
    monkeypatch.delenv("FUND_MODEL_EXTRACTOR", raising=False)
    agent = extractor_agent()
    assert agent.model == "gpt-5.4-mini" and agent.output_type is ExtractorOutput
    assert agent.model_settings.temperature is None and agent.model_settings.reasoning.effort == "low"


def test_conversion_labels_everything_ai_extracted_and_keeps_risk_bases_apart():
    fs = to_factsheet(ExtractorOutput.model_validate(output()))
    assert (fs.source, fs.entered_by) == ("ai_extracted", "extractor")
    assert fs.series["fund_nav"].y5 == 50.0 and fs.series_annualised["fund_nav"].y5 == 8.4
    assert fs.risk("pnav").tracking_error == 0.05 and fs.risk("nav").fund_vol == 13.92
    assert fs.calendar_years["fund_nav"] == {"2024": 12.0, "2025": -8.6}


def test_the_profile_draft_never_contains_fields_reserved_for_people_or_the_mandate_agent():
    assert not NEVER_FROM_AI & set(ExtractedProfile.model_fields)          # the AI cannot even return them
    draft, missing = profile_draft(ExtractorOutput.model_validate(output()))
    assert draft == {"fund_name": "Sample Fund A Acc", "share_class": "A Acc", "currency": "GBP",
                     "distribution": "accumulation", "ocf_pct": 0.10, "fund_size_gbp_m": 1250, "risk_indicator": 4}
    assert "performance_fee_justification" not in draft
    assert {"objective_type", "isin", "launch_date"} <= set(missing)


def test_all_numbers_found_in_the_document():
    assert unfound_numbers(ExtractorOutput.model_validate(output()), DOC) == []


def test_a_number_not_in_the_document_is_flagged():
    data = output()
    data["series"][0]["y5"] = 55.0                                        # not printed anywhere
    result = asyncio.run(extract(DOC, run=FakeRun(data)))
    [warning] = [f for f in result.flags if f.level == "warning"]
    assert "fund_nav cumulative y5 = 55.0" in warning.message
    assert result.factsheet.series["fund_nav"].y5 == 55.0                # kept, but flagged for checking


def test_valid_answer():
    result = asyncio.run(extract(DOC, run=FakeRun(output())))
    assert result.factsheet is not None and [f.level for f in result.flags] == ["info"]
    assert "please verify" in result.flags[0].message


def test_output_that_does_not_convert_is_retried_once():
    bad = output(discrete_12m=[{"series": "index", "end_date": "Sep 2026", "value": 17.1}])   # not a date
    fake = FakeRun(bad, output())
    result = asyncio.run(extract(DOC, run=fake))
    assert result.factsheet is not None and len(fake.prompts) == 2


def test_invalid_twice_is_check_data():
    bad = output(discrete_12m=[{"series": "index", "end_date": "Sep 2026", "value": 17.1}])
    result = asyncio.run(extract(DOC, run=FakeRun(bad, {"series": "nonsense"})))
    [flag] = result.flags
    assert result.factsheet is None and flag.level == "blocking"
    assert flag.message.startswith("CHECK DATA: Extractor Agent gave no valid answer after one retry")


def _test1_output() -> dict:
    """ The Test 1 figures typed by hand, in the agent's output shape """
    fs = json.loads(TEST1_FACTSHEET.read_text())
    series = [{"name": n, "basis": b, "pricing": s.get("pricing"), "y1": s.get("1y"), "y3": s.get("3y"),
               "y5": s.get("5y"), "since_launch": s.get("since_launch")}
              for b, block in (("cumulative", fs["series"]), ("annualised", fs["series_annualised"])) for n, s in block.items()]
    years = [{"series": n, "year": y, "value": v} for n, ys in fs["calendar_years"].items() for y, v in ys.items()]
    windows = [{"series": n, "end_date": d, "value": v} for n, ws in fs["discrete_12m"].items() for d, v in ws.items()]
    empty = dict.fromkeys(["fund_vol", "index_vol", "tracking_error", "beta", "r2", "sharpe_fund", "sharpe_index",
                           "info_ratio", "alpha"])
    risk = [empty | fs["risk_3y"], empty | fs["risk_3y_nav"]]
    return output(series=series, calendar_years=years, discrete_12m=windows, risk=risk)


@requires_test1
def test_test1_every_typed_figure_is_found_in_the_real_factsheet():
    text = read_document(TEST1 / "Monthly_FactSheet.pdf")
    out = ExtractorOutput.model_validate(_test1_output())
    assert unfound_numbers(out.model_copy(update={"profile": ExtractedProfile.model_validate(
        output()["profile"] | {"ocf_pct": 0.06, "fund_size_gbp_m": 11006, "risk_indicator": 5})}), text) == []
    assert to_factsheet(out).series["fund_pnav"].y5 == 90.9


@pytest.mark.live
@requires_test1
def test_live_test1_extraction_matches_the_typed_figures():
    text = read_document(TEST1 / "Monthly_FactSheet.pdf") + "\n\n" + read_document(TEST1 / "Key_Investor_Info.pdf")
    result = asyncio.run(extract(text))
    print("\nExtractor flags:", [f.message for f in result.flags])
    manual = read_json(TEST1_FACTSHEET)
    fs = result.factsheet
    assert fs is not None
    for name in ("fund_nav", "fund_pnav", "index"):
        got, want = fs.series[name], manual.series[name]
        assert (got.y1, got.y3, got.y5) == (want.y1, want.y3, want.y5), name
    assert fs.risk("pnav").tracking_error == 0.02
    assert not any(f.level == "warning" for f in result.flags)
    assert "performance_fee_justification" not in result.profile_draft
