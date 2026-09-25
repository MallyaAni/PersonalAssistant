"""Local import and research-only command boundaries with persisted readback."""

import json
import subprocess
import sys

import pytest

from backend.cli import market_desk
from backend.market import fundamental_source_store as archive
from backend.market.store import MarketStore
from backend.tests.test_fundamental_source_store import ASOF, CAPTURED, _source


# Invoke the actual importer process against an already acquired synthetic response.
def _import(tmp_path, source, filename):
    path = tmp_path / filename
    path.write_bytes(source.body)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.cli.market_fundamental_sources",
            "--data-dir",
            str(tmp_path / "store"),
            "--source",
            str(path),
            "--sha256",
            source.sha256,
            "--cik",
            "1",
            "--ticker",
            "TEST",
            "--asof",
            ASOF.isoformat(),
            "--captured-at",
            CAPTURED.isoformat(),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


# The receipt names the actual preserved source, including a conflicting rerun.
def test_import_process_reads_back_actual_archive_identity(tmp_path):
    original, replacement = _source(), _source(999)
    first = json.loads(_import(tmp_path, original, "original.json").stdout)
    store = MarketStore(tmp_path / "store")
    saved = store._path(archive.KIND, ASOF, "TEST").read_bytes()
    assert first["status"] == "written"
    assert first["stored_source_sha256"] == original.sha256
    assert archive.load(store, "TEST", ASOF).source.body == original.body
    second = json.loads(_import(tmp_path, replacement, "replacement.json").stdout)
    assert second["status"] == "kept_existing"
    assert second["stored_source_sha256"] == original.sha256
    assert second["requested_source_sha256"] == replacement.sha256
    assert second["historical_authenticity_verified"] is False
    assert store._path(archive.KIND, ASOF, "TEST").read_bytes() == saved


# Current-source qualification cannot silently enable a historical performance claim.
@pytest.mark.parametrize(
    "option", [["--backtest", "TEST"], ["--book-backtest"], ["--calibrate"]]
)
def test_qualified_performance_commands_refused_before_desk_runs(
    monkeypatch, capsys, option
):
    # Nothing should read data or compute grades after a refused command.
    def refuse(*args, **kwargs):
        raise AssertionError("desk must not run for unsupported historical claims")

    monkeypatch.setattr(market_desk.trading_desk, "run", refuse)
    monkeypatch.setattr(
        sys, "argv", ["market_desk", "--fundamentals", "qualified", *option]
    )
    with pytest.raises(SystemExit) as exc:
        market_desk.main()
    assert exc.value.code == 2
    assert "no authenticated historical archive" in capsys.readouterr().err


# Saving a new-profile research record is an explicit mode-specific operation.
def test_research_record_flag_requires_qualified_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["market_desk", "--research-record-root", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as exc:
        market_desk.main()
    assert exc.value.code == 2
    assert "requires the explicit qualified research mode" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
