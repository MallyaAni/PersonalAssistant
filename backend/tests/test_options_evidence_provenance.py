"""Stored options provenance, separate clocks, and immutable cached HTTP reads.

Parquet, live-row/cache calculations, balancer persistence, bearer authorization,
and API projection are real. Analyst opinions, source quotes, and account inputs
are synthetic; no provider, model, database, or broker runtime is required.
Collection age does not establish the effective time or freshness of OI.
"""

import importlib
import json
import socket
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_balancer, market_event_recovery
from backend.market import desk_freshness, intraday_research, live_technical, options
from backend.market.store import MarketStore
from backend.tests.test_options_diagnostic_isolation import (
    _chain_rows,
    _evening_record,
    _synthetic_read,
)

TODAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
OLD_COLLECTION = "2026-09-01T12:45:00+00:00"
BAR_START = "2026-09-25T14:15:00+00:00"
VERSION = "raw-option-oi-levels/1"
METHOD = {
    "min_days": 1,
    "max_days": 60,
    "strike_range_fraction": 0.25,
    "min_open_interest": 500,
}
LEVEL_FIELDS = {
    "put_level",
    "call_level",
    "put_oi",
    "call_oi",
    "put_distance",
    "call_distance",
}
COMMON_FIELDS = {
    "checked_at",
    "collected_at",
    "collection_status",
    "collection_age_seconds",
    "oi_effective_at",
    "oi_freshness",
}


# Detect forbidden networking even if a production fallback catches the exception.
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts = []

    # Record only that a connection was attempted, never its address or credentials.
    def refuse(*args, **kwargs):
        attempts.append("network connection attempted")
        raise RuntimeError("Options provenance tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    assert attempts == []


# Import lazily so the pre-implementation baseline reports each missing boundary.
def _evidence_module():
    return importlib.import_module("backend.market.options_evidence")


# Record the agreed producer contract independently of its implementation helper.
def _calculation(*, price=100.0, bar=None, day=TODAY, session=TODAY):
    return {
        "version": VERSION,
        "date": day.isoformat(),
        "reference_price": price,
        "reference_basis": "raw_panel_close",
        "reference_session": session.isoformat(),
        "reference_bar_start": bar,
        "method": dict(METHOD),
    }


# Supply one internally consistent stored calculation without calling production.
def _recorded_walls():
    return {
        "expiry": "2026-10-16",
        "through": "2026-10-16",
        "fetched_at": OLD_COLLECTION,
        "put_wall": 95.0,
        "call_wall": 105.0,
        "put_wall_oi": 3000,
        "call_wall_oi": 3000,
        "put_wall_distance": -0.05,
        "call_wall_distance": 0.05,
        "net_gamma": 0.0,
        "calculation": _calculation(bar=BAR_START),
    }


# Write a real old chain whose collection-time price must not become the reference.
def _old_chain(root, *, symbol="AAA", rows=None, source_time=OLD_COLLECTION):
    store = MarketStore(root)
    metadata = {"price": "177.7700"}
    if source_time is not None:
        metadata["source_time"] = source_time
    assert store.write_frame(
        options.KIND,
        date(2026, 9, 1),
        symbol,
        options.frame(_chain_rows() if rows is None else rows),
        metadata,
    )
    return store


# Compare every task-owned file, including files created or removed during a read.
def _files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


# Verify the normalized public descriptor without using its helper as the oracle.
def _assert_recorded(evidence, *, now=NOW, bar=BAR_START):
    assert evidence["status"] == "recorded"
    assert evidence["checked_at"] == now.isoformat()
    assert evidence["collected_at"] == OLD_COLLECTION
    assert evidence["collection_status"] == "recorded"
    assert (
        evidence["collection_age_seconds"]
        == (now - datetime.fromisoformat(OLD_COLLECTION)).total_seconds()
    )
    assert evidence["oi_effective_at"] is None
    assert evidence["oi_freshness"] == "unknown"
    assert evidence["calculation_version"] == VERSION
    assert evidence["calculated_on"] == TODAY.isoformat()
    assert evidence["calculation_date_status"] == "same_date"
    assert evidence["reference_price"] == 100.0
    assert evidence["reference_basis"] == "raw_panel_close"
    assert evidence["reference_session"] == TODAY.isoformat()
    assert evidence["reference_bar_start"] == bar
    assert evidence["expiry"] == evidence["through"] == "2026-10-16"
    assert evidence["method"] == METHOD
    assert (evidence["put_level"], evidence["call_level"]) == (95.0, 105.0)
    assert (evidence["put_oi"], evidence["call_oi"]) == (3000, 3000)
    assert evidence["put_distance"] == pytest.approx(-0.05)
    assert evidence["call_distance"] == pytest.approx(0.05)
    assert "net_gamma" not in evidence
    assert "fresh" not in evidence


# Real Parquet metadata and raw panel prices must survive producer calculations.
@pytest.mark.parametrize("adjustment", [1.0, 0.98, 0.5])
def test_producer_records_actual_raw_reference_not_adjusted_or_chain_price(
    tmp_path, monkeypatch, adjustment
):
    store = _old_chain(tmp_path)
    read, quotes = _synthetic_read(adjustment)
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    before = _files(tmp_path)
    original_read = deepcopy(read)
    baseline = live_technical.technical_detail(None, quotes, TODAY)
    detail = live_technical.technical_detail(store, quotes, TODAY)
    walls = detail["AAA"].pop("walls")
    assert walls["calculation"] == _calculation()
    assert walls["fetched_at"] == OLD_COLLECTION
    assert (walls["put_wall"], walls["call_wall"]) == (95.0, 105.0)
    assert walls["put_wall_distance"] == pytest.approx(-0.05)
    assert walls["call_wall_distance"] == pytest.approx(0.05)
    assert detail == baseline
    assert _files(tmp_path) == before
    np.testing.assert_array_equal(read["panel"].close, original_read["panel"].close)
    np.testing.assert_array_equal(
        read["panel"].adj_close, original_read["panel"].adj_close
    )
    np.testing.assert_array_equal(
        read["opinion"].scores, original_read["opinion"].scores
    )


# Keep the actual live-row and cache path while replacing only analyst boundaries.
def _synthetic_opinions(monkeypatch):
    from backend.agents.trading.desk import value
    from backend.market import levels_pit

    read, quotes = _synthetic_read(0.5)
    monkeypatch.setattr(live_technical, "_cache", {"key": None, "value": {}})
    monkeypatch.setattr(live_technical, "book_panel", lambda *args: (read["panel"], {}))
    monkeypatch.setattr(live_technical, "tightening_for", lambda *args: None)
    monkeypatch.setattr(
        live_technical.regime,
        "opine",
        lambda *args: SimpleNamespace(ai_trend=np.ones(3)),
    )
    monkeypatch.setattr(
        live_technical.technical_analyst, "opine", lambda *args: read["opinion"]
    )
    monkeypatch.setattr(levels_pit, "point_in_time_levels", lambda *args: {})
    monkeypatch.setattr(value, "opine", lambda *args: None)
    return read, quotes


# A newer quote on the same candle cannot relabel the original cached reference.
def test_real_live_cache_retains_original_price_and_bar_until_next_candle(
    tmp_path, monkeypatch
):
    store = _old_chain(tmp_path)
    _read, quotes = _synthetic_opinions(monkeypatch)
    first = live_technical.technical_detail(store, quotes, TODAY)["AAA"]["walls"]
    first_cache = live_technical._cache["value"]
    assert first["calculation"] == _calculation(bar=BAR_START)
    assert first_cache["reference_bars"]["AAA"] == BAR_START
    updated = {**quotes, "AAA": replace(quotes["AAA"], last=120.0, high=121.0)}
    second = live_technical.technical_detail(store, updated, TODAY)["AAA"]["walls"]
    assert live_technical._cache["value"] is first_cache
    assert updated["AAA"].last == 120.0
    assert first_cache["panel"].close[-1, 0] == 100.0
    assert second == first
    next_bar = "2026-09-25T14:30:00+00:00"
    updated["AAA"] = replace(updated["AAA"], bar=next_bar)
    third = live_technical.technical_detail(store, updated, TODAY)["AAA"]["walls"]
    assert live_technical._cache["value"] is not first_cache
    assert third["calculation"] == _calculation(price=120.0, bar=next_bar)
    assert third["put_wall_distance"] == pytest.approx(95.0 / 120.0 - 1.0)
    assert third["call_wall"] is None


# A carried raw price is usable but cannot acquire a bar from a rejected quote.
def test_real_live_cache_does_not_claim_bar_for_quote_that_was_not_used(
    tmp_path, monkeypatch
):
    store = _old_chain(tmp_path)
    _read, quotes = _synthetic_opinions(monkeypatch)
    quotes["AAA"] = replace(quotes["AAA"], last=0.0)
    walls = live_technical.technical_detail(store, quotes, TODAY)["AAA"]["walls"]
    assert walls["calculation"] == _calculation()
    assert "AAA" not in live_technical._cache["value"]["reference_bars"]


# Keep a genuine earlier source bar distinct from the panel row receiving its price.
def test_older_source_bar_is_not_redated_to_the_raw_panel_session(
    tmp_path, monkeypatch
):
    store = _old_chain(tmp_path)
    _read, quotes = _synthetic_opinions(monkeypatch)
    old_bar = "2026-09-24T19:45:00+00:00"
    quotes["AAA"] = replace(quotes["AAA"], bar=old_bar)
    walls = live_technical.technical_detail(store, quotes, TODAY)["AAA"]["walls"]
    assert walls["calculation"] == _calculation(bar=old_bar)
    evidence = _evidence_module().describe(walls, NOW)
    _assert_recorded(evidence, bar=old_bar)


# Price-space range boundaries accepted by the producer must remain displayable.
@pytest.mark.parametrize("price", [0.28, 3.92, 10.01, 100.0])
@pytest.mark.parametrize("side", ["put", "call"])
def test_exact_range_boundary_levels_survive_producer_and_descriptor(
    tmp_path, monkeypatch, price, side
):
    strike = price * (0.75 if side == "put" else 1.25)
    rows = [options.ChainRow(TODAY + timedelta(days=7), side, strike, 500, 0, 0.5, 0.0)]
    store = _old_chain(tmp_path, rows=rows)
    read, quotes = _synthetic_read()
    read["panel"].close[-1, 0] = price
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    walls = live_technical.technical_detail(store, quotes, TODAY)["AAA"]["walls"]
    assert walls[f"{side}_wall"] == strike
    assert walls[f"{side}_wall_oi"] == 500
    evidence = _evidence_module().describe(walls, NOW)
    assert evidence["status"] == "recorded"
    assert evidence[f"{side}_level"] == strike
    assert evidence[f"{side}_oi"] == 500
    assert evidence[f"{side}_distance"] == pytest.approx(strike / price - 1.0)


# A valid dated record exposes OI levels, not gamma or an asserted OI update time.
def test_descriptor_keeps_oi_effective_time_unknown_without_mutating_record():
    walls = _recorded_walls()
    original = deepcopy(walls)
    evidence = _evidence_module().describe(walls, NOW)
    _assert_recorded(evidence)
    assert walls == original


# Missing, malformed, naive, future, and offset clocks preserve their meanings.
@pytest.mark.parametrize(
    ("source_time", "status", "collected_at", "age"),
    [
        (None, "missing", None, None),
        ("", "invalid", None, None),
        ("not-a-time", "invalid", None, None),
        ("2026-09-01", "invalid", None, None),
        ("2026-09-01T12:45:00", "invalid", None, None),
        (True, "invalid", None, None),
        (1234, "invalid", None, None),
        ({"at": OLD_COLLECTION}, "invalid", None, None),
        ("2026-09-26T01:00:00Z", "future", "2026-09-26T01:00:00+00:00", None),
        ("2026-09-25T10:29:30-04:00", "recorded", "2026-09-25T14:29:30+00:00", 30),
        ("2026-09-25T14:30:00Z", "recorded", NOW.isoformat(), 0),
    ],
)
def test_collection_clock_is_separate_from_valid_calculation(
    source_time, status, collected_at, age
):
    walls = _recorded_walls()
    walls["fetched_at"] = source_time
    original = deepcopy(walls)
    evidence = _evidence_module().describe(walls, NOW)
    assert evidence["status"] == "recorded"
    assert evidence["collection_status"] == status
    assert evidence["collected_at"] == collected_at
    assert evidence["collection_age_seconds"] == age
    assert evidence["oi_effective_at"] is None
    assert evidence["oi_freshness"] == "unknown"
    assert evidence["reference_price"] == 100.0
    assert walls == original


# Refuse ambiguous assessment clocks rather than silently assuming a timezone.
def test_naive_assessment_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        _evidence_module().describe(_recorded_walls(), NOW.replace(tzinfo=None))


# Undocumented calculation assumptions must not be backfilled onto legacy walls.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", None),
        ("version", "raw-option-oi-levels/unknown"),
        ("date", None),
        ("date", "2026-09-26"),
        ("date", "20260925"),
        ("date", "2026-09-25T14:30:00Z"),
        ("reference_price", None),
        ("reference_price", "100"),
        ("reference_price", True),
        ("reference_price", 0.0),
        ("reference_price", -100.0),
        ("reference_price", np.nan),
        ("reference_price", np.inf),
        ("reference_basis", "adjusted_close"),
        ("reference_session", None),
        ("reference_session", "invalid"),
        ("reference_session", "2026-09-24"),
        ("reference_session", "2026-09-26"),
        ("reference_bar_start", "invalid"),
        ("reference_bar_start", "2026-09-25T14:15:00"),
        ("reference_bar_start", "2026-09-26T14:15:00Z"),
        ("method", None),
        ("method", {**METHOD, "min_days": 0}),
        ("method", {**METHOD, "max_days": 61}),
        ("method", {**METHOD, "strike_range_fraction": 0.5}),
        ("method", {**METHOD, "min_open_interest": 499}),
        ("method", {**METHOD, "min_days": True}),
    ],
)
def test_bad_calculation_metadata_withholds_levels_but_preserves_collection(
    field, value
):
    walls = _recorded_walls()
    walls["calculation"][field] = value
    evidence = _evidence_module().describe(walls, NOW)
    assert evidence["status"] == "unverified"
    assert evidence["reason"] == "calculation_provenance_unverified"
    assert set(evidence) == COMMON_FIELDS | {"status", "reason"}
    assert not LEVEL_FIELDS.intersection(evidence)
    assert evidence["collected_at"] == OLD_COLLECTION
    assert evidence["collection_age_seconds"] > 24 * 60 * 60
    assert evidence["oi_freshness"] == "unknown"


# Missing provenance and unavailable source data remain distinct display states.
@pytest.mark.parametrize(
    ("state", "status", "reason"),
    [
        ("absent", "absent", "no_stored_diagnostic"),
        ("unreadable", "unavailable", "options_data_unavailable"),
        ("legacy", "unverified", "calculation_provenance_unverified"),
        ("null_calculation", "unverified", "calculation_provenance_unverified"),
        ("empty_calculation", "unverified", "calculation_provenance_unverified"),
    ],
)
def test_missing_provenance_states_have_reasons_and_no_displayed_levels(
    state, status, reason
):
    walls = _recorded_walls()
    if state == "absent":
        walls = None
    elif state == "unreadable":
        walls = {"status": "unavailable", "reason": "options_data_unavailable"}
    elif state == "legacy":
        del walls["calculation"]
    else:
        walls["calculation"] = None if state == "null_calculation" else {}
    evidence = _evidence_module().describe(walls, NOW)
    assert evidence["status"] == status
    assert evidence["reason"] == reason
    assert set(evidence) == COMMON_FIELDS | {"status", "reason"}
    assert evidence["oi_effective_at"] is None
    assert evidence["oi_freshness"] == "unknown"


# Levels incompatible with their stored raw reference are never presented as valid.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("put_wall", 105.0),
        ("put_wall", 70.0),
        ("put_wall", True),
        ("put_wall", np.inf),
        ("put_wall", None),
        ("call_wall", 95.0),
        ("call_wall", 130.0),
        ("put_wall_oi", -1),
        ("put_wall_oi", 499),
        ("put_wall_oi", 500.5),
        ("put_wall_oi", True),
        ("put_wall_distance", None),
        ("put_wall_distance", -0.04),
        ("call_wall_distance", np.inf),
        ("expiry", "bad-date"),
        ("expiry", TODAY.isoformat()),
        ("expiry", None),
        ("through", "2026-12-31"),
        ("through", "2026-10-01"),
    ],
)
def test_inconsistent_stored_levels_are_unverified(field, value):
    walls = _recorded_walls()
    walls[field] = value
    evidence = _evidence_module().describe(walls, NOW)
    assert evidence["status"] == "unverified"
    assert not LEVEL_FIELDS.intersection(evidence)


# The assessment date uses New York, not UTC midnight or the reader's timezone.
@pytest.mark.parametrize(
    ("now", "date_status"),
    [
        (datetime(2026, 9, 26, 3, 59, tzinfo=UTC), "same_date"),
        (datetime(2026, 9, 26, 4, 0, tzinfo=UTC), "historical"),
        (datetime(2026, 10, 16, 14, 30, tzinfo=UTC), "historical"),
        (datetime(2026, 10, 17, 14, 30, tzinfo=UTC), "historical"),
    ],
)
def test_expiry_rollover_dates_old_calculation_without_recomputing_it(now, date_status):
    walls = _recorded_walls()
    before = deepcopy(walls)
    evidence = _evidence_module().describe(walls, now)
    assert evidence["status"] == "recorded"
    assert evidence["calculation_date_status"] == date_status
    assert evidence["calculated_on"] == TODAY.isoformat()
    assert evidence["expiry"] == evidence["through"] == "2026-10-16"
    assert evidence["put_level"] == 95.0
    assert evidence["put_distance"] == pytest.approx(-0.05)
    assert evidence["oi_freshness"] == "unknown"
    assert walls == before


# No qualifying contracts is a computed result, not a storage failure or fresh OI.
@pytest.mark.parametrize("kind", ["below_threshold", "only_same_day", "unreadable"])
def test_real_producer_distinguishes_no_qualifying_levels_from_unreadable_chain(
    tmp_path, monkeypatch, kind
):
    rows = [
        replace(row, open_interest=499)
        if kind == "below_threshold"
        else replace(row, expiry=TODAY)
        for row in _chain_rows()
    ]
    store = _old_chain(tmp_path, rows=rows)
    if kind == "unreadable":
        store._path(options.KIND, date(2026, 9, 1), "AAA").write_bytes(
            b"synthetic unreadable options frame"
        )
    read, quotes = _synthetic_read()
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    before = _files(tmp_path)
    walls = live_technical.technical_detail(store, quotes, TODAY)["AAA"]["walls"]
    evidence = _evidence_module().describe(walls, NOW)
    if kind == "unreadable":
        assert evidence["status"] == "unavailable"
        assert evidence["reason"] == "options_data_unavailable"
        assert not LEVEL_FIELDS.intersection(evidence)
    else:
        assert evidence["status"] == "recorded"
        assert evidence["put_level"] is evidence["call_level"] is None
        assert evidence["put_distance"] is evidence["call_distance"] is None
        assert evidence["put_oi"] == evidence["call_oi"] == 0
        assert evidence["method"] == METHOD
        assert evidence["oi_freshness"] == "unknown"
        if kind == "only_same_day":
            assert evidence["expiry"] is evidence["through"] is None
        else:
            assert evidence["expiry"] == "2026-10-16"
    assert _files(tmp_path) == before


# Both quoted and diagnostic-only symbols receive explicit evidence availability.
def test_snapshot_projection_covers_union_without_reusing_stored_descriptor():
    walls = _recorded_walls()
    snapshot = {
        "quotes": {"AAA": {"last": 200.0}, "BBB": {"last": 100.0}},
        "technical_detail": {"AAA": {"walls": walls}, "CCC": {"walls": walls}},
        "options_evidence": {"AAA": {"status": "fresh"}},
    }
    original = deepcopy(snapshot)
    result = _evidence_module().for_snapshot(snapshot, NOW)
    assert set(result) == {"AAA", "BBB", "CCC"}
    _assert_recorded(result["AAA"])
    _assert_recorded(result["CCC"])
    assert result["BBB"]["status"] == "absent"
    assert snapshot == original


# Separate stock/snapshot clocks from the untouched options collection reference.
def test_fresh_stock_snapshot_does_not_make_old_options_current():
    snapshot = {
        "as_of": NOW.isoformat(),
        "quotes": {"AAA": {"last": 140.0, "bar": BAR_START}},
        "technical": {"AAA": {"now": 0.8, "close": 0.7, "stance": 1}},
        "technical_detail": {"AAA": {"walls": _recorded_walls()}},
    }
    original = deepcopy(snapshot)
    first = desk_freshness.describe(snapshot, NOW)
    assert first["stale"] is False
    assert first["quote_status"]["AAA"]["data_age_seconds"] == 900
    _assert_recorded(first["options_evidence"]["AAA"])
    later = NOW + timedelta(minutes=5)
    second = desk_freshness.describe(snapshot, later)
    _assert_recorded(second["options_evidence"]["AAA"], now=later)
    assert second["stale"] is False
    assert second["technical"] == first["technical"] == snapshot["technical"]
    assert second["technical_detail"] == snapshot["technical_detail"]
    assert snapshot == original


# Persist a true balancer snapshot while replacing only external/account inputs.
def _persist_snapshot(root, monkeypatch):
    store = _old_chain(root)
    _old_chain(root, symbol="BBB", rows=[])
    read, quotes = _synthetic_read()
    clock = [NOW]

    # Advance only the test clock, never the computer or a provider's timestamp.
    class Clock(datetime):
        # Return the declared instant in the caller's requested timezone.
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    monkeypatch.setattr(live_technical, "datetime", Clock)
    monkeypatch.setattr(market_balancer, "datetime", Clock)
    monkeypatch.setattr(market_balancer.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(
        market_balancer.live_quotes, "quotes", lambda *args, **kwargs: quotes
    )
    monkeypatch.setattr(
        market_balancer.deskrecord,
        "latest_pair",
        lambda *args: (_evening_record(), None),
    )
    monkeypatch.setattr(market_balancer.holdings, "load", lambda *args: [])
    monkeypatch.setattr(market_balancer, "_observe_paper", lambda *args: None)
    monkeypatch.setattr(market_balancer, "_green_day_skip", lambda *args: None)
    monkeypatch.setattr(market_event_recovery, "run", lambda *args: None)
    monkeypatch.setattr(intraday_research, "publish", lambda *args: {})
    expected_technical = live_technical.technical_now(store, quotes, TODAY)
    plan = market_balancer.run(root, 100_000.0)
    return plan, expected_technical, clock, Clock


# Authenticated cached reads add only derived evidence and never rewrite history.
@pytest.mark.asyncio
async def test_authenticated_live_reads_date_produced_snapshot_without_side_effects(
    tmp_path, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from backend.api.v1 import market
    from backend.config.settings import settings
    from backend.core import auth
    from backend.core.auth import issue_user_token
    from backend.main import app

    plan_path, expected_technical, clock, clock_type = _persist_snapshot(
        tmp_path, monkeypatch
    )
    snapshot_path = tmp_path / "desk" / market_balancer.LIVE_FILE
    snapshot = json.loads(snapshot_path.read_bytes())
    plan = json.loads(plan_path.read_bytes())
    assert all(row["grade_source"] == "intraday" for row in plan["rows"])
    assert {row["ticker"]: row["grade_live"] for row in plan["rows"]} == {
        "AAA": "A+",
        "BBB": "B",
    }
    assert "options_evidence" not in snapshot
    monkeypatch.setattr(market, "datetime", clock_type)
    monkeypatch.setattr(desk_freshness, "datetime", clock_type)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "options_provenance_owner")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)

    # Exclude only search-metering's unrelated account query, not authentication.
    async def no_search_account_lookup(*args, **kwargs):
        return None

    monkeypatch.setattr(auth, "_bind_search_identity", no_search_account_lookup)
    forbidden = []

    # Detect forbidden recalculation/account activity even if a fallback catches it.
    def forbid(*args, **kwargs):
        forbidden.append("cached read crossed a forbidden boundary")
        raise AssertionError("Cached live reads must not fetch, calculate, or trade")

    monkeypatch.setattr(market.alpaca, "credentials", forbid)
    monkeypatch.setattr(market.live_quotes, "quotes", forbid)
    monkeypatch.setattr(live_technical, "technical_detail", forbid)
    monkeypatch.setattr(live_technical, "technical_now", forbid)
    monkeypatch.setattr(live_technical, "value_now", forbid)
    monkeypatch.setattr(market_balancer.holdings, "load", forbid)
    monkeypatch.setattr(market_balancer, "_observe_paper", forbid)
    monkeypatch.setattr(market_event_recovery, "run", forbid)
    monkeypatch.setattr(intraday_research, "publish", forbid)
    token = issue_user_token("options_provenance_owner", scopes=["memory:read"])
    other = issue_user_token("options_provenance_other", scopes=["memory:read"])
    route = "/api/v1/market/options_provenance_owner/desk/live"
    before = _files(tmp_path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get(route)
        cross_user = await client.get(
            route, headers={"Authorization": f"Bearer {other}"}
        )
        first = await client.get(route, headers={"Authorization": f"Bearer {token}"})
        clock[0] += timedelta(minutes=5)
        second = await client.get(route, headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 401
    assert cross_user.status_code == 403
    for response, instant in ((first, NOW), (second, clock[0])):
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["technical"] == expected_technical == snapshot["technical"]
        assert body["technical_detail"] == snapshot["technical_detail"]
        assert body["quotes"] == snapshot["quotes"]
        assert body["as_of"] == snapshot["as_of"]
        assert body["stale"] is False
        _assert_recorded(body["options_evidence"]["AAA"], now=instant, bar=None)
        assert body["options_evidence"]["BBB"]["status"] == "absent"
        assert body["options_evidence"]["SPY"]["status"] == "absent"
    assert _files(tmp_path) == before
    assert forbidden == []
