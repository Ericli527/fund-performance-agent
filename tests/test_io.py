""" File reader (spec 3.1): dates, trailing commas, '-' values, sorting, file types """
import pandas as pd
import pytest
from docx import Document
from fund_performance.io import (AmbiguousDatesError, DMY, MDY, YMD, detect_file_type, parse_dates,
                                 read_document, read_json, read_prices)
from fund_performance.models import FactsheetPerformance, FundProfile, Peer
from conftest import FIXTURES, TEST1_CSV, TEST1_FACTSHEET, TEST1_PROFILE, requires_test1


def test_us_dates_trailing_commas_dashes_and_sorting():
    data = read_prices(FIXTURES / "prices_us_dates_trailing_comma.csv")
    p = data.prices
    assert data.date_format == MDY
    assert any("Trailing comma" in line for line in data.log)
    assert any("2 '-' or blank value(s) read as missing" in line for line in data.log)
    assert any("sorted" in line for line in data.log)
    assert list(p.columns) == ["date", "nav"]                    # the Name column and the empty field are gone
    assert p["date"].is_monotonic_increasing
    assert p["nav"].isna().tolist() == [False, False, True, True, False]   # Mar '-' and Apr blank
    assert p["nav"].iloc[1] == 10.20                              # Feb row moved into place


def test_uk_dates_with_index_column():
    data = read_prices(FIXTURES / "prices_uk_dates_with_index.csv")
    assert data.date_format == DMY and data.has_index
    assert data.prices["index_level"].tolist() == [1000.0, 1011.0, 1024.0, 1018.0]
    assert data.frequency == "monthly"


def test_ambiguous_dates_use_the_order_that_gives_one_price_per_month():
    data = read_prices(FIXTURES / "prices_first_of_month.csv")
    assert data.date_format == DMY
    assert data.prices["date"].dt.month.tolist() == [2, 3, 4, 5]
    assert "one price per month" in data.log[0]


def test_ambiguous_dates_that_fit_both_orders_stop_and_ask():
    with pytest.raises(AmbiguousDatesError, match="confirm the date format"):
        read_prices(FIXTURES / "prices_ambiguous_dates.csv")


def test_iso_dates():
    dates, fmt, _ = parse_dates(pd.Series(["2024-01-31", "2024-02-29"]))
    assert fmt == YMD and dates.iloc[1] == pd.Timestamp("2024-02-29")


def test_a_non_empty_extra_value_is_an_error_not_dropped():
    with pytest.raises(ValueError, match="more values than there are column names"):
        read_prices(FIXTURES / "prices_extra_value.csv")


def test_text_in_a_number_column_is_an_error(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("date,nav\n2024-01-31,10.0\n2024-02-29,ten\n")
    with pytest.raises(ValueError, match="not numbers"):
        read_prices(path)


def test_duplicate_dates_are_an_error(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("date,nav\n2024-01-31,10.0\n2024-01-31,10.1\n")
    with pytest.raises(ValueError, match="more than once"):
        read_prices(path)


def test_excel_with_index_level_column(tmp_path):
    path = tmp_path / "daily.xlsx"
    pd.DataFrame({"Date": pd.to_datetime(["2024-06-26", "2024-06-27", "2024-06-28"]),
                  "NAV": [10.0, 10.1, 10.2], "Index Level": [500.0, 501.0, "-"]}).to_excel(path, index=False)
    data = read_prices(path)
    assert data.date_format == "Excel date" and data.has_index
    assert data.prices["index_level"].isna().tolist() == [False, False, True]
    assert data.frequency == "daily"


def test_detect_file_types(tmp_path):
    assert detect_file_type(FIXTURES / "prices_uk_dates_with_index.csv") == "prices"
    assert detect_file_type(FIXTURES / "fund_profile_sample.json") == "fund_profile"
    assert detect_file_type(FIXTURES / "factsheet_performance_sample.json") == "factsheet_performance"
    assert detect_file_type(FIXTURES / "peer_sample.json") == "peer"
    (tmp_path / "notes.txt").write_text("hello")
    assert detect_file_type(tmp_path / "notes.txt") == "document"
    (tmp_path / "other.csv").write_text("sector,weight\nIT,40\n")
    assert detect_file_type(tmp_path / "other.csv") == "unknown"


def test_read_json_returns_the_right_model():
    assert isinstance(read_json(FIXTURES / "fund_profile_sample.json"), FundProfile)
    assert isinstance(read_json(FIXTURES / "factsheet_performance_sample.json"), FactsheetPerformance)
    assert isinstance(read_json(FIXTURES / "peer_sample.json"), Peer)


def test_read_documents(tmp_path):
    (tmp_path / "a.txt").write_text("Manager commentary")
    doc = Document()
    doc.add_paragraph("Quarterly review")
    doc.save(tmp_path / "b.docx")
    assert read_document(tmp_path / "a.txt") == "Manager commentary"
    assert "Quarterly review" in read_document(tmp_path / "b.docx")


@requires_test1
def test_test1_csv():
    data = read_prices(TEST1_CSV)
    p = data.prices
    assert data.date_format == MDY
    assert data.log[0] == "Trailing comma: removed an empty extra field from 167 row(s)"
    assert len(p) == 167 and p["nav"].notna().all()
    assert p["date"].iloc[0] == pd.Timestamp("2012-11-30") and p["date"].iloc[-1] == pd.Timestamp("2026-09-30")
    assert p["nav"].iloc[-1] == 6.2578
    assert data.frequency == "monthly"


@requires_test1
def test_test1_json_files_are_detected():
    assert detect_file_type(TEST1_PROFILE) == "fund_profile"
    assert detect_file_type(TEST1_FACTSHEET) == "factsheet_performance"
