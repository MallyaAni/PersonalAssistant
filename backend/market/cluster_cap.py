"""The peer-cluster exposure cap (R1): clusters, cap, capped allocator, verdict.

The plan (`docs/research/cluster-cap-plan-2026-10-02.md`, registered before
any code) fixes the method, the arms and the criteria; nothing here
restates them in a way the plan does not.

**The clusters.** At a session t the policy's target names (weight > 0) are
clustered on the residual-correlation matrix `peer_groups.py` uses: daily
log returns of the adjusted closes over t-59..t (closes t-60..t), each
regressed on the benchmark's with an intercept (`peer_groups.residuals`),
the residuals correlated pairwise. A name with a missing return in the
window or zero residual variance has no correlation and stays a cluster of
its own. Average linkage cut at rho*: the two clusters whose average
pairwise residual correlation is highest merge while that average is at
least rho*, ties to the pair first in order of their smallest columns.
Nothing after t's close is read and no label or ticker enters.

**The cap.** A cluster binds when its weight exceeds C (tolerance 1e-9).
In passes, every binding cluster not yet capped is scaled pro rata to C and
marked capped; the weight removed (plus whatever an earlier pass could not
place) goes to the names outside capped clusters pro rata to their current
weights, each held at the name cap (water-filled); a cluster pushed over C
binds in the next pass. What cannot be placed is cash. A book on which no
cluster binds is returned unchanged - the same array - so C = 100%
reproduces the policy to the bit (the null test).

**The verdict** pairs an arm's point-in-time scorecard payload with the
control's (`ew_graded_cap25`) at 25 bp: REPLACES when the median worst
drawdown is at least 3 points shallower on both windows with the median
CAGR no more than 1 point lower on both; RECORD: real but immaterial at 1
point with the drawdown shallower at 15 or more of 20 offsets on both;
else RECORD. The paired Newey-West t, the offsets above, the Sharpe and the
deflated Sharpe at the cumulative 488 are reported and decide nothing.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.market import candidate_stats
from backend.market import peer_groups as pg

PLAN = "docs/research/cluster-cap-plan-2026-10-02.md"
STUDY = "cluster_cap"
# The residual-correlation window, `peer_groups`' own.
CORR_SESSIONS = pg.CORR_SESSIONS
# The operator's per-name hold limit the redistribution respects (`/5`).
NAME_CAP = policy_v5.HOLD_CAP
# A cluster binds only above C by more than this, so C = 100% never binds
# on a book whose weights sum to one up to rounding.
TOLERANCE = 1e-9
# The criteria, fixed by the plan.
DRAWDOWN_POINTS = 0.03
IMMATERIAL_POINTS = 0.01
CAGR_GIVE_UP = 0.01
OFFSETS_SHALLOWER = 15
HAC_LAG = 20
DSR_GATE = 0.95
TRIALS = {"registered": 3, "cumulative": 488}
DECIDING = "2016-2023"
RECENT = "2024-2026"
WINDOWS = (DECIDING, RECENT)
COST_BPS = 25.0
RULE_LINE = "rule / point-in-time"
INDEXES = ("SPY", "QQQ")
REPLACES = "REPLACES"
IMMATERIAL = "RECORD: real but immaterial"
RECORD = "RECORD"


@dataclass(frozen=True)
class Spec:
    """One cluster-cap arm: the cap C on a cluster's weight and the linkage cut rho*."""

    cap: float
    rho: float

    # The file tag and payload name of this arm: "cc35_r60" for C 35% at
    # rho* 0.6; "cc100_r60" is the null.
    @property
    def tag(self) -> str:
        """Return the arm's tag."""
        return f"cc{round(self.cap * 100):02d}_r{round(self.rho * 100):02d}"

    # Whether the plan registered this arm.
    @property
    def registered(self) -> bool:
        """Return True for the three registered arms."""
        return any(
            math.isclose(self.cap, r.cap) and math.isclose(self.rho, r.rho)
            for r in REGISTERED
        )

    # The payload's record of the arm.
    def record(self) -> dict[str, Any]:
        """Return the arm as a JSON-ready dict."""
        return {
            "cap": self.cap,
            "rho": self.rho,
            "tag": self.tag,
            "registered": self.registered,
            "name_cap": NAME_CAP,
            "corr_sessions": CORR_SESSIONS,
            "linkage": "average",
            "residual": "to the benchmark with an intercept (peer_groups.residuals)",
            "unplaced": "cash",
        }


# The three registered arms (R1a-c) and the null, fixed by the plan.
REGISTERED = (Spec(0.35, 0.6), Spec(0.50, 0.6), Spec(0.35, 0.5))
NULL = Spec(1.0, 0.6)

assert TRIALS["registered"] == len(REGISTERED)


# Parse "35:0.6" (C in percent, rho*) into a Spec.
def parse_spec(text: str) -> Spec:
    """Return the Spec named by `C:RHO`, C in percent."""
    cap, _, rho = str(text).partition(":")
    spec = Spec(float(cap) / 100.0, float(rho))
    if not (0 < spec.cap <= 1.0) or not (-1.0 <= spec.rho <= 1.0):
        raise ValueError(f"cap must be in (0, 100] and rho in [-1, 1]: {text!r}")
    return spec


# --- the clusters ------------------------------------------------------------


# The residual correlations among `columns` at session t, exactly as
# `peer_groups.session_peers` computes them: log returns over t-59..t
# (closes t-60..t), residuals on the market column with an intercept, the
# residuals' pairwise correlation clipped to [-1, 1]. A column with a
# missing return in the window or zero residual variance gets a NaN row and
# column (diagonal included); everything is NaN when the window does not
# fit or the market is missing. Reads no close after t.
def residual_corr(
    adj_close: np.ndarray,
    market: int,
    columns: Sequence[int],
    t: int,
    window: int = CORR_SESSIONS,
) -> np.ndarray:
    """Return the (k, k) residual-correlation matrix of `columns` at t."""
    cols = np.asarray(columns, dtype=np.int64)
    k = len(cols)
    out = np.full((k, k), np.nan)
    lo = t - window + 1
    if lo < 1 or k == 0:
        return out
    closes = np.asarray(adj_close, dtype=float)[lo - 1 : t + 1]
    returns = pg.log_returns(closes)[1:]
    m = returns[:, market]
    if not np.isfinite(m).all():
        return out
    r = returns[:, cols]
    valid = np.flatnonzero(np.isfinite(r).all(axis=0))
    if not len(valid):
        return out
    e = pg.residuals(r[:, valid], m)
    norm = np.sqrt((e * e).sum(axis=0))
    keep = norm > 0
    valid = valid[keep]
    if not len(valid):
        return out
    z = e[:, keep] / norm[keep]
    out[np.ix_(valid, valid)] = np.clip(z.T @ z, -1.0, 1.0)
    return out


# Average-linkage clusters of k items from their (k, k) correlation matrix
# cut at `rho`: every item starts alone; the two clusters with the highest
# average pairwise correlation merge while it is at least `rho`; ties go to
# the pair first in order of their smallest indices. An item with a NaN
# correlation to another never merges with it (a NaN row stays alone).
# Returns the clusters as sorted index lists, ordered by smallest index.
def average_linkage(corr: np.ndarray, rho: float) -> list[list[int]]:
    """Return the clusters (lists of item indices) at the cut `rho`."""
    c = np.asarray(corr, dtype=float)
    k = c.shape[0]
    # Each cluster lives on the row of its smallest index; `total` holds the
    # sum of the pairwise correlations between two clusters (NaN when any
    # pair is missing, which then never merges), so the average linkage is
    # total / (size_a * size_b), updated by row addition on each merge.
    total = c.copy()
    size = np.ones(k)
    active = np.ones(k, dtype=bool)
    members = [[i] for i in range(k)]
    upper = np.triu(np.ones((k, k), dtype=bool), 1)
    while active.sum() > 1:
        with np.errstate(invalid="ignore"):
            avg = total / np.outer(size, size)
        live = upper & active[:, None] & active[None, :] & np.isfinite(avg)
        if not live.any():
            break
        scored = np.where(live, avg, -np.inf)
        # The first maximum in row-major order: the pair first in order of
        # their smallest indices.
        flat = int(np.argmax(scored))
        a, b = divmod(flat, k)
        if scored[a, b] < rho:
            break
        total[a, :] += total[b, :]
        total[:, a] += total[:, b]
        size[a] += size[b]
        active[b] = False
        members[a] = sorted(members[a] + members[b])
    return [members[i] for i in np.flatnonzero(active)]


# The average pairwise correlation inside one cluster (NaN for a singleton).
def cluster_mean_corr(corr: np.ndarray, members: Sequence[int]) -> float:
    """Return the mean of the off-diagonal correlations among `members`."""
    idx = list(members)
    if len(idx) < 2:
        return math.nan
    block = np.asarray(corr, dtype=float)[np.ix_(idx, idx)]
    off = block[~np.eye(len(idx), dtype=bool)]
    return float(off.mean())


# The clusters of the names a weight vector holds at session t, as panel
# columns: the target names (weight > 0), their residual correlations at
# t and average linkage at `rho`. Returns (clusters as lists of panel
# columns, the (k, k) matrix, the target columns in order).
def clusters_at(
    adj_close: np.ndarray, market: int, weights: np.ndarray, t: int, rho: float
) -> tuple[list[list[int]], np.ndarray, np.ndarray]:
    """Return (clusters of panel columns, residual correlations, target columns)."""
    targets = np.flatnonzero(np.asarray(weights, dtype=float) > 0)
    corr = residual_corr(adj_close, market, targets, t)
    local = average_linkage(corr, rho)
    return [[int(targets[i]) for i in g] for g in local], corr, targets


# --- the cap -----------------------------------------------------------------


# Give `amount` to the names in `free` pro rata to their current weights,
# none above `name_cap` (water-filling: a name that reaches the cap leaves
# and the rest is shared among the others). Returns the new weights and
# the amount that could not be placed.
def _distribute(
    w: np.ndarray, free: np.ndarray, amount: float, name_cap: float
) -> tuple[np.ndarray, float]:
    """Return (weights after the distribution, the amount left over)."""
    w = w.copy()
    open_ = free & (w > 0) & (w < name_cap - TOLERANCE)
    while amount > TOLERANCE and open_.any():
        base = w[open_]
        share = amount * base / base.sum()
        room = name_cap - base
        give = np.minimum(share, room)
        w[open_] = base + give
        amount -= float(give.sum())
        open_ = open_ & (w < name_cap - TOLERANCE)
        if not (share > room).any():
            break
    return w, max(amount, 0.0)


# The cap on one weight vector given its clusters (lists of columns): the
# plan's passes - scale every binding uncapped cluster to `cap`, give the
# removed weight to the names outside capped clusters under the name cap,
# repeat until no uncapped cluster binds; the rest is cash. Returns the
# capped weights (the input array itself when nothing binds) and a record
# of what the cap did.
def cap_weights(
    weights: np.ndarray,
    clusters: Sequence[Sequence[int]],
    cap: float,
    name_cap: float = NAME_CAP,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (capped weights, {binds, capped, moved, cash, passes})."""
    groups = [np.asarray(g, dtype=np.int64) for g in clusters]
    totals = [float(np.asarray(weights, dtype=float)[g].sum()) for g in groups]
    if not any(total > cap + TOLERANCE for total in totals):
        return weights, {
            "binds": False,
            "capped": [],
            "moved": 0.0,
            "cash": 0.0,
            "passes": 0,
        }
    w = np.asarray(weights, dtype=float).copy()
    capped = np.zeros(len(groups), dtype=bool)
    in_capped = np.zeros(len(w), dtype=bool)
    carry, moved, passes = 0.0, 0.0, 0
    while True:
        binding = [
            i
            for i, g in enumerate(groups)
            if not capped[i] and float(w[g].sum()) > cap + TOLERANCE
        ]
        if not binding:
            break
        passes += 1
        for i in binding:
            g = groups[i]
            total = float(w[g].sum())
            w[g] = w[g] * (cap / total)
            removed = total - float(w[g].sum())
            carry += removed
            moved += removed
            capped[i] = True
            in_capped[g] = True
        w, carry = _distribute(w, ~in_capped, carry, name_cap)
    return w, {
        "binds": True,
        "capped": [[int(c) for c in groups[i]] for i in np.flatnonzero(capped)],
        "moved": moved,
        "cash": carry,
        "passes": passes,
    }


# One session's capped targets from the policy's: the clusters of its
# target names at t and the cap. Returns (capped weights, clusters, the
# residual-correlation matrix, the target columns, the cap's record).
def cap_session(
    adj_close: np.ndarray,
    market: int,
    weights: np.ndarray,
    t: int,
    spec: Spec,
    name_cap: float = NAME_CAP,
) -> tuple[np.ndarray, list[list[int]], np.ndarray, np.ndarray, dict[str, Any]]:
    """Return (capped weights, clusters, corr, target columns, record)."""
    clusters, corr, targets = clusters_at(adj_close, market, weights, t, spec.rho)
    capped, record = cap_weights(weights, clusters, spec.cap, name_cap)
    return capped, clusters, corr, targets, record


# An allocator factory (`market_pit_scorecard.ARMS` style) whose
# allocator is the base factory's, capped: on every session it is asked,
# the base targets are clustered at t (reading closes through t only) and
# capped. When no cluster binds the base allocator's own array is
# returned, so C = 100% is the base arm to the bit.
def capped_arm(base: Callable, spec: Spec, name_cap: float = NAME_CAP) -> Callable:
    """Return `(report, mask) -> allocator` with the cluster cap applied."""

    # The factory: the base allocator for this report and mask, wrapped.
    def factory(report, mask):
        inner = base(report, mask)

        # One session's targets: the base's, clustered and capped at t.
        def allocate(report, panel, config, t: int) -> np.ndarray:
            weights = inner(report, panel, config, t)
            if not (np.asarray(weights) > 0).any():
                return weights
            market = panel.index(panel.benchmark)
            capped, *_ = cap_session(
                panel.adj_close, market, weights, t, spec, name_cap
            )
            return capped

        return allocate

    return factory


# How often the cap binds on the point-in-time book: for every session of
# the restricted report, the base targets and the capped targets (what the
# arm would set if asked that day), per window the share of sessions with
# a target book on which a cluster binds, the clusters capped, the weight
# moved, the cash left, the largest cluster before and after, the names in
# clusters of two or more; and each binding session's names, clusters,
# weights before and after and cluster correlations, for the check.
def binding_record(
    restricted,
    mask: np.ndarray,
    base: Callable,
    spec: Spec,
    windows: Mapping[str, tuple],
    in_window: Callable,
    name_cap: float = NAME_CAP,
) -> dict[str, Any]:
    """Return {"windows": {name: stats}, "sessions": [binding sessions]}."""
    panel = restricted.panel
    allocate = base(restricted, mask)
    market = panel.index(panel.benchmark)
    tickers = [str(x) for x in panel.tickers]
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    length = len(dates)
    held = np.zeros(length, dtype=bool)
    binds = np.zeros(length, dtype=bool)
    n_capped = np.zeros(length)
    moved = np.zeros(length)
    cash = np.zeros(length)
    largest_before = np.zeros(length)
    largest_after = np.zeros(length)
    clustered_names = np.zeros(length)
    sessions: list[dict[str, Any]] = []
    for t in range(length):
        w = np.asarray(allocate(restricted, panel, None, t), dtype=float)
        if not (w > 0).any():
            continue
        held[t] = True
        capped, clusters, corr, targets, record = cap_session(
            panel.adj_close, market, w, t, spec, name_cap
        )
        sizes = [float(w[g].sum()) for g in clusters]
        largest_before[t] = max(sizes)
        largest_after[t] = max(float(np.asarray(capped)[g].sum()) for g in clusters)
        clustered_names[t] = sum(len(g) for g in clusters if len(g) > 1)
        if not record["binds"]:
            continue
        binds[t] = True
        n_capped[t] = len(record["capped"])
        moved[t] = record["moved"]
        cash[t] = record["cash"]
        position = {int(c): i for i, c in enumerate(targets)}
        sessions.append(
            {
                "date": str(dates[t]),
                "names": [tickers[c] for c in targets],
                "before": [float(w[c]) for c in targets],
                "after": [float(capped[c]) for c in targets],
                "clusters": [[tickers[c] for c in g] for g in clusters],
                "cluster_corr": [
                    cluster_mean_corr(corr, [position[c] for c in g]) for g in clusters
                ],
                "capped": [[tickers[c] for c in g] for g in record["capped"]],
                "moved": record["moved"],
                "cash": record["cash"],
                "passes": record["passes"],
            }
        )
    out: dict[str, Any] = {"spec": spec.record(), "windows": {}, "sessions": sessions}
    for name, (start, end) in windows.items():
        keep = in_window(dates, start, end) & held
        hit = keep & binds
        n = int(keep.sum())
        out["windows"][name] = {
            "sessions_with_targets": n,
            "sessions_binding": int(hit.sum()),
            "share_binding": float(hit.sum() / n) if n else math.nan,
            "mean_clusters_capped_when_binding": _mean(n_capped[hit]),
            "mean_weight_moved_when_binding": _mean(moved[hit]),
            "mean_cash_when_binding": _mean(cash[hit]),
            "max_cash": float(cash[keep].max()) if n else math.nan,
            "mean_cash_all_sessions": _mean(cash[keep]),
            "median_largest_cluster_before": _median(largest_before[keep]),
            "median_largest_cluster_after": _median(largest_after[keep]),
            "max_largest_cluster_before": float(largest_before[keep].max())
            if n
            else math.nan,
            "median_names_in_clusters": _median(clustered_names[keep]),
        }
    return out


# Mean of an array, NaN when empty.
def _mean(x: np.ndarray) -> float:
    """Return the mean or NaN."""
    return float(np.mean(x)) if len(x) else math.nan


# Median of an array, NaN when empty.
def _median(x: np.ndarray) -> float:
    """Return the median or NaN."""
    return float(np.median(x)) if len(x) else math.nan


# The clusters and every arm's capped targets for one weight vector at the
# panel's session t, by ticker: what the 09-30 report prints.
def session_report(
    tickers: Sequence[str],
    adj_close: np.ndarray,
    market: int,
    weights: np.ndarray,
    t: int,
    specs: Sequence[Spec],
    name_cap: float = NAME_CAP,
) -> dict[str, Any]:
    """Return {"targets", "by_rho": {rho: clusters}, "arms": {tag: weights}}."""
    names = [str(x) for x in tickers]
    w = np.asarray(weights, dtype=float)
    out: dict[str, Any] = {
        "targets": {names[c]: float(w[c]) for c in np.flatnonzero(w > 0)},
        "by_rho": {},
        "arms": {},
    }
    for rho in sorted({s.rho for s in specs}, reverse=True):
        clusters, corr, targets = clusters_at(adj_close, market, w, t, rho)
        position = {int(c): i for i, c in enumerate(targets)}
        out["by_rho"][f"{rho:g}"] = [
            {
                "names": [names[c] for c in g],
                "weight": float(w[g].sum()),
                "mean_corr": cluster_mean_corr(corr, [position[c] for c in g]),
            }
            for g in clusters
        ]
        if rho == max(s.rho for s in specs):
            out["corr"] = {
                "names": [names[c] for c in targets],
                "matrix": [[float(v) for v in row] for row in corr],
            }
    for spec in specs:
        capped, _, _, _, record = cap_session(adj_close, market, w, t, spec, name_cap)
        out["arms"][spec.tag] = {
            "weights": {names[c]: float(capped[c]) for c in np.flatnonzero(w > 0)},
            "capped": [[names[c] for c in g] for g in record["capped"]],
            "cash": float(record["cash"]),
            "binds": record["binds"],
        }
    return out


# --- the verdict against the control -----------------------------------------


# A payload number as a float: None (a NaN written to JSON) reads NaN.
def _f(value: Any) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# A signed number for a verdict line, "n/a" when missing.
def _signed(x: Any, digits: int = 2) -> str:
    """Return `x` with its sign, "n/a" when missing."""
    v = _f(x)
    return f"{v:+.{digits}f}" if math.isfinite(v) else "n/a"


# A line's row of a payload at the study's cost on a window.
def _row(
    payload: Mapping[str, Any],
    window: str,
    line: str = RULE_LINE,
    cost: float = COST_BPS,
) -> Mapping[str, Any]:
    """Return the matching row; KeyError when the payload has none."""
    for r in payload["rows"]:
        if r["line"] == line and r["window"] == window and float(r["cost_bps"]) == cost:
            return r
    raise KeyError(f"no {line!r} row for {window!r} at {cost:g} bp")


# The median-offset daily returns of the rule line on a window, paired
# session by session between two payloads (dates matched, both finite).
def paired_daily(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    window: str,
    cost: float = COST_BPS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (candidate daily, control daily) on the sessions both price."""
    start, end = candidate["windows"][window]
    key = f"{cost:g}"
    a, b = candidate["curves"][key], control["curves"][key]
    theirs = dict(zip(b["dates"], b["lines"][RULE_LINE], strict=True))
    xs, ys = [], []
    for day, value in zip(a["dates"], a["lines"][RULE_LINE], strict=True):
        if (start is not None and day < start) or (end is not None and day >= end):
            continue
        other = theirs.get(day)
        if value is None or other is None:
            continue
        if not (math.isfinite(value) and math.isfinite(other)):
            continue
        xs.append(value)
        ys.append(other)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


# The paired difference (arm minus control) on a window: length, mean in
# bp a session, Newey-West t at lag 20, the moments the deflated Sharpe needs.
def paired(
    candidate: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, Any]:
    """Return the statistics of the arm's rule line minus the control's."""
    a, b = paired_daily(candidate, control, window)
    diff = a - b
    mom = candidate_stats.moments(diff)
    return {
        "window": window,
        "sessions": int(len(diff)),
        "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
        "hac_t": candidate_stats.hac_t(diff, HAC_LAG) if len(diff) > 2 else math.nan,
        "sharpe": mom.sharpe,
        "skew": mom.skew,
        "kurtosis": mom.kurtosis,
        "length": mom.length,
    }


# The window's reading of an arm against the control from the rows: median
# worst drawdown, CAGR and Sharpe of both, the differences, and per offset
# how often the arm's CAGR is above and its drawdown shallower.
def window_reading(
    candidate: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, Any]:
    """Return the window's numbers for the verdict."""
    a, b = _row(candidate, window), _row(control, window)
    f = _f
    own_c = np.asarray([_f(x) for x in a["cagrs"]], dtype=float)
    their_c = np.asarray([_f(x) for x in b["cagrs"]], dtype=float)
    own_d = np.asarray([_f(x) for x in a.get("drawdowns", [])], dtype=float)
    their_d = np.asarray([_f(x) for x in b.get("drawdowns", [])], dtype=float)
    same_c = len(own_c) == len(their_c)
    same_d = len(own_d) == len(their_d) and len(own_d) > 0
    return {
        "drawdown": f(a["median_drawdown"]),
        "drawdown_control": f(b["median_drawdown"]),
        # Positive when the arm's worst drawdown is shallower.
        "drawdown_gain": f(a["median_drawdown"]) - f(b["median_drawdown"]),
        "cagr": f(a["median_cagr"]),
        "cagr_control": f(b["median_cagr"]),
        "cagr_difference": f(a["median_cagr"]) - f(b["median_cagr"]),
        "sharpe": f(a["median_sharpe"]),
        "sharpe_control": f(b["median_sharpe"]),
        "sharpe_difference": f(a["median_sharpe"]) - f(b["median_sharpe"]),
        "offsets": int(len(their_c)),
        "offsets_above": int(np.nansum(own_c > their_c)) if same_c else 0,
        "offsets_shallower": int(np.nansum(own_d > their_d)) if same_d else 0,
    }


# SPY's and QQQ's median CAGR, worst drawdown and Sharpe on each window
# from the control's rows, printed beside the verdict.
def indexes(control: Mapping[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    """Return {symbol: {window: {cagr, drawdown, sharpe}}}."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol in INDEXES:
        out[symbol] = {}
        for window in WINDOWS:
            try:
                r = _row(control, window, symbol)
            except KeyError:
                continue
            out[symbol][window] = {
                "cagr": _f(r["median_cagr"]),
                "drawdown": _f(r["median_drawdown"]),
                "sharpe": _f(r["median_sharpe"]),
            }
    return out


# The plan's label from the per-window readings.
def label(readings: Mapping[str, Mapping[str, Any]]) -> str:
    """Return REPLACES, RECORD: real but immaterial, or RECORD."""

    # Whether every window improves the drawdown by `points` within the CAGR band.
    def trade(points: float) -> bool:
        return all(
            math.isfinite(r["drawdown_gain"])
            and r["drawdown_gain"] >= points
            and math.isfinite(r["cagr_difference"])
            and r["cagr_difference"] >= -CAGR_GIVE_UP
            for r in readings.values()
        )

    if trade(DRAWDOWN_POINTS):
        return REPLACES
    if trade(IMMATERIAL_POINTS) and all(
        r["offsets_shallower"] >= OFFSETS_SHALLOWER for r in readings.values()
    ):
        return IMMATERIAL
    return RECORD


# One arm's verdict from its payload and the control's. `trial_variance`
# is the across-arm variance of the registered arms' paired Sharpes (NaN
# leaves the deflated Sharpe unjudged; it decides nothing either way).
def verdict(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    trial_variance: float = math.nan,
) -> dict[str, Any]:
    """Return the arm's verdict record."""
    spec = candidate.get("cluster_cap", {}).get("spec", {})
    readings = {w: window_reading(candidate, control, w) for w in WINDOWS}
    pairs = {w: paired(candidate, control, w) for w in WINDOWS}
    deciding = pairs[DECIDING]
    dsr = math.nan
    if math.isfinite(trial_variance) and math.isfinite(deciding["sharpe"]):
        dsr = candidate_stats.deflated_sharpe(
            deciding["sharpe"],
            deciding["length"],
            deciding["skew"],
            deciding["kurtosis"],
            TRIALS["cumulative"],
            trial_variance,
        )
    binding = candidate.get("cluster_cap", {}).get("binding", {}).get("windows", {})
    reading = {
        "label": label(readings),
        "windows": readings,
        "paired": pairs,
        "dsr": dsr,
        "trials": TRIALS["cumulative"],
        "trial_variance": trial_variance,
        "cost_bps": COST_BPS,
        "cluster_cap": dict(spec),
        "binding": {w: binding.get(w) for w in WINDOWS},
        "candidate_arm": candidate.get("arm"),
        "control_arm": control.get("arm"),
        "criteria": {
            "drawdown_points": DRAWDOWN_POINTS,
            "immaterial_points": IMMATERIAL_POINTS,
            "cagr_give_up": CAGR_GIVE_UP,
            "offsets_shallower": OFFSETS_SHALLOWER,
            "hac_lag": HAC_LAG,
            "dsr_gate_reported": DSR_GATE,
        },
    }
    reading["lines"] = lines(reading)
    return reading


# An arm's verdict as lines: the paired evidence, how often the cap
# binds, each window against the control, the label.
def lines(reading: Mapping[str, Any]) -> list[str]:
    """Return the verdict as lines."""
    signed = _signed
    spec = reading.get("cluster_cap", {})
    cap, rho = _f(spec.get("cap")), _f(spec.get("rho"))
    head = f"C = {cap * 100:.0f}% at rho* = {rho:g} ({spec.get('tag', '?')})"
    d, r = reading["paired"][DECIDING], reading["paired"][RECENT]
    out = [
        f"{head}: paired {DECIDING} {signed(d['mean_daily_bp'], 1)} bp/session "
        f"(t {signed(d['hac_t'])}) over {d['sessions']} sessions; {RECENT} "
        f"{signed(r['mean_daily_bp'], 1)} bp/session (t {signed(r['hac_t'])}); "
        f"deflated Sharpe {signed(reading['dsr'])} at {reading['trials']}"
    ]
    for window, v in reading["windows"].items():
        b = (reading.get("binding") or {}).get(window) or {}
        share = _f(b.get("share_binding"))
        binds = f"{share * 100:.0f}%" if math.isfinite(share) else "n/a"
        out.append(
            f"  {window}: median worst drawdown {v['drawdown'] * 100:+.1f}% against "
            f"{v['drawdown_control'] * 100:+.1f}% "
            f"({signed(v['drawdown_gain'] * 100, 1)} points), shallower at "
            f"{v['offsets_shallower']} of {v['offsets']} offsets; CAGR "
            f"{v['cagr'] * 100:+.1f}% against {v['cagr_control'] * 100:+.1f}% "
            f"({signed(v['cagr_difference'] * 100, 1)} points), above at "
            f"{v['offsets_above']} of {v['offsets']}; Sharpe {v['sharpe']:.2f} "
            f"against {v['sharpe_control']:.2f}; the cap binds on {binds} of sessions"
        )
    if reading["label"] == REPLACES:
        out.append("  REPLACES (drawdown >= 3 points shallower, CAGR within -1, both)")
    elif reading["label"] == IMMATERIAL:
        out.append(
            "  RECORD: real but immaterial (>= 1 point on both, CAGR within -1, "
            f"shallower at >= {OFFSETS_SHALLOWER} offsets; not 3 points on both)"
        )
    else:
        out.append("  RECORD")
    return out


# The variance of the deciding window's paired Sharpes across the
# registered arms' payloads (NaN with fewer than two finite).
def trial_variance(
    candidates: Mapping[str, Mapping[str, Any]], control: Mapping[str, Any]
) -> float:
    """Return the across-arm variance of the deciding window's paired Sharpe."""
    sharpes = [
        paired(c, control, DECIDING)["sharpe"]
        for c in candidates.values()
        if c.get("cluster_cap", {}).get("spec", {}).get("registered")
    ]
    sharpes = [s for s in sharpes if math.isfinite(s)]
    if len(sharpes) < 2:
        return math.nan
    return float(np.var(sharpes, ddof=1))
