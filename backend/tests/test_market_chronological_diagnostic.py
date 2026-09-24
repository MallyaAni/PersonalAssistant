"""Preserved research must remain unchanged while its block diagnostics are read."""

import hashlib
import json
import subprocess
import sys

import exchange_calendars
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.cli import market_chronological_diagnostic as diagnostic
from backend.market import neural_study_metrics as metrics


# Fingerprint fixture bytes independently from the command under test.
def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Save a test-only JSON artifact with deterministic serialization.
def _json(path, value):
    path.write_text(json.dumps(value, allow_nan=False))


# Repin deliberately modified fixtures to exercise semantic checks beyond byte identity.
def _repin(root):
    receipt = json.loads((root / "receipt.json").read_text())
    provenance = receipt["provenance"]
    for name, key in (
        ("manifest.json", "manifest_sha256"),
        ("results.json", "original_result_sha256"),
        ("inputs.npz", "input_sha256"),
    ):
        provenance[key] = _hash(root / name)
    provenance["curves_sha256"] = {
        str(cost): _hash(root / f"curves-{cost}bps.npz") for cost in (10, 25)
    }
    _json(root / "receipt.json", receipt)


# Build complete calendar-aligned accounts and a separately pinned price snapshot.
@pytest.fixture
def study(tmp_path):
    dates = exchange_calendars.get_calendar(
        "XNYS", start="2019-01-02", end="2022-12-30"
    ).sessions.values.astype("datetime64[D]")[-850:]
    account_dates = dates[-429:]
    close = 100 * np.exp(np.arange(len(dates)) * 0.0003)
    source_time = f"{dates[-1]}T23:00:00+00:00"
    source = f"/preserved/bars/asof={dates[-1]}/SPY.parquet"
    table = pa.table(
        {
            "session_date": pa.array(dates.astype(object), type=pa.date32()),
            "adjusted_close": close,
        }
    ).replace_schema_metadata(
        {
            b"ticker": b"SPY",
            b"source": b"yahoo",
            b"source_time": source_time.encode(),
            b"asof": str(dates[-1]).encode(),
        }
    )
    pq.write_table(table, tmp_path / "SPY.parquet")
    spy_hashes = {source: _hash(tmp_path / "SPY.parquet")}
    manifest = {
        "policy": "neural-price-only-live-ranking/1",
        "adoption_eligible": False,
        "source_revision": "a" * 40,
        "report_sha256": "b" * 64,
        "test_start": str(account_dates[0]),
        "test_end": str(account_dates[-1]),
        "source_hashes": spy_hashes,
        "input_audit": {"SPY": {"source": "yahoo", "source_time": source_time}},
    }
    _json(tmp_path / "manifest.json", manifest)
    np.savez(tmp_path / "inputs.npz", dates=dates)
    result = {
        "policy": manifest["policy"],
        "adoption_eligible": False,
        "tables": {},
        "benchmark_hashes": spy_hashes,
        "limitations": ["Examined current-survivor reconstruction"],
    }
    rates = {
        "candidate": 0.0007,
        "incumbent": 0.001,
        "SPY": 0.0003,
        "QQQ": 0.0004,
        "equal_weight": 0.0005,
    }
    for cost in (10, 25):
        curves = {
            name: metrics.Curve(
                account_dates,
                np.exp(np.arange(429) * (rate - cost / 1e7)),
                cost,
            )
            for name, rate in rates.items()
        }
        np.savez(
            tmp_path / f"curves-{cost}bps.npz",
            dates=account_dates,
            **{name: curve.equity for name, curve in curves.items()},
        )
        result["tables"][str(cost)] = metrics.scorecard(curves, cost_bps=cost)
    _json(tmp_path / "results.json", result)
    _json(
        tmp_path / "receipt.json",
        {
            "policy": manifest["policy"],
            "adoption_eligible": False,
            "benchmark_hashes": spy_hashes,
            "provenance": {
                "training_source_revision": manifest["source_revision"],
                "report_sha256": manifest["report_sha256"],
            },
        },
    )
    _repin(tmp_path)
    return tmp_path


# Call the actual artifact loader with its separate fixture provenance receipt.
def _diagnose(root):
    return diagnostic.diagnose(
        root, root / "SPY.parquet", receipt_path=root / "receipt.json"
    )


# Exercise the real command and prove complete block coverage and unchanged inputs.
def test_command_reports_fixed_blocks_and_preserves_every_file(study):
    before = {path.name: _hash(path) for path in study.iterdir()}
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.cli.market_chronological_diagnostic",
            "--artifact-dir",
            str(study),
            "--spy-bars",
            str(study / "SPY.parquet"),
            "--receipt",
            str(study / "receipt.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["parameters"] == diagnostic.FOLD_SHAPE
    coverage = report["coverage"]
    assert coverage["complete_folds"] == 4
    assert coverage["all_intervals_accounted_for"]
    assert [part["return_intervals"] for part in coverage["partitions"].values()] == [
        152,
        252,
        24,
    ]
    for fold in report["folds"]:
        assert fold["evaluation"]["return_intervals"] == 63
        for cost, block in fold["cost_levels"].items():
            actual = block["performance"]["rows"]["incumbent"]["total_return"]
            assert actual == pytest.approx(np.expm1(63 * (0.001 - int(cost) / 1e7)))
            assert block["comparisons"]["incumbent"]["SPY"]["strict_win"]
            assert not block["comparisons"]["candidate"]["incumbent"]["strict_win"]
    assert report["independent_validation"] is False
    assert report["adoption_eligible"] is False
    assert report["refit_performed"] is False
    assert (
        report["provenance"]["historical_point_in_time_availability_verified"] is False
    )
    assert before == {path.name: _hash(path) for path in study.iterdir()}


# Every consumed artifact must match a previously recorded fingerprint.
@pytest.mark.parametrize(
    "name",
    [
        "manifest.json",
        "inputs.npz",
        "results.json",
        "curves-10bps.npz",
        "curves-25bps.npz",
        "SPY.parquet",
    ],
)
def test_changed_artifact_is_rejected_before_scoring(study, name):
    path = study / name
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        _diagnose(study)


# A newly pinned curve still must reproduce the preserved full-sample results.
def test_curve_summary_mismatch_cannot_be_hidden_by_repinning(study):
    path = study / "curves-10bps.npz"
    with np.load(path, allow_pickle=False) as archive:
        values = {name: archive[name].copy() for name in archive.files}
    values["incumbent"][-1] *= 1.1
    np.savez(path, **values)
    _repin(study)
    with pytest.raises(ValueError, match="saved total_return mismatch"):
        _diagnose(study)


# Missing or extra sessions cannot silently redefine either warm-up or regimes.
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_changed_input_session_grid_fails_calendar_validation(study, change):
    path = study / "inputs.npz"
    with np.load(path, allow_pickle=False) as archive:
        dates = archive["dates"].copy()
    changed = (
        np.delete(dates, 30)
        if change == "missing"
        else np.sort(np.append(dates, np.datetime64("2021-01-02")))
    )
    np.savez(path, dates=changed)
    _repin(study)
    with pytest.raises(ValueError, match="Incomplete XNYS session grid"):
        _diagnose(study)


# A curve with another valid calendar window must still match the original manifest.
def test_shortened_cost_window_is_rejected(study):
    path = study / "curves-25bps.npz"
    with np.load(path, allow_pickle=False) as archive:
        values = {name: archive[name][1:].copy() for name in archive.files}
    np.savez(path, **values)
    _repin(study)
    with pytest.raises(ValueError, match="saved first_session differs"):
        _diagnose(study)


# Independent provenance records must identify the same source price partition.
def test_disagreeing_source_hashes_fail_closed(study):
    path = study / "results.json"
    result = json.loads(path.read_text())
    source = next(iter(result["benchmark_hashes"]))
    result["benchmark_hashes"][source] = "c" * 64
    _json(path, result)
    _repin(study)
    with pytest.raises(ValueError, match="SPY source hashes disagree"):
        _diagnose(study)


# A price file's source timestamp must agree with the pinned manifest metadata.
def test_source_vintage_disagreement_is_rejected(study):
    path = study / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["input_audit"]["SPY"]["source_time"] = "2020-01-01T00:00:00+00:00"
    _json(path, manifest)
    _repin(study)
    with pytest.raises(ValueError, match="identity or vintage differs"):
        _diagnose(study)


# Parse errors must exit unsuccessfully without emitting a misleading JSON success.
def test_cli_error_is_fail_closed(study, capsys):
    (study / "manifest.json").write_bytes(b"broken")
    with pytest.raises(SystemExit) as failure:
        diagnostic.main(
            [
                "--artifact-dir",
                str(study),
                "--spy-bars",
                str(study / "SPY.parquet"),
                "--receipt",
                str(study / "receipt.json"),
            ]
        )
    captured = capsys.readouterr()
    assert failure.value.code == 2
    assert not captured.out
    assert "SHA256 mismatch" in captured.err
