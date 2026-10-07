"""One-shot actual-intent collector journey with exclusive private receipts."""

import json
import stat
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import live_policy, paper
from backend.cli import market_sequential_shadow as collector
from backend.market import alpaca_trading
from backend.tests.test_sequential_execution_shadow import model
from backend.tests.test_sequential_shadow_context import source_case


# Provide actual-shaped immutable desk files, broker responses and two provider pages.
def case(tmp_path, monkeypatch, pending=True):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    record, partition, session, now = source_case(inputs)
    root = tmp_path / "market"
    path = paper.state_path(root)
    path.parent.mkdir(parents=True)
    order = {
        "client_order_id": "original-order-1",
        "symbol": "ONE",
        "side": "buy",
        "qty": 3,
        "execute_on": session,
        "execution_timing": "intraday",
    }
    from backend.agents.trading.desk import intraday_orders

    order["execution_timing"] = intraday_orders.INTRADAY_TIMING
    path.write_text(
        json.dumps(
            {
                "policy_version": live_policy.ACTIVE,
                "pending": [order] if pending else [],
            }
        )
    )
    requests = []

    # Exercise the real broker parser and the collector's restrictive paper transport.
    def broker(method, url, headers, body):
        assert method == "GET"
        assert body is None
        requests.append(url)
        payload = (
            {"equity": "200", "cash": "100", "buying_power": "100"}
            if url.endswith("/account")
            else []
        )
        return 200, json.dumps(payload).encode()

    monkeypatch.setattr(alpaca_trading, "urllib_transport", broker)
    client = alpaca_trading.AlpacaTradingClient(
        "private", "secret", transport=collector.paper_transport
    )
    current = {
        "t": "2026-10-05T13:30:00Z",
        "o": 10,
        "h": 11,
        "l": 9,
        "c": 10.5,
        "v": 100,
    }
    previous = {**current, "t": "2026-10-02T19:45:00Z", "c": 10}
    pages = iter(
        [
            json.dumps({"bars": {"ONE": [current]}}).encode(),
            json.dumps({"bars": {"ONE": [previous, current]}}).encode(),
        ]
    )

    # Consume the declared raw and split requests through the real endpoint decoder.
    def transport(url, headers):
        requests.append(url)
        return 200, next(pages)

    args = SimpleNamespace(
        root=root,
        record=record,
        daily_partition=partition,
        models=tmp_path / "models",
        output=tmp_path / "private",
    )
    return args, client, transport, lambda: now, lambda _: model(-0.001), requests


# Traverse the full capture, raw-anchor comparison and actual-order decision path.
def test_collector_persists_original_bytes_and_actual_intent_without_submission(
    tmp_path, monkeypatch
):
    args, client, transport, clock, loader, requested = case(tmp_path, monkeypatch)
    before = paper.state_path(args.root).read_bytes()
    result = collector.collect(
        args,
        client=client,
        transport=transport,
        headers={},
        clock=clock,
        model_loader=loader,
    )
    assert result["status"] == "observed"
    assert len(requested) == 8
    assert result["decisions"][0]["original_order"]["qty"] == 3
    assert result["decisions"][0]["state"] == "execute"
    assert (
        result["decisions"][0]["conditional_whole_share_capacity_at_observed_price"]
        == 3
    )
    assert result["order_submission"] is False
    assert result["committed_attempts"] is False
    assert result["wealth_evaluated"] is False
    assert result["training_prior_source_matches"] is False
    assert paper.state_path(args.root).read_bytes() == before
    assert (
        json.loads((args.output / "raw-page-000.json").read_bytes())["bars"]["ONE"][0][
            "c"
        ]
        == 10.5
    )
    assert stat.S_IMODE((args.output / "intents.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(args.output.stat().st_mode) == 0o700
    assert json.loads((args.output / "observation.json").read_text()) == result
    assert result["source"]["files"]


# A no-op account observation must not fetch prices, load a model or require context.
def test_no_eligible_intents_stops_after_stable_get_reads(tmp_path, monkeypatch):
    args, client, transport, clock, loader, requested = case(
        tmp_path, monkeypatch, pending=False
    )
    args.record = args.record.with_name("absent.json")
    result = collector.collect(
        args,
        client=client,
        transport=transport,
        headers={},
        clock=clock,
        model_loader=loader,
    )
    assert result["status"] == "no_eligible_intents"
    assert len(requested) == 6
    assert not (args.output / "context.json").exists()


# Preserve a malformed endpoint response without changing the production plan.
def test_failed_capture_keeps_bytes_and_has_no_decisions(tmp_path, monkeypatch):
    args, client, _, clock, loader, _ = case(tmp_path, monkeypatch)
    raw = b'{"bars":{"ONE":[{"t":"bad"}]}}'
    result = collector.collect(
        args,
        client=client,
        transport=lambda *_: (200, raw),
        headers={},
        clock=clock,
        model_loader=loader,
    )
    assert result["status"] == "source_capture_failed"
    assert (args.output / "failed-page-000.json").read_bytes() == raw
    assert "decisions" not in result


# Refuse to score a plan that becomes sent or changes during the provider read.
def test_concurrent_intent_change_is_not_recommended(tmp_path, monkeypatch):
    args, client, transport, clock, loader, _ = case(tmp_path, monkeypatch)

    # Mutate only the fixture plan after its snapshot, as an independent executor could.
    def mutate(url, headers):
        result = transport(url, headers)
        path = paper.state_path(args.root)
        data = json.loads(path.read_text())
        data["pending"][0]["sent"] = True
        path.write_text(json.dumps(data))
        return result

    result = collector.collect(
        args,
        client=client,
        transport=mutate,
        headers={},
        clock=clock,
        model_loader=loader,
    )
    assert result["status"] == "input_validation_failed"
    assert "intents changed" in result["error"]
    assert "decisions" not in result


# Model-computation latency cannot backdate a decision to an earlier bar receipt.
def test_model_completion_after_next_bar_retains_sources_without_decision(
    tmp_path, monkeypatch
):
    args, client, transport, clock, loader, _ = case(tmp_path, monkeypatch)
    now = [clock()]

    # Advance the actual computation clock after loading the frozen coefficients.
    def delayed_model(path):
        value = loader(path)
        now[0] = now[0].replace(hour=10, minute=0)
        return value

    result = collector.collect(
        args,
        client=client,
        transport=transport,
        headers={},
        clock=lambda: now[0],
        model_loader=delayed_model,
    )
    assert result["status"] == "model_completion_boundary_crossed"
    assert result["decisions"] == []
    assert result["decision_generated_at"].startswith("2026-10-05T10:00")
    assert (args.output / "raw-page-000.json").exists()
    assert (args.output / "split-page-000.json").exists()


# Never rewrite an earlier private observation or put artifacts under production inputs.
def test_output_exclusivity_and_source_separation(tmp_path, monkeypatch):
    args, client, transport, clock, loader, _ = case(
        tmp_path, monkeypatch, pending=False
    )
    collector.collect(
        args,
        client=client,
        transport=transport,
        headers={},
        clock=clock,
        model_loader=loader,
    )
    with pytest.raises(FileExistsError):
        collector.collect(args, client=client, clock=clock)
    args.output = args.root / "research"
    with pytest.raises(ValueError, match="outside all source"):
        collector.collect(args, client=client, clock=clock)


# A passed-in broker endpoint never grants permission to touch a real account.
@pytest.mark.parametrize(
    "url", ["https://api.alpaca.markets/v2", "http://paper-api.alpaca.markets/v2"]
)
def test_real_account_or_unsecured_endpoint_is_rejected(tmp_path, monkeypatch, url):
    args, client, _, clock, _, requested = case(tmp_path, monkeypatch, pending=False)
    client.base_url = url
    with pytest.raises(ValueError, match="Paper endpoint"):
        collector.collect(args, client=client, clock=clock)
    assert not requested
