"""Collection preserves required OI independently of optional diagnostics.

These offline journeys use synthetic transport, the actual collector, real
Parquet, the unchanged dashboard reader and query-only CLI. They do not prove
provider coverage, OI effective time, dealer positioning or predictive value.
"""

import io
import json
import math
import socket
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, timedelta

import pytest

from backend.cli import market_options
from backend.market import live_technical, options
from backend.market.store import MarketStore

TODAY = date(2026, 9, 25)
SYMBOL = "SYNTH"
MISSING = object()
OPTIONALS = {"volume": "volume", "iv": "implied_volatility", "gamma": "gamma"}
VALID_LINE = (
    "SYNTH  price   100.00  expiry 2026-10-16  "
    "put wall 95 (1,000 OI)           call wall 105 (1,000 OI)          "
    "dealer gamma +1,000 shares per 1%\n"
)


# Detect attempted network calls even if a production fallback swallows an error.
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts = []

    # Keep forbidden connection diagnostics free of endpoints or credentials.
    def refuse(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("Collection contract tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    assert attempts == []


# Supply a complete two-sided chain whose asymmetric gamma exposes partial sums.
def _payload():
    return {
        "data": {
            "current_price": 100.0,
            "options": [
                {
                    "option": "SYNTH261016P00095000",
                    "open_interest": 1000,
                    "volume": 1,
                    "iv": 0.5,
                    "gamma": 0.01,
                },
                {
                    "option": "SYNTH261016C00105000",
                    "open_interest": 1000,
                    "volume": 1,
                    "iv": 0.5,
                    "gamma": 0.02,
                },
            ],
        }
    }


# Mutate one reported field while distinguishing omission from explicit null.
def _set(record, key, value):
    if value is MISSING:
        record.pop(key, None)
    else:
        record[key] = value


# Exercise transport through immutable Parquet with bounded recorded pacing.
def _collect(root, payload, *, status=200, body=None, error=None):
    calls, sleeps = [], []

    # Return only synthetic provider bytes and record every collection attempt.
    def transport(url):
        calls.append(url)
        assert url == options.CHAIN_URL.format(ticker=SYMBOL)
        if error is not None:
            raise error
        return status, {}, json.dumps(payload).encode() if body is None else body

    output = io.StringIO()
    store = MarketStore(root)
    with redirect_stdout(output):
        result = market_options.refresh(
            store, (SYMBOL,), TODAY, transport=transport, sleep=sleeps.append
        )
    return store, result, calls, sleeps, output.getvalue()


# Compare all file bytes to detect unexpected writes, removals or sidecars.
def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


# Run the public query-only CLI, keeping every stored byte and fetch observable.
def _query(root, monkeypatch, *, book=False):
    before = _files(root)
    attempts = []

    # Guard native provider boundaries as well as Python sockets and disk bytes.
    def forbidden(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Query-only options must not collect or write")

    argv = [
        "market_options",
        "--data-dir",
        str(root),
        "--asof",
        TODAY.isoformat(),
    ]
    argv += ["--walls-book"] if book else ["--walls", SYMBOL.lower()]
    output = io.StringIO()
    with monkeypatch.context() as scoped:
        scoped.setattr(sys, "argv", argv)
        scoped.setattr(market_options, "build_universe", lambda: ())
        scoped.setattr(market_options, "book_sides", lambda universe: {SYMBOL: "long"})
        scoped.setattr(market_options, "refresh", forbidden)
        scoped.setattr(market_options, "impersonating_transport", forbidden)
        scoped.setattr(options, "fetch_chain", forbidden)
        scoped.setattr(options, "fetch_collection", forbidden, raising=False)
        scoped.setattr(MarketStore, "write_frame", forbidden)
        with redirect_stdout(output):
            market_options.main()
    assert attempts == []
    assert _files(root) == before
    return output.getvalue()


# The unchanged dashboard reads both OI levels using its independent raw price.
def _assert_dashboard(store):
    before = _files(store.root)
    found = live_technical._walls_for(store, SYMBOL, 100.0, TODAY)
    assert (found["put_wall"], found["put_wall_oi"]) == (95.0, 1000)
    assert (found["call_wall"], found["call_wall_oi"]) == (105.0, 1000)
    assert _files(store.root) == before


# Metadata has a fixed schema, fixed statuses and bounded counts, never raw values.
def _assert_metadata(metadata, rows=2, *, price=True):
    keys = {"collection_schema", "required_rows", "price_status", "source_time"}
    if price:
        keys.add("price")
    for column in OPTIONALS.values():
        keys.update(
            f"{column}_{state}" for state in ("available", "missing", "invalid")
        )
        counts = [
            int(metadata[f"{column}_{state}"])
            for state in ("available", "missing", "invalid")
        ]
        assert sum(counts) == rows
        assert all(0 <= count <= rows for count in counts)
    assert set(metadata) == keys
    assert metadata["collection_schema"] == "options-collection-v1"
    assert metadata["required_rows"] == str(rows)
    assert metadata["price_status"] in {"available", "missing", "invalid"}
    assert len(json.dumps(metadata)) < 1024


# Every isolated optional defect retains the row and only nulls its own cell.
@pytest.mark.parametrize("book", [False, True])
@pytest.mark.parametrize("field", OPTIONALS)
@pytest.mark.parametrize(
    "value",
    [MISSING, None, "invalid-private-value", math.nan, math.inf, -math.inf, [], True],
)
def test_optional_defect_survives_collection_and_both_readers(
    tmp_path, monkeypatch, field, value, book
):
    payload = _payload()
    _set(payload["data"]["options"][0], field, value)
    store, result, calls, sleeps, output = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    assert sleeps == [market_options.PACE_SECONDS]
    assert "invalid-private-value" not in output
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["open_interest"] == [1000, 1000]
    assert {len(column) for column in columns.values()} == {2}
    assert columns[OPTIONALS[field]][0] is None
    for source, column in OPTIONALS.items():
        assert columns[column][1] == payload["data"]["options"][1][source]
        if source != field:
            assert columns[column][0] == payload["data"]["options"][0][source]
    _assert_metadata(metadata)
    state = "missing" if value is MISSING or value is None else "invalid"
    assert metadata[f"{OPTIONALS[field]}_{state}"] == "1"
    _assert_dashboard(store)
    line = _query(tmp_path, monkeypatch, book=book)
    assert "95 (1,000 OI)" in line
    assert "105 (1,000 OI)" in line
    if field == "gamma":
        assert "dealer gamma unavailable" in line
        assert "+2,000" not in line
        assert "+0 shares" not in line
    else:
        assert line == VALID_LINE


# Reported zero optionals and OI remain observations, never missing-value sentinels.
@pytest.mark.parametrize("field", OPTIONALS)
def test_zero_optional_values_and_oi_remain_reported(tmp_path, monkeypatch, field):
    payload = _payload()
    for row in payload["data"]["options"]:
        row[field] = 0
    payload["data"]["options"][0]["open_interest"] = 0
    store, result, calls, sleeps, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    assert sleeps == [market_options.PACE_SECONDS]
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["open_interest"] == [0, 1000]
    assert columns[OPTIONALS[field]] == [0, 0]
    assert metadata[f"{OPTIONALS[field]}_available"] == "2"
    assert metadata[f"{OPTIONALS[field]}_missing"] == "0"
    assert metadata[f"{OPTIONALS[field]}_invalid"] == "0"
    _assert_metadata(metadata)
    line = _query(tmp_path, monkeypatch)
    expected_gamma = "+0" if field == "gamma" else "+2,000"
    assert f"dealer gamma {expected_gamma} shares per 1%" in line
    assert "unavailable" not in line


# Pin IEEE-754 results from the original loop, including cancellation and association.
@pytest.mark.parametrize(
    ("gammas", "oi", "price", "expected"),
    [
        ([1e13, 1e-5, -1e13], 1, 100.0, "0x0.0p+0"),
        ([1e13, -1e13, 1e-5], 1, 100.0, "0x1.0624dd2f1a9fcp-10"),
        ([0.1], 999, 1.0001, "0x1.8fa3d46b26bf8p+6"),
    ],
)
def test_gamma_preserves_fixed_original_operation_order(gammas, oi, price, expected):
    rows = [options.OIRow(date(2026, 10, 16), "call", 105.0, oi) for _ in gammas]
    # These literals were captured from source-options.py, SHA256 9a303276f6d9367c.
    # Reordering accumulation or cancelling the *100 and *0.01 changes a result.
    assert options.gamma_from_frame({"gamma": gammas}, rows, price).hex() == expected
    legacy = [
        options.ChainRow(row.expiry, row.kind, row.strike, oi, 1, 0.5, gamma)
        for row, gamma in zip(rows, gammas, strict=True)
    ]
    assert options.walls(legacy, price, TODAY).net_gamma.hex() == expected


# All-null optional columns must survive Arrow inference without losing required OI.
def test_all_optional_fields_unavailable_round_trip(tmp_path, monkeypatch):
    payload = _payload()
    for row in payload["data"]["options"]:
        for field in OPTIONALS:
            row.pop(field)
    store, result, calls, sleeps, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    assert sleeps == [market_options.PACE_SECONDS]
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["open_interest"] == [1000, 1000]
    for column in OPTIONALS.values():
        assert columns[column] == [None, None]
        assert metadata[f"{column}_missing"] == "2"
    _assert_metadata(metadata)
    _assert_dashboard(store)
    assert "dealer gamma unavailable" in _query(tmp_path, monkeypatch)


# Unavailable chain prices do not block OI storage or create synthetic CLI levels.
@pytest.mark.parametrize(
    "value", [MISSING, None, "invalid-private-value", "NaN", math.inf, 0, -1, True, []]
)
def test_unavailable_underlying_preserves_oi_but_withholds_cli_levels(
    tmp_path, monkeypatch, value
):
    payload = _payload()
    _set(payload["data"], "current_price", value)
    store, result, calls, sleeps, output = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    assert sleeps == [market_options.PACE_SECONDS]
    assert "invalid-private-value" not in output
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["open_interest"] == [1000, 1000]
    _assert_metadata(metadata, price=False)
    assert metadata["price_status"] == (
        "missing" if value is MISSING or value is None else "invalid"
    )
    _assert_dashboard(store)
    line = _query(tmp_path, monkeypatch)
    assert "price unavailable" in line
    assert "levels unavailable" in line
    assert "dealer gamma unavailable" in line
    assert "0.00" not in line
    assert "nan" not in line.lower()


# A bad eligible OI value invalidates the whole collection instead of a partial save.
@pytest.mark.parametrize(
    "value",
    [
        MISSING,
        None,
        "invalid-private-value",
        "",
        True,
        -1,
        1.5,
        "1.5",
        math.nan,
        math.inf,
        2**63,
        float(2**63),
        [],
        {},
    ],
)
def test_bad_required_oi_fails_whole_chain_explicitly(tmp_path, value):
    payload = _payload()
    _set(payload["data"]["options"][0], "open_interest", value)
    store, result, calls, sleeps, output = _collect(tmp_path, payload)
    assert result == (0, [SYMBOL])
    assert len(calls) == 3
    assert sleeps == [8.0, 16.0, 24.0, market_options.PACE_SECONDS]
    assert store.read_frame(options.KIND, SYMBOL) is None
    assert _files(tmp_path) == {}
    assert "invalid_required_open_interest" in output
    assert "invalid-private-value" not in output
    assert len(output) < 512


# Accepted integer shapes retain their exact magnitude and distinguish reported zero.
@pytest.mark.parametrize(
    "value", [0, 1000, 1000.0, "1000", " 1000 ", 2**53 + 1, 2**63 - 1]
)
def test_required_integer_values_are_exact_not_float_rounded(tmp_path, value):
    payload = _payload()
    payload["data"]["options"][0]["open_interest"] = value
    store, result, calls, _, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    columns, _ = store.read_frame(options.KIND, SYMBOL)
    assert columns["open_interest"] == [int(value), 1000]


# Missing eligibility cannot be treated as an out-of-horizon contract to skip.
@pytest.mark.parametrize(
    "contract",
    [
        None,
        [],
        {},
        {"option": "invalid-private-value"},
        {"option": "SYNTH261016P00095000\n", "open_interest": 1000},
        {"option": "SYNTH261332P00095000"},
        {"option": "SYNTH261016X00095000"},
        {"option": "SYNTH261016P00000000", "open_interest": 1000},
    ],
)
def test_malformed_required_contract_cannot_create_successful_partial_chain(
    tmp_path, contract
):
    payload = _payload()
    payload["data"]["options"][0] = contract
    store, result, calls, _, output = _collect(tmp_path, payload)
    assert result == (0, [SYMBOL])
    assert len(calls) == 3
    assert store.read_frame(options.KIND, SYMBOL) is None
    assert "invalid_required_" in output
    assert "invalid-private-value" not in output
    assert len(output) < 512


# Retention filters valid symbols before field admission at the unchanged endpoints.
def test_retention_still_skips_only_known_out_of_horizon_contracts(tmp_path):
    payload = _payload()
    for days in (-1, 0, 180, 181):
        expiry = TODAY + timedelta(days=days)
        payload["data"]["options"].append(
            {
                "option": f"SYNTH{expiry:%y%m%d}P00095000",
                "open_interest": 1000 if days in (0, 180) else "invalid-private-value",
            }
        )
    store, result, calls, _, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["expiry"] == [
        "2026-10-16",
        "2026-10-16",
        TODAY.isoformat(),
        (TODAY + timedelta(days=180)).isoformat(),
    ]
    _assert_metadata(metadata, rows=4)


# Existing complete and incomplete files are immutable and never relabelled complete.
@pytest.mark.parametrize("legacy_partial", [False, True])
def test_same_date_retry_preserves_bytes_and_does_not_fetch(tmp_path, legacy_partial):
    store = MarketStore(tmp_path)
    if legacy_partial:
        _, rows = options.parse_chain(_payload(), TODAY)
        assert store.write_frame(
            options.KIND,
            TODAY,
            SYMBOL,
            options.frame(rows[1:]),
            {"price": "100.0000", "source_time": "2026-09-25T12:00:00+00:00"},
        )
    else:
        payload = _payload()
        payload["data"]["options"][0]["iv"] = "invalid-private-value"
        _, result, _, _, _ = _collect(tmp_path, payload)
        assert result == (1, [])
    before = _files(tmp_path)
    _, result, calls, sleeps, output = _collect(tmp_path, _payload())
    assert result == (0, [])
    assert calls == sleeps == []
    assert output == "SYNTH  kept\n"
    assert _files(tmp_path) == before
    assert set(before) == {f"options/asof={TODAY}/{SYMBOL}.parquet"}
    if legacy_partial:
        assert "collection_schema" not in store.read_frame(options.KIND, SYMBOL)[1]


# Valid legacy parsers, frames, gamma math and both public query flags stay exact.
@pytest.mark.parametrize("book", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_fully_valid_legacy_and_new_cli_output_is_unchanged(
    tmp_path, monkeypatch, book, legacy
):
    payload = _payload()
    price, rows = options.parse_chain(payload, TODAY)
    assert options.rows_from_frame(options.frame(rows)) == rows
    assert options.walls(rows, price, TODAY).net_gamma == 1000.0
    assert options.fetch_chain(
        SYMBOL, lambda url: (200, {}, json.dumps(payload).encode()), TODAY
    ) == (price, rows)
    if legacy:
        store = MarketStore(tmp_path)
        assert store.write_frame(
            options.KIND, TODAY, SYMBOL, options.frame(rows), {"price": "100.0000"}
        )
    else:
        store, result, calls, _, output = _collect(tmp_path, payload)
        assert result == (1, [])
        assert len(calls) == 1
        assert output == "SYNTH  ok     2 contracts at 100.00\n"
        _assert_metadata(store.read_frame(options.KIND, SYMBOL)[1])
    assert _query(tmp_path, monkeypatch, book=book) == VALID_LINE


# Gamma completeness is all stored rows, including contracts outside the OI window.
@pytest.mark.parametrize("gamma", [None, math.nan, math.inf, 1e308, -0.03, 0.0])
def test_gamma_scope_and_numerical_order_remain_legacy_compatible(
    tmp_path, monkeypatch, gamma
):
    payload = _payload()
    extra = deepcopy(payload["data"]["options"][1])
    extra["option"] = "SYNTH261225C00105000"
    extra["gamma"] = gamma
    payload["data"]["options"].append(extra)
    _, result, calls, _, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    line = _query(tmp_path, monkeypatch)
    if gamma is None or not math.isfinite(gamma) or gamma == 1e308:
        assert "dealer gamma unavailable" in line
    else:
        price, rows = options.parse_chain(payload, TODAY)
        expected = options.walls(rows, price, TODAY).net_gamma
        assert f"dealer gamma {expected:+,.0f} shares per 1%" in line
    assert "95 (1,000 OI)" in line
    assert "105 (1,000 OI)" in line


# Volume has an integer range; invalid magnitude never corrupts otherwise valid rows.
@pytest.mark.parametrize("volume", [-1, 1.5, 2**63])
def test_invalid_optional_volume_never_truncates_or_overflows_storage(
    tmp_path, monkeypatch, volume
):
    payload = _payload()
    payload["data"]["options"][0]["volume"] = volume
    store, result, calls, _, _ = _collect(tmp_path, payload)
    assert result == (1, [])
    assert len(calls) == 1
    columns, metadata = store.read_frame(options.KIND, SYMBOL)
    assert columns["volume"] == [None, 1]
    assert metadata["volume_invalid"] == "1"
    assert _query(tmp_path, monkeypatch) == VALID_LINE


# A required-only legacy frame is readable without inventing optional observations.
@pytest.mark.parametrize("missing_price", [False, True])
def test_required_only_legacy_frames_remain_queryable_read_only(
    tmp_path, monkeypatch, missing_price
):
    _, rows = options.parse_chain(_payload(), TODAY)
    columns = options.frame(rows)
    for column in OPTIONALS.values():
        columns.pop(column)
    store = MarketStore(tmp_path)
    assert store.write_frame(
        options.KIND,
        TODAY,
        SYMBOL,
        columns,
        {} if missing_price else {"price": "100.0000"},
    )
    _assert_dashboard(store)
    line = _query(tmp_path, monkeypatch)
    assert "dealer gamma unavailable" in line
    assert ("levels unavailable" in line) is missing_price
    assert ("95 (1,000 OI)" in line) is not missing_price


# Actual refusals and malformed containers stay bounded failures without saving rows.
@pytest.mark.parametrize(
    ("payload", "status", "body"),
    [
        (None, 200, None),
        ({"data": []}, 200, None),
        ({"data": {"options": {}}}, 200, None),
        ({"data": {"options": []}}, 200, None),
        ({}, 429, None),
        ({}, 200, b"invalid-private-value"),
    ],
)
def test_transport_or_chain_failure_is_bounded_and_sanitized(
    tmp_path, payload, status, body
):
    _, result, calls, sleeps, output = _collect(
        tmp_path, payload, status=status, body=body
    )
    assert result == (0, [SYMBOL])
    assert len(calls) == 3
    assert sleeps == [8.0, 16.0, 24.0, market_options.PACE_SECONDS]
    assert _files(tmp_path) == {}
    assert "invalid-private-value" not in output
    assert len(output) < 512


# Provider exception bodies are not safe console output even on bounded retries.
def test_provider_exception_does_not_log_raw_body(tmp_path):
    _, result, calls, _, output = _collect(
        tmp_path, {}, error=ValueError("invalid-private-value")
    )
    assert result == (0, [SYMBOL])
    assert len(calls) == 3
    assert "invalid-private-value" not in output
    assert len(output) < 512


# Malformed stored required data produces one explicit unavailable result, not a crash.
def test_invalid_required_legacy_frame_has_explicit_cli_outcome(tmp_path, monkeypatch):
    _, rows = options.parse_chain(_payload(), TODAY)
    columns = options.frame(rows)
    columns["open_interest"][0] = None
    store = MarketStore(tmp_path)
    assert store.write_frame(
        options.KIND, TODAY, SYMBOL, columns, {"price": "100.0000"}
    )
    line = _query(tmp_path, monkeypatch)
    assert "levels unavailable" in line
    assert "dealer gamma unavailable" in line
