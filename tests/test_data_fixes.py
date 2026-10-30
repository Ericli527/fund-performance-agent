""" Stage 4B data fixes, on made-up data only: price downloads (title rows, "Sept", currency-formatted values, newest
first), the review-date cutoff, and the declared return basis (annualised kept annualised) """
import json
import shutil
from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from fund_performance.calc import annualise, cumulate
from fund_performance.checks import after_review_date
from fund_performance.io import DMON, parse_dates, read_prices

PORTABLE = Path(__file__).parent / "fixtures" / "portable"


# --- 1. Price downloads -------------------------------------------------------------------------------------------

def download_rows(dates_and_prices):
    """ A provider-style download: title rows, a blank row, then "Date" and "NAV (GBP)" with £ values, newest first """
    return ([["This file was downloaded on 30 Oct 2026", None], ["Historical Prices", None], [None, None],
             ["Sample Fund GBP Acc", None], ["Inception date", "08 Nov 2016"], [None, None], ["Date", "NAV (GBP)"]]
            + [[d, f"£{p:,.4f}"] for d, p in dates_and_prices])


PRICES = [("02 Oct 2026", 1205.5), ("30 Sept 2026", 1200.0), ("29 Sept 2026", 1190.25), ("31 Aug 2026", 1180.0),
          ("1 March 2026", 1100.0)]


def test_an_excel_download_with_title_rows_sept_and_pound_signs(tmp_path):
    path = tmp_path / "prices.xlsx"
    pd.DataFrame(download_rows(PRICES)).to_excel(path, header=False, index=False)
    data = read_prices(path)
    assert data.date_format == DMON
    assert list(data.prices["date"].dt.strftime("%Y-%m-%d")) == [
        "2026-03-01", "2026-08-31", "2026-09-29", "2026-09-30", "2026-10-02"]          # every September price kept
    assert list(data.prices["nav"]) == [1100.0, 1180.0, 1190.25, 1200.0, 1205.5]     # "£1,205.5000" -> 1205.5
    assert "Skipped 6 title row(s) above the column names" in data.log and "Rows sorted into date order" in data.log


def test_a_csv_download_with_title_rows_and_currency_codes(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("Fund prices,\nDownloaded 30 Oct 2026,\nDate,Price (GBP)\n30-Sep-2026,GBP 1234.50\n"
                    "31-Aug-2026,\"1,200.00 GBP\"\n")
    data = read_prices(path)
    assert list(data.prices["nav"]) == [1200.0, 1234.5] and "Skipped 2 title row(s) above the column names" in data.log


def test_unknown_month_names_and_text_values_still_stop_the_run(tmp_path):
    with pytest.raises(ValueError, match="Month names not recognised"):
        parse_dates(pd.Series(["30 Sept 2026", "31 Foo 2026"]))
    path = tmp_path / "prices.xlsx"
    pd.DataFrame(download_rows([("30 Sept 2026", 1.0)]) + [["31 Aug 2026", "about £1"]]).to_excel(
        path, header=False, index=False)
    with pytest.raises(ValueError, match="not numbers"):
        read_prices(path)


def test_monthly_numeric_dates_newest_first_still_resolve_the_day_month_order():
    dates, fmt, _ = parse_dates(pd.Series(["03/31/2026", "02/28/2026", "01/31/2026"]))
    assert fmt == "MM/DD/YYYY"
    dates, fmt, why = parse_dates(pd.Series(["12/01/2026", "11/01/2026", "10/01/2026"]))   # newest first, all <= 12
    assert fmt == "MM/DD/YYYY" and "one price per month" in why


# --- 2. Review-date cutoff -----------------------------------------------------------------------------------------

def test_prices_after_the_review_date_are_left_out_with_an_info_flag():
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-08-31", "2026-09-30", "2026-10-01", "2026-10-29"]),
                           "nav": [1.0, 1.1, 1.2, 1.3]})
    kept, flags = after_review_date(prices, date(2026, 9, 30))
    assert list(kept["nav"]) == [1.0, 1.1]
    assert [f.level for f in flags] == ["info"] and flags[0].check == "review_date_cutoff"
    assert flags[0].message == ("2 price(s) dated after the review date 30 Sep 2026 left out (01 Oct 2026 to "
                                "29 Oct 2026); figures are as at the review date")
    assert after_review_date(kept, date(2026, 9, 30)) == (kept, [])


def test_later_prices_cannot_change_the_reported_returns(tmp_path):
    """ A file downloaded a month after the review gives the same figures as one that stops on the review date """
    import asyncio
    from fund_performance.controller import run_review
    later = tmp_path / "later"
    shutil.copytree(PORTABLE, later)
    prices = pd.read_csv(later / "prices.csv")
    extra = pd.DataFrame({"Date": ["2026-01-31", "2026-02-28"], "NAV": [999.0, 5.0]})
    pd.concat([prices, extra]).iloc[::-1].to_csv(later / "prices.csv", index=False)      # newest first, too
    base = asyncio.run(run_review(PORTABLE, out_root=tmp_path / "a", offline=True))
    result = asyncio.run(run_review(later, out_root=tmp_path / "b", offline=True))
    figures = lambda r: {f["name"]: f["value"] for f in r.facts["figures"]}  # noqa: E731
    assert figures(result) == figures(base)
    assert result.facts["scorecard"] == base.facts["scorecard"]
    assert any(f.check == "review_date_cutoff" and "2 price(s)" in f.message for f in result.flags)


# --- 3. Declared return basis ----------------------------------------------------------------------------------------

def annualised_inputs(tmp_path, since_launch=None):
    """ The portable fund with its NAV returns given as a-year figures (as some factsheets print them) """
    folder = tmp_path / "ann"
    shutil.copytree(PORTABLE, folder)
    fs = json.loads((folder / "factsheet_performance.json").read_text())
    nav = fs["series"]["fund_nav"]
    fs["series"]["fund_nav"] = {"1y": nav["1y"], "3y": round(annualise(nav["3y"], 3), 4),
                                "5y": round(annualise(nav["5y"], 5), 4), "basis": "annualised", "pricing": "midday"}
    if since_launch is not None:
        fs["series"]["fund_nav"]["since_launch"] = since_launch
    (folder / "factsheet_performance.json").write_text(json.dumps(fs))
    return folder


def test_an_annualised_series_is_kept_annualised_and_its_cumulative_derived(tmp_path):
    from test_portable_financial import pipeline
    _, _, reported, _ = pipeline(annualised_inputs(tmp_path))
    f = reported.figures
    assert (f["fund_nav.ann.5y"].source, f["fund_nav.ann.5y"].exact) == ("factsheet", round(annualise(60.0, 5), 4))
    assert f["fund_nav.cum.5y"].source == "calculated" and f["fund_nav.cum.5y"].value == pytest.approx(60.0, abs=0.01)
    assert f["fund_nav.cum.3y"].value == pytest.approx(29.0, abs=0.01) and f["fund_nav.cum.1y"].value == 8.1
    assert not any(x.check == "cross_check" for x in reported.flags)      # compared a-year with a-year: no false alarm
    assert any("Cross-check 5y NAV return a year" in line for line in reported.log)


def test_the_same_returns_give_the_same_figures_whichever_basis_they_are_given_in(tmp_path):
    from test_portable_financial import pipeline
    _, _, cumulative, card_c = pipeline(PORTABLE)
    _, _, annualised, card_a = pipeline(annualised_inputs(tmp_path))
    for name in ("fund_nav.cum.3y", "fund_nav.cum.5y", "fund_nav.ann.3y", "fund_nav.ann.5y"):
        assert annualised.figures[name].value == pytest.approx(cumulative.figures[name].value, abs=0.01), name
    assert card_a.verdict == card_c.verdict


def test_a_wrong_annualised_figure_is_still_caught_by_the_cross_check(tmp_path):
    from test_portable_financial import pipeline
    folder = annualised_inputs(tmp_path)
    fs = json.loads((folder / "factsheet_performance.json").read_text())
    fs["series"]["fund_nav"]["5y"] = 12.0                                  # the prices give about 9.86% a year
    (folder / "factsheet_performance.json").write_text(json.dumps(fs))
    _, _, reported, _ = pipeline(folder)
    assert [x.message for x in reported.flags if x.check == "cross_check"] == [
        "5y: calculated 9.86% vs factsheet 12.0% (gap above 0.3 pp); the factsheet figure is used"]


def test_an_annualised_since_launch_figure_is_never_read_as_cumulative(tmp_path):
    from test_portable_financial import pipeline
    _, _, reported, _ = pipeline(annualised_inputs(tmp_path, since_launch=9.86))
    assert reported.figures["fund_nav.since_launch.ann"].exact == 9.86
    assert reported.figures["fund_nav.since_launch.cum"].source == "calculated"


def test_cumulate_is_the_inverse_of_annualise():
    assert cumulate(annualise(88.3, 5), 5) == pytest.approx(88.3)
