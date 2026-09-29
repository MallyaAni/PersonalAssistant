"""Exact counterfactual forks of the existing cash-funded `/4` simulator."""

import pickle
from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v4, simulate
from backend.market import profit_taking
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.market.simulator_checkpoint import ResearchOrder
from backend.tests.funded_simulator_fixtures import _report


# Build changing grades, a green opening gap, funding retries and a bounded event.
def _source(rows=48):
    prices = np.full((rows, 7), 100.0)
    prices[:, 1] += np.sin(np.arange(rows))
    grades = np.zeros_like(prices, dtype=int)
    grades[:, :5] = 3
    grades[20:, 0] = 0
    grades[20:, 5] = 3
    opens = prices.copy()
    opens[6, 0] = 110.0
    opens[21, 0] = 110.0
    report = _report(close=prices, grades=grades, open=opens)
    mask = np.ones_like(prices, dtype=bool)
    options = profit_taking.control_options(report.panel)
    event = np.ones(rows)
    event[7:10] = 0.5
    options["event_exposure"] = event
    return report, mask, options


# Compare continuation observations with the same positions on a full-prefix run.
def _same_tail(prefix, resumed, t):
    for key in ("dates", "equity", "invested", "top_weight", "risk_off"):
        np.testing.assert_array_equal(getattr(resumed, key), getattr(prefix, key)[t:])
    np.testing.assert_array_equal(resumed.returns[1:], prefix.returns[t + 1 :])
    assert np.isnan(resumed.returns[0])
    assert resumed.traded == prefix.traded
    assert resumed.rebalances == prefix.rebalances
    assert resumed.dip_adds == prefix.dip_adds
    assert repr(resumed.trades) == repr(prefix.trades)


# Observe no-op callbacks without allowing future source or mutable book references.
def test_preparation_and_noop_capture_preserve_exact_results():
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    plain = simulate.run(report, allocator=allocate, cost_bps=25, **options)
    prepared = simulate.prepare_research(report, **options)
    checkpoints, contexts = [], []

    # Record close-local context and return no intervention.
    def observe(context):
        contexts.append(context)
        assert not context.prices.flags.writeable
        assert not context.held_units.flags.writeable
        assert not context.incumbent_units.flags.writeable
        assert not context.buy_allowed[-1]
        return None

    observed = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_capture=checkpoints.append,
        research_hook=observe,
        **options,
    )
    _same_tail(plain, observed, 0)
    assert len(checkpoints) == len(report.panel.dates) - 1
    assert checkpoints[10].event_baseline is not None
    assert checkpoints[21].pending_deferred
    assert all(context.t not in (7, 8, 9, 10) for context in contexts)
    assert checkpoints[5].shares.flags.writeable is False
    assert checkpoints[1].trades is checkpoints[2].trades


# Every short no-op fork must equal a fresh full-prefix run through that endpoint.
@pytest.mark.parametrize("start", [0, 1, 6, 7, 8, 10, 11, 19, 20, 21, 22, 39, 40])
def test_resume_exact_through_events_resets_and_funding(start):
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    prepared = simulate.prepare_research(report, **options)
    checkpoints = []
    simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_capture=checkpoints.append,
        **options,
    )
    stop = min(start + 7, len(report.panel.dates) - 1)
    resumed = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_resume=checkpoints[start],
        research_stop=stop,
        **options,
    )
    prefix = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_stop=stop,
        **options,
    )
    _same_tail(prefix, resumed, start)


# Build one deterministic reduction which persists through ordinary retry paths.
def _cut_at(start):
    cap = None

    # Keep a fixed unit ceiling until the actual reset, leaving event ownership intact.
    def hook(context):
        nonlocal cap
        if context.rebalanced:
            cap = None
        if context.t == start:
            cap = float(context.held_units[0]) / 2
        if cap is None:
            return None
        units = context.incumbent_units.copy()
        units[0] = min(units[0], cap)
        return ResearchOrder(units, (context.symbols[0],), {"cut": True})

    return hook


# An action fork must equal inserting that same action into the whole teacher history.
@pytest.mark.parametrize("start", [5, 11, 15, 19])
def test_intervention_fork_equals_full_prefix(start):
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    prepared = simulate.prepare_research(report, **options)
    checkpoints = []
    simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_capture=checkpoints.append,
        **options,
    )
    stop = start + 20
    resumed = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_resume=checkpoints[start],
        research_stop=stop,
        research_hook=_cut_at(start),
        **options,
    )
    prefix = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_prepared=prepared,
        research_stop=stop,
        research_hook=_cut_at(start),
        **options,
    )
    _same_tail(prefix, resumed, start)


# Forking uses cached market work, never recomputing full-history signals per candidate.
def test_resume_uses_market_cache_and_checkpoint_is_pickleable(monkeypatch):
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    prepared = simulate.prepare_research(report, **options)
    checkpoints = []
    simulate.run(
        report,
        allocator=allocate,
        research_prepared=prepared,
        research_capture=checkpoints.append,
        **options,
    )

    # Fail if a supposedly cheap continuation attempts expensive market preparation.
    def forbidden(*args, **kwargs):
        raise AssertionError("market preparation was repeated")

    monkeypatch.setattr(simulate, "_signals_for", forbidden)
    monkeypatch.setattr(simulate, "adjusted_open", forbidden)
    from backend.agents.trading.desk import entry

    monkeypatch.setattr(entry, "bollinger_z", forbidden)
    checkpoint = pickle.loads(pickle.dumps(checkpoints[5]))
    assert checkpoint.t == 5
    assert dict(checkpoint.opened) == dict(checkpoints[5].opened)
    result = simulate.run(
        report,
        allocator=allocate,
        research_prepared=prepared,
        research_resume=checkpoint,
        research_stop=25,
        **options,
    )
    assert len(result.equity) == 21


# Reject source/configuration changes instead of silently constructing a different fork.
@pytest.mark.parametrize(
    "change", ["cost", "allocator", "rebalance", "report", "writable"]
)
def test_incompatible_resume_is_refused(change):
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    prepared = simulate.prepare_research(report, **options)
    checkpoints = []
    simulate.run(
        report,
        allocator=allocate,
        research_prepared=prepared,
        research_capture=checkpoints.append,
        **options,
    )
    extra = dict(allocator=allocate, cost_bps=10)
    if change == "cost":
        extra["cost_bps"] = 25
    elif change == "allocator":
        extra["allocator"] = policy_v4.allocator(mask)
    elif change == "rebalance":
        options["rebalance"] = 5
    elif change == "report":
        report, _, _ = _source()
    else:
        report.panel.close.setflags(write=True)
    with pytest.raises(ValueError, match="differs|different|changed|writable"):
        simulate.run(
            report,
            research_prepared=prepared,
            research_resume=checkpoints[5],
            research_stop=25,
            **extra,
            **options,
        )


# Full observed runs still emit independently verifiable unchanged cash/fill journals.
def test_full_hook_journal_verifies_and_bounded_journal_is_refused():
    report, mask, options = _source()
    allocate = policy_v4.allocator(mask)
    journal = ResearchJournal(
        report.panel.dates,
        report.panel.tickers,
        simulate.adjusted_open(report.panel),
        report.panel.adj_close,
        run_id="resume-test",
        account_id="synthetic",
        policy_id="synthetic-cut",
        cost_bps=25,
        provenance={"synthetic": True},
    )
    result = simulate.run(
        report,
        allocator=allocate,
        cost_bps=25,
        research_hook=_cut_at(5),
        journal=journal,
        **options,
    )
    proof = verify_snapshot(journal.snapshot())
    assert proof["ok"], proof["errors"]
    np.testing.assert_allclose([m["nav"] for m in proof["marks"]], result.equity)
    decisions = [e for e in journal.snapshot()["events"] if e["type"] == "decision"]
    assert any(d["metadata"].get("research_order") == {"cut": True} for d in decisions)
    with pytest.raises(ValueError, match="cannot attach a journal"):
        simulate.run(
            report, allocator=allocate, research_stop=20, journal=journal, **options
        )


# A callback never receives mutable live account arrays and cannot emit bad units.
@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_bad_research_order_is_refused(bad):
    report, mask, options = _source()

    # Supply a deliberately malformed unit proposal at the first ordinary decision.
    def hook(context):
        units = context.incumbent_units.copy()
        units[0] = bad
        return ResearchOrder(units)

    with pytest.raises(ValueError, match="finite and nonnegative"):
        simulate.run(
            report, allocator=policy_v4.allocator(mask), research_hook=hook, **options
        )


# A changed source array identity is refused even when dimensions happen to match.
def test_replaced_price_source_is_refused():
    report, mask, options = _source()
    prepared = simulate.prepare_research(report, **options)
    report.panel = replace(report.panel, close=report.panel.close.copy())
    with pytest.raises(ValueError, match="source changed"):
        simulate.run(
            report,
            allocator=policy_v4.allocator(mask),
            research_prepared=prepared,
            **options,
        )
