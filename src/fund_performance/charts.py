""" Charts for the report (spec 4.7): growth of 100 and yearly returns, fund vs index """
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

NAVY, GREY = "#1f3a5f", "#9aa7b4"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 9,
                     "axes.spines.top": False, "axes.spines.right": False})


def dashboard_five_year_chart(prices: pd.DataFrame, as_of, fund_currency: str, fund_pricing: str | None,
                              evidence: dict | None, path: Path) -> dict:
    """Plot only confirmed, aligned total-return observations; never fill missing prices."""
    unavailable = lambda why: {'available': False, 'reason': why}
    e = evidence or {}
    if (e.get('confirmed') is not True or e.get('benchmark_identity_confirmed') is not True
            or e.get('fund_total_return') is not True or e.get('benchmark_total_return') is not True):
        return unavailable('The benchmark identity, shared currency and total-return basis have not been confirmed.')
    currency = str(e.get('currency') or '').strip().upper()
    if not currency or currency != str(fund_currency or '').upper():
        return unavailable('The confirmed series currency does not match the fund currency.')
    fund_time, index_time = e.get('fund_pricing'), e.get('benchmark_pricing')
    if fund_time not in ('midday', 'market_close') or index_time not in ('midday', 'market_close'):
        return unavailable('The pricing times for both series have not been confirmed.')
    if fund_pricing and fund_pricing != fund_time:
        return unavailable('The confirmed fund pricing time conflicts with the fund profile.')
    if not {'date', 'nav', 'index_level'} <= set(prices.columns):
        return unavailable('The price history does not contain an aligned benchmark series.')
    end = pd.Timestamp(as_of)
    start = end - pd.DateOffset(years=5)
    p = prices.loc[(prices['date'] >= start) & (prices['date'] <= end), ['date', 'nav', 'index_level']].copy()
    if p.empty or p['date'].duplicated().any() or not p['date'].is_monotonic_increasing:
        return unavailable('The five-year observations are missing, duplicated or not ordered.')
    if p['date'].iloc[0] != start or p['date'].iloc[-1] != end or len(p) < 3:
        return unavailable('Aligned observations are not available at both exact five-year endpoints.')
    if p['date'].diff().dropna().max() > pd.Timedelta(days=45):
        return unavailable('The five-year series has a gap too large for a continuous comparison.')
    if p[['nav', 'index_level']].isna().any().any() or not np.isfinite(p[['nav', 'index_level']].to_numpy()).all() or (p[['nav', 'index_level']] <= 0).any().any():
        return unavailable('The five-year series contains missing or invalid observations.')
    labels = [f'{d:%b %Y}' for d in p['date']]
    fund = (p['nav'] / p['nav'].iloc[0] * 100).tolist()
    benchmark = (p['index_level'] / p['index_level'].iloc[0] * 100).tolist()
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=150)
    x = np.arange(len(labels))
    ax.plot(x, fund, color=NAVY, linewidth=2, label='Fund NAV-based total return')
    ax.plot(x, benchmark, color='#447c9d', linewidth=1.8, linestyle='--', label='Benchmark total return')
    step = max(1, -(-len(labels) // 6))
    ax.set_xticks(x[::step], [labels[i] for i in range(0, len(labels), step)])
    ax.set_ylabel('Growth of 100')
    ax.set_title('Five-year cumulative performance', loc='left', fontweight='bold', color=NAVY)
    ax.grid(axis='y', alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    words = {'midday': 'noon', 'market_close': 'market close'}
    timing = f"Fund NAV-based series: {words[fund_time]}; benchmark: {words[index_time]}."
    if fund_time != index_time:
        timing += ' Pricing times differ, which can affect the comparison.'
    return {'available': True, 'file': path.name,
            'caption': f"Growth of 100 from {start:%d %b %Y} to {end:%d %b %Y}, {currency}. "
                       f"User-confirmed total-return basis; observed prices, no interpolation. {timing}"}


def allocation_chart(items: list[tuple[str, float]], path: Path, title: str) -> Path:
    """Plot already source-checked allocation weights without deriving or filling any values."""
    fig, ax = plt.subplots(figsize=(6, max(1.8, len(items) * .35)), dpi=150)
    names, values = zip(*items)
    ax.barh(range(len(items)), values, color='#447c9d')
    ax.set_yticks(range(len(items)), names)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel('Weight (%)')
    ax.set_title(title, loc='left', color=NAVY, fontweight='bold')
    ax.grid(axis='x', alpha=.2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


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


# --- Evidence dashboard (Phase C) --------------------------------------------------------------------------------

GREEN_BAND, AMBER_BAND = "#d8ecd9", "#fbe7bf"
PEER_COLOURS = ["#6d4c9f", "#2e7d32", "#c26a00", "#00838f", "#8d6e63"]


def _finish(fig, ax, path: Path, title: str) -> Path:
    ax.set_title(title, loc="left", fontweight="bold", color=NAVY)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def yearly_gap_chart(years: list[str], gaps: list[float], path: Path, title: str, ocf: float | None = None,
                     green: float | None = None, amber: float | None = None) -> Path:
    """ Fund minus index each calendar year; for an index fund, the fee as a line and the Green and Amber limits as
    bands (the limits are for the size of the gap, so the bands are drawn on both sides of zero) """
    fig, ax = plt.subplots(figsize=(3.6, 2.4), dpi=200)
    x = np.arange(len(years))
    if green is not None and amber is not None:
        ax.axhspan(-amber, amber, color=AMBER_BAND, zorder=0, label=f"Amber: within ±{amber:.2f}")
        ax.axhspan(-green, green, color=GREEN_BAND, zorder=0, label=f"Green: within ±{green:.2f}")
    ax.bar(x, gaps, width=0.6, color=NAVY, zorder=2, label="Fund minus index")
    if ocf is not None:
        ax.axhline(-ocf, color="#c62828", linewidth=1, linestyle="--", zorder=3, label=f"Fee: −{ocf:.2f}")
    ax.axhline(0, color="black", linewidth=0.6, zorder=3)
    ax.set_xticks(x, [f"'{y[2:]}" for y in years])
    ax.set_ylabel("pp")
    edge = amber if amber is not None else 0
    low, high = min(gaps + [-edge]), max(gaps + [edge])
    ax.set_ylim(low - 0.1 * (high - low), high + 0.1 * (high - low))
    ax.legend(frameon=False, fontsize=6.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    return _finish(fig, ax, path, title)


def peer_returns_chart(periods: list[str], series: dict[str, list[float | None]], path: Path, title: str) -> Path:
    """ Grouped bars: fund, index and each peer, per period (% a year) """
    fig, ax = plt.subplots(figsize=(3.6, 2.4), dpi=200)
    x = np.arange(len(periods))
    names = list(series)
    width = 0.8 / max(1, len(names))
    colours = [NAVY, GREY] + PEER_COLOURS
    for i, name in enumerate(names):
        values = [np.nan if v is None else v for v in series[name]]
        ax.bar(x - 0.4 + width * (i + 0.5), values, width=width, color=colours[i % len(colours)], label=name)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(x, periods)
    ax.set_ylabel("% a year")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False, fontsize=6.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    return _finish(fig, ax, path, title)


def limits_chart(rows: list[dict], path: Path, title: str) -> Path:
    """ One bullet bar per rated metric: its Green, Amber and Red zones and the value as a marker. Each row has
    its own scale, so metrics in different units sit together """
    fig, axes = plt.subplots(len(rows), 1, figsize=(3.6, 0.42 * len(rows) + 0.45), dpi=200, squeeze=False)
    for ax, row in zip(axes[:, 0], rows):
        value, kind = row["value"], row["kind"]
        if kind == "max":
            top = max(row["amber"] * 1.5, value * 1.15, row["amber"] + 0.01)
            zones = [(0, row["green"], GREEN_BAND), (row["green"], row["amber"], AMBER_BAND), (row["amber"], top, "#f6d0cf")]
            lo, hi = 0, top
        elif kind == "min":
            lo = min(row["amber"] - (row["green"] - row["amber"]), value - 0.005)
            zones = [(lo, row["amber"], "#f6d0cf"), (row["amber"], row["green"], AMBER_BAND), (row["green"], 1.0, GREEN_BAND)]
            hi = 1.0
        else:                                                   # range: Green and Amber are (low, high) pairs
            (g_lo, g_hi), (a_lo, a_hi) = row["green"], row["amber"]
            lo, hi = min(a_lo - (g_lo - a_lo), value - 0.01), max(a_hi + (a_hi - g_hi), value + 0.01)
            zones = [(lo, a_lo, "#f6d0cf"), (a_lo, g_lo, AMBER_BAND), (g_lo, g_hi, GREEN_BAND),
                     (g_hi, a_hi, AMBER_BAND), (a_hi, hi, "#f6d0cf")]
        for start, end, colour in zones:
            ax.barh(0, end - start, left=start, height=0.8, color=colour)
        ax.plot([value], [0], marker="D", color=NAVY, markersize=4.5)
        ax.set_xlim(lo, hi)
        ax.set_yticks([0], [row["metric"]], fontsize=6)
        ax.tick_params(axis="x", labelsize=5.5)
        ax.spines["left"].set_visible(False)
        ax.text(hi, 0, f" {value:.2f}{row['unit'] if row['unit'] == '%' else (' pp' if row['unit'] == 'pp' else '')}",
                va="center", fontsize=6, color=NAVY)
    axes[0, 0].set_title(title, loc="left", fontweight="bold", color=NAVY)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def scatter_chart(points: list[tuple[str, float, float]], path: Path, title: str) -> Path:
    """ Return (% a year) against volatility (%), one labelled point per fund """
    fig, ax = plt.subplots(figsize=(3.6, 2.1), dpi=200)
    colours = [NAVY, GREY] + PEER_COLOURS
    for i, (name, vol, ret) in enumerate(points):
        ax.scatter([vol], [ret], color=colours[i % len(colours)], s=18, zorder=3)
        ax.annotate(name, (vol, ret), textcoords="offset points", xytext=(4, 3), fontsize=5.5)
    ax.set_xlabel("Volatility, % a year")
    ax.set_ylabel("Return, % a year")
    ax.grid(alpha=0.3)
    ax.margins(0.25)
    return _finish(fig, ax, path, title)
