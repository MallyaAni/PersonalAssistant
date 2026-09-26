"""A learned selection arm on the point-in-time book, for the scorecard.

The first point-in-time scorecard showed the rule's top-decile selection
with no measured edge over equal weight on the same names. This arm asks
whether a learned ordering does better, under exactly the conditions the
gate demands: names restricted each session to the dated membership, a
label the account can execute (next open to the open ten sessions later,
relative to SPY, `learned_policy.relative_open_labels`), monthly refits
that train only on labels published before the scoring month
(`learned_policy.walk_forward_ranker`), and the same allocator shape as the
capped equal-weight arm so the two differ only in *which* names.

Features are the eight causal price features of `growth_pilot.FEATURE_NAMES`
ranked cross-sectionally among that session's members, plus the desk's own
grade and conviction as two more columns, so the model can learn to reorder
within the analysts' view rather than start from nothing. Price features
are reconstructed from history rather than read from an archive, so the
inputs carry `evidence_basis="retrospective-price"` and this arm never
enters the desk's live target adapter; it is scored, not traded.
"""

from __future__ import annotations

import numpy as np

from backend.market import growth_pilot as gp
from backend.market import learned_policy as lp

TOP_K = 10
# Percent of equity per name; ten names at 10% is fully invested, the same
# cap the capped equal-weight arm uses, so selection is the only difference.
CAP = 0.10
GRADE_FEATURE = "desk_grade"
CONVICTION_FEATURE = "desk_conviction"


# Feature sets an arm can train on. "price" is the eight causal price
# features plus the desk's grade and summed conviction: the baseline every
# earlier learned attempt in this repository used, and the one the book has
# shown to carry roughly nothing. "desk" adds what the analysts actually
# measure, all of it point in time by construction: each analyst's own
# conviction, the numeric evidence behind it (revenue growth and
# acceleration, margins, capital intensity, release tone, valuation against
# the side, the expectations gap when the report carries it, moving-average
# distances and slopes, range position, trend states, reward-to-risk), the
# 31 causal multi-scale price and volume summaries of `alpha.alpha_features`
# (relative-to-market and relative-to-theme returns, volatility regimes,
# correlation and beta, ranges and gaps), and the regime analyst's session
# context repeated on every name (participation percentile, correlation z,
# novelty, basket drawdown and trend, exposure, tightening) so the model can
# learn interactions between a name's state and the market's. Every column
# is ranked cross-sectionally among that session's members before the fit;
# a context column that is constant across names ranks to 0.5 and acts only
# through interactions, which is the point.
FEATURE_SETS = ("price", "desk")
# Evidence keys that are labels, not numbers.
_TEXT_EVIDENCE = frozenset({"support_kind", "resistance_kind"})


# The (T, N, F) feature stack for one feature set, with its column names.
def feature_stack(report, feature_set: str = "price") -> tuple[np.ndarray, tuple[str, ...]]:
    """Return (features, names); NaN where a value is unknown."""
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"unknown feature set {feature_set!r}")
    panel = report.panel
    rows, names = panel.adj_close.shape
    columns: list[np.ndarray] = list(np.moveaxis(gp.dataset(panel).features, 2, 0))
    labels: list[str] = list(gp.FEATURE_NAMES)
    columns.append(np.asarray(report.graded.grades, dtype=float))
    labels.append(GRADE_FEATURE)
    columns.append(np.asarray(report.scores, dtype=float))
    labels.append(CONVICTION_FEATURE)
    if feature_set == "desk":
        from backend.market import alpha

        for analyst, opinion in sorted(report.opinions.items()):
            columns.append(np.asarray(opinion.conviction(), dtype=float))
            labels.append(f"{analyst}:conviction")
            for key, values in sorted(opinion.evidence.items()):
                if key in _TEXT_EVIDENCE or values is None:
                    continue
                array = np.asarray(values)
                if array.shape != (rows, names) or not np.issubdtype(array.dtype, np.number):
                    continue
                columns.append(array.astype(float))
                labels.append(f"{analyst}:{key}")
        stack = alpha.alpha_features(panel)
        for k, name in enumerate(alpha.ALPHA_NAMES):
            columns.append(stack[:, :, k])
            labels.append(f"alpha:{name}")
        context = np.array(
            [
                [
                    s.participation_percentile,
                    s.correlation_z,
                    s.novelty_z,
                    s.rotation_spread,
                    s.ai_drawdown,
                    s.ai_trend_60,
                    s.selection_confidence,
                    s.exposure,
                    float(s.tightening),
                ]
                for s in report.regime.states
            ],
            dtype=float,
        )
        for k, name in enumerate(
            (
                "participation_percentile", "correlation_z", "novelty_z",
                "rotation_spread", "ai_drawdown", "ai_trend_60",
                "selection_confidence", "exposure", "tightening",
            )
        ):
            columns.append(np.broadcast_to(context[:, k][:, None], (rows, names)).copy())
            labels.append(f"regime:{name}")
    return np.stack(columns, axis=2), tuple(labels)


# Assemble the walk-forward inputs from a (restricted) desk report and its
# membership mask. Membership is 1 inside the dated interval and 0 outside,
# never unknown, because the mask says exactly which names the book could
# have held; the benchmark column is never a member.
def historical_inputs(
    report, mask: np.ndarray, feature_set: str = "price"
) -> lp.HistoricalInputs:
    """Return HistoricalInputs for `learned_policy.walk_forward_ranker`."""
    panel = report.panel
    from backend.agents.trading.desk import simulate

    opens = simulate.adjusted_open(panel)
    stock, _names = feature_stack(report, feature_set)
    membership = np.where(mask, 1, 0).astype(int)
    membership[:, panel.index(panel.benchmark)] = 0
    observed = np.broadcast_to(panel.dates[:, None], opens.shape).copy()
    inputs = lp.HistoricalInputs(
        panel.dates,
        panel.tickers,
        opens,
        observed,
        stock,
        np.broadcast_to(panel.dates[:, None, None], stock.shape).copy(),
        membership,
        observed,
        spy=panel.benchmark,
        evidence_basis="retrospective-price",
        rank_features=(True,) * stock.shape[2],
    )
    lp.validate(inputs)
    return inputs


# Fit the ranker walk-forward and return its out-of-sample forecasts.
def forecasts(report, mask: np.ndarray, feature_set: str = "price") -> lp.Forecasts:
    """Return purged monthly walk-forward forecasts aligned to the report."""
    return lp.walk_forward_ranker(historical_inputs(report, mask, feature_set))


# The arm's allocator: on each decision session, the top `TOP_K` members by
# out-of-sample forecast at `CAP` each; cash before the first fit and for
# any slot without a qualifying name. Reads only the forecast and mask row
# for `t`, so the unsliced panel the simulator passes cannot leak.
def top_k_allocator(forecast: lp.Forecasts, mask: np.ndarray, top_k: int = TOP_K, cap: float = CAP):
    """Return a callable (report, panel, config, t) -> target weights."""

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.zeros(len(panel.tickers))
        if np.isnat(forecast.fit_session[t]) or forecast.last_training_label_end[t] >= t:
            return targets
        scores = np.where(mask[t], forecast.values[t], np.nan)
        scores[panel.index(panel.benchmark)] = np.nan
        scores = np.where(np.isfinite(panel.adj_close[t]), scores, np.nan)
        usable = np.flatnonzero(np.isfinite(scores))
        if not len(usable):
            return targets
        chosen = usable[np.argsort(-scores[usable], kind="stable")[:top_k]]
        targets[chosen] = cap
        return targets

    return allocate


_CACHE: dict[tuple[int, bytes, str], lp.Forecasts] = {}


# The scorecard's arm factory. The forecasts depend on the report and the
# mask only, not on the offset or the cost, so they are fitted once per
# (report, mask) and reused across the scorecard's 40 runs; the cache key
# is the report's identity and the mask's bytes.
def arm(report, mask: np.ndarray, feature_set: str = "price"):
    """Return the top-K allocator built from walk-forward forecasts."""
    key = (id(report), np.ascontiguousarray(mask).tobytes(), feature_set)
    if key not in _CACHE:
        _CACHE[key] = forecasts(report, mask, feature_set)
    return top_k_allocator(_CACHE[key], mask)
