import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FUND_COLOUR = "#12355b"
BENCHMARK_COLOUR = "#9aa5b1"
ACCENT_COLOUR = "#2e86ab"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10})


def growth_chart(nav: pd.DataFrame, path: str) -> str:
    """ Growth of 100 for the fund and benchmark """
    fig, ax = plt.subplots(figsize=(8, 3.1), dpi=150)
    for col, colour in (("fund", FUND_COLOUR), ("benchmark", BENCHMARK_COLOUR)):
        ax.plot(nav["date"], nav[col] / nav[col].iloc[0] * 100, label=col.capitalize(), color=colour, linewidth=2)
    ax.set_title("Growth of 100", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def drawdown_chart(nav: pd.DataFrame, path: str) -> str:
    """ Fall from the previous peak, for the fund and benchmark """
    fig, ax = plt.subplots(figsize=(8, 2.6), dpi=150)
    for col, colour in (("fund", FUND_COLOUR), ("benchmark", BENCHMARK_COLOUR)):
        drawdown = (nav[col] / nav[col].cummax() - 1) * 100
        ax.plot(nav["date"], drawdown, label=col.capitalize(), color=colour, linewidth=1.8)
        if col == "fund":
            ax.fill_between(nav["date"], drawdown, 0, color=colour, alpha=0.12)
    ax.set_title("Drawdown from previous peak (%)", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def attribution_chart(attribution: pd.DataFrame, path: str) -> str:
    """ Allocation and selection (incl. interaction) effects by segment """
    df = attribution[attribution["Segment"] != "Total"].reset_index(drop=True)
    y = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(df) + 1.4), dpi=150)
    ax.barh(y - 0.2, df["Allocation"] * 100, height=0.4, label="Allocation", color=ACCENT_COLOUR)
    ax.barh(y + 0.2, (df["Selection"] + df["Interaction"]) * 100, height=0.4,
            label="Selection + interaction", color=FUND_COLOUR)
    ax.set_yticks(y, df["Segment"])
    ax.invert_yaxis()
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Contribution to active return (%)")
    ax.set_title("Attribution by segment", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


DONUT_COLOURS = ["#12355b", "#2e86ab", "#e0a100", "#c0392b", "#7b5ea7", "#3a9d5d",
                 "#e67e22", "#5d6d7e", "#a3c4dc", "#d4a5a5", "#9aa5b1", "#c8d6e5"]


def cumulative_chart(nav: pd.DataFrame, path: str) -> str:
    """ Compact factsheet chart: fund (filled) vs benchmark, rebased to 100 """
    fig, ax = plt.subplots(figsize=(4.6, 2.3), dpi=200)
    fund = nav["fund"] / nav["fund"].iloc[0] * 100
    bench = nav["benchmark"] / nav["benchmark"].iloc[0] * 100
    ax.fill_between(nav["date"], fund, fund.min() * 0.95, color=FUND_COLOUR, alpha=0.85, label="Fund", linewidth=0)
    ax.plot(nav["date"], bench, color=ACCENT_COLOUR, linewidth=1.4, label="Benchmark")
    ax.set_ylim(fund.min() * 0.95, max(fund.max(), bench.max()) * 1.03)
    ax.tick_params(labelsize=6.5)
    ax.legend(frameon=False, fontsize=6.5, loc="upper left", ncol=2)
    ax.grid(axis="y", alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.4)
    fig.savefig(path)
    plt.close(fig)
    return path


def donut_chart(weights: pd.DataFrame, path: str) -> str:
    """ Small donut of fund weights; the table next to it carries the labels """
    fig, ax = plt.subplots(figsize=(1.6, 1.6), dpi=200)
    ax.pie(weights["fund_weight"].clip(lower=0), colors=DONUT_COLOURS[:len(weights)], startangle=90,
           counterclock=False, wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 0.6})
    ax.set_aspect("equal")
    fig.tight_layout(pad=0.1)
    fig.savefig(path, transparent=True)
    plt.close(fig)
    return path
