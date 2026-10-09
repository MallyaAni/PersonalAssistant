"""Keep streaming account persistence byte-identical and atomic on write failure."""

import json
from dataclasses import asdict

import pytest

from backend.agents.trading.desk import paper


# Preserve all nested receipts and the exact original serialized state representation.
def test_streamed_state_matches_original_bytes_and_reloads(tmp_path, monkeypatch):
    state = paper.PaperState(
        history=[
            {
                "session": "2026-10-08",
                "note": 'Unicode \u2014 "quoted" text',
                "positions": [{"ticker": "AAA", "qty": 17, "price": 95.25}],
                "receipt": {"indices": list(range(1200)), "missing": None},
            }
        ] * 5,
        deferred_buys={"AAA": 3},
    )
    expected = json.dumps(state, indent=2, default=paper._state_json).encode("utf-8")

    # Fail if persistence materializes the complete formatted JSON string again.
    def reject_whole_string(*args, **kwargs):
        raise AssertionError("Account writer must stream the original JSON chunks")

    monkeypatch.setattr(paper.json, "dumps", reject_whole_string)
    path = paper.save_state(tmp_path, state)
    assert path.read_bytes() == expected
    assert asdict(paper.load_state(tmp_path)) == asdict(state)
    assert list(path.parent.iterdir()) == [path]


# A failure after partial output must preserve the last durable state and clean up.
def test_partial_stream_failure_preserves_original_state(tmp_path, monkeypatch):
    path = paper.save_state(tmp_path, paper.PaperState(deferred_buys={"AAA": 2}))
    original = path.read_bytes()

    # Reproduce interrupted serialization after bytes reach the private temporary file.
    def interrupted_dump(value, handle, **kwargs):
        handle.write('{"history": [')
        raise OSError("Interrupted state stream")

    monkeypatch.setattr(paper.json, "dump", interrupted_dump)
    with pytest.raises(OSError, match="Interrupted state stream"):
        paper.save_state(tmp_path, paper.PaperState(deferred_buys={"AAA": 7}))
    assert path.read_bytes() == original
    assert paper.load_state(tmp_path).deferred_buys == {"AAA": 2}
    assert list(path.parent.iterdir()) == [path]
