"""Installed learned artifacts must drive the actual locked sender, without fitting."""

import base64
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import calendar, live_probability_timing
from backend.market import forward_probability_timing as forward
from backend.market import learned_live_timing as runtime
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_forward_execution import residual_month, write
from backend.tests.test_forward_market_evidence import NOW, capture_payloads
from backend.tests.test_forward_probability_timing import inference_inputs
from backend.tests.test_live_probability_timing import intent


# Install real synthetic numeric heads and independently published residual arrays.
def install(root, fitted, residual_archive):
    folder = (root / runtime.CONFIG).parent
    folder.mkdir(parents=True)
    digest = write(folder / "models", fitted[1])
    residual_sha = forward.write_residual_month(
        folder / "residuals",
        residual_month(residual_archive[1]),
        clock=lambda: "2026-10-05T08:00:00-04:00",
    )
    config = {
        "policy": live_probability_timing.POLICY,
        "model_directory": "models",
        "model_receipt_sha256": digest,
        "residual_directory": "residuals",
        "residual_receipt_sha256": residual_sha,
        "cost_bps": 10,
    }
    (root / runtime.CONFIG).write_text(json.dumps(config))
    return config


# Adapt existing synthetic daily inputs to the actual prior-record loader's shape.
def context():
    (panel, grades, eligible, _), clocks = inference_inputs()
    return SimpleNamespace(
        panel=SimpleNamespace(
            dates=np.append(panel.dates, np.datetime64(NOW.date())),
            tickers=panel.tickers,
            adj_close=np.vstack((panel.adj_close, np.full(len(panel.tickers), np.nan))),
        ),
        grades=np.vstack((grades, np.full(len(panel.tickers), -1))),
        eligible=np.vstack((eligible, np.zeros(len(panel.tickers), dtype=bool))),
        published_at=clocks["daily_as_of"],
        provenance={"schema": "synthetic_published_context", "sources": {}},
    )


# Preserve a pending learned leg and the private broker's actual funding clock.
def pending(root, *, side="buy", price=99):
    row = intent(symbol="AAOI", qty=5, side=side)
    row["execute_on"] = NOW.date().isoformat()
    row["timing_policy"] = live_probability_timing.POLICY
    state = paper.PaperState()
    state.pending = [row]
    paper.save_state(root, state)
    client = ReplayBroker(
        10000,
        0,
        initial_holdings={"AAOI": 5} if side == "sell" else {},
        initial_average_prices={"AAOI": 90} if side == "sell" else {},
    )
    client.observe(NOW, {"AAOI": price}, True)
    return client, row


# The installed factory must restore numeric inference under the actual paper lock.
@pytest.mark.parametrize(("side", "price"), [("buy", 99), ("sell", 150)])
def test_installed_heads_drive_locked_sender(
    fitted, residual_archive, tmp_path, monkeypatch, side, price
):
    config = install(tmp_path, fitted, residual_archive)
    client, row = pending(tmp_path, side=side, price=price)
    original_transaction = paper.transaction
    locked = []
    seen = []
    source = context()
    original_observe = runtime.observe
    original_bodies = capture_payloads(
        NOW,
        datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK),
    )
    quotes = json.loads(original_bodies[-1])
    for quote in quotes["quotes"].values():
        quote.update(bp=price - 0.005, ap=price + 0.005)
    original_bodies[-1] = json.dumps(quotes).encode()
    bodies = iter(original_bodies)

    # Retain the actual file lock while making its lifetime inspectable.
    @contextmanager
    def transaction(root):
        with original_transaction(root):
            locked.append(True)
            try:
                yield
            finally:
                locked.pop()

    # Supply synthetic daily inputs; run real source parsing and numeric inference.
    def load_context(record, partition, session, captured):
        assert locked
        assert record == tmp_path / "desk/asof=2026-10-02/desk.json"
        assert partition == tmp_path / "bars/asof=2026-10-02"
        assert session == NOW.date()
        return source

    # Exercise the real source acquisition without using an external provider.
    def transport(url, headers):
        assert locked
        seen.append(url)
        return 200, next(bodies)

    # Keep the original installed-artifact path with only an explicit synthetic clock.
    def observe(root, rows, snapshot, now, factory):
        assert locked
        assert rows == [row]
        return original_observe(
            root,
            rows,
            snapshot,
            now,
            factory,
            transport=transport,
            clock=lambda: NOW + timedelta(seconds=2),
        )

    # Runtime execution may restore heads but must never train replacements.
    def forbidden(*args, **kwargs):
        pytest.fail("Live timing attempted model fitting")

    monkeypatch.setattr(paper, "transaction", transaction)
    monkeypatch.setattr(runtime.sequential_shadow_context, "load_context", load_context)
    monkeypatch.setattr(runtime.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(runtime, "observe", observe)
    from backend.market import learned_entry_models

    monkeypatch.setattr(learned_entry_models, "_estimator", forbidden)
    lines = intraday_orders.send_due(tmp_path, {}, NOW, lambda: client)
    assert len(lines) == 1
    assert "sent" in lines[0]
    stored = paper.load_state(tmp_path).pending[0]
    reference = stored["sent"]["forward_timing"]["receipt"]["inference"]
    original = (tmp_path / reference["path"]).read_bytes()
    assert sha256(original).hexdigest() == reference["sha256"]
    receipt = json.loads(original)
    assert (
        receipt["live_dispatch"]["config_sha256"]
        == sha256((tmp_path / runtime.CONFIG).read_bytes()).hexdigest()
    )
    assert receipt["live_dispatch"]["context"] == source.provenance
    assert receipt["live_dispatch"]["strategy_promotion"] is False
    assert len(seen) == 3
    assert stored["qty"] == 5
    assert stored["side"] == side
    assert len(client.orders_since("2026-10-05T00:00:00Z")) == 1
    assert intraday_orders.send_due(tmp_path, {}, NOW, lambda: client) == []
    assert len(seen) == 3
    assert json.loads((tmp_path / runtime.CONFIG).read_bytes()) == config


# Incumbent-only rows must not load models, read a broker or fetch market evidence.
def test_no_learned_intents_do_nothing(tmp_path):
    assert not runtime.configured(tmp_path)
    assert runtime.observe(tmp_path, [], {}, NOW, None) == ({}, NOW, None)


# A learned paper row cannot describe an unsent order using the incumbent percent level.
def test_learned_paper_view_never_displays_incumbent_threshold(tmp_path):
    _, row = pending(tmp_path)
    shown = intraday_orders.board_row(
        row, broker=None, latch=None,
        quote={"open": 100, "last": 90, "bar": "2026-10-05T13:30:00Z"},
        held=0, price=90, equity=10000, now=NOW,
    )
    assert shown["timing_policy"] == live_probability_timing.POLICY
    assert "1%" not in shown["when"]
    assert "1%" not in shown["status"]
    assert shown["state"] == "waiting"


# A learned source failure cannot fire the incumbent's one-percent trigger.
def test_failed_factory_retains_learned_intent(tmp_path):
    client, row = pending(tmp_path)

    # Represent an unavailable authentic publication, not a replacement prediction.
    def unavailable(*args):
        raise ValueError("Original publication unavailable")

    snapshot = {"quotes": {"AAOI": {"open": 100, "price": 90, "bar": NOW.isoformat()}}}
    lines = intraday_orders.send_due(
        tmp_path,
        snapshot,
        NOW,
        lambda: client,
        timing_reader_factory=unavailable,
    )
    assert lines == ["learned timing unavailable; ordinary intents retained"]
    assert paper.load_state(tmp_path).pending == [row]
    assert client.orders_since("2026-10-05T00:00:00Z") == []


# Missing, backward or changed-date factory clocks cannot publish an execution reader.
@pytest.mark.parametrize(
    "instant",
    [
        None,
        NOW.replace(tzinfo=None),
        NOW - timedelta(seconds=1),
        NOW + timedelta(days=1),
        NOW + timedelta(minutes=15),
    ],
)
def test_invalid_factory_observation_does_not_send(tmp_path, instant):
    client, row = pending(tmp_path)

    # Return malformed observation metadata without fabricating a valid forecast.
    def invalid(*args):
        return {}, instant, None

    assert intraday_orders.send_due(
        tmp_path,
        {},
        NOW,
        lambda: client,
        timing_reader_factory=invalid,
    ) == ["learned timing unavailable; ordinary intents retained"]
    assert paper.load_state(tmp_path).pending == [row]


# An installed artifact path must not escape into unrelated data or secrets.
@pytest.mark.parametrize("path", ["../private", "/tmp/models", ".", ""])
def test_artifact_directory_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError, match="artifact|installed root"):
        runtime._folder(tmp_path, path)


# Changed installed model bytes must stop before any external market request.
def test_tampered_model_prevents_source_requests(fitted, residual_archive, tmp_path):
    install(tmp_path, fitted, residual_archive)
    client, row = pending(tmp_path)
    model = (tmp_path / runtime.CONFIG).parent / "models/models.npz"
    model.write_bytes(model.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="model bytes differ"):
        runtime.observe(tmp_path, [row], {}, NOW, lambda: client, clock=lambda: NOW)
    assert client.orders_since("2026-10-05T00:00:00Z") == []


# A failed original HTTP body is durable evidence, never an invented numeric forecast.
def test_original_source_failure_is_preserved(
    fitted, residual_archive, tmp_path, monkeypatch
):
    install(tmp_path, fitted, residual_archive)
    client, row = pending(tmp_path)
    monkeypatch.setattr(
        runtime.sequential_shadow_context, "load_context", lambda *args: context()
    )
    monkeypatch.setattr(
        runtime.alpaca, "credentials", lambda: {"APCA-API-KEY-ID": "private-secret"}
    )
    with pytest.raises(ValueError, match="unavailable"):
        runtime.observe(
            tmp_path,
            [row],
            {},
            NOW,
            lambda: client,
            transport=lambda *args: (503, b'{"message":"unavailable"}'),
            clock=lambda: NOW,
        )
    files = list((tmp_path / "paper/forecast-evidence").glob("*.json"))
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    original = files[0].read_bytes()
    receipt = json.loads(original)
    assert receipt["forecast_available"] is False
    assert receipt["pages"][0]["status"] == 503
    assert (
        base64.b64decode(receipt["pages"][0]["body_base64"])
        == b'{"message":"unavailable"}'
    )
    assert b"private-secret" not in original
    assert paper.load_state(tmp_path).pending == [row]
    assert client.orders_since("2026-10-05T00:00:00Z") == []


# The final execution deadline must not launch a new numeric observation or fetch.
def test_final_deadline_does_not_start_factory(tmp_path):
    client, _ = pending(tmp_path)
    final = NOW.replace(hour=15, minute=46)
    client.observe(final, {"AAOI": 99}, True)

    # Fail if the original deadline starts another source observation.
    def forbidden(*args):
        pytest.fail("Closing deadline started a new learned forecast")

    lines = intraday_orders.send_due(
        tmp_path,
        {},
        final,
        lambda: client,
        timing_reader_factory=forbidden,
    )
    assert len(lines) == 1
    assert "sent" in lines[0]
    assert paper.load_state(tmp_path).pending[0]["sent"]["how"] == "market"


# Original-endpoint capture must not follow a redirect with credential headers.
def test_market_transport_installs_redirect_refusal(monkeypatch):
    seen = []

    # Reject the unguarded convenience opener used before this boundary was enforced.
    def unsafe(*args, **kwargs):
        pytest.fail("Market transport used a redirect-following convenience opener")

    # Exercise an original endpoint failure through the explicitly guarded opener.
    def opener(handler):
        assert (
            handler.redirect_request(
                None, None, 302, "redirect", {}, "https://other.example"
            )
            is None
        )

        # Return the actual HTTP error instead of following its alternate endpoint.
        def opening(query, timeout):
            seen.append(query.full_url)
            from io import BytesIO

            raise runtime.error.HTTPError(
                query.full_url, 302, "redirect", {}, BytesIO(b"original redirect")
            )

        return SimpleNamespace(open=opening)

    monkeypatch.setattr(runtime.request, "urlopen", unsafe)
    monkeypatch.setattr(runtime.request, "build_opener", opener)
    result = runtime.market_transport(
        "https://data.alpaca.markets/v2/stocks/quotes/latest?feed=iex",
        {},
    )
    assert result == (302, b"original redirect")
    assert len(seen) == 1
