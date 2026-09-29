"""The torch families of the deep stage-2 plan: stage 1's temporal CNN and
PatchTST with one head per target trained jointly, and the masked-patch
pretraining of the PatchTST encoder read out by a linear probe.

Imported by `deep_stage2.walk_forward` only when a torch model is asked
for, so the rest of the study runs where torch is absent. The networks
are stage 1's (`deep_intraday_cnn.TemporalCNN`,
`deep_intraday_patchtst.PatchTST`) built for the longer, wider sequence
with their two-way head replaced by a `len(targets)`-way one; nothing
else in the architectures changes. Training is stage 1's configuration
(Adam, 20 epochs, batch 512, dropout 0.1, weight decay 1e-4) through a
loop that differs from `deep_intraday_cnn.train_predict` in one respect:
the loss is the sum over heads of that head's loss on the rows where its
target is defined - MSE on a standardized continuous target, binary
cross-entropy on a 0/1 target - so the four heads train together on the
same rows and a row with an undefined horizon target still teaches the
other heads. Inputs are standardized on the training rows (stage 1's
`_standardizer`), the standardized arrays stay on the CPU and each batch
is moved to the device as it is used.

Pretraining (`pretrain_embed`). The PatchTST encoder is trained for a
fixed number of epochs on the fold's training rows to reconstruct patches
hidden from it: each (row, channel, patch) is masked independently with
probability `mask_ratio`, the masked patch's embedding is replaced by a
learned mask token before the positional embedding is added, the encoder
output at every masked position is read by a linear head back to the
`patch` standardized bar values and the loss is the MSE over the masked
positions only. The encoder is then frozen and every row - training and
test - is embedded once (mean over patches, then over channels, as the
stage-1 forward pass pools); `deep_stage2` fits its ridge on
[embedding, scalars] per target. Only the fold's training rows enter the
reconstruction loss, so the purge holds for the encoder as for the
heads. The parameter count reported is the encoder's (embedding,
position, encoder layers) plus the pretraining-only mask token and
reconstruction head.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import torch
from torch import nn

from backend.market.deep_intraday import MIN_NAMES, announce_device, resolve_device
from backend.market.deep_intraday_cnn import (
    TemporalCNN,
    _standardizer,
    parameter_count,
)
from backend.market.deep_intraday_patchtst import PatchTST
from backend.market.deep_intraday_patchtst import build as build_patchtst

# Rows per prediction or embedding batch.
PREDICT_BATCH = 1024
# The loss kinds a head may train with.
KINDS = ("mse", "bce")


# Build stage 1's network for `family` ("cnn", "patchtst" or
# "patchtst-pretrained") on a `seq_len`-step sequence of `in_channels`
# channels with `scalars` side inputs, its head replaced by a
# `heads`-way linear layer.
def build_network(
    family: str,
    in_channels: int,
    scalars: int,
    seq_len: int,
    config: Mapping[str, Any],
    heads: int,
) -> nn.Module:
    """Return the untrained multi-head network."""
    if family == "cnn":
        model: nn.Module = TemporalCNN(
            in_channels=in_channels,
            scalars=scalars,
            channels=int(config["channels"]),
            kernel=int(config["kernel"]),
            dilations=tuple(int(d) for d in config["dilations"]),
            dropout=float(config["dropout"]),
            hidden=int(config.get("hidden", 32)),
        )
    elif family in ("patchtst", "patchtst-pretrained"):
        model = build_patchtst(in_channels, scalars, seq_len, config)
    else:
        raise ValueError(f"unknown family {family!r}")
    model.heads = nn.Linear(model.heads.in_features, heads)
    return model


# Standardized float32 tensors of a sequence and its scalars, on the CPU.
def _tensors(
    seq: np.ndarray,
    scalar: np.ndarray,
    stats: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> tuple[torch.Tensor, torch.Tensor]:
    seq_mean, seq_scale, scalar_mean, scalar_scale = stats
    s = torch.as_tensor(
        ((seq.astype(np.float32, copy=False) - seq_mean) / seq_scale).astype(np.float32)
    )
    c = torch.as_tensor(
        ((scalar.astype(np.float32) - scalar_mean) / scalar_scale).astype(np.float32)
    )
    return s, c


# Centre and scale of each continuous head's target over its defined
# rows (0 and 1 for a bce head): (H,), (H,).
def _target_scaling(
    y: np.ndarray, kinds: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray]:
    means = np.zeros(y.shape[1])
    scales = np.ones(y.shape[1])
    for h, kind in enumerate(kinds):
        if kind != "mse":
            continue
        column = y[:, h][np.isfinite(y[:, h])]
        if len(column):
            means[h] = float(column.mean())
            scale = float(column.std())
            scales[h] = scale if scale > 0 else 1.0
    return means, scales


# The multi-head loss: for each head, its loss over the batch rows where
# the target is finite, summed over the heads that have any such row.
def _loss(out: torch.Tensor, y: torch.Tensor, kinds: tuple[str, ...]) -> torch.Tensor:
    total = out.new_zeros(())
    for h, kind in enumerate(kinds):
        ok = torch.isfinite(y[:, h])
        if not bool(ok.any()):
            continue
        prediction, target = out[ok, h], y[ok, h]
        if kind == "bce":
            total = total + nn.functional.binary_cross_entropy_with_logits(
                prediction, target
            )
        else:
            total = total + torch.mean((prediction - target) ** 2)
    return total


# Train the multi-head network of `family` on the training rows for the
# targets `y_train` (n, H) with loss kinds `kinds` (H,) under the fixed
# configuration and return (the (m, H) test predictions - probabilities
# for a bce head, the target's scale for an mse head - and the parameter
# count). Heads below the existing minimum observed-label count stay NaN.
# `device` is "auto", "cpu" or "cuda".
def fit_predict(
    family: str,
    seq_train: np.ndarray,
    scalar_train: np.ndarray,
    y_train: np.ndarray,
    kinds: tuple[str, ...],
    seq_test: np.ndarray,
    scalar_test: np.ndarray,
    config: Mapping[str, Any],
    device: str = "auto",
) -> tuple[np.ndarray, int]:
    """Return (test predictions (m, H), parameter count)."""
    y_train = np.asarray(y_train, dtype=np.float64)
    if y_train.ndim != 2 or len(kinds) != y_train.shape[1]:
        raise ValueError("y_train must be (n, H) with one loss kind per head")
    for kind in kinds:
        if kind not in KINDS:
            raise ValueError(f"unknown loss kind {kind!r}; expected one of {KINDS}")
    torch.manual_seed(int(config.get("seed", 0)))
    model = build_network(
        family,
        seq_train.shape[-1],
        scalar_train.shape[-1],
        seq_train.shape[1],
        config,
        len(kinds),
    )
    resolved = resolve_device(device, torch.cuda.is_available())
    announce_device(resolved)
    where = torch.device(resolved)
    stats = _standardizer(seq_train, scalar_train)
    means, scales = _target_scaling(y_train, kinds)
    seq_t, scalar_t = _tensors(seq_train, scalar_train, stats)
    y_t = torch.as_tensor(((y_train - means) / scales).astype(np.float32))
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
            out = model(seq_t[rows].to(where), scalar_t[rows].to(where))
            loss = _loss(out, y_t[rows].to(where), kinds)
            if loss.requires_grad:
                loss.backward()
                optimizer.step()
    model.eval()
    predicted = _predict(model, seq_test, scalar_test, stats, where)
    for h, kind in enumerate(kinds):
        if kind == "bce":
            predicted[:, h] = 1.0 / (1.0 + np.exp(-predicted[:, h]))
        else:
            predicted[:, h] = predicted[:, h] * scales[h] + means[h]
    # Other supervised heads can train shared layers without teaching this output.
    predicted[:, np.isfinite(y_train).sum(axis=0) < MIN_NAMES] = np.nan
    return predicted, parameter_count(model)


# The network's raw (m, H) outputs on the test rows, batch by batch.
def _predict(
    model: nn.Module,
    seq: np.ndarray,
    scalar: np.ndarray,
    stats: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    where: torch.device,
) -> np.ndarray:
    seq_v, scalar_v = _tensors(seq, scalar, stats)
    heads = model.heads.out_features
    out = np.zeros((len(seq_v), heads))
    with torch.no_grad():
        for lo in range(0, len(seq_v), PREDICT_BATCH):
            chunk = model(
                seq_v[lo : lo + PREDICT_BATCH].to(where),
                scalar_v[lo : lo + PREDICT_BATCH].to(where),
            )
            out[lo : lo + PREDICT_BATCH] = chunk.cpu().numpy().astype(np.float64)
    return out


class MaskedPatchHead(nn.Module):  # type: ignore[misc]  # torch is untyped here
    """The pretraining-only parameters: a mask token and a reconstruction head."""

    # Build for the encoder's `d_model` and the `patch` length reconstructed.
    def __init__(self, d_model: int, patch: int) -> None:
        super().__init__()
        self.mask_token = nn.Parameter(torch.zeros(d_model))
        nn.init.normal_(self.mask_token, std=0.02)
        self.reconstruct = nn.Linear(d_model, patch)


# The (B * C, patches, patch) patch tensor of a (B, steps, C) sequence.
def _patches(model: PatchTST, seq: torch.Tensor) -> torch.Tensor:
    b, _, c = seq.shape
    return seq.transpose(1, 2).reshape(b * c, model.n_patches, model.patch)


# The encoder's (B * C, patches, d_model) output for the patches, with the
# masked positions' embeddings replaced by the mask token when `mask` is
# given (a (B * C, patches) Boolean tensor).
def _encode(
    model: PatchTST,
    patches: torch.Tensor,
    mask: torch.Tensor | None = None,
    head: MaskedPatchHead | None = None,
) -> torch.Tensor:
    x = model.embed(patches)
    if mask is not None and head is not None:
        x = torch.where(mask.unsqueeze(-1), head.mask_token.to(x.dtype), x)
    return model.encoder(x + model.position)


# Pretrain the PatchTST encoder by masked-patch reconstruction on the
# standardized training sequences for the fixed epochs, in place. Returns
# (the mean reconstruction loss of the last epoch, the pretraining head).
def pretrain(
    model: PatchTST,
    seq_t: torch.Tensor,
    config: Mapping[str, Any],
    pretrain_config: Mapping[str, Any],
    where: torch.device,
) -> tuple[float, MaskedPatchHead]:
    """Pretrain `model`'s encoder; return (last epoch's mean loss, the head)."""
    head = MaskedPatchHead(model.d_model, model.patch).to(where)
    optimizer = torch.optim.Adam(
        [
            *model.embed.parameters(),
            model.position,
            *model.encoder.parameters(),
            *head.parameters(),
        ],
        lr=float(config["lr"]),
        weight_decay=float(config["weight_decay"]),
    )
    batch = int(config["batch"])
    ratio = float(pretrain_config["mask_ratio"])
    n = len(seq_t)
    generator = torch.Generator(device="cpu").manual_seed(
        int(pretrain_config.get("seed", 0))
    )
    model.train()
    head.train()
    last = float("nan")
    for _ in range(int(pretrain_config["epochs"])):
        order = torch.randperm(n, generator=generator)
        total, count = 0.0, 0
        for lo in range(0, n, batch):
            rows = order[lo : lo + batch]
            patches = _patches(model, seq_t[rows].to(where))
            mask = torch.rand(patches.shape[:2], generator=generator) < ratio
            mask = mask.to(where)
            if not bool(mask.any()):
                continue
            optimizer.zero_grad()
            z = _encode(model, patches, mask, head)
            reconstructed = head.reconstruct(z[mask])
            loss = torch.mean((reconstructed - patches[mask]) ** 2)
            loss.backward()
            optimizer.step()
            total += float(loss.detach().cpu()) * int(mask.sum())
            count += int(mask.sum())
        last = total / count if count else float("nan")
    model.eval()
    head.eval()
    return last, head


# The frozen encoder's (n, d_model) embedding of the sequences: the
# encoder output mean-pooled over patches, then over channels.
def embed(model: PatchTST, seq_t: torch.Tensor, where: torch.device) -> np.ndarray:
    """Return the (n, d_model) embeddings, float32."""
    out = np.zeros((len(seq_t), model.d_model), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for lo in range(0, len(seq_t), PREDICT_BATCH):
            chunk = seq_t[lo : lo + PREDICT_BATCH].to(where)
            b, _, c = chunk.shape
            z = _encode(model, _patches(model, chunk))
            pooled = z.mean(dim=1).reshape(b, c, model.d_model).mean(dim=1)
            out[lo : lo + PREDICT_BATCH] = pooled.cpu().numpy()
    return out


# Pretrain the encoder on the training rows, then embed the training and
# test rows with it frozen. Returns (train embedding, test embedding, the
# parameter count of the encoder plus the pretraining head). The scalars
# are used only to standardize alongside the sequence (stage 1's
# standardizer takes both); they are not embedded.
def pretrain_embed(
    seq_train: np.ndarray,
    scalar_train: np.ndarray,
    seq_test: np.ndarray,
    scalar_test: np.ndarray,
    config: Mapping[str, Any],
    pretrain_config: Mapping[str, Any],
    device: str = "auto",
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (embedding of the training rows, of the test rows, parameters)."""
    torch.manual_seed(int(config.get("seed", 0)))
    model = build_patchtst(
        seq_train.shape[-1], scalar_train.shape[-1], seq_train.shape[1], config
    )
    resolved = resolve_device(device, torch.cuda.is_available())
    announce_device(resolved)
    where = torch.device(resolved)
    stats = _standardizer(seq_train, scalar_train)
    seq_t, _ = _tensors(seq_train, scalar_train, stats)
    model = model.to(where)
    _, head = pretrain(model, seq_t, config, pretrain_config, where)
    parameters = (
        parameter_count(model.embed)
        + int(model.position.numel())
        + parameter_count(model.encoder)
        + parameter_count(head)
    )
    emb_train = embed(model, seq_t, where)
    seq_v, _ = _tensors(seq_test, scalar_test, stats)
    emb_test = embed(model, seq_v, where)
    return emb_train, emb_test, parameters
