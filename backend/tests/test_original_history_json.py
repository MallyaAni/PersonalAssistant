"""Strict streaming ORIGINAL evidence; all inputs here are explicitly synthetic."""

import gzip
import io
import json
import os
from hashlib import sha256

import pytest

from backend.market import original_history_json as stream


# Write a small synthetic source with an external byte identity before parsing it.
def admitted(tmp_path, raw, *, compressed=False, physical=False, retain=True):
    path = tmp_path / "original.json"
    original = gzip.compress(raw, mtime=0) if compressed else raw
    path.write_bytes(original)
    return stream.read(
        path,
        sha256(original).hexdigest(),
        directory=tmp_path,
        compressed=compressed,
        physical=physical,
        retain=retain,
    )


# Streaming canonical hashes must equal the old whole-value algorithm bit for bit.
@pytest.mark.parametrize("compressed", [False, True])
def test_canonical_digest_and_complete_order(tmp_path, compressed):
    value = {
        "paper_state": {
            "pending": [],
            "history": [
                {"session": "initial", "qty": 1, "text": 'é\\"[x]', "x": -0.0},
                {"session": "next", "qty": 2, "x": 1e-9},
            ],
        },
        "input_sha256": {"a": "b"},
    }
    parsed = admitted(tmp_path, json.dumps(value).encode(), compressed=compressed)
    assert (
        stream.digest(parsed)
        == sha256(
            json.dumps(value, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    )
    assert list(parsed["paper_state"]["history"]) == value["paper_state"]["history"]
    stream.release(parsed)


# Every streamed or discarded row still passes strict nested grammar and value checks.
@pytest.mark.parametrize("retain", [False, True])
@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"paper_state":{"history":[{"nested":{"x":1,"x":2}}]}}',
        b'{"paper_state":{"history":[{"x":NaN}]}}',
        b'{"paper_state":{"history":[{"x":1e999}]}}',
        b'{"paper_state":{"history":[{"x":1],2]}}',
        b'{"paper_state":{"history":[{"x":1},]}}',
        b'{"paper_state":{"history":[{"x":1}]},"x":trueX}',
        b'{"paper_state":{"history":[{"x":"unterminated}]}}',
        b'{"paper_state":{"history":[]}} trailing',
    ],
)
def test_strict_all_framing_even_discarded(tmp_path, retain, raw):
    with pytest.raises(
        ValueError,
        match=(
            "Duplicate|Nonfinite|Malformed|Truncated|Trailing|Expecting|Unterminated"
            "|Extra data"
        ),
    ):
        admitted(tmp_path, raw, retain=retain)


# Broken gzip trailers and concatenated invalid JSON never become admitted projections.
@pytest.mark.parametrize("corruption", ["crc", "truncate", "second_member"])
def test_gzip_integrity_and_full_eof(tmp_path, corruption):
    raw = gzip.compress(b'{"history":[{"session":"initial"}]}', mtime=0)
    if corruption == "crc":
        raw = raw[:-8] + bytes([raw[-8] ^ 1]) + raw[-7:]
    elif corruption == "truncate":
        raw = raw[:-3]
    else:
        raw += gzip.compress(b"{}", mtime=0)
    path = tmp_path / "original.gz"
    path.write_bytes(raw)
    with pytest.raises((ValueError, OSError, EOFError)):
        stream.read(path, sha256(raw).hexdigest(), compressed=True, directory=tmp_path)


# Physical writer literals have a separate logical projection, never a source rewrite.
def test_physical_nonfinite_domain_and_original_bytes(tmp_path):
    raw = b'{"history":[{"session":"initial","x":NaN,"y":Infinity,"z":-Infinity}]}'
    with pytest.raises(ValueError, match="Nonfinite"):
        admitted(tmp_path, raw)
    value = admitted(tmp_path, raw, physical=True)
    expected = {"history": [{"session": "initial", "x": None, "y": None, "z": None}]}
    assert (
        stream.digest(value)
        == sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    )
    assert (tmp_path / "original.json").read_bytes() == raw
    with pytest.raises(ValueError, match="SHA differs"):
        stream.read(
            tmp_path / "original.json", "0" * 64, physical=True, directory=tmp_path
        )


# Unit and cumulative control limits run before an unbounded decoder can see bytes.
def test_row_and_aggregate_controls_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "ROW_BYTES", 32)
    with pytest.raises(ValueError, match="unit exceeds"):
        admitted(tmp_path, b'{"history":[{"long":"' + b"x" * 40 + b'"}]}')
    monkeypatch.setattr(stream, "CONTROL_BYTES", 32)
    with pytest.raises(ValueError, match="controls exceed"):
        admitted(tmp_path, b'{"a":"12345678901234567890","b":"12345678901234567890"}')


# Fixed block reads and split escape sequences preserve every byte boundary.
def test_bounded_cursor_chunk_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "CHUNK_BYTES", 3)

    # Refuse any unsized or oversized cursor read rather than faking a small source.
    class Reader(io.StringIO):
        # Record the parser's actual finite read request.
        def read(self, size=-1):
            assert 0 < size <= 3
            return super().read(size)

    raw = '{"history":[{"session":"a","x":"\\u0041\\\\\\""}]}'
    value = stream.Cursor(Reader(raw), False, tmp_path, True).object()
    assert (
        stream.digest(value)
        == sha256(json.dumps(json.loads(raw), sort_keys=True).encode()).hexdigest()
    )


# Scalar root fields and nested controls remain exact across every small chunk size.
@pytest.mark.parametrize("chunk_bytes", range(1, 9))
def test_positive_scalar_chunk_boundaries(tmp_path, monkeypatch, chunk_bytes):
    monkeypatch.setattr(stream, "CHUNK_BYTES", chunk_bytes)
    raw = (
        b'{"true":true,"false":false,"null":null,"negative":-17,'
        b'"fraction":-0.125,"exponent":6.25e-7,"controls":'
        b'{"true":true,"false":false,"null":null,"negative":-17,'
        b'"fraction":-0.125,"exponent":6.25e-7},"history":'
        b'[{"session":"initial","value":false},{"session":"next","value":null}]}'
    )
    expected = json.loads(raw)
    value = admitted(tmp_path, raw)
    assert {key: value[key] for key in expected if key != "history"} == {
        key: expected[key] for key in expected if key != "history"
    }
    assert list(value["history"]) == expected["history"]
    assert (
        stream.digest(value)
        == sha256(
            json.dumps(expected, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    )
    assert (tmp_path / "original.json").read_bytes() == raw


# Real plain and gzip TextIO decoders preserve multi-byte characters crossing blocks.
@pytest.mark.parametrize("compressed", [False, True])
def test_utf8_crosses_actual_text_input_blocks(tmp_path, monkeypatch, compressed):
    monkeypatch.setattr(stream, "CHUNK_BYTES", 8192)
    raw = b'{"control":"'
    raw += b"x" * (8191 - len(raw)) + "€".encode()
    raw += b"y" * (16383 - len(raw)) + "𐍈".encode()
    raw += (
        '","history":[{"session":"initial","value":"é"},'
        '{"session":"next","value":"雪"}]}'.encode()
    )
    assert raw[8191:8194] == "€".encode()
    assert raw[16383:16387] == "𐍈".encode()
    expected = json.loads(raw)
    value = admitted(tmp_path, raw, compressed=compressed)
    assert value["control"] == expected["control"]
    assert list(value["history"]) == expected["history"]
    assert (
        stream.digest(value)
        == sha256(
            json.dumps(expected, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    )
    original = gzip.compress(raw, mtime=0) if compressed else raw
    assert (tmp_path / "original.json").read_bytes() == original


# Symlinks and edits during parsing cannot borrow the old byte identity.
def test_source_identity_changes_and_symlinks_refuse(tmp_path, monkeypatch):
    path = tmp_path / "source.json"
    raw = b'{"history":[]}'
    path.write_bytes(raw)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="Symlink"):
        stream.read(alias, sha256(raw).hexdigest(), directory=tmp_path)
    original = stream.Cursor.take
    changed = False

    # Change actual source metadata after parsing begins, keeping identical bytes.
    def changed_take(self):
        nonlocal changed
        if not changed:
            changed = True
            path.write_bytes(raw)
        return original(self)

    monkeypatch.setattr(stream.Cursor, "take", changed_take)
    with pytest.raises(ValueError, match="evidence changed"):
        stream.read(path, sha256(raw).hexdigest(), directory=tmp_path)


# Depth and row-count profiles refuse excess rather than dropping later rows.
def test_fixed_depth_and_complete_row_count(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "DEPTH", 2)
    with pytest.raises(ValueError, match="depth exceeds"):
        admitted(tmp_path, b'{"x":[[[1]]]}')
    monkeypatch.setattr(stream, "HISTORY_ROWS", 2)
    with pytest.raises(ValueError, match="row count exceeds"):
        admitted(tmp_path, b'{"history":[{},{},{}]}')


# Processing limits bound gzip expansion and whitespace without a resident-file buffer.
def test_stream_processing_bound_is_checked_on_bounded_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "STREAM_BYTES", 32)
    with pytest.raises(ValueError, match="processing bound"):
        admitted(tmp_path, b'{"history":[]}' + b" " * 40, compressed=True)


# Independent append/replacement preserves initial rows and their exact order.
def test_independent_history_order_and_full_state_digest(tmp_path):
    ledger = stream.History(tmp_path / "derived")
    first, second = {"session": "initial", "qty": 1}, {"session": "next", "qty": 2}
    ledger.record(first)
    ledger.record(second)
    expected = {"pending": [], "history": [first, second]}
    assert (
        stream.digest({"pending": [], "history": ledger.view()})
        == sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    )
    for rows in ([second], [second, first], [first, dict(second, qty=3)]):
        assert stream.digest({"pending": [], "history": rows}) != stream.digest(
            {"pending": [], "history": ledger.view()}
        )
    ledger.record(dict(first, qty=4))
    assert list(ledger.view()) == [second, dict(first, qty=4)]
    ledger.view().entries[0].path.write_text("{}")
    with pytest.raises(ValueError, match="spool"):
        ledger.view()[0]


# Generate1916 rows only in the explicit private large-fixture resource run.
@pytest.mark.skipif(
    "ANIOS_ORIGINAL_JSON_STRESS_BYTES" not in os.environ,
    reason="Explicit isolated large-fixture resource run required",
)
def test_profile_1916_resource(tmp_path):
    target = int(os.environ["ANIOS_ORIGINAL_JSON_STRESS_BYTES"])
    assert target in (373782589, 832110254)
    path = tmp_path / "synthetic-1916.json"
    payload = "x" * (target // stream.HISTORY_ROWS - 128)
    expected = sha256()
    with path.open("wb") as output:
        output.write(b'{"history": [')
        expected.update(b'{"history": [')
        for index in range(stream.HISTORY_ROWS):
            raw = json.dumps(
                {"session": str(index), "payload": payload}, sort_keys=True
            ).encode()
            if index:
                output.write(b", ")
                expected.update(b", ")
            output.write(raw)
            expected.update(raw)
        output.write(b"]}")
        expected.update(b"]}")
        remaining = target - output.tell()
        assert remaining >= 0
        while remaining:
            size = min(remaining, stream.CHUNK_BYTES)
            output.write(b" " * size)
            remaining -= size
    raw_hash = sha256()
    with path.open("rb") as original:
        while block := original.read(stream.CHUNK_BYTES):
            raw_hash.update(block)
    source = stream.authenticate(path, raw_hash.hexdigest())
    assert source[2] == target
    value = stream.read(path, raw_hash.hexdigest(), directory=tmp_path)
    assert len(value["history"]) == 1916
    assert stream.digest(value) == expected.hexdigest()
