"""A better volatility forecast, and whether it makes a better book.

    python -m backend.cli.market_volatility families
    python -m backend.cli.market_volatility fair
    python -m backend.cli.market_volatility book

The desk sizes on a trailing sixty-session window. These are the three
measurements, in the order they were made, that asked whether anything
learned could forecast volatility better and whether it would matter if
it did. All three are walk-forward with the twenty-session label purged at
the fold boundary and preprocessing fit on training rows only.

families
    Different families of learner, not different shapes of the same one.
    Every network tried on the desk before this was a feed-forward net or
    an attention variant over the same features - one family in several
    hats. The volatility target is where a fair comparison is possible,
    because the loss is defined and the baselines are strong:

      trailing-60             what the desk uses
      EWMA                    RiskMetrics
      HAR (levels)            Corsi's regression, unlogged
      log-HAR                 the same in logs
      ridge                   log-HAR with L2; rv1, rv5, rv22 and rv60 are
                              extremely collinear
      gradient boosting       LightGBM on the same features
      boosting, QLIKE-aware   the same trees trained on the loss the field
                              scores, not squared error
      random forest           bagged deep trees, the opposite trade
      k-nearest neighbours    no model: the most similar past states,
                              averaged
      MLP                     the network, on squared error
      best pair               the two best single models averaged in logs

    Scored by QLIKE and RMSE on log volatility over the book's names.

fair
    The network given the loss the winner is scored on. QLIKE punishes
    under-forecasting; a model fit by squared error on log volatility
    predicts the mean of the log, and exponentiating that sits below the
    mean of the level, so every log-target model inherits a downward bias
    on exactly the loss being scored. HAR in levels does not. The boosted
    trees in the first table went from +19.9% to +1.3% purely by swapping
    squared error for the QLIKE gradient, so the same MLP is trained three
    ways - log target on squared error, log target on QLIKE, level target
    on squared error - beside HAR in levels.

book
    Forecast quality and portfolio benefit are different questions, and
    the second decides. Sizing reads one function,
    `sizing.realised_volatility`, so the QLIKE network's out-of-sample
    forecast is put behind that name and the desk's own full-rule
    simulation is run against it with the same scores, grades, regime,
    costs and constraints. Only the volatility differs; where the forecast
    has no value the trailing window stands in, so coverage is not the
    difference.

Results
-------
Recorded in full above `sizing.realised_volatility`. Eleven models on
147,376 name-sessions, QLIKE:

  trailing-60, the desk's                0.4361
  HAR (levels)                           0.4055    -7.0%
  MLP, log target, QLIKE                 0.3686   -15.5%
  MLP, log target, MSE                   0.4486    +2.9%
  boosting, EWMA, ridge, forest, kNN     all worse than trailing-60

The network wins clearly, and only when trained on the loss it is scored
on. Behind the simulator, twenty folds, the forecast on 148,596
name-sessions:

  sizing volatility              annual    vol  Sharpe   maxDD    total
  trailing-60 (the desk's)       +31.8%  17.2%    1.85  -19.0%  +389.6%
  the QLIKE network's forecast   +31.3%  17.3%    1.82  -18.9%  +378.2%

The estimates do differ - the cross-sectional rank correlation with the
trailing window is 0.854 and the swap moves 8.4% of the book - but the
caps bind, the volatility target rescales whatever comes out, and the
scores decide what is held. The trailing window stays because it is
simpler and just as good here.

The first run of `book` recorded 1.85 to 1.85. It patched the forecast
onto the sizing module's attribute, and the sizing inside
`risk.desk_targets` reads the function by its imported name, so the
forecast never reached the book. The table above is the rerun with every
site patched; the conclusion did not change, the numbers did, and the
script lives here so the next check is a command rather than a memory.
"""

import argparse
from dataclasses import dataclass
from datetime import date

import numpy as np
import torch
from torch import nn

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import risk, simulate
from backend.market import sizing
from backend.market.store import MarketStore

HORIZON = 20
REFIT = 126
MIN_TRAIN = 500
MIN_FIT_ROWS = 2_000
SEEDS = 3
EPOCHS = 60
BATCH = 4_096
WINDOWS = (1, 5, 22, 60, 120)
ANNUAL = float(np.sqrt(252.0))
FLOOR = 1e-4
RIDGE_PENALTY = 10.0
KNN_REFERENCE = 20_000
KNN_K = 50
KNN_BLOCK = 2_048
BOOST_ROUNDS = 300
FOREST_ROUNDS = 200
BOOK_SINCE = date(2021, 6, 1)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

TRAILING = "trailing-60 (the desk's)"
FAMILIES = (
    "HAR (levels)",
    "log-HAR",
    "ridge",
    "gradient boosting",
    "boosting, QLIKE-aware",
    "random forest",
    "k-nearest neighbours",
    "MLP",
)
FAIR = (
    ("MLP, log target, MSE", "mse", False),
    ("MLP, log target, QLIKE", "qlike", False),
    ("MLP, level target, MSE", "mse", True),
)
BOOST_COMMON = {
    "verbosity": -1,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
}


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Forecast volatility; size on it.")
    parser.add_argument("command", choices=("families", "fair", "book"))
    parser.add_argument("--data-dir", default="data/market")
    return parser


@dataclass(frozen=True)
class Features:
    """The volatility state of every name-session, in logs, and its label."""

    stack: np.ndarray  # (T, N, 8): rv1 rv5 rv22 rv60 rv120, EWMA, market, cross
    y_log: np.ndarray  # (T, N) log of the next HORIZON sessions' realised vol
    rv60: np.ndarray  # (T, N) the trailing window the desk sizes on, in levels
    ewma: np.ndarray  # (T, N) RiskMetrics, in levels
    in_book: np.ndarray  # (N,) the book's names, benchmark excluded
    usable: np.ndarray  # (T, N) a full feature row, any name


# Annualised realised volatility over the trailing `window` sessions.
def _trailing(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    for t in range(window, values.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = np.sqrt(np.nanmean(values[t - window + 1 : t + 1] ** 2, axis=0))
    return out * ANNUAL


# Annualised realised volatility over the next `horizon` sessions: the label.
def _forward(values: np.ndarray, horizon: int) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    for t in range(values.shape[0] - horizon):
        with np.errstate(all="ignore"):
            out[t] = np.sqrt(np.nanmean(values[t + 1 : t + horizon + 1] ** 2, axis=0))
    return out * ANNUAL


# RiskMetrics: an exponentially weighted variance with the 0.94 decay.
def _ewma(clean: np.ndarray) -> np.ndarray:
    out = np.full(clean.shape, np.nan)
    var = np.nanvar(clean[:60], axis=0)
    for t in range(60, clean.shape[0]):
        today = np.where(np.isfinite(clean[t]), clean[t], 0.0)
        var = 0.94 * var + 0.06 * today**2
        out[t] = np.sqrt(var) * ANNUAL
    return out


# The feature block every model sees, from the desk's own panel.
def _features(report) -> Features:
    panel = report.panel
    rets = panel.log_returns()
    names = rets.shape[1]
    in_book = np.array([t in report.sides for t in panel.tickers])
    bench = panel.index(panel.benchmark)
    in_book[bench] = False
    clean = np.where(np.isfinite(rets), rets, np.nan)
    rv = {w: _trailing(clean, w) for w in WINDOWS}
    ewma = _ewma(clean)
    with np.errstate(all="ignore"):
        market = np.repeat(rv[22][:, bench : bench + 1], names, axis=1)
        book_median = np.nanmedian(
            np.where(in_book[None, :], rv[22], np.nan), axis=1, keepdims=True
        )
        cross = np.repeat(book_median, names, axis=1)
        columns = [rv[1], rv[5], rv[22], rv[60], rv[120], ewma, market, cross]
        stack = np.stack([np.log(np.maximum(c, FLOOR)) for c in columns], axis=-1)
        y_log = np.log(np.maximum(_forward(clean, HORIZON), FLOOR))
    usable = np.isfinite(stack).all(axis=-1)
    return Features(stack, y_log, rv[60], ewma, in_book, usable)


# The design rows and labels of the sessions in [start, stop) under a mask.
def _rows(feat: Features, mask: np.ndarray, start: int, stop: int):
    take = np.zeros_like(mask)
    take[start:stop] = mask[start:stop]
    t_idx, n_idx = np.nonzero(take)
    return feat.stack[t_idx, n_idx], feat.y_log[t_idx, n_idx], t_idx, n_idx


# Standardise on the fit rows only.
def _standardise(x_fit: np.ndarray, x_test: np.ndarray):
    mean, std = x_fit.mean(axis=0), x_fit.std(axis=0) + 1e-9
    return (x_fit - mean) / std, (x_test - mean) / std


# Least squares with an intercept; a penalty makes it ridge, with the
# intercept left unpenalised.
def _linear(zf, yf, zt, penalty: float = 0.0) -> np.ndarray:
    design_f = np.column_stack([np.ones(len(zf)), zf])
    design_t = np.column_stack([np.ones(len(zt)), zt])
    if penalty:
        reg = np.eye(design_f.shape[1]) * penalty
        reg[0, 0] = 0.0
        beta = np.linalg.solve(design_f.T @ design_f + reg, design_f.T @ yf)
    else:
        beta, *_ = np.linalg.lstsq(design_f, yf, rcond=None)
    return design_t @ beta


# Corsi's HAR fit in levels: inputs and label exponentiated, the prediction
# floored and returned in logs so every model is scored alike.
def _har_levels(x_fit, y_fit, x_test) -> np.ndarray:
    zf, zt = _standardise(np.exp(x_fit), np.exp(x_test))
    return np.log(np.maximum(_linear(zf, np.exp(y_fit), zt), FLOOR))


# QLIKE on log volatility as a gradient and hessian for LightGBM. With
# a = exp(2y) and p = exp(2f), QLIKE is a/p - log(a/p) - 1, whose
# derivative in f is 2(1 - a/p).
def _qlike_objective(pred, dataset):
    ratio = np.exp(2.0 * (dataset.get_label() - pred))
    return 2.0 * (1.0 - ratio), 4.0 * ratio


# Gradient-boosted trees, or a random forest when told to be one.
def _boosting(zf, yf, zt, objective, rounds: int = BOOST_ROUNDS, **overrides):
    import lightgbm as lgb

    params = {**BOOST_COMMON, "objective": objective, **overrides}
    booster = lgb.train(params, lgb.Dataset(zf, label=yf), num_boost_round=rounds)
    return booster.predict(zt)


# Nearest neighbours on a subsample, so the distance matrix fits in memory.
def _knn(zf, yf, zt) -> np.ndarray:
    size = min(KNN_REFERENCE, len(zf))
    take = np.random.default_rng(0).choice(len(zf), size=size, replace=False)
    ref, ref_y = zf[take], yf[take]
    guess = np.empty(len(zt))
    for start in range(0, len(zt), KNN_BLOCK):
        block = zt[start : start + KNN_BLOCK]
        d = ((block[:, None, :] - ref[None, :, :]) ** 2).sum(-1)
        nearest = np.argpartition(d, KNN_K, axis=1)[:, :KNN_K]
        guess[start : start + KNN_BLOCK] = ref_y[nearest].mean(axis=1)
    return guess


class _Net(nn.Module):
    """A small feed-forward net over the eight log features."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(width, 32),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        """Return one prediction per row."""
        return self.body(x).squeeze(-1)


# QLIKE on a log-volatility prediction: with a = exp(2y) and p = exp(2f),
# the loss is a/p - log(a/p) - 1.
def _qlike_loss(pred, truth):
    gap = truth - pred
    return (torch.exp(2.0 * gap) - 2.0 * gap - 1.0).mean()


# Train the net SEEDS times and average. `loss` is "mse" or "qlike";
# `level_target` fits the level the way HAR does. Returns log predictions.
def _mlp(zf, yf, zt, loss: str = "mse", level_target: bool = False) -> np.ndarray:
    xt = torch.tensor(zf, dtype=torch.float32, device=DEVICE)
    yt = torch.tensor(np.exp(yf) if level_target else yf, dtype=torch.float32)
    yt = yt.to(DEVICE)
    tt = torch.tensor(zt, dtype=torch.float32, device=DEVICE)
    acc = np.zeros(len(zt))
    for seed in range(SEEDS):
        torch.manual_seed(seed)
        model = _Net(zf.shape[1]).to(DEVICE)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        model.train()
        for _epoch in range(EPOCHS):
            order = torch.randperm(len(xt), device=DEVICE)
            for i in range(0, len(order), BATCH):
                b = order[i : i + BATCH]
                opt.zero_grad()
                out = model(xt[b])
                if loss == "qlike":
                    fit = _qlike_loss(out, yt[b])
                else:
                    fit = nn.functional.mse_loss(out, yt[b])
                fit.backward()
                opt.step()
        model.eval()
        with torch.no_grad():
            out = model(tt).cpu().numpy()
        acc += np.log(np.maximum(out, FLOOR)) if level_target else out
    return acc / SEEDS


# QLIKE between log predictions and log truth.
def _qlike(pred_log: np.ndarray, truth_log: np.ndarray) -> float:
    p, a = np.exp(2 * pred_log), np.exp(2 * truth_log)
    return float(np.mean(a / p - np.log(a / p) - 1.0))


# Root mean squared error in logs.
def _rmse(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - truth) ** 2)))


# Print each model on the cells every model scored, against the desk's window.
def _table(predictions: dict[str, np.ndarray], feat, mask, first_cut, names):
    common = mask.copy()
    common[:first_cut] = False
    for values in predictions.values():
        common &= np.isfinite(values)
    truth = feat.y_log[common]
    base = _qlike(predictions[TRAILING][common], truth)
    print(f"\nscored on {int(common.sum()):,} rows\n")
    print(f"{'model':26} {'QLIKE':>9} {'RMSE':>9} {'vs the desk':>13}")
    table = {}
    for name in names:
        pred = predictions[name][common]
        q = _qlike(pred, truth)
        table[name] = q
        against = (q / base - 1) * 100
        print(f"{name:26} {q:9.4f} {_rmse(pred, truth):9.4f} {against:+12.1f}%")
    return table, common


# Every family, walk-forward, on the book's labelled cells.
def _families(feat: Features, panel) -> None:
    rows, names = feat.y_log.shape
    mask = feat.usable & np.isfinite(feat.y_log) & feat.in_book[None, :]
    cuts = list(range(MIN_TRAIN, rows - HORIZON, REFIT))
    predictions = {name: np.full((rows, names), np.nan) for name in FAMILIES}
    print(f"{int(mask.sum()):,} labelled rows; {len(cuts)} folds\n")
    for number, cut in enumerate(cuts, start=1):
        x_fit, y_fit, _, _ = _rows(feat, mask, 0, cut - HORIZON)
        stop = min(cut + REFIT, rows - HORIZON)
        x_test, _, t_idx, n_idx = _rows(feat, mask, cut, stop)
        if len(x_fit) < MIN_FIT_ROWS or not len(x_test):
            continue
        zf, zt = _standardise(x_fit, x_test)
        fitted = {
            "log-HAR": _linear(zf, y_fit, zt),
            "ridge": _linear(zf, y_fit, zt, RIDGE_PENALTY),
            "HAR (levels)": _har_levels(x_fit, y_fit, x_test),
            "gradient boosting": _boosting(zf, y_fit, zt, "regression"),
            "boosting, QLIKE-aware": _boosting(zf, y_fit, zt, _qlike_objective),
            "random forest": _boosting(
                zf,
                y_fit,
                zt,
                "regression",
                rounds=FOREST_ROUNDS,
                boosting="rf",
                learning_rate=1.0,
                num_leaves=255,
                min_data_in_leaf=40,
            ),
            "k-nearest neighbours": _knn(zf, y_fit, zt),
            "MLP": _mlp(zf, y_fit, zt),
        }
        for name, values in fitted.items():
            predictions[name][t_idx, n_idx] = values
        print(f"  fold {number}/{len(cuts)} to {panel.dates[cut]}", flush=True)
    with np.errstate(all="ignore"):
        predictions[TRAILING] = np.log(np.maximum(feat.rv60, FLOOR))
        predictions["EWMA"] = np.log(np.maximum(feat.ewma, FLOOR))
    order = (TRAILING, "EWMA", *FAMILIES)
    table, common = _table(predictions, feat, mask, cuts[0], order)
    best = sorted(FAMILIES, key=lambda k: table[k])[:2]
    pair = 0.5 * (predictions[best[0]][common] + predictions[best[1]][common])
    truth = feat.y_log[common]
    q = _qlike(pair, truth)
    against = (q / table[TRAILING] - 1) * 100
    print(f"{'+'.join(best):26} {q:9.4f} {_rmse(pair, truth):9.4f} {against:+12.1f}%")


# The same network under three losses, beside HAR in levels.
def _fair(feat: Features, panel) -> None:
    rows, names = feat.y_log.shape
    mask = feat.usable & np.isfinite(feat.y_log) & feat.in_book[None, :]
    cuts = list(range(MIN_TRAIN, rows - HORIZON, REFIT))
    labels = ("HAR (levels)", *(name for name, _, _ in FAIR))
    predictions = {name: np.full((rows, names), np.nan) for name in labels}
    for number, cut in enumerate(cuts, start=1):
        x_fit, y_fit, _, _ = _rows(feat, mask, 0, cut - HORIZON)
        stop = min(cut + REFIT, rows - HORIZON)
        x_test, _, t_idx, n_idx = _rows(feat, mask, cut, stop)
        if len(x_fit) < MIN_FIT_ROWS or not len(x_test):
            continue
        zf, zt = _standardise(x_fit, x_test)
        predictions["HAR (levels)"][t_idx, n_idx] = _har_levels(x_fit, y_fit, x_test)
        for name, loss, level in FAIR:
            predictions[name][t_idx, n_idx] = _mlp(zf, y_fit, zt, loss, level)
        print(f"  fold {number}/{len(cuts)} to {panel.dates[cut]}", flush=True)
    with np.errstate(all="ignore"):
        predictions[TRAILING] = np.log(np.maximum(feat.rv60, FLOOR))
    _table(predictions, feat, mask, cuts[0], (TRAILING, *labels))


# Run the desk's full-rule simulation with `matrix` standing in for the
# realised volatility, or with the desk's own window when None.
#
# The stand-in has to reach every place the desk reads volatility. The
# sizing inside `risk.desk_targets` calls the function by its imported
# name, so patching the sizing module alone only reaches the simulator's
# tilt; the first run of this experiment did exactly that, which is why it
# is a CLI now and the number in the docstring is the rerun's.
def _simulated(report, matrix: np.ndarray | None, label: str) -> dict:
    real = sizing.realised_volatility

    def fixed(_panel, _lookback):
        return matrix

    if matrix is not None:
        sizing.realised_volatility = fixed
        risk.realised_volatility = fixed
    try:
        result = simulate.run(report, since=BOOK_SINCE, use_exits=False)
    finally:
        sizing.realised_volatility = real
        risk.realised_volatility = real
    s = result.stats()
    invested = result.invested[np.isfinite(result.invested)]
    print(
        f"{label:34} {s['annual']:+7.1%} {s['volatility']:6.1%} {s['sharpe']:7.2f} "
        f"{s['drawdown']:7.1%} {s['total']:+9.1%} {invested.mean():7.1%}"
    )
    return s


# The QLIKE network's forecast behind the desk's sizing, against the window.
def _book(feat: Features, panel, report) -> None:
    rows, names = feat.y_log.shape
    labelled = feat.usable & np.isfinite(feat.y_log)
    cuts = list(range(MIN_TRAIN, rows, REFIT))
    forecast = np.full((rows, names), np.nan)
    print(f"building the forecast over {len(cuts)} folds", flush=True)
    for number, cut in enumerate(cuts, start=1):
        x_fit, y_fit, _, _ = _rows(feat, labelled, 0, max(1, cut - HORIZON))
        x_test, _, t_idx, n_idx = _rows(feat, feat.usable, cut, min(cut + REFIT, rows))
        if len(x_fit) < MIN_FIT_ROWS or not len(x_test):
            continue
        zf, zt = _standardise(x_fit, x_test)
        forecast[t_idx, n_idx] = np.exp(_mlp(zf, y_fit, zt, "qlike"))
        print(f"  fold {number}/{len(cuts)}", flush=True)
    blended = np.where(np.isfinite(forecast), forecast, feat.rv60)
    covered = np.isfinite(forecast) & feat.in_book[None, :]
    print(f"\nforecast covers {int(covered.sum()):,} name-sessions")
    print(
        f"\n{'sizing volatility':34} {'annual':>8} {'vol':>7} {'Sharpe':>7} "
        f"{'maxDD':>8} {'total':>10} {'gross':>8}"
    )
    base = _simulated(report, None, TRAILING)
    net = _simulated(report, blended, "the QLIKE network's forecast")
    print(
        f"\nSharpe {base['sharpe']:.2f} -> {net['sharpe']:.2f}, "
        f"drawdown {base['drawdown']:.1%} -> {net['drawdown']:.1%}"
    )


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    report = trading_desk.run(MarketStore(args.data_dir))
    feat = _features(report)
    print(f"device {DEVICE}")
    if args.command == "families":
        _families(feat, report.panel)
    elif args.command == "fair":
        _fair(feat, report.panel)
    else:
        _book(feat, report.panel, report)


if __name__ == "__main__":
    main()
