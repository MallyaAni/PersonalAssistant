"""A frozen pretrained time-series encoder as the fourth model family of
the deep-intraday plan, stage 1 (added 2026-09-27): "chronos" in
`deep_intraday.walk_forward` is the ridge on the Chronos-Bolt encoder's
mean-pooled embedding of each row's bar-return channel, beside the three
scalars.

Why a frozen encoder and not fine-tuning. Stage 1 asks one question with
one fixed configuration per family and no search. A frozen encoder keeps
that: the pretrained weights are read once, the embedding of a row depends
on that row's 130 bar returns and nothing else, and the only fitted object
is the ridge on top, which walks forward exactly as the plain ridge does.
Fine-tuning would add a training loop, a learning rate and an epoch count
to choose, and a model whose weights change with the training window; it
is a stage-2 question if the frozen embedding shows anything. Because the
encoder fits nothing, computing the embedding once for the whole dataset
before the walk-forward cannot leak across the purge.

The pipeline. `BaseChronosPipeline.from_pretrained(model_id,
device_map=device, torch_dtype=bfloat16 on cuda else float32)`;
`pipeline.embed(context)` when the installed chronos-forecasting exposes
it (it returns `(embeddings, state)` with embeddings of shape (batch,
tokens, d)); otherwise the model's own `encode(context=...)`; a clear
error when neither exists. The (batch, tokens, d) output is mean-pooled
over the tokens to (batch, d). Rows go through in batches of
`batch_size`; nothing but the model is resident on the device. Weights
download from Hugging Face on first use.

The cache. `dataset_embedding` writes the (M, D) float32 array to
`<cache_dir>/embeddings_<model slug>_<fingerprint>.npy` with a sidecar
JSON (model id, rows, dimension, the encoder's parameter count), where
the fingerprint is the sha256 of the dataset's dates, tickers and
sequence shape, so a second run of the walk-forward on the same dataset
reads the file and a different dataset never reads a stale one. torch
and chronos are imported inside the functions that need them; the
fingerprint, the cache path and the feature join run without either.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.market.deep_intraday import (
    CHANNELS,
    CHRONOS_CONFIG,
    announce_device,
    resolve_device,
)

if TYPE_CHECKING:
    from backend.market.deep_intraday import Dataset

# The default checkpoint and batch, from the study's configuration.
DEFAULT_MODEL_ID = str(CHRONOS_CONFIG["model_id"])
DEFAULT_BATCH = int(CHRONOS_CONFIG["batch_size"])
# The sequence channel the encoder reads: the bar log return.
CHANNEL = CHANNELS.index(str(CHRONOS_CONFIG["channel"]))
# Hex digits of the fingerprint kept in the file name.
FINGERPRINT_DIGITS = 16


# The model id as a file-name stem: anything outside [A-Za-z0-9._-]
# becomes an underscore ("amazon/chronos-bolt-small" ->
# "amazon_chronos-bolt-small").
def model_slug(model_id: str) -> str:
    """Return the file-name-safe form of a Hugging Face model id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_id.strip()) or "model"


# The dataset fingerprint the cache is keyed on: sha256 over the session
# dates, the tickers and the sequence array's shape. Two datasets with the
# same rows in the same order share it; a different membership, window,
# ordering or sequence layout changes it.
def dataset_fingerprint(
    dates: np.ndarray, tickers: np.ndarray, shape: tuple[int, ...]
) -> str:
    """Return the hex fingerprint of (dates, tickers, shape)."""
    digest = hashlib.sha256()
    days = np.asarray(dates).astype("datetime64[D]").astype("int64")
    digest.update(days.tobytes())
    digest.update(b"\0")
    digest.update("\0".join(str(t) for t in np.asarray(tickers)).encode("utf-8"))
    digest.update(b"\0")
    digest.update(repr(tuple(int(n) for n in shape)).encode("ascii"))
    return digest.hexdigest()[:FINGERPRINT_DIGITS]


# Where the embedding of a dataset with `fingerprint` under `model_id`
# lives inside `cache_dir`.
def cache_path(cache_dir: Path, model_id: str, fingerprint: str) -> Path:
    """Return the .npy path of the cached embedding."""
    return Path(cache_dir) / f"embeddings_{model_slug(model_id)}_{fingerprint}.npy"


# The ridge's feature matrix for the chronos model: the embedding beside
# the scalars, float32 (the ridge standardizes every column itself).
def features(embedding: np.ndarray, x_scalar: np.ndarray) -> np.ndarray:
    """Return the (M, D + scalars) feature matrix."""
    embedding = np.asarray(embedding, dtype=np.float32)
    x_scalar = np.asarray(x_scalar, dtype=np.float32)
    if embedding.ndim != 2 or len(embedding) != len(x_scalar):
        raise ValueError(
            f"embedding {embedding.shape} does not match scalars {x_scalar.shape}"
        )
    return np.hstack([embedding, x_scalar])


# The number of parameters in the pipeline's encoder (the whole model when
# it has no separate encoder attribute).
def encoder_parameters(pipeline: Any) -> int:
    """Return the frozen encoder's parameter count."""
    model = pipeline.model
    encoder = getattr(model, "encoder", model)
    return int(sum(p.numel() for p in encoder.parameters()))


# Load the Chronos pipeline on `device` (bfloat16 on cuda, float32 on cpu).
def load_pipeline(model_id: str, device: str) -> Any:
    """Return the BaseChronosPipeline for `model_id` on the resolved device."""
    import torch
    from chronos import BaseChronosPipeline

    resolved = resolve_device(device, torch.cuda.is_available())
    announce_device(resolved)
    dtype = torch.bfloat16 if resolved == "cuda" else torch.float32
    return BaseChronosPipeline.from_pretrained(
        model_id, device_map=resolved, torch_dtype=dtype
    )


# One batch of contexts (B, steps) through the pipeline's encoder to
# (B, tokens, d): `pipeline.embed` where it exists, else the model's own
# `encode`; a clear error when neither is there.
def _encode(pipeline: Any, context: Any) -> Any:
    embed = getattr(pipeline, "embed", None)
    if callable(embed):
        out = embed(context)
        return out[0] if isinstance(out, tuple) else out
    model = getattr(pipeline, "model", None)
    encode = getattr(model, "encode", None)
    if callable(encode):
        out = encode(context=context.to(model.device))
        return out[0] if isinstance(out, tuple) else out
    raise RuntimeError(
        "the installed chronos pipeline exposes neither .embed(context) nor"
        " .model.encode(context=); cannot take encoder embeddings from it"
    )


# The (M, D) mean-pooled encoder embedding of every row's bar-return
# channel, `batch_size` rows at a time. `pipeline` is loaded when not
# given. Returns the embedding as float32.
def embed(
    x_seq: np.ndarray,
    device: str = "auto",
    batch_size: int = DEFAULT_BATCH,
    model_id: str = DEFAULT_MODEL_ID,
    pipeline: Any | None = None,
) -> np.ndarray:
    """Return the (M, D) embedding of `x_seq[:, :, CHANNEL]`."""
    import torch

    if pipeline is None:
        pipeline = load_pipeline(model_id, device)
    x_seq = np.asarray(x_seq)
    if x_seq.ndim != 3:
        raise ValueError(f"x_seq must be (M, steps, channels), got {x_seq.shape}")
    context = torch.as_tensor(
        np.ascontiguousarray(x_seq[:, :, CHANNEL], dtype=np.float32)
    )
    parts: list[np.ndarray] = []
    with torch.no_grad():
        for lo in range(0, len(context), max(1, int(batch_size))):
            tokens = _encode(pipeline, context[lo : lo + batch_size])
            pooled = tokens.float().mean(dim=1)
            parts.append(pooled.cpu().numpy().astype(np.float32))
    if not parts:
        return np.zeros((0, 0), dtype=np.float32)
    return np.concatenate(parts, axis=0)


# The dataset's embedding, from the cache under `cache_dir` when a file
# for this dataset and model is there, else computed and (when `cache_dir`
# is given) written with its sidecar. Returns (embedding, info) where info
# carries the model id, the fingerprint, the path, whether it was read
# from the cache and the encoder's parameter count (None when the sidecar
# of an older cache lacks it).
def dataset_embedding(
    ds: Dataset,
    device: str = "auto",
    cache_dir: Path | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    batch_size: int = DEFAULT_BATCH,
    log: Callable[[str], None] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (the (M, D) float32 embedding, an info record)."""
    fingerprint = dataset_fingerprint(ds.dates, ds.tickers, ds.x_seq.shape)
    info: dict[str, Any] = {
        "model_id": model_id,
        "fingerprint": fingerprint,
        "path": None,
        "cached": False,
        "parameters": None,
        "rows": len(ds),
        "dim": None,
    }
    path = cache_path(cache_dir, model_id, fingerprint) if cache_dir else None
    sidecar = path.with_suffix(".json") if path else None
    if path is not None and path.exists():
        embedding = np.load(path)
        if embedding.ndim == 2 and len(embedding) == len(ds):
            info.update(path=str(path), cached=True, dim=int(embedding.shape[1]))
            if sidecar is not None and sidecar.exists():
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                info["parameters"] = meta.get("parameters")
            if log is not None:
                log(f"  chronos: embedding {embedding.shape} read from {path}")
            return embedding.astype(np.float32, copy=False), info
    pipeline = load_pipeline(model_id, device)
    info["parameters"] = encoder_parameters(pipeline)
    if log is not None:
        log(
            f"  chronos: embedding {len(ds):,} rows with {model_id}"
            f" ({info['parameters']:,} encoder parameters, batch {batch_size})"
        )
    embedding = embed(ds.x_seq, device, batch_size, model_id, pipeline=pipeline)
    info["dim"] = int(embedding.shape[1]) if embedding.ndim == 2 else None
    if path is not None and sidecar is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, embedding)
        sidecar.write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "fingerprint": fingerprint,
                    "rows": int(len(embedding)),
                    "dim": info["dim"],
                    "parameters": info["parameters"],
                    "channel": str(CHRONOS_CONFIG["channel"]),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        info["path"] = str(path)
        if log is not None:
            log(f"  chronos: embedding written to {path}")
    return embedding, info
