""" Oversight scorecard and verdict (spec Section 6). Every rating is decided here, by fixed rules from
config/thresholds.yaml; AI agents only explain them """
from dataclasses import dataclass, field
from typing import get_args
from fund_performance.calc import annualise, hit_rate_target
from fund_performance.config import Thresholds
from fund_performance.mandate import SHORT_HISTORY_REASON, DecisionPath
from fund_performance.models import FundProfile, ObjectiveType, Peer
from fund_performance.precedence import PRICE_SERIES, ReportedFigures

GREEN, AMBER, RED, CHECK_DATA = "GREEN", "AMBER", "RED", "CHECK DATA"
MANUAL_CHECK = "MANUAL CHECK"       # a reviewer must check it; it does not block the verdict (owner decision)
_SEVERITY = {GREEN: 0, AMBER: 1, RED: 2}
NO_PEER = "no comparison available"
ADD_PEER = "Add peer"
MANUAL_MANDATE_REASON = "Style and holdings need a reviewer check"
SHORT_NAMES = {"Value for investors": "Value", "Fees": "Fees", "Mandate": "Mandate", "Performance": "Performance"}


@dataclass
class SubRating:
    name: str
    rating: str
    reason: str


@dataclass
class Pillar:
    name: str
    rating: str
    reason: str
    sub_ratings: list[SubRating] = field(default_factory=list)
    summary: str | None = None          # short label for the summary page, e.g. "Add peer"
    notes: list[str] = field(default_factory=list)


@dataclass
class Scorecard:
    pillars: dict[str, Pillar]
    verdict: str
    verdict_reason: str
    path: DecisionPath

    @property
    def manual_checks(self) -> list[Pillar]:
        """ Items the reviewer must tick in the approval section """
        return [p for p in self.pillars.values() if p.rating == MANUAL_CHECK]


def weakest(ratings: list[str]) -> str:
    """ The weaker rating wins; CHECK DATA wins over all, because the figure cannot be trusted """
    if CHECK_DATA in ratings:
        return CHECK_DATA
    return max(ratings, key=_SEVERITY.__getitem__)


def _band(value: float, green_max: float, amber_max: float) -> str:
    """ Compared at the stored 2 d.p. (spec 4), so a value on the limit counts as within it
    (13.9 + 0.16 - 13.9 is 0.16000000000000014 in floating point) """
    value, green_max, amber_max = round(value, 2), round(green_max, 2), round(amber_max, 2)
    return GREEN if value <= green_max else AMBER if value <= amber_max else RED


def _fmt(value: float, unit: str = "%") -> str:
    return f"{value:+.2f}{unit}" if unit == " pp" else f"{value:.2f}{unit}"


# --- 6.1 Mandate --------------------------------------------------------------------------------------------

def _tracking_stats(reported: ReportedFigures, n: int) -> tuple[float | None, float | None, str]:
    """ R2 and beta: calculated from an index series when available, otherwise the factsheet's """
    if f"relative.r2.{n}y" in reported.figures:
        return reported.value(f"relative.r2.{n}y"), reported.value(f"relative.beta.{n}y"), f"{n}y (calculated)"
    for basis in ("pnav", "unspecified", "nav"):
        r2, beta = reported.value(f"risk.{basis}.r2.3y"), reported.value(f"risk.{basis}.beta.3y")
        if r2 is not None or beta is not None:
            return r2, beta, "3y (factsheet)"
    return None, None, ""


def mandate_rating(reported: ReportedFigures, profile: FundProfile, t: Thresholds) -> Pillar:
    if profile.objective_type != "index_tracker":
        # Spec 6.1 has no measurable rule for active funds ("style and holdings consistent with policy"):
        # a reviewer checks it (owner decision; measurable rules in v2)
        return Pillar("Mandate", MANUAL_CHECK, MANUAL_MANDATE_REASON, summary="Manual check")
    m = t.mandate_index
    r2, beta, label = _tracking_stats(reported, profile.time_horizon_years)
    if r2 is None or beta is None:
        return Pillar("Mandate", CHECK_DATA, "R² and beta not available from the factsheet or an index price series")
    in_green = m.green_beta_range[0] <= beta <= m.green_beta_range[1]
    in_amber = m.amber_beta_range[0] <= beta <= m.amber_beta_range[1]
    if r2 >= m.green_min_r2 and in_green:
        rating = GREEN
    elif r2 >= m.amber_min_r2 and in_amber:
        rating = AMBER
    else:
        rating = RED
    return Pillar("Mandate", rating, f"R² {r2:.2f} and beta {beta:.2f}, {label}")


# --- 6.2 Performance ----------------------------------------------------------------------------------------

def _period_figures(reported: ReportedFigures, path: DecisionPath, series: str) -> tuple[float | None, float | None, str]:
    """ Fund and benchmark annualised returns over the main period, or since launch for a short history """
    if path.short_history:
        return (reported.value(f"{series}.since_launch.ann"), reported.value("index.since_launch.ann"), "since launch")
    n = path.main_period_years
    return reported.value(f"{series}.ann.{n}y"), reported.value(f"index.ann.{n}y"), f"{n}y"


def _index_tests(reported: ReportedFigures, profile: FundProfile, path: DecisionPath, t: Thresholds,
                 series: str, extra_tolerance_pp: float) -> tuple[list[SubRating], list[str]]:
    """ Index fund: tracking difference and tracking error rated separately (owner decision) """
    p = t.performance_index
    notes = []
    fund, index, period = _period_figures(reported, path, series)
    if fund is None or index is None:
        td_sub = SubRating("Tracking difference", CHECK_DATA, f"fund or index return not available ({period})")
    else:
        td = fund - index
        green = profile.ocf_pct + p.green_td_margin_over_ocf_pp + extra_tolerance_pp
        amber = profile.ocf_pct + p.amber_td_margin_over_ocf_pp + extra_tolerance_pp
        td_sub = SubRating("Tracking difference", _band(abs(td), green, amber),
                           f"TD {_fmt(td, ' pp')} a year ({period}, {series} vs index); Green within {green:.2f}, "
                           f"Amber within {amber:.2f}")
        if extra_tolerance_pp:
            notes.append(f"Tolerance widened by {extra_tolerance_pp:.2f} pp for the fund/index timing difference")

    n = path.main_period_years
    if f"relative.tracking_error.{n}y" in reported.figures:
        te, te_period = reported.value(f"relative.tracking_error.{n}y"), f"{n}y (calculated)"
    else:
        te = next((reported.value(f"risk.{b}.tracking_error.3y") for b in ("pnav", "unspecified", "nav")
                   if reported.value(f"risk.{b}.tracking_error.3y") is not None), None)
        te_period = "3y (factsheet)"
    if te is None:
        te_sub = SubRating("Tracking error", CHECK_DATA, "tracking error not available from the factsheet or an index series")
    else:
        te_sub = SubRating("Tracking error", _band(te, p.green_max_te_pct, p.amber_max_te_pct),
                           f"TE {te:.2f}%, {te_period}; Green up to {p.green_max_te_pct:.2f}, Amber up to {p.amber_max_te_pct:.2f}")
        if not te_period.startswith(period):
            notes.append(f"Periods differ: tracking difference is {period}, tracking error is {te_period}")
    return [td_sub, te_sub], notes


def _active_target(reported: ReportedFigures, path: DecisionPath, t: Thresholds, series: str) -> SubRating:
    a = t.performance_active_target
    fund, target, period = _period_figures(reported, path, series)
    if fund is None or target is None:
        return SubRating("Excess return vs target", CHECK_DATA, f"fund or target return not available ({period})")
    excess = fund - target
    fund_12m = {k.rsplit(".", 1)[1]: f.exact for k, f in reported.figures.items() if k.startswith(f"{series}.discrete_12m.")}
    target_12m = {k.rsplit(".", 1)[1]: f.exact for k, f in reported.figures.items() if k.startswith("index.discrete_12m.")}
    hits, windows = hit_rate_target(fund_12m, target_12m)
    if excess < a.red_below_excess_pct:
        rating = RED
    elif excess < a.green_min_excess_pct or hits < a.min_hit_rate:
        rating = AMBER
    else:
        rating = GREEN
    return SubRating("Excess return vs target", rating,
                     f"Annualised excess {_fmt(excess, ' pp')} ({period}); hit rate {hits} of {windows}")


def _objective_test(objective: str, reported: ReportedFigures, profile: FundProfile, path: DecisionPath,
                    t: Thresholds, series: str, extra_tolerance_pp: float) -> tuple[list[SubRating], list[str]]:
    if objective == "index_tracker":
        return _index_tests(reported, profile, path, t, series, extra_tolerance_pp)
    if objective == "active_target":
        return [_active_target(reported, path, t, series)], []
    if objective not in get_args(ObjectiveType):
        return [SubRating(f"Objective '{objective}'", CHECK_DATA, "not a known objective type, so it cannot be rated")], []
    needs = {"active_comparator": "peer-group quartile ranking", "active_constraint": "the constraints to check",
             "income_target": "yield and income target", "absolute_return": "the return target"}[objective]
    return [SubRating(objective, CHECK_DATA, f"needs {needs}; no input format agreed yet")], []


def performance_rating(reported: ReportedFigures, profile: FundProfile, path: DecisionPath, t: Thresholds,
                       series: str, extra_tolerance_pp: float = 0.0) -> Pillar:
    subs, notes = [], []
    for objective in path.objectives:
        s, n = _objective_test(objective, reported, profile, path, t, series, extra_tolerance_pp)
        subs += s
        notes += n
    rating = weakest([s.rating for s in subs])
    weak = [s for s in subs if s.rating == rating]
    reason = "; ".join(f"{s.name} {s.rating}: {s.reason}" for s in weak)
    if path.short_history and rating == GREEN:
        rating, reason = AMBER, f"{SHORT_HISTORY_REASON} ({reason})"
    elif path.short_history:
        notes.append(f"Short history: {SHORT_HISTORY_REASON}")
    if len(path.objectives) > 1:
        notes.append("Dual objective: Performance is the weaker of the two objectives")
    return Pillar("Performance", rating, reason, subs, notes=notes)


# --- 6.3 Value and 6.4 Fees -------------------------------------------------------------------------------------

def _peer_problem(peer: Peer | None, profile: FundProfile) -> tuple[str, str] | None:
    """ (rating, reason) when the peer cannot be used """
    if peer is None:
        return AMBER, NO_PEER
    if peer.currency.upper() != profile.currency.upper():
        return CHECK_DATA, f"peer is in {peer.currency}, the fund in {profile.currency}; not comparable"
    return None


def value_rating(reported: ReportedFigures, profile: FundProfile, t: Thresholds, peer: Peer | None) -> Pillar:
    problem = _peer_problem(peer, profile)
    if problem:
        return Pillar("Value for investors", *problem, summary=ADD_PEER if problem[1] == NO_PEER else None)
    n = profile.time_horizon_years
    peer_value = getattr(peer.returns, f"y{n}")
    fund = reported.value(f"{PRICE_SERIES}.ann.{n}y")
    if peer_value is None or fund is None:
        return Pillar("Value for investors", CHECK_DATA, f"{n}-year return missing for the fund or the peer")
    peer_ann = peer_value if peer.returns.basis == "annualised" else annualise(peer_value, n)
    gap = peer_ann - fund
    rating = _band(gap, t.value.green_max_peer_outperformance_pp, t.value.amber_max_peer_outperformance_pp)
    return Pillar("Value for investors", rating, f"{peer.name} returned {_fmt(gap, ' pp')} a year vs the fund ({n}y, "
                                                  "annualised, both net of fees)")


def fees_rating(profile: FundProfile, t: Thresholds, peer: Peer | None, performance: str) -> Pillar:
    problem = _peer_problem(peer, profile)
    if problem:
        return Pillar("Fees", *problem, summary=ADD_PEER if problem[1] == NO_PEER else None)
    gap = profile.ocf_pct - peer.ocf_pct
    notes = []
    if profile.objective_type == "index_tracker":
        f = t.fees_index
        rating = _band(gap, f.green_max_ocf_over_peer_pp, f.amber_max_ocf_over_peer_pp)
    elif gap <= 0 and performance != RED:
        rating = GREEN
    elif gap > 0 and performance == RED:
        rating = RED
    else:
        # Fee above the peer with Green performance (spec 6.4), and the two cases the spec leaves open
        # (fee above the peer with Amber performance; fee at or below the peer with Red performance): Amber
        rating = AMBER
    if profile.performance_fee:
        justification = (profile.performance_fee_justification or "").strip()
        if justification:
            notes.append(f"The fund charges a performance fee; justified in the profile: {justification}")
        else:
            notes.append("The fund charges a performance fee, not justified in the profile, so at least Amber")
            if rating == GREEN:
                rating = AMBER
    return Pillar("Fees", rating, f"OCF {profile.ocf_pct:.2f}% vs {peer.name} {peer.ocf_pct:.2f}% "
                                  f"(gap {_fmt(gap, ' pp')})", notes=notes)


# --- 6.5 Verdict -------------------------------------------------------------------------------------------------

def verdict(pillars: dict[str, Pillar]) -> tuple[str, str]:
    ratings = {name: p.rating for name, p in pillars.items()}
    checks = [n for n in ("Mandate", "Performance") if ratings[n] == CHECK_DATA]
    if checks:
        return "Pending data check", f"{' and '.join(checks)} need a data check before a verdict"
    # A manual check does not block the verdict; it is named in the reason and ticked by the reviewer
    manual = [n for n, r in ratings.items() if r == MANUAL_CHECK]
    also = f"; {', '.join(manual)} need a reviewer check" if manual else ""
    if RED in ratings.values():
        return "Review", "Red on " + ", ".join(n for n, r in ratings.items() if r == RED) + also
    data = [SHORT_NAMES[n] for n, r in ratings.items() if r == CHECK_DATA]
    amber = [n for n, r in ratings.items() if r == AMBER]
    if data:
        return f"Monitor (data check needed: {', '.join(data)})", \
               "Data check needed on " + ", ".join(data) + (f"; Amber on {', '.join(amber)}" if amber else "") + also
    if not amber:
        return "Retain", ("All four questions Green" if not manual else "No Amber or Red") + also
    if all(pillars[n].reason == NO_PEER for n in amber):
        return "Monitor until a peer is added", "Value and fees cannot be judged without a peer" + also
    return "Monitor", "Amber on " + ", ".join(amber) + also


def score(reported: ReportedFigures, profile: FundProfile, thresholds: Thresholds, path: DecisionPath,
          peer: Peer | None = None, comparison_series: str = PRICE_SERIES,
          extra_tolerance_pp: float = 0.0) -> Scorecard:
    pillars = {"Mandate": mandate_rating(reported, profile, thresholds),
               "Performance": performance_rating(reported, profile, path, thresholds, comparison_series,
                                                 extra_tolerance_pp)}
    if path.blocking:
        # Spec 5.1 step 5: a blocking data flag turns the affected items into CHECK DATA
        for name in ("Mandate", "Performance"):
            pillars[name] = Pillar(name, CHECK_DATA, "; ".join(f.message for f in path.blocking),
                                   pillars[name].sub_ratings, notes=pillars[name].notes)
    pillars["Value for investors"] = value_rating(reported, profile, thresholds, peer)
    pillars["Fees"] = fees_rating(profile, thresholds, peer, pillars["Performance"].rating)
    v, why = verdict(pillars)
    return Scorecard(pillars, v, why, path)
