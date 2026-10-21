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
