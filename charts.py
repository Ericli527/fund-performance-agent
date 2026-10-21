import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FUND_COLOUR = "#209dd7"
BENCHMARK_COLOUR = "#6f6f72"


def growth_chart(nav: pd.DataFrame, path: str) -> str:
    """ Growth of 100 for the fund and benchmark """
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    for col, colour in (("fund", FUND_COLOUR), ("benchmark", BENCHMARK_COLOUR)):
        ax.plot(nav["date"], nav[col] / nav[col].iloc[0] * 100, label=col.capitalize(), color=colour, linewidth=2)
    ax.set_title("Growth of 100", loc="left", fontsize=11, fontweight="bold")
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
    ax.barh(y - 0.2, df["Allocation"] * 100, height=0.4, label="Allocation", color="#ecad0a")
    ax.barh(y + 0.2, (df["Selection"] + df["Interaction"]) * 100, height=0.4,
            label="Selection + interaction", color=FUND_COLOUR)
    ax.set_yticks(y, df["Segment"])
    ax.invert_yaxis()
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Contribution to active return (%)")
    ax.set_title("Attribution by segment", loc="left", fontsize=11, fontweight="bold")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
