"""Exercise real ASGI startup, loopback HTTP and disk state with synthetic quotes."""

import asyncio
import json
import socket
import threading
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx
import pytest
import uvicorn
from pydantic import ValidationError

from backend import main
from backend.config.settings import Settings, settings
from backend.core.auth import issue_user_token
from backend.market import session_price_snapshot, session_prices


# Wait for observable startup or storage changes rather than assuming a fixed delay.
async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.005)


class IdleMaintenance:
    """Only unrelated model/document maintenance is replaced in this HTTP harness."""

    # Accept each existing maintenance constructor without opening dependencies.
    def __init__(self, *args):
        self.started = False

    # Preserve the application lifecycle contract without background side effects.
    def start(self):
        self.started = True

    # Finish unrelated maintenance without altering the collector under test.
    async def stop(self):
        self.started = False


# Start the real app without external dependencies; verify published state and shutdown.
@pytest.mark.asyncio
async def test_lifespan_collects_before_http_and_drains_publication(
    tmp_path, monkeypatch, caplog
):
    root = tmp_path / "market"
    grade_path = root / "desk" / "asof=2026-09-24" / "desk.json"
    grade_path.parent.mkdir(parents=True)
    grade_path.write_text(json.dumps({"grades": {"AAA": {}, "BBB": {}}}))
    original_grade = grade_path.read_bytes()
    path = root / "desk" / "session-prices" / "latest.json"
    now = datetime(2026, 9, 24, 22, tzinfo=UTC)
    failed = False
    block = False
    entered = threading.Event()
    release = threading.Event()
    calls = []

    # Return only dated public quotes, with controlled failure and shutdown boundaries.
    def fetch(symbols):
        calls.append(tuple(symbols))
        if block:
            entered.set()
            assert release.wait(5)
        if failed:
            raise RuntimeError("PRIVATE_PROVIDER_BODY_MUST_NOT_BE_LOGGED")
        return {
            "session": session_prices.session_window(now)[0],
            "as_of": now.isoformat(),
            "signal_scope": "regular-session",
            "quotes": {
                symbol: session_prices.describe(
                    {"bp": 100, "ap": 102, "bs": 10, "as": 10, "t": now.isoformat()},
                    "sip",
                    now,
                )
                for symbol in symbols
            },
        }

    for name in (
        "ImageEmbeddingReconciler",
        "DocumentParseQueue",
        "DocumentArchiver",
        "DriveSync",
    ):
        monkeypatch.setattr(main, name, IdleMaintenance)
    monkeypatch.setattr(main, "get_vision_embedding_provider", lambda: None)
    monkeypatch.setattr(main, "get_binary_artifact_store", lambda: None)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(root))
    monkeypatch.setattr(settings, "MARKET_SESSION_PRICES_ENABLED", True)
    # Accelerate scheduling only; real configuration bounds are tested separately.
    monkeypatch.setattr(settings, "MARKET_SESSION_PRICES_POLL_SECONDS", 0.04)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "collector_test")
    monkeypatch.setattr(session_prices.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(session_price_snapshot, "utc_now", lambda: now)
    monkeypatch.setattr(
        session_price_snapshot,
        "collect",
        partial(session_price_snapshot.collect, fetch=fetch, clock=lambda: now),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    address = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(
            main.app,
            lifespan="on",
            log_config=None,
            access_log=False,
        )
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    endpoint = "/api/v1/market/collector_test/desk/session-prices"
    auth = {"Authorization": "Bearer " + issue_user_token("collector_test")}
    try:
        # There is no HTTP client yet: startup alone must publish the real file.
        await eventually(lambda: server.started and path.exists())
        assert calls == [("AAA", "BBB")]
        initial = path.read_bytes()
        modified = path.stat().st_mtime_ns
        async with (
            httpx.AsyncClient(base_url=address, trust_env=False) as first,
            httpx.AsyncClient(base_url=address, trust_env=False) as second,
        ):
            assert (await first.get(endpoint)).status_code == 401
            wrong = {"Authorization": "Bearer " + issue_user_token("other")}
            assert (await first.get(endpoint, headers=wrong)).status_code == 403
            responses = await asyncio.gather(
                *[
                    client.get(endpoint, headers=auth)
                    for client in (first, second)
                    for _ in range(5)
                ]
            )
            original = json.loads(initial)["snapshot"]
            for response in responses:
                assert response.status_code == 200
                assert response.headers["cache-control"] == "private, no-store"
                assert response.json() == original
            assert calls == [("AAA", "BBB")]
            assert path.read_bytes() == initial
            assert path.stat().st_mtime_ns == modified

            # A new failed pass must replace, not revive, a still-fresh quote.
            failed = True
            now += timedelta(seconds=1)
            await eventually(
                lambda: json.loads(path.read_bytes())["snapshot"]["as_of"] is None
            )
            response = await first.get(endpoint, headers=auth)
            assert response.json()["as_of"] is None
            assert all(
                row["price"] is None for row in response.json()["quotes"].values()
            )
            failed = False
            now += timedelta(seconds=1)
            await eventually(
                lambda: (
                    session_price_snapshot.read(root, ["AAA"])["as_of"]
                    == now.isoformat()
                )
            )
            recovered = (await second.get(endpoint, headers=auth)).json()
            assert recovered["quotes"]["AAA"]["price"] == 101
            assert recovered["as_of"] == now.isoformat()

            # Graceful app shutdown waits for the already-running writer.
            block = True
            now += timedelta(seconds=1)
            await eventually(entered.is_set)
            server.should_exit = True
            await asyncio.sleep(0.15)
            assert not serving.done()
            assert (
                json.loads(path.read_bytes())["snapshot"]["as_of"] == recovered["as_of"]
            )
            release.set()
            await asyncio.wait_for(serving, timeout=5)
        final = path.read_bytes()
        published = json.loads(final)["snapshot"]
        assert published["as_of"] == now.isoformat()
        count = len(calls)
        await asyncio.sleep(0.08)
        assert len(calls) == count == 4
        assert path.read_bytes() == final
        expired = session_price_snapshot.read(
            root, ["AAA"], now=now + timedelta(seconds=61)
        )
        assert expired["quotes"]["AAA"]["status"] == "stale"
        assert expired["quotes"]["AAA"]["price"] is None
        assert expired["as_of"] == published["as_of"]
        assert expired["quotes"]["AAA"]["at"] == published["quotes"]["AAA"]["at"]
        assert grade_path.read_bytes() == original_grade
        assert sorted(
            str(item.relative_to(root)) for item in root.rglob("*") if item.is_file()
        ) == [
            "desk/asof=2026-09-24/desk.json",
            "desk/session-prices/collector.lock",
            "desk/session-prices/latest.json",
        ]
        assert "PRIVATE_PROVIDER_BODY_MUST_NOT_BE_LOGGED" not in caplog.text
    finally:
        release.set()
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        listener.close()


# Production settings limit request cadence and reject non-finite or unsafe intervals.
@pytest.mark.parametrize("interval", [0, 9, 31, float("inf"), float("nan")])
def test_collection_interval_config_is_bounded(interval):
    with pytest.raises(ValidationError):
        Settings(MARKET_SESSION_PRICES_POLL_SECONDS=interval)


# Compose forwards both explicit controls into the one process that collects quotes.
def test_collection_settings_defaults_and_compose_allowlist():
    from pathlib import Path

    import yaml

    assert Settings().MARKET_SESSION_PRICES_ENABLED is True
    assert Settings().MARKET_SESSION_PRICES_POLL_SECONDS == 15
    compose = yaml.safe_load(
        (Path(__file__).parents[2] / "docker-compose.yml").read_text()
    )
    expected = {
        "MARKET_SESSION_PRICES_ENABLED=${MARKET_SESSION_PRICES_ENABLED:-true}",
        "MARKET_SESSION_PRICES_POLL_SECONDS=${MARKET_SESSION_PRICES_POLL_SECONDS:-15}",
    }
    assert expected <= set(compose["services"]["backend"]["environment"])
    for name, service in compose["services"].items():
        if name != "backend":
            assert not any(
                "MARKET_SESSION_PRICES_" in entry
                for entry in service.get("environment", [])
            )
