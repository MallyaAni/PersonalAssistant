"""Restore published timing for explicitly learned paper intents in the sender.

This does not promote a holding policy. The nightly must first select that
policy and stamp its intents; ordinary incumbent orders never load these models.
Original IEX evidence remains a different source from the training archive.
"""

import base64
import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from urllib import error, request
from urllib.parse import urlsplit

import numpy as np

from backend.market import (
    alpaca,
    calendar,
    forward_execution,
    sequential_shadow_context,
)
from backend.market import forward_market_evidence as market
from backend.market import forward_probability_timing as timing
from backend.market.live_probability_timing import POLICY

CONFIG = "desk/learned-timing/config.json"


# Preserve the original endpoint instead of forwarding credentials through redirects.
class _NoRedirect(request.HTTPRedirectHandler):
    # Let urllib return the original HTTP failure without issuing another request.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Keep the scheduled job on the incumbent when no learned artifacts are installed.
def configured(root):
    return (Path(root) / CONFIG).is_file()


# Resolve only artifact folders under the dedicated installed timing directory.
def _folder(root, name):
    base = (Path(root) / CONFIG).parent.resolve()
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Relative installed timing artifact directory required")
    path = (base / name).resolve()
    if path == base or not path.is_relative_to(base):
        raise ValueError("Timing artifacts must remain under their installed root")
    return path


# Restrict source capture to free stock bars and quotes, without a write operation.
def market_transport(url, headers):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "data.alpaca.markets"
        or parsed.path not in ("/v2/stocks/bars", "/v2/stocks/quotes/latest")
    ):
        raise ValueError("Only original stock-bar and quote GETs are permitted")
    query = request.Request(url, headers=headers, method="GET")
    try:
        with request.build_opener(_NoRedirect()).open(query, timeout=15) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()


# Build current inference inside the sender's account lock from installed heads only.
def observe(root, rows, snapshot, now, client_factory, *, transport=None, clock=None):
    selected = [
        row
        for row in rows
        if row.get("timing_policy") == POLICY and "execution_policy" not in row
    ]
    if not selected:
        return snapshot, now, None
    clock = clock or (lambda: datetime.now(calendar.NEW_YORK))
    started = market._as_of(clock())
    session, _, completed = market._window(started)
    market._same_window(completed, started, market._as_of(now))
    raw_config = (Path(root) / CONFIG).read_bytes()
    config = json.loads(raw_config)
    if (
        set(config)
        != {
            "policy",
            "model_directory",
            "model_receipt_sha256",
            "residual_directory",
            "residual_receipt_sha256",
            "cost_bps",
        }
        or config["policy"] != POLICY
        or isinstance(config["cost_bps"], bool)
        or not isinstance(config["cost_bps"], (int, float))
        or not np.isfinite(config["cost_bps"])
        or not 0 <= config["cost_bps"] < 10000
    ):
        raise ValueError("Exact published timing configuration required")
    residual = timing.load_residual_month(
        _folder(root, config["residual_directory"]),
        receipt_sha256=config["residual_receipt_sha256"],
        observed_at=started,
    )
    model_folder = _folder(root, config["model_directory"])
    _, publication = forward_execution.load_publication(
        model_folder,
        receipt_sha256=config["model_receipt_sha256"],
        observed_at=started,
    )
    identity = residual.receipt["identity"]
    if (
        publication["identity"]["input_identity"].get("cohort")
        != identity["archive_identity"]["cohort"]
        or publication["training"]["fit_date"] != identity["fit_date"]
    ):
        raise ValueError("Published timing head and residual cohort/month differ")
    _, exchange = calendar.reviewed_sessions()
    prior = str(np.busday_offset(np.datetime64(session), -1, busdaycal=exchange))
    context = sequential_shadow_context.load_context(
        Path(root) / "desk" / f"asof={prior}" / "desk.json",
        Path(root) / "bars" / f"asof={prior}",
        session,
        started,
    )
    if tuple(context.panel.tickers) != tuple(residual.receipt["identity"]["symbols"]):
        raise ValueError("Current book differs from the published model cohort")
    if any(row.get("symbol") not in context.panel.tickers for row in selected):
        raise ValueError("Learned intent has no authenticated stock context")
    try:
        packet = market.capture(
            context.panel.tickers,
            transport=transport or market_transport,
            headers=alpaca.credentials(),
            clock=clock,
        )
    except market.source.CaptureError as exc:
        # Preserve original failed receipts privately without recording credentials.
        failure = {
            "contract": "learned-market-unavailable/1",
            "config_sha256": sha256(raw_config).hexdigest(),
            "observed_at": started.isoformat(),
            "pages": [
                {
                    **{
                        key: page[key]
                        for key in (
                            "url",
                            "requested_at",
                            "received_at",
                            "status",
                            "sha256",
                        )
                    },
                    "body_base64": base64.b64encode(page["body"]).decode(),
                }
                for page in exc.pages
            ],
            "forecast_available": False,
        }
        timing._store_inference(root, failure, timing._digest(failure))
        raise
    # The context's empty current-day row is not a published daily model input.
    panel = SimpleNamespace(
        dates=context.panel.dates[:-1],
        tickers=context.panel.tickers,
        adj_close=context.panel.adj_close[:-1],
    )
    forecast = market.prepare_forecast(
        packet,
        panel,
        context.grades[:-1],
        context.eligible[:-1],
        daily_as_of=context.published_at,
        model_folder=model_folder,
        model_receipt_sha256=config["model_receipt_sha256"],
        residual_month=residual,
        clock=clock,
    )
    sequential_shadow_context._check_unchanged(context.provenance["sources"])
    receipt = deepcopy(forecast.receipt)
    receipt["live_dispatch"] = {
        "config_sha256": sha256(raw_config).hexdigest(),
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "context": deepcopy(context.provenance),
        "strategy_promotion": False,
    }
    forecast = timing.ObservedForecast(
        forecast.distributions,
        receipt,
        timing._digest(receipt),
    )
    account = timing.capture_account(client_factory(), completed, clock=clock)
    available = market._as_of(clock())
    market._same_window(completed, available, started)
    if (Path(root) / CONFIG).read_bytes() != raw_config:
        raise ValueError("Installed timing configuration changed during inference")
    reader = timing.build_forecast_reader(
        forecast,
        available,
        packet.snapshot,
        rows,
        account,
        config["cost_bps"],
        [],
        evidence_root=Path(root),
    )
    return packet.snapshot, available, reader
