"""One fixed retrospective price study, explicitly ineligible for live adoption."""

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk import simulate, trend_brake
from backend.market import growth_pilot as gp
from backend.market import learned_policy as lp

HOLDOUT = np.datetime64("2026-08-03", "D")
POLICIES = (
    "momentum120",
    "learned_rank",
    "momentum120_learned_brake",
    "learned_rank_learned_brake",
    "momentum120_fixed_brake",
    "equal",
    "SPY",
    "QQQ",
)


@dataclass(frozen=True)
class ResearchData:
    """Reconstructed features, with no claim of historical desk membership."""

    panel: object
    inputs: lp.HistoricalInputs
    market: np.ndarray
    momentum: np.ndarray
    eligible: np.ndarray


# Derive scale-consistent features using only each observation's trailing rows.
def prepare(panel) -> ResearchData:
    base = gp.dataset(panel)
    rows, names = panel.close.shape
    opens = simulate.adjusted_open(panel)
    ratio = np.divide(
        panel.adj_close,
        panel.close,
        out=np.full_like(opens, np.nan),
        where=panel.close > 0,
    )
    span = np.full((rows, names), np.nan)
    for t in range(19, rows):
        hi = panel.high[t - 19 : t + 1] * ratio[t - 19 : t + 1]
        lo = panel.low[t - 19 : t + 1] * ratio[t - 19 : t + 1]
        valid = np.isfinite(hi).all(axis=0) & np.isfinite(lo).all(axis=0)
        valid &= np.isfinite(panel.adj_close[t]) & (panel.adj_close[t] > 0)
        span[t, valid] = (
            hi[:, valid].max(axis=0) - lo[:, valid].min(axis=0)
        ) / panel.adj_close[t, valid]
    stock = np.concatenate((base.features[:, :, :7], span[:, :, None]), axis=2)
    eligible = np.isfinite(stock).all(axis=2) & np.isfinite(opens) & (opens > 0)
    spy, qqq = panel.index("SPY"), panel.index("QQQ")
    eligible[:, [spy, qqq]] = False
    count = eligible.sum(axis=1)
    breadth = np.divide(
        ((stock[:, :, 1] > 0) & eligible).sum(axis=1),
        count,
        out=np.full(rows, np.nan),
        where=count > 0,
    )
    drawdown = np.full(rows, np.nan)
    for t in range(251, rows):
        window = panel.adj_close[t - 251 : t + 1, qqq]
        if np.isfinite(window).all() and np.all(window > 0):
            drawdown[t] = window[-1] / window.max() - 1
    market = np.column_stack(
        (
            stock[:, spy, 1],
            stock[:, spy, 4],
            stock[:, spy, 6],
            stock[:, qqq, 1],
            stock[:, qqq, 4],
            stock[:, qqq, 6],
            breadth,
            drawdown,
        )
    )
    features = np.concatenate(
        (stock, np.broadcast_to(market[:, None, :], (rows, names, market.shape[1]))),
        axis=2,
    )
    # These dates describe the reconstruction assumption. The manifest retains
    # the actual later vintage, and the evidence tag blocks live target sizing.
    observed = np.broadcast_to(panel.dates[:, None], opens.shape).copy()
    inputs = lp.HistoricalInputs(
        panel.dates,
        panel.tickers,
        opens,
        observed,
        features,
        np.broadcast_to(panel.dates[:, None, None], features.shape).copy(),
        eligible.astype(int),
        observed,
        evidence_basis="retrospective-price",
        rank_features=(True,) * 8 + (False,) * market.shape[1],
    )
    lp.validate(inputs)
    return ResearchData(panel, inputs, market, stock[:, :, 3], eligible)


# Freeze all label endpoints before the final holdout, including later refits.
def training_labels(values, dates, horizon, holdout=HOLDOUT):
    labels = np.array(values, dtype=float, copy=True)
    published = np.full(labels.shape, np.datetime64("NaT", "D"))
    for t in range(len(dates)):
        end = t + horizon
        if end >= len(dates) or dates[end] >= holdout:
            labels[t] = np.nan
        else:
            published[t] = dates[end]
    return labels, published


# Fit the registered models without training on any held-out outcome.
def fit(data: ResearchData):
    dates = data.panel.dates
    labels, published = training_labels(
        lp.relative_open_labels(data.inputs), dates, lp.RANKER_LABEL_END
    )
    rank = lp.walk_forward_ranker(
        data.inputs, observed_labels=labels, labels_recorded_on=published
    )
    qqq = data.panel.adj_close[:, data.panel.index("QQQ")]
    crashes, crash_when = training_labels(
        lp.future_drawdown_labels(qqq), dates, lp.BRAKE_HORIZON
    )
    brake = lp.walk_forward_brake(
        data.market,
        np.broadcast_to(dates[:, None], data.market.shape),
        dates,
        qqq,
        dates,
        observed_labels=crashes,
        labels_recorded_on=crash_when,
        evidence_basis="retrospective-price",
    )
    ready = np.isfinite(rank.values).sum(axis=1) >= 2
    ready &= np.isfinite(brake.values) & (dates >= np.datetime64("2016-01-04"))
    first = np.flatnonzero(ready)
    if not len(first):
        raise ValueError("no common fitted out-of-sample period")
    return rank, brake, int(first[0])


# Reject missing marks before the shared ledger can omit an unpriced holding.
def require_prices(prices, selected, context):
    if np.any(selected & (~np.isfinite(prices) | (prices <= 0))):
        raise ValueError(f"missing required price: {context}")


# Choose one fixed composition from the current observation's available names.
def composition(data, rank, policy, t):
    target = np.zeros(len(data.panel.tickers))
    if policy in ("SPY", "QQQ"):
        target[data.panel.index(policy)] = 1.0
    elif policy == "equal":
        count = data.eligible[t].sum()
        target[data.eligible[t]] = min(1 / max(count, 1), 0.1)
    else:
        score = (
            rank.values[t] if policy.startswith("learned_rank") else data.momentum[t]
        )
        if (
            policy.startswith("learned_rank")
            and not np.isfinite(score[data.eligible[t]]).any()
        ):
            raise ValueError("missing learned scores on a scheduled decision")
        target = gp.basket(score, data.eligible[t])
    return target


# Select the predeclared exposure rule without using account outcomes.
def exposure(panel, brake, first, policy):
    scale = np.ones(len(panel.dates))
    if policy.endswith("learned_brake"):
        if not np.isfinite(brake.values[first:]).all():
            raise ValueError("missing learned brake in the common scoring interval")
        scale = lp.brake_scale_path(brake.values)
    elif policy.endswith("fixed_brake"):
        scale = np.where(
            trend_brake.risk_off_path(panel.adj_close[:, panel.index("QQQ")]), 0.5, 1.0
        )
    return scale


# Execute fixed close-sized orders through the existing cash-funded ledger.
def replay(data, rank, brake, first, policy, cost_bps):
    if policy not in POLICIES or first >= len(data.panel.dates) - 1:
        raise ValueError("valid policy and executable interval required")
    panel = data.panel
    rows, names = panel.close.shape
    opens = simulate.adjusted_open(panel)
    scale = exposure(panel, brake, first, policy)
    book = simulate._Book(names, 1.0, cost_bps, panel, None, None)
    nav = np.full(rows - first, np.nan)
    turnover = np.zeros_like(nav)
    cash = np.ones_like(nav)
    nav[0] = 1.0
    base = np.zeros(names)
    retry = False
    decisions = []
    for t in range(first, rows - 1):
        require_prices(
            panel.adj_close[t], book.shares > 0, f"held close {panel.dates[t]}"
        )
        scheduled = t == first or (
            policy not in ("SPY", "QQQ") and (t - first) % 20 == 0
        )
        changed = t > first and scale[t] != scale[t - 1]
        followup = retry
        retry = False
        if scheduled:
            base = composition(data, rank, policy, t)
        order = None
        if scheduled or changed or followup:
            target = base * scale[t]
            require_prices(panel.adj_close[t], target > 0, f"decision {panel.dates[t]}")
            order = book.plan(target, panel.adj_close[t])
        selected = book.shares > 0
        if order is not None:
            selected |= np.abs(order - book.shares) > 1e-12
        require_prices(opens[t + 1], selected, f"open {panel.dates[t + 1]}")
        before_nav = book.equity(opens[t + 1])
        before_traded = book.traded
        if order is not None:
            had_sales = np.any(order < book.shares - 1e-12)
            book._fill(order, opens[t + 1], recycle_sells=False)
            retry = bool(had_sales and not followup)
            decisions.append(
                {
                    "decision": str(panel.dates[t]),
                    "execution": str(panel.dates[t + 1]),
                    "scheduled": bool(scheduled),
                    "brake_change": bool(changed),
                    "deferred": bool(followup),
                    "scale": float(scale[t]),
                }
            )
        require_prices(
            panel.adj_close[t + 1], book.shares > 0, f"held close {panel.dates[t + 1]}"
        )
        index = t + 1 - first
        nav[index] = book.equity(panel.adj_close[t + 1])
        turnover[index] = (book.traded - before_traded) / before_nav
        cash[index] = book.cash / nav[index]
        if book.cash < -1e-10 or not np.isfinite(nav[index]) or nav[index] <= 0:
            raise ValueError("invalid funded account state")
    return {
        "dates": panel.dates[first:],
        "nav": nav,
        "turnover": turnover,
        "cash": cash,
        "decisions": decisions,
    }


# Summarize the continuous funded account without resetting period holdings.
def metrics(path, start=None, stop=None):
    dates, nav = path["dates"], path["nav"]
    selected = np.ones(len(dates), dtype=bool)
    if start is not None:
        selected &= dates >= np.datetime64(start)
    if stop is not None:
        selected &= dates < np.datetime64(stop)
    indices = np.flatnonzero(selected)
    if len(indices) < 2:
        return {"available": False, "reason": "fewer than two observed sessions"}
    left, right = int(indices[0]), int(indices[-1])
    # Include the return into a segment's first close from the preceding close.
    anchor = max(0, left - 1)
    curve = nav[anchor : right + 1] / nav[anchor]
    daily = curve[1:] / curve[:-1] - 1
    years = len(daily) / 252
    volatility = float(daily.std() * np.sqrt(252))
    return {
        "available": True,
        "first": str(dates[left]),
        "last": str(dates[right]),
        "transitions": len(daily),
        "total_return": float(curve[-1] - 1),
        "cagr": float(curve[-1] ** (1 / years) - 1),
        "max_drawdown": float(np.min(curve / np.maximum.accumulate(curve) - 1)),
        "sharpe": float(daily.mean() * 252 / volatility) if volatility > 0 else None,
        "turnover_per_year": float(
            path["turnover"][anchor + 1 : right + 1].sum() / years
        ),
        "mean_cash": float(path["cash"][left : right + 1].mean()),
    }


# Compare complete trailing one-year account returns on identical dates.
def rolling_wins(path, control):
    if not np.array_equal(path["dates"], control["dates"]):
        raise ValueError("rolling comparison requires identical dates")
    if len(path["nav"]) <= 252:
        return {"windows": 0, "win_fraction": None}
    own = path["nav"][252:] / path["nav"][:-252]
    other = control["nav"][252:] / control["nav"][:-252]
    return {"windows": len(own), "win_fraction": float(np.mean(own > other))}
