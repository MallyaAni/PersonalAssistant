"""The point-in-time embedder: the checkpoint rule and the pooling.

The checkpoint chosen for a release must have a cutoff strictly before
its reaction date, a release before the first cutoff gets none, and the
pooled vector must be the mean of the attended token vectors, batched in
order, whatever the batch size. No weights, no GPU, no network: the model
is a fake handed in through the loader.
"""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import chrono_embed


# The boundaries of the date rule.
@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (date(2014, 12, 31), None),  # not strictly after the first cutoff
        (date(2015, 1, 1), "chrono-bert-v1-20141231"),
        (date(2015, 12, 31), "chrono-bert-v1-20141231"),
        (date(2016, 1, 1), "chrono-bert-v1-20151231"),
        (date(2024, 12, 31), "chrono-bert-v1-20231231"),
        (date(2025, 1, 1), "chrono-bert-v1-20241231"),
        (date(2026, 9, 29), "chrono-bert-v1-20241231"),  # the newest there is
        (date(2010, 6, 1), None),
    ],
)
def test_checkpoint_for(when, expected):
    assert chrono_embed.checkpoint_for(when) == expected


# The checkpoint names cover 2014..2024, one per year.
def test_checkpoint_names():
    assert chrono_embed.checkpoint_name(2019) == "chrono-bert-v1-20191231"
    assert len(chrono_embed.CHECKPOINT_YEARS) == 11
    assert chrono_embed.cutoff(2014) == date(2014, 12, 31)


# Mean pooling averages only the attended tokens and never divides by zero.
def test_mean_pool_uses_the_mask():
    hidden = np.array(
        [
            [[1.0, 2.0], [3.0, 4.0], [100.0, 100.0]],
            [[5.0, 6.0], [7.0, 8.0], [9.0, 10.0]],
            [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]],
        ]
    )
    mask = np.array([[1, 1, 0], [1, 1, 1], [0, 0, 0]])
    pooled = chrono_embed.mean_pool(hidden, mask)
    assert pooled.dtype == np.float32
    np.testing.assert_allclose(pooled[0], [2.0, 3.0])
    np.testing.assert_allclose(pooled[1], [7.0, 8.0])
    np.testing.assert_allclose(pooled[2], [0.0, 0.0])


# A fake tokenizer and encoder: each text becomes as many tokens as it
# has words, padded to the batch's longest, and the encoder's hidden
# state is the token's position times a constant per text, so the pooled
# value is checkable by hand and depends on the padding being masked.
class _Tokenizer:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, texts, **kwargs):
        self.calls.append(kwargs)
        lengths = [min(len(t.split()), kwargs["max_length"]) for t in texts]
        width = max(lengths)
        ids = np.zeros((len(texts), width), dtype=np.int64)
        mask = np.zeros((len(texts), width), dtype=np.int64)
        for i, n in enumerate(lengths):
            ids[i, :n] = np.arange(1, n + 1)
            mask[i, :n] = 1
        return {"input_ids": _Tensor(ids), "attention_mask": _Tensor(mask)}


class _Tensor:
    def __init__(self, array):
        self.array = np.asarray(array)

    def to(self, device):
        return self

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


class _Model:
    def __call__(self, input_ids, attention_mask):
        ids = input_ids.array.astype(np.float32)
        # hidden width 2: (position, 10 * position), zero on padding
        hidden = np.stack([ids, 10.0 * ids], axis=-1)
        return SimpleNamespace(last_hidden_state=_Tensor(hidden))


# Texts are embedded in order, across batches, with padding excluded from
# the mean; the loader is called once with the checkpoint and device.
def test_embed_texts_batches_in_order_and_masks_padding():
    tokenizer = _Tokenizer()
    loads: list[tuple[str, str]] = []

    def loader(model_dir, device):
        loads.append((model_dir, device))
        return tokenizer, _Model()

    texts = ["a b c", "a", "a b c d e", "a b", "a b c"]
    out = chrono_embed.embed_texts(
        texts, "/models/chrono-bert-v1-20191231", "cpu", batch=2, loader=loader
    )
    assert loads == [("/models/chrono-bert-v1-20191231", "cpu")]
    assert out.shape == (5, 2)
    assert out.dtype == np.float32
    # mean of positions 1..n is (n + 1) / 2
    np.testing.assert_allclose(out[:, 0], [2.0, 1.0, 3.0, 1.5, 2.0])
    np.testing.assert_allclose(out[:, 1], [20.0, 10.0, 30.0, 15.0, 20.0])
    assert len(tokenizer.calls) == 3
    assert all(c["max_length"] == chrono_embed.MAX_TOKENS for c in tokenizer.calls)
    assert all(c["truncation"] is True for c in tokenizer.calls)


# The token cap reaches the tokenizer, and an empty input needs no model.
def test_max_tokens_and_empty_input():
    tokenizer = _Tokenizer()
    out = chrono_embed.embed_texts(
        ["one two three four"],
        "m",
        "cpu",
        max_tokens=2,
        loader=lambda d, v: (tokenizer, _Model()),
    )
    np.testing.assert_allclose(out[0], [1.5, 15.0])
    empty = chrono_embed.embed_texts(
        [], "m", "cpu", loader=lambda d, v: pytest.fail("no load for no texts")
    )
    assert empty.shape == (0, 0)
