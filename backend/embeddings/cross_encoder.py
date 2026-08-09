"""A cross-encoder, for the question an embedding cannot answer well.

An embedding turns a query and a document into vectors separately and compares
them afterwards, so nothing ever reads the two together. That is what makes it
cheap enough to run over every candidate, and it is also why its scores cluster:
measured over real Scout candidates, a genuine concert scored 0.612 against
"Concerts" while a lantern festival scored 0.616 against "Line Dancing" — the
wrong match scored higher than the right one. `MIN_ATTRIBUTION_MARGIN` in
`relevance.py` exists because of that clustering.

A cross-encoder reads the pair in one forward pass, so the words of the query
can attend to the words of the document. It cannot be precomputed and it costs
one pass per pair, which is exactly why it belongs at the end of a cascade:
embeddings pick a shortlist out of everything, this reorders the shortlist.

**It runs on CPU, in-process, on purpose.** The card is already fully committed —
the generation model claims most of it and lends it to ComfyUI through sleep
mode — so a third resident GPU service would have to take VRAM from the model
answering people. This one is 22M parameters scoring a couple of hundred short
pairs once a week; CPU is the right place for it, and it keeps working while the
GPU is lent away. `NomicVisionEmbeddingProvider` established this shape and this
follows it: weights load lazily, and a missing file disables the provider rather
than failing startup.
"""

import threading
from pathlib import Path
from typing import Any

import numpy as np

from backend.core.interfaces import RerankProvider

# How much of a pair the model reads. A cross-encoder truncates rather than
# failing, so this bounds cost rather than correctness: an event's name, place
# and first sentence carry the signal, and the rest is a page's boilerplate.
MAX_PAIR_TOKENS = 256

# How many pairs go through one forward pass. Padding is per batch, so a large
# batch pads every short pair up to the longest one in it and wastes the saving.
BATCH_SIZE = 16


class OnnxCrossEncoder(RerankProvider):
    """Score query/document pairs with a local ONNX cross-encoder on CPU."""

    # Configure local weights and tokenizer; absence of either disables scoring.
    def __init__(
        self,
        model_path: str,
        tokenizer_path: str,
        max_tokens: int = MAX_PAIR_TOKENS,
        intra_op_threads: int = 1,
    ) -> None:
        self.model_path = Path(model_path)
        self.tokenizer_path = Path(tokenizer_path)
        self.max_tokens = max_tokens
        self.intra_op_threads = intra_op_threads
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._input_names: tuple[str, ...] = ()
        self._lock = threading.Lock()

    # Reranking is skipped entirely when the local files are not present, which
    # is what lets a deployment run without them and rank on embeddings alone.
    def is_enabled(self) -> bool:
        return self.model_path.is_file() and self.tokenizer_path.is_file()

    # Load the session and tokenizer once, under a lock, on first use.
    def _ensure_loaded(self) -> tuple[Any, Any]:
        if self._session is not None and self._tokenizer is not None:
            return self._session, self._tokenizer
        with self._lock:
            if self._session is None or self._tokenizer is None:
                import onnxruntime
                from tokenizers import Tokenizer

                options = onnxruntime.SessionOptions()
                options.intra_op_num_threads = self.intra_op_threads
                session = onnxruntime.InferenceSession(
                    str(self.model_path),
                    sess_options=options,
                    providers=["CPUExecutionProvider"],
                )
                tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
                # Truncation and padding belong to the tokenizer rather than to
                # hand-written slicing: a pair truncated at the wrong end loses
                # the document instead of its tail.
                tokenizer.enable_truncation(self.max_tokens)
                tokenizer.enable_padding()
                self._input_names = tuple(item.name for item in session.get_inputs())
                self._session = session
                self._tokenizer = tokenizer
        return self._session, self._tokenizer

    # Score pairs, higher meaning more relevant, preserving the caller's order.
    #
    # Returns the model's raw logit, deliberately, after measuring the
    # alternative. A sigmoid looks friendlier — a probability in 0..1 that reads
    # the same for every checkpoint — and it destroys the signal, because these
    # logits sit far out in the tail where the curve is flat. Measured over the
    # candidates in `relevance.py`'s recorded table, squashed scores put the
    # gap between a correct attribution and a wrong one at 0.000 versus 0.001;
    # the same pairs in logit space separate 0.29 from 1.49. Log-odds is where
    # the difference lives, so log-odds is what callers get.
    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        if not self.is_enabled():
            raise RuntimeError(
                "Cross-encoder reranking is not configured; local ONNX weights "
                "or tokenizer are missing."
            )
        session, tokenizer = self._ensure_loaded()
        scores: list[float] = []
        for start in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[start : start + BATCH_SIZE]
            encoded = tokenizer.encode_batch(
                [(query, document) for query, document in batch]
            )
            inputs = {
                "input_ids": np.array([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.array(
                    [item.attention_mask for item in encoded], dtype=np.int64
                ),
                "token_type_ids": np.array(
                    [item.type_ids for item in encoded], dtype=np.int64
                ),
            }
            # Some exports drop token_type_ids. Sending an input the graph does
            # not declare is an error, so the session decides what it receives.
            fed = {name: inputs[name] for name in self._input_names if name in inputs}
            logits = np.asarray(session.run(None, fed)[0], dtype=np.float32)
            scores.extend(_logits(logits))
        return scores


# Reduce a batch of raw outputs to one log-odds value per pair.
#
# A relevance cross-encoder emits a single logit per pair, so the squeeze is the
# common case. A two-column output is a binary classifier head whose log-odds is
# the difference between the columns; both are handled because which one a
# checkpoint uses is not visible from its name.
def _logits(logits: np.ndarray) -> list[float]:
    if logits.ndim == 2 and logits.shape[1] == 2:
        values = logits[:, 1] - logits[:, 0]
    else:
        values = logits.reshape(logits.shape[0], -1)[:, 0]
    return [float(value) for value in values]
