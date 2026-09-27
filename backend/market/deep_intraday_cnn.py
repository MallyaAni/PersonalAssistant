"""The temporal CNN of the deep-intraday plan, stage 1.

Imported by `deep_intraday.walk_forward` only when the CNN is asked for,
so the rest of the study runs where torch is absent. The architecture is
the plan's: three dilated one-dimensional convolutions (dilations 1, 2, 4)
over the `K * 26`-step sequence, global pooling, the three scalars joined,
one hidden layer and two heads (rank, volatility). Training is the plan's
one fixed configuration (`deep_intraday.CNN_CONFIG`): Adam, 20 epochs,
batch 512, dropout 0.1, weight decay 1e-4. The loss is the mean squared
error of the head the target names; the other head is left untrained on
that fit, so "cnn x rank" and "cnn x vol" are two trials, as the plan
counts them.

Device. `fit_predict(..., device="auto")` trains on cuda when torch sees
one and on the CPU otherwise (`deep_intraday.resolve_device`). The model
and each batch go to the device; the standardized dataset stays on the CPU
and is moved one batch at a time, so a large dataset never has to fit in
GPU memory beside whatever else is running there. On the CPU the
arithmetic is exactly what it was before the device option existed: the
seed, the parameter initialization, the shuffle generator and the batch
order are unchanged. The training loop (`train_predict`) is shared with
`deep_intraday_patchtst`, so the two families differ only in the network.

Size. With the configuration as written (32 channels, kernel 5, dilations
1, 2, 4, a 32-unit hidden layer) the network has 13,058 trainable
parameters (512 + 5,152 + 5,152 in the convolutions, 2,176 in the hidden
layer, 66 in the heads); the plan's "about fifty thousand" was an estimate
and the written configuration is what is built. The count is reported in
the payload (`parameters.cnn`) rather than tuned toward the estimate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import torch
from torch import nn

from backend.market.deep_intraday import announce_device, resolve_device

# Rows per prediction batch.
PREDICT_BATCH = 4096
# The heads, in output order.
HEADS = ("rank", "vol")


class TemporalCNN(nn.Module):  # type: ignore[misc]  # torch is untyped here
    """Dilated convolutions over the bar sequence, pooled, with two heads."""

    # Build the network for `in_channels` sequence channels and `scalars`
    # side inputs.
    def __init__(
        self,
        in_channels: int,
        scalars: int,
        channels: int = 32,
        kernel: int = 5,
        dilations: tuple[int, ...] = (1, 2, 4),
        dropout: float = 0.1,
        hidden: int = 32,
    ) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        width = in_channels
        for dilation in dilations:
            layers.append(
                nn.Conv1d(
                    width,
                    channels,
                    kernel,
                    dilation=dilation,
                    padding=(kernel - 1) * dilation // 2,
                )
            )
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            width = channels
        self.convolutions = nn.Sequential(*layers)
        # Mean and max pooling over the steps, concatenated with the scalars.
        self.hidden = nn.Sequential(
            nn.Linear(2 * channels + scalars, hidden), nn.ReLU(), nn.Dropout(dropout)
        )
        self.heads = nn.Linear(hidden, len(HEADS))

    # Forward pass: `seq` is (B, steps, channels), `scalar` is (B, scalars);
    # returns (B, 2) with the rank head first and the volatility head second.
    def forward(self, seq: torch.Tensor, scalar: torch.Tensor) -> torch.Tensor:
        """Return the (B, 2) head outputs."""
        x = self.convolutions(seq.transpose(1, 2))
        pooled = torch.cat([x.mean(dim=2), x.amax(dim=2), scalar], dim=1)
        return self.heads(self.hidden(pooled))


# The number of trainable parameters.
def parameter_count(model: nn.Module) -> int:
    """Return how many parameters the model trains."""
    return int(sum(p.numel() for p in model.parameters() if p.requires_grad))


# Per-feature mean and standard deviation from the training rows: per
# channel over every step for the sequence, per column for the scalars.
def _standardizer(
    seq: np.ndarray, scalar: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    flat = seq.reshape(-1, seq.shape[-1])
    seq_mean = flat.mean(axis=0, dtype=np.float64)
    seq_scale = flat.std(axis=0, dtype=np.float64)
    seq_scale[~(seq_scale > 0)] = 1.0
    scalar_mean = scalar.mean(axis=0, dtype=np.float64)
    scalar_scale = scalar.std(axis=0, dtype=np.float64)
    scalar_scale[~(scalar_scale > 0)] = 1.0
    # float32 statistics so standardizing a float32 sequence never promotes
    # the whole array to float64.
    return (
        seq_mean.astype(np.float32),
        seq_scale.astype(np.float32),
        scalar_mean.astype(np.float32),
        scalar_scale.astype(np.float32),
    )


# Fit the CNN on the training rows for `target` ("rank" or "vol") with
# the fixed configuration and return (predictions on the test rows, the
# parameter count). Inputs are standardized on the training rows, the
# target centred and scaled on them and the prediction mapped back.
# `device` is "auto", "cpu" or "cuda".
def fit_predict(
    seq_train: np.ndarray,
    scalar_train: np.ndarray,
    y_train: np.ndarray,
    seq_test: np.ndarray,
    scalar_test: np.ndarray,
    target: str,
    config: Mapping[str, Any],
    device: str = "auto",
) -> tuple[np.ndarray, int]:
    """Return (test predictions, parameter count)."""
    torch.manual_seed(int(config.get("seed", 0)))
    model = TemporalCNN(
        in_channels=seq_train.shape[-1],
        scalars=scalar_train.shape[-1],
        channels=int(config["channels"]),
        kernel=int(config["kernel"]),
        dilations=tuple(int(d) for d in config["dilations"]),
        dropout=float(config["dropout"]),
        hidden=int(config.get("hidden", 32)),
    )
    return train_predict(
        model,
        seq_train,
        scalar_train,
        y_train,
        seq_test,
        scalar_test,
        target,
        config,
        device,
    )


# Train an already-built two-head network (built after `torch.manual_seed`
# by the caller, so its initialization is the seeded one) on the training
# rows for `target` with the fixed configuration - Adam at `lr` with
# `weight_decay`, `epochs` passes over shuffled batches of `batch` rows,
# MSE on the selected head - and return (test predictions, parameter
# count). Inputs are standardized on the training rows, the target centred
# and scaled on them and the prediction mapped back. The standardized
# arrays stay on the CPU; each batch is moved to the device as it is used.
def train_predict(
    model: nn.Module,
    seq_train: np.ndarray,
    scalar_train: np.ndarray,
    y_train: np.ndarray,
    seq_test: np.ndarray,
    scalar_test: np.ndarray,
    target: str,
    config: Mapping[str, Any],
    device: str = "auto",
) -> tuple[np.ndarray, int]:
    """Return (test predictions, parameter count)."""
    if target not in HEADS:
        raise ValueError(f"unknown target {target!r}; expected one of {HEADS}")
    head = HEADS.index(target)
    resolved = resolve_device(device, torch.cuda.is_available())
    announce_device(resolved)
    where = torch.device(resolved)
    seq_mean, seq_scale, scalar_mean, scalar_scale = _standardizer(
        seq_train, scalar_train
    )
    y = np.asarray(y_train, dtype=np.float64)
    y_mean, y_scale = float(y.mean()), float(y.std())
    if not y_scale > 0:
        y_scale = 1.0

    # Standardized float32 tensors, on the CPU.
    def tensors(
        seq: np.ndarray, scalar: np.ndarray
    ) -> tuple[torch.Tensor, torch.Tensor]:
        s = torch.as_tensor(
            ((seq.astype(np.float32, copy=False) - seq_mean) / seq_scale).astype(
                np.float32
            )
        )
        c = torch.as_tensor(
            ((scalar.astype(np.float32) - scalar_mean) / scalar_scale).astype(
                np.float32
            )
        )
        return s, c

    seq_t, scalar_t = tensors(seq_train, scalar_train)
    y_t = torch.as_tensor(((y - y_mean) / y_scale).astype(np.float32))
    model = model.to(where)
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(config["lr"]),
        weight_decay=float(config["weight_decay"]),
    )
    batch = int(config["batch"])
    n = len(y_t)
    generator = torch.Generator(device="cpu").manual_seed(int(config.get("seed", 0)))
    model.train()
    for _ in range(int(config["epochs"])):
        order = torch.randperm(n, generator=generator)
        for lo in range(0, n, batch):
            rows = order[lo : lo + batch]
            optimizer.zero_grad()
            out = model(seq_t[rows].to(where), scalar_t[rows].to(where))[:, head]
            loss = torch.mean((out - y_t[rows].to(where)) ** 2)
            loss.backward()
            optimizer.step()
    model.eval()
    seq_v, scalar_v = tensors(seq_test, scalar_test)
    predictions = []
    with torch.no_grad():
        for lo in range(0, len(seq_v), PREDICT_BATCH):
            out = model(
                seq_v[lo : lo + PREDICT_BATCH].to(where),
                scalar_v[lo : lo + PREDICT_BATCH].to(where),
            )
            predictions.append(out[:, head].cpu().numpy())
    predicted = np.concatenate(predictions) if predictions else np.zeros(0)
    return predicted.astype(np.float64) * y_scale + y_mean, parameter_count(model)
