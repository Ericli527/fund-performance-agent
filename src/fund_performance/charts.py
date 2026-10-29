""" Charts for the report (spec 4.7): growth of 100 and yearly returns, fund vs index """
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

NAVY, GREY = "#1f3a5f", "#9aa7b4"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 9,
                     "axes.spines.top": False, "axes.spines.right": False})


def growth_chart(labels: list[str], fund: list[float], index: list[float], path: Path,
                 fund_label: str, index_label: str, title: str) -> Path:
    """ Growth of 100: values already rebased to 100 at the first point """
    fig, ax = plt.subplots(figsize=(3.6, 2.0), dpi=200)
    x = np.arange(len(labels))
    ax.plot(x, fund, color=NAVY, linewidth=1.8, label=fund_label)
    ax.plot(x, index, color=GREY, linewidth=1.4, linestyle="--", label=index_label)
    step = max(1, -(-len(labels) // 6))                  # at most about 6 labels, so they never overlap
    ax.set_xticks(x[::step], [labels[i] for i in range(0, len(labels), step)])
    ax.set_title(title, loc="left", fontweight="bold", color=NAVY)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def yearly_returns_chart(labels: list[str], fund: list[float], index: list[float], path: Path,
                         fund_label: str, index_label: str, title: str) -> Path:
    """ Returns in percent for each period, fund vs index, side by side """
    fig, ax = plt.subplots(figsize=(3.6, 2.0), dpi=200)
    x = np.arange(len(labels))
    ax.bar(x - 0.2, fund, width=0.4, color=NAVY, label=fund_label)
    ax.bar(x + 0.2, index, width=0.4, color=GREY, label=index_label)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(x, labels)
    ax.set_ylabel("%")
    ax.set_title(title, loc="left", fontweight="bold", color=NAVY)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def rebase(returns_pct: list[float]) -> list[float]:
    """ Growth of 100 from period returns in percent: [100, 100*(1+r1), ...] """
    values = [100.0]
    for r in returns_pct:
        values.append(values[-1] * (1 + r / 100))
    return values
