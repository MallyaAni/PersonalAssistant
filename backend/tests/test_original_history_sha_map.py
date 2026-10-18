"""Synthetic complete SHA-map preservation, never original/model acceptance."""

import inspect
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest

from backend.market import original_history_json as stream


# Pin synthetic source bytes before selecting disk-backed input hashes.
def admitted(tmp_path, raw):
    path = tmp_path / "completion.json"
    path.write_bytes(raw)
    return stream.read(
        path,
        sha256(raw).hexdigest(),
        directory=tmp_path,
        retain=False,
        external_inputs=True,
    )


# Preserve every pair, source order, lookup and exact old canonical JSON digest.
@pytest.mark.parametrize("keys", [[], ["z", "a"], ["é", "a", "𐀀", "\ue000", "\ud800"]])
def test_complete_map_matches_dictionary(tmp_path, keys):
    expected = {
        name: sha256(str(index).encode()).hexdigest() for index, name in enumerate(keys)
    }
    value = admitted(tmp_path, json.dumps({"input_sha256": expected}).encode())
    mapping = value["input_sha256"]
    assert type(mapping) is stream.ShaMap
    assert len(mapping) == len(expected)
    assert list(mapping) == keys
    assert list(mapping.items()) == list(expected.items())
    assert list(mapping.pairs(canonical=True)) == sorted(expected.items())
    assert mapping == expected
    assert deepcopy(mapping) is mapping
    assert mapping.get("absent") is None
    assert mapping.get("absent", "missing") == "missing"
    assert "absent" not in mapping
    with pytest.raises(KeyError):
        mapping["absent"]
    for key, digest in expected.items():
        assert key in mapping
        assert mapping[key] == digest
    assert (
        stream.digest(value)
        == sha256(
            json.dumps(
                {"input_sha256": expected}, sort_keys=True, allow_nan=False
            ).encode()
        ).hexdigest()
    )
    assert (
        mapping.verify()["canonical_sha256"]
        == sha256(
            json.dumps(expected, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    )


# Decoded-key uniqueness rejects both literal repeats and differently escaped aliases.
@pytest.mark.parametrize("second", [b'"a"', b'"\\u0061"'])
def test_duplicate_decoded_key_is_never_replaced(tmp_path, second):
    raw = (
        b'{"input_sha256":{"a":"'
        + b"a" * 64
        + b'",'
        + second
        + b':"'
        + b"b" * 64
        + b'"}}'
    )
    with pytest.raises(ValueError, match="Duplicate"):
        admitted(tmp_path, raw)
    assert not list(tmp_path.glob("original-sha-*"))


# Every digest must remain a strict lower-case64-character string, not a truthy value.
@pytest.mark.parametrize(
    "value", [None, True, 1, 1.0, [], {}, "a" * 63, "a" * 65, "A" * 64, "g" * 64]
)
def test_digest_type_and_shape_refuse(tmp_path, value):
    raw = json.dumps({"input_sha256": {"a": value}}).encode()
    with pytest.raises(ValueError, match="lower-case SHA256"):
        admitted(tmp_path, raw)
    assert not list(tmp_path.glob("original-sha-*"))


# Reject malformed map grammar and repeated root fields.
@pytest.mark.parametrize(
    "raw",
    [
        b'{"input_sha256":{"a":NaN}}',
        b'{"input_sha256":{"a":1e999}}',
        b'{"input_sha256":[]}',
        b'{"input_sha256":{1:"a"}}',
        b'{"input_sha256":{"a":"' + b"a" * 64 + b'",}}',
        b'{"input_sha256":{},"input_sha256":{}}',
    ],
)
def test_map_framing_is_strict(tmp_path, raw):
    with pytest.raises(ValueError, match="Nonfinite|Malformed|Expecting|Duplicate|Extra data"):
        admitted(tmp_path, raw)


# Only an explicit root opt-in bypasses resident map allocation; nested controls do not.
def test_opt_in_is_root_only_and_controls_stay_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "CONTROL_BYTES", 128)
    raw = json.dumps({"input_sha256": {"a": "a" * 64, "b": "b" * 64}}).encode()
    path = tmp_path / "completion.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="unit exceeds|controls exceed"):
        stream.read(path, sha256(raw).hexdigest(), directory=tmp_path, retain=False)
    assert admitted(tmp_path, raw)["input_sha256"]["a"] == "a" * 64
    nested = json.dumps(
        {"metadata": {"input_sha256": {"a": "a" * 64, "b": "b" * 64}}}
    ).encode()
    with pytest.raises(ValueError, match="unit exceeds|controls exceed"):
        admitted(tmp_path, nested)
    with pytest.raises(ValueError, match="Explicit root"):
        stream.read(
            path,
            sha256(raw).hexdigest(),
            physical=True,
            external_inputs=True,
            directory=tmp_path,
        )


# Refuse entry, key and byte excess without retaining a partial map.
@pytest.mark.parametrize("limit", ["entries", "key", "bytes"])
def test_map_resource_caps_refuse_without_truncating(tmp_path, monkeypatch, limit):
    if limit == "entries":
        monkeypatch.setattr(stream, "SHA_MAP_ENTRIES", 1)
    elif limit == "key":
        monkeypatch.setattr(stream, "SHA_MAP_KEY_BYTES", 2)
    else:
        monkeypatch.setattr(stream, "SHA_MAP_BYTES", 16)
    raw = json.dumps({"input_sha256": {"a": "a" * 64, "b": "b" * 64}}).encode()
    with pytest.raises(ValueError, match="bound"):
        admitted(tmp_path, raw)
    assert not list(tmp_path.glob("original-sha-*"))


# No public mutation or changed row/index can continue as the original sealed map.
@pytest.mark.parametrize(
    "mutation", ["attribute", "item", "spool", "index", "replacement", "seal"]
)
def test_immutable_store_rejects_tampering(tmp_path, mutation):
    mapping = admitted(tmp_path, b'{"input_sha256":{"a":"' + b"a" * 64 + b'"}}')[
        "input_sha256"
    ]
    if mutation == "attribute":
        with pytest.raises(AttributeError):
            mapping.count = 2
        return
    if mutation == "item":
        with pytest.raises(TypeError):
            mapping["a"] = "b" * 64
        return
    if mutation == "spool":
        with mapping.spool.open("r+b") as output:
            output.seek(8)
            output.write(b"b")
    elif mutation == "index":
        connection = sqlite3.connect(mapping.index)
        connection.execute("DELETE FROM entries")
        connection.commit()
        connection.close()
    elif mutation == "replacement":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(mapping.spool.read_bytes())
        replacement.replace(mapping.spool)
    else:
        mapping = replace(mapping, index_sha256="0" * 64)
        with pytest.raises(ValueError, match="SHA differs"):
            mapping.verify()
        return
    with pytest.raises(ValueError, match="changed"):
        mapping["a"]
    with pytest.raises(ValueError, match="changed"):
        mapping.verify()


# Compare every pair and retain insertion order separately from canonical order.
def test_complete_pair_comparison_detects_loss_replacement_and_reordering(tmp_path):
    wanted = {"b": "b" * 64, "a": "a" * 64}
    first = admitted(tmp_path, json.dumps({"input_sha256": wanted}).encode())[
        "input_sha256"
    ]
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = admitted(
        second_dir,
        json.dumps({"input_sha256": dict(reversed(list(wanted.items())))}).encode(),
    )["input_sha256"]
    assert first == second
    assert list(first.items()) != list(second.items())
    assert first != {"a": "a" * 64}
    assert first != {"a": "a" * 64, "b": "c" * 64}
    assert list(first.items()) == list(wanted.items())


# Stream a complete164833-pair map above16MiB without constructing a whole dictionary.
def test_large_input_map_exceeds_legacy_resident_limit(tmp_path):
    path = tmp_path / "large-completion.json"
    expected_map, expected_root, raw_hash = sha256(), sha256(), sha256()
    with path.open("xb") as output:
        header = b'{"input_sha256": '
        output.write(header)
        expected_root.update(header)
        raw_hash.update(header)
        for index in range(164833):
            name = "/synthetic/" + "x" * 40 + f"/{index:06d}"
            value = sha256(str(index).encode()).hexdigest()
            raw = (
                (b"{" if index == 0 else b", ")
                + json.dumps(name).encode()
                + b": "
                + json.dumps(value).encode()
            )
            output.write(raw)
            expected_map.update(raw)
            expected_root.update(raw)
            raw_hash.update(raw)
        output.write(b"}}")
        expected_map.update(b"}")
        expected_root.update(b"}}")
        raw_hash.update(b"}}")
    assert 16 * 1024**2 < path.stat().st_size < 32 * 1024**2
    # Reach the old parser's capacity failure instead of an unsupported keyword.
    kwargs = (
        {"external_inputs": True}
        if "external_inputs" in inspect.signature(stream.read).parameters
        else {}
    )
    result = stream.read(
        path, raw_hash.hexdigest(), directory=tmp_path, retain=False, **kwargs
    )
    mapping = result["input_sha256"]
    assert type(mapping) is stream.ShaMap
    assert len(mapping) == 164833
    assert mapping.verify()["canonical_sha256"] == expected_map.hexdigest()
    assert stream.digest(result) == expected_root.hexdigest()
    assert mapping["/synthetic/" + "x" * 40 + "/000000"] == sha256(b"0").hexdigest()
    assert (
        mapping["/synthetic/" + "x" * 40 + "/164832"] == sha256(b"164832").hexdigest()
    )
    assert sum(1 for _ in mapping.items()) == 164833
    assert stream.authenticate(path, raw_hash.hexdigest())[2] == path.stat().st_size
