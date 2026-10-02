"""The paper planner on the account's real books of 2026-10-01 and 2026-10-02.

The fixture is the live paper account as it stood when the operator reported
that it "doesn't know when to buy and sell properly": the positions, cash and
equity the 10-01 nightly planned from (`paper/state.json` history) and the
account at 16:41 ET on 10-02 (an Alpaca paper GET), the 2026-10-01 record's
targets (`graded-equal-weight/5`, eleven names at 1/11), the grades and the
10-01 closes the plan was sized at, and the state's rebalance clock. The
investigation is `docs/NEXT_SESSION.md` (2026-10-02, paper target tracking).

What these pin is the executor's half of the promise: the cash on hand beyond
the buffer goes to the names under their targets, in whole shares, as the
promoted simulation spends it - not floored away a leg at a time. The names
above their targets (NTAP, SMCI) are left alone between resets by the policy
itself, which the simulation does too; that is measured, not a defect here.
"""

import json
import math
from pathlib import Path

import pytest

from backend.agents.trading.desk import paper, simulate

FIXTURE = Path(__file__).parent / "fixtures" / "paper_target_tracking_2026-10.json"


# The fixture's two sessions, read once.
@pytest.fixture(scope="module")
def books() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# One session's inputs from the fixture, as `market_daily._paper_trade` passes
# them: the names graded below A that the book holds are the rotation's.
def _inputs(book: dict) -> dict:
    grades = book["grades"]
    held = {s: float(q) for s, q in book["held"].items() if float(q) > 0}
    finished = {
        s: f"graded {grades.get(s)}; the desk wants the money elsewhere"
        for s in held
        if grades.get(s) not in paper.ENTRY_MIN_GRADE
    }
    return {
        "session": book["session"],
        "equity": float(book["equity"]),
        "cash": float(book["cash"]),
        "held": held,
        "prices": {s: float(p) for s, p in book["prices"].items()},
        "targets": {s: float(w) for s, w in book["targets"].items()},
        "grades": grades,
        "finished": finished,
        "entries": {s: float(b) for s, b in book["entries"].items()},
        "blocked": set(book["blocked"]),
    }


# The paper state the session planned from: the real rebalance clock, the
# reset's targets and policy stamp, and nothing pending or deferred.
def _state(book: dict) -> paper.PaperState:
    return paper.PaperState(**book["state"])


# Plan the session on the fixture's account; return (orders, state, what, inputs).
def _plan(book: dict, **override):
    x = {**_inputs(book), **override}
    orders, new, what = paper.plan(
        x["session"],
        _state(book),
        x["equity"],
        x["held"],
        x["prices"],
        x["targets"],
        x["grades"],
        finished=x["finished"],
        entry_blocked=x["blocked"],
        entries=x["entries"],
        cash=x["cash"],
    )
    return orders, new, what, x


# The book once the plan has filled at its decision prices: shares per name and
# the cash, with sells' proceeds credited (they arrive at the close).
def _after(orders, x) -> tuple[dict[str, float], float, float]:
    held = dict(x["held"])
    buys = sells = 0.0
    for o in orders:
        value = o.qty * x["prices"][o.symbol]
        if o.side == "buy":
            held[o.symbol] = held.get(o.symbol, 0.0) + o.qty
            buys += value
        else:
            held[o.symbol] = held.get(o.symbol, 0.0) - o.qty
            sells += value
    return held, buys, sells


# The names the policy wants tonight that the redeploy may fill: under target,
# graded A or better, not rotating out, and held, bought tonight, or graded in
# since the reset - the simulator's taker set.
def _takers(x, at_rebalance, orders) -> set[str]:
    bought = {o.symbol for o in orders if o.side == "buy"}
    out = set()
    for s, w in x["targets"].items():
        if s in x["finished"] or x["grades"].get(s) not in paper.ENTRY_MIN_GRADE:
            continue
        held = x["held"].get(s, 0.0) > 0 or s in bought
        new = float(at_rebalance.get(s, 0.0)) <= 0
        if (held or new) and x["held"].get(s, 0.0) * x["prices"][s] < w * x["equity"]:
            out.add(s)
    return out


# Tonight's account (10-02 at the close): 30% cash, eleven names held. After the
# plan the cash beyond the buffer is in the under-target names, to within one
# share of what the simulator's dollars would buy, and the book is invested at
# the target gross the cash allows - every name the policy wants, held at or
# under its target, plus the overweights the policy holds until its reset.
def test_tonight_puts_the_idle_cash_to_work_up_to_the_target_gross(books):
    book = books["2026-10-02"]
    orders, new, what, x = _plan(book)
    equity, cash = x["equity"], x["cash"]
    assert cash / equity > 0.29  # the 30% the operator saw
    held, buys, sells = _after(orders, x)
    left = cash - buys
    buffer = paper.REDEPLOY_BUFFER * equity
    assert left >= buffer - 1e-6  # the buffer is kept
    redeploy = [o for o in orders if o.kind == paper.REDEPLOY_KIND]
    assert redeploy
    # What the simulator's leg spends on the same inputs, in dollars.
    sim = simulate._redeploy_orders(
        [o for o in orders if o.kind != paper.REDEPLOY_KIND],
        x["held"],
        x["prices"],
        equity,
        x["grades"],
        x["finished"],
        x["targets"],
        book["state"]["rebalance_targets"],
        cash,
        simulate.REDEPLOY_BUFFER,
        x["session"],
        paper.PaperState(),
    )
    sim_dollars = sum(o.qty * x["prices"][o.symbol] for o in sim)
    live_dollars = sum(o.qty * x["prices"][o.symbol] for o in redeploy)
    priciest = max(x["prices"][o.symbol] for o in sim)
    assert sim_dollars - priciest < live_dollars <= sim_dollars + 1e-6
    invested = sum(q * x["prices"][s] for s, q in held.items() if q > 0) / equity
    # 1 less the buffer, the rotation's proceeds still to arrive at the close,
    # and under a share of the dearest name: the gross the cash allows.
    floor = 1.0 - paper.REDEPLOY_BUFFER - sells / equity - priciest / equity
    assert invested >= floor
    assert invested > 0.93
    # No name is pushed past its target by tonight's buys.
    for o in redeploy:
        weight = held[o.symbol] * x["prices"][o.symbol] / equity
        assert weight <= x["targets"][o.symbol] + 1e-9, o.symbol


# No name the policy wants under its target is passed over because its share
# price exceeds its pro-rata dollars: every name the simulator's redeploy
# gives a leg gets one live, unless a single share would carry it past its
# target, and what is left of the simulator's dollars cannot buy one more
# share of any leg still short of its own. MU at 1,097 a share was floored
# to nothing by /5 on 10-01 against a 767 slice.
def test_no_target_is_ignored_because_a_share_costs_more_than_its_slice(books):
    for day in ("2026-10-01", "2026-10-02"):
        book = books[day]
        orders, _new, _what, x = _plan(book)
        others = [o for o in orders if o.kind != paper.REDEPLOY_KIND]
        sim = simulate._redeploy_orders(
            others,
            x["held"],
            x["prices"],
            x["equity"],
            x["grades"],
            x["finished"],
            x["targets"],
            book["state"]["rebalance_targets"],
            x["cash"],
            simulate.REDEPLOY_BUFFER,
            x["session"],
            paper.PaperState(),
        )
        sim_by = {o.symbol: o.qty * x["prices"][o.symbol] for o in sim}
        live = {o.symbol: o.qty for o in orders if o.kind == paper.REDEPLOY_KIND}
        held, _, _ = _after(others, x)
        for s in sim_by:
            room = x["targets"][s] * x["equity"] - held.get(s, 0.0) * x["prices"][s]
            assert s in live or x["prices"][s] > room, (day, s)
        left = sum(sim_by.values()) - sum(q * x["prices"][s] for s, q in live.items())
        for s, dollars in sim_by.items():
            if live.get(s, 0) * x["prices"][s] < dollars:
                assert x["prices"][s] > left + 1e-6, (day, s, left)
    # Tonight every under-target name the policy holds or wants gets a leg.
    book = books["2026-10-02"]
    orders, _new, _what, x = _plan(book)
    bought = {o.symbol for o in orders if o.kind == paper.REDEPLOY_KIND}
    takers = _takers(x, book["state"]["rebalance_targets"], orders)
    assert (
        takers
        == bought
        == {
            "ALAB",
            "HPE",
            "INTC",
            "MU",
            "SIMO",
            "SNDK",
            "STX",
            "SWKS",
        }
    )


# Every order is a whole number of shares; the buys together fit inside the
# cash on hand (the broker's buying power on this account is at least its
# cash), and no sell asks for more shares than are held.
def test_quantities_are_whole_shares_within_cash_and_holdings(books):
    for day in ("2026-10-01", "2026-10-02"):
        orders, _new, _what, x = _plan(books[day])
        assert orders, day
        for o in orders:
            assert isinstance(o.qty, int), (day, o)
            assert o.qty > 0, (day, o)
            if o.side == "sell":
                assert o.qty <= x["held"].get(o.symbol, 0.0), (day, o)
        buys = sum(o.qty * x["prices"][o.symbol] for o in orders if o.side == "buy")
        assert buys <= x["cash"] + 1e-6, day


# The 10-01 replay reproduces the plan the account actually sent that night
# (sells AAOI 127, ANET 18, LITE 4; rotation buys HPE 31, SWKS 21, MDB 7,
# STX 1; redeploy INTC 9, SIMO 4, ALAB 2 under /5), and /6 differs only in
# the redeploy: the simulator's 4,188 of dollars become INTC 10, SIMO 4,
# ALAB 2 and MU 1 (4,111) instead of /5's 2,894.
def test_the_10_01_plan_is_the_one_sent_with_the_redeploy_spent(books):
    book = books["2026-10-01"]
    orders, _new, what, x = _plan(book)
    assert what == "exits"
    rows = {(o.side, o.symbol, o.qty, o.kind) for o in orders}
    assert {r for r in rows if r[3] is None} == {
        ("sell", "AAOI", 127, None),
        ("sell", "ANET", 18, None),
        ("sell", "LITE", 4, None),
        ("buy", "HPE", 31, None),
        ("buy", "SWKS", 21, None),
        ("buy", "MDB", 7, None),
        ("buy", "STX", 1, None),
    }
    redeploy = {o.symbol: o.qty for o in orders if o.kind == paper.REDEPLOY_KIND}
    assert redeploy == {"INTC": 10, "SIMO": 4, "ALAB": 2, "MU": 1}
    others = [o for o in orders if o.kind != paper.REDEPLOY_KIND]
    floored = paper._redeploy_orders(
        others,
        x["held"],
        x["prices"],
        x["equity"],
        x["grades"],
        x["finished"],
        x["targets"],
        book["state"]["rebalance_targets"],
        x["cash"],
        paper.REDEPLOY_BUFFER,
        x["session"],
        paper.PaperState(),
        whole_shares=False,
    )
    sim_dollars = sum(o.qty * x["prices"][o.symbol] for o in floored)
    v5 = {
        o.symbol: math.floor(o.qty + 1e-10)
        for o in floored
        if math.floor(o.qty + 1e-10) > 0
    }
    assert v5 == {"INTC": 9, "SIMO": 4, "ALAB": 2}  # what the account sent
    spent = sum(q * x["prices"][s] for s, q in redeploy.items())
    old = sum(q * x["prices"][s] for s, q in v5.items())
    assert round(old) == 2_894
    assert round(sim_dollars) == 4_188
    assert round(spent) == 4_111
    assert spent <= sim_dollars + 1e-6


# A book already at its targets sends nothing: every wanted name held at the
# whole shares of its target weight and the rest in cash. Planning the same
# session twice sends nothing the second time either.
def test_nothing_changes_when_the_account_already_matches_its_targets(books):
    book = books["2026-10-02"]
    x = _inputs(book)
    equity = x["equity"]
    wanted = {
        s: w
        for s, w in x["targets"].items()
        if x["grades"].get(s) in paper.ENTRY_MIN_GRADE
    }
    held = {
        s: float(math.floor(w * equity / x["prices"][s])) for s, w in wanted.items()
    }
    cash = equity - sum(q * x["prices"][s] for s, q in held.items())
    targets = dict(wanted)
    orders, new, what, _ = _plan(
        book,
        held=held,
        cash=cash,
        targets=targets,
        finished={},
        entries={},
    )
    assert orders == []
    assert what == "hold"
    again, _, what2 = paper.plan(
        x["session"],
        new,
        equity,
        held,
        x["prices"],
        targets,
        x["grades"],
        finished={},
        entry_blocked=set(),
        entries={},
        cash=cash,
    )
    assert again == []
    assert what2 == "already planned for this session"


# The remainder fill on its own: floored legs first, then one share at a time
# to the leg with the largest unspent remainder, only while that leg is still
# short of its own dollars, never past its room, never past the total asked.
def test_whole_share_fill_spends_the_remainder_by_largest_shortfall():
    prices = {"CHEAP": 50.0, "MID": 400.0, "DEAR": 1_000.0}
    room = {"CHEAP": 5_000.0, "MID": 5_000.0, "DEAR": 5_000.0}
    wants = {"CHEAP": 700.0, "MID": 700.0, "DEAR": 900.0}
    # Floors: CHEAP 14 (700), MID 1 (400), DEAR 0; 1,200 left. DEAR's 900 is
    # the largest remainder and a share fits: 1 share, 200 left. MID's 300
    # remainder cannot buy a 400 share, CHEAP has none: done.
    assert paper._whole_share_fill(wants, room, prices) == {
        "CHEAP": 14,
        "MID": 1,
        "DEAR": 1,
    }
    # A share that would pass the name's room is never bought.
    tight = paper._whole_share_fill({"DEAR": 900.0}, {"DEAR": 950.0}, {"DEAR": 1_000.0})
    assert tight == {"DEAR": 0}
    # Nothing asked, nothing bought.
    assert paper._whole_share_fill({}, {}, {}) == {}
