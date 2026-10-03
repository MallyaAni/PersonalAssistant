"""Actual funded first-available control and authenticated original evidence reuse."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_sequential_first_available as cli
from backend.market.sip_cube import SessionCube


# Supply a held-account-compatible book without any model or opening features.
def _case(stocks=("ONE", "SPY", "QQQ"), days=2):
    dates = np.busday_offset("2026-08-03", np.arange(days)).astype("datetime64[D]")
    prices = np.full((days, len(stocks)), 10.0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=stocks,
        adj_close=prices,
        open=prices.copy(),
        close=prices.copy(),
    )
    shape = (days, 25, len(stocks))
    data = {
        "dates": dates,
        "current_close": np.full(shape, 10.0),
        "next_open": np.full(shape, 10.0),
        "provenance": {"fixture": "synthetic"},
    }
    grades = np.full(prices.shape, 3)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, -2:] = False
    return panel, grades, eligible, data


# Choose the first known quote without model context or future prices.
def test_first_known_quote_ignores_absent_forecasts_and_unknown_future():
    args = _case()
    args[3]["current_close"][1, :4, 0] = np.nan
    args[3]["next_open"][1, 4, 0] = 12
    before = cli.account(*args, first=1, cost_bps=10, offset=0)
    args[3]["next_open"][1] *= 1.5
    after = cli.account(*args, first=1, cost_bps=10, offset=0)
    assert before["intent_trace"][0]["attempt_clock"] == 4
    assert after["intent_trace"][0]["attempt_clock"] == 4
    assert before["nav"][-1] != after["nav"][-1]


# Lock a missing selected execution instead of searching later for a favorable fill.
def test_missing_first_execution_never_retries():
    args = _case()
    args[3]["next_open"][1, 0, 0] = np.nan
    args[3]["next_open"][1, 1:, 0] = 8
    result = cli.account(*args, first=1, cost_bps=0, offset=0)
    trace = result["intent_trace"][0]
    assert trace["attempt_clock"] == 0
    assert trace["realized_price"] is None
    assert trace["filled_delta"] == 0
    assert result["counts"]["missing_execution"] == 1
    assert result["counts"]["fills"] == 0


# Retain a funded partial first attempt without spending again at a later lower price.
def test_partial_first_attempt_is_not_retried():
    args = _case()
    args[3]["next_open"][1, 0, 0] = 100
    args[3]["next_open"][1, 1:, 0] = 8
    result = cli.account(*args, first=1, cost_bps=0, offset=0)
    trace = result["intent_trace"][0]
    assert trace["attempt_clock"] == 0
    assert trace["outcome"] == "partial"
    assert trace["filled_delta"] == pytest.approx(0.01)
    assert trace["desired_shares"] == pytest.approx(0.025)
    assert result["counts"]["fills"] == 1
    assert result["counts"]["expired_partial"] == 1


# Enforce morning cash when covered sales release cash at the same clock.
def test_zero_morning_cash_cannot_recycle_same_observation_sales():
    args = _case(stocks=("OLD0", "OLD1", "OLD2", "OLD3", "NEW", "SPY", "QQQ"), days=22)
    args[2][:, 4] = False
    args[2][20:, :4] = False
    args[2][20:, 4] = True
    result = cli.account(*args, first=1, cost_bps=0, offset=0)
    final = [
        row for row in result["intent_trace"] if row["date"] == str(args[0].dates[21])
    ]
    sells = [row for row in final if row["side"] == "sell"]
    buys = [row for row in final if row["side"] == "buy"]
    assert len(sells) == 4
    assert all(row["filled_delta"] == pytest.approx(-0.025) for row in sells)
    assert len(buys) == 1
    assert buys[0]["morning_cash"] == pytest.approx(0)
    assert buys[0]["attempt_clock"] == 0
    assert buys[0]["filled_delta"] == 0
    assert buys[0]["outcome"] == "unfilled"
    assert result["cash"][-1] == pytest.approx(1)


# Retain unsupported early closes without supplying replacement regular prices.
def test_early_close_remains_unattempted():
    args = _case()
    args[0].dates[:] = np.array(["2026-11-25", "2026-11-27"], dtype="datetime64[D]")
    result = cli.account(*args, first=1, cost_bps=0, offset=0)
    assert result["counts"]["unsupported_plan_sessions"] == 1
    assert result["counts"]["expired_unfilled"] == 1
    assert result["intent_trace"][0]["attempt_clock"] is None


# Create authenticated saved accounts directly without replaying any original strategy.
def _primary(tmp_path, args, monkeypatch):
    panel, _, _, data = args
    dates = np.array(
        ["2018-01-31", "2018-02-01", "2026-09-29", "2026-09-30"], dtype="datetime64[D]"
    )
    panel.dates[:] = dates
    size = len(dates)
    source = cli.primary_cli.source_identity()
    identity = {
        "source": source,
        "data": data["provenance"],
        "baseline_sha256": cli.primary_cli.BASELINE_SHA256,
        "supported_sessions_sha256": cli.original._array_hash(
            cli.primary_cli.execution_support(panel, 1)
        ),
        "session_open_sha256": cli.original._array_hash(panel.open),
    }
    saved = {
        "curves": {
            "nav": [1] * size,
            "cash": [1] * size,
            "exposure": [0] * size,
            "fees": [0] * size,
            "turnover": [0] * size,
        },
        "counts": {"intents": 0},
        "stocks": {},
        "intent_trace": [],
    }
    benchmarks = {}
    for cost in cli.primary_cli.COSTS:
        value = 1 / (1 + cost / 1e4)
        curves = {
            "nav": [1, value, value, value],
            "cash": [1, 0, 0, 0],
            "exposure": [0, 1, 1, 1],
            "turnover": [0, value, 0, 0],
            "fees": [0, 1 - value, 0, 0],
        }
        benchmarks[str(cost)] = {name: {"curves": curves} for name in ("SPY", "QQQ")}
    report = {
        "identity": identity,
        "dates": dates.astype(str).tolist(),
        "status": "complete_reused_conditional_research",
        "adoption_eligible": False,
        "phases": [
            {"cost_bps": cost, "phase": phase, "candidate": saved, "control": saved}
            for cost in cli.primary_cli.COSTS
            for phase in range(20)
        ],
        "benchmarks": benchmarks,
    }
    path, proof = tmp_path / "primary.json", tmp_path / "primary-proof.json"
    cli.write_json(path, report)
    digest = cli.sha256(path)
    monkeypatch.setattr(cli, "PRIMARY_SHA256", digest)
    cli.write_json(proof, {"report_sha256": digest, "identity": identity})
    cube = SessionCube(
        "ONE",
        dates,
        **{key: np.full((size, 26), 100.0) for key in ("open", "high", "low", "close")},
        volume=np.ones((size, 26)),
        prior_close=np.full(size, 100.0),
        excluded={},
        auction_open=np.full(size, 100.0),
        auction_volume=np.ones(size),
    )
    return path, proof, {name: cube for name in panel.tickers}


# Raise immediately if the ablation attempts any original model, control or ETF replay.
def _forbidden(*args, **kwargs):
    raise AssertionError("Original account or model replay is forbidden")


# Authenticate primary bytes and proof while retaining the original artifact unchanged.
def test_primary_authentication_read_only_and_proof_guard(tmp_path, monkeypatch):
    args = _case(days=4)
    path, proof, _ = _primary(tmp_path, args, monkeypatch)
    original_sha = cli.sha256(path)
    _, comparisons = cli.load_primary(args[0], args[3], path, proof)
    assert len(comparisons) == 60
    assert set(comparisons[(10, 5)]) == {"candidate", "control", "SPY", "QQQ"}
    assert cli.sha256(path) == original_sha
    receipt = json.loads(proof.read_text())
    receipt["report_sha256"] = "wrong"
    cli.write_json(proof, receipt)
    with pytest.raises(ValueError, match="authenticate original"):
        cli.load_primary(args[0], args[3], path, proof)


# Run sixty first-available books and refuse repeating authenticated completion.
def test_all60_new_accounts_reuse_original_curves_without_replay(tmp_path, monkeypatch):
    args = _case(days=4)
    primary, proof, cubes = _primary(tmp_path, args, monkeypatch)
    plan = tmp_path / "ablation-plan.md"
    plan.write_text("One fixed post-result interpretation control, no adoption.\n")
    monkeypatch.setattr(cli, "PROTOCOL_PATH", plan)
    monkeypatch.setattr(cli.primary_cli.replay, "account", _forbidden)
    monkeypatch.setattr(cli.primary_cli.models, "walk_forward", _forbidden)
    monkeypatch.setattr(cli.primary_cli.scoring, "benchmark_account", _forbidden)
    before = cli.sha256(primary)
    output = tmp_path / "first-available"
    report = cli.evaluate(*args[:3], cubes, args[3], output, primary, proof)
    assert len(report["phases"]) == 60
    assert report["adoption_eligible"] is False
    first = report["phases"][0]["first_available"]
    assert first["intent_trace"][0]["attempt_clock"] == 0
    assert set(first["score"]["regime_diagnostics"][0]["mean_excess"]) == {
        "candidate",
        "control",
        "SPY",
        "QQQ",
    }
    assert cli.sha256(primary) == before
    monkeypatch.setattr(cli, "account", _forbidden)
    assert cli.evaluate(*args[:3], cubes, args[3], output, primary, proof) == report
    plan.write_text("Changed after completion.\n")
    with pytest.raises(ValueError, match="source identity changed"):
        cli.evaluate(*args[:3], cubes, args[3], output, primary, proof)


# Ignore unreviewed warmup calendars while checking only the actual execution interval.
def test_unreviewed_warmup_calendar_does_not_block_execution():
    args = _case()
    args[0].dates[0] = np.datetime64("2015-01-02", "D")
    result = cli.account(*args, first=1, cost_bps=0, offset=0)
    assert result["intent_trace"][0]["attempt_clock"] == 0
