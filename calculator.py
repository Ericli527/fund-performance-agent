import os
import numpy as np
import pandas as pd

RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.0))


def _periods_per_year(dates: pd.Series) -> int:
    """ Guess the data frequency from the typical gap between dates """
    gap = dates.diff().dt.days.median()
    if gap <= 3:
        return 252
    if gap <= 8:
        return 52
    if gap <= 35:
        return 12
    return 4


def performance_metrics(nav: pd.DataFrame) -> pd.DataFrame:
    """ Return and risk metrics for the fund and benchmark, from NAV or price levels """
    n = _periods_per_year(nav["date"])
    returns = nav[["fund", "benchmark"]].pct_change().dropna()
    years = len(returns) / n

    def annual_return(col):
        return (nav[col].iloc[-1] / nav[col].iloc[0]) ** (1 / years) - 1

    def max_drawdown(col):
        levels = nav[col]
        return (levels / levels.cummax() - 1).min()

    rows = {}
    for col in ("fund", "benchmark"):
        ann_ret = annual_return(col)
        vol = returns[col].std() * np.sqrt(n)
        rows[col.capitalize()] = {
            "Total return": nav[col].iloc[-1] / nav[col].iloc[0] - 1,
            "Annualised return": ann_ret,
            "Annualised volatility": vol,
            "Sharpe ratio": (ann_ret - RISK_FREE_RATE) / vol,
            "Max drawdown": max_drawdown(col),
        }

    active = returns["fund"] - returns["benchmark"]
    tracking_error = active.std() * np.sqrt(n)
    excess = rows["Fund"]["Annualised return"] - rows["Benchmark"]["Annualised return"]
    rows["Relative"] = {
        "Excess return (annualised)": excess,
        "Tracking error": tracking_error,
        "Information ratio": excess / tracking_error,
        "Beta": returns["fund"].cov(returns["benchmark"]) / returns["benchmark"].var(),
    }
    return pd.DataFrame(rows)


def brinson_attribution(attr: pd.DataFrame) -> pd.DataFrame:
    """ Brinson-Fachler attribution by segment: allocation, selection and interaction """
    df = attr.copy()
    num_cols = ["fund_weight", "benchmark_weight", "fund_return", "benchmark_return"]
    df[num_cols] = df[num_cols].astype(float)
    # Weights given in percent (summing to ~100) mean returns are in percent too
    if df["benchmark_weight"].sum() > 1.5:
        df[num_cols] = df[num_cols] / 100

    total_benchmark_return = (df["benchmark_weight"] * df["benchmark_return"]).sum()
    active_weight = df["fund_weight"] - df["benchmark_weight"]

    df["Allocation"] = active_weight * (df["benchmark_return"] - total_benchmark_return)
    df["Selection"] = df["benchmark_weight"] * (df["fund_return"] - df["benchmark_return"])
    df["Interaction"] = active_weight * (df["fund_return"] - df["benchmark_return"])
    df["Total"] = df["Allocation"] + df["Selection"] + df["Interaction"]

    result = df[["sector", "fund_weight", "benchmark_weight", "fund_return", "benchmark_return",
                 "Allocation", "Selection", "Interaction", "Total"]].rename(columns={
        "sector": "Segment", "fund_weight": "Fund wt", "benchmark_weight": "Bmk wt",
        "fund_return": "Fund ret", "benchmark_return": "Bmk ret",
    })
    totals = {
        "Segment": "Total",
        "Fund wt": df["fund_weight"].sum(),
        "Bmk wt": df["benchmark_weight"].sum(),
        "Fund ret": (df["fund_weight"] * df["fund_return"]).sum(),
        "Bmk ret": total_benchmark_return,
        **{c: df[c].sum() for c in ["Allocation", "Selection", "Interaction", "Total"]},
    }
    return pd.concat([result, pd.DataFrame([totals])], ignore_index=True)


def _fmt(value, ratio: bool) -> str:
    # Adding 0.0 turns a rounded -0.0 into 0.0, so "-0.00%" never appears
    return f"{round(value, 2) + 0.0:.2f}" if ratio else f"{round(value, 4) + 0.0:.2%}"


def metrics_to_markdown(metrics: pd.DataFrame) -> str:
    ratios = {"Sharpe ratio", "Information ratio", "Beta"}
    lines = ["| Metric | Fund | Benchmark |", "|---|---|---|"]
    for metric in metrics.index:
        if metric in metrics["Fund"].dropna().index:
            r = metric in ratios
            lines.append(f"| {metric} | {_fmt(metrics.at[metric, 'Fund'], r)} | {_fmt(metrics.at[metric, 'Benchmark'], r)} |")
    lines += ["", "| Relative metric | Value |", "|---|---|"]
    for metric, value in metrics["Relative"].dropna().items():
        lines.append(f"| {metric} | {_fmt(value, metric in ratios)} |")
    return "\n".join(lines)


ATTRIBUTION_NOTE = "*Bmk = benchmark, wt = weight, ret = return. Effects are contributions to active return.*"


def attribution_to_markdown(attribution: pd.DataFrame) -> str:
    cols = list(attribution.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in attribution.iterrows():
        cells = [str(row["Segment"])] + [_fmt(row[c], ratio=False) for c in cols[1:]]
        if row["Segment"] == "Total":
            cells = [f"**{c}**" for c in cells]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n\n" + ATTRIBUTION_NOTE
