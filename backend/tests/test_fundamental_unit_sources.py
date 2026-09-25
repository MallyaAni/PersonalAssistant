"""Source-bound unit ingestion, isolated from the legacy live/cache contracts.

Legacy failures were reproduced by the root on 2026-09-25 at 00f3102:
/private/tmp/anios-fundamental-units.pkKxBnJd/test_unit_boundary.py and baseline.xml.
They remain strict xfails; the new adapter does not claim to repair old data.
"""

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa


# Supply four quarter spans with explicit source values and publication fields.
def _rows():
    return [
        {
            "start": start,
            "end": end,
            "val": value,
            "filed": filed,
            "accn": str(index),
            "form": "10-Q",
        }
        for index, (start, end, value, filed) in enumerate(
            (
                ("2025-01-01", "2025-03-31", 100, "2025-05-01"),
                ("2025-04-01", "2025-06-30", 110, "2025-08-01"),
                ("2025-07-01", "2025-09-30", 120, "2025-11-01"),
                ("2025-10-01", "2025-12-31", 130, "2026-02-15"),
            )
        )
    ]


# Keep each unit's observations separate under one recognized source concept.
def _payload(groups=None):
    return {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": _rows()} if groups is None else groups,
                }
            }
        },
    }


# Bind the exact fixture bytes to their expected source hash before extraction.
def _parse(payload):
    body = json.dumps(payload, allow_nan=False).encode()
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Add a larger alternate-currency group unavailable at the earlier decision.
def _future_case():
    base = _payload()
    future = copy.deepcopy(base)
    alternate = [
        dict(row, filed="2027-05-01", val=1000 + index)
        for index, row in enumerate(_rows())
    ]
    alternate.append(dict(_rows()[-1], filed="2027-05-02", val=1005, accn="later"))
    future["facts"]["us-gaap"]["Revenues"]["units"]["EUR"] = alternate
    return base, future


# Retain the legacy defect while testing its separate replacement explicitly.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Reproduced 2026-09-25 baseline.xml: legacy largest-unit selection "
        "erases earlier USD quarters"
    ),
)
def test_legacy_future_unit_rows_do_not_change_earlier_levels():
    base, future = _future_case()
    dates = np.array(["2026-03-02"], dtype="datetime64[D]")
    before = fa.levels_for(fa.parse_versions(base), dates)["revenue"]
    after = fa.levels_for(fa.parse_versions(future), dates)["revenue"]
    assert before.tolist() == [460.0]
    np.testing.assert_array_equal(after, before)


# Unit loss in the legacy persisted representation is retained as an unfixed finding.
@pytest.mark.xfail(
    strict=True,
    reason="Reproduced 2026-09-25 baseline.xml: legacy Version/frame omit source units",
)
def test_legacy_stored_versions_retain_source_unit():
    columns = fa.frame(fa.parse_versions(_payload()))
    assert columns.get("unit") == ["USD"] * 4


# Keep future non-USD evidence without altering an earlier USD projection.
def test_future_unit_rows_preserve_actual_legacy_consumer_levels():
    base, future = map(_parse, _future_case())
    before, after = units.project(base), units.project(future)
    dates = np.array(["2026-03-02", "2027-05-03"], dtype="datetime64[D]")
    np.testing.assert_array_equal(
        fa.levels_for(before.versions, dates)["revenue"],
        fa.levels_for(after.versions, dates)["revenue"],
    )
    assert fa.levels_for(after.versions, dates)["revenue"].tolist() == [460.0, 460.0]
    assert len(future.facts) == 9
    assert len(after.versions) == 4
    assert [item.unit for item in after.exclusions] == ["EUR"] * 5
    assert all(item.expected_unit == "USD" for item in after.exclusions)


# Separate units even when their accession and fiscal period match.
def test_mixed_currency_rows_keep_both_values_and_source_paths():
    source = _parse(_payload({"EUR": [dict(_rows()[0], val=90)], "USD": [_rows()[0]]}))
    assert [(fact.unit, fact.version.value) for fact in source.facts] == [
        ("EUR", 90),
        ("USD", 100),
    ]
    projected = units.project(source)
    assert [version.value for version in projected.versions] == [100]
    assert projected.exclusions[0].source_path.endswith("/EUR/0")
    assert projected.accepted_facts[0].source_path.endswith("/USD/0")


# Preserve shares and per-share earnings as distinct measurement dimensions.
def test_share_and_eps_dimensions_are_explicit():
    payload = _payload({})
    instant = {key: value for key, value in _rows()[0].items() if key != "start"}
    payload["facts"]["us-gaap"].update(
        {
            "CommonStockSharesOutstanding": {
                "units": {"shares": [instant], "USD": [instant]}
            },
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [_rows()[0]],
                    "EUR/shares": [_rows()[0]],
                    "USD": [_rows()[0]],
                }
            },
        }
    )
    source = _parse(payload)
    projection = units.project(source)
    assert {(fact.version.name, fact.unit) for fact in projection.accepted_facts} == {
        ("shares", "shares"),
        ("eps", "USD/shares"),
    }
    assert any("USD~1shares" in fact.source_path for fact in source.facts)
    assert len(projection.versions) == 2


# Instant facts cannot acquire meaning from a malformed falsy start field.
@pytest.mark.parametrize("start", [False, 0, [], {}])
def test_instant_start_rejects_nondate_falsy_values(start):
    payload = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "StockholdersEquity": {
                    "units": {"USD": [dict(_rows()[0], start=start)]},
                }
            }
        },
    }
    source = _parse(payload)
    assert source.facts == ()
    assert source.exclusions[0].reason == "unsupported_period_shape"


# Keep revisions separate until their own availability dates.
def test_every_filing_vintage_and_original_dates_survive_projection():
    rows = _rows() + [
        dict(_rows()[1], val=999, filed="2026-03-04", accn="revision", form="10-K/A")
    ]
    source = _parse(_payload({"USD": rows}))
    versions = units.project(source).versions
    dates = np.array(["2026-03-03", "2026-03-04", "2026-03-05"], dtype="datetime64[D]")
    assert len(versions) == 5
    assert fa.levels_for(versions, dates)["revenue"].tolist() == [460, 460, 1349]
    assert versions[-1].accession == "revision"
    assert str(versions[-1].filed) == "2026-03-04"


# Exact repeated rows remain auditable rather than being silently collapsed.
def test_exact_duplicate_source_rows_are_retained_with_their_first_path():
    row = _rows()[0]
    source = _parse(_payload({"USD": [row, row]}))
    assert len(source.facts) == len(units.project(source).versions) == 2
    assert source.facts[0].duplicate_of is None
    assert source.facts[1].duplicate_of == source.facts[0].source_path
    assert source.facts[1].row_index == 1


# One filing cannot provide contradictory values or clocks under the same fact identity.
@pytest.mark.parametrize(
    "change",
    [
        {"val": 101},
        {"filed": "2025-05-02"},
        {"form": "10-K"},
        {"accepted": "2025-05-01T12:00:00Z"},
    ],
)
def test_conflicting_same_accession_observations_are_rejected(change):
    row = _rows()[0]
    with pytest.raises(ValueError, match="conflicting source observation"):
        _parse(_payload({"USD": [row, dict(row, **change)]}))


# No accepted timestamp is invented when the source has only a filing date.
def test_missing_time_retains_fallback_and_aware_time_is_preserved():
    early = dict(_rows()[1], accepted="2025-08-01T09:00:00-04:00")
    source = _parse(_payload({"USD": [_rows()[0], early]}))
    assert source.facts[0].version.accepted is None
    assert str(source.facts[0].version.available) == "2025-05-02"
    assert source.facts[1].version.accepted.isoformat() == "2025-08-01T09:00:00-04:00"


# An after-hours acceptance may precede its assigned filing date without replacing it.
def test_acceptance_and_filing_dates_remain_distinct():
    row = dict(_rows()[0], filed="2025-05-02", accepted="2025-05-01T18:00:00-04:00")
    source = _parse(_payload({"USD": [row]}))
    version = units.project(source).versions[0]
    assert str(version.filed) == "2025-05-02"
    assert version.accepted.isoformat() == "2025-05-01T18:00:00-04:00"
    assert str(version.available) == "2025-05-02"


# Exclude unrepresentable availability before it can crash a reader.
@pytest.mark.parametrize(
    "dates",
    [
        {"end": "9999-12-30", "filed": "9999-12-31"},
        {
            "end": "0001-01-01",
            "filed": "0001-01-01",
            "accepted": "0001-01-01T00:00:00+14:00",
        },
    ],
)
def test_unrepresentable_availability_is_excluded(dates):
    row = {"val": 1, "accn": "original", "form": "10-Q", **dates}
    source = _parse(
        {
            "cik": 1,
            "facts": {
                "us-gaap": {
                    "StockholdersEquity": {
                        "units": {"USD": [row]},
                    }
                }
            },
        }
    )
    assert source.facts == ()
    assert source.exclusions[0].reason == "availability_date_out_of_range"


# Exclude malformed supplied timestamps instead of treating them as absent.
@pytest.mark.parametrize("accepted", ["", None, "bad", "2025-05-01T12:00:00"])
def test_invalid_explicit_acceptance_is_an_exclusion(accepted):
    source = _parse(_payload({"USD": [dict(_rows()[0], accepted=accepted)]}))
    assert source.facts == ()
    assert len(source.exclusions) == 1
    assert "acceptance" in source.exclusions[0].reason


# An acceptance timestamp cannot make a fiscal fact visible before its period ends.
def test_acceptance_before_fiscal_period_is_excluded():
    source = _parse(
        _payload({"USD": [dict(_rows()[0], accepted="2024-01-02T12:00:00Z")]})
    )
    assert source.facts == ()
    assert source.exclusions[0].reason == "acceptance_precedes_period_end"
    assert units.project(source).versions == ()


# Invalid numeric or period evidence is counted without manufacturing a financial fact.
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"val": True}, "value_not_numeric"),
        ({"val": "100"}, "value_not_numeric"),
        ({"val": None}, "value_not_numeric"),
        ({"start": "20250101"}, "invalid_period_or_filing_date"),
        ({"start": "2025-03-25"}, "unsupported_period"),
        ({"accn": ""}, "missing_accn"),
        ({"form": ""}, "missing_form"),
        ({"filed": "2025-01-01"}, "period_end_after_filed"),
    ],
)
def test_invalid_source_rows_have_explicit_reasons(change, reason):
    source = _parse(_payload({"USD": [dict(_rows()[0], **change)]}))
    assert source.facts == ()
    assert [item.reason for item in source.exclusions] == [reason]


# Numeric overflow in valid JSON remains an exclusion instead of reaching a consumer.
def test_overflowed_source_number_is_not_a_finite_fact():
    body = json.dumps(_payload()).replace('"val": 100', '"val": 1e999').encode()
    source = units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )
    assert len(source.facts) == 3
    assert source.exclusions[0].reason == "value_not_finite"


# Empty sources and absent units remain explicit and cannot acquire default USD facts.
def test_empty_and_missing_unit_evidence_roundtrips():
    empty = _parse({"cik": 1, "facts": {}})
    assert empty.facts == empty.exclusions == units.project(empty).versions == ()
    columns, metadata = units.frame(empty)
    assert units.from_frame(columns, metadata, source_body=empty.body) == empty
    missing = _parse(_payload({"": [_rows()[0]]}))
    assert missing.facts == ()
    assert missing.exclusions[0].reason == "missing_or_invalid_unit"
    assert units.project(missing).exclusions == missing.exclusions


# Check source hashes, issuer identity and JSON keys before extraction.
@pytest.mark.parametrize("case", ["hash", "cik", "boolean_cik", "duplicate", "nan"])
def test_source_envelope_rejects_ambiguous_or_mismatched_evidence(case):
    body = json.dumps(_payload()).encode()
    cik = 1
    if case == "cik":
        cik = 2
    elif case == "boolean_cik":
        body = body.replace(b'"cik": 1', b'"cik": true')
    elif case == "duplicate":
        body = body.replace(b'"cik": 1', b'"cik": 1, "cik": 1')
    elif case == "nan":
        body = body.replace(b'"val": 100', b'"val": NaN')
    digest = "0" * 64 if case == "hash" else hashlib.sha256(body).hexdigest()
    with pytest.raises(
        ValueError, match="hash mismatch|CIK mismatch|duplicate|nonfinite"
    ):
        units.parse(body, expected_sha256=digest, expected_cik=cik)


# Reauthenticate persisted Parquet units against the original raw body.
def test_persisted_frame_roundtrip_reauthenticates_original_source(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    source = _parse(_future_case()[1])
    columns, metadata = units.frame(source)
    path = tmp_path / "unit-source.parquet"
    table = pa.table(columns).replace_schema_metadata(
        {key.encode(): value.encode() for key, value in metadata.items()}
    )
    pq.write_table(table, path)
    stored = pq.read_table(path)
    saved_metadata = {
        key.decode(): value.decode() for key, value in stored.schema.metadata.items()
    }
    assert (
        units.from_frame(stored.to_pydict(), saved_metadata, source_body=source.body)
        == source
    )
    assert units.KIND != fa.KIND
    assert metadata["schema"] != fa.VERSION


# Reject unitless legacy frames and incompatible schema declarations.
@pytest.mark.parametrize(
    "case",
    [
        "missing_schema",
        "wrong_schema",
        "missing_unit",
        "legacy",
        "wrong_cik",
        "wrong_body",
    ],
)
def test_frame_requires_separate_schema_units_and_matching_source(case):
    source = _parse(_payload())
    columns, metadata = units.frame(source)
    body = source.body
    if case == "missing_schema":
        del metadata["schema"]
    elif case == "wrong_schema":
        metadata["schema"] = fa.VERSION
    elif case == "missing_unit":
        del columns["unit"]
    elif case == "legacy":
        columns = fa.frame(fa.parse_versions(_payload()))
        metadata = {"version": fa.VERSION}
    elif case == "wrong_cik":
        metadata["cik"] = "2"
    else:
        body += b" "
    with pytest.raises(
        ValueError, match="schema|unit column|CIK mismatch|hash mismatch"
    ):
        units.from_frame(columns, metadata, source_body=body)


# Reject currency relabelling and type coercion through raw-source replay.
@pytest.mark.parametrize(
    ("column", "replacement"),
    [("unit", "USD"), ("value", True), ("row_index", False), ("accession", "changed")],
)
def test_frame_cannot_self_relabel_or_coerce_source_observations(column, replacement):
    source = _parse(_payload({"EUR": [dict(_rows()[0], val=1)]}))
    columns, metadata = units.frame(source)
    columns[column][0] = replacement
    with pytest.raises(ValueError, match="observations differ"):
        units.from_frame(columns, metadata, source_body=source.body)


# Prevent returned containers from changing source-bound observations.
def test_source_projection_and_frame_are_immutable_and_independently_owned():
    payload = _payload()
    source = _parse(payload)
    baseline = units.project(source)
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] = 999
    columns, metadata = units.frame(source)
    columns["value"][0] = 999
    metadata["schema"] = "changed"
    assert units.project(source) == baseline
    with pytest.raises(FrozenInstanceError):
        source.facts[0].unit = "EUR"
    forged = replace(
        source, facts=(replace(source.facts[0], unit="EUR"), *source.facts[1:])
    )
    with pytest.raises(ValueError, match="differ from original bytes"):
        units.project(forged)


# Equal-comparing Boolean substitutions cannot pass an exact source-object check.
@pytest.mark.parametrize("field", ["value", "row_index"])
def test_caller_made_dataclass_types_must_match_raw_source(field):
    source = _parse(_payload({"USD": [dict(_rows()[0], val=1)]}))
    fact = source.facts[0]
    changed = (
        replace(fact, version=replace(fact.version, value=True))
        if field == "value"
        else replace(fact, row_index=False)
    )
    with pytest.raises(ValueError, match="types differ"):
        units.project(replace(source, facts=(changed,)))
