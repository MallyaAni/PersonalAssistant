"""One private, read-only current-intent observation; never order submission.

This collector measures source compatibility and decisions on actual pending
orders. It neither replaces the live gate nor initializes a trading account,
simulates wealth, commits execution attempts, or claims the frozen September
model is a refitted October policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit

import numpy as np

from backend.market import (
    alpaca,
    alpaca_trading,
    sequential_execution_shadow,
    sequential_shadow_context,
    sequential_shadow_prefix,
)


# Restrict every broker operation to the paper account's three read-only routes.
def paper_transport(method, url, headers, body):
    parsed = urlsplit(url)
    if (
        method != "GET"
        or body is not None
        or parsed.scheme != "https"
        or parsed.netloc != "paper-api.alpaca.markets"
        or parsed.path not in ("/v2/account", "/v2/positions", "/v2/orders")
        or (parsed.path == "/v2/orders" and parsed.query != "status=open&limit=500")
    ):
        raise ValueError("Only ordinary paper-account GETs are permitted")
    return alpaca_trading.urllib_transport(method, url, headers, body)


# Fetch original free IEX response bytes without permitting another host or method.
def market_transport(url, headers):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "data.alpaca.markets"
        or parsed.path != "/v2/stocks/bars"
    ):
        raise ValueError("Only the stock-bars GET endpoint is permitted")
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()


# Persist private artifacts exclusively so later observations cannot rewrite them.
def _write(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
    return hashlib.sha256(content).hexdigest()


# Keep source JSON private with the same exclusive-write rule as endpoint bytes.
def _json(path, value):
    return _write(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


# Preserve every original page before any subsequent provider request or model decision.
def _pages(output, label, pages):
    receipts = []
    for number, page in enumerate(pages):
        name = f"{label}-page-{number:03d}.json"
        if _write(output / name, page["body"]) != page["sha256"]:
            raise ValueError("Endpoint bytes differ from their capture identity")
        receipts.append(
            {key: value for key, value in page.items() if key != "body"}
            | {"file": name}
        )
    return receipts


# Materialize actual causal packets only after the paired source receipts are known.
def _packets(context, raw, anchors):
    received = datetime.fromisoformat(anchors["received_at"])
    packets = {}
    for name, cube in raw["cubes"].items():
        cube.prior_close[0] = anchors["anchors"].get(name, np.nan)
        packets[name] = sequential_execution_shadow.observe(
            context.panel,
            context.grades,
            context.eligible,
            cube,
            raw["observation_clock"],
            received,
            published_at=context.published_at,
            feed="iex",
        )
    return packets


# Bind every receipt to its actual loaded source files and declared built artifact.
def _source():
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    paths = [
        Path(__file__),
        Path(sequential_execution_shadow.__file__),
        Path(sequential_shadow_context.__file__),
        Path(sequential_shadow_prefix.__file__),
    ]
    return {
        "source_revision": os.environ.get(
            "ANIOS_RESEARCH_SOURCE_REVISION",
            revision.stdout.strip() if revision.returncode == 0 else "unavailable",
        ),
        "image_id": os.environ.get("ANIOS_RESEARCH_IMAGE_ID", "unavailable"),
        "numpy": np.__version__,
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
    }


# Capture market evidence on the frozen actual orders without committing an attempt.
def _observe(args, snapshot, output, transport, headers, clock, model_loader):
    context = sequential_shadow_context.load_context(
        args.record, args.daily_partition, snapshot["session"], clock()
    )
    _json(output / "context.json", context.provenance)
    names = tuple(dict.fromkeys(order["symbol"] for order in snapshot["orders"]))
    if set(names) - set(context.panel.tickers):
        raise ValueError("An actual intended order is outside the recorded context")
    raw = sequential_shadow_prefix.capture(
        names, snapshot["session"], transport=transport, headers=headers, clock=clock
    )
    receipts = {"raw": _pages(output, "raw", raw["pages"])}
    if raw["status"] != "captured":
        return {"status": raw["status"], "source_receipts": receipts, "decisions": []}
    anchors = sequential_shadow_prefix.capture_split_anchors(
        raw,
        context.provenance["prior_session"],
        snapshot["session"],
        transport=transport,
        headers=headers,
        clock=clock,
    )
    receipts["split"] = _pages(output, "split", anchors["pages"])
    if anchors["status"] != "captured":
        return {
            "status": anchors["status"],
            "source_receipts": receipts,
            "decisions": [],
        }
    model = model_loader(args.models)
    packets = _packets(context, raw, anchors)
    from backend.agents.trading.desk import paper

    if (
        hashlib.sha256(paper.state_path(args.root).read_bytes()).hexdigest()
        != snapshot["paper_state_sha256"]
    ):
        raise ValueError("Actual intents changed during market/context capture")
    generated = sequential_execution_shadow._aware(clock())
    if generated < datetime.fromisoformat(anchors["received_at"]):
        raise ValueError("Model completion clock cannot precede source receipt")
    if (
        sequential_shadow_prefix.observation_clock(generated, snapshot["session"])
        != raw["observation_clock"]
    ):
        return {
            "status": "model_completion_boundary_crossed",
            "source_receipts": receipts,
            "decisions": [],
            "decision_generated_at": generated.isoformat(),
        }
    decisions = sequential_execution_shadow.inspect_intents(snapshot, packets, model)
    return {
        "status": "observed",
        "source_receipts": receipts,
        "decisions": decisions,
        "model_month": sequential_execution_shadow.MODEL_MONTH,
        "frozen_model_carry_forward": snapshot["session"][:7]
        != sequential_execution_shadow.MODEL_MONTH,
        "model_manifest_sha256": model.manifest_sha256,
        "model_archive_sha256": model.archive_sha256,
        "raw_prior_anchor_symbols": sorted(anchors["anchors"]),
        "anchor_basis": anchors["anchor_basis"],
        "training_prior_source_matches": False,
        "recorded_current_book_differs_from_research_membership": True,
        "recorded_grades_differ_from_recomputed_training_grades": True,
        "market_received_at": anchors["received_at"],
        "decision_generated_at": generated.isoformat(),
        "committed_attempts": False,
        "actual_fills": False,
        "wealth_evaluated": False,
    }


# Freeze and inspect one actual observation into a new private directory outside inputs.
def collect(
    args,
    *,
    client=None,
    transport=market_transport,
    headers=None,
    clock=lambda: datetime.now(UTC),
    model_loader=sequential_execution_shadow.load_model,
):
    output = args.output.resolve()
    protected = (args.root, args.record.parent, args.daily_partition, args.models)
    if any(
        path.resolve() == output or path.resolve() in output.parents
        for path in protected
    ):
        raise ValueError("Private output must be outside all source inputs")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    received = sequential_execution_shadow._aware(clock())
    if client is None:
        client = alpaca_trading.client_from_env(transport=paper_transport)
    if client.base_url != alpaca_trading.PAPER_URL:
        raise ValueError("Paper endpoint required")
    snapshot = sequential_execution_shadow.freeze_intents(
        args.root, client, str(received.date()), clock=clock
    )
    _json(output / "intents.json", snapshot)
    result = {
        "schema": "sequential-shadow-observation/1",
        "session": snapshot["session"],
        "policy": sequential_execution_shadow.POLICY,
        "order_submission": False,
        "production_writes": False,
        "eligible_intents": len(snapshot["orders"]),
        "excluded_intents": len(snapshot["excluded"]),
        "source": _source(),
    }
    if not snapshot["orders"]:
        result["status"] = "no_eligible_intents"
    elif (
        sequential_shadow_prefix.observation_clock(received, snapshot["session"])
        is None
    ):
        result["status"] = "unsupported_observation_time"
    else:
        try:
            result.update(
                _observe(
                    args,
                    snapshot,
                    output,
                    transport,
                    headers if headers is not None else alpaca.credentials(),
                    clock,
                    model_loader,
                )
            )
        except sequential_shadow_prefix.CaptureError as exc:
            result.update(
                status="source_capture_failed",
                error=str(exc),
                failed_pages=_pages(output, "failed", exc.pages),
            )
        except (ValueError, OSError) as exc:
            result.update(status="input_validation_failed", error=str(exc))
    _json(output / "observation.json", result)
    return result


# Require explicit original source paths rather than choosing a stale latest artifact.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "record", "daily-partition", "models", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    result = collect(args)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "session",
                    "eligible_intents",
                    "excluded_intents",
                    "order_submission",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
