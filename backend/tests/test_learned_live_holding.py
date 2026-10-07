"""Current installed sizing must bind original input, approval and paper state."""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_daily
from backend.market import alpaca_trading, learned_live_timing
from backend.market import learned_live_holding as runtime
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_forward_holding import example_factory, report


# Publish real synthetic numeric heads once for current inference and funded planning.
@pytest.fixture(scope="module")
def example(tmp_path_factory):
    return example_factory(tmp_path_factory, with_market=True)


# Install original current daily bytes and an explicitly synthetic reviewed release.
def install(root, example, monkeypatch):
    original, model, digest, panel, grades, _, _, now = example
    partition = root / "bars" / ("asof=" + str(panel.dates[-1]))
    partition.mkdir(parents=True)
    for column, name in enumerate(panel.tickers):
        values = {"session_date": pa.array(panel.dates.astype(object), pa.date32())}
        for key in ("open", "high", "low", "close", "volume", "adj_close"):
            values["adjusted_close" if key == "adj_close" else key] = pa.array(
                getattr(panel, key)[:, column]
            )
        table = pa.table(values).replace_schema_metadata(
            {
                b"ticker": name.encode(),
                b"source": b"yahoo",
                b"asof": str(panel.dates[-1]).encode(),
                b"complete_through": str(panel.dates[-1]).encode(),
                b"source_time": (now - timedelta(seconds=10)).isoformat().encode(),
            }
        )
        pq.write_table(table, partition / (name + ".parquet"))
    folder = (root / runtime.CONFIG).parent
    folder.mkdir(parents=True)
    (folder / "models").mkdir()
    for path in model.iterdir():
        (folder / "models" / path.name).write_bytes(path.read_bytes())
    timing_path = root / learned_live_timing.CONFIG
    timing_path.parent.mkdir(parents=True)
    timing_bytes = b'{"policy":"synthetic-timing-adapter","cost_bps":10}'
    timing_path.write_bytes(timing_bytes)
    evidence = b'{"status":"synthetic_release_fixture_not_economic_evidence"}'
    (folder / "evidence.json").write_bytes(evidence)
    approval = {
        "schema": "learned-holding-release/1",
        "policy": runtime.funded.MARKET_TIMED_POLICY,
        "approved_at": now.isoformat(),
        "source_sha256": runtime.source_identity(),
        "evidence_sha256": sha256(evidence).hexdigest(),
        "approved": True,
    }
    release = json.dumps(approval).encode()
    (folder / "release.json").write_bytes(release)
    config = {
        "policy": runtime.funded.MARKET_TIMED_POLICY,
        "risk_directory": "risk",
        "risk_receipt_sha256": "a" * 64,
        "model_directory": "models",
        "model_receipt_sha256": digest,
        "cost_bps": 10,
        "timing_config_sha256": sha256(timing_bytes).hexdigest(),
        "release_receipt_sha256": sha256(release).hexdigest(),
    }
    (root / runtime.CONFIG).write_text(json.dumps(config))

    # Storage has independent real-bank acceptance; this boundary supplies that reader.
    def load_bank(path, **kwargs):
        assert path == folder / "risk"
        assert kwargs == {"receipt_sha256": "a" * 64, "observed_at": now}
        return original, {}

    # Execution publication has its own real numeric tests, not repeated model fitting.
    def timing(root_, config_, reader, now_):
        assert root_ == root
        assert config_ == config
        assert reader is original
        assert now_ == now
        return timing_bytes

    monkeypatch.setattr(runtime.holding_risk_bank, "load_bank", load_bank)
    monkeypatch.setattr(runtime, "_timing", timing)
    shown = report(panel, grades)
    shown.sides = {"AAA": "long", "BBB": "long"}
    shown.scores = grades.astype(float)
    return shown, now


# Installed current inference must produce genuine risk quantities without a fresh fit.
def test_installed_current_heads_and_funded_nightly(example, tmp_path, monkeypatch):
    shown, now = install(tmp_path, example, monkeypatch)

    # A runtime fit would silently turn a frozen live model into another experiment.
    def forbidden(*args, **kwargs):
        pytest.fail("Installed holding attempted training")

    monkeypatch.setattr(runtime.forward.direct, "_fit", forbidden)
    chosen = runtime.prepare(tmp_path, shown, clock=lambda: now)
    assert chosen.version == runtime.funded.MARKET_TIMED_POLICY
    assert (
        chosen.reader.distribution(len(chosen.reader.dates) - 1, ("AAA",)).receipt[
            "status"
        ]
        == "available"
    )
    broker = ReplayBroker(100000, 10)
    broker.observe(
        now,
        {
            name: float(shown.panel.close[-1, i])
            for i, name in enumerate(shown.panel.tickers)
        },
        False,
    )
    calls = []

    # Exercise the actual paper HTTP client against a private, consistently read ledger.
    def transport(method, url, headers, body):
        assert method == "GET"
        assert body is None
        assert url.startswith(alpaca_trading.PAPER_URL + "/")
        calls.append(url)
        suffix = url.removeprefix(alpaca_trading.PAPER_URL)
        value = (
            broker.clock()
            if suffix == "/clock"
            else asdict(broker.account())
            if suffix == "/account"
            else []
        )
        return 200, json.dumps(value).encode()

    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", transport=transport
    )
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: client)
    original_prepare = runtime.prepare

    # Keep actual default selection with only the explicit synthetic wall clock.
    def prepare(root, item):
        return original_prepare(root, item, clock=lambda: now)

    monkeypatch.setattr(runtime, "prepare", prepare)
    entry = market_daily.paper_trade(shown, tmp_path, str(shown.panel.dates[-1]), True)
    state = paper.load_state(tmp_path)
    assert calls[0].endswith("/clock")
    assert entry["policy"] == state.policy_version == chosen.version
    assert entry["selected_targets"]["weights"] == {
        name: entry["joint_funded"]["targets"].get(name, 0.0)
        for name in shown.panel.tickers
        if name != "SPY"
    }
    assert market_daily._record_targets(shown, entry) == entry["selected_targets"]
    assert entry["until_rebalance"] is None
    assert str(shown.panel.dates[-1]) in state.sessions_seen
    assert all(
        row["timing_policy"] == chosen.timing_policy
        for row in state.pending
        if row.get("execution_timing") == "dip_or_close"
    )
    assert entry["learned_holding"]["close_receipt_sha256"]
    # No submission or ledger mutation is permitted by this HTTP fixture.
    assert broker.account().cash == 100000
    assert len(broker.attempt_history) == 0


# Report marks and features cannot be changed after the actual source bytes were read.
@pytest.mark.parametrize("field", ["adj_close", "close", "open", "volume"])
def test_changed_current_report_refused(example, tmp_path, monkeypatch, field):
    shown, now = install(tmp_path, example, monkeypatch)
    shown.panel = deepcopy(shown.panel)
    getattr(shown.panel, field)[-1, 0] *= 1.01
    with pytest.raises(ValueError, match="differs from original daily"):
        runtime.prepare(tmp_path, shown, clock=lambda: now)
    assert not ((tmp_path / runtime.CONFIG).parent / "observations").exists()


# Missing or edited release evidence cannot silently fall back to the old live rule.
@pytest.mark.parametrize("name", ["release.json", "evidence.json"])
def test_edited_approval_refuses_default_before_account(
    example, tmp_path, monkeypatch, name
):
    shown, _ = install(tmp_path, example, monkeypatch)
    path = (tmp_path / runtime.CONFIG).with_name(name)
    path.write_bytes(path.read_bytes() + b"edited")

    # Any account read would happen after an unapproved policy had been selected.
    def forbidden():
        pytest.fail("Unapproved learned release contacted the account")

    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    with pytest.raises(ValueError, match="differs|required"):
        market_daily.paper_trade(shown, tmp_path, str(shown.panel.dates[-1]), True)


# Explicit broker admission rejects a real endpoint and changed installation bytes.
def test_broker_admission_refuses_live_endpoint_and_changed_config(
    example, tmp_path, monkeypatch
):
    shown, now = install(tmp_path, example, monkeypatch)
    chosen = runtime.prepare(tmp_path, shown, clock=lambda: now)
    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", base_url="https://api.alpaca.markets/v2"
    )
    with pytest.raises(ValueError, match="paper endpoint"):
        market_daily._holding_broker(chosen, client, now)
    client.base_url = alpaca_trading.PAPER_URL
    (tmp_path / runtime.CONFIG).write_text("{}")
    with pytest.raises(ValueError, match="configuration"):
        market_daily._holding_broker(chosen, client, now)


# A different named policy or incomplete target map cannot mislabel the dashboard book.
def test_recorded_targets_cannot_fabricate_selection(example):
    shown = report(example[3], example[4])
    entry = {
        "policy": runtime.funded.MARKET_TIMED_POLICY,
        "selected_targets": {
            "policy": runtime.funded.MARKET_TIMED_POLICY,
            "weights": {"AAA": 0.2},
        },
    }
    with pytest.raises(ValueError, match="Exact funded"):
        market_daily._record_targets(shown, entry)
    entry["selected_targets"]["weights"] = {
        name: 0.0 for name in shown.panel.tickers if name != "SPY"
    }
    entry["selected_targets"]["weights"]["AAA"] = 0.2
    entry["policy"] = "another-policy"
    with pytest.raises(ValueError, match="Exact funded"):
        market_daily._record_targets(shown, entry)


# Source and execution changes after inference must refuse the first account boundary.
@pytest.mark.parametrize("changed", ["daily", "timing", "costs"])
def test_concurrent_changes_refuse_account_boundary(
    example, tmp_path, monkeypatch, changed
):
    shown, now = install(tmp_path, example, monkeypatch)
    chosen = runtime.prepare(tmp_path, shown, clock=lambda: now)
    client = alpaca_trading.AlpacaTradingClient("fixture", "fixture")
    if changed == "daily":
        path = next((tmp_path / "bars").rglob("*.parquet"))
        path.write_bytes(path.read_bytes() + b"changed")
    elif changed == "timing":
        (tmp_path / learned_live_timing.CONFIG).write_text("{}")
    else:
        chosen.cost_bps = 25
    with pytest.raises(ValueError, match="Concurrent|timing changed|costs differ"):
        market_daily._holding_broker(chosen, client, now)


# A frozen close cannot survive into its following open even with intact artifacts.
def test_expired_close_refuses_before_account(example, tmp_path, monkeypatch):
    shown, now = install(tmp_path, example, monkeypatch)
    chosen = runtime.prepare(tmp_path, shown, clock=lambda: now)
    deadline = chosen.reader.current.receipt["identity"]["expires_at"]

    # A read-only current paper clock defines the expiry check without placing orders.
    def transport(method, url, headers, body):
        assert method == "GET"
        assert url.endswith("/clock")
        return 200, json.dumps({"timestamp": deadline}).encode()

    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", transport=transport
    )
    with pytest.raises(ValueError, match="Completed close"):
        market_daily._holding_broker(chosen, client, now)


# A failed selected nightly policy must not publish an equal-weight fallback record.
def test_default_job_does_not_publish_false_incumbent_fallback(tmp_path, monkeypatch):
    from backend.market.store import MarketStore
    from backend.tests.test_market_daily import _report

    report = _report()
    config = tmp_path / runtime.CONFIG
    config.parent.mkdir(parents=True)
    config.write_text("{}")
    monkeypatch.setattr(market_daily, "desk_report", lambda *args: report)
    monkeypatch.setattr(market_daily, "observe_ml_forward", lambda *args: None)
    # Console table formatting is outside the nightly selection and record boundary.
    monkeypatch.setattr(market_daily, "_print_grades", lambda *args: None)
    monkeypatch.setattr(market_daily, "_print_book", lambda *args: None)
    args = SimpleNamespace(
        asof=None,
        history_only=False,
        refresh=False,
        force=False,
        top=5,
        paper_trade=True,
        paper_dry_run=False,
        rebalance_now=False,
    )
    with pytest.raises(RuntimeError, match="incumbent record not substituted"):
        market_daily._run(args, MarketStore(tmp_path))
    assert not (
        tmp_path / "desk" / ("asof=" + str(report.panel.dates[-1])) / "desk.json"
    ).exists()
    assert not (tmp_path / "paper").exists()
