"""Hash-bound, unit-preserving companyfacts inputs for isolated research.

No store, network, desk or collector is used. Projection is explicitly limited
to USD money, shares and USD/share EPS; it does not convert currencies or prove
price/share-class compatibility. Source-byte integrity is not authentication of
historical publication, SEC completeness or first-filed economic truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from backend.market import fundamentals_asof as fa

SCHEMA = "fundamental-unit-sources/1"
KIND = "edgar_facts_unit_sources"
PROJECTION = "USD-money_shares_USD-per-share/1"


@dataclass(frozen=True, slots=True)
class Exclusion:
    """One explicit source or projection exclusion without a fabricated value."""

    source_path: str
    name: str
    unit: str | None
    reason: str
    expected_unit: str | None = None


@dataclass(frozen=True, slots=True)
class UnitFact:
    """One original unit-labelled row, retaining duplicate source positions."""

    version: fa.Version
    unit: str
    source_path: str
    row_index: int
    duplicate_of: str | None = None


@dataclass(frozen=True, slots=True)
class UnitSource:
    """Immutable parsed observations bound to the complete supplied source bytes."""

    cik: int
    sha256: str
    body: bytes = field(repr=False)
    facts: tuple[UnitFact, ...]
    exclusions: tuple[Exclusion, ...]


@dataclass(frozen=True, slots=True)
class Projection:
    """Dimension-compatible legacy values with their retained source references."""

    versions: tuple[fa.Version, ...]
    accepted_facts: tuple[UnitFact, ...]
    exclusions: tuple[Exclusion, ...]


# Reject malformed source boundaries rather than silently coercing their meaning.
def _require(condition, message):
    if not condition:
        raise ValueError(message)


# Compare JSON types and values exactly, including numbers versus Booleans.
def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


# Refuse duplicate keys whose last value would otherwise hide conflicting evidence.
def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate source JSON key: {key}")
        result[key] = value
    return result


# Reject JSON's nonstandard nonfinite constants before interpreting financial rows.
def _constant(value):
    raise ValueError(f"nonfinite JSON constant: {value}")


# Retain an unambiguous JSON-pointer path even for slash-containing unit names.
def _path(*parts):
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


# Require original date-only strings without accepting compact or timestamp coercion.
def _day(value):
    _require(isinstance(value, str), "date must be text")
    parsed = date.fromisoformat(value)
    _require(parsed.isoformat() == value, "date must be YYYY-MM-DD")
    return parsed


# Validate a recognized row before reusing the legacy period and field vocabulary.
def _version(name, tag, row, instant):
    _require(isinstance(row, dict), "row_not_object")
    value = row.get("val")
    _require(type(value) in (int, float), "value_not_numeric")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, "value_not_finite")
    for key in ("accn", "form"):
        _require(
            isinstance(row.get(key), str) and bool(row[key].strip()), f"missing_{key}"
        )
    try:
        end, filed = _day(row.get("end")), _day(row.get("filed"))
        if instant:
            beginning = row.get("start")
            _require(beginning is None or beginning == "", "unsupported_period_shape")
        else:
            start = _day(row.get("start"))
            _require(fa.span_kind(start, end) is not None, "unsupported_period")
    except (TypeError, ValueError) as exc:
        if str(exc).startswith("unsupported_period"):
            raise
        raise ValueError("invalid_period_or_filing_date") from exc
    _require(end <= filed, "period_end_after_filed")
    if "accepted" in row:
        stamp = row["accepted"]
        _require(isinstance(stamp, str) and bool(stamp), "invalid_acceptance_timestamp")
        try:
            accepted = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid_acceptance_timestamp") from exc
        _require(
            accepted.tzinfo is not None and accepted.utcoffset() is not None,
            "acceptance_timezone_missing",
        )
        try:
            accepted_day = accepted.astimezone(fa.NEW_YORK).date()
        except OverflowError as exc:
            raise ValueError("availability_date_out_of_range") from exc
        _require(accepted_day >= end, "acceptance_precedes_period_end")
    version = fa._version(name, tag, row, instant)
    _require(version is not None, "unsupported_period")
    try:
        _availability = version.available
    except OverflowError as exc:
        raise ValueError("availability_date_out_of_range") from exc
    return version


# Preserve same-source duplicates but reject contradictory facts for one accession/span.
def _fact(name, tag, unit, row, index, path, instant, seen):
    version = _version(name, tag, row, instant)
    key = (name, tag, unit, version.start, version.end, version.accession)
    prior = seen.get(key)
    if prior is not None:
        _require(version == prior.version, f"conflicting source observation: {path}")
    fact = UnitFact(
        version, unit, path, index, None if prior is None else prior.source_path
    )
    seen.setdefault(key, fact)
    return fact


# Extract every recognized unit group without whole-history unit selection.
def parse(body: bytes, *, expected_sha256: str, expected_cik: int) -> UnitSource:
    _require(type(body) is bytes and bool(body), "nonempty original bytes are required")
    _require(
        type(expected_cik) is int and 0 < expected_cik < 10**10, "invalid expected CIK"
    )
    digest = hashlib.sha256(body).hexdigest()
    _require(digest == expected_sha256, "source byte hash mismatch")
    try:
        payload = json.loads(body, object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid companyfacts JSON") from exc
    _require(isinstance(payload, dict), "companyfacts root must be an object")
    _require(
        type(payload.get("cik")) is int and payload["cik"] == expected_cik,
        "source CIK mismatch",
    )
    root = payload.get("facts")
    _require(isinstance(root, dict), "facts must be an object")
    facts, exclusions, seen = [], [], {}
    for name, taxonomy, tag, instant in fa._candidates():
        namespace = root.get(taxonomy, {})
        _require(isinstance(namespace, dict), "taxonomy must be an object")
        if tag not in namespace:
            continue
        concept = namespace[tag]
        _require(isinstance(concept, dict), "concept must be an object")
        units = concept.get("units")
        base = _path("facts", taxonomy, tag, "units")
        if units is None or units == {}:
            exclusions.append(Exclusion(base, name, None, "missing_units"))
            continue
        _require(isinstance(units, dict), "units must be an object")
        for unit, rows in units.items():
            _require(isinstance(rows, list), "unit observations must be an array")
            for index, row in enumerate(rows):
                path = _path("facts", taxonomy, tag, "units", unit, index)
                if not unit or unit.strip() != unit:
                    exclusions.append(
                        Exclusion(path, name, None, "missing_or_invalid_unit")
                    )
                    continue
                try:
                    fact = _fact(
                        name, f"{taxonomy}:{tag}", unit, row, index, path, instant, seen
                    )
                except ValueError as exc:
                    if str(exc).startswith("conflicting source observation"):
                        raise
                    exclusions.append(Exclusion(path, name, unit, str(exc)))
                    continue
                facts.append(fact)
    return UnitSource(expected_cik, digest, body, tuple(facts), tuple(exclusions))


# Rebind caller-supplied dataclasses to their original source observations.
def _validated(source):
    _require(isinstance(source, UnitSource), "UnitSource is required")
    expected = parse(
        source.body, expected_sha256=source.sha256, expected_cik=source.cik
    )
    _require(source == expected, "UnitSource observations differ from original bytes")
    _require(
        _canonical(_columns(source)) == _canonical(_columns(expected)),
        "UnitSource observation types differ from original bytes",
    )
    return expected


# State dimensions explicitly without inferring any reporting or price currency.
def _expected_unit(name):
    return "shares" if name == "shares" else "USD/shares" if name == "eps" else "USD"


# Project only explicitly compatible units, retaining every excluded source reference.
def project(source: UnitSource) -> Projection:
    source = _validated(source)
    accepted, excluded = [], list(source.exclusions)
    for fact in source.facts:
        expected = _expected_unit(fact.version.name)
        if fact.unit == expected:
            accepted.append(fact)
        else:
            excluded.append(
                Exclusion(
                    fact.source_path,
                    fact.version.name,
                    fact.unit,
                    "unsupported_unit_for_projection",
                    expected,
                )
            )
    return Projection(
        tuple(fact.version for fact in accepted), tuple(accepted), tuple(excluded)
    )


# Flatten immutable evidence without losing its unit or exact original row position.
def _columns(source):
    columns = fa.frame([fact.version for fact in source.facts])
    columns.update(
        unit=[fact.unit for fact in source.facts],
        source_path=[fact.source_path for fact in source.facts],
        row_index=[fact.row_index for fact in source.facts],
        duplicate_of=[fact.duplicate_of or "" for fact in source.facts],
    )
    return columns


# Bind the separate frame schema and exclusion summary to original source bytes.
def _metadata(source):
    exclusions = [
        [item.source_path, item.name, item.unit, item.reason]
        for item in source.exclusions
    ]
    return {
        "schema": SCHEMA,
        "source_sha256": source.sha256,
        "cik": str(source.cik),
        "source_bytes": str(len(source.body)),
        "facts": str(len(source.facts)),
        "exclusions": str(len(exclusions)),
        "exclusions_sha256": hashlib.sha256(
            _canonical(exclusions).encode()
        ).hexdigest(),
    }


# Return fresh frame containers; persistence remains an explicit caller-owned operation.
def frame(source: UnitSource) -> tuple[dict, dict]:
    source = _validated(source)
    return _columns(source), _metadata(source)


# Authenticate a frame by re-extraction, never by relabelling old rows.
def from_frame(
    columns: Mapping, metadata: Mapping, *, source_body: bytes
) -> UnitSource:
    _require(
        isinstance(columns, Mapping) and isinstance(metadata, Mapping),
        "frame mappings are required",
    )
    _require(
        metadata.get("schema") == SCHEMA, "unit-source schema is missing or unsupported"
    )
    _require("unit" in columns, "explicit unit column is required")
    try:
        cik = metadata["cik"]
        _require(
            isinstance(cik, str) and cik.isascii() and cik.isdigit(),
            "invalid frame CIK",
        )
        source = parse(
            source_body,
            expected_sha256=metadata["source_sha256"],
            expected_cik=int(cik),
        )
        _require(
            _canonical(dict(metadata)) == _canonical(_metadata(source)),
            "frame metadata differs from source",
        )
        _require(
            _canonical(dict(columns)) == _canonical(_columns(source)),
            "frame observations differ from source",
        )
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("malformed unit-source frame") from exc
    return source
