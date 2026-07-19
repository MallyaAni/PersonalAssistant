import json

import pytest

from backend.cli.soak_memory import SoakStats, _validate_args, build_parser, main


# Verify the monitoring report includes operations, latency, and failure state.
def test_soak_stats_report_success_and_failure() -> None:
    stats = SoakStats()
    stats.success("working_read", 10.0)
    stats.success("chat", 30.0)
    passed = stats.report(1.0, 2)
    assert passed["status"] == "passed"
    assert passed["operations_total"] == 2
    assert passed["latency_ms"] == {
        "median": 20.0,
        "p95": 30.0,
        "maximum": 30.0,
    }

    stats.failure("chat", "provider unavailable")
    failed = stats.report(1.0, 2)
    assert failed["status"] == "failed"
    assert failed["failures_total"] == 1


# Verify unsafe soak sizes are rejected before requests begin.
@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--concurrency", "0"], "concurrency"),
        (["--chat-every", "0"], "chat-every"),
        (["--duration-seconds", "0"], "duration-seconds"),
        (["--timeout-seconds", "0"], "timeout-seconds"),
    ],
)
def test_soak_argument_bounds(arguments: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _validate_args(build_parser().parse_args(arguments))


# Verify invalid command input returns structured monitoring output.
def test_soak_main_reports_invalid_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--concurrency", "0"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "invalid",
        "message": "concurrency must be between 1 and 100",
    }
