"""Describe chronological stability of an already completed, hash-pinned study.

This command only reads artifacts. It never fits a model, replays trades, fetches
prices, or changes an account. The block shape was fixed before reading block
results: 126 reference sessions, 63 evaluation intervals, the original study's
21-session label horizon, and five additional embargo sessions. The reference
and purge ranges are descriptive geometry, not evidence that folds were fitted.
"""

import argparse
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath

import numpy as np

from backend.market import harness
from backend.market import neural_study_metrics as metrics

DEFAULT_RECEIPT = (
    Path(__file__).resolve().parents[1] / "market/data/neural_price_study_20260924.json"
)
FOLD_SHAPE = {"train_size": 126, "test_size": 63, "horizon": 21, "embargo": 5}


# Parse a JSON object without interpreting any artifact as executable code.
def _object(payload: bytes, label: str) -> dict:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise TypeError(f"{label}: a JSON object is required")
    return value


# Bind each loaded byte sequence to the separately supplied provenance receipt.
def _checked_bytes(path: Path, expected: str) -> bytes:
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ValueError(f"{path.name}: a complete SHA256 is required")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"{path.name}: SHA256 mismatch")
    return payload


# Reject missing or extra exchange sessions without coercing timestamp precision.
def _calendar(dates: np.ndarray) -> str:
    import exchange_calendars

    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or len(dates) < 2
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("Sorted unique daily session dates are required")
    expected = exchange_calendars.get_calendar(
        "XNYS", start=str(dates[0]), end=str(dates[-1])
    ).sessions.values.astype("datetime64[D]")
    if not np.array_equal(dates, expected):
        raise ValueError("Incomplete XNYS session grid")
    return exchange_calendars.__version__


# Locate one explicit SPY bar source without using a manifest path for file access.
def _spy_source(hashes: dict) -> tuple[str, str]:
    matches = [
        (name, digest)
        for name, digest in hashes.items()
        if PurePosixPath(name).name == "SPY.parquet"
        and len(PurePosixPath(name).parts) >= 3
        and PurePosixPath(name).parts[-3] == "bars"
    ]
    if len(matches) != 1:
        raise ValueError("Exactly one preserved SPY bars source is required")
    return matches[0]


# Recover unmodified adjusted closes from the hash-pinned original price snapshot.
def _regime_evidence(payload: bytes, manifest: dict, input_dates: np.ndarray):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.ParquetFile(io.BytesIO(payload)).read(
        columns=["session_date", "adjusted_close"]
    )
    if not pa.types.is_date(table.schema.field("session_date").type):
        raise ValueError("SPY source dates must be daily dates, not timestamps")
    metadata = {
        key.decode(): value.decode()
        for key, value in (table.schema.metadata or {}).items()
    }
    audit = manifest["input_audit"]["SPY"]
    if (
        metadata.get("ticker") != "SPY"
        or metadata.get("source") != audit["source"]
        or metadata.get("source_time") != audit["source_time"]
        or metadata.get("asof") != manifest["test_end"]
    ):
        raise ValueError("SPY source identity or vintage differs from the manifest")
    dates = np.asarray(table["session_date"].to_pylist(), dtype="datetime64[D]")
    closes = np.asarray(table["adjusted_close"].to_numpy(), dtype=float)
    _calendar(dates)
    positions = np.searchsorted(dates, input_dates)
    if np.any(positions >= len(dates)) or not np.array_equal(
        dates[positions], input_dates
    ):
        raise ValueError("SPY source must cover every preserved input session")
    return metrics.RegimeEvidence(input_dates, closes[positions]), metadata


# Validate identity and summary arithmetic before reporting any newly sliced results.
def _check_report(report: dict, manifest: dict, receipt: dict, full_sample: dict):
    provenance = receipt["provenance"]
    if not (
        manifest["policy"] == report["policy"] == receipt["policy"]
        and manifest["adoption_eligible"] is False
        and report["adoption_eligible"] is False
        and receipt["adoption_eligible"] is False
        and manifest["source_revision"] == provenance["training_source_revision"]
        and manifest["report_sha256"] == provenance["report_sha256"]
    ):
        raise ValueError("Study identity or source revision differs from the receipt")
    if set(report["tables"]) != {"10", "25"}:
        raise ValueError("Saved results must contain exactly the two declared costs")
    for cost, actual in full_sample.items():
        saved = report["tables"][cost]
        for field in ("first_session", "last_session", "cost_bps"):
            if saved[field] != actual[field]:
                raise ValueError(f"{cost} bp: saved {field} differs from curves")
        if (
            actual["first_session"] != manifest["test_start"]
            or actual["last_session"] != manifest["test_end"]
        ):
            raise ValueError("Account window differs from the preserved manifest")
        if set(saved["rows"]) != set(actual["rows"]):
            raise ValueError("Saved results and curves contain different accounts")
        for account, row in actual["rows"].items():
            prior = saved["rows"][account]
            for field in (
                "return_intervals",
                "total_return",
                "cagr",
                "max_drawdown",
                "sharpe_zero_risk_free",
            ):
                left, right = row[field], prior[field]
                matches = (
                    left is right
                    if left is None or right is None
                    else math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12)
                )
                if not matches:
                    raise ValueError(f"{cost} bp {account}: saved {field} mismatch")


# Read one completed study and retain its original provenance limitations in every run.
def diagnose(artifact_dir: Path, spy_bars: Path, *, receipt_path=DEFAULT_RECEIPT):
    receipt_payload = Path(receipt_path).read_bytes()
    receipt = _object(receipt_payload, "Provenance receipt")
    provenance = receipt["provenance"]
    hashes = {
        "manifest.json": provenance["manifest_sha256"],
        "results.json": provenance["original_result_sha256"],
        "inputs.npz": provenance["input_sha256"],
        **{
            f"curves-{cost}bps.npz": provenance["curves_sha256"][str(cost)]
            for cost in (10, 25)
        },
    }
    payloads = {
        name: _checked_bytes(Path(artifact_dir) / name, digest)
        for name, digest in hashes.items()
    }
    manifest = _object(payloads["manifest.json"], "Manifest")
    saved = _object(payloads["results.json"], "Saved results")
    spy_source = _spy_source(manifest["source_hashes"])
    if not (
        spy_source == _spy_source(saved["benchmark_hashes"])
        and spy_source == _spy_source(receipt["benchmark_hashes"])
    ):
        raise ValueError("SPY source hashes disagree across preserved records")
    spy_payload = _checked_bytes(Path(spy_bars), spy_source[1])
    with np.load(io.BytesIO(payloads["inputs.npz"]), allow_pickle=False) as inputs:
        input_dates = inputs["dates"].copy()
    calendar_version = _calendar(input_dates)
    evidence, metadata = _regime_evidence(spy_payload, manifest, input_dates)
    curves = {}
    for cost in (10, 25):
        with np.load(
            io.BytesIO(payloads[f"curves-{cost}bps.npz"]), allow_pickle=False
        ) as archive:
            if set(archive.files) != metrics.REQUIRED_ACCOUNTS | {"dates"}:
                raise ValueError("Saved curves must contain the exact comparison set")
            dates = archive["dates"].copy()
            _calendar(dates)
            curves[cost] = {
                name: metrics.Curve(dates, archive[name].copy(), cost)
                for name in sorted(metrics.REQUIRED_ACCOUNTS)
            }
    full_sample = {
        str(cost): metrics.scorecard(table, cost_bps=cost)
        for cost, table in curves.items()
    }
    _check_report(saved, manifest, receipt, full_sample)
    result = metrics.chronological_fold_scorecard(
        curves, evidence=evidence, **FOLD_SHAPE
    )
    result["provenance"] = {
        "artifact_sha256": hashes,
        "receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "original_source_revision": manifest["source_revision"],
        "report_sha256": manifest["report_sha256"],
        "spy_source": spy_source[0],
        "spy_source_sha256": spy_source[1],
        "spy_snapshot_metadata": metadata,
        "exchange_calendar_version": calendar_version,
        "historical_point_in_time_availability_verified": False,
        "fold_shape_selected_before_block_results": True,
        "original_artifacts_modified": False,
        "diagnostic_source_sha256": {
            "backend/cli/market_chronological_diagnostic.py": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "backend/market/neural_study_metrics.py": hashlib.sha256(
                Path(metrics.__file__).read_bytes()
            ).hexdigest(),
            "backend/market/harness.py": hashlib.sha256(
                Path(harness.__file__).read_bytes()
            ).hexdigest(),
        },
    }
    result["limitations"] = [
        *saved["limitations"],
        (
            "A preserved later price snapshot does not prove historical availability; "
            "regime indexing is causal within that snapshot only"
        ),
        "Hash checks prove artifact identity, not achievable returns or untouched data",
        (
            "Original raw fill and cash journals were not retained; fees, exposure and "
            "turnover cannot be independently recovered from the saved NAV curves"
        ),
    ]
    return result


# Print a diagnostic without adding any filesystem, broker, model, or network write path.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--spy-bars", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    try:
        result = diagnose(args.artifact_dir, args.spy_bars, receipt_path=args.receipt)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
