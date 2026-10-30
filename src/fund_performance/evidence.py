""" The evidence dashboard's statistics (Phase C): code only, no AI

- Yearly gaps: fund minus index for each full calendar year (factsheet), using the market-close price (PNAV) when
  the factsheet gives it, else the noon price (NAV).
- Statistics: hit rate (years within OCF + the hit-rate margin), average, best and worst yearly gap.
- Significance test: a one-sample t-test (two-sided) of the fee-adjusted yearly gap (gap + OCF) against zero for
  index funds, or the yearly excess return against zero for active funds. It runs only with at least
  `min_points` years, and not when rounding makes most values identical. The level is in config/settings.yaml.
- Peer percentile: with 3 or more peers whose returns can be used, the share of them the fund beat.
"""
from dataclasses import asdict, dataclass, field
import math
from collections import Counter
from fund_performance.config import StatisticsSettings, Thresholds
from fund_performance.models import FundProfile
from fund_performance.peers import PeerComparison
from fund_performance.precedence import ReportedFigures

NOT_RELIABLE = "Not reliable: the data is rounded and too short for a significance test"


# --- The t distribution, without scipy ---------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """ Continued fraction for the incomplete beta function (Numerical Recipes, 6.4) """
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """ Regularised incomplete beta function I_x(a, b) """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_p_value(t: float, df: int) -> float:
    """ Two-sided p-value of a t-statistic with df degrees of freedom """
    return _betainc(df / 2, 0.5, df / (df + t * t))


# --- Yearly gaps and the statistics ------------------------------------------------------------------------------

def _years(reported: ReportedFigures, series: str) -> dict[str, float]:
    prefix = f"{series}.calendar."
    return {k.rsplit(".", 1)[1]: f.exact if f.exact is not None else f.value
            for k, f in reported.figures.items() if k.startswith(prefix) and k[-1].isdigit()}


def yearly_gaps(reported: ReportedFigures) -> tuple[dict[str, float], str]:
    """ Fund minus index for each calendar year both have, and the fund series used (PNAV preferred) """
    index = _years(reported, "index")
    for series in ("fund_pnav", "fund_nav"):
        fund = _years(reported, series)
        common = sorted(set(fund) & set(index))
        if common:
            return {y: fund[y] - index[y] for y in common[-10:]}, series
    return {}, ""


@dataclass
class TTest:
    what: str                          # e.g. "fee-adjusted yearly gap (gap + OCF)"
    n: int
    mean: float | None = None
    t: float | None = None
    p: float | None = None
    significant: bool | None = None
    result: str = ""                   # the plain result, e.g. "Not statistically significant (p = 0.41): ..."


def t_test(values: list[float], what: str, stats: StatisticsSettings) -> TTest:
    """ One-sample t-test of the mean against zero, two-sided """
    n = len(values)
    out = TTest(what, n)
    if n < stats.min_points:
        out.result = f"Not run: {n} yearly values, at least {stats.min_points} are needed"
        return out
    rounded = Counter(round(v, 2) for v in values)
    if rounded.most_common(1)[0][1] > n / 2:
        out.result = NOT_RELIABLE
        return out
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    out.mean = mean
    if sd == 0:
        out.result = NOT_RELIABLE
        return out
    out.t = mean / (sd / math.sqrt(n))
    out.p = t_p_value(out.t, n - 1)
    out.significant = out.p < stats.significance_level
    p_text = "p < 0.001" if out.p < 0.001 else f"p = {out.p:.2f}" if out.p >= 0.01 else f"p = {out.p:.3f}"
    out.result = (f"Statistically significant ({p_text}): the gap is unlikely to be chance" if out.significant else
                  f"Not statistically significant ({p_text}): the gap could be chance")
    return out


@dataclass
class Evidence:
    gaps: dict[str, float] = field(default_factory=dict)     # year -> fund minus index, pp
    series: str = ""                                          # fund series used for the gaps
    hit_rate: tuple[int, int] | None = None                   # years within OCF + margin, years
    hit_margin_pp: float | None = None
    average: float | None = None
    best: tuple[str, float] | None = None
    worst: tuple[str, float] | None = None
    test: TTest | None = None
    percentile: dict | None = None                            # {"beaten": k, "peers": n, "percentile": p}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["test"] = asdict(self.test) if self.test else None
        return data


def peer_percentile(comparison: PeerComparison | None) -> dict | None:
    """ With 3 or more peers whose returns can be used: how many the fund beat over the main period """
    if comparison is None or len(comparison.used) < 3:
        return None
    used = comparison.used
    beaten = sum(1 for r in used if r.gap < 0)
    return {"beaten": beaten, "peers": len(used), "percentile": round(100 * beaten / len(used)),
            "years": comparison.years}


def build_evidence(reported: ReportedFigures, profile: FundProfile, t: Thresholds, stats: StatisticsSettings,
                   comparison: PeerComparison | None = None) -> Evidence:
    gaps, series = yearly_gaps(reported)
    ev = Evidence(gaps, series, percentile=peer_percentile(comparison))
    if not gaps:
        return ev
    values = list(gaps.values())
    ev.average = sum(values) / len(values)
    best = max(gaps, key=gaps.get)
    worst = min(gaps, key=gaps.get)
    ev.best, ev.worst = (best, gaps[best]), (worst, gaps[worst])
    if profile.objective_type == "index_tracker":
        ev.hit_margin_pp = profile.ocf_pct + t.performance_index.hit_rate_td_margin_over_ocf_pp
        ev.hit_rate = (sum(1 for v in values if abs(round(v, 2)) <= round(ev.hit_margin_pp, 2)), len(values))
        ev.test = t_test([v + profile.ocf_pct for v in values], "fee-adjusted yearly gap (gap + OCF)", stats)
    else:
        ev.hit_rate = (sum(1 for v in values if v >= 0), len(values))
        ev.test = t_test(values, "yearly excess return over the benchmark", stats)
    return ev
