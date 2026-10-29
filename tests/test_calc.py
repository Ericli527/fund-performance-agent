""" Calculator (spec 4). Only calendar-year returns so far; the rest arrives in step 3 """
import pandas as pd
import pytest
from fund_performance.calc import calendar_year_returns


def test_calendar_year_returns_from_year_end_prices():
    prices = pd.DataFrame({"date": pd.to_datetime(["2022-12-31", "2023-06-30", "2023-12-31", "2024-12-31", "2025-03-31"]),
                           "nav": [100.0, 105.0, 110.0, 121.0, 125.0]})
    years = calendar_year_returns(prices, "nav")
    assert years == {"2023": pytest.approx(10.0), "2024": pytest.approx(10.0)}   # 2025 is not a full year
