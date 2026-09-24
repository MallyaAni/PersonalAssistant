"""Import reviewed public evidence without creating historical prices or trades.

The input manifest and original source bodies are local files. This command
verifies them, copies them into a new research archive and persists a readiness
report on actual XNYS sessions. It does not fetch data, infer missing facts,
train a model, replay a strategy, or write to a live or paper account.
"""

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from backend.market import historical_cohort

DEFAULT_FEATURES = ("open", "adjusted_close", "volume", "grade")


# Keep requested calendar boundaries exact instead of silently accepting timestamps.
def _day(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("Calendar bounds must be YYYY-MM-DD dates")
    return result


# Use the exchange's actual closes, including early closes, for availability decisions.
def _calendar(start: str, end: str):
    import exchange_calendars

    first, last = _day(start), _day(end)
    if first > last:
        raise ValueError("Calendar start must not follow its end")
    calendar = exchange_calendars.get_calendar(
        "XNYS", start=first - timedelta(days=7), end=last + timedelta(days=7)
    )
    labels = calendar.sessions_in_range(start, end)
    if labels.empty:
        raise ValueError("Requested calendar contains no XNYS sessions")
    sessions = labels.values.astype("datetime64[D]")
    decisions = [
        calendar.session_close(label).to_pydatetime() + timedelta(minutes=15)
        for label in labels
    ]
    return (
        sessions,
        decisions,
        {
            "exchange": "XNYS",
            "package": "exchange-calendars",
            "version": exchange_calendars.__version__,
            "requested_start": start,
            "requested_end": end,
            "first_session": str(sessions[0]),
            "last_session": str(sessions[-1]),
            "decision_rule": "scheduled session close plus 15 minutes",
            "sessions_sha256": hashlib.sha256(
                "\n".join(np.datetime_as_string(sessions)).encode()
            ).hexdigest(),
        },
    )


# Fingerprint exactly the code and archived bytes exercised by this local import.
def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Persist a new report without replacing any existing research artifact.
def _write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


# Import verified evidence, read the archive back, and retain every named evidence gap.
def import_and_assess(
    manifest_path: Path,
    destination: Path,
    *,
    start: str,
    end: str,
    required_features: tuple[str, ...] = DEFAULT_FEATURES,
) -> dict:
    cohort = historical_cohort.load_cohort(manifest_path)
    sessions, decisions, calendar = _calendar(start, end)
    # Preflight the full request before creating any output directory.
    historical_cohort.readiness(cohort, sessions, decisions, required_features)
    manifest = historical_cohort.archive_cohort(cohort, destination)
    archived = historical_cohort.load_cohort(manifest)
    if archived.source_bytes != cohort.source_bytes:
        raise ValueError("Archived source bytes differ from the validated input")
    report = historical_cohort.readiness(
        archived, sessions, decisions, required_features
    )
    report["calendar"] = calendar
    report["required_features"] = list(required_features)
    report["provenance"] = {
        "created_at": datetime.now(UTC).isoformat(),
        "input_manifest_sha256": hashlib.sha256(cohort.original_manifest).hexdigest(),
        "archived_manifest_sha256": _hash(manifest),
        "archive_readback_verified": True,
        "source_artifact_sha256": {
            "backend/cli/market_historical_cohort.py": _hash(Path(__file__)),
            "backend/market/historical_cohort.py": _hash(
                Path(historical_cohort.__file__)
            ),
        },
    }
    report_path = manifest.parent / "readiness.json"
    _write_json(report_path, report)
    # Read the actual persisted output; a successful write call is not proof of state.
    if json.loads(report_path.read_bytes()) != report:
        raise ValueError("Persisted readiness report differs from the assessed cohort")
    receipt = {
        "schema": "historical-cohort-import/1",
        "archive": str(manifest.parent.resolve()),
        "manifest_sha256": _hash(manifest),
        "readiness_sha256": _hash(report_path),
        "source_count": report["source_count"],
        "security_count": report["security_count"],
        "sessions": report["sessions"],
        "session_security_rows": report["session_security_rows"],
        "feature_complete_rows": report["feature_complete_rows"],
        "gap_counts": report["gap_counts"],
        "source_integrity_verified": report["source_integrity_verified"],
        "archive_readback_verified": True,
        "historical_backtest_ready": False,
        "adoption_eligible": False,
        "independent_validation": False,
        "accounts_changed": False,
        "source_authentication": "reviewed extraction; not independently authenticated",
    }
    _write_json(manifest.parent / "import-receipt.json", receipt)
    return receipt


# Run the offline importer with explicit calendar bounds and a fresh archive target.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument(
        "--required-feature", action="append", dest="features", default=None
    )
    arguments = parser.parse_args(argv)
    try:
        receipt = import_and_assess(
            arguments.manifest,
            arguments.archive,
            start=arguments.start,
            end=arguments.end,
            required_features=tuple(arguments.features or DEFAULT_FEATURES),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Historical cohort import failed: {exc}\n")
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
