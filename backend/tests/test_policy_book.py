"""The account-faithful simulator behind the backtest, the charts and the live rule."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import grade_led_leader_policy as leader
from backend.market import policy_book as pb

TICKERS = ("XXX", "YYY", "ZZZ", "SPY")


def _days(n, start=date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _market(T=160, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(rng.normal(0.0005, 0.015, size=(T, len(TICKERS))).cumsum(axis=0))
    open_ = close * (1 + rng.normal(0, 0.003, size=close.shape))
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    band = np.zeros((T, len(TICKERS)), dtype=bool)
    return _days(T), open_, close, grades, band


def _run(grades, band=None, rule=None, T=160, seed=1, **kw):
    dates, open_, close, _, zero = _market(T, seed)
    return pb.simulate(
        dates, TICKERS, "SPY", open_, close, close.copy(), grades,
        zero if band is None else band, rule or pb.Rule(fomc=False), **kw
    )


# The defaults are the installed rule, so the backtest is the live policy.
def test_rule_defaults_are_the_installed_policy():
    rule = pb.Rule()
    policy = leader.GradeLedLeaderFundedPolicy
    assert rule.entry_grade == policy.entry_grade == 2
    assert rule.hold_grade == policy.minimum_held_grade == 1
    assert rule.min_trade == policy.min_trade
    assert (rule.floor, rule.target) == (leader.EXPOSURE_FLOOR, leader.TARGET)


# A name is sizable from its first full window, and never an index or the benchmark.
def test_sizable_starts_at_the_full_window():
    _, _, close, _, _ = _market()
    close[:10, 0] = np.nan
    mask = pb.sizable(close, TICKERS, "SPY")
    assert not mask[: 10 + leader.WINDOW, 0].any() and mask[10 + leader.WINDOW :, 0].all()
    assert mask[leader.WINDOW :, 1].all() and not mask[leader.WINDOW - 1, 1]
    assert not mask[:, 3].any()


# Bought when graded A, kept while B, sold at C; a name only ever B is never bought.
def test_entry_at_a_hold_at_b():
    T = 160
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[80:91, 0] = 2
    grades[91:101, 0] = 1
    grades[:, 1] = 1
    book = _run(grades)
    x = [t for t in book.trades if t["ticker"] == "XXX"]
    assert x[0]["action"] == "BUY" and x[0]["decided"] == book.dates[80]
    assert x[0]["date"] == book.dates[81]
    assert (book.weights[81:102, 0] > 0).all() and (book.weights[102:, 0] == 0).all()
    assert x[-1]["action"] == "SELL" and x[-1]["decided"] == book.dates[101]
    assert not [t for t in book.trades if t["ticker"] == "YYY"]
    # Under the old B rule the B name is bought.
    old = _run(grades, rule=pb.Rule(fomc=False, entry_grade=1, hold_grade=1, min_trade=0))
    assert [t for t in old.trades if t["ticker"] == "YYY"]


# Whole shares, never more than the book, and every fill the session after its decision.
def test_fills_are_whole_shares_within_the_book():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    book = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    assert book.trades
    for trade in book.trades:
        assert trade["shares"] == int(trade["shares"]) and trade["shares"] > 0
        assert book.dates.index(trade["date"]) == book.dates.index(trade["decided"]) + 1
    assert (book.weights.sum(axis=1) <= 1 + 1e-9).all()


# A resize under the minimum trade is not traded; an exit always is.
def test_min_trade_skips_small_resizes_not_exits():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    grades[120:, 2] = 0
    every = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    banded = _run(grades, rule=pb.Rule(fomc=False, min_trade=0.01))
    assert len(banded.trades) < len(every.trades)
    exits = [t for t in banded.trades if t["ticker"] == "ZZZ" and t["action"] == "SELL"]
    assert exits and exits[-1]["target"] == 0
    for trade in banded.trades:
        if trade["target"] > 0 and trade["before"] > 0:
            assert trade["size"] >= 0.01 * 0.9


# Buys are funded from the cash on hand before the day's sells (the funded
# planner never spends same-day proceeds): on every session, what the buys
# cost with fees is within the cash the account opened the session with.
def test_buys_never_spend_same_day_sale_proceeds():
    T = 160
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[64:100, :3] = 2
    grades[100:, 0] = 2
    grades[110:, 1:3] = 2
    book = _run(grades, rule=pb.Rule(fomc=False, min_trade=0))
    cost = pb.Rule().cost_bps / 1e4
    for t, day in enumerate(book.dates):
        buys = [x for x in book.trades if x["date"] == day and x["action"] == "BUY"]
        if not buys:
            continue
        spent = sum(x["shares"] * x["price"] for x in buys) * (1 + cost)
        assert spent <= book.cash_before[t] + 1e-6
    assert np.nanmin(book.cash) >= -1e-6


# The FOMC cycle: half of each holding sold at the next open after the first
# reduced close, nothing else traded through the lead-in, the baseline bought
# back at the decision session's close, the ordinary plan that night.
def test_fomc_cycle_matches_the_live_state_machine(monkeypatch):
    T = 160
    dates, open_, close, _, band = _market(T)
    grades = np.zeros((T, len(TICKERS)), dtype=int)
    grades[:, :3] = 2
    factor = np.ones(T)
    factor[120:124] = 0.5
    decision = date.fromisoformat(dates[124])
    monkeypatch.setattr(pb.event_risk, "live_path", lambda panel: factor)
    monkeypatch.setattr(pb, "fomc_decisions", lambda: [decision])
    book = pb.simulate(dates, TICKERS, "SPY", open_, close, close.copy(), grades, band,
                       pb.Rule(min_trade=0))
    cuts = [t for t in book.trades if t.get("reason") == "fomc_reduction"]
    back = [t for t in book.trades if t.get("reason") == "fomc_restoration_decision_close"]
    assert cuts and {t["decided"] for t in cuts} == {dates[120]}
    assert {t["date"] for t in cuts} == {dates[121]}
    assert back and {t["date"] for t in back} == {dates[124]}
    assert all(t["timing"] == "decision_close" for t in back)
    between = [t for t in book.trades if dates[121] < t["date"] < dates[124]]
    assert between == []
    for cut in cuts:
        restored = next(t for t in back if t["ticker"] == cut["ticker"])
        assert restored["shares"] == cut["shares"]
    after = [t for t in book.trades if t["decided"] == dates[124] and not t.get("reason")]
    assert all(t["date"] == dates[125] for t in after)


# Tonight's plan after the last close is reported for the chart's current call.
def test_tonights_plan_is_reported():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    book = _run(grades)
    assert book.planned is not None and book.planned.shape == (len(TICKERS),)
    assert book.planned[3] == 0 and book.planned[:3].sum() == pytest.approx(
        book.planned.sum()
    )


# A research universe narrower than the desk: a name outside it is never sized.
def test_eligible_mask_excludes_names():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    eligible = np.ones((160, len(TICKERS)), dtype=bool)
    eligible[:, 1] = False
    book = _run(grades, eligible=eligible)
    assert not [t for t in book.trades if t["ticker"] == "YYY"]
    assert [t for t in book.trades if t["ticker"] == "XXX"]


# A held name that leaves the research universe is sold at the next open; it
# does not freeze the rest of the book.
def test_leaving_the_universe_sells_without_freezing():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    eligible = np.ones((160, len(TICKERS)), dtype=bool)
    eligible[120:, 0] = False
    book = _run(grades, eligible=eligible, rule=pb.Rule(fomc=False, min_trade=0))
    assert (book.weights[122:, 0] == 0).all()
    later = [t for t in book.trades if t["decided"] > book.dates[121] and t["ticker"] != "XXX"]
    assert later


# The chase guard defers an unheld name that has already run more than the
# threshold; a held name is never deferred.
def test_chase_guard_defers_only_unheld_hot_names():
    window = leader.WINDOW
    adj = np.full((window + 1, 3), 100.0)
    adj[:, 0] = np.linspace(100, 200, window + 1)
    adj[:, 1] = np.linspace(100, 110, window + 1)
    adj[:, 2] = np.linspace(100, 200, window + 1)
    shares = np.array([0, 0, 10])
    defer = pb.chase_defer(adj, shares, window, threshold=0.25)
    assert defer.tolist() == [True, False, False]


# The guard reads only closes on or before the decision session.
def test_chase_guard_reads_only_past_closes():
    window = leader.WINDOW
    adj = np.full((window + 20, 2), 100.0)
    adj[:, 0] = np.linspace(100, 200, window + 20)
    shares = np.zeros(2)
    t = window + 10
    before = pb.chase_defer(adj, shares, t, threshold=0.25)
    changed = adj.copy()
    changed[t + 1 :] *= 10.0
    after = pb.chase_defer(changed, shares, t, threshold=0.25)
    assert np.array_equal(before, after)
    changed[t, 0] = 50.0
    moved = pb.chase_defer(changed, shares, t, threshold=0.25)
    assert moved[0] != before[0]


# The random placebo defers exactly the guard's count, drawn from entering names.
def test_random_deferral_defers_the_guard_count():
    window = leader.WINDOW
    adj = np.full((window + 1, 3), 100.0)
    adj[:, 0] = np.linspace(100, 200, window + 1)
    adj[:, 1] = np.linspace(100, 110, window + 1)
    adj[:, 2] = np.linspace(100, 300, window + 1)
    mask = np.ones(3, dtype=bool)
    grades = np.full(3, 2, dtype=int)
    shares = np.zeros(3)
    below = np.zeros(3, dtype=int)
    band = np.zeros(3, dtype=bool)
    held = np.zeros(3)
    unguarded = pb._ordinary(
        pb.Rule(fomc=False), mask, grades, below, shares, band, adj, window, held
    )
    guard = pb._ordinary(
        pb.Rule(fomc=False, chase=0.25),
        mask, grades, below, shares, band, adj, window, held,
    )
    rng = np.random.default_rng(7)
    random_target = pb._ordinary(
        pb.Rule(fomc=False, chase=0.25, chase_random=7),
        mask, grades, below, shares, band, adj, window, held, rng=rng,
    )
    entering = set(np.flatnonzero(unguarded > 0))
    hot = set(np.flatnonzero(guard == 0))
    zeroed = set(np.flatnonzero(random_target == 0))
    assert hot == {0, 2}
    assert len(zeroed) == len(hot)
    assert zeroed <= entering


# The guard is off by default: the installed book is reproduced exactly.
def test_chase_off_reproduces_the_installed_book():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    base = _run(grades)
    off = _run(grades, rule=pb.Rule(fomc=False, chase=None))
    assert np.array_equal(base.equity, off.equity, equal_nan=True)
    assert np.array_equal(base.weights, off.weights)
    assert base.trades == off.trades


# The all-defer null never enters a name.
def test_all_defer_guard_never_enters():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    book = _run(grades, rule=pb.Rule(fomc=False, chase=-1.0))
    assert not [t for t in book.trades if t["action"] == "BUY"]


# A random placebo without a threshold is a configuration error, not a silent
# no-op.
def test_chase_random_requires_chase():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    with pytest.raises(ValueError):
        _run(grades, rule=pb.Rule(fomc=False, chase_random=1))


# The sector cap's four labels: two IT, one Industrial, the benchmark blank.
SECTOR = np.array(
    ["Information Technology", "Information Technology", "Industrials", ""]
)


# The cap scales the sector group down to the cap; the freed weight stays cash
# and a name outside the sector keeps its leader slot.
def test_sector_cap_scales_the_group_and_leaves_cash():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    rule = pb.Rule(fomc=False, min_trade=0, target=10.0, floor=1.0, sector_cap=0.4)
    book = _run(grades, rule=rule, sector=SECTOR)
    late = book.weights[150, :3]
    assert late[:2].sum() <= 0.4 + 1e-6
    assert late[2] > 0
    assert late.sum() < 0.75 - 1e-6


# The new parameter is off by default and at unit capital: both reproduce the
# installed book exactly, with or without labels.
def test_sector_cap_off_and_one_reproduce_the_installed_book():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    base = _run(grades)
    off = _run(grades, rule=pb.Rule(fomc=False, sector_cap=None), sector=SECTOR)
    one = _run(grades, rule=pb.Rule(fomc=False, sector_cap=1.0), sector=SECTOR)
    for book in (off, one):
        assert np.array_equal(base.equity, book.equity, equal_nan=True)
        assert np.array_equal(base.weights, book.weights)
        assert base.trades == book.trades


# A zero cap holds no unprotected sector name once the cap applies; a name
# outside the sector is still sized.
def test_zero_sector_cap_holds_no_sector_name():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    rule = pb.Rule(fomc=False, min_trade=0, target=10.0, floor=1.0, sector_cap=0.0)
    book = _run(grades, rule=rule, sector=SECTOR)
    assert book.weights[150, :2].sum() == 0
    assert book.weights[150, 2] > 0


# The placebo removes the same weight as the cap but from a random subset, and
# a fixed seed makes it deterministic.
def test_sector_placebo_removes_the_cap_weight():
    target = np.array([0.3, 0.3, 0.2, 0.1])
    protected = np.zeros(4, dtype=bool)
    rule = pb.Rule(sector_cap=0.4)
    capped = pb.cap_sector_target(rule, target, SECTOR, protected)
    first = pb.cap_sector_target(
        rule, target, SECTOR, protected, np.random.default_rng(7)
    )
    second = pb.cap_sector_target(
        rule, target, SECTOR, protected, np.random.default_rng(7)
    )
    assert target.sum() - capped.sum() == pytest.approx(target.sum() - first.sum())
    assert np.array_equal(first, second)
    assert not np.array_equal(capped, first)


# The cap reads only closes on or before the decision session: changing every
# close after the cutoff leaves the book and its early trades unchanged.
def test_sector_cap_reads_only_past_closes():
    sessions = 160
    dates, open_, close, grades, band = _market(sessions)
    grades[:, :3] = 2
    rule = pb.Rule(fomc=False, min_trade=0, target=10.0, floor=1.0, sector_cap=0.4)
    base = pb.simulate(
        dates, TICKERS, "SPY", open_, close, close.copy(), grades, band, rule,
        sector=SECTOR,
    )
    changed = close.copy()
    changed[120:] *= 10.0
    moved = pb.simulate(
        dates, TICKERS, "SPY", open_, changed, changed.copy(), grades, band, rule,
        sector=SECTOR,
    )
    assert np.array_equal(base.weights[:120], moved.weights[:120])
    early = [
        trade for trade in base.trades if base.dates.index(trade["decided"]) < 118
    ]
    later = [
        trade for trade in moved.trades if moved.dates.index(trade["decided"]) < 118
    ]
    assert early == later


# A cap without labels, and a placebo without a cap, are configuration errors.
def test_sector_cap_configuration_errors():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    with pytest.raises(ValueError, match="sector_cap requires"):
        _run(grades, rule=pb.Rule(fomc=False, sector_cap=0.5))
    with pytest.raises(ValueError, match="sector_random requires"):
        _run(grades, rule=pb.Rule(fomc=False, sector_random=1))


# The earnings overlay blocks a flagged unheld name, trims a flagged held name
# by the factor, leaves an unflagged name alone and never touches a protected
# holding. The freed weight stays cash.
def test_earnings_overlay_trims_held_and_blocks_entries():
    target = np.array([0.3, 0.2, 0.1, 0.1])
    shares = np.array([10, 0, 5, 0])
    protected = np.zeros(4, dtype=bool)
    flags = np.array([True, True, False, True])
    rule = pb.Rule(earnings_trim=0.5, earnings_blackout=True)
    out = pb.trim_earnings_target(rule, target, flags, shares, protected)
    assert out[0] == pytest.approx(0.15)  # held, flagged: trimmed
    assert out[1] == 0.0  # unheld, flagged: blocked
    assert out[2] == pytest.approx(0.1)  # unflagged: unchanged
    assert out[3] == 0.0  # unheld, flagged: blocked
    assert out.sum() < target.sum() - 1e-9  # freed weight is cash, not moved


# A protected holding is kept at its weight even when its name is flagged.
def test_earnings_overlay_leaves_a_protected_holding():
    target = np.array([0.3, 0.2, 0.1, 0.1])
    shares = np.array([10, 0, 5, 0])
    protected = np.array([True, False, False, False])
    flags = np.ones(4, dtype=bool)
    rule = pb.Rule(earnings_trim=0.5, earnings_blackout=True)
    out = pb.trim_earnings_target(rule, target, flags, shares, protected)
    assert out[0] == pytest.approx(0.3)
    assert out[1] == 0.0
    assert out[2] == pytest.approx(0.05)


# Off, trim=1 and an all-False flag matrix reproduce the installed book exactly.
def test_earnings_overlay_off_and_one_reproduce_the_installed_book():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    grades[:, 3] = 0
    flags = np.ones((160, len(TICKERS)), dtype=bool)
    base = _run(grades)
    off = _run(grades, rule=pb.Rule(fomc=False), earnings=flags)
    one = _run(
        grades,
        rule=pb.Rule(fomc=False, earnings_trim=1.0, earnings_blackout=False),
        earnings=flags,
    )
    silent = _run(
        grades,
        rule=pb.Rule(fomc=False, earnings_trim=0.5, earnings_blackout=True),
        earnings=np.zeros((160, len(TICKERS)), dtype=bool),
    )
    for book in (off, one, silent):
        assert np.array_equal(base.equity, book.equity, equal_nan=True)
        assert np.array_equal(base.weights, book.weights)
        assert base.trades == book.trades


# The placebo removes the overlay's total removed weight from a random subset,
# and a fixed seed makes it deterministic.
def test_earnings_placebo_removes_the_overlay_weight():
    target = np.array([0.3, 0.3, 0.2, 0.1])
    shares = np.full(4, 10)
    protected = np.zeros(4, dtype=bool)
    flags = np.array([True, True, False, False])
    rule = pb.Rule(earnings_trim=0.5, earnings_blackout=False)
    trimmed = pb.trim_earnings_target(rule, target, flags, shares, protected)
    first = pb.trim_earnings_target(
        rule, target, flags, shares, protected, np.random.default_rng(7)
    )
    second = pb.trim_earnings_target(
        rule, target, flags, shares, protected, np.random.default_rng(7)
    )
    assert target.sum() - trimmed.sum() == pytest.approx(target.sum() - first.sum())
    assert np.array_equal(first, second)
    assert not np.array_equal(trimmed, first)


# The overlay reads only closes on or before the decision session: changing
# every close after the cutoff leaves the book and its early trades unchanged.
def test_earnings_overlay_reads_only_past_closes():
    sessions = 160
    dates, open_, close, grades, band = _market(sessions)
    grades[:, :3] = 2
    flags = np.ones((sessions, len(TICKERS)), dtype=bool)
    rule = pb.Rule(fomc=False, min_trade=0, earnings_trim=0.5, earnings_blackout=True)
    base = pb.simulate(
        dates, TICKERS, "SPY", open_, close, close.copy(), grades, band, rule,
        earnings=flags,
    )
    changed = close.copy()
    changed[120:] *= 10.0
    moved = pb.simulate(
        dates, TICKERS, "SPY", open_, changed, changed.copy(), grades, band, rule,
        earnings=flags,
    )
    assert np.array_equal(base.weights[:120], moved.weights[:120])
    early = [
        trade for trade in base.trades if base.dates.index(trade["decided"]) < 118
    ]
    later = [
        trade for trade in moved.trades if moved.dates.index(trade["decided"]) < 118
    ]
    assert early == later


# An overlay without flags, a placebo without an overlay, a trim outside the
# unit interval and a flag matrix of the wrong shape are configuration errors.
def test_earnings_overlay_configuration_errors():
    grades = np.full((160, len(TICKERS)), 2, dtype=int)
    flags = np.zeros((160, len(TICKERS)), dtype=bool)
    with pytest.raises(ValueError, match="earnings_trim"):
        _run(grades, rule=pb.Rule(fomc=False, earnings_trim=1.5), earnings=flags)
    with pytest.raises(ValueError, match="earnings_random requires"):
        _run(grades, rule=pb.Rule(fomc=False, earnings_random=1))
    with pytest.raises(ValueError, match="requires one flag"):
        _run(grades, rule=pb.Rule(fomc=False, earnings_trim=0.5))
    with pytest.raises(ValueError, match="One earnings flag"):
        _run(grades, rule=pb.Rule(fomc=False, earnings_trim=0.5), earnings=flags[:80])
