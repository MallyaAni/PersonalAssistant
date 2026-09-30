"""Point-in-time text embeddings with ChronoBERT.

ChronoBERT (`manelalab/chrono-bert-v1-<YYYY>1231`) is a family of
ModernBERT-style encoders, one per year, each trained only on text written
up to the last day of that year. Embedding a release with the newest
checkpoint whose cutoff precedes the release's reaction date gives a
vector from a model that has never seen the release, the company's later
history, or anything written after it. That is the look-ahead-free arm
of the tone-validity study: it needs no masking to be honest, so it is
the arbiter when a masked re-read is in doubt.

Two pieces. `checkpoint_for` is the date rule, pure and tested at its
boundaries. `embed_texts` runs the encoder from a local directory, in
batches, at up to 8,192 tokens, mean-pooling the last hidden state over
the attention mask into one vector per text. Loading is behind a function
so tests can hand in a fake model and check the pooling arithmetic
without weights, a GPU or a network.
"""

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import numpy as np

FIRST_YEAR = 2014
LAST_YEAR = 2024
CHECKPOINT_YEARS: tuple[int, ...] = tuple(range(FIRST_YEAR, LAST_YEAR + 1))
MAX_TOKENS = 8192
BATCH = 4


# The directory name of the checkpoint whose training text ends on
# December 31 of `year`.
def checkpoint_name(year: int) -> str:
    """Return the ChronoBERT checkpoint name for a cutoff year."""
    return f"chrono-bert-v1-{year}1231"


# The last day the checkpoint's training text may carry.
def cutoff(year: int) -> date:
    """Return the checkpoint's cutoff date, December 31 of `year`."""
    return date(year, 12, 31)


# The newest checkpoint whose cutoff is strictly before the reaction date,
# or None for a release the earliest checkpoint could have read.
def checkpoint_for(reaction_date: date) -> str | None:
    """Return the checkpoint name to embed a release dated `reaction_date`."""
    eligible = [y for y in CHECKPOINT_YEARS if cutoff(y) < reaction_date]
    if not eligible:
        return None
    return checkpoint_name(max(eligible))


# Mean of the token vectors where the attention mask is on; a text with
# no attended token (never, after tokenisation) gets zeros, not NaN.
def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return (batch, hidden) means of `hidden` (batch, tokens, hidden) under `mask`."""
    weights = np.asarray(mask, dtype=np.float32)[:, :, None]
    summed = (np.asarray(hidden, dtype=np.float32) * weights).sum(axis=1)
    counts = np.maximum(weights.sum(axis=1), 1.0)
    return (summed / counts).astype(np.float32)


# A tensor or an array as a float32 numpy array on the host.
def to_numpy(value: Any) -> np.ndarray:
    """Return `value` as a float32 numpy array, whatever framework made it."""
    if isinstance(value, np.ndarray):
        return value.astype(np.float32)
    return value.detach().float().cpu().numpy().astype(np.float32)


# Load the tokenizer and encoder from a local checkpoint directory. The
# encoder is ModernBERT-style, which a transformers old enough not to
# know it can only load with the model's own code; either way nothing is
# fetched, and a missing class is reported as such rather than as a
# stack trace from inside the library.
def load_model(model_dir: str, device: str) -> tuple[Any, Any]:
    """Return (tokenizer, model) from `model_dir`, on `device`, eval mode."""
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - the RTX has them
        raise RuntimeError(
            "chrono_embed needs transformers and torch; run it on the RTX"
        ) from exc
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        model = AutoModel.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=True
        )
    except (ValueError, KeyError, OSError, ImportError) as exc:
        raise RuntimeError(
            f"cannot load {model_dir}: {exc}; ChronoBERT is a ModernBERT "
            "encoder and needs transformers >= 4.48 or the checkpoint's own "
            "modelling code beside its weights"
        ) from exc
    model = model.to(device)
    if device.startswith("cuda"):
        model = model.half()
    model.eval()
    return tokenizer, model


# Encode one batch: tokenise to at most `max_tokens`, run the encoder
# without gradients, and pool.
def encode_batch(
    tokenizer: Any, model: Any, texts: Sequence[str], device: str, max_tokens: int
) -> np.ndarray:
    """Return (len(texts), hidden) pooled vectors for one batch."""
    encoded = tokenizer(
        list(texts),
        padding=True,
        truncation=True,
        max_length=max_tokens,
        return_tensors="pt",
    )
    encoded = {k: v.to(device) for k, v in encoded.items()}
    outputs = _forward(model, encoded)
    hidden = to_numpy(outputs.last_hidden_state)
    return mean_pool(hidden, to_numpy(encoded["attention_mask"]))


# The forward pass under no_grad when torch is present; a fake model in a
# test has no torch to switch off.
def _forward(model: Any, encoded: dict[str, Any]) -> Any:
    try:
        import torch
    except ImportError:  # pragma: no cover - tests without torch
        return model(**encoded)
    with torch.no_grad():
        return model(**encoded)


# Embed every text with the checkpoint at `model_dir`, in order, in
# batches. `loader` is swapped for a fake in tests.
def embed_texts(
    texts: Sequence[str],
    model_dir: str,
    device: str,
    max_tokens: int = MAX_TOKENS,
    batch: int = BATCH,
    loader: Callable[[str, str], tuple[Any, Any]] = load_model,
) -> np.ndarray:
    """Return (len(texts), hidden) float32 mean-pooled embeddings."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    tokenizer, model = loader(model_dir, device)
    parts = [
        encode_batch(tokenizer, model, texts[i : i + batch], device, max_tokens)
        for i in range(0, len(texts), batch)
    ]
    return np.concatenate(parts, axis=0).astype(np.float32)
