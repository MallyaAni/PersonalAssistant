"""Admit SEC's canonical text CIK without weakening source or financial integrity.

The unchanged September 25 current-source packet admitted 82 of 94 issuers.
The other twelve carried numerically matching, zero-padded ten-character CIKs;
their original bytes remain retained outside this synthetic regression suite.
"""

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from backend.market import fundamental_unit_sources as units


# Provide financial observations whose extraction cannot depend on CIK representation.
def _payload(cik):
    row = {
        "start": "2025-01-01",
        "end": "2025-03-31",
        "val": 100,
        "filed": "2025-05-01",
        "accn": "original",
        "form": "10-Q",
    }
    instant = {key: value for key, value in row.items() if key != "start"}
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [row, dict(row), dict(row, val=True, accn="invalid")],
                        "EUR": [dict(row, val=90)],
                    }
                },
                "GrossProfit": {"units": {"USD": [dict(row, val=50)]}},
                "EarningsPerShareDiluted": {
                    "units": {"USD/shares": [dict(row, val=1.25)]}
                },
                "CommonStockSharesOutstanding": {
                    "units": {"shares": [dict(instant, val=10)]}
                },
            }
        },
    }


# Bind exact synthetic bytes without canonicalizing the original source CIK field.
def _body(cik):
    return json.dumps(_payload(cik), ensure_ascii=False, allow_nan=False).encode()


# Authenticate the supplied body independently of its source CIK representation.
def _parse(body, expected_cik):
    return units.parse(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        expected_cik=expected_cik,
    )


# Preserve bytes, financial rows and canonical metadata across all public paths.
@pytest.mark.parametrize("cik", [1, 123456, 1144879, 2058873, 9999999999])
@pytest.mark.parametrize("text", [False, True])
def test_integer_and_exact_ten_digit_source_identity_round_trip(cik, text):
    original_cik = f"{cik:010d}" if text else cik
    body = _body(original_cik)
    digest = hashlib.sha256(body).hexdigest()
    source = _parse(body, cik)
    projection = units.project(source)
    columns, metadata = units.frame(source)
    restored = units.from_frame(columns, metadata, source_body=body)

    assert source == restored
    assert source.body is body
    assert source.sha256 == digest == hashlib.sha256(body).hexdigest()
    assert type(source.cik) is int
    assert source.cik == cik
    assert json.loads(source.body)["cik"] == original_cik
    assert type(json.loads(source.body)["cik"]) is type(original_cik)
    assert [
        (fact.version.name, fact.unit, fact.version.value) for fact in source.facts
    ] == [
        ("revenue", "USD", 100),
        ("revenue", "USD", 100),
        ("revenue", "EUR", 90),
        ("eps", "USD/shares", 1.25),
        ("gross_profit", "USD", 50),
        ("shares", "shares", 10),
    ]
    assert source.facts[1].duplicate_of == source.facts[0].source_path
    assert [fact.unit for fact in projection.accepted_facts] == [
        "USD",
        "USD",
        "USD/shares",
        "USD",
        "shares",
    ]
    assert [item.reason for item in projection.exclusions] == [
        "value_not_numeric",
        "unsupported_unit_for_projection",
    ]
    exclusion = [
        ["/facts/us-gaap/Revenues/units/USD/2", "revenue", "USD", "value_not_numeric"]
    ]
    assert metadata == {
        "schema": "fundamental-unit-sources/1",
        "source_sha256": digest,
        "cik": str(cik),
        "source_bytes": str(len(body)),
        "facts": "6",
        "exclusions": "1",
        "exclusions_sha256": hashlib.sha256(
            json.dumps(exclusion, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    assert columns["unit"] == ["USD", "USD", "EUR", "USD/shares", "USD", "shares"]
    assert columns["value"] == [100, 100, 90, 1.25, 50, 10]


# Only byte identity metadata may differ between the two legal source shapes.
@pytest.mark.parametrize("cik", [1, 123456, 1144879, 2058873, 9999999999])
def test_source_shape_does_not_change_financial_extraction_or_projection(cik):
    integer = _parse(_body(cik), cik)
    padded = _parse(_body(f"{cik:010d}"), cik)
    assert integer.facts == padded.facts
    assert integer.exclusions == padded.exclusions
    assert units.project(integer) == units.project(padded)
    integer_columns, integer_metadata = units.frame(integer)
    padded_columns, padded_metadata = units.frame(padded)
    assert integer_columns == padded_columns
    for key in ("source_sha256", "source_bytes"):
        integer_metadata.pop(key)
        padded_metadata.pop(key)
    assert integer_metadata == padded_metadata
    assert integer.body != padded.body
    assert integer.sha256 != padded.sha256


# Reject ambiguous source shapes even when a permissive conversion yields one.
@pytest.mark.parametrize(
    "source_cik",
    [
        True,
        False,
        1.0,
        0,
        -1,
        10**10,
        None,
        [],
        {},
        "1",
        "000000001",
        "00000000001",
        "0000000000",
        "0000000002",
        "+000000001",
        "-000000001",
        " 000000001",
        "000000001 ",
        "000000001\n",
        "\t000000001",
        "00000001e0",
        "00000001.0",
        "000000001_",
        "0x00000001",
        "０００００００００１",
        "٠٠٠٠٠٠٠٠٠١",
        "000000000¹",
        "000000000\x00",
        "",
    ],
)
def test_noncanonical_or_wrong_source_identity_is_rejected(source_cik):
    with pytest.raises(ValueError, match="source CIK mismatch"):
        _parse(_body(source_cik), 1)


# Keep the expected identity a bounded positive integer, never a coercion target.
@pytest.mark.parametrize(
    "expected", [True, False, 1.0, "1", "0000000001", 0, -1, 10**10, None, [], {}]
)
@pytest.mark.parametrize("source_cik", [1, "0000000001"])
def test_expected_identity_remains_strict_for_both_source_shapes(expected, source_cik):
    with pytest.raises(ValueError, match="invalid expected CIK"):
        _parse(_body(source_cik), expected)


# Validly shaped identifiers must still match the exact expected issuer.
@pytest.mark.parametrize("source_cik", [2, "0000000002", 9999999999, "9999999999"])
def test_other_valid_issuer_is_rejected(source_cik):
    with pytest.raises(ValueError, match="source CIK mismatch"):
        _parse(_body(source_cik), 1)


# Missing source identity is not inferred from the request or from the financial data.
def test_missing_source_identity_is_rejected():
    payload = _payload(1)
    del payload["cik"]
    with pytest.raises(ValueError, match="source CIK mismatch"):
        _parse(json.dumps(payload).encode(), 1)


# Conflicting or repeated JSON keys cannot hide a different source identifier.
@pytest.mark.parametrize("second", [b'"0000000001"', b'"0000000002"'])
def test_duplicate_source_identity_keys_remain_rejected(second):
    body = b'{"cik":1,"cik":' + second + b',"facts":{}}'
    with pytest.raises(ValueError, match="duplicate source JSON key: cik"):
        _parse(body, 1)


# Admitting a canonical text CIK must not bypass the unchanged financial root boundary.
@pytest.mark.parametrize("source_cik", [1, "0000000001"])
def test_valid_identity_still_requires_financial_object(source_cik):
    body = json.dumps({"cik": source_cik, "facts": []}).encode()
    with pytest.raises(ValueError, match="facts must be an object"):
        _parse(body, 1)


# Revalidating admitted text sources must still reject altered identity, bytes or facts.
@pytest.mark.parametrize("operation", [units.project, units.frame])
@pytest.mark.parametrize("change", ["issuer", "hash", "body", "value"])
def test_padded_source_dataclass_tampering_is_rejected(operation, change):
    source = _parse(_body("0001144879"), 1144879)
    if change == "issuer":
        altered = replace(source, cik=1144880)
    elif change == "hash":
        altered = replace(source, sha256="0" * 64)
    elif change == "body":
        altered = replace(source, body=_body(1144879))
    else:
        fact = replace(
            source.facts[0], version=replace(source.facts[0].version, value=999)
        )
        altered = replace(source, facts=(fact, *source.facts[1:]))
    errors = {
        "issuer": "source CIK mismatch",
        "hash": "source byte hash mismatch",
        "body": "source byte hash mismatch",
        "value": "UnitSource observations differ from original bytes",
    }
    with pytest.raises(ValueError, match=errors[change]):
        operation(altered)


# Authenticate original bytes on frame readback and retain the metadata schema.
@pytest.mark.parametrize(
    "change", ["issuer", "padded_metadata", "hash", "value", "unit", "body"]
)
def test_padded_source_frame_tampering_is_rejected(change):
    source = _parse(_body("0001144879"), 1144879)
    columns, metadata = copy.deepcopy(units.frame(source))
    body = source.body
    if change == "issuer":
        metadata["cik"] = "1144880"
    elif change == "padded_metadata":
        metadata["cik"] = "0001144879"
    elif change == "hash":
        metadata["source_sha256"] = "0" * 64
    elif change == "value":
        columns["value"][0] = 999
    elif change == "unit":
        columns["unit"][0] = "EUR"
    else:
        body = _body(1144879)
    errors = {
        "issuer": "source CIK mismatch",
        "padded_metadata": "frame metadata differs from source",
        "hash": "source byte hash mismatch",
        "body": "source byte hash mismatch",
        "value": "frame observations differ from source",
        "unit": "frame observations differ from source",
    }
    with pytest.raises(ValueError, match=errors[change]):
        units.from_frame(columns, metadata, source_body=body)
