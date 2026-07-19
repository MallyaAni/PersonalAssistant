import json

import pytest

from backend.cli.run_memory_maintenance import main


# Verify invalid scheduler intervals fail before running maintenance.
def test_maintenance_cli_rejects_subsecond_interval(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--all-users", "--interval-seconds", "0"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "invalid",
        "message": "interval-seconds must be at least 1",
    }
