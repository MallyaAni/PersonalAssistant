"""Synthetic native final dispatch; no model, provider or settled-paper claim."""

import sys
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Thread

import pytest
import test_historical_conditional_market as generic
from test_historical_conditional_cycle import intent

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import historical_conditional_cycle as connected
from backend.market import historical_conditional_market as market
from backend.market import historical_packet_demand as demand
from backend.market import historical_session_completion as completion
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_store import StorePause

CASES = []


# Reuse exact native source admission rather than replacing its expected identity.
@pytest.fixture
def pins():
    return generic.pins.__wrapped__()


# Refuse every numerical forecast and authentic-live observation path in final tests.
@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    generic.shared_external.__wrapped__(monkeypatch)

    # Final dispatch must not call even the numeric identity or forward reader seam.
    def forbidden(*args, **kwargs):
        raise AssertionError("Final dispatch reached a model/forward inference seam")

    monkeypatch.setattr(connected.forward, "capture_account", forbidden)
    monkeypatch.setattr(connected.forward, "build_reader", forbidden)
    monkeypatch.setattr(connected.forward, "_forecast_identity", forbidden)


# Name the final phase explicitly while retaining the original fixed schedule.
def final_context(at):
    names = generic.cohort()
    return market.session_completion_context(
        at, names, cohort_sha256=packet._digest(list(names))
    )


# Reuse only synthetic account/packet setup, with separately named final contexts.
@pytest.fixture
def make(tmp_path, pins, monkeypatch):
    monkeypatch.setattr(generic, "context", final_context)
    fixture = generic.make.__wrapped__(tmp_path, pins)
    create = next(fixture)

    # Supply no distribution object to final dispatch and preserve all source bytes.
    def new(**kwargs):
        value = create(at=kwargs.pop("at", "2019-03-01T20:45:00Z"), **kwargs)
        value["distributions"] = None
        return value

    yield new
    with pytest.raises(StopIteration):
        next(fixture)


# Retain actual connected native results and exact no-model classification.
def run(value):
    result = value["cycle"].run(
        value["manifest"],
        value["registry"],
        value["captured"],
        None,
        anchors=value["anchors"],
    )
    CASES.append(
        {
            "origin": "SYNTHETIC_SESSION_COMPLETION_MARKET",
            "result": result,
            "ledger": value["client"].ledger(),
            "attempts": value["client"].attempt_history,
            "original_pending": paper.load_state(value["root"]).pending,
            "provider_gets": 0,
            "model_calls": 0,
        }
    )
    assert result["classification"] == "NOT_MODEL_TIMED"
    return result


# Count original native code invocations without replacing their policy bodies.
def counted(value):
    counts = {"ready": 0, "decide": 0}
    before_profile = sys.getprofile()

    # Observe only exact original native code objects in this synchronous thread.
    def profile(frame, event, arg):
        if event == "call":
            if frame.f_code is completion.READY.__code__:
                counts["ready"] += 1
            if frame.f_code is completion.DECIDE.__code__:
                counts["decide"] += 1

    sys.setprofile(profile)
    try:
        result = run(value)
    finally:
        sys.setprofile(before_profile)
    return result, counts


# Check actual native annotations, clocks, quantities and independent cash arithmetic.
@pytest.mark.parametrize("at", ["2019-03-01T20:45:00Z", "2019-11-29T17:45:00Z"])
def test_final_regular_and_early_close_exact_native_path(make, at):
    value = make(rows=[intent("buy", 2)], at=at)
    result, counts = counted(value)
    assert counts == {"ready": 1, "decide": 1}
    assert intraday_orders._ready is completion.READY
    assert intraday_orders.decide is completion.DECIDE
    verdict = result["verdicts"][0]["verdict"]
    assert verdict["send"] == intraday_orders.MARKET
    assert verdict["timed"]["reason"] == "Session completion"
    assert verdict["timed"]["level"] is None
    assert verdict["timed"]["level_fraction"] is None
    assert "forward_receipt" not in verdict["timed"]
    assert value["client"]._cash == pytest.approx(
        float(Decimal("599.6")), abs=1e-10, rel=0
    )
    assert value["client"]._held == {"AAPL": 2}
    assert value["client"]._average == {"AAPL": 200}
    assert result["venue"]["outcomes"][0]["fee"] == 0.4
    assert result["nav"] == pytest.approx(float(Decimal("999.59")), abs=1e-10, rel=0)
    assert paper.load_state(value["root"]).journal == []
    generic.restored(value, result)
    entry = value["store"].recover_operation(result["decision_operation"])
    receipt = packet._decode(
        value["store"].read_blob(entry["receipt_sha256"], limit=connected.META_CAP)
    )
    assert (
        receipt["detail"]["native_observation"]["snapshot_boundary"]
        == "AFTER_NATIVE_READY_BEFORE_FACTORY"
    )
    assert receipt["detail"]["forecast"] is None


# Preserve native SELL clipping and exclude its proceeds from the later BUY budget.
def test_final_sell_first_frozen_budget_and_fractional_residue(make):
    sell, buy = intent("sell", 8), intent("buy", 5, 1)
    buy["symbol"] = "MSFT"
    value = make(rows=[sell, buy], held={"AAPL": 5, "NVDA": 2.5}, reserve=True)
    result, counts = counted(value)
    assert counts == {"ready": 1, "decide": 2}
    assert value["client"]._cash == pytest.approx(
        float(Decimal("1198.15005")), abs=1e-10, rel=0
    )
    assert value["client"]._held == {"MSFT": 4, "NVDA": 2.5}
    assert value["client"]._average == {"MSFT": 200, "NVDA": 100}
    assert result["venue"]["initial_budget"] == pytest.approx(899.9)
    assert result["venue"]["nondue_reserved_cash"] == pytest.approx(100.1)
    assert [r["filled_qty"] for r in result["venue"]["outcomes"]] == [5, 4]
    assert [r["fee"] for r in result["venue"]["outcomes"]] == [0.99995, 0.8]
    generic.restored(value, result)


# Fractional held availability is floored only by native order sizing, never rounded.
def test_final_fractional_covered_sell_preserves_half_share(make):
    value = make(rows=[{**intent("sell", 8), "symbol": "NVDA"}], held={"NVDA": 2.5})
    result = run(value)
    assert value["client"]._held == {"NVDA": 0.5}
    assert value["client"]._cash == pytest.approx(
        float(Decimal("1399.58002")), abs=1e-10, rel=0
    )
    assert result["venue"]["original_submitted"][0]["qty"] == "2"
    assert result["venue"]["outcomes"][0]["filled_qty"] == 2


# Missing held or submission marks produce an outer skip with no native verdict.
@pytest.mark.parametrize("mode", ["held", "recent", "due"])
def test_missing_evidence_skips_before_native_dispatch(make, monkeypatch, mode):
    value = make(
        held={"NVDA": 2} if mode != "due" else {},
        absent=("NVDA",) if mode != "due" else ("AAPL",),
        prior_delay=10 if mode == "recent" else -60,
    )

    # Any preflight-skip branch must not even enter the native dispatch observer.
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing final evidence reached native dispatch")

    monkeypatch.setattr(completion, "dispatch", forbidden)
    result = run(value)
    assert result["factory_calls"] == 0
    assert result["verdicts"] == []
    assert result["skipped_native_final"][0]["native_verdict"] is None
    assert result["preflight"]["allowed"] is False
    assert value["client"]._attempts == []
    if mode != "due":
        assert result["preflight"]["missing_held_marks"] == ["NVDA"]
        assert connected.codec._pack(value["client"].__dict__) == value["prior"]
    if mode == "recent":
        assert result["preflight"]["native_error"] is None
        assert (
            result["preflight"]["broker_clock"]["timestamp"]
            == "2019-03-01T20:45:10+00:00"
        )


# A genuine native unknown cash claim remains an actual error and outer skip.
def test_native_account_error_preserved_without_native_final_verdict(make, monkeypatch):
    begin = connected.Cycle.begin

    # Introduce a native dated unknown claim before freezing the original prior state.
    def with_claim(self, reg):
        self.client.apply_share_consolidation(
            "NVDA", 1, 3, self.client._now, fractional_policy="cash_in_lieu_unknown"
        )
        return begin(self, reg)

    monkeypatch.setattr(connected.Cycle, "begin", with_claim)
    value = make(held={"NVDA": 10})
    result = run(value)
    assert result["verdicts"] == []
    assert result["preflight"]["allowed"] is False
    assert "Unknown consolidation" in result["preflight"]["native_error"]
    assert result["factory_calls"] == 0
    assert result["nav"] is None
    assert value["client"]._share_consolidations[0]["cash_in_lieu"] is None


# Native flush advances the real clock without observation; final must retain refusal.
def test_stale_native_observation_clock_skips_before_dispatch(make, monkeypatch):
    begin = connected.Cycle.begin

    # Produce a genuine native stale-clock state before the immutable prior snapshot.
    def stale(self, reg):
        self.client.flush(self.client._now + timedelta(seconds=1), {})
        return begin(self, reg)

    # Any stale-clock final preflight must finish without entering native dispatch.
    def forbidden(*args, **kwargs):
        raise AssertionError("Stale native clock reached final dispatch")

    monkeypatch.setattr(connected.Cycle, "begin", stale)
    monkeypatch.setattr(completion, "dispatch", forbidden)
    value = make(held={"NVDA": 2}, absent=("NVDA",))
    result = run(value)
    assert result["preflight"]["broker_clock"] is None
    assert (
        result["preflight"]["native_error"] == "Fresh observed account clock required"
    )
    assert result["preflight"]["native_now"] == "2019-03-01T20:44:01+00:00"
    assert result["preflight"]["native_observed_at"] == "2019-03-01T20:44:00+00:00"
    assert result["factory_calls"] == 0
    assert result["verdicts"] == []
    assert connected.codec._pack(value["client"].__dict__) == value["prior"]


# Empty final due sets commit empty receipts without native per-row claims.
def test_empty_final_set_does_not_dispatch(make, monkeypatch):
    value = make(rows=[])

    # Empty original intent sets need no native _ready invocation or model surrogate.
    def forbidden(*args, **kwargs):
        raise AssertionError("Empty final set reached native dispatcher")

    monkeypatch.setattr(completion, "dispatch", forbidden)
    result = run(value)
    assert result["verdicts"] == []
    assert result["skipped_native_final"] == []
    assert result["factory_calls"] == 0
    generic.restored(value, result)


# Failure to commit annotated native decisions restores both function identities.
def test_final_commit_crash_restores_functions_and_pauses(make, monkeypatch):
    value = make()

    # Fail the exact decision commit before any native factory or submission.
    def failed(*args, **kwargs):
        raise StorePause("SYNTHETIC final decision commit crash")

    monkeypatch.setattr(value["store"], "complete_operation", failed)
    with pytest.raises(StorePause, match="commit crash"):
        run(value)
    assert intraday_orders._ready is completion.READY
    assert intraday_orders.decide is completion.DECIDE
    assert not completion.LOCK.locked()
    assert value["client"]._attempts == []
    before = deepcopy(value["client"].__dict__)
    with pytest.raises(ValueError, match="Full broker"):
        run(value)
    assert value["client"].__dict__ == before


# A concurrent direct policy call cannot use the temporary native function bindings.
def test_nested_and_nonowner_calls_refuse_before_original_policy(make, monkeypatch):
    value = make(rows=[intent("buy", 2)])
    complete = value["store"].complete_operation
    errors = []

    # Attempt a direct native call only from another thread while the observer owns it.
    def nonowner():
        try:
            intraday_orders.decide({}, None, None, None, None)
        except StorePause as error:
            errors.append(str(error))

    # Probe nested dispatch during the already-observed decision's commit boundary.
    def probing(operation, receipt):
        stage = (
            value["store"]
            .connection.execute("SELECT stage FROM operations WHERE id=?", (operation,))
            .fetchone()[0]
        )
        if stage != "DECISION_FROZEN":
            return complete(operation, receipt)
        thread = Thread(target=nonowner)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        with pytest.raises((ValueError, StorePause)):
            completion.dispatch(
                root=value["root"],
                rows=paper.load_state(value["root"]).pending,
                now=connected.native._instant(
                    value["cycle"].window["assumed_decision_at"]
                ),
                context=value["context"],
                source_sha256=value["pins"]["identity"]["source_sha256"][
                    "backend/agents/trading/desk/intraday_orders.py"
                ],
                factory=lambda: None,
                freeze=lambda _: None,
            )
        return complete(operation, receipt)

    monkeypatch.setattr(value["store"], "complete_operation", probing)
    result, counts = counted(value)
    assert result["factory_calls"] == 1
    assert counts == {"ready": 1, "decide": 1}
    assert errors
    assert intraday_orders._ready is completion.READY
    assert intraday_orders.decide is completion.DECIDE


# Default model demand bytes remain unchanged and unknown final branches refuse.
def test_demand_default_and_explicit_branch_binding(make):
    value = make()
    data = demand.read(value["manifest"], value["registry"])
    args = {
        k: data[k]
        for k in ("identity_sha256", "parent_sha256", "prior", "held", "legs", "used")
    }
    args["completed_at"] = data["window"]["completed_at"]
    default = demand.build(value["registry"], **args)
    explicit = demand.build(value["registry"], **args, branch="MODEL_TIMED_MARKET_ONLY")
    assert default.raw == explicit.raw
    with pytest.raises(ValueError, match="branch"):
        demand.build(value["registry"], **args, branch="UNKNOWN")
    with pytest.raises(ValueError, match="branch"):
        value["cycle"].admit(default, value["registry"], value["captured"])
    tampered = {**data, "branch": "UNKNOWN"}
    raw = demand.encoded(tampered)
    with pytest.raises(ValueError, match="branch"):
        demand.read(demand.Demand(raw, connected.sha(raw)), value["registry"])


# Model contexts still reject final, and final contexts reject every other phase.
@pytest.mark.parametrize(
    "at", ["2019-03-01T20:30:00Z", "2019-03-01T21:00:00Z", "2019-03-02T20:45:00Z"]
)
def test_final_context_refuses_inexact_or_closed_windows(at):
    with pytest.raises(ValueError, match="session-completion"):
        final_context(at)
    names = generic.cohort()
    with pytest.raises(ValueError, match="final/auctions"):
        market.context(
            "2019-03-01T20:45:00Z", names, cohort_sha256=packet._digest(list(names))
        )
