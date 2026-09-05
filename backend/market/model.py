"""The learned ranker, trained the only way its number can be trusted.

A cross-sectional model: on each session it scores every name, and the
loss is the negative correlation between its scores and the names'
*residual* forward returns within that session. It is never asked to
predict a price, only to order the cross-section, because ordering is what
a long-short book is made of and because a level forecast for a single
name has no information at this horizon (the baseline report measured
that).

Inputs per (session, name): the last `window_size` sessions of the raw
channels from `windows.channel_matrices` — optionally widened with the
multi-scale causal statistics in `alpha.py`, which is what the leaderboard
models read — plus the baselines' percentile ranks on that session.
Channels are z-scored, clipped, with statistics fit on the training
sessions of the fold only. The training label is the residual forward
return, or its cross-sectional rank (the leaderboard's CSRankNorm), which
makes the correlation loss a rank correlation and stops a few outliers
from owning the gradient.

Training is walk-forward through `harness.walk_forward_folds`: each fold
fits on its training range (whose last label ends before the test range
starts), keeps the tail of that range as validation for early stopping, and
scores its test range. Several seeds can be trained per fold and their
scores averaged. The scores from every fold are assembled into one
(sessions x tickers) matrix that is NaN outside the test ranges and handed
to `harness.evaluate_scores` — the same function, the same residual label,
the same cost accounting the baselines were measured with. A model that
does not beat the baseline rows there does not exist.

Encoders:

- `mlp`, `gru`: score each name alone.
- `xsect`: a GRU per name, then transformer attention across every name on
  the same session, so a score can depend on what the rest of the
  cross-section is doing.
- `master`: the shape of the AAAI-24 MASTER family — a market-state vector
  gates the input features, a transformer over time inside each name, then
  attention across names.
- `lgbm`: a LightGBM regressor on the last session's features — the
  tabular reference that every deep model on the leaderboard is judged
  against.

torch is imported here and nowhere else in the package, so the store, the
panel and the baselines never need it.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
import torch
from torch import nn

from backend.market import baselines
from backend.market.alpha import alpha_features
from backend.market.harness import rank_correlation, walk_forward_folds
from backend.market.panel import Panel
from backend.market.windows import channel_matrices

# The baselines whose percentile ranks are fed alongside the window.
BASELINE_FEATURES: tuple[str, ...] = (
    "momentum_12_1",
    "relative_strength_20",
    "theme_momentum_20",
    "theme_relative_strength_20",
)

# z-scores beyond this are clipped: a single split-day outlier must not
# dominate a fold.
CLIP = 5.0


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
    features: str = "raw"  # "raw" | "alpha" | "alpha+edgar" | "raw+edgar"
    label: str = "residual"  # "residual" | "rank"
    encoder: str = "mlp"  # mlp | gru | xsect | master | lgbm | chart_cnn | tape
    hidden: int = 128
    dropout: float = 0.1
    heads: int = 4
    temporal_layers: int = 1
    cross_layers: int = 2
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    epochs: int = 8
    sessions_per_batch: int = 8
    patience: int = 3
    seeds: int = 1
    seed: int = 7
    cnn_max_train_cells: int = 60_000
    tape_sessions: int = 5  # sessions of 15-minute bars the tape encoder reads
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

    channels: np.ndarray  # (T, N, C) float32, NaN where unknown
    ranks: np.ndarray  # (T, N, R) float32, NaN where unknown
    market: np.ndarray  # (T, M) float32 market-state vector, NaN where unknown
    labels: np.ndarray  # (T, N) float32 training label, NaN unknown
    tape: np.ndarray | None = None  # (T, N, 26, 5) float32, NaN where absent

    @property
    def width(self) -> int:
        return int(self.channels.shape[2] + self.ranks.shape[2])


# Build the model's inputs from a panel. Everything at session t reads <= t
# except the label, which is the only forward-looking array and is kept
# apart.
def build_features(
    panel: Panel,
    horizon: int,
    momentum_length: int = 252,
    momentum_skip: int = 21,
    lookback: int = 20,
    features: str = "raw",
    label: str = "residual",
    extra: np.ndarray | None = None,
    tape: np.ndarray | None = None,
    market_extra: np.ndarray | None = None,
) -> Features:
    """Return channels, baseline ranks, market state and labels for a panel."""
    channels = channel_matrices(panel).astype(np.float32)
    parts = features.split("+")
    if parts[0] == "alpha":
        channels = np.concatenate([channels, alpha_features(panel)], axis=2)
    elif parts[0] != "raw":
        raise ValueError(f"unknown feature set {features!r}")
    extras = [p for p in parts[1:] if p]
    layers = ("edgar", "tone", "technical", "intraday", "calendar", "macro")
    if any(p not in layers for p in extras):
        raise ValueError(f"unknown feature set {features!r}")
    if extras:
        if extra is None:
            raise ValueError("extra features requested but no extra array given")
        channels = np.concatenate([channels, extra.astype(np.float32)], axis=2)
    named = {
        "momentum_12_1": baselines.momentum(panel, momentum_length, momentum_skip),
        "relative_strength_20": baselines.relative_strength(panel, lookback),
        "theme_momentum_20": baselines.theme_momentum(
            panel, lookback, untagged_as_market=True
        ),
        "theme_relative_strength_20": baselines.theme_relative_strength(
            panel, lookback, untagged_as_market=True
        ),
    }
    ranks = np.stack(
        [baselines.percentile_rank(named[name]) for name in BASELINE_FEATURES], axis=2
    ).astype(np.float32)

    # The market state: the benchmark's own channels plus the cross-sectional
    # mean and dispersion of every channel on the session.
    bench = panel.index(panel.benchmark)
    known = np.isfinite(channels)
    counts = known.sum(axis=1)
    filled = np.where(known, channels, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(counts > 0, filled.sum(axis=1) / np.maximum(counts, 1), np.nan)
        sq = np.where(known, channels * channels, 0.0).sum(axis=1)
        var = np.where(counts > 0, sq / np.maximum(counts, 1) - mean * mean, np.nan)
        std = np.sqrt(np.maximum(var, 0.0))
    from backend.market.calendar import calendar_by_session

    blocks = [channels[:, bench, :], mean, std, calendar_by_session(panel)]
    if market_extra is not None:
        blocks.append(market_extra)
    market = np.concatenate(blocks, axis=1).astype(np.float32)

    residual = panel.forward_residual(horizon).astype(np.float32)
    residual[:, bench] = np.nan
    if label == "residual":
        labels = residual
    elif label == "rank":
        labels = (baselines.percentile_rank(residual) - 0.5).astype(np.float32)
    else:
        raise ValueError(f"unknown label {label!r}")
    return Features(
        channels=channels, ranks=ranks, market=market, labels=labels, tape=tape
    )


# The features a config asks for; `extra` is the (T, N, K) array an
# "+edgar" feature set concatenates.
def _features_for(
    panel: Panel,
    config: TrainConfig,
    extra: np.ndarray | None = None,
    tape: np.ndarray | None = None,
    market_extra: np.ndarray | None = None,
) -> Features:
    return build_features(
        panel,
        config.horizon,
        momentum_length=config.momentum_length,
        momentum_skip=config.momentum_skip,
        lookback=config.lookback,
        features=config.features,
        label=config.label,
        extra=extra,
        tape=tape,
        market_extra=market_extra,
    )


# Which (session, name) pairs have a complete window, complete baseline
# ranks, a known market state, and (when required) a known label.
def _eligible(
    features: Features,
    window_size: int,
    need_label: bool,
    tape_sessions: int = 0,
) -> np.ndarray:
    known = np.isfinite(features.channels).all(axis=2)  # (T, N)
    if tape_sessions and features.tape is not None:
        tape_known = np.isfinite(features.tape).all(axis=(2, 3))
        for offset in range(tape_sessions):
            shifted = np.zeros_like(tape_known)
            shifted[offset:] = tape_known[: tape_known.shape[0] - offset]
            known &= shifted
    complete = np.ones_like(known)
    for offset in range(window_size):
        shifted = np.ones_like(known)
        shifted[offset:] = known[: known.shape[0] - offset]
        complete &= shifted
    complete[: window_size - 1] = False
    complete &= np.isfinite(features.ranks).all(axis=2)
    market_known = np.isfinite(features.market).all(axis=1)
    complete &= market_known[:, None]
    if need_label:
        complete &= np.isfinite(features.labels)
    return complete


@dataclass(slots=True)
class Normalizer:
    """Per-feature z-scoring, clipped, fit on training sessions only."""

    channel_mean: np.ndarray
    channel_std: np.ndarray
    market_mean: np.ndarray
    market_std: np.ndarray

    # Fit on the eligible (session, name) cells of the training range.
    @classmethod
    def fit(cls, features: Features, rows: range, eligible: np.ndarray) -> "Normalizer":
        """Compute channel and market statistics over the training range."""
        block = features.channels[rows.start : rows.stop]
        mask = eligible[rows.start : rows.stop]
        values = block[mask]
        if len(values) == 0:
            raise ValueError("no eligible training cells to fit the normalizer")
        market = features.market[rows.start : rows.stop]
        market = market[np.isfinite(market).all(axis=1)]
        if len(market) == 0:
            market = np.zeros((1, features.market.shape[1]), dtype=np.float32)
        return cls(
            channel_mean=values.mean(axis=0).astype(np.float32),
            channel_std=_safe_std(values.std(axis=0)),
            market_mean=market.mean(axis=0).astype(np.float32),
            market_std=_safe_std(market.std(axis=0)),
        )

    # Apply the statistics to a (…, C) array of channels.
    def apply(self, channels: np.ndarray) -> np.ndarray:
        """Return clipped z-scored channels."""
        z = (channels - self.channel_mean) / self.channel_std
        return np.clip(z, -CLIP, CLIP)

    # Apply the statistics to a (M,) market vector.
    def apply_market(self, market: np.ndarray) -> np.ndarray:
        """Return the clipped z-scored market vector."""
        z = (market - self.market_mean) / self.market_std
        return np.clip(z, -CLIP, CLIP)


# A standard deviation that never divides by zero.
def _safe_std(std: np.ndarray) -> np.ndarray:
    return np.where(std > 1e-8, std, 1.0).astype(np.float32)


# Gather one session's inputs for a set of columns: the (names, W, width)
# window tensor and the (M,) market vector.
def _session_inputs(
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    t: int,
    cols: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (windows, market) for the names `cols` on session `t`."""
    rows = np.arange(t - window_size + 1, t + 1)
    _ = rows  # the tape, when present, is gathered by _tape_inputs
    window = features.channels[rows[:, None], cols[None, :]]  # (W, k, C)
    window = normalizer.apply(np.transpose(window, (1, 0, 2)))  # (k, W, C)
    ranks = np.repeat(features.ranks[t, cols][:, None, :], window_size, axis=1)
    x = np.concatenate([window, ranks], axis=2).astype(np.float32)
    market = normalizer.apply_market(features.market[t]).astype(np.float32)
    return x, market


# Gather several sessions into one padded batch: (B, Nmax, W, width)
# inputs, (B, M) market vectors, a (B, Nmax) mask of real slots, and
# (B, Nmax) labels. One forward pass per optimiser step instead of one
# per session, which is what keeps a GPU busy.
def _batch_inputs(
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    sessions: np.ndarray,
    eligible: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return padded (inputs, market, mask, labels) for a batch of sessions."""
    parts = []
    for t in sessions:
        cols = np.flatnonzero(eligible[t])
        x, market = _session_inputs(features, normalizer, window_size, int(t), cols)
        parts.append((x, market, features.labels[t, cols]))
    widest = max(len(part[2]) for part in parts)
    width = parts[0][0].shape[2]
    x_out = np.zeros((len(parts), widest, window_size, width), dtype=np.float32)
    market_out = np.stack([part[1] for part in parts]).astype(np.float32)
    mask = np.zeros((len(parts), widest), dtype=bool)
    y_out = np.zeros((len(parts), widest), dtype=np.float32)
    for b, (x, _, y) in enumerate(parts):
        n = len(y)
        x_out[b, :n] = x
        mask[b, :n] = True
        y_out[b, :n] = y
    return x_out, market_out, mask, y_out


# The padded tape batch matching _batch_inputs, (B, Nmax, S*26, 5).
def _batch_tape(
    features: Features, tape_sessions: int, sessions: np.ndarray, eligible: np.ndarray
) -> np.ndarray:
    """Return the padded tape for a batch of sessions."""
    parts = [
        _tape_inputs(features, tape_sessions, int(t), np.flatnonzero(eligible[t]))
        for t in sessions
    ]
    widest = max(len(part) for part in parts)
    steps = parts[0].shape[1]
    out = np.zeros((len(parts), widest, steps, 5), dtype=np.float32)
    for b, part in enumerate(parts):
        out[b, : len(part)] = part
    return out


# The tape of the last `steps_sessions` sessions for the names `cols` on
# session `t`, as (k, steps_sessions * 26, 5), oldest bar first.
def _tape_inputs(
    features: Features, tape_sessions: int, t: int, cols: np.ndarray
) -> np.ndarray:
    """Return the concatenated tape of the last sessions for the given names."""
    assert features.tape is not None
    rows = np.arange(t - tape_sessions + 1, t + 1)
    block = features.tape[rows[:, None], cols[None, :]]  # (S, k, 26, 5)
    block = np.transpose(block, (1, 0, 2, 3))  # (k, S, 26, 5)
    return block.reshape(len(cols), tape_sessions * block.shape[2], block.shape[3])


class Ranker(nn.Module):
    """Scores a session's names; MLP, GRU, cross-sectional or MASTER-style."""

    # `inputs` is the per-step width (channels + ranks) and `market` the
    # width of the market-state vector. The training loop always passes one
    # whole session, which is what lets the cross-sectional encoders attend
    # across every name on it.
    def __init__(
        self,
        inputs: int,
        market: int,
        window_size: int,
        encoder: str,
        hidden: int,
        dropout: float,
        heads: int = 4,
        temporal_layers: int = 1,
        cross_layers: int = 2,
        tape_steps: int = 0,
    ) -> None:
        super().__init__()
        self.encoder_kind = encoder
        self.tape_steps = tape_steps
        if encoder in ("xsect", "master") and hidden % heads:
            raise ValueError("hidden must be divisible by heads")
        head = nn.Sequential(
            nn.LayerNorm(hidden),
            nn.Linear(hidden, hidden // 2),
            nn.GELU(),
            nn.Linear(hidden // 2, 1),
        )
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
            self.body = nn.Sequential(nn.Dropout(dropout), head)
        elif encoder == "xsect":
            self.temporal = nn.GRU(inputs, hidden, batch_first=True)
            self.cross = _transformer(hidden, heads, dropout, cross_layers)
            self.body = head
        elif encoder == "tape":
            # The tape: 1-D convolutions over K x 26 bars of five channels,
            # pooled; the daily window through a small MLP; both mixed across
            # the session's names by attention.
            self.tape_conv = nn.Sequential(
                nn.Conv1d(5, 32, kernel_size=5, padding=2),
                nn.GELU(),
                nn.MaxPool1d(2),
                nn.Conv1d(32, 64, kernel_size=5, padding=2),
                nn.GELU(),
                nn.MaxPool1d(2),
                nn.Conv1d(64, hidden, kernel_size=3, padding=1),
                nn.GELU(),
                nn.AdaptiveAvgPool1d(1),
            )
            self.daily = nn.Sequential(
                nn.Flatten(),
                nn.Linear(inputs * window_size, hidden),
                nn.GELU(),
                nn.Dropout(dropout),
            )
            self.merge = nn.Linear(2 * hidden, hidden)
            self.cross = _transformer(hidden, heads, dropout, cross_layers)
            self.body = head
        elif encoder == "master":
            self.gate = nn.Sequential(nn.Linear(market, inputs), nn.Sigmoid())
            self.embed = nn.Linear(inputs, hidden)
            self.position = nn.Parameter(torch.zeros(1, window_size, hidden))
            self.temporal = _transformer(hidden, heads, dropout, temporal_layers)
            self.pool = nn.Linear(hidden, 1)
            self.cross = _transformer(hidden, heads, dropout, cross_layers)
            self.body = head
        else:
            raise ValueError(f"unknown encoder {encoder!r}")

    # Forward pass over one session: x is (names, window_size, inputs) and
    # market is (market,) or None for the encoders that ignore it.
    def forward(
        self,
        x: torch.Tensor,
        market: torch.Tensor | None = None,
        mask: torch.Tensor | None = None,
        tape: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Return one score per name.

        `x` is one session, (names, window, inputs), or a padded batch of
        sessions, (sessions, names, window, inputs), with `mask` (sessions,
        names) True where a slot holds a real name. Scores come back as
        (names,) or (sessions, names); padded slots carry garbage the
        caller must slice off.
        """
        single = x.dim() == 3
        if single:
            x = x.unsqueeze(0)
            if market is not None:
                market = market.unsqueeze(0)
            if tape is not None:
                tape = tape.unsqueeze(0)
        batch, names, window, width = x.shape
        flat = x.reshape(batch * names, window, width)
        padding = None if mask is None else ~mask
        if self.encoder_kind == "mlp":
            scores = self.body(flat).reshape(batch, names)
        elif self.encoder_kind == "gru":
            _, last = self.gru(flat)
            scores = self.body(last[-1]).reshape(batch, names)
        elif self.encoder_kind == "tape":
            if tape is None:
                raise ValueError("the tape encoder needs the tape tensor")
            # tape: (B, N, steps, 5) -> conv over steps
            steps = tape.shape[2]
            series = tape.reshape(batch * names, steps, 5).transpose(1, 2)
            tape_embedding = self.tape_conv(series).squeeze(-1)
            daily_embedding = self.daily(flat)
            merged = torch.nn.functional.gelu(
                self.merge(torch.cat([tape_embedding, daily_embedding], dim=1))
            )
            mixed = self.cross(
                merged.reshape(batch, names, -1), src_key_padding_mask=padding
            )
            scores = self.body(mixed).squeeze(-1)
        elif self.encoder_kind == "xsect":
            _, last = self.temporal(flat)
            tokens = last[-1].reshape(batch, names, -1)
            mixed = self.cross(tokens, src_key_padding_mask=padding)
            scores = self.body(mixed).squeeze(-1)
        else:  # master
            if market is None:
                raise ValueError("the master encoder needs the market vector")
            gate = (2.0 * self.gate(market)).reshape(batch, 1, 1, width)
            gated = (x * gate).reshape(batch * names, window, width)
            tokens = self.temporal(self.embed(gated) + self.position)
            weights = torch.softmax(self.pool(tokens).squeeze(-1), dim=1)
            pooled = (tokens * weights.unsqueeze(-1)).sum(dim=1)
            mixed = self.cross(
                pooled.reshape(batch, names, -1), src_key_padding_mask=padding
            )
            scores = self.body(mixed).squeeze(-1)
        return scores[0] if single else scores


# A stack of transformer encoder layers over a (batch, tokens, hidden) input.
def _transformer(hidden: int, heads: int, dropout: float, layers: int) -> nn.Module:
    layer = nn.TransformerEncoderLayer(
        d_model=hidden,
        nhead=heads,
        dim_feedforward=hidden * 2,
        dropout=dropout,
        batch_first=True,
    )
    return nn.TransformerEncoder(layer, num_layers=layers)


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


# Score one session with a model, as numpy.
def _predict(
    model: Ranker,
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    t: int,
    cols: np.ndarray,
    device: str,
) -> np.ndarray:
    x, market = _session_inputs(features, normalizer, window_size, t, cols)
    tape = None
    if model.encoder_kind == "tape":
        tape = torch.from_numpy(_tape_inputs(features, model.tape_steps, t, cols)).to(
            device
        )
    with torch.no_grad():
        scores = model(
            torch.from_numpy(x).to(device),
            torch.from_numpy(market).to(device),
            tape=tape,
        )
    return scores.cpu().numpy()


# The mean rank IC of a model over a set of sessions.
def _validation_ic(
    model: Ranker,
    features: Features,
    normalizer: Normalizer,
    window_size: int,
    sessions: list[int],
    eligible: np.ndarray,
    device: str,
) -> float:
    model.eval()
    ics: list[float] = []
    for t in sessions:
        cols = np.flatnonzero(eligible[t])
        if len(cols) < 10:
            continue
        pred = _predict(model, features, normalizer, window_size, t, cols, device)
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

    model = Ranker(
        features.width,
        features.market.shape[1],
        config.window_size,
        config.encoder,
        config.hidden,
        config.dropout,
        heads=config.heads,
        temporal_layers=config.temporal_layers,
        cross_layers=config.cross_layers,
        tape_steps=config.tape_sessions if config.encoder == "tape" else 0,
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
            x, market, mask, y = _batch_inputs(
                features, normalizer, config.window_size, batch, eligible_labelled
            )
            tape_batch = None
            if config.encoder == "tape":
                tape_batch = torch.from_numpy(
                    _batch_tape(
                        features, config.tape_sessions, batch, eligible_labelled
                    )
                ).to(config.device)
            scores = model(
                torch.from_numpy(x).to(config.device),
                torch.from_numpy(market).to(config.device),
                torch.from_numpy(mask).to(config.device),
                tape=tape_batch,
            )
            losses = []
            for b in range(len(batch)):
                n = int(mask[b].sum())
                y_b = torch.from_numpy(y[b, :n]).to(config.device)
                losses.append(session_loss(scores[b, :n], y_b))
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


# Score every eligible cell of the given sessions with a fitted model,
# standardised per session so that seeds can be averaged on one scale.
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
    """Write per-session standardised model scores into `out`."""
    for t in sessions:
        cols = np.flatnonzero(eligible[t])
        if len(cols) == 0:
            continue
        pred = _predict(model, features, normalizer, window_size, t, cols, device)
        out[t, cols] = _standardise(pred)


# A session's scores centred and scaled, so different models' scores are
# comparable before they are averaged.
def _standardise(values: np.ndarray) -> np.ndarray:
    std = values.std()
    return (values - values.mean()) / std if std > 1e-12 else values - values.mean()


# Rows of (last-session channels + ranks + market) for the eligible cells
# of a range of sessions: the tabular view a tree model reads.
def _tabular_rows(
    features: Features,
    normalizer: Normalizer,
    sessions: range,
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    xs, ys = [], []
    width = features.width + features.market.shape[1]
    for t in sessions:
        cols = np.flatnonzero(mask[t])
        if len(cols) == 0:
            continue
        x = normalizer.apply(features.channels[t, cols])
        r = features.ranks[t, cols]
        m = normalizer.apply_market(features.market[t])[None, :]
        xs.append(np.concatenate([x, r, np.repeat(m, len(cols), 0)], axis=1))
        ys.append(features.labels[t, cols])
    if not xs:
        return np.empty((0, width), dtype=np.float32), np.empty(0, dtype=np.float32)
    return np.concatenate(xs), np.concatenate(ys)


# The tabular reference: LightGBM on the last session's features. Trained
# on the fold's fit sessions with early stopping on the validation tail;
# writes per-session standardised scores for the test range into `out`.
def _lgbm_fold(
    features: Features,
    config: TrainConfig,
    train: range,
    test: range,
    labelled: np.ndarray,
    scorable: np.ndarray,
    out: np.ndarray,
    log: Callable[[str], None] | None,
) -> tuple[float, int]:
    import lightgbm as lgb

    normalizer = Normalizer.fit(features, train, labelled)
    split = train.stop - max(1, int(len(train) * config.validation_fraction))
    x_fit, y_fit = _tabular_rows(
        features, normalizer, range(train.start, split), labelled
    )
    x_val, y_val = _tabular_rows(
        features, normalizer, range(split, train.stop), labelled
    )
    params = {
        "objective": "regression",
        "learning_rate": 0.03,
        "num_leaves": 63,
        "min_data_in_leaf": 200,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "feature_fraction": 0.8,
        "lambda_l2": 1.0,
        "seed": config.seed,
        "verbosity": -1,
    }
    fit_set = lgb.Dataset(x_fit, label=y_fit)
    if len(x_val):
        booster = lgb.train(
            params,
            fit_set,
            num_boost_round=600,
            valid_sets=[lgb.Dataset(x_val, label=y_val, reference=fit_set)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
    else:
        booster = lgb.train(params, fit_set, num_boost_round=600)
    trees = max(1, int(booster.best_iteration or booster.num_trees()))
    ics: list[float] = []
    for t in range(split, train.stop):
        cols = np.flatnonzero(labelled[t])
        if len(cols) < 10:
            continue
        x, _ = _tabular_rows(features, normalizer, range(t, t + 1), labelled)
        ics.append(
            rank_correlation(
                booster.predict(x, num_iteration=trees), features.labels[t, cols]
            )
        )
    val_ic = float(np.nanmean(ics)) if ics else float("nan")
    if log:
        log(f"    lightgbm: {trees} trees, validation IC {val_ic:.4f}")
    for t in test:
        cols = np.flatnonzero(scorable[t])
        if len(cols) == 0:
            continue
        x, _ = _tabular_rows(features, normalizer, range(t, t + 1), scorable)
        out[t, cols] = _standardise(booster.predict(x, num_iteration=trees))
    return val_ic, trees


# The chart-image CNN (Jiang, Kelly and Xiu 2023) on one fold: train on
# the labelled cells of the fit range, early-stop on the validation tail,
# score the test range's cells. Writes per-session standardised scores.
def _chart_cnn_fold(
    panel: Panel,
    features: Features,
    config: TrainConfig,
    train: range,
    test: range,
    labelled: np.ndarray,
    scorable: np.ndarray,
    out: np.ndarray,
    log: Callable[[str], None] | None,
) -> tuple[float, int]:
    from backend.market.chart_cnn import train_and_score

    split = train.stop - max(1, int(len(train) * config.validation_fraction))
    train_cells = np.argwhere(labelled[train.start : split])
    train_cells[:, 0] += train.start
    val_cells = np.argwhere(labelled[split : train.stop])
    val_cells[:, 0] += split
    test_cells = np.argwhere(scorable[test.start : test.stop])
    test_cells[:, 0] += test.start
    # The CNN reads a fixed 20-session image; cap the fit set so a fold
    # renders in minutes, not hours, keeping every session represented.
    rng = np.random.default_rng(config.seed)
    if len(train_cells) > config.cnn_max_train_cells:
        train_cells = train_cells[
            rng.choice(len(train_cells), config.cnn_max_train_cells, replace=False)
        ]
    scores, acc, epochs_run = train_and_score(
        panel,
        features.labels,
        train_cells,
        val_cells,
        test_cells,
        device=config.device,
        epochs=config.epochs,
        seed=config.seed,
        log=log,
    )
    by_session: dict[int, list[int]] = {}
    for i, (t, _) in enumerate(test_cells):
        by_session.setdefault(int(t), []).append(i)
    for t, rows in by_session.items():
        values = scores[rows]
        known = np.isfinite(values)
        if known.sum() < 2:
            continue
        cols = test_cells[rows, 1][known]
        out[t, cols] = _standardise(values[known])
    return acc, epochs_run


# Run the whole walk-forward: train each fold on its purged range (one
# model per seed, scores averaged), score its test range, assemble one
# out-of-sample score matrix.
def walk_forward(
    panel: Panel,
    config: TrainConfig,
    log: Callable[[str], None] | None = None,
    extra: np.ndarray | None = None,
    tape: np.ndarray | None = None,
    market_extra: np.ndarray | None = None,
) -> WalkForwardResult:
    """Return out-of-sample scores for the panel under purged walk-forward folds."""
    features = _features_for(panel, config, extra, tape, market_extra)
    need_tape = config.tape_sessions if config.encoder == "tape" else 0
    if need_tape and features.tape is None:
        raise ValueError("the tape encoder needs the tape tensor; fetch 15-minute bars")
    labelled = _eligible(features, config.window_size, True, need_tape)
    scorable = _eligible(features, config.window_size, False, need_tape)
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
        if config.encoder == "lgbm":
            val_ic, trees = _lgbm_fold(
                features, config, train, test, labelled, scorable, scores, log
            )
            records.append(FoldResult(train, test, val_ic, trees))
            continue
        if config.encoder == "chart_cnn":
            acc, epochs_run = _chart_cnn_fold(
                panel, features, config, train, test, labelled, scorable, scores, log
            )
            records.append(FoldResult(train, test, acc, epochs_run))
            continue
        fold_scores = np.full(
            (config.seeds,) + features.labels.shape, np.nan, dtype=np.float32
        )
        val_ics: list[float] = []
        epochs: list[int] = []
        for k in range(config.seeds):
            seeded = replace(config, seed=config.seed + k)
            model, normalizer, best_ic, epochs_run = train_fold(
                features, seeded, train, labelled, log
            )
            score_sessions(
                model,
                features,
                normalizer,
                config.window_size,
                test,
                scorable,
                config.device,
                fold_scores[k],
            )
            val_ics.append(best_ic)
            epochs.append(epochs_run)
        known = np.isfinite(fold_scores)
        counts = known.sum(axis=0)
        total = np.where(known, fold_scores, 0.0).sum(axis=0)
        averaged = np.where(counts > 0, total / np.maximum(counts, 1), np.nan)
        scores[test.start : test.stop] = averaged[test.start : test.stop]
        records.append(
            FoldResult(train, test, float(np.nanmean(val_ics)), int(np.mean(epochs)))
        )
    return WalkForwardResult(scores=scores, folds=tuple(records))


# Fit one model on everything up to the last labelled session and score the
# final session: what the model says today. The training range ends
# horizon + embargo sessions before the last one so no label is partial.
def score_today(
    panel: Panel,
    config: TrainConfig,
    log: Callable[[str], None] | None = None,
    extra: np.ndarray | None = None,
    tape: np.ndarray | None = None,
    market_extra: np.ndarray | None = None,
) -> np.ndarray:
    """Return scores for the last session from a model trained on all prior history."""
    features = _features_for(panel, config, extra, tape, market_extra)
    need_tape = config.tape_sessions if config.encoder == "tape" else 0
    labelled = _eligible(features, config.window_size, True, need_tape)
    scorable = _eligible(features, config.window_size, False, need_tape)
    last = len(panel.dates) - 1
    stop = last - config.horizon - config.embargo
    train = range(max(0, stop - config.train_size), stop)
    out = np.full(features.labels.shape, np.nan, dtype=np.float32)
    if config.encoder == "lgbm":
        _lgbm_fold(
            features, config, train, range(last, last + 1), labelled, scorable, out, log
        )
        return out[last]
    model, normalizer, _, _ = train_fold(features, config, train, labelled, log)
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


# The EDGAR feature array for a panel, from the store's newest frames, or
# None when the store holds no EDGAR layer. Shared by the CLIs.
def load_edgar_features(store, panel, asof=None):
    """Return edgar_features(panel, records) from stored frames, or None."""
    from datetime import datetime

    from backend.market import edgar

    records = {}
    for ticker in panel.tickers:
        events = store.read_frame("edgar_events", ticker, asof)
        facts = store.read_frame("edgar_facts", ticker, asof)
        if events is None or facts is None:
            continue
        columns, meta = events
        records[ticker] = edgar.record_from_frames(
            ticker,
            int(meta.get("cik", "0")),
            columns,
            facts[0],
            datetime.fromisoformat(
                meta.get("source_time", "2000-01-01T00:00:00+00:00")
            ),
        )
    if not records:
        return None
    return edgar.edgar_features(panel, records)


# The release-tone feature array for a panel from stored frames, or None.
def load_tone_features(store, panel, asof=None):
    """Return language.tone_features(panel, records) from stored frames, or None."""
    from backend.market import language

    records = {}
    for ticker in panel.tickers:
        frame = store.read_frame(language.TONE_KIND, ticker, asof)
        if frame is None:
            continue
        records[ticker] = language.records_from_frame(frame[0])
    if not records:
        return None
    return language.tone_features(panel, records)


# The concatenated extra array a feature set names ("alpha+edgar+tone"),
# or None when it names none. Raises when a named layer is not stored.
def load_extra_features(store, panel, features, asof=None):
    """Return the (T, N, K) extra array for the layers `features` names."""
    parts = [p for p in features.split("+")[1:] if p]
    arrays = []
    for part in parts:
        if part == "edgar":
            array = load_edgar_features(store, panel, asof)
        elif part == "tone":
            array = load_tone_features(store, panel, asof)
        elif part == "technical":
            from backend.market.technical import technical_features

            array = technical_features(panel)
        elif part == "intraday":
            array = load_intraday_features(store, panel, asof)
        elif part == "calendar":
            from backend.market.calendar import calendar_features

            array = calendar_features(panel)
        elif part == "macro":
            from backend.market.macro import macro_features

            array = macro_features(store, panel, asof)
        else:
            raise ValueError(f"unknown feature layer {part!r}")
        if array is None:
            raise ValueError(
                f"no {part} layer in the store; run market_{part} --refresh"
            )
        arrays.append(array)
    if not arrays:
        return None
    return np.concatenate(arrays, axis=2)


# The 15-minute feature array for a panel from stored Alpaca bars, or None.
def load_intraday_features(store, panel, asof=None):
    """Return alpaca.intraday_features(panel, bars) from stored frames, or None."""
    from backend.market import alpaca

    bars = {}
    for ticker in panel.tickers:
        frame = store.read_frame(alpaca.BARS_KIND, ticker, asof)
        if frame is None:
            continue
        bars[ticker] = alpaca.bars_from_frame(frame[0])
    if not bars:
        return None
    return alpaca.intraday_features(panel, bars)


# The tape tensor for a panel from stored 15-minute frames, or None.
def load_tape(store, panel, asof=None):
    """Return tape.tape_tensor(panel, bars) from stored bars_15m frames, or None."""
    from backend.market import alpaca, tape

    bars = {}
    for ticker in panel.tickers:
        frame = store.read_frame(alpaca.BARS_KIND, ticker, asof)
        if frame is None:
            continue
        bars[ticker] = alpaca.bars_from_frame(frame[0])
    if not bars:
        return None
    return tape.tape_tensor(panel, bars)


# The per-session macro block for the market-state vector, or None when
# the store holds none of the series.
def load_market_extra(store, panel, asof=None):
    """Return macro.macro_by_session(store, panel) with NaN filled by 0, or None."""
    from backend.market.macro import macro_by_session

    block = macro_by_session(store, panel, asof)
    if not np.isfinite(block).any():
        return None
    return np.where(np.isfinite(block), block, 0.0).astype(np.float32)
