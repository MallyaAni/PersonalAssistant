"""Relative valuation magnitude, a history reference, and the candidate's rules.

Research only; nothing here is read by the desk, the nightly or the
shadow ledger. Three things, each with the algebra that bounds it:

**Relative valuation magnitude.** For name i on session t, with side
s(i) and the point-in-time log price-to-sales x_i(t):

    d_i(t) = median_{j in s(i)} x_j(t) - x_i(t)    (distance below the side's median)
    m_i(t) = tanh( d_i(t) / c(t) ),  c(t) = median_{j eligible} |d_j(t)|

so m is in (-1, 1), zero at the side's median, and scale-free across
sessions. Under a whole-book repricing x_j -> x_j + log k for every j,
every median shifts by log k, every d_i is unchanged, c(t) is unchanged,
and m is unchanged: a contemporaneous peer-relative measure cannot see
market-wide expensiveness, by construction. It is labelled relative
valuation magnitude and is not an expected return.

**History reference.** For broader price sensitivity, one reference that
does not depend on the other names' prices today: the name's own log
multiple against the median of its own trailing window,

    h_i(t) = median_{u in [t-W+1, t]} x_i(u) - x_i(t),
    W = 756 sessions with at least 250 known,

using only that name's past prices and its as-of fundamentals. Under a
whole-book repricing on the last session h falls by log k for every
name, so it sees the level. Limitations: a multiple can re-rate for
good reasons (a business changing shape), so a low h is not a mispricing
by itself; a three-year window is short after a structural break and
undefined for a young listing; the window's fundamentals are the as-of
versions, so the reference is honest but changes when a restatement
becomes available; and it is, again, not an expected return.

**The candidate's selection.** The ordering score keeps every analyst's
signed conviction and replaces the value leg by the average of the rank
conviction and the magnitude:

    S_i(t) = sum_a w_a conv_a,i(t)   with   conv_value := (rank conviction + m) / 2

Every term is signed: strengthening any bearish opinion lowers S and can
only lower eligibility and weight (`test_attractiveness`). Candidacy:
hard gates pass, and either the grade rule admits the name (grade above
C) or S is at least the weakest name the grade rule admits that
session. When the grade rule admits nobody, nobody is admitted: the
score never bootstraps a book on its own. A name admitted by the score
alone is sized as a B (the veto and the vote count stay size limiters).
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import grading

WINDOW = 756
MIN_KNOWN = 250


# Distance below the side's median, over the book's typical distance, squashed.
def magnitude(
    distance: np.ndarray, eligible: np.ndarray, scale: np.ndarray | float | None = None
) -> np.ndarray:
    """Return tanh(distance / scale); scale defaults to the eligible median."""
    d = np.asarray(distance, dtype=float)
    two_d = d.ndim == 2
    rows = d if two_d else d[None, :]
    elig = np.asarray(eligible, dtype=bool)
    elig = elig if elig.ndim == 2 else np.broadcast_to(elig[None, :], rows.shape)
    if scale is None:
        masked = np.where(elig & np.isfinite(rows), np.abs(rows), np.nan)
        with np.errstate(all="ignore"):
            scale = np.nanmedian(masked, axis=1)
    scale = np.asarray(scale, dtype=float)
    scale = np.where(np.isfinite(scale) & (scale > 0), scale, 1.0)
    scale = scale if scale.ndim else np.full(rows.shape[0], float(scale))
    out = np.tanh(np.nan_to_num(rows, nan=0.0) / scale[:, None])
    return out if two_d else out[0]


# The name's own log multiple against its trailing median, a level a peer
# comparison cannot see.
def history_reference(
    log_multiple: np.ndarray, window: int = WINDOW, min_known: int = MIN_KNOWN
) -> np.ndarray:
    """Return (T, N) trailing-median log multiple minus today's, NaN when young."""
    x = np.asarray(log_multiple, dtype=float)
    out = np.full(x.shape, np.nan)
    for t in range(x.shape[0]):
        past = x[max(0, t - window + 1) : t + 1]
        known = np.isfinite(past).sum(axis=0)
        with np.errstate(all="ignore"):
            med = np.nanmedian(past, axis=0)
        out[t] = np.where(known >= min_known, med - x[t], np.nan)
    return out


# The same reference strictly trailing: the window ends the session before,
# so today's observation never enters its own median.
def trailing_reference(
    log_multiple: np.ndarray, window: int = WINDOW, min_known: int = MIN_KNOWN
) -> np.ndarray:
    """Return (T, N) median over [t-window, t-1] minus today's value, NaN when young."""
    x = np.asarray(log_multiple, dtype=float)
    out = np.full(x.shape, np.nan)
    for t in range(1, x.shape[0]):
        past = x[max(0, t - window) : t]
        known = np.isfinite(past).sum(axis=0)
        with np.errstate(all="ignore"):
            med = np.nanmedian(past, axis=0)
        out[t] = np.where(known >= min_known, med - x[t], np.nan)
    return out


# The candidate's ordering score: every analyst's signed conviction, the
# value leg the average of rank conviction and magnitude.
def candidate_scores(
    convictions: dict[str, np.ndarray],
    value_magnitude: np.ndarray,
    weights: dict[str, float] | None = None,
) -> np.ndarray:
    """Return (T, N) S with the value leg blended with the magnitude."""
    w = grading.analyst_weights(weights, tuple(convictions))
    total = np.zeros(next(iter(convictions.values())).shape)
    for name, conv in convictions.items():
        leg = np.nan_to_num(np.asarray(conv, dtype=float))
        if name == "value":
            leg = 0.5 * (leg + np.nan_to_num(np.asarray(value_magnitude, dtype=float)))
        total = total + w[name] * leg
    return total


# Who is a candidate: the grade rule's own admissions, plus any name whose
# score reaches the weakest admitted name's. Nobody when the rule admits nobody.
def admitted(scores: np.ndarray, grades: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ((T, N) admitted mask, (T,) the cut used per session)."""
    by_grade = np.asarray(grades) > 0
    s = np.asarray(scores, dtype=float)
    with np.errstate(all="ignore"):
        cut = np.nanmin(np.where(by_grade & np.isfinite(s), s, np.nan), axis=1)
    by_score = np.isfinite(cut)[:, None] & np.isfinite(s) & (s >= cut[:, None])
    return by_grade | by_score, cut


# Ordinal grades for sizing: a name admitted by the score alone is sized as B.
def sizing_grades(grades: np.ndarray, admitted_mask: np.ndarray) -> np.ndarray:
    """Return the ordinal grades the engine sizes with."""
    g = np.asarray(grades).copy()
    g[(g == 0) & admitted_mask] = grading.ORDINAL[grading.B]
    return g
