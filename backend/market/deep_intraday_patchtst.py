"""The PatchTST encoder of the deep-intraday plan, stage 1 (added
2026-09-27 as a third model family beside the ridge and the CNN).

Imported by `deep_intraday.walk_forward` only when "patchtst" is asked
for, so the rest of the study runs where torch is absent. The architecture
follows Nie et al. (2023), "A Time Series is Worth 64 Words": the
`K * 26 = 130`-step sequence is cut into non-overlapping patches of
`patch = 13` steps (ten patches per channel), each channel is encoded
independently with the same weights (channel independence, as in the
paper), each patch is embedded linearly to `d_model = 64`, a learnable
positional embedding is added, two transformer encoder layers (4 heads,
feed-forward 128, dropout 0.1) mix the patches, the encoder output is
mean-pooled over patches and then over channels, the three scalars are
concatenated, one hidden layer of 32 units and the same two heads (rank,
volatility) as the CNN. Training is the CNN's fixed configuration
(`deep_intraday.PATCHTST_CONFIG`: Adam 1e-3, 20 epochs, batch 512, weight
decay 1e-4, MSE on the selected head) through the shared loop
`deep_intraday_cnn.train_predict`, so the two families differ only in the
network. `fit_predict` has the CNN's signature.

Size. By hand, with the configuration as written: the patch embedding
13 x 64 + 64 = 896, the positional embedding 10 x 64 = 640, each encoder
layer 33,472 (attention in-projection 12,480, out-projection 4,160,
feed-forward 8,320 + 8,256, two layer norms 256), so 66,944 for two, the
hidden layer (64 + 3) x 32 + 32 = 2,176 and the heads 66: 70,722 in all.
The payload reports the count as built (`parameters.patchtst`); the hand
count is UNVERIFIED until torch runs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import torch
from torch import nn

from backend.market.deep_intraday_cnn import HEADS, train_predict


class PatchTST(nn.Module):  # type: ignore[misc]  # torch is untyped here
    """Channel-independent patch transformer over the bar sequence, two heads."""

    # Build the network for a `seq_len`-step sequence of `in_channels`
    # channels cut into `patch`-step patches, with `scalars` side inputs.
    def __init__(
        self,
        in_channels: int,
        scalars: int,
        seq_len: int,
        patch: int = 13,
        d_model: int = 64,
        heads: int = 4,
        layers: int = 2,
        ff: int = 128,
        dropout: float = 0.1,
        hidden: int = 32,
    ) -> None:
        super().__init__()
        if patch <= 0 or seq_len % patch != 0:
            raise ValueError(
                f"sequence length {seq_len} is not a multiple of the patch {patch}"
            )
        self.in_channels = in_channels
        self.patch = patch
        self.n_patches = seq_len // patch
        self.d_model = d_model
        self.embed = nn.Linear(patch, d_model)
        self.position = nn.Parameter(torch.empty(1, self.n_patches, d_model))
        nn.init.normal_(self.position, std=0.02)
        layer = nn.TransformerEncoderLayer(
            d_model,
            heads,
            dim_feedforward=ff,
            dropout=dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, layers)
        self.hidden = nn.Sequential(
            nn.Linear(d_model + scalars, hidden), nn.ReLU(), nn.Dropout(dropout)
        )
        self.heads = nn.Linear(hidden, len(HEADS))

    # Forward pass: `seq` is (B, steps, channels), `scalar` is (B, scalars);
    # returns (B, 2) with the rank head first and the volatility head
    # second. Every channel goes through the encoder as its own series.
    def forward(self, seq: torch.Tensor, scalar: torch.Tensor) -> torch.Tensor:
        """Return the (B, 2) head outputs."""
        b, _, c = seq.shape
        # (B, C, steps) -> (B * C, patches, patch): channel independence.
        patches = seq.transpose(1, 2).reshape(b * c, self.n_patches, self.patch)
        x = self.embed(patches) + self.position
        x = self.encoder(x)  # (B * C, patches, d_model)
        pooled = x.mean(dim=1).reshape(b, c, self.d_model).mean(dim=1)  # (B, d)
        joined = torch.cat([pooled, scalar], dim=1)
        return self.heads(self.hidden(joined))


# Build the PatchTST the configuration describes for the given input shape.
def build(
    in_channels: int, scalars: int, seq_len: int, config: Mapping[str, Any]
) -> PatchTST:
    """Return an untrained PatchTST for the configuration."""
    return PatchTST(
        in_channels=in_channels,
        scalars=scalars,
        seq_len=seq_len,
        patch=int(config["patch"]),
        d_model=int(config["d_model"]),
        heads=int(config["heads"]),
        layers=int(config["layers"]),
        ff=int(config["ff"]),
        dropout=float(config["dropout"]),
        hidden=int(config.get("hidden", 32)),
    )


# Fit the PatchTST on the training rows for `target` ("rank" or "vol")
# with the fixed configuration and return (predictions on the test rows,
# the parameter count); the CNN's signature, the CNN's training loop.
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
    model = build(
        seq_train.shape[-1], scalar_train.shape[-1], seq_train.shape[1], config
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
