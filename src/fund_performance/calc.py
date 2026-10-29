""" Calculator formulas (spec Section 4). The rest of this module is built in step 3 """
import pandas as pd


def calendar_year_returns(prices: pd.DataFrame, column: str) -> dict[str, float]:
    """ Spec 4.1: P_Dec31(y) / P_Dec31(y-1) - 1 in percent, for each full year in the data.
    P_Dec31 is the last price on or before 31 December. Built in step 2 because the currency check uses it """
    series = prices.set_index("date")[column].dropna()
    year_end = series.groupby(series.index.year).last()
    # A year counts only if the data reaches 31 December (or its last business day) of that year
    last_date = series.groupby(series.index.year).apply(lambda s: s.index.max())
    full = [y for y in year_end.index if last_date[y].month == 12 and last_date[y].day >= 24]
    return {str(y): (year_end[y] / year_end[y - 1] - 1) * 100
            for y in full if y - 1 in full}
