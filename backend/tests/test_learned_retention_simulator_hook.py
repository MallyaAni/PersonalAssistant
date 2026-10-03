"""Exercise optional retention inside the actual funded daily simulator loop."""

import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v5, simulate
from backend.tests.test_market_pit_scorecard import _report


# Create a real report with a held name downgraded to B and later to C.
def report_fixture():
    report = _report()
    prices = np.full_like(report.panel.adj_close, 100.0)
    panel = replace(
        report.panel,
        open=prices.copy(),
        high=prices.copy(),
        low=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades = report.graded.grades.copy()
    grades[25:70, 1] = 1
    grades[70:, 1] = 0
    return replace(report, panel=panel, graded=replace(report.graded, grades=grades))


# Supply unchanged policy selection and legacy funded execution to both arms.
def options(report):
    eligible = np.ones(report.panel.adj_close.shape, dtype=bool)
    eligible[:, -1] = False
    return {
        "allocator": policy_v5.allocator(eligible),
        "use_exits": False,
        "rebalance": 20,
        "exit_at_close": True,
        "deferred_buys": True,
        "live_midcycle": True,
        "midcycle_redeploy": True,
        "cost_bps": 10.0,
    }


class Passthrough:
    # Record callback clocks without changing any reset target.
    def reset(self, t, target, closes, held, cash, grades, blocked):
        return target

    # Preserve every incumbent exit and buy gate when predictions are unavailable.
    def midcycle(self, t, prices, held, grades, finished, excluded, equity, cash):
        return finished, excluded, {}


class KeepB(Passthrough):
    # Remember resets and midcycle holdings for acceptance assertions.
    def __init__(self, fraction=1.0):
        self.fraction = fraction
        self.resets = []
        self.midcycles = []

    # Reserve existing B shares while preserving the relative A reset basket.
    def reset(self, t, target, closes, held, cash, grades, blocked):
        self.resets.append(t)
        nav = float(cash + np.dot(held, closes))
        reserve = np.where(grades == 1, held * closes / nav, 0)
        reserve = np.minimum(reserve, 0.25)
        if target.sum() > 0:
            target *= (1 - reserve.sum()) / target.sum()
        return target + reserve

    # Retain only ordinary held-B exits and prohibit additions to those names.
    def midcycle(self, t, prices, held, grades, finished, excluded, equity, cash):
        self.midcycles.append((t, held.copy(), cash))
        retained = {
            s: held[s] * self.fraction
            for s in finished
            if grades[s] == "B" and s in held
        }
        return (
            {s: reason for s, reason in finished.items() if s not in retained},
            excluded | set(retained),
            retained,
        )


# Missing predictions produce identical account curves and trades through the real loop.
def test_passthrough_is_bit_identical_to_default():
    report = report_fixture()
    baseline = simulate.run(report, **options(report))
    candidate = simulate.run(report, **options(report), retention_adapter=Passthrough())
    for key in ("equity", "returns", "invested", "top_weight", "dates"):
        np.testing.assert_array_equal(getattr(candidate, key), getattr(baseline, key))
    assert candidate.traded == baseline.traded
    assert candidate.rebalances == baseline.rebalances
    assert json.dumps(
        [asdict(t) for t in candidate.trades], sort_keys=True
    ) == json.dumps([asdict(t) for t in baseline.trades], sort_keys=True)


# The offset shifts resets while ordinary midcycle cash deployment remains active.
def test_offset_delays_first_reset_without_pausing_existing_midcycle():
    report = report_fixture()
    hook = KeepB()
    result = simulate.run(
        report, **options(report), retention_adapter=hook, rebalance_offset=7
    )
    assert hook.resets[:3] == [7, 27, 47]
    assert result.equity[0] == 1
    assert result.equity[1] < 1
    assert result.invested[1] > 0


# A retained B survives daily rotation and subsequent resets but C still exits.
def test_held_b_is_not_added_and_c_exit_remains(monkeypatch):
    report = report_fixture()
    decisions = []
    original = simulate._Book.observe_decision

    # Capture orders from the real account before fills without changing its behavior.
    def capture(book, t, order, *args, **kwargs):
        decisions.append((t, book.shares.copy(), order.copy()))
        return original(book, t, order, *args, **kwargs)

    monkeypatch.setattr(simulate._Book, "observe_decision", capture)
    simulate.run(report, **options(report), retention_adapter=KeepB())
    for t, held, wanted in decisions:
        if 25 <= t < 70:
            assert held[1] > 0
            assert wanted[1] <= held[1] + 1e-12
            assert wanted[1] == pytest.approx(held[1])
        if t == 70:
            assert wanted[1] == 0


# Declared share caps trim a B while its replacement purchases are recomputed.
def test_midcycle_cap_cut_is_an_actual_sell(monkeypatch):
    report = report_fixture()
    decisions = []
    original = simulate._Book.observe_decision

    # Record the ordinary submitted quantities for the first downgraded session.
    def capture(book, t, order, *args, **kwargs):
        if t == 25:
            decisions.append((book.shares.copy(), order.copy()))
        return original(book, t, order, *args, **kwargs)

    monkeypatch.setattr(simulate._Book, "observe_decision", capture)
    simulate.run(report, **options(report), retention_adapter=KeepB(0.5))
    held, wanted = decisions[0]
    assert wanted[1] == pytest.approx(held[1] * 0.5)


# Active event lifecycle sessions bypass both hooks and retain the incumbent event path.
def test_event_lifecycle_bypasses_hooks_and_preserves_passthrough():
    report = report_fixture()
    exposure = np.ones(len(report.panel.dates))
    exposure[24:43] = 0.5
    common = {**options(report), "event_lifecycle": True, "event_exposure": exposure}
    baseline = simulate.run(report, **common)
    hook = KeepB()
    candidate = simulate.run(report, **common, retention_adapter=hook)
    assert not any(24 <= t <= 43 for t in hook.resets)
    assert not any(24 <= t <= 43 for t, _, _ in hook.midcycles)
    # No B survives the C downgrade after the event path resumes.
    assert np.isfinite(candidate.equity).all()
    passthrough = simulate.run(report, **common, retention_adapter=Passthrough())
    np.testing.assert_array_equal(passthrough.equity, baseline.equity)
    assert passthrough.traded == baseline.traded


# Incompatible or unsupported options fail instead of silently bypassing the hook.
@pytest.mark.parametrize(
    "bad",
    [
        {"funded_allocation": True},
        {"weight_filter": lambda *_: None},
        {"midcycle_exits": False},
        {"live_midcycle": False},
        {"use_exits": True},
    ],
)
def test_incompatible_paths_are_rejected(bad):
    report = report_fixture()
    with pytest.raises(ValueError, match="retention"):
        simulate.run(
            report, **{**options(report), **bad}, retention_adapter=Passthrough()
        )


# Invalid phase clocks cannot alter the cohort or reset cadence.
@pytest.mark.parametrize("offset", [-1, 20, True, 1.5, "1"])
def test_offset_is_a_bounded_integer(offset):
    report = report_fixture()
    with pytest.raises(ValueError, match="rebalance_offset"):
        simulate.run(report, **options(report), rebalance_offset=offset)


# Explicit zero offset exercises exactly the old loop and account initialization.
def test_explicit_default_phase_is_bit_identical():
    report = report_fixture()
    baseline = simulate.run(report, **options(report))
    result = simulate.run(report, **options(report), rebalance_offset=0)
    np.testing.assert_array_equal(result.equity, baseline.equity)
    np.testing.assert_array_equal(result.returns, baseline.returns)
    assert result.traded == baseline.traded


class MutatingPassthrough(Passthrough):
    # Mutate every supplied array while returning the original reset verdict.
    def reset(self, t, target, closes, held, cash, grades, blocked):
        original = target.copy()
        target[:] = 99
        closes[:] = -1
        held[:] = 99
        grades[:] = -99
        blocked[:] = True
        return original

    # Mutate input mappings without changing the returned original planning verdict.
    def midcycle(self, t, prices, held, grades, finished, excluded, equity, cash):
        original_finished, original_excluded = finished.copy(), excluded.copy()
        prices.clear()
        held.clear()
        grades.clear()
        finished.clear()
        excluded.clear()
        return original_finished, original_excluded, {}


# Caller-visible mutations cannot corrupt source arrays or the carried account.
def test_callback_inputs_are_copies():
    report = report_fixture()
    prices, grades = report.panel.adj_close.copy(), report.graded.grades.copy()
    baseline = simulate.run(report, **options(report))
    result = simulate.run(
        report, **options(report), retention_adapter=MutatingPassthrough()
    )
    np.testing.assert_array_equal(result.equity, baseline.equity)
    assert result.traded == baseline.traded
    np.testing.assert_array_equal(report.panel.adj_close, prices)
    np.testing.assert_array_equal(report.graded.grades, grades)


# An unheld missing-price cell is not a missing held mark or an unavailable account.
def test_reset_preserves_unheld_missing_price_cells():
    report = report_fixture()
    panel = report.panel
    prices = panel.adj_close.copy()
    prices[0, 1] = np.nan
    panel = replace(panel, close=prices, adj_close=prices)
    report = replace(report, panel=panel)
    baseline = simulate.run(report, **options(report))
    result = simulate.run(report, **options(report), retention_adapter=Passthrough())
    np.testing.assert_array_equal(result.equity, baseline.equity)


class InvalidReset(Passthrough):
    # Save one deliberately malformed reset response for structural rejection.
    def __init__(self, value):
        self.value = value

    # Return malformed dimensions or weights without inspecting future data.
    def reset(self, t, target, closes, held, cash, grades, blocked):
        return self.value


# Reset hooks must return numeric, finite, capped weights on the exact grid.
@pytest.mark.parametrize(
    "response",
    [
        [0.1],
        ["0.1"] * 7,
        np.full(7, np.nan),
        np.full(7, -0.1),
        np.full(7, 0.2),
        np.array([0.3, 0, 0, 0, 0, 0, 0]),
        np.array([0, 0, 0, 0, 0, 0, 0.1]),
    ],
)
def test_invalid_reset_responses_fail_in_real_loop(response):
    report = report_fixture()
    with pytest.raises(ValueError, match="retention"):
        simulate.run(
            report, **options(report), retention_adapter=InvalidReset(response)
        )


class InvalidMidcycle(Passthrough):
    # Choose one prohibited modification of the ordinary B rotation response.
    def __init__(self, mode):
        self.mode = mode

    # Violate one boundary after the real account has acquired a B position.
    def midcycle(self, t, prices, held, grades, finished, excluded, equity, cash):
        if "BBB" not in finished:
            return finished, excluded, {}
        changed = {s: reason for s, reason in finished.items() if s != "BBB"}
        blocked = excluded | {"BBB"}
        caps = {"BBB": held["BBB"]}
        if self.mode == "increase":
            caps["BBB"] *= 2
        elif self.mode == "negative":
            caps["BBB"] = -1
        elif self.mode == "missing_cap":
            caps = {}
        elif self.mode == "missing_block":
            blocked = excluded
        elif self.mode == "change_reason":
            changed = {"BBB": "different"}
            caps = {}
        elif self.mode == "extra_cap":
            caps["AAA"] = held["AAA"]
        elif self.mode == "C" and grades["BBB"] != "C":
            return finished, excluded, {}
        return changed, blocked, caps


# Invalid B additions, omitted blocks and C removals fail before funding or fills.
@pytest.mark.parametrize(
    "mode",
    [
        "increase",
        "negative",
        "missing_cap",
        "missing_block",
        "change_reason",
        "extra_cap",
        "C",
    ],
)
def test_invalid_midcycle_responses_fail_in_real_loop(mode):
    report = report_fixture()
    if mode == "C":
        grades = report.graded.grades.copy()
        grades[25:, 1] = 0
        report = replace(report, graded=replace(report.graded, grades=grades))
    with pytest.raises(ValueError, match="retention"):
        simulate.run(report, **options(report), retention_adapter=InvalidMidcycle(mode))


# A custom mandatory thesis exit cannot be relabelled as a removable grade rotation.
def test_custom_mandatory_reason_cannot_be_removed():
    with pytest.raises(ValueError, match="ordinary"):
        simulate._retention_midcycle_inputs(
            KeepB(),
            0,
            {"BBB": 100.0},
            {"BBB": 1.0},
            {"BBB": "B"},
            {"BBB": "company thesis ended"},
            set(),
            1000.0,
            900.0,
        )


# Existing buy blocks and low-grade holdings remain structural reset restrictions.
@pytest.mark.parametrize(
    ("grades", "held", "blocked"),
    [
        (np.array([1]), np.array([0.0]), np.array([False])),
        (np.array([0]), np.array([1.0]), np.array([False])),
        (np.array([2]), np.array([0.0]), np.array([True])),
    ],
)
def test_reset_cannot_introduce_low_grade_or_blocked_purchases(grades, held, blocked):
    with pytest.raises(ValueError, match="retention"):
        simulate._retention_reset(
            InvalidReset([0.1]),
            0,
            np.array([0.0]),
            np.array([100.0]),
            held,
            1000.0,
            grades,
            blocked,
        )


# A scheduled retained-B trim must reach submitted units below the trade minimum.
def test_reset_cap_cut_bypasses_trade_floor_only_for_retained_b(monkeypatch):
    report = report_fixture()
    grades = report.graded.grades.copy()
    grades[:40, 1] = 3
    prices = report.panel.adj_close.copy()
    prices[40:, 1] = 168.0
    panel = replace(
        report.panel,
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
        high=prices.copy(),
        low=prices.copy(),
    )
    report = replace(report, panel=panel, graded=replace(report.graded, grades=grades))
    decisions = []
    original = simulate._Book.observe_decision

    # Capture the scheduled-reset request before existing execution adjustments.
    def capture(book, t, order, *args, **kwargs):
        if t == 40:
            nav = book.equity(panel.adj_close[t])
            decisions.append((book.shares[1], order[1], 0.25 * nav / prices[t, 1]))
        return original(book, t, order, *args, **kwargs)

    monkeypatch.setattr(simulate._Book, "observe_decision", capture)
    simulate.run(report, **options(report), retention_adapter=KeepB())
    held, wanted, cap = decisions[0]
    assert held > cap
    assert wanted <= cap


# Reconcile active retention without B additions or sale-funded buys.
def test_active_retention_preserves_journal_funding_and_owned_quantities():
    from backend.market.research_journal import ResearchJournal
    from backend.market.research_journal_replay import verify_snapshot
    from backend.market.retention_replay import RetentionAdapter

    report = report_fixture()
    panel = report.panel
    eligible = np.ones(panel.close.shape, dtype=bool)
    eligible[:, -1] = False
    forecasts = np.zeros(panel.close.shape)
    forecasts[:, 1] = 0.2
    adapter = RetentionAdapter(
        panel.tickers, eligible, forecasts, np.zeros(len(panel.dates)), 10
    )
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id="retention-active",
        account_id="carried",
        policy_id="test-only",
        cost_bps=10,
        provenance={"fixture": "active-retention"},
    )
    simulate.run(report, **options(report), retention_adapter=adapter, journal=journal)
    snapshot = journal.snapshot()
    assert verify_snapshot(snapshot)["ok"]
    assert any(event["reason"] == "retain" for event in adapter.events)
    for event in snapshot["events"]:
        if event["type"] != "fill_batch":
            continue
        if 26 <= event["session_index"] <= 70:
            assert event["positions_after"][1] <= event["positions_before"][1] + 1e-12
        if event["gross_buys"] > 0:
            assert event["buy_budget"] <= event["cash_before"] + 1e-12
