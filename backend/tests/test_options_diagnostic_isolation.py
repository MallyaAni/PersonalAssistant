"""Raw-strike comparisons and optional-options failure isolation.

The live row, Parquet store, options reader, technical detail, board, and
balancer persistence are real. Opinion inputs and external/account boundaries
are synthetic. This contract does not qualify options freshness or alpha.
"""

import hashlib
import json
import socket
from datetime import UTC, date, datetime

import numpy as np
import pytest
from pyarrow import ArrowInvalid, ArrowKeyError, ArrowTypeError

from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_balancer, market_event_recovery
from backend.market import intraday_research, live_quotes, live_technical, options
from backend.market.panel import Panel
from backend.market.store import MarketStore

TODAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
EXPIRY = date(2026, 10, 16)
UNAVAILABLE = {"status": "unavailable", "reason": "options_data_unavailable"}
INVALID_FIELDS = {
    "unknown_kind": ("kind", "unknown"),
    "zero_strike": ("strike", 0.0),
    "negative_strike": ("strike", -1.0),
    "nan_strike": ("strike", np.nan),
    "infinite_strike": ("strike", np.inf),
    "negative_infinite_strike": ("strike", -np.inf),
    "boolean_strike": ("strike", True),
    "negative_oi": ("open_interest", -1),
    "fractional_oi": ("open_interest", 0.5),
    "boolean_oi": ("open_interest", True),
    "nan_oi": ("open_interest", np.nan),
    "infinite_oi": ("open_interest", np.inf),
    "negative_volume": ("volume", -1),
    "fractional_volume": ("volume", 0.5),
    "boolean_volume": ("volume", True),
    "nan_volume": ("volume", np.nan),
    "infinite_volume": ("volume", np.inf),
    "nan_gamma": ("gamma", np.nan),
    "infinite_gamma": ("gamma", np.inf),
    "negative_infinite_gamma": ("gamma", -np.inf),
    "boolean_gamma": ("gamma", True),
    "nan_iv": ("implied_volatility", np.nan),
    "infinite_iv": ("implied_volatility", np.inf),
    "negative_infinite_iv": ("implied_volatility", -np.inf),
    "boolean_iv": ("implied_volatility", True),
    "negative_iv": ("implied_volatility", -0.5),
    "gamma_product_overflow": ("gamma", 1e308),
}
FAILURES = (
    "bad_expiry",
    "missing_column",
    "missing_strike_column",
    "unequal_lengths",
    "unreadable_parquet",
    *INVALID_FIELDS,
)


# Freeze only the synthetic observation clock, without changing system time.
class _FixedDatetime(datetime):
    # Return the declared observation instant in the requested timezone.
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


# Reject attempted networking even if an outer production handler catches it.
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts = []

    # Record connection attempts without retaining any endpoint or credential.
    def refuse(*args, **kwargs):
        attempts.append("network connection attempted")
        raise RuntimeError("This synthetic options test forbids networking")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    assert attempts == []


# Supply declared opinion inputs while retaining the real live-row transform.
def _synthetic_read(adjustment=1.0):
    close = np.array([[100.0, 100.0, 400.0], [100.0, 100.0, 400.0]])
    panel = Panel(
        dates=np.array(["2026-09-23", "2026-09-24"], dtype="datetime64[D]"),
        tickers=("AAA", "BBB", "SPY"),
        open=close.copy(),
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        adj_close=close * adjustment,
        volume=np.full(close.shape, 1000.0),
        themes={},
        benchmark="SPY",
    )
    quotes = {
        symbol: live_quotes.Quote(
            symbol,
            price,
            price,
            price + 1.0,
            price - 1.0,
            "2026-09-25T14:15:00+00:00",
            NOW.isoformat(),
        )
        for symbol, price in (("AAA", 100.0), ("BBB", 100.0), ("SPY", 400.0))
    }
    live = live_technical.with_live_row(panel, quotes, TODAY)
    scores = np.tile([0.8, 0.2, np.nan], (3, 1))
    evidence = {"ema21_distance": np.full((3, 3), 0.1)}
    opinion = Opinion("technical", scores, evidence)
    return {"panel": live, "opinion": opinion, "value": None}, quotes


# Include separate low-strike OI maxima to expose price-basis selection errors.
def _chain_rows():
    return [
        options.ChainRow(EXPIRY, "put", 45.0, 1000, 1, 0.5, 0.01),
        options.ChainRow(EXPIRY, "call", 55.0, 1000, 1, 0.5, 0.01),
        options.ChainRow(EXPIRY, "put", 95.0, 3000, 1, 0.5, 0.02),
        options.ChainRow(EXPIRY, "call", 105.0, 3000, 1, 0.5, 0.02),
    ]


# Produce the declared malformed scalar or missing-column fixture before storage.
def _chain_columns(state):
    columns = options.frame(_chain_rows())
    if state == "bad_expiry":
        columns["expiry"][0] = "bad-expiry"
    elif state == "missing_column":
        del columns["gamma"]
    elif state == "missing_strike_column":
        del columns["strike"]
    elif state in INVALID_FIELDS:
        column, value = INVALID_FIELDS[state]
        if isinstance(value, bool):
            # Preserve a Boolean Parquet type instead of coercing it into an int.
            columns[column] = [value] * len(columns[column])
        else:
            columns[column][0] = value
    return columns


# Create real synthetic storage, injecting an impossible column length at readback.
def _stored_chain(root, monkeypatch, *, symbol="AAA", state="valid"):
    store = MarketStore(root)
    if state == "absent":
        return store
    columns = _chain_columns(state)
    path = store._path(options.KIND, TODAY, symbol)
    if state == "unreadable_parquet":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic non-Parquet bytes")
    else:
        assert store.write_frame(
            options.KIND,
            TODAY,
            symbol,
            columns,
            {"source_time": "2026-09-25T12:45:00+00:00", "price": "100.0000"},
        )
    if state == "unequal_lengths":
        original_read = MarketStore.read_frame

        # Corrupt only this frame's returned shape; the healthy symbol stays real.
        def read_with_short_column(self, kind, ticker, asof=None):
            frame = original_read(self, kind, ticker, asof)
            if self.root == root and kind == options.KIND and ticker == symbol:
                found, metadata = frame
                found["gamma"] = found["gamma"][:-1]
                return found, metadata
            return frame

        monkeypatch.setattr(MarketStore, "read_frame", read_with_short_column)
    return store


# Assert valid walls, independently calculated raw distances, and producer provenance.
def _assert_raw_walls(walls):
    assert set(walls) == {
        "expiry",
        "through",
        "fetched_at",
        "put_wall",
        "call_wall",
        "put_wall_oi",
        "call_wall_oi",
        "net_gamma",
        "put_wall_distance",
        "call_wall_distance",
        "calculation",
    }
    assert walls["expiry"] == walls["through"] == EXPIRY.isoformat()
    assert walls["fetched_at"] == "2026-09-25T12:45:00+00:00"
    assert (walls["put_wall"], walls["call_wall"]) == (95.0, 105.0)
    assert (walls["put_wall_oi"], walls["call_wall_oi"]) == (3000, 3000)
    assert walls["put_wall_distance"] == pytest.approx(-0.05)
    assert walls["call_wall_distance"] == pytest.approx(0.05)
    assert walls["net_gamma"] == 0.0
    assert walls["calculation"] == {
        "version": "raw-option-oi-levels/1",
        "date": TODAY.isoformat(),
        "reference_price": 100.0,
        "reference_basis": "raw_panel_close",
        "reference_session": TODAY.isoformat(),
        "reference_bar_start": None,
        "method": {
            "min_days": 1,
            "max_days": options.WALL_DAYS,
            "strike_range_fraction": options.WALL_RANGE,
            "min_open_interest": options.MIN_WALL_OI,
        },
    }


# Keep raw-dollar strike comparisons independent of adjusted technical features.
@pytest.mark.parametrize("adjustment", [1.0, 0.98, 0.5])
def test_option_walls_use_raw_close_without_changing_technical_inputs(
    tmp_path, monkeypatch, adjustment
):
    store = _stored_chain(tmp_path, monkeypatch)
    read, quotes = _synthetic_read(adjustment)
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    original_close = read["panel"].close.copy()
    original_adjusted = read["panel"].adj_close.copy()
    original_scores = read["opinion"].scores.copy()
    baseline = live_technical.technical_detail(None, quotes, TODAY)
    actual = live_technical.technical_detail(store, quotes, TODAY)
    assert quotes["AAA"].last == read["panel"].close[-1, 0] == 100.0
    assert read["panel"].adj_close[-1, 0] == 100.0 * adjustment
    _assert_raw_walls(actual["AAA"].pop("walls"))
    assert actual == baseline
    np.testing.assert_array_equal(read["panel"].close, original_close)
    np.testing.assert_array_equal(read["panel"].adj_close, original_adjusted)
    np.testing.assert_array_equal(read["opinion"].scores, original_scores)


# A missing or invalid raw close cannot be replaced with a valid adjusted price.
@pytest.mark.parametrize("raw_price", [np.nan, np.inf, -np.inf, 0.0, -1.0])
def test_invalid_raw_panel_price_omits_walls(tmp_path, monkeypatch, raw_price):
    store = _stored_chain(tmp_path, monkeypatch)
    read, quotes = _synthetic_read()
    read["panel"].close[-1, 0] = raw_price
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    assert read["panel"].adj_close[-1, 0] == 100.0
    actual = live_technical.technical_detail(store, quotes, TODAY)
    assert "walls" not in actual["AAA"]
    assert actual["AAA"]["now"] == 1.0


# Reject absent, nonnumeric and nonfinite prices before the options store is read.
@pytest.mark.parametrize("price", [None, "invalid", np.nan, np.inf, -np.inf, 0.0, -1.0])
def test_invalid_wall_reference_price_does_not_read_storage(monkeypatch, price):
    store = MarketStore("unused-synthetic-options-root")
    reads = []

    # Detect an invalid-price lookup without accessing any real path.
    def unexpected_read(*args, **kwargs):
        reads.append(True)
        raise AssertionError("Invalid reference price reached the store")

    monkeypatch.setattr(store, "read_frame", unexpected_read)
    assert live_technical._walls_for(store, "AAA", price, TODAY) is None
    assert reads == []


# Keep genuinely absent options distinct from a malformed stored observation.
@pytest.mark.parametrize("state", ["no_store", "no_partition", "empty_frame"])
def test_absent_or_empty_options_leave_technical_detail_intact(
    tmp_path, monkeypatch, state
):
    store = None if state == "no_store" else MarketStore(tmp_path)
    if state == "empty_frame":
        assert store.write_frame(options.KIND, TODAY, "AAA", options.frame([]))
    read, quotes = _synthetic_read()
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    expected = live_technical.technical_detail(None, quotes, TODAY)
    assert live_technical.technical_detail(store, quotes, TODAY) == expected


# Optional-data handling must not conceal unrelated computation errors.
@pytest.mark.parametrize("stage", ["wall_calculation", "technical_read"])
def test_unexpected_runtime_errors_still_propagate(tmp_path, monkeypatch, stage):
    store = _stored_chain(tmp_path, monkeypatch)
    read, quotes = _synthetic_read()
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)

    # Represent a programming failure rather than a malformed external data value.
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic computation failure")

    if stage == "wall_calculation":
        monkeypatch.setattr(options, "walls", fail)
    else:
        monkeypatch.setattr(live_technical, "_live_read", fail)
    with pytest.raises(RuntimeError, match="synthetic computation failure"):
        live_technical.technical_detail(store, quotes, TODAY)


# Distinguish typed storage failures from unrelated exceptions raised by store code.
@pytest.mark.parametrize("error", [TypeError, KeyError, ValueError, RuntimeError])
def test_storage_programming_errors_remain_visible(monkeypatch, error):
    store = MarketStore("unused-synthetic-options-root")

    # Represent a coding defect, without opening any file or provider connection.
    def fail(*args, **kwargs):
        raise error("synthetic storage programming error")

    monkeypatch.setattr(store, "read_frame", fail)
    with pytest.raises(error, match="synthetic storage programming error"):
        live_technical._walls_for(store, "AAA", 100.0, TODAY)


# Keep recognized filesystem, decoding and Arrow data errors local to the options read.
@pytest.mark.parametrize(
    "error", [OSError, UnicodeError, ArrowInvalid, ArrowTypeError, ArrowKeyError]
)
def test_expected_storage_errors_return_unavailable(monkeypatch, error):
    store = MarketStore("unused-synthetic-options-root")

    # Supply each supported storage exception without relying on the host filesystem.
    def fail(*args, **kwargs):
        raise error("synthetic unreadable options data")

    monkeypatch.setattr(store, "read_frame", fail)
    assert live_technical._walls_for(store, "AAA", 100.0, TODAY) == UNAVAILABLE


# Isolate each unreadable optional frame without removing healthy technical detail.
@pytest.mark.parametrize("failure", FAILURES)
def test_bad_options_are_explicit_and_do_not_remove_other_detail(
    tmp_path, monkeypatch, failure
):
    store = _stored_chain(tmp_path, monkeypatch, state=failure)
    _stored_chain(tmp_path, monkeypatch, symbol="BBB")
    bad_path = store._path(options.KIND, TODAY, "AAA")
    before = hashlib.sha256(bad_path.read_bytes()).hexdigest()
    read, quotes = _synthetic_read()
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    baseline = live_technical.technical_detail(None, quotes, TODAY)
    actual = live_technical.technical_detail(store, quotes, TODAY)
    assert actual["AAA"].pop("walls") == UNAVAILABLE
    _assert_raw_walls(actual["BBB"].pop("walls"))
    assert actual == baseline
    assert hashlib.sha256(bad_path.read_bytes()).hexdigest() == before


# Supply public synthetic evening evidence to the real board calculation.
def _evening_record():
    grades = {
        name: {
            "grade": "A",
            "score": 1.0,
            "stances": {
                "fundamental": 1,
                "technical": 0,
                "sentiment": 1,
                "value": 0,
            },
            "ranks": {"technical": 0.5},
        }
        for name in ("AAA", "BBB")
    }
    return {
        "session": "2026-09-24",
        "grades": grades,
        "book": [{"ticker": name, "weight": 0.1} for name in grades],
        "actions": [
            {"ticker": name, "last_close": 100.0, "rejecting_band": False}
            for name in grades
        ],
    }


# Persist a real balancer result from declared inputs without external operations.
def _run_synthetic_balancer(tmp_path, monkeypatch, chain_state):
    store = _stored_chain(tmp_path, monkeypatch, state=chain_state)
    _stored_chain(tmp_path, monkeypatch, symbol="BBB")
    read, quotes = _synthetic_read()
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: read)
    monkeypatch.setattr(live_technical, "datetime", _FixedDatetime)
    monkeypatch.setattr(market_balancer, "datetime", _FixedDatetime)
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
    monkeypatch.setattr(
        intraday_research, "publish", lambda *args: {"status": "synthetic_noop"}
    )
    monkeypatch.setattr(market_balancer, "_observe_paper", lambda *args: None)
    monkeypatch.setattr(market_balancer, "_green_day_skip", lambda *args: None)
    monkeypatch.setattr(market_event_recovery, "run", lambda *args: None)
    expected = live_technical.technical_now(store, quotes, TODAY)
    assert set(expected) == {"AAA", "BBB"}
    plan_path = market_balancer.run(tmp_path, 100_000.0)
    return plan_path, expected


# Run actual balancer persistence while excluding providers and account operations.
@pytest.mark.parametrize("chain_state", ["absent", "valid", *FAILURES])
def test_balancer_preserves_both_technical_reads_when_options_are_unavailable(
    tmp_path, monkeypatch, chain_state
):
    plan_path, expected = _run_synthetic_balancer(tmp_path, monkeypatch, chain_state)
    plan = json.loads(plan_path.read_text())
    snapshot = json.loads((tmp_path / "desk" / market_balancer.LIVE_FILE).read_text())
    assert snapshot["quotes"]["AAA"]["last"] == 100.0
    assert snapshot["technical"] == expected
    _assert_raw_walls(snapshot["technical_detail"]["BBB"]["walls"])
    if chain_state in FAILURES:
        assert snapshot["technical_detail"]["AAA"]["walls"] == UNAVAILABLE
    elif chain_state == "valid":
        _assert_raw_walls(snapshot["technical_detail"]["AAA"]["walls"])
    else:
        assert "walls" not in snapshot["technical_detail"]["AAA"]
    assert {row["ticker"] for row in plan["rows"]} == {"AAA", "BBB"}
    assert all(row["grade_source"] == "intraday" for row in plan["rows"])
    assert {row["ticker"]: row["grade_live"] for row in plan["rows"]} == {
        "AAA": "A+",
        "BBB": "B",
    }


# Serve the actual persisted result through authenticated HTTP without recalculation.
@pytest.mark.asyncio
@pytest.mark.parametrize("chain_state", ["absent", "valid", "bad_expiry"])
async def test_live_api_preserves_produced_options_state_without_rewriting(
    tmp_path, monkeypatch, chain_state
):
    from httpx import ASGITransport, AsyncClient

    from backend.api.v1 import market
    from backend.config.settings import settings
    from backend.core import auth
    from backend.core.auth import issue_user_token
    from backend.main import app
    from backend.market import desk_freshness

    plan_path, expected = _run_synthetic_balancer(tmp_path, monkeypatch, chain_state)
    snapshot_path = tmp_path / "desk" / market_balancer.LIVE_FILE
    saved_snapshot = snapshot_path.read_bytes()
    saved_plan = plan_path.read_bytes()
    snapshot = json.loads(saved_snapshot)
    monkeypatch.setattr(market, "datetime", _FixedDatetime)
    monkeypatch.setattr(desk_freshness, "datetime", _FixedDatetime)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "options_test_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)

    # Exclude the unrelated search-metering account lookup, not token verification.
    async def no_search_account_lookup(*args, **kwargs):
        return None

    monkeypatch.setattr(auth, "_bind_search_identity", no_search_account_lookup)

    # Detect any fallback instead of silently supplying another synthetic quote.
    def forbid_recalculation(*args, **kwargs):
        raise AssertionError("The live API must serve the persisted snapshot")

    monkeypatch.setattr(market.alpaca, "credentials", forbid_recalculation)
    monkeypatch.setattr(market.live_quotes, "quotes", forbid_recalculation)
    monkeypatch.setattr(live_technical, "technical_detail", forbid_recalculation)
    monkeypatch.setattr(live_technical, "technical_now", forbid_recalculation)
    token = issue_user_token("options_test_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.get("/api/v1/market/options_test_user/desk/live")
        response = await client.get(
            "/api/v1/market/options_test_user/desk/live",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert denied.status_code == 401
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == "options_test_user"
    assert body["technical"] == expected
    assert body["technical_detail"] == snapshot["technical_detail"]
    assert body["quotes"] == snapshot["quotes"]
    assert body["stale"] is False
    assert body["stale_symbols"] == []
    _assert_raw_walls(body["technical_detail"]["BBB"]["walls"])
    if chain_state == "bad_expiry":
        assert body["technical_detail"]["AAA"]["walls"] == UNAVAILABLE
    elif chain_state == "valid":
        _assert_raw_walls(body["technical_detail"]["AAA"]["walls"])
    else:
        assert "walls" not in body["technical_detail"]["AAA"]
    assert snapshot_path.read_bytes() == saved_snapshot
    assert plan_path.read_bytes() == saved_plan
