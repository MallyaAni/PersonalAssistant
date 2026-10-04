"""Fixed study declarations, honest missing metrics and actual archived journeys."""

import gzip
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_actual_policy_timing as study
from backend.market import calendar
from backend.tests.test_live_policy_replay import fixture


# Supply reviewed exchange sessions spanning the entire fixed comparison range.
def dates():
    _, sessions = calendar.reviewed_sessions()
    days = np.arange(np.datetime64("2018-01-31"), np.datetime64("2026-10-01"))
    return days[np.is_busday(days, busdaycal=sessions)]


# Keep exactly180 policy books and120 matched controls across all twenty starts.
def test_fixed_grid_retains_every_arm_cost_start():
    grid = study.account_grid(dates())
    assert len(grid) == len({row["id"] for row in grid}) == 300
    assert sum(row["arm"] in study.ARMS for row in grid) == 180
    assert sum(row["arm"] in study.BENCHMARKS for row in grid) == 120
    assert {row["cost_bps"] for row in grid} == {0, 10, 25}
    assert {row["start"] for row in grid} == set(range(20))
    assert {row["first_session"] for row in grid} == set(map(str, dates()[1:21]))
    assert all(str(dates()[row["last"]]) == "2026-09-30" for row in grid)


# Refuse changed endpoints, duplicate dates and truncated start coverage.
@pytest.mark.parametrize("change", ["duplicate", "start", "end", "dtype"])
def test_changed_grid_is_rejected(change):
    values = dates()
    if change == "duplicate":
        values[2] = values[1]
    elif change == "start":
        values = values[values != np.datetime64("2018-02-01")]
    elif change == "end":
        values = values[:-1]
    else:
        values = values.astype("datetime64[ns]")
    with pytest.raises(ValueError, match="Ordered|Fixed"):
        study.account_grid(values)


# Supply explicit wealth and trade records for independent hand-calculated metrics.
def account(nav=(100.0, 110.0, 105.0)):
    return {
        "sessions": [
            {
                "session": day,
                "initial": i == 0,
                "nav": value,
                "price_nav": value,
                "cash": 10.0 if value else 0.0,
            }
            for i, (day, value) in enumerate(
                zip(("2020-12-31", "2021-01-04", "2021-01-05"), nav, strict=True)
            )
        ],
        "fills": [
            {
                "at": "2021-01-04T14:30:00+00:00",
                "client_order_id": "original-order",
                "requested_qty": 1,
                "filled_qty": 1,
                "price": 20.0,
                "fee": 0.02,
            }
        ],
    }


# Rebase a fixed era at the prior close and preserve positive-loss drawdown signs.
def test_metrics_retain_gain_cost_turnover_and_window_baseline():
    score = study.account_score(account(), "2021-01-01", "2026-10-01")
    assert score["status"] == "complete"
    assert score["sessions"] == 2
    assert score["total_gain"] == pytest.approx(0.05)
    assert score["drawdown_positive_loss"] == pytest.approx(1 - 105 / 110)
    assert score["fees"] == 0.02
    assert score["realized_notional"] == 20
    assert score["realized_turnover"] == 0.2


# Retain unfinished orders at an era boundary even when they fill in a later era.
def test_future_fill_does_not_erase_an_earlier_unexecuted_order():
    result = account()
    result["intents"] = [
        {
            "client_order_id": "later-order",
            "symbol": "AAOI",
            "session": "2021-01-04",
            "execute_on": "2021-01-05",
            "qty": 5,
        }
    ]
    result["fills"].append(
        {
            "client_order_id": "later-order",
            "at": "2021-01-06T14:30:00+00:00",
            "requested_qty": 5,
            "filled_qty": 5,
            "price": 20.0,
            "fee": 0.1,
        }
    )
    score = study.account_score(result, "2021-01-01", "2021-01-06")
    assert score["unexecuted_original_intents"] == 1
    assert score["remaining_original_qty_by_symbol"] == {"AAOI": 5}
    assert score["fees"] == 0.02


# Keep endpoint gain but withhold risk metrics when an interior mark is missing.
def test_missing_nav_does_not_get_dropped_or_forward_filled():
    score = study.account_score(
        account((100.0, None, 105.0)), "2021-01-01", "2026-10-01"
    )
    assert score["status"] == "missing_wealth_observations"
    assert score["missing_nav_marks"] == 1
    assert score["total_gain"] == pytest.approx(0.05)
    assert score["cagr"] is None
    assert score["sharpe"] is None
    assert score["drawdown_positive_loss"] is None
    assert score["mean_end_session_exposure"] is None


# Distinguish real bankruptcy from missing data rather than hiding a total loss.
def test_zero_wealth_is_a_loss_not_an_unavailable_endpoint():
    score = study.account_score(
        account((100.0, 110.0, 0.0)), "2021-01-01", "2026-10-01"
    )
    assert score["status"] == "zero_wealth"
    assert score["total_gain"] == -1.0
    assert score["drawdown_positive_loss"] == 1.0
    assert score["cagr"] == -1.0
    assert score["sharpe"] is None


# Reject negative wealth in an unlevered venue rather than publish a plausible score.
def test_negative_wealth_is_a_correctness_failure():
    with pytest.raises(ValueError, match="Negative"):
        study.account_score(account((100, 110, -1)), "2021-01-01", "2026-10-01")


# Publish immutable compressed bytes with deterministic headers and explicit nulls.
def test_account_archive_is_hashed_lossless_and_never_overwritten(tmp_path):
    result = {"nav": [1.0, None], "missing": np.nan, "adoption_eligible": False}
    path = tmp_path / "account.json.gz"
    digest = study.archive_account(path, result)
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(gzip.decompress(path.read_bytes())) == {
        "nav": [1.0, None],
        "missing": None,
        "adoption_eligible": False,
    }
    with pytest.raises(FileExistsError):
        study.archive_account(path, {"nav": [999999]})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


# Detect both changed original bytes and the appearance of an originally absent file.
def test_original_input_checks_retain_absence(tmp_path):
    present, absent = tmp_path / "original", tmp_path / "absent"
    present.write_bytes(b"original")
    files = {
        str(present): hashlib.sha256(present.read_bytes()).hexdigest(),
        str(absent): None,
    }
    study.check_original_files(files)
    absent.write_bytes(b"new data")
    with pytest.raises(ValueError, match="absent input appeared"):
        study.check_original_files(files)
    absent.unlink()
    present.write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence changed"):
        study.check_original_files(files)


# Keep all start comparisons and refuse benchmark excess from an unfilled entry proxy.
def test_summary_retains_missingness_and_all_twenty_starts():
    rows = []
    for spec in study.account_grid(dates()):
        gain = {"rule": 0.1, "boosting": 0.12, "ridge": 0.09, "SPY": 0.11, "QQQ": 0.13}[
            spec["arm"]
        ]
        score = {
            "status": "complete",
            "total_gain": gain,
            "benchmark_reference_available": spec["arm"] in study.BENCHMARKS,
        }
        if spec["start"] == 3 and spec["arm"] == "boosting":
            score["status"] = "missing_wealth_observations"
        if spec["start"] == 7 and spec["arm"] == "QQQ":
            score["benchmark_reference_available"] = False
        rows.append(
            {**spec, "scores": {name: dict(score) for name, _, _ in study.WINDOWS}}
        )
    summary = study.comparison_summary(rows)
    assert len(summary) == 2 * 3 * 4
    boosting = summary[0]
    assert boosting["endpoint_pairs"] == 20
    assert boosting["complete_risk_pairs"] == 19
    assert boosting["count_better"] == 20
    assert boosting["median_gain_difference"] == pytest.approx(0.02)
    assert boosting["pairs"][7]["benchmark_excess"]["QQQ"] is None
    assert boosting["pairs"][7]["benchmark_excess"]["SPY"] == pytest.approx(0.01)


# Run real nightly/sender and ETF paths through the archive/progress lifecycle.
def test_driver_archives_actual_accounts_without_real_broker_or_fit(
    tmp_path, monkeypatch
):
    from backend.market import alpaca_trading

    # Fail if an ordinary environment-backed broker is reached by any study arm.
    def forbidden():
        raise AssertionError("Real broker requested")

    # Deliberately supply no forecast so the shared actual deadline must handle it.
    def unavailable(day, clock, stock):
        return None

    panel, raw, cubes = fixture()
    source = {"manifest_sha256": "b" * 64, "git_commit": "synthetic", "files": 1}
    providers = {
        name: SimpleNamespace(provider=unavailable, verification={"test": True})
        for name in ("boosting", "ridge")
    }
    grid = [
        {
            "arm": arm,
            "cost_bps": 10,
            "start": 0,
            "first": 1,
            "last": 2,
            "first_session": "2026-09-02",
            "id": f"{arm}-10-0",
        }
        for arm in (*study.ARMS, *study.BENCHMARKS)
    ]
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    monkeypatch.setattr(study, "source_identity", lambda args: source)
    monkeypatch.setattr(
        study, "load_inputs", lambda args: (panel, raw, cubes, providers, {})
    )
    monkeypatch.setattr(study, "account_grid", lambda values: grid)
    monkeypatch.setattr(
        study, "comparison_summary", lambda rows: {"synthetic_rows": len(rows)}
    )
    output = tmp_path / "study"
    study.evaluate(SimpleNamespace(output=output, preflight=False))
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "complete_pending_independent_verification"
    assert report["adoption_eligible"] is False
    assert len(report["accounts"]) == 5
    decoded = {}
    for row in report["accounts"]:
        path = output / row["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        decoded[row["arm"]] = json.loads(gzip.decompress(path.read_bytes()))
    assert decoded["rule"]["sessions"][-1]["nav"] == 100225.25
    assert decoded["boosting"]["sessions"][-1]["nav"] == 99724.75
    assert decoded["ridge"]["sessions"][-1]["nav"] == 99724.75
    assert decoded["SPY"]["broker"]["holdings"] == {"SPY": 999}
    assert decoded["QQQ"]["broker"]["holdings"] == {"QQQ": 999}
    assert all(row["sessions"][-1]["cash"] >= 0 for row in decoded.values())
    assert json.loads((output / "progress.json").read_text())["completed"] == 5


# Keep an input-only preflight free of accounts, attempts and performance rows.
def test_preflight_does_not_run_a_study_account(tmp_path, monkeypatch):
    panel, raw, cubes = fixture()
    monkeypatch.setattr(study, "source_identity", lambda args: {})
    monkeypatch.setattr(study, "load_inputs", lambda args: (panel, raw, cubes, {}, {}))
    monkeypatch.setattr(
        study, "account_grid", lambda values: [dict(id="declaration_only")]
    )
    output = tmp_path / "preflight"
    study.evaluate(SimpleNamespace(output=output, preflight=True))
    assert json.loads((output / "preflight.json").read_text())["accounts_created"] == 0
    assert not (output / "state").exists()
    assert not (output / "accounts").exists()
    assert not (output / "report.json").exists()
