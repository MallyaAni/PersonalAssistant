"""Differential parity of the comparison's incumbent price entry against production.

Independent synthetic acceptance, per `INCUMBENT_PARITY_TASK.md`. It runs the
real production helpers rather than replicas: the incumbent band is the same
``entry.bollinger_z`` over the developing-day live panel that
``live_technical.entry_now`` builds with ``with_live_row``, and the gate is the
same ``decision_view.entry_action`` (threshold, grade floor, rejecting band and
``paper`` name cap/size). The comparison's incumbent must equal that production
formula on the same causal inputs, and the fixed-reclaim candidate must keep
its own prior-20 mapping.

What has to hold: the comparison band equals the live read's band on raw and
adjusted scales; the band is dynamic (the developing intraday close is inside
the 20-observation window, not a frozen prior-day band); readiness crosses the
entry threshold exactly where ``entry_action`` does; the fixed candidate levels
stay on the prior-20 mapping while the incumbent moves; the rejecting-band gate
and the grade floor block both methods exactly as production refuses; raw and
adjusted economic paths agree; unknown or late eligibility blocks both. The
account-level boundaries the comparison cannot reach - live intraday grade
refresh, holdings/cash/name-cap at account level, and execution - are pinned as
divergences rather than approximated.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.agents.trading.desk.entry import bollinger_z
from backend.market import calendar, live_technical
from backend.market.decision_view import Action, entry_action
from backend.market.intraday_comparison import (
    ENTRY_READY,
    NOT_ELIGIBLE,
    WAIT,
    DailyRow,
    Eligibility,
    compare,
    fixed_levels,
    incumbent_band_z,
)
from backend.market.intraday_entry import (
    Bar,
    session_close_for,
    session_open_for,
)
from backend.market.live_technical import with_live_row
from backend.market.panel import Panel

SESSION = date(2026, 1, 6)
# The 20 prior sessions, deliberately supplied in reverse order so every helper
# must sort before using them, exactly as the comparison and the store do.
_, _EXCHANGE_SESSIONS = calendar.reviewed_sessions()
_PRIOR_DATES = (
    np.busday_offset(
        np.datetime64(SESSION), -np.arange(1, 31), busdaycal=_EXCHANGE_SESSIONS
    )
    .astype(object)
    .tolist()
)


# The standard 20-prior daily history: adjusted closes 100..119 rising in time,
# raw closes exactly double, so the adjustment ratio r = 119/238 = 0.5.
def _history() -> list[DailyRow]:
    """Return 20 prior DailyRows, adjusted 100..119 rising chronologically."""
    dates = sorted(_PRIOR_DATES[:20])
    rows = [
        DailyRow(date=d, close=2.0 * (100.0 + i), adj_close=100.0 + i)
        for i, d in enumerate(dates)
    ]
    return list(reversed(rows))


# One regular-session bar at `slot` (0 = 09:30, 1 = 09:45, ...) on SESSION.
def _bar(slot: int, o: float, h: float, lo: float, c: float) -> Bar:
    """Return a 15-minute Bar at the given slot and OHLC on SESSION."""
    start = session_open_for(SESSION) + timedelta(minutes=15 * slot)
    return Bar(start=start, open=o, high=h, low=lo, close=c, volume=100.0)


# The instant a bar's 15-minute window has fully elapsed.
def _completed(slot: int) -> datetime:
    """Return the New York instant the slot's window has elapsed."""
    return session_open_for(SESSION) + timedelta(minutes=15 * (slot + 1))


# The reclaim path: hold above the level, pull back to a setup, reclaim.
def _reclaim_bars(close2: float) -> list[Bar]:
    """Return a path that breaks the level then reclaims with bar 2 closing close2."""
    return [
        _bar(0, 260.0, 262.0, 258.0, 260.0),
        _bar(1, 260.0, 260.0, 238.0, 240.0),
        _bar(2, close2, close2 + 1.0, close2 - 1.0, close2),
    ]


# The standard eligibility: grade A, not rejecting, known at the session open.
def _eligibility(
    grade: str | None = "A",
    rejecting_band: bool | None = False,
    grade_at: datetime | None = None,
    rejecting_at: datetime | None = None,
) -> Eligibility:
    """Return an Eligibility known by the session open unless overridden."""
    return Eligibility(
        grade=grade,
        grade_available_at=grade_at or session_open_for(SESSION),
        rejecting_band=rejecting_band,
        rejecting_band_available_at=rejecting_at or session_open_for(SESSION),
    )


# The production live panel: the stored daily history with today's row appended
# by the real `with_live_row` at the supplied raw live price, so the same
# causal inputs the comparison sees drive the production read.
def _live_panel(observed_close: float, history: list[DailyRow] | None = None) -> Panel:
    """Return the production live panel for the priors plus one developing row."""
    rows = _history() if history is None else history
    rows = sorted((r for r in rows if r.date < SESSION), key=lambda r: r.date)
    n = len(rows)
    close = np.array([[r.close] for r in rows])
    adj = np.array([[r.adj_close] for r in rows])
    prior = Panel(
        dates=np.array([np.datetime64(r.date, "D") for r in rows]),
        tickers=("AAA",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=adj,
        volume=np.full((n, 1), 1000.0),
        themes={"AAA": ()},
        benchmark="AAA",
    )
    quote = SimpleNamespace(
        last=observed_close,
        open=observed_close,
        high=observed_close + 1.0,
        low=observed_close - 1.0,
        bar="x",
    )
    return with_live_row(prior, {"AAA": quote}, SESSION)


# The real production entry read at one raw live price: `entry_now` is called
# unchanged with only the store read supplied, the same pattern the API and the
# live_technical tests use, so `entries` and `bollinger_z` are the real callees.
def _production_band(observed_close: float, panel: Panel | None = None) -> float:
    """Return the production live read's band_z for AAA at observed_close."""
    live = _live_panel(observed_close) if panel is None else panel
    original = live_technical._live_read
    live_technical._live_read = lambda store, quotes, today: {
        "panel": live,
        "ai_trend": np.zeros(live.dates.shape[0]),
    }
    try:
        out = live_technical.entry_now(
            None, {"AAA": SimpleNamespace(last=observed_close, bar="x")}, SESSION
        )
    finally:
        live_technical._live_read = original
    assert out["AAA"]["band_z"] is not None
    return out["AAA"]["band_z"]


# The comparison's incumbent band and the production live read are the same
# causal series: the same 19 priors plus today's close converted by the same
# adjustment ratio, run through the same bollinger_z. This is the core parity
# claim, tested across the developing-day range on the raw scale.
@pytest.mark.parametrize("observed", [235.0, 240.0, 245.0, 248.64, 250.0, 260.0])
def test_incumbent_band_equals_the_live_technical_read(observed):
    comp = incumbent_band_z(_history(), SESSION, observed, price_basis="raw")
    prod = _production_band(observed)
    assert comp == pytest.approx(prod, abs=1e-12)


# The band is dynamic: the developing intraday close sits inside the 20-bar
# window, so the band moves with the close and is never a frozen prior-day band.
def test_developing_close_is_inside_the_band_not_a_frozen_prior_day():
    prior = sorted((r for r in _history() if r.date < SESSION), key=lambda r: r.date)
    frozen_series = np.array([r.adj_close for r in prior[-20:]], dtype=float).reshape(
        -1, 1
    )
    frozen_z = float(bollinger_z(frozen_series)[-1, 0])
    low = incumbent_band_z(_history(), SESSION, 245.0, price_basis="raw")
    high = incumbent_band_z(_history(), SESSION, 260.0, price_basis="raw")
    assert high > low
    assert low != pytest.approx(frozen_z)
    assert _production_band(260.0) > _production_band(245.0)
    # The exact construction the protocol requires: prior19 + observed*r.
    ratio = prior[-1].adj_close / prior[-1].close
    manual = float(
        bollinger_z(
            np.array([r.adj_close for r in prior[-19:]] + [260.0 * ratio]).reshape(
                -1, 1
            )
        )[-1, 0]
    )
    assert high == pytest.approx(manual)


# The reclaim candidate's levels, by contrast, stay on the prior-20 mapping and
# never see the developing close: the two methods deliberately differ in which
# daily observations are inside the rule.
def test_candidate_levels_are_the_frozen_prior_20_not_the_developing_day():
    context = fixed_levels(_history(), SESSION, price_basis="raw")
    adj = np.arange(20, dtype=float) + 100.0
    mean, std = float(adj.mean()), float(np.std(adj, ddof=0))
    assert context.observations == 20
    assert context.levels.level == pytest.approx((mean + 2 * std) / context.ratio)
    assert context.levels.entry_level == pytest.approx(
        (mean + 2 * std * paper.ENTRY_BAND_Z) / context.ratio
    )
    assert context.levels.invalidation_level == pytest.approx(mean / context.ratio)
    # The candidate levels do not move as the intraday session develops.
    early = compare(
        "AAA",
        SESSION,
        _reclaim_bars(245.0),
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    late = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        _eligibility(),
        _completed(3),
        price_basis="raw",
    )
    assert early.levels == late.levels == context.levels
    assert early.band_z != late.band_z


# Readiness crosses the entry threshold exactly where production entry_action
# crosses it: for every band reading across the threshold, the comparison's
# incumbent buy decision equals the real gate's buy decision.
@pytest.mark.parametrize(
    "observed", [240.0, 248.0, 248.29, 248.64, 248.99, 250.0, 255.0, 260.0]
)
def test_entry_threshold_readiness_matches_the_production_gate(observed):
    band = incumbent_band_z(_history(), SESSION, observed, price_basis="raw")
    result = entry_action({"rejecting_band": False}, band, "A", 0.0)
    expected = result is not None and result[0] == Action.BUY
    cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(observed),
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    assert cmp.incumbent.band_z == pytest.approx(band)
    assert cmp.incumbent.readiness is expected, observed
    if expected:
        assert cmp.incumbent.state == ENTRY_READY
    elif band is not None and band < paper.ENTRY_BAND_Z:
        assert cmp.incumbent.state == WAIT


# The exact threshold boundary of the production gate: band == ENTRY_BAND_Z
# fires and a band a hair below does not, and the comparison reads the same.
def test_threshold_equality_fires_and_just_below_does_not():
    at = entry_action({"rejecting_band": False}, paper.ENTRY_BAND_Z, "A", 0.0)
    below = entry_action({"rejecting_band": False}, paper.ENTRY_BAND_Z - 1e-9, "A", 0.0)
    assert at is not None
    assert at[0] == Action.BUY
    assert below is None
    # A close just over the boundary fires the comparison incumbent, just under
    # it does not (248.6416 is the raw close whose band is exactly the trigger).
    cmp_over = compare(
        "AAA",
        SESSION,
        _reclaim_bars(248.65),
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    cmp_under = compare(
        "AAA",
        SESSION,
        _reclaim_bars(248.60),
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    assert cmp_over.incumbent.readiness is True
    assert cmp_under.incumbent.readiness is False
    assert cmp_over.incumbent.state == ENTRY_READY


# The same economic path expressed in raw and adjusted coordinates gives the
# same band, the same readiness and the same states for both methods, with
# levels that scale by the adjustment ratio - the units correction locked in
# the protocol, verified through the actual helpers.
def test_raw_and_adjusted_scales_are_equivalent():
    raw_bars = _reclaim_bars(248.65)
    adjusted = [
        Bar(b.start, b.open / 2, b.high / 2, b.low / 2, b.close / 2, b.volume)
        for b in raw_bars
    ]
    raw = compare(
        "AAA",
        SESSION,
        raw_bars,
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    adj = compare(
        "AAA",
        SESSION,
        adjusted,
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="adjusted",
    )
    assert raw.band_z == pytest.approx(adj.band_z)
    assert raw.levels.level / 2 == pytest.approx(adj.levels.level)
    assert raw.levels.entry_level / 2 == pytest.approx(adj.levels.entry_level)
    for name in ("incumbent", "candidate"):
        r, a = getattr(raw, name), getattr(adj, name)
        assert (r.readiness, r.state) == (a.readiness, a.state)
        assert r.price_basis == "raw"
        assert a.price_basis == "adjusted"
    # The production live read agrees on both scales too.
    assert _production_band(248.65) == pytest.approx(raw.band_z, abs=1e-12)
    adj_panel = _live_panel(248.65)
    adj_panel = Panel(
        dates=adj_panel.dates,
        tickers=adj_panel.tickers,
        open=adj_panel.open / 2,
        high=adj_panel.high / 2,
        low=adj_panel.low / 2,
        close=adj_panel.close / 2,
        adj_close=adj_panel.adj_close / 2,
        volume=adj_panel.volume,
        themes=adj_panel.themes,
        benchmark=adj_panel.benchmark,
    )
    assert _production_band(124.325, panel=adj_panel) == pytest.approx(
        adj.band_z, abs=1e-12
    )


# A missing or unsupported price basis raises before any scoring, so a caller
# can never silently mix scales.
@pytest.mark.parametrize("basis", [None, "mixed", "unadjusted_guess"])
def test_unknown_price_basis_is_rejected(basis):
    with pytest.raises(ValueError, match="basis"):
        compare(
            "AAA",
            SESSION,
            _reclaim_bars(248.65),
            _history(),
            _eligibility(),
            _completed(2),
            price_basis=basis,
        )


# A rejecting-band daily blocks both methods: production entry_action returns
# Hold (never a Buy) at any band, and the comparison reports NOT_ELIGIBLE.
def test_rejecting_band_gate_matches_the_production_refusal():
    strong = incumbent_band_z(_history(), SESSION, 260.0, price_basis="raw")
    assert strong is not None
    assert strong > paper.ENTRY_BAND_Z
    result = entry_action({"rejecting_band": True}, strong, "A", 0.0)
    assert result is not None
    assert result[0] == Action.HOLD
    cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        _eligibility(rejecting_band=True),
        _completed(2),
        price_basis="raw",
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert cmp.incumbent.state == NOT_ELIGIBLE
    assert cmp.candidate.state == NOT_ELIGIBLE


# The grade floor is the production one: grade B is refused by entry_action at
# any band, and the comparison blocks both methods for the same reason.
def test_grade_floor_matches_the_production_refusal():
    strong = incumbent_band_z(_history(), SESSION, 260.0, price_basis="raw")
    assert entry_action({"rejecting_band": False}, strong, "B", 0.0) is None
    cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        _eligibility(grade="B"),
        _completed(2),
        price_basis="raw",
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert cmp.incumbent.state == NOT_ELIGIBLE
    assert cmp.candidate.state == NOT_ELIGIBLE


# Unknown eligibility, or eligibility learned after the decision time, blocks
# both methods; once the same inputs are known by the decision time they enable.
def test_late_or_unknown_eligibility_blocks_both_methods():
    unknown = _eligibility(grade=None)
    cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        unknown,
        _completed(2),
        price_basis="raw",
    )
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    assert cmp.incumbent.state == NOT_ELIGIBLE
    late = _eligibility(grade_at=_completed(3))
    late_cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        late,
        _completed(2),
        price_basis="raw",
    )
    assert not late_cmp.incumbent.readiness
    assert not late_cmp.candidate.readiness
    known = _eligibility(grade_at=_completed(2))
    known_cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        known,
        _completed(2),
        price_basis="raw",
    )
    assert known_cmp.incumbent.readiness is True
    assert known_cmp.candidate.readiness is True


# Named divergence - account holdings and the name cap are outside the
# comparison. Production entry_action refuses to add to a name already at the
# 15% name cap even at a strong band; the comparison calls the same function
# with current=0.0, so it reports the formula ready and cannot see the cap.
def test_name_cap_and_holdings_are_out_of_scope_for_the_comparison():
    strong = incumbent_band_z(_history(), SESSION, 260.0, price_basis="raw")
    capped = entry_action({"rejecting_band": False}, strong, "A", paper.ENTRY_NAME_CAP)
    assert capped is not None
    assert capped[0] == Action.HOLD
    assert "name cap" in capped[2]
    cmp = compare(
        "AAA",
        SESSION,
        _reclaim_bars(260.0),
        _history(),
        _eligibility(),
        _completed(2),
        price_basis="raw",
    )
    assert cmp.incumbent.readiness is True
    assert cmp.incumbent.state == ENTRY_READY


# Named divergence - the comparison is a fixed-eligibility formula check, never
# an execution. A close-time reclaim is recorded with its trigger, not treated
# as a fill or a next-session order, and neither method carries account state.
def test_close_time_signal_is_historical_and_carries_no_execution():
    bars = _reclaim_bars(260.0)
    cmp = compare(
        "AAA",
        SESSION,
        bars,
        _history(),
        _eligibility(),
        session_close_for(SESSION),
        price_basis="raw",
    )
    assert cmp.incumbent.state == "historical"
    assert cmp.candidate.state == "historical"
    assert not cmp.incumbent.readiness
    assert not cmp.candidate.readiness
    for obs in (cmp.incumbent, cmp.candidate):
        assert obs.session == SESSION
        assert obs.price_basis == "raw"
