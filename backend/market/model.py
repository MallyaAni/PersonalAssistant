"""The learned ranker, trained the only way its number can be trusted.

A cross-sectional model: on each session it scores every name, and the
loss is the negative correlation between its scores and the names'
*residual* forward returns within that session. It is never asked to
predict a price, only to order the cross-section, because ordering is what
a long-short book is made of and because a level forecast for a single
name has no information at this horizon (the baseline report measured
that).

Inputs per (session, name): the last `window_size` sessions of the eight
raw channels from `windows.channel_matrices`, plus the baselines' percentile
ranks on that session, so the model starts from what the classic signals
know and has to find what they do not. Channels are z-scored with
statistics fit on the training sessions of the fold only.

Training is walk-forward through `harness.walk_forward_folds`: each fold
fits on its training range (whose last label ends before the test range
starts), keeps the tail of that range as validation for early stopping, and
scores its test range. The scores from every fold are assembled into one
(sessions x tickers) matrix that is NaN outside the test ranges and handed
to `harness.evaluate_scores` — the same function, the same residual label,
the same cost accounting the baselines were measured with. A model that
does not beat the baseline rows there does not exist.

Two encoders: a plain MLP over the flattened window, and a GRU over the
sequence. The MLP is the honest first model; the GRU is the first thing to
try when the MLP has found something. torch is imported here and nowhere
else in the package, so the store, the panel and the baselines never need it.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from backend.market import baselines
from backend.market.harness import walk_forward_folds
from backend.market.panel import Panel
from backend.market.windows import CHANNELS, channel_matrices

# The baselines whose percentile ranks are fed alongside the window.
BASELINE_FEATURES: tuple[str, ...] = (
    "momentum_12_1",
    "relative_strength_20",
    "theme_momentum_20",
    "theme_relative_strength_20",
)


@dataclass(frozen=True, slots=True)
class TrainConfig:
    """Everything a walk-forward run is parameterised by."""

    window_size: int = 20
    horizon: int = 10
    # Lookbacks of the baseline features fed beside the window.
    momentum_length: int = 252
    momentum_skip: int = 21
    lookback: int = 20
    train_size: int = 750
    test_size: int = 125
    embargo: int = 5
    validation_fraction: float = 0.1
    encoder: str = "mlp"  # "mlp" | "gru"
    hidden: int = 128
    dropout: float = 0.1
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    epochs: int = 8
    sessions_per_batch: int = 8
    patience: int = 3
    seed: int = 7
    device: str = "cpu"


@dataclass(frozen=True, slots=True)
class FoldResult:
    """What one fold produced: which sessions it scored and its validation IC."""

    train: range
    test: range
    best_validation_ic: float
    epochs_run: int


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """The assembled out-of-sample score matrix and the per-fold record."""

    scores: np.ndarray  # (T, N) NaN outside test ranges
    folds: tuple[FoldResult, ...]


@dataclass(frozen=True, slots=True)
class Features:
    """The model's inputs for a panel, aligned with it."""

    channels: np.ndarray  # (T, N, CHANNELS) float32, NaN where unknown
    ranks: np.ndarray  # (T, N, len(BASELINE_FEATURES)) float32, NaN where unknown
    labels: np.ndarray  # (T, N) float32 residual forward log return, NaN unknown


# Build the model's inputs from a panel: raw channels, baseline ranks, and
# the residual forward-return label. Everything at session t reads <= t
# except the label, which is the only forward-looking array and is kept
# apart.
def build_features(
    panel: Panel,
    horizon: int,
    momentum_length: int = 252,
    momentum_skip: int = 21,
    lookback: int = 20,
) -> Features:
    """Return channels, baseline ranks and residual labels for a panel."""
    channels = channel_matrices(panel).astype(np.float32)
    named = {
        "momentum_12_1": baselines.momentum(panel, momentum_length, momentum_skip),
        "relative_strength_20": baselines.relative_strength(panel, lookback),
        "theme_momentum_20": baselines.theme_momentum(panel, lookback),
        "theme_relative_strength_20": baselines.theme_relative_strength(
            panel, lookback
        ),
    }
    ranks = np.stack(
        [baselines.percentile_rank(named[name]) for name in BASELINE_FEATURES], axis=2
    ).astype(np.float32)
    own = panel.forward_log_returns(horizon)
    market = own[:, panel.index(panel.benchmark)][:, None]
    labels = (own - market).astype(np.float32)
    labels[:, panel.index(panel.benchmark)] = np.nan
    return Features(channels=channels, ranks=ranks, labels=labels)


# Which (session, name) pairs have a complete window, complete baseline
# ranks, and (when required) a known label.
def _eligible(features: Features, window_size: int, need_label: bool) -> np.ndarray:
    known = np.isfinite(features.channels).all(axis=2)  # (T, N)
    # A window ending at t is complete when every session in it is known.
    complete = np.ones_like(known)
    for offset in range(window_size):
        shifted = np.ones_like(known)
        shifted[offset:] = known[: known.shape[0] - offset]
        complete &= shifted
    complete[: window_size - 1] = False
    complete &= np.isfinite(features.ranks).all(axis=2)
    if need_label:
        complete &= np.isfinite(features.labels)
    return complete


@dataclass(slots=True)
class Normalizer:
    """Per-channel z-scoring fit on training sessions only."""

    channel_mean: np.ndarray
    channel_std: np.ndarray

    # Fit on the eligible (session, name) cells of the training range.
    @classmethod
    def fit(cls, features: Features, rows: range, eligible: np.ndarray) -> "Normalizer":
        """Compute channel statistics over eligible training cells."""
        block = features.channels[rows.start : rows.stop]
        mask = eligible[rows.start : rows.stop]
        values = block[mask]  # (k, CHANNELS)
        if len(values) == 0:
            raise ValueError("no eligible training cells to fit the normalizer")
        mean = values.mean(axis=0)
        std = values.std(axis=0)
        std = np.where(std > 1e-8, std, 1.0)
        return cls(
            channel_mean=mean.astype(np.float32), channel_std=std.astype(np.float32)
        )

    # Apply the statistics to a (…, CHANNELS) array.
    def apply(self, channels: np.ndarray) -> np.ndarray:
        """Return z-scored channels."""
        return (channels - self.channel_mean) / self.channel_std


# Gather the flattened window + ranks for a set of (session, column) cells.
def _gather(
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    t: np.ndarray,
    cols: np.ndarray,
) -> np.ndarray:
    """Return (k, window_size, CHANNELS + ranks) inputs for the cells."""
    offsets = np.arange(window_size)[None, :]  # (1, W)
    rows = t[:, None] - (window_size - 1) + offsets  # (k, W)
    window = features.channels[rows, cols[:, None]]  # (k, W, C)
    window = normalizer.apply(window)
    ranks = features.ranks[t, cols]  # (k, R)
    ranks = np.repeat(ranks[:, None, :], window_size, axis=1)  # (k, W, R)
    return np.concatenate([window, ranks], axis=2).astype(np.float32)


class Ranker(nn.Module):
    """Scores one (window, ranks) input; MLP or GRU encoder."""

    # `inputs` is the per-step width (channels + ranks); the MLP flattens
    # window_size x inputs, the GRU reads the sequence.
    def __init__(
        self, inputs: int, window_size: int, encoder: str, hidden: int, dropout: float
    ) -> None:
        super().__init__()
        self.encoder_kind = encoder
        if encoder == "mlp":
            self.body = nn.Sequential(
                nn.Flatten(),
                nn.Linear(inputs * window_size, hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden, hidden // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden // 2, 1),
            )
        elif encoder == "gru":
            self.gru = nn.GRU(inputs, hidden, batch_first=True)
            self.body = nn.Sequential(
                nn.Dropout(dropout),
                nn.Linear(hidden, hidden // 2),
                nn.GELU(),
                nn.Linear(hidden // 2, 1),
            )
        else:
            raise ValueError(f"unknown encoder {encoder!r}")

    # Forward pass over (batch, window_size, inputs).
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return one score per row."""
        if self.encoder_kind == "gru":
            _, last = self.gru(x)
            return self.body(last[-1]).squeeze(-1)
        return self.body(x).squeeze(-1)


# The cross-sectional loss for one session: negative Pearson correlation
# between scores and labels. Constant scores give zero gradient rather than
# NaN, which is what keeps a degenerate epoch from poisoning the run.
def session_loss(scores: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """Return -corr(scores, labels) for one session's cross-section."""
    if scores.numel() < 3:
        return scores.sum() * 0.0
    s = scores - scores.mean()
    y = labels - labels.mean()
    denominator = torch.sqrt((s * s).sum() * (y * y).sum() + 1e-12)
    return -(s * y).sum() / denominator


# The mean rank IC of a model over a set of sessions, as numpy.
def _validation_ic(
    model: Ranker,
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    sessions: list[int],
    eligible: np.ndarray,
    device: str,
) -> float:
    from backend.market.harness import rank_correlation

    model.eval()
    ics: list[float] = []
    with torch.no_grad():
        for t in sessions:
            cols = np.flatnonzero(eligible[t])
            if len(cols) < 10:
                continue
            x = torch.from_numpy(
                _gather(features, normalizer, window_size, np.full(len(cols), t), cols)
            ).to(device)
            pred = model(x).cpu().numpy()
            ics.append(rank_correlation(pred, features.labels[t, cols]))
    model.train()
    return float(np.nanmean(ics)) if ics else float("nan")


# Train one fold and return the fitted model plus its record. Sessions are
# shuffled per epoch; each optimisation step averages the loss over a batch
# of sessions so every step is a cross-sectional objective.
def train_fold(
    features: Features,
    config: TrainConfig,
    train: range,
    eligible_labelled: np.ndarray,
    log: Callable[[str], None] | None = None,
) -> tuple[Ranker, Normalizer, float, int]:
    """Fit a Ranker on `train` sessions with validation on the range's tail."""
    torch.manual_seed(config.seed)
    rng = np.random.default_rng(config.seed)
    normalizer = Normalizer.fit(features, train, eligible_labelled)
    split = train.stop - max(1, int(len(train) * config.validation_fraction))
    fit_sessions = [
        t for t in range(train.start, split) if eligible_labelled[t].sum() >= 10
    ]
    val_sessions = [
        t for t in range(split, train.stop) if eligible_labelled[t].sum() >= 10
    ]
    if not fit_sessions:
        raise ValueError("no training sessions with enough eligible names")

    inputs = CHANNELS + len(BASELINE_FEATURES)
    model = Ranker(
        inputs, config.window_size, config.encoder, config.hidden, config.dropout
    ).to(config.device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    best_ic = float("-inf")
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    stale = 0
    epochs_run = 0
    for epoch in range(config.epochs):
        order = rng.permutation(fit_sessions)
        for start in range(0, len(order), config.sessions_per_batch):
            batch = order[start : start + config.sessions_per_batch]
            optimizer.zero_grad()
            losses = []
            for t in batch:
                cols = np.flatnonzero(eligible_labelled[t])
                x = torch.from_numpy(
                    _gather(
                        features,
                        normalizer,
                        config.window_size,
                        np.full(len(cols), t),
                        cols,
                    )
                ).to(config.device)
                y = torch.from_numpy(features.labels[t, cols]).to(config.device)
                losses.append(session_loss(model(x), y))
            loss = torch.stack(losses).mean()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        epochs_run = epoch + 1
        val_ic = (
            _validation_ic(
                model,
                features,
                normalizer,
                config.window_size,
                val_sessions,
                eligible_labelled,
                config.device,
            )
            if val_sessions
            else float("nan")
        )
        if log:
            log(f"    epoch {epoch + 1}: validation IC {val_ic:.4f}")
        if np.isnan(val_ic) or val_ic > best_ic:
            if not np.isnan(val_ic):
                best_ic = val_ic
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= config.patience:
                break
    model.load_state_dict(best_state)
    model.eval()
    return model, normalizer, best_ic, epochs_run


# Score every eligible cell of the given sessions with a fitted model.
def score_sessions(
    model: Ranker,
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    sessions: range,
    eligible: np.ndarray,
    device: str,
    out: np.ndarray,
) -> None:
    """Write model scores into `out` for eligible cells of `sessions`."""
    with torch.no_grad():
        for t in sessions:
            cols = np.flatnonzero(eligible[t])
            if len(cols) == 0:
                continue
            x = torch.from_numpy(
                _gather(features, normalizer, window_size, np.full(len(cols), t), cols)
            ).to(device)
            out[t, cols] = model(x).cpu().numpy()


# The features a config asks for.
def _features_for(panel: Panel, config: TrainConfig) -> Features:
    return build_features(
        panel,
        config.horizon,
        momentum_length=config.momentum_length,
        momentum_skip=config.momentum_skip,
        lookback=config.lookback,
    )


# Run the whole walk-forward: train each fold on its purged range, score its
# test range, assemble one out-of-sample score matrix.
def walk_forward(
    panel: Panel,
    config: TrainConfig,
    log: Callable[[str], None] | None = None,
) -> WalkForwardResult:
    """Return out-of-sample scores for the panel under purged walk-forward folds."""
    features = _features_for(panel, config)
    labelled = _eligible(features, config.window_size, need_label=True)
    scorable = _eligible(features, config.window_size, need_label=False)
    folds = walk_forward_folds(
        len(panel.dates),
        config.train_size,
        config.test_size,
        config.horizon,
        config.embargo,
    )
    if not folds:
        raise ValueError("panel too short for one walk-forward fold")
    scores = np.full(features.labels.shape, np.nan, dtype=np.float32)
    records: list[FoldResult] = []
    for index, (train, test) in enumerate(folds):
        if log:
            log(
                f"fold {index + 1}/{len(folds)}: "
                f"train {panel.dates[train.start]}..{panel.dates[train.stop - 1]}, "
                f"test {panel.dates[test.start]}..{panel.dates[test.stop - 1]}"
            )
        model, normalizer, best_ic, epochs_run = train_fold(
            features, config, train, labelled, log
        )
        score_sessions(
            model,
            features,
            normalizer,
            config.window_size,
            test,
            scorable,
            config.device,
            scores,
        )
        records.append(
            FoldResult(
                train=train,
                test=test,
                best_validation_ic=best_ic,
                epochs_run=epochs_run,
            )
        )
    return WalkForwardResult(scores=scores, folds=tuple(records))


# Fit one model on everything up to the last labelled session and score the
# final session: what the model says today. The training range ends
# horizon + embargo sessions before the last one so no label is partial.
def score_today(
    panel: Panel, config: TrainConfig, log: Callable[[str], None] | None = None
) -> np.ndarray:
    """Return scores for the last session from a model trained on all prior history."""
    features = _features_for(panel, config)
    labelled = _eligible(features, config.window_size, need_label=True)
    scorable = _eligible(features, config.window_size, need_label=False)
    last = len(panel.dates) - 1
    train = range(
        max(0, last - config.horizon - config.embargo - config.train_size),
        last - config.horizon - config.embargo,
    )
    model, normalizer, _, _ = train_fold(features, config, train, labelled, log)
    out = np.full(features.labels.shape, np.nan, dtype=np.float32)
    score_sessions(
        model,
        features,
        normalizer,
        config.window_size,
        range(last, last + 1),
        scorable,
        config.device,
        out,
    )
    return out[last]
