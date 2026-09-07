"""Earnings press releases, kept as text, and turned into vectors.

The desk's most valuable signal is a language model reading each earnings
release and returning five categorical fields. The release itself was
fetched, read, and thrown away, so every later question about what the
text could tell us meant fetching it again - and no question could be
asked of the text at all without a new prompt and a new functional test.

This keeps the text. Two frame kinds:

  edgar_release_text   one row per release: the accession, the first
                       session the market could react on, the plain text
                       of the EX-99.1 exhibit, and whether it was cut to
                       fit
  edgar_release_vec    the same rows as fixed-width embeddings from the
                       deployment's own embedding service, with the model
                       name recorded so a vector is never mistaken for one
                       made by a different model

Point in time. A release is dated by its reaction date, the same rule the
tone reader uses: the acceptance date when accepted before the close in
New York, else the next calendar day. Nothing built from a release is
visible to the panel before that session.

Why embeddings first. A general text model turns a document into a
vector without being told what to look for, and a small supervised model
on top can then be measured against the desk's own label with the same
purged walk-forward as everything else. That is the cheapest honest test
of whether there is information in the release beyond the five fields the
reader already extracts. The embedder is a parameter, not a commitment:
the text is what is stored, so a different model is one more `embed` run.
"""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import httpx
import numpy as np

RELEASE_TEXT_KIND = "edgar_release_text"
RELEASE_VEC_KIND = "edgar_release_vec"
# A release longer than this is cut. Press releases run 5,000 to 40,000
# characters; the tables at the end are the part that gets cut, and the
# words before them are the part that carries the guidance.
MAX_CHARS = 30_000
# The prefix nomic-embed asks for on documents, as opposed to queries.
DOCUMENT_PREFIX = "search_document: "
EMBED_BATCH = 16
EMBED_TIMEOUT = 120.0


@dataclass(frozen=True)
class ReleaseText:
    """One release's text, dated by when the market could first react."""

    accession: str
    reaction_date: date
    text: str
    chars: int  # of the original, before any cut
    truncated: bool


@dataclass(frozen=True)
class ReleaseVector:
    """One release's embedding, with the model that made it."""

    accession: str
    reaction_date: date
    model: str
    vector: tuple[float, ...]


# --- text storage ------------------------------------------------------------


# Serialise text records for the store's frames.
def text_frame(records: Sequence[ReleaseText]) -> dict[str, list]:
    """Return the columns of a release-text frame."""
    ordered = sorted(records, key=lambda r: (r.reaction_date, r.accession))
    return {
        "accession": [r.accession for r in ordered],
        "reaction_date": [r.reaction_date.isoformat() for r in ordered],
        "text": [r.text for r in ordered],
        "chars": [int(r.chars) for r in ordered],
        "truncated": [bool(r.truncated) for r in ordered],
    }


# Rebuild text records from a stored frame.
def texts_from_frame(columns: Mapping[str, list]) -> tuple[ReleaseText, ...]:
    """Return the ReleaseTexts a frame encodes, oldest reaction first."""
    rows = [
        ReleaseText(
            accession=str(columns["accession"][i]),
            reaction_date=date.fromisoformat(str(columns["reaction_date"][i])),
            text=str(columns["text"][i]),
            chars=int(columns["chars"][i]),
            truncated=bool(columns["truncated"][i]),
        )
        for i in range(len(columns.get("accession", [])))
    ]
    return tuple(sorted(rows, key=lambda r: r.reaction_date))


# The partial file a long fetch appends to, one JSON record per line.
def partial_path(root: Path, asof: date, ticker: str) -> Path:
    """Return the path of a ticker's in-progress text file."""
    return (
        root
        / RELEASE_TEXT_KIND
        / f"asof={asof.isoformat()}"
        / f"{ticker}.partial.jsonl"
    )


# Append one record to the partial file.
def append_partial(path: Path, record: ReleaseText) -> None:
    """Append a record to the partial file, creating it if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(record)
    payload["reaction_date"] = record.reaction_date.isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


# Read the records already fetched into a partial file.
def read_partial(path: Path) -> dict[str, ReleaseText]:
    """Return {accession: record} from a partial file, empty if absent."""
    if not path.exists():
        return {}
    out: dict[str, ReleaseText] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        payload["reaction_date"] = date.fromisoformat(payload["reaction_date"])
        record = ReleaseText(**payload)
        out[record.accession] = record
    return out


# Cut a release to MAX_CHARS, keeping the front, which is where the words
# are; the tables at the back are what goes.
def clip(text: str) -> tuple[str, bool]:
    """Return (text within the limit, whether it was cut)."""
    if len(text) <= MAX_CHARS:
        return text, False
    return text[:MAX_CHARS], True


# --- vectors -----------------------------------------------------------------


# Serialise vectors for the store's frames. Each vector is one list column
# entry, which parquet stores as a fixed-width list.
def vector_frame(records: Sequence[ReleaseVector]) -> dict[str, list]:
    """Return the columns of a release-vector frame."""
    ordered = sorted(records, key=lambda r: (r.reaction_date, r.accession))
    return {
        "accession": [r.accession for r in ordered],
        "reaction_date": [r.reaction_date.isoformat() for r in ordered],
        "model": [r.model for r in ordered],
        "vector": [list(r.vector) for r in ordered],
    }


# Rebuild vector records from a stored frame.
def vectors_from_frame(columns: Mapping[str, list]) -> tuple[ReleaseVector, ...]:
    """Return the ReleaseVectors a frame encodes, oldest reaction first."""
    rows = [
        ReleaseVector(
            accession=str(columns["accession"][i]),
            reaction_date=date.fromisoformat(str(columns["reaction_date"][i])),
            model=str(columns["model"][i]),
            vector=tuple(float(v) for v in columns["vector"][i]),
        )
        for i in range(len(columns.get("accession", [])))
    ]
    return tuple(sorted(rows, key=lambda r: r.reaction_date))


# Embed a batch of texts with an OpenAI-compatible embeddings endpoint.
# `post` is the transport, so a test can hand in a stub.
def embed(
    texts: Sequence[str],
    base_url: str,
    model: str,
    post: Callable[..., httpx.Response] | None = None,
) -> list[list[float]]:
    """Return one vector per text, in order."""
    if not texts:
        return []
    poster = post or _post
    out: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        chunk = [DOCUMENT_PREFIX + t for t in texts[start : start + EMBED_BATCH]]
        response = poster(
            f"{base_url.rstrip('/')}/v1/embeddings",
            json={"model": model, "input": chunk},
            timeout=EMBED_TIMEOUT,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda r: r["index"])
        out.extend([float(v) for v in row["embedding"]] for row in rows)
    return out


# The default transport, with bounded retries on a busy server.
def _post(url: str, **kwargs) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = httpx.post(url, **kwargs)
            if response.status_code in (429, 500, 502, 503):
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return response
        except (httpx.HTTPError, OSError) as exc:  # transient
            last = exc
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"embedding endpoint failed after retries: {last}")


# --- features ----------------------------------------------------------------


# The vector each name carried on each session: the newest release whose
# reaction date is on or before the session, or NaN where there is none.
def vector_panel(
    dates: np.ndarray,
    tickers: Sequence[str],
    by_ticker: Mapping[str, Sequence[ReleaseVector]],
    width: int,
) -> np.ndarray:
    """Return (T, N, width) release vectors aligned to the panel, NaN where none."""
    rows = len(dates)
    out = np.full((rows, len(tickers), width), np.nan)
    stamps = np.asarray(dates).astype("datetime64[D]")
    for column, ticker in enumerate(tickers):
        items = sorted(by_ticker.get(ticker, ()), key=lambda r: r.reaction_date)
        for i, record in enumerate(items):
            start = int(
                np.searchsorted(stamps, np.datetime64(record.reaction_date), "left")
            )
            stop = rows
            if i + 1 < len(items):
                nxt = np.datetime64(items[i + 1].reaction_date)
                stop = int(np.searchsorted(stamps, nxt, "left"))
            if start < stop:
                out[start:stop, column, :] = record.vector
    return out
