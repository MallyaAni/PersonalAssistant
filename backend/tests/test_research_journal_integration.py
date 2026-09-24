"""Replay journals emitted by the actual research accounts, not copied ledgers.

Synthetic source arrays isolate accounting from strategy efficacy. None of these
tests fits a model, reruns an examined study, touches a paper account or promotes
a policy. Exact enabled/disabled equality protects the existing algorithms;
the independent verifier then reconstructs their observed fills and every NAV.
"""

from dataclasses import asdict, replace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market import allocation_controls as controls
from backend.market import learned_research as research
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_archive, verify_snapshot
from backend.tests.funded_simulator_fixtures import _report, _run
from backend.tests.test_learned_research import forecasts, panel


# Bind an isolated account to the exact arrays exercised by a synthetic fixture.
def _journal(sessions, symbols, opens, closes, cost_bps=10.0, policy="synthetic"):
    return ResearchJournal(
        sessions,
        symbols,
        opens,
        closes,
        run_id="journal-integration",
        account_id=f"synthetic-{policy}",
        policy_id=policy,
        cost_bps=cost_bps,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )


# Require every independent NAV reconstruction and preserve the research limits.
def _verified(journal, nav):
    result = verify_snapshot(journal.snapshot())
    assert result["ok"], result["errors"]
    assert result["accounting_verified"]
    assert result["integrity_verified"]
    assert result["complete"]
    assert len(result["marks"]) == len(nav)
    np.testing.assert_allclose(
        [mark["nav"] for mark in result["marks"]], nav, rtol=1e-12, atol=1e-12
    )
    for limitation in (
        "historical_availability_verified",
        "security_identity_verified",
        "settlement_verified",
        "adoption_eligible",
    ):
        assert result[limitation] is False
    assert result["terminal"]["status"] == "complete"
    assert result["total_fees"] == pytest.approx(
        result["total_traded"] * journal.snapshot()["manifest"]["cost_bps"] / 1e4,
        rel=1e-10,
        abs=1e-12,
    )
    return result


# Compare every public simulator output exactly while treating unavailable values alike.
def _same_simulation(plain, observed):
    for name in ("dates", "equity", "returns", "invested", "top_weight", "risk_off"):
        np.testing.assert_equal(getattr(plain, name), getattr(observed, name))
    for name in ("traded", "rebalances", "dip_adds"):
        assert getattr(plain, name) == getattr(observed, name)
    np.testing.assert_equal(plain.trace, observed.trace)
    np.testing.assert_equal(
        [asdict(trade) for trade in plain.trades],
        [asdict(trade) for trade in observed.trades],
    )


# Both benchmark controls retain exactly the same path through gaps and sales.
@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
@pytest.mark.parametrize("fraction", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("cost_bps", [0.0, 10.0, 25.0])
def test_control_journaling_preserves_exact_nav(symbol, fraction, cost_bps):
    sessions = np.arange("2024-01-02", "2024-01-09", dtype="datetime64[D]")
    closes = np.array([100.0, 200.0, 80.0, 150.0, 75.0, 100.0, 110.0])
    opens = np.array([100.0, 150.0, 200.0, 50.0, 175.0, 80.0, 120.0])
    journal = _journal(
        sessions, (symbol,), opens[:, None], closes[:, None], cost_bps, symbol
    )
    plain = controls.constant_exposure(closes, opens, fraction, cost_bps)
    observed = controls.constant_exposure(
        closes,
        opens,
        fraction,
        cost_bps,
        journal=journal,
        sessions=sessions,
        symbol=symbol,
    )
    assert np.array_equal(plain, observed)
    replayed = _verified(journal, observed)
    assert replayed["terminal"]["pending"] == {}
    events = journal.snapshot()["events"]
    batches = [event for event in events if event["type"] == "fill_batch"]
    assert len(batches) == len(sessions) - 1
    assert all(event["phase"] == "open" for event in batches)
    assert all(event["recycle_sells"] is False for event in batches)
    if fraction == 0:
        assert replayed["total_traded"] == 0
        assert replayed["total_fees"] == 0
        assert replayed["terminal"]["positions"] == [0.0]
        assert all(mark["cash"] == 1.0 for mark in replayed["marks"])
    if fraction == 1:
        assert 0 < batches[0]["filled_units"][0] < 0.01
        assert batches[0]["scale"] < 1
        assert replayed["terminal"]["positions"][0] > 0


# A recorder must match the producer's source identity, prices, calendar and costs.
@pytest.mark.parametrize("mismatch", ["symbol", "sessions", "opens", "cost"])
def test_control_refuses_a_journal_bound_to_different_inputs(mismatch):
    sessions = np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    closes = np.array([100.0, 110.0])
    opens = np.array([100.0, 105.0])
    journal = _journal(sessions, ("SPY",), opens[:, None], closes[:, None])
    supplied_sessions = sessions.copy()
    supplied_opens = opens.copy()
    symbol, cost_bps = "SPY", 10.0
    if mismatch == "symbol":
        symbol = "QQQ"
    elif mismatch == "sessions":
        supplied_sessions += np.timedelta64(1, "D")
    elif mismatch == "opens":
        supplied_opens[1] += 1
    else:
        cost_bps = 25.0
    with pytest.raises(ValueError, match="Journal .* differ[s]? from producer inputs"):
        controls.constant_exposure(
            closes,
            supplied_opens,
            1.0,
            cost_bps,
            journal=journal,
            sessions=supplied_sessions,
            symbol=symbol,
        )
    assert journal.snapshot()["events"] == []


# Benchmark labels and dates are mandatory when recording, never guessed.
@pytest.mark.parametrize("omitted", ["symbol", "sessions"])
def test_control_journaling_requires_explicit_source_context(omitted):
    sessions = np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    values = np.array([100.0, 110.0])
    journal = _journal(sessions, ("SPY",), values[:, None], values[:, None])
    context = {"sessions": sessions, "symbol": "SPY"}
    context.pop(omitted)
    with pytest.raises(ValueError, match="explicit source sessions and symbol"):
        controls.constant_exposure(values, values, 1.0, journal=journal, **context)
    assert journal.snapshot()["events"] == []


# A saved journal replays from its archive with no live producer object available.
def test_control_archive_replays_and_does_not_invent_terminal_liquidation(tmp_path):
    sessions = np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    closes = np.array([100.0, 95.0])
    opens = np.array([100.0, 120.0])
    journal = _journal(sessions, ("QQQ",), opens[:, None], closes[:, None])
    nav = controls.constant_exposure(
        closes, opens, 1.0, journal=journal, sessions=sessions, symbol="QQQ"
    )
    archive = tmp_path / "control-journal"
    journal.archive(archive)
    result = verify_archive(archive)
    assert result["ok"], result["errors"]
    assert result["terminal"]["positions"][0] > 0
    assert result["total_traded"] == pytest.approx(1 / 1.001)
    assert result["marks"][-1]["nav"] == pytest.approx(nav[-1])
    assert result["terminal"]["cash"] == pytest.approx(0, abs=1e-12)


# Existing research replay remains identical through an overnight gap or rotation.
@pytest.mark.parametrize("policy", ["SPY", "QQQ", "momentum120"])
def test_learned_replay_journaling_preserves_every_account_series(policy):
    source = panel()
    if policy in ("SPY", "QQQ"):
        column = source.index(policy)
        source.open[261:, column] = 200
        source.close[261:, column] = 200
        source.adj_close[261:, column] = 200
    data = research.prepare(source)
    scores = np.zeros_like(data.momentum)
    scores[:280, :10] = 1
    scores[280:, 10:20] = 2
    data = replace(data, momentum=scores)
    rank, brake = forecasts(data)
    journal = _journal(
        source.dates,
        source.tickers,
        simulate.adjusted_open(source),
        source.adj_close,
        policy=policy,
    )
    plain = research.replay(data, rank, brake, 260, policy, 10)
    observed = research.replay(data, rank, brake, 260, policy, 10, journal=journal)
    for name in ("dates", "nav", "turnover", "cash"):
        assert np.array_equal(plain[name], observed[name])
    assert plain["decisions"] == observed["decisions"]
    result = _verified(journal, observed["nav"])
    np.testing.assert_allclose(
        [mark["cash"] for mark in result["marks"]],
        observed["cash"] * observed["nav"],
        rtol=1e-12,
        atol=1e-12,
    )
    if policy == "momentum120":
        assert observed["cash"][21] > 0.99
        assert observed["cash"][22] < 1e-10
        assert result["total_traded"] > 2


# The funded simulator's public path emits every actual cash and holding mark.
@pytest.mark.parametrize("missing_open", [False, True])
def test_funded_simulator_journaling_preserves_trace_and_every_nav(missing_open):
    report = _report()
    if missing_open:
        report.panel = replace(report.panel, open=report.panel.open.copy())
        report.panel.open[61, 1] = np.nan
    source = report.panel
    journal = _journal(
        source.dates,
        source.tickers,
        simulate.adjusted_open(source),
        source.adj_close,
        policy="funded-simulator",
    )
    plain = _run(report)
    observed = _run(report, journal=journal)
    for name in ("equity", "returns", "invested", "top_weight"):
        assert np.array_equal(
            getattr(plain, name), getattr(observed, name), equal_nan=True
        )
    assert plain.trace == observed.trace
    assert plain.traded == observed.traded
    result = _verified(journal, observed.equity)
    assert result["total_traded"] == pytest.approx(observed.traded)
    np.testing.assert_allclose(
        [mark["cash"] for mark in result["marks"]][1:],
        [entry["cash_after"] for entry in observed.trace],
        rtol=1e-12,
        atol=1e-12,
    )
    if missing_open:
        batches = [
            e
            for e in journal.snapshot()["events"]
            if e["type"] == "fill_batch" and e["session_index"] == 61
        ]
        assert len(batches) == 1
        assert batches[0]["unfilled_reasons"][1] == "price_unavailable"
        assert batches[0]["filled_units"][1] == 0
        assert observed.trace[61]["shares_after"]["N1"] > 0


# The public lifecycle records its actual cut, deferral and next-open restoration.
def test_simulator_event_lifecycle_journal_replays_the_real_transition_branch():
    report = _report(close=np.full((24, 6), 100.0))
    source = report.panel
    exposure = np.ones(24)
    exposure[4:9] = 0.5
    allocation_sessions = []

    # Expose actual rebalance timing while keeping composition fixed for accounting.
    def allocation(report, panel, config, session):
        allocation_sessions.append(session)
        return np.array([0.5, 0, 0, 0, 0, 0])

    options = {
        "allocator": allocation,
        "rebalance": 5,
        "use_exits": False,
        "cost_bps": 10,
        "event_exposure": exposure,
        "event_lifecycle": True,
    }
    journal = _journal(source.dates, source.tickers, source.open, source.adj_close)
    plain = simulate.run(report, **options)
    original_sessions = allocation_sessions.copy()
    allocation_sessions.clear()
    observed = simulate.run(report, **options, journal=journal)
    _same_simulation(plain, observed)
    assert original_sessions == allocation_sessions == [0, 10, 15, 20]
    result = _verified(journal, observed.equity)
    events = journal.snapshot()["events"]
    decisions = {
        event["decision_id"]: event for event in events if event["type"] == "decision"
    }
    cuts, restores = [], []
    for batch in (event for event in events if event["type"] == "fill_batch"):
        decision = decisions[batch["decision_id"]]
        if decision["reason"] == "FOMC risk reduction" and batch["gross_sells"] > 0:
            cuts.append(batch)
        if decision["reason"] == "FOMC risk restoration" and batch["gross_buys"] > 0:
            restores.append(batch)
    assert len(cuts) == len(restores) == 1
    assert (cuts[0]["session_index"], cuts[0]["phase"]) == (5, "open")
    assert (restores[0]["session_index"], restores[0]["phase"]) == (10, "open")
    assert cuts[0]["filled_units"][0] == pytest.approx(-0.0025)
    assert restores[0]["filled_units"][0] == pytest.approx(0.0025)
    assert result["marks"][5]["positions"][0] == pytest.approx(0.0025)
    assert result["marks"][10]["positions"][0] == pytest.approx(0.005)
    assert result["terminal"]["pending"] == {}


# A real green-open suppression remains attached to its original submitted sell.
@pytest.mark.parametrize("exit_at_close", [False, True])
def test_simulator_green_day_skip_journal_preserves_the_adjusted_sell(exit_at_close):
    closes = np.full((7, 6), 100.0)
    opens = closes.copy()
    opens[4, 0] = 110.0
    report = _report(close=closes, open=opens)
    source = report.panel

    # Submit a real rotation on the rebalance just before the old holding gaps up.
    def allocation(report, panel, config, session):
        target = np.zeros(6)
        target[0 if session == 0 else 1] = 0.5
        return target

    options = {
        "allocator": allocation,
        "rebalance": 3,
        "use_exits": False,
        "cost_bps": 10,
        "exit_at_close": exit_at_close,
    }
    journal = _journal(source.dates, source.tickers, opens, closes)
    no_skip = simulate.run(report, **options)
    plain = simulate.run(report, **options, green_day_skip=True)
    observed = simulate.run(report, **options, green_day_skip=True, journal=journal)
    _same_simulation(plain, observed)
    result = _verified(journal, observed.equity)
    events = journal.snapshot()["events"]
    suppression = [
        event
        for event in events
        if event["type"] == "adjustment"
        and event["reason"] == "green-open sell suppression"
    ]
    assert len(suppression) == 1
    adjustment = suppression[0]
    assert (adjustment["session_index"], adjustment["phase"]) == (4, "open")
    decision = next(
        event
        for event in events
        if event["type"] == "decision"
        and event["decision_id"] == adjustment["decision_id"]
    )
    assert decision["session_index"] == 3
    assert decision["submitted_units"][0] == 0
    assert adjustment["submitted_units"][0] > 0
    batches = [
        event
        for event in events
        if event["type"] == "fill_batch" and event["session_index"] == 4
    ]
    assert [batch["phase"] for batch in batches] == (
        ["open", "close"] if exit_at_close else ["open"]
    )
    assert all(batch["filled_units"][0] == 0 for batch in batches)
    assert result["marks"][4]["positions"][0] > 0
    assert result["terminal"]["positions"][0] > 0
    assert all(
        trade.closed is not None for trade in no_skip.trades if trade.ticker == "N0"
    )
    assert any(
        trade.closed is None for trade in observed.trades if trade.ticker == "N0"
    )


# Unavailable held prices stay unavailable and prevent an accounting verification.
def test_funded_missing_held_close_preserves_outputs_and_rejects_replay():
    report = _report()
    report.panel = replace(
        report.panel,
        open=report.panel.open.copy(),
        close=report.panel.close.copy(),
        adj_close=report.panel.adj_close.copy(),
    )
    source = report.panel
    for prices in (source.open, source.close, source.adj_close):
        prices[62, 1] = np.nan
    journal = _journal(
        source.dates,
        source.tickers,
        simulate.adjusted_open(source),
        source.adj_close,
    )
    plain = _run(report)
    observed = _run(report, journal=journal)
    _same_simulation(plain, observed)
    assert np.isnan(observed.equity[62])
    assert np.isnan(observed.returns[62:64]).all()
    assert np.isfinite(observed.equity[63])
    assert observed.trace[62]["fills"] == {}
    snapshot = journal.snapshot()
    marks = {
        event["session_index"]: event
        for event in snapshot["events"]
        if event["type"] == "mark"
    }
    assert marks[62]["nav"] is None
    assert marks[62]["unavailable_held_symbols"] == ["N1"]
    assert marks[62]["positions"][1] == marks[61]["positions"][1] > 0
    assert marks[63]["positions"][1] == marks[62]["positions"][1]
    assert marks[63]["unavailable_held_symbols"] == []
    assert marks[63]["nav"] is not None
    assert snapshot["prices"]["close"][62][1] is None
    result = verify_snapshot(snapshot)
    assert result["ok"] is False
    assert result["integrity_verified"] is True
    assert result["accounting_verified"] is False
    assert result["complete"] is False
    assert "held closing mark unavailable" in result["errors"]


# Drive the real book through an open-buy/close-sell rotation and retained retry.
def _split_rotation(report, journal=None):
    source = report.panel
    book = simulate._Book(
        len(source.tickers), 1.0, 10.0, source, report, source.dates, journal=journal
    )
    nav, cash, held = [1.0], [1.0], [book.shares.copy()]
    if journal is not None:
        journal.open_account(0, book.cash, book.shares)
        book.observe_mark(0, 1.0)
    for decision in range(len(source.dates) - 1):
        target = np.zeros(len(source.tickers))
        target[0 if decision == 0 else 1] = 1.0
        order = book.plan(target, source.adj_close[decision])
        book.observe_decision(decision, order, target, reason="synthetic-rotation")
        session = decision + 1
        book.settle_split(
            order,
            source.open[session],
            source.adj_close[session],
            session,
            "synthetic-rotation",
            recycle_sells=False,
        )
        nav.append(book.equity(source.adj_close[session]))
        cash.append(book.cash)
        held.append(book.shares.copy())
        book.observe_mark(session, nav[-1])
    if journal is not None:
        journal.finish(session, book.cash, book.shares, book.traded, pending={})
    return np.array(nav), np.array(cash), np.array(held), book.traded


# Separate phase prices and the no-recycle convention survive independent replay.
def test_split_open_buy_close_sell_keeps_prices_cash_and_partial_fills_distinct():
    closes = np.full((4, 6), 100.0)
    closes[1:, 0] = [110.0, 120.0, 130.0]
    closes[1:, 1] = [80.0, 100.0, 145.0]
    opens = closes.copy()
    opens[1, 0] = 100.0
    opens[2, 0] = 200.0
    opens[2, 1] = 200.0
    opens[3, 1] = 150.0
    report = _report(close=closes, open=opens)
    source = report.panel
    journal = _journal(source.dates, source.tickers, opens, closes)
    plain = _split_rotation(report)
    observed = _split_rotation(report, journal)
    for expected, actual in zip(plain, observed, strict=True):
        assert np.array_equal(expected, actual)
    result = _verified(journal, observed[0])
    np.testing.assert_allclose(
        [mark["cash"] for mark in result["marks"]], observed[1], atol=1e-12
    )
    np.testing.assert_allclose(
        [mark["positions"] for mark in result["marks"]], observed[2], atol=1e-12
    )
    assert observed[1][2] > 1.19
    assert observed[2][2, 1] == pytest.approx(0, abs=1e-12)
    assert observed[2][3, 1] > 0
    batches = [e for e in journal.snapshot()["events"] if e["type"] == "fill_batch"]
    sales = [e for e in batches if e["gross_sells"] > 0]
    assert len(sales) == 1
    assert sales[0]["phase"] == "close"
    assert sales[0]["prices"][0] == 120.0


# Exercise a real purchase followed by a too-small-to-trade zero target.
def _zero_target_residual(report, journal=None):
    source = report.panel
    opens, closes = source.open, source.adj_close
    book = simulate._Book(6, 1.0, 10.0, source, report, source.dates, journal=journal)
    if journal is not None:
        journal.open_account(0, book.cash, book.shares)
    book.observe_mark(0, 1.0)
    target = np.array([0.5, 0, 0, 0, 0, 0])
    order = book.plan(target, closes[0])
    book.observe_decision(0, order, target, reason="synthetic-entry")
    book.settle(order, opens[1], 1, "synthetic-entry")
    nav = [1.0, book.equity(closes[1])]
    book.observe_mark(1, nav[-1])
    residual = book.shares.copy()
    zero = np.zeros(6)
    order = book.plan(zero, closes[1])
    book.observe_decision(1, order, zero, reason="synthetic-zero-target")
    book.settle(order, opens[2], 2, "synthetic-zero-target")
    nav.append(book.equity(closes[2]))
    book.observe_mark(2, nav[-1])
    if journal is not None:
        journal.finish(2, book.cash, book.shares, book.traded, pending={})
    return np.array(nav), residual, book.shares.copy(), book.cash, book.traded, order


# A zero target records the minimum-trade residual without changing liquidation.
def test_zero_target_keeps_and_records_the_existing_minimum_trade_residual():
    closes = np.full((3, 6), 100.0)
    closes[1:, 0] = 0.1
    opens = closes.copy()
    opens[1, 0] = 100.0
    report = _report(close=closes, open=opens)
    source = report.panel
    journal = _journal(source.dates, source.tickers, opens, closes)
    plain = _zero_target_residual(report)
    observed = _zero_target_residual(report, journal)
    for expected, actual in zip(plain, observed, strict=True):
        assert np.array_equal(expected, actual)
    assert np.array_equal(observed[1], observed[-1])
    assert observed[-1][0] > 0
    result = _verified(journal, observed[0])
    np.testing.assert_array_equal(result["terminal"]["positions"], observed[1])
    decisions = [e for e in journal.snapshot()["events"] if e["type"] == "decision"]
    assert decisions[-1]["desired_weights"] == [0.0] * 6
    assert decisions[-1]["submitted_units"][0] > 0


# A final-session rotation preserves its real retry flag instead of inventing a fill.
def test_learned_replay_terminal_state_preserves_an_unexecuted_funding_retry():
    source = panel(rows=282)
    data = research.prepare(source)
    scores = np.zeros_like(data.momentum)
    scores[:280, :10] = 1
    scores[280:, 10:20] = 2
    data = replace(data, momentum=scores)
    rank, brake = forecasts(data)
    journal = _journal(
        source.dates,
        source.tickers,
        simulate.adjusted_open(source),
        source.adj_close,
        policy="momentum120",
    )
    plain = research.replay(data, rank, brake, 260, "momentum120", 10)
    observed = research.replay(
        data, rank, brake, 260, "momentum120", 10, journal=journal
    )
    for name in ("dates", "nav", "cash", "turnover"):
        assert np.array_equal(plain[name], observed[name])
    result = _verified(journal, observed["nav"])
    assert result["terminal"]["pending"]["retry"] is True
    assert result["terminal"]["cash"] > 0.99
    assert result["marks"][-1]["session_index"] == 281


# An account without an explicit terminal state is not a completed replay.
def test_missing_terminal_state_is_rejected_even_with_a_valid_initial_mark():
    sessions = np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    values = np.full((2, 1), 100.0)
    journal = _journal(sessions, ("SPY",), values, values)
    journal.open_account(0, 1.0, [0.0])
    journal.mark(0, 1.0, [0.0], 1.0, 0.0)
    journal.mark(1, 1.0, [0.0], 1.0, 0.0)
    result = verify_snapshot(journal.snapshot())
    assert result["ok"] is False
    assert result["complete"] is False
    assert result["terminal"] is None
    assert result["errors"]
