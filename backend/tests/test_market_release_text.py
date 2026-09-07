"""Earnings releases kept as text and turned into vectors.

The release text was fetched, read and thrown away, so nothing could be
asked of it later without a new prompt. Now it is stored, and a vector is
made from it by the deployment's own embedding service. What has to hold:
records survive the store's frames unchanged, a long fetch resumes from its
partial file, a release is cut at the back rather than the front, the
embedding call batches and keeps order, and a vector reaches the panel only
from the session the market could first react on.
"""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import release_text


def _text(
    accession: str, when: str, body: str = "Revenue grew."
) -> release_text.ReleaseText:
    return release_text.ReleaseText(
        accession=accession,
        reaction_date=date.fromisoformat(when),
        text=body,
        chars=len(body),
        truncated=False,
    )


# A text record survives a trip through the frame columns unchanged, and
# comes back oldest first whatever order it went in.
def test_text_records_round_trip_through_a_frame():
    records = [_text("b", "2026-05-02", "Second."), _text("a", "2026-05-01", "First.")]
    frame = release_text.text_frame(records)
    assert frame["accession"] == ["a", "b"]
    back = release_text.texts_from_frame(frame)
    assert [r.accession for r in back] == ["a", "b"]
    assert back[0] == records[1]
    assert release_text.texts_from_frame({"accession": []}) == ()


# A long fetch appends to a partial file and reads it back by accession, so
# an interrupted run does not refetch what it already has.
def test_partial_file_resumes(tmp_path):
    path = release_text.partial_path(tmp_path, date(2026, 9, 7), "ADBE")
    assert release_text.read_partial(path) == {}
    first, second = _text("a", "2026-05-01"), _text("b", "2026-05-02")
    release_text.append_partial(path, first)
    release_text.append_partial(path, second)
    got = release_text.read_partial(path)
    assert set(got) == {"a", "b"}
    assert got["a"] == first
    assert got["b"].reaction_date == date(2026, 5, 2)


# A release over the limit keeps its front, which is where the words are,
# and says it was cut. One under the limit is untouched.
def test_clip_keeps_the_front():
    body = "words " * 10_000  # 60,000 characters
    kept, cut = release_text.clip(body)
    assert cut is True
    assert len(kept) == release_text.MAX_CHARS
    assert kept == body[: release_text.MAX_CHARS]
    short, cut = release_text.clip("short")
    assert (short, cut) == ("short", False)


# A stub server: the tokenizer route counts `chars_per_token` characters as
# one token, and the embeddings route answers in reverse order to prove the
# index is honoured. Every request is kept, by route.
def _server(chars_per_token: int, embeds: list[dict], counts: list[str]):
    def post(url, json, timeout):
        if url.endswith("/tokenize"):
            counts.append(json["prompt"])
            count = -(-len(json["prompt"]) // chars_per_token)
            return SimpleNamespace(
                status_code=200,
                raise_for_status=lambda: None,
                json=lambda: {"count": count},
            )
        embeds.append(json)
        data = [
            {"index": i, "embedding": [float(i), float(len(text))]}
            for i, text in enumerate(json["input"])
        ][::-1]
        return SimpleNamespace(
            status_code=200, raise_for_status=lambda: None, json=lambda: {"data": data}
        )

    return post


# The embedding call batches, carries the document prefix nomic asks for,
# and returns vectors in the caller's order however the server orders them.
def test_embed_batches_and_keeps_order():
    embeds: list[dict] = []
    post = _server(4, embeds, [])
    texts = [f"release {i}" for i in range(release_text.EMBED_BATCH + 3)]
    vectors = release_text.embed(texts, "http://embed", "nomic", post=post)
    assert len(embeds) == 2
    assert embeds[0]["model"] == "nomic"
    assert all(t.startswith(release_text.DOCUMENT_PREFIX) for t in embeds[0]["input"])
    assert len(vectors) == len(texts)
    # The first value is the in-batch index, so order is exactly the input's.
    assert [v[0] for v in vectors[: release_text.EMBED_BATCH]] == [
        float(i) for i in range(release_text.EMBED_BATCH)
    ]
    assert vectors[release_text.EMBED_BATCH][0] == 0.0  # the second batch restarts
    assert release_text.embed([], "http://embed", "nomic", post=post) == []


# What reaches the embedder is cut to what the server will take, measured
# in the server's own tokens. The deployment serves the model at 2,048 and
# refuses a longer request outright with a 400 - it does not truncate - so
# a release past the cap would fail the whole batch it sat in. Characters
# are not a safe proxy: a table-dense release runs more tokens per
# character than prose. The cut keeps the front, where the words are.
def test_embed_cuts_each_text_to_what_the_server_accepts():
    embeds: list[dict] = []
    counts: list[str] = []
    # Two characters a token: 7,000 characters would be 3,500 tokens, well
    # past the cap, so the cut has to go below EMBED_CHARS.
    post = _server(2, embeds, counts)
    long = "guidance " * 5_000  # 45,000 characters
    release_text.embed([long, "short"], "http://embed", "nomic", post=post)
    prefix = release_text.DOCUMENT_PREFIX
    sent = embeds[0]["input"]
    limit = release_text.EMBED_TOKENS - release_text.TOKEN_MARGIN
    assert sent[0].startswith(prefix + "guidance guidance")
    assert len(sent[0]) < len(prefix) + release_text.EMBED_CHARS
    assert -(-len(sent[0]) // 2) <= limit  # what the stub would count
    assert sent[0] == prefix + long[: len(sent[0]) - len(prefix)]  # the front
    assert sent[1] == prefix + "short"
    # Every measurement carried the prefix, because the server counts it.
    assert all(c.startswith(prefix) for c in counts)


# The fit converges from the character cap by measured overshoot and never
# touches a text that already fits.
def test_fit_shrinks_by_measured_overshoot():
    calls: list[int] = []

    def count(body: str) -> int:
        calls.append(len(body))
        return len(body) // 2

    body = release_text.fit("x" * 10_000, 2_000, count)
    assert len(body) <= 4_000
    assert calls[0] == release_text.EMBED_CHARS  # starts at the character cap
    assert len(calls) <= 3  # proportional shrink converges in a pass or two
    assert release_text.fit("short", 2_000, count) == "short"


# A vector record round-trips with its model name, so a vector made by one
# model is never mistaken for another's.
def test_vector_records_round_trip_with_their_model():
    records = [
        release_text.ReleaseVector("a", date(2026, 5, 1), "nomic", (0.1, 0.2)),
        release_text.ReleaseVector("b", date(2026, 5, 2), "nomic", (0.3, 0.4)),
    ]
    back = release_text.vectors_from_frame(release_text.vector_frame(records))
    assert back == tuple(records)
    assert back[0].model == "nomic"


# A release reaches the panel on its reaction date and not before, stands
# until the next one replaces it, and a name with none reads as NaN.
def test_vectors_reach_the_panel_only_from_the_reaction_date():
    dates = np.arange("2026-05-01", "2026-05-11", dtype="datetime64[D]")
    by_ticker = {
        "AAA": [
            release_text.ReleaseVector("a", date(2026, 5, 3), "nomic", (1.0, 1.0)),
            release_text.ReleaseVector("b", date(2026, 5, 7), "nomic", (2.0, 2.0)),
        ]
    }
    panel = release_text.vector_panel(dates, ("AAA", "BBB"), by_ticker, 2)
    assert panel.shape == (10, 2, 2)
    assert np.isnan(panel[:2, 0]).all()  # before the first reaction date
    assert panel[2, 0].tolist() == [1.0, 1.0]  # May 3
    assert panel[5, 0].tolist() == [1.0, 1.0]  # May 6, still the first
    assert panel[6, 0].tolist() == [2.0, 2.0]  # May 7, the second takes over
    assert panel[9, 0].tolist() == [2.0, 2.0]
    assert np.isnan(panel[:, 1]).all()  # a name with no releases


# The index form of the same alignment: each cell names the release it
# carries and how many sessions it has carried it, with -1 before any.
def test_active_index_matches_the_panel_alignment():
    dates = np.arange("2026-05-01", "2026-05-11", dtype="datetime64[D]")
    records = [
        release_text.ReleaseVector("a", date(2026, 5, 3), "m", (1.0,)),
        release_text.ReleaseVector("b", date(2026, 5, 7), "m", (2.0,)),
        release_text.ReleaseVector("z", date(2026, 5, 2), "m", (9.0,)),  # another name
    ]
    ticker_of = {"a": "AAA", "b": "AAA", "z": "ZZZ"}
    index, since = release_text.active_index(
        dates, ("AAA", "BBB", "ZZZ"), records, ticker_of
    )
    assert index.shape == since.shape == (10, 3)
    assert index[:2, 0].tolist() == [-1, -1]
    assert index[2:6, 0].tolist() == [0, 0, 0, 0]  # 'a' from May 3
    assert index[6:, 0].tolist() == [1, 1, 1, 1]  # 'b' from May 7
    assert since[2:6, 0].tolist() == [0, 1, 2, 3]
    assert since[6, 0] == 0  # the counter restarts with the new release
    assert (index[:, 1] == -1).all()  # a name with no releases
    assert index[1, 2] == 2  # 'z' belongs to ZZZ, not AAA
    # And it agrees with the dense panel wherever the panel has a vector.
    panel = release_text.vector_panel(
        dates,
        ("AAA", "BBB", "ZZZ"),
        {"AAA": records[:2], "ZZZ": records[2:]},
        1,
    )
    dense = np.where(np.isfinite(panel[:, :, 0]), panel[:, :, 0], np.nan)
    looked_up = np.where(
        index >= 0, np.array([r.vector[0] for r in records])[index], np.nan
    )
    assert np.array_equal(np.isnan(dense), np.isnan(looked_up))
    assert np.allclose(dense[np.isfinite(dense)], looked_up[np.isfinite(looked_up)])


# The reaction date is the point-in-time rule, so a release accepted after
# the close cannot show up on the day it was filed.
@pytest.mark.parametrize(
    ("reaction", "first_visible_row"),
    [(date(2026, 5, 1), 0), (date(2026, 5, 2), 1), (date(2026, 5, 30), None)],
)
def test_a_release_is_never_visible_before_its_reaction_date(
    reaction, first_visible_row
):
    dates = np.arange("2026-05-01", "2026-05-11", dtype="datetime64[D]")
    panel = release_text.vector_panel(
        dates,
        ("AAA",),
        {"AAA": [release_text.ReleaseVector("a", reaction, "m", (1.0,))]},
        1,
    )
    visible = np.flatnonzero(np.isfinite(panel[:, 0, 0]))
    if first_visible_row is None:
        assert len(visible) == 0
    else:
        assert visible[0] == first_visible_row
