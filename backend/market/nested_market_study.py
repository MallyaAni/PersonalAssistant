"""Matched, independently reconciled research accounts around real nested fits.

This companion leaves the incumbent and all producer ledgers unchanged. It does
not fetch data, trade, promote a policy, or make examined history untouched.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, fields, is_dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from itertools import chain
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

from backend.agents.trading.desk import event_risk, paper, risk, simulate
from backend.market import calendar
from backend.market import nested_allocation as nested
from backend.market import neural_study_metrics as metrics
from backend.market.allocation_attribution import attribution
from backend.market.allocation_controls import adjusted_open, constant_exposure
from backend.market.allocation_replay import AllocationInstruction, replay
from backend.market.forecast_diagnostics import diagnose
from backend.market.research_journal import ResearchJournal, _new_directory
from backend.market.research_journal_replay import verify_archive, verify_snapshot

if TYPE_CHECKING:
    from backend.market.nested_market_inputs import StudyInputs

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = ROOT / "docs/research/nested-market-study-2026-09-24.md"
POLICY = "nested-market-study/1-research"
ACCOUNT_NAMES = (
    "candidate",
    "no_gate_adapter",
    "incumbent",
    "SPY",
    "QQQ",
    "equal_weight",
)
_BUFFER_BYTES = 64 * 1024


# Bind the declared protocol and inclusive producer/source code before any fits.
def _source_hashes():
    paths = {
        PROTOCOL_PATH,
        Path(__file__),
        ROOT / "backend/cli/market_nested_study.py",
        calendar.FOMC_PATH,
        calendar.HOLIDAYS_PATH,
    }
    for folder in ("backend/market", "backend/agents/trading/desk"):
        paths.update((ROOT / folder).rglob("*.py"))
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


# Preserve the exact incumbent configuration rather than infer it from its report.
def _configuration():
    if (
        paper.POLICY_VERSION != "cash-bounded-breakout-rotation/3"
        or paper.REBALANCE_EVERY != 20
    ):
        raise ValueError(
            "The frozen comparison requires the unchanged /3 policy and cadence"
        )
    expected_sizing = {
        "top_fraction": 0.1,
        "short_fraction": 0.0,
        "volatility_lookback": 60,
        "min_volatility": 0.1,
        "target_volatility": 0.3,
        "max_gross": 1.0,
        "name_cap": 0.15,
        "theme_cap": 0.4,
        "rebalance_every": 20,
        "speed": 0.5,
        "min_trade": 0.005,
        "cost_bps": 10.0,
    }
    expected_flags = {
        "block_overbought": True,
        "exit_at_close": True,
        "green_day_skip": True,
        "live_midcycle": True,
        "deferred_buys": True,
    }
    if (
        asdict(risk.BOOK_CONFIG) != expected_sizing
        or expected_flags != simulate.LIVE_POLICY
        or str(event_risk.GUIDANCE_CHANGE) != "2026-06-18"
        or event_risk.VERSION != "fomc-3-session-weakness/2"
    ):
        raise ValueError("The incumbent configuration differs from the frozen protocol")
    return {
        "policy": paper.POLICY_VERSION,
        "sizing": asdict(risk.BOOK_CONFIG),
        "rebalance": paper.REBALANCE_EVERY,
        "use_exits": False,
        "event_lifecycle": True,
        "event_policy": event_risk.VERSION,
        "event_guidance_change": str(event_risk.GUIDANCE_CHANGE),
        "live_policy": dict(simulate.LIVE_POLICY),
        "cash_yield": 0.0,
        "terminal_liquidation": False,
        "costs_bps": list(nested.COSTS),
        "adapter_stock_cadence": nested.STOCK_CADENCE,
        "adapter_cadence_anchor": (
            "absolute source row zero; initial effective basket seeded"
        ),
        "index_control_cadence": (
            "daily close-sized, next-open funded constant exposure"
        ),
    }


# Refuse a substituted report, calendar, price basis, or malformed label sidecar.
def _bind_inputs(report, inputs):
    from backend.market.nested_market_inputs import binding

    if inputs.report is not report:
        raise ValueError("The original report must be the one bound to StudyInputs")
    if inputs.audit.get("book_config") != asdict(risk.BOOK_CONFIG):
        raise ValueError(
            "Stock baskets were not built under the pinned book configuration"
        )
    if inputs.audit.get("assembly_binding") != binding(report):
        raise ValueError("Assembly binding changed: report state or source differs")
    source, execution = report.panel, inputs.panel
    if not np.array_equal(source.dates, execution.dates):
        raise ValueError("Original report and execution calendars must match exactly")
    if "QQQ" in source.tickers or set(execution.tickers) != set(source.tickers) | {
        "QQQ"
    }:
        raise ValueError("Execution must preserve original symbols and add only QQQ")
    columns = [execution.tickers.index(symbol) for symbol in source.tickers]
    for name in ("open", "high", "low", "close", "adj_close", "volume"):
        if not np.array_equal(
            getattr(source, name), getattr(execution, name)[:, columns], equal_nan=True
        ):
            raise ValueError(f"Original report {name} differs from execution source")
    shape = (len(execution.dates), 3)
    if (
        np.asarray(inputs.raw_labels).shape != shape
        or np.asarray(inputs.label_end_on).shape != shape
    ):
        raise ValueError("Raw labels and endpoints must preserve all three targets")
    if not np.array_equal(
        inputs.label_end_on, inputs.regression.label_end_on, equal_nan=True
    ):
        raise ValueError("Raw label endpoints must match the regression declaration")
    # Reuse the runner's shape/cadence validator, without fitting any observations.
    nested._inputs(execution, inputs.regression, inputs.equal_weights)


# Bind one recorder to its own complete source grid, never another account's slice.
def _journal(panel, cost, name, configuration):
    return ResearchJournal(
        panel.dates,
        panel.tickers,
        adjusted_open(panel.open, panel.close, panel.adj_close),
        panel.adj_close,
        run_id=POLICY,
        account_id=f"{name}:{cost}",
        policy_id=paper.POLICY_VERSION if name == "incumbent" else POLICY,
        cost_bps=cost,
        provenance={
            "study": POLICY,
            "configuration": configuration,
            "historical_availability_verified": False,
        },
        raw_prices={
            "open": panel.open,
            "close": panel.close,
            "adjusted_close": panel.adj_close,
        },
    )


# Build every metric exclusively from fresh independent journal reconstruction.
def _verified_account(snapshot, expected_dates, expected_nav, expected_traded=None):
    proof = verify_snapshot(snapshot)
    if not proof["ok"]:
        raise ValueError(f"Independent journal verification failed: {proof['errors']}")
    marks = proof["marks"]
    dates = np.asarray([mark["session"] for mark in marks], dtype="datetime64[D]")
    nav = np.asarray([mark["nav"] for mark in marks])
    if not np.array_equal(dates, expected_dates):
        raise ValueError("Journal marks do not match the complete account calendar")
    if np.asarray(expected_nav).shape != nav.shape or not np.allclose(
        nav, expected_nav, rtol=1e-12, atol=1e-12
    ):
        raise ValueError("Producer NAV differs from independent reconstruction")
    if expected_traded is not None and not math.isclose(
        proof["total_traded"], expected_traded, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError(
            "Producer traded notional differs from independent reconstruction"
        )
    positions = np.asarray([mark["positions"] for mark in marks])
    indices = [mark["session_index"] for mark in marks]
    # The incumbent keeps the full grid; sliced adapters index from their own zero.
    prices = np.asarray(snapshot["prices"]["close"], dtype=float)[indices]
    values = np.zeros_like(positions)
    np.multiply(positions, prices, out=values, where=positions > 0)
    curve = metrics.Curve(
        dates,
        nav,
        snapshot["manifest"]["cost_bps"],
        proof["total_traded"],
        values.sum(axis=1) / nav,
        values.max(axis=1) / nav,
    )
    metrics._validated(curve)
    return {
        "curve": curve,
        "journal": snapshot,
        "verification": proof,
        "journal_sha256": _json_digest(snapshot),
    }


# Keep the original report and exact live flags on a fresh, matched incumbent account.
def _incumbent(report, first, cost, configuration, event_path):
    journal = _journal(report.panel, cost, "incumbent", configuration)
    result = simulate.run(
        report,
        since=report.panel.dates[first].astype(object),
        config=risk.BOOK_CONFIG,
        rebalance=paper.REBALANCE_EVERY,
        cost_bps=cost,
        use_exits=False,
        event_exposure=event_path,
        event_lifecycle=True,
        journal=journal,
        **simulate.LIVE_POLICY,
    )
    return _verified_account(
        journal.snapshot(), report.panel.dates[first:], result.equity, result.traded
    )


# Preserve the source's remaining execution window without dropping any session.
def _window(panel, first, columns=None):
    columns = list(range(len(panel.tickers))) if columns is None else columns
    return SimpleNamespace(
        dates=panel.dates[first:],
        tickers=tuple(panel.tickers[j] for j in columns),
        **{
            name: getattr(panel, name)[first:, columns]
            for name in ("open", "close", "adj_close")
        },
    )


# Run each index through the canonical daily funded control, including every fee.
def _index_account(panel, first, cost, symbol, configuration):
    window = _window(panel, first, [panel.tickers.index(symbol)])
    journal = _journal(window, cost, symbol, configuration)
    opens = adjusted_open(window.open, window.close, window.adj_close)[:, 0]
    nav = constant_exposure(
        window.adj_close[:, 0],
        opens,
        1.0,
        cost,
        journal=journal,
        sessions=window.dates,
        symbol=symbol,
    )
    return _verified_account(journal.snapshot(), window.dates, nav)


# Execute equal weights on the same absolute composition schedule as the gate.
def _equal_account(panel, weights, first, cost, configuration):
    window = _window(panel, first)
    instructions = []
    for t in range(first, len(panel.dates) - 1):
        basket = None
        if t == first or t % nested.STOCK_CADENCE == 0:
            basket = {
                symbol: float(weight)
                for symbol, weight in zip(panel.tickers, weights[t], strict=True)
                if weight > 0
            }
        instructions.append(
            AllocationInstruction(
                str(panel.dates[t]),
                str(panel.dates[t]),
                f"equal-weight:{t}",
                1.0,
                0.0,
                0.0,
                stock_weights=basket,
            )
        )
    journal = _journal(window, cost, "equal_weight", configuration)
    result = replay(window, instructions, cost_bps=cost, journal=journal)
    return _verified_account(journal.snapshot(), window.dates, result["nav"])


# Attribute an actual fitted fold using carried account marks and local trading totals.
def _fold_curve(account, first, stop):
    curve, marks = account["curve"], account["verification"]["marks"]
    cut = slice(first, stop + 1)
    return replace(
        curve,
        dates=curve.dates[cut],
        equity=curve.equity[cut],
        traded_notional=marks[stop]["traded"] - marks[first]["traded"],
        invested_fraction=curve.invested_fraction[cut],
        largest_position_fraction=curve.largest_position_fraction[cut],
    )


# Retain matched scorecards, actual fit folds and descriptive decision/fill outcomes.
def _scorecards(accounts, fitted, panel, first):
    evidence = metrics.RegimeEvidence(
        panel.dates, panel.adj_close[:, panel.tickers.index("SPY")]
    )
    full = {}
    for cost in nested.COSTS:
        curves = {
            name: account["curve"] for name, account in accounts[str(cost)].items()
        }
        full[str(cost)] = {
            "performance": metrics.scorecard(curves, cost_bps=cost),
            "regimes": metrics.regime_scorecard(
                curves, cost_bps=cost, evidence=evidence
            ),
            "decision_outcomes": attribution(
                {
                    name: account["journal"]
                    for name, account in accounts[str(cost)].items()
                },
                cost_bps=cost,
            ),
        }
    folds = []
    for fold in fitted["outer_folds"]:
        start, stop = fold["start"] - first, fold["stop"] - first
        tables = {}
        for cost in nested.COSTS:
            curves = {
                name: _fold_curve(account, start, stop)
                for name, account in accounts[str(cost)].items()
            }
            tables[str(cost)] = {
                "performance": metrics.scorecard(curves, cost_bps=cost),
                "regimes": metrics.regime_scorecard(
                    curves, cost_bps=cost, evidence=evidence
                ),
            }
        folds.append(
            {
                "source_start": fold["start"],
                "source_stop_exclusive": fold["stop"],
                "selected_id": fold["selected_id"],
                "model_hash": fold["model_hash"],
                "fit_receipt_sha256": fold["fit_receipt_sha256"],
                "cost_levels": tables,
            }
        )
    return {
        "full_sample": full,
        "actual_outer_folds": folds,
        "folds_refit_performed": True,
        "independent_validation": False,
        "fold_accounting": (
            "Carried marks [start,stop]; cumulative traded differences; "
            "no resets or added costs"
        ),
        "regime_source": "Full source SPY adjusted closes, never funded benchmark NAV",
    }


# Record installed dependency versions and checkout identity without changing Git state.
def _runtime():
    dependencies = {}
    for name in ("numpy", "pandas", "pyarrow", "exchange_calendars"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    git = {}
    for key, command in (
        ("head", ["rev-parse", "HEAD"]),
        ("working_tree", ["status", "--porcelain"]),
    ):
        try:
            result = subprocess.run(
                ["git", "-C", str(ROOT), *command],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            git[key] = (
                result.stdout.strip() if result.returncode == 0 else "UNAVAILABLE"
            )
        except (OSError, subprocess.TimeoutExpired):
            git[key] = "UNAVAILABLE"
    return {
        "python": sys.version,
        "dependencies": dependencies,
        "architecture": platform.machine(),
        "git": git,
    }


# Compare actual outer forecasts and six reconciled accounts under the frozen geometry.
def run(report, inputs: StudyInputs, *, protocol=nested.DEFAULT_PROTOCOL):
    _bind_inputs(report, inputs)
    hashes = _source_hashes()
    configuration = _configuration()
    # Refresh this process's cached holiday interpretation from the pinned file.
    calendar._published_sessions.cache_clear()
    event_path = event_risk.live_path(report.panel)
    fitted = nested.run(
        inputs.panel, inputs.regression, inputs.stock_weights, protocol=protocol
    )
    first = protocol.first_outer
    dates = inputs.panel.dates[first:]
    accounts = {}
    for cost in nested.COSTS:
        group = {}
        for name in ("candidate", "no_gate_adapter"):
            account = fitted["accounts"][str(cost)][name]
            group[name] = _verified_account(
                account["journal"], dates, account["result"]["nav"]
            )
        group["incumbent"] = _incumbent(report, first, cost, configuration, event_path)
        for symbol in ("SPY", "QQQ"):
            group[symbol] = _index_account(
                inputs.panel, first, cost, symbol, configuration
            )
        group["equal_weight"] = _equal_account(
            inputs.panel, inputs.equal_weights, first, cost, configuration
        )
        if any(
            not np.array_equal(account["curve"].dates, dates)
            for account in group.values()
        ):
            raise ValueError("Every comparator must retain exactly the same calendar")
        accounts[str(cost)] = group
    summary = _scorecards(accounts, fitted, inputs.panel, first)
    summary["forecast_diagnostics"] = diagnose(
        inputs.regression,
        fitted["outer_folds"],
        first_decision=first,
        stop_decision=len(inputs.panel.dates) - 1,
        evaluated_on=inputs.panel.dates[-1],
    )
    _bind_inputs(report, inputs)
    if hashes != _source_hashes() or configuration != _configuration():
        raise ValueError("Source or configuration changed during the study")
    evidence = {
        "schema": POLICY,
        "nested": fitted,
        "accounts": accounts,
        "summary": summary,
        "configuration": configuration,
        "source_hashes": hashes,
        "protocol_document": str(PROTOCOL_PATH.relative_to(ROOT)),
        "protocol_document_sha256": hashes[str(PROTOCOL_PATH.relative_to(ROOT))],
        "input_audit": inputs.audit,
        "additional_inputs": {
            "raw_labels": np.array(inputs.raw_labels, copy=True),
            "label_end_on": np.array(inputs.label_end_on, copy=True),
            "equal_weights": np.array(inputs.equal_weights, copy=True),
            "incumbent_event_exposure": event_path.copy(),
        },
        "runtime": _runtime(),
        "accounting_verified": True,
        "benchmark_study_complete": True,
        "independent_validation": False,
        "historical_availability_verified": False,
        "adoption_eligible": False,
        "interpretation": (
            "Exploratory comparison on examined history; proxy labels are not "
            "funded account P&L"
        ),
    }
    evidence["evidence_sha256"] = _evidence_digest(evidence)
    return evidence


# Reject unsafe or existing destinations before loading inputs or spending on fits.
def check_destination(destination):
    path = Path(destination)
    if ".." in path.parts:
        raise ValueError("Study output cannot contain parent traversal")
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Study output cannot traverse symlinks")
    if path.exists() or not path.parent.is_dir():
        raise ValueError("Study output must be new, with an existing parent")
    return path


# Enumerate every outer and inner ledger under generated, non-user-controlled names.
def _journals(evidence):
    rows = [
        (f"outer-{cost}-{name}", account["journal"])
        for cost, group in evidence["accounts"].items()
        for name, account in group.items()
    ]
    rows.extend(
        (f"inner-{number:04d}", account["journal"])
        for number, account in enumerate(evidence["nested"]["inner_runs"])
    )
    return rows


# Preserve arrays without pickle and represent all remaining evidence as explicit JSON.
def _pack(value, arrays, journal_paths):  # noqa: C901 - explicit serialization types
    if id(value) in journal_paths:
        return {"journal_archive": journal_paths[id(value)]}
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise ValueError("Object arrays are not permitted in study archives")
        key = f"array_{len(arrays):05d}"
        arrays[key] = np.array(value, copy=True)
        return {
            "array_ref": key,
            "shape": list(value.shape),
            "dtype": value.dtype.str,
            "sha256": hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest(),
        }
    if isinstance(value, np.datetime64):
        return {"daily_date": str(value)}
    if isinstance(value, np.generic):
        return _pack(value.item(), arrays, journal_paths)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _pack(getattr(value, field.name), arrays, journal_paths)
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Study JSON keys must be strings")
        return {key: _pack(value[key], arrays, journal_paths) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_pack(item, arrays, journal_paths) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_float": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Unsupported study evidence type: {type(value).__name__}")


# Yield the legacy canonical JSON bytes without buffering the whole document.
def _json_chunks(value):
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    buffer = bytearray()
    # The encoder can still allocate an escaped scalar; only document buffering
    # is bounded here. Packing container trees and arrays is a separate cost.
    for fragment in chain(encoder.iterencode(value), ("\n",)):
        offset = 0
        while offset < len(fragment):
            stop = offset + _BUFFER_BYTES - len(buffer)
            buffer.extend(fragment[offset:stop].encode("ascii"))
            offset = stop
            if len(buffer) == _BUFFER_BYTES:
                yield bytes(buffer)
                buffer.clear()
    if buffer:
        yield bytes(buffer)


# Hash exactly the previous sorted, ASCII-escaped JSON representation and final LF.
def _json_digest(value):
    digest = hashlib.sha256()
    for chunk in _json_chunks(value):
        digest.update(chunk)
    return digest.hexdigest()


# Count and hash the bytes actually read using a bounded file buffer.
def _file_receipt(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_BUFFER_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


# Bind complete metadata, arrays and actual journals without a full encoded buffer.
def _evidence_digest(evidence):
    content = {
        key: value for key, value in evidence.items() if key != "evidence_sha256"
    }
    snapshots = {
        id(snapshot): "sha256:" + _json_digest(snapshot)
        for _, snapshot in _journals(evidence)
    }
    packed = _pack(content, {}, snapshots)
    return _json_digest(packed)


# Write exclusive files and retain their hashes for complete readback verification.
def _write(path, body, root, manifest):
    with path.open("xb") as stream:
        stream.write(body)
    manifest[str(path.relative_to(root))] = {
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


# Write canonical JSON exclusively and register its receipt only after a complete close.
def _write_json(path, value, root, manifest):
    digest = hashlib.sha256()
    size = 0
    with path.open("xb") as stream:
        for chunk in _json_chunks(value):
            written = stream.write(chunk)
            if written != len(chunk):
                raise OSError("Incomplete study JSON write")
            digest.update(chunk)
            size += written
    receipt = {"bytes": size, "sha256": digest.hexdigest()}
    manifest[str(path.relative_to(root))] = receipt
    return receipt


# Archive verified evidence with bounded JSON/file buffers and no destination overwrite.
def archive(evidence, destination):  # noqa: C901 - ordered evidence safety boundaries
    path = check_destination(destination)
    if evidence.get("evidence_sha256") != _evidence_digest(evidence):
        raise ValueError("Study evidence changed after the verified run")
    if evidence["source_hashes"] != _source_hashes():
        raise ValueError("Exercised source changed before evidence archival")
    journals = _journals(evidence)
    proofs = {}
    for name, snapshot in journals:
        proof = verify_snapshot(snapshot)
        if not proof["ok"]:
            raise ValueError(
                f"Cannot archive invalid journal {name}: {proof['errors']}"
            )
        proofs[name] = proof
    path = _new_directory(path)
    (path / "journals").mkdir()
    manifest, journal_paths = {}, {}
    _write(path / "protocol.md", PROTOCOL_PATH.read_bytes(), path, manifest)
    for name in evidence["source_hashes"]:
        if name == evidence["protocol_document"]:
            continue
        destination = path / "code" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        body = (ROOT / name).read_bytes()
        if hashlib.sha256(body).hexdigest() != evidence["source_hashes"][name]:
            raise ValueError(f"Source changed before copying: {name}")
        _write(destination, body, path, manifest)
    for name, snapshot in journals:
        folder = path / "journals" / name
        folder.mkdir()
        for field in ("prices", "events", "manifest"):
            _write_json(folder / f"{field}.json", snapshot[field], path, manifest)
        if verify_archive(folder) != proofs[name]:
            raise ValueError(f"Archived journal {name} does not reproduce its proof")
        _write_json(folder / "verification.json", proofs[name], path, manifest)
        journal_paths[id(snapshot)] = str(folder.relative_to(path))
    del proofs
    arrays = {}
    packed = _pack(evidence, arrays, journal_paths)
    _write_json(path / "evidence.json", packed, path, manifest)
    del packed
    _write_json(path / "summary.json", evidence["summary"], path, manifest)
    _write_json(path / "source-hashes.json", evidence["source_hashes"], path, manifest)
    with (path / "arrays.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    with np.load(path / "arrays.npz", allow_pickle=False) as saved:
        if set(saved.files) != set(arrays) or any(
            not np.array_equal(saved[key], values, equal_nan=True)
            for key, values in arrays.items()
        ):
            raise ValueError("Archived arrays differ from the exercised arrays")
    del arrays
    manifest["arrays.npz"] = _file_receipt(path / "arrays.npz")
    if evidence["source_hashes"] != _source_hashes():
        raise ValueError("Exercised source changed during evidence archival")
    if evidence["evidence_sha256"] != _evidence_digest(evidence):
        raise ValueError("Study evidence changed during archival")
    for name, entry in manifest.items():
        if _file_receipt(path / name) != entry:
            raise ValueError(f"Archive readback mismatch: {name}")
    receipt = {
        "schema": POLICY,
        "evidence_sha256": evidence["evidence_sha256"],
        "files": manifest,
        "file_count": len(manifest),
        "bytes": sum(entry["bytes"] for entry in manifest.values()),
        "journal_count": len(journals),
        "scope": "All other files; excludes this manifest itself",
        "adoption_eligible": False,
    }
    # Its own write receipt stays outside the manifest's declared file set.
    written = _write_json(path / "manifest.json", receipt, path, {})
    if _file_receipt(path / "manifest.json") != written:
        raise ValueError("Archive manifest readback mismatch")
    return path / "manifest.json"
