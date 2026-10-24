"""Grade direction with leader-tilted equal weight at a realised-volatility target.

The candidate keeps every rule of the installed grade-led policy except how an
eligible name is sized: instead of the learned scenario optimiser, each name
graded A or better (held while it keeps B) takes an equal slot tilted by its
trailing-return rank among the sized names, the book is scaled down to a
realised-volatility target, and each name is capped. Nothing after the
decision session is read, no model is fitted, and the receipt says the
optimiser did not run.
"""

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import adaptive_growth_policy as growth
from backend.market import joint_funded_policy as funded

POLICY = "grade-led-leader-weight/1"
PROTOCOL = "docs/research/grade-led-leader-weight-contract-2026-10-21.md"
BASIS = "grade_led_leader_weight"
WINDOW = 63
STRENGTH = 0.5
TARGET = 0.25
TRADING_DAYS = 252.0


# The volatility the target is measured against: an exponentially weighted
# estimate of the basket's daily variance over the window (span `EWMA_SPAN`),
# annualised. On the scorecard it set the exposure a little better than the
# plain trailing standard deviation (worst drawdown -34.2% against -35.1%,
# Sharpe 1.03 against 0.97, 0.3 points of CAGR), and a walk-forward ridge
# forecast of the same quantity did worse (-39.8%): the naive forecaster is
# the one that earned its place.
EWMA_SPAN = 20
# The least of its full exposure the book keeps whatever the volatility
# reads: the target is a brake, not an exit. Without a floor the rule held
# a sixth of its book through 2020 and made -6% in a year the equal-weight
# A/A+ book made +37%, because a volatility spike cut the exposure first
# and kept it cut through the rebound. On the scorecard (B cut, 25 bp, 20
# offsets) a floor of 0.5 earned 26.7% a year at worst drawdown -34.1% and
# Sharpe 1.12 against 26.0%, -34.3% and 1.11 without one (2020 +16.6%
# against +7.4%, every other year within a point); 0.65 earned 27.5% at
# -36.0%, 0.35 was the rule without a floor. Half is the floor that paid
# for itself without buying drawdown.
EXPOSURE_FLOOR = 0.5
# The ordinal grades (C 0, B 1, A 2, A+ 3) at which a name is admitted and at
# which a held name keeps its place, and the least resize worth trading as a
# share of equity (an exit always trades). Chosen on the account-faithful
# simulator (`backend.market.policy_book`: the nightly's grades, fills at the
# next open from cash on hand, whole shares, 10 bp, the FOMC cycle), tuned on
# 2015-2022 and checked on 2023-2026 (docs/research/
# account-simulator-rule-2026-10-24.md): admitting at A and holding while B
# earned 39.4% a year at worst drawdown -26.9% and Sharpe 1.51 against 34.0%,
# -29.5% and 1.39 for admitting and holding at B, ahead in both windows (25.0%
# against 19.8% to 2022, 74.4% against 68.5% after) and at 25 bp costs; the
# 1% minimum trade cut fills from 82,000 to 6,700 without giving up return.
ENTRY_GRADE = 2
HOLD_GRADE = 1
MIN_TRADE = 0.01
# The P/E-history tilt: each sized name's leader slot is multiplied by
# 1 + PE_HISTORY_TILT * (1 - 2 h), where h is where its price/earnings sits in
# its own trailing three years of readings (valuation.own_history_rank: 0 the
# cheapest it has been, 1 the richest); no positive earnings or fewer than 250
# readings leaves the slot unchanged. On the account simulator with the
# split-corrected grades it earned 37.4% a year at worst drawdown -27.1%
# against 34.8% and -27.7% without it, ahead to 2022 (21.2% against 19.1%) and
# after (77.4% against 73.8%), at 25 bp, in 8 of 11 years and about 3.5
# standard deviations above shuffled and random placebos; in practice it
# reads "earnings have grown faster than the price"
# (docs/research/pe-history-tilt-2026-10-24.md). It sizes; it admits no name.
PE_HISTORY_TILT = 0.5
PE_HISTORY_WINDOW = 756
PE_HISTORY_MIN = 250


def pe_history_tilt(history_rank, strength=PE_HISTORY_TILT):
    h = np.asarray(history_rank, dtype=float)
    return np.where(np.isfinite(h), 1.0 + strength * (1.0 - 2.0 * h), 1.0)


# The valuation analyst's own price/earnings evidence (the reading the grade
# cites), (T, N) in panel order, or None when the report carries none.
def _report_pe(report):
    opinion = (getattr(report, "opinions", None) or {}).get("value")
    pe = None if opinion is None else (opinion.evidence or {}).get("price_earnings")
    shape = (len(report.panel.dates), len(report.panel.tickers))
    return None if pe is None or np.shape(pe) != shape else np.asarray(pe, float)


# The tilt for every name on the report's last session: (N,) multipliers in
# panel order, all 1.0 when the evidence is absent.
def report_pe_tilt(report) -> np.ndarray:
    from backend.market import valuation

    pe = _report_pe(report)
    if pe is None:
        return np.ones(len(report.panel.tickers))
    rank = valuation.own_history_rank(
        pe[-PE_HISTORY_WINDOW:], window=PE_HISTORY_WINDOW, min_known=PE_HISTORY_MIN
    )[-1]
    return pe_history_tilt(rank)


# The same tilt on every session of the report, for the account simulator:
# row t reads only readings up to t, exactly as that night's plan would.
def report_pe_tilts(report) -> np.ndarray | None:
    from backend.market import valuation

    pe = _report_pe(report)
    if pe is None:
        return None
    rank = valuation.own_history_rank(
        pe, window=PE_HISTORY_WINDOW, min_known=PE_HISTORY_MIN
    )
    return pe_history_tilt(rank)


def forecast_volatility(basket: np.ndarray) -> float:
    alpha = 2.0 / (EWMA_SPAN + 1.0)
    weights = (1.0 - alpha) ** np.arange(len(basket))[::-1]
    variance = float(np.sum(weights * basket**2) / weights.sum())
    return float(np.sqrt(variance * TRADING_DAYS))


# Share one unit of capital across the sized names from their trailing closes only:
# equal slots tilted by trailing-return rank, the whole book scaled down to the
# volatility target but never below the exposure floor, each name capped, the
# remainder cash; never levered.
def leader_weights(
    closes,
    sized,
    *,
    window=WINDOW,
    strength=STRENGTH,
    target=TARGET,
    cap=growth.CAP,
    floor=EXPOSURE_FLOOR,
    extra=None,
):
    closes = np.asarray(closes, dtype=float)
    sized = np.asarray(sized, dtype=bool)
    if (
        closes.ndim != 2
        or sized.ndim != 1
        or closes.shape != (window + 1, len(sized))
        or window < 2
        or not 0 <= strength <= 1
        or not target > 0
        or not 0 < cap <= 1
        or not 0 <= floor <= 1
    ):
        raise ValueError("Exactly window+1 trailing closes for every name required")
    certificate = {
        "basis": BASIS,
        "window": int(window),
        "strength": float(strength),
        "volatility_target": float(target),
        "volatility_estimator": f"ewma_span_{EWMA_SPAN}",
        "exposure_floor": float(floor),
        "cap": float(cap),
        "annualisation": TRADING_DAYS,
        "sized": int(sized.sum()),
        "optimizer_ran": False,
    }
    weights = np.zeros(len(sized))
    if not sized.any():
        return weights, {**certificate, "status": "no_sized_names"}
    book = closes[:, sized]
    if not np.isfinite(book).all() or not (book > 0).all():
        raise ValueError("Finite positive trailing closes for every sized name")
    multipliers = point_in_time.TILTS["leader"](book, strength)
    if extra is not None:
        # A per-name multiplier on the leader slot (the P/E-history tilt):
        # a missing or non-positive value leaves the slot as it is.
        x = np.asarray(extra, dtype=float)[sized]
        multipliers = multipliers * np.where(np.isfinite(x) & (x > 0), x, 1.0)
    slots = multipliers / multipliers.sum()
    basket = np.diff(np.log(book), axis=0).mean(axis=1)
    realised = forecast_volatility(basket)
    scale = max(floor, min(1.0, target / realised)) if realised > 0 else 1.0
    weights[sized] = np.minimum(slots * scale, cap)
    if not np.isfinite(weights).all() or weights.sum() > 1 + 1e-10:
        raise ValueError("Leader weights must stay within unit capital")
    certificate.update(
        status="sized",
        trailing_returns=(book[-1] / book[0] - 1.0).tolist(),
        multipliers=multipliers.tolist(),
        realised_volatility=realised,
        scale=float(scale),
        gross=float(weights.sum()),
    )
    return weights, certificate


# The trailing close window of the report ending on its last session, per name.
def _window(report, names, window=WINDOW):
    panel = report.panel
    if len(panel.dates) < window + 1:
        raise ValueError("Trailing close window longer than the report")
    columns = [panel.index(name) for name in names]
    return np.asarray(panel.adj_close[-(window + 1) :, columns], dtype=float)


# Size `names` on unit capital from the report's trailing closes. A name without a
# full finite window is not sized, and a blocked name may not grow past `current`,
# so the funded account and the account-free publication share one calculation.
def size_report(report, names, blocked, current):
    closes = _window(report, names)
    with np.errstate(invalid="ignore"):
        known = np.isfinite(closes).all(axis=0) & (closes > 0).all(axis=0)
    sized = known & np.array(
        [name not in blocked or current.get(name, 0) > 0 for name in names],
        dtype=bool,
    )
    tilt = report_pe_tilt(report)
    columns = [report.panel.index(name) for name in names]
    extra = tilt[columns]
    weights, certificate = leader_weights(closes, sized, extra=extra)
    certificate["pe_history_tilt"] = {
        "strength": PE_HISTORY_TILT,
        "window": PE_HISTORY_WINDOW,
        "multipliers": dict(zip(names, extra.tolist(), strict=True)),
    }
    sizes = {
        name: min(weight, current.get(name, 0.0)) if name in blocked else weight
        for name, weight in zip(names, weights.tolist(), strict=True)
    }
    certificate.update(
        unsized=[
            name for name, ok in zip(names, known.tolist(), strict=True) if not ok
        ],
        dates=[str(report.panel.dates[-(WINDOW + 1)]), str(report.panel.dates[-1])],
    )
    return sizes, certificate


# Keep the grade-led direction, funding, timing and receipts; replace only the sizing.
class GradeLedLeaderFundedPolicy(funded.GradeLedFundedPolicy):
    version = POLICY
    protocol = PROTOCOL
    sizing_reason = BASIS
    target_basis = BASIS
    # A name is admitted at A or better and held while it keeps at least B
    # (ENTRY_GRADE, HOLD_GRADE). The scorecard that once preferred the B cut
    # graded with the research fundamentals mode, not the nightly's; on the
    # nightly's grades the A entry with a B hold leads in both windows.
    entry_grade = ENTRY_GRADE
    minimum_held_grade = HOLD_GRADE
    exit_letter = "B"
    min_trade = MIN_TRADE

    # Bind the sizing source beside the funded policy source the parent already pins;
    # the installed subclass passes its release arguments through unchanged.
    def __init__(self, reader, cost_bps, *installed):
        super().__init__(reader, cost_bps, *installed)
        self.identity["sizing_source_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        self.identity["sizing_basis"] = BASIS

    # Grades alone admit names; no per-name risk reading qualifies or excludes one.
    def _required_stocks(self, grades, current, day, blocked, *, refusal=None):
        candidates, _ = funded.JointFundedPolicy._required_stocks(
            self, grades, current, day, blocked
        )
        retained = [name for name in candidates if current.get(name, 0) > 0]
        excluded = {
            name: {"reason": "buy_permission_blocked"}
            for name in candidates
            if name not in retained and name in blocked
        }
        required = tuple(name for name in candidates if name not in excluded)
        return required, {
            "entry_qualification": {
                "policy": self.version,
                "considered_entrants": [n for n in candidates if n not in retained],
                "admitted_entrants": [n for n in required if n not in retained],
                "mandatory_held": retained,
                "excluded_entries": excluded,
                "selection_uses_future_outcomes": False,
                "joint_risk_still_required": False,
            }
        }

    # Size from the report's own trailing closes instead of the scenario optimiser.
    def _size(
        self, names, exits, grades, current, cash, equity, day, blocked, report, receipt
    ):
        try:
            sizes, certificate = size_report(report, names, blocked, current)
        except ValueError as exc:
            receipt["leader_sizing"] = {"status": "unavailable", "reason": str(exc)}
            return {}, "leader_window_unavailable"
        held_unsized = [n for n in certificate["unsized"] if current.get(n, 0) > 0]
        if held_unsized:
            # A held name the window cannot price must not be resized blind.
            receipt["leader_sizing"] = {
                "status": "unavailable",
                "reason": "trailing_window_unavailable",
                "symbols": held_unsized,
            }
            return {}, "leader_window_unavailable"
        qualification = receipt["entry_qualification"]
        for name in certificate["unsized"]:
            qualification["excluded_entries"][name] = {
                "reason": "trailing_window_unavailable"
            }
            qualification["admitted_entrants"].remove(name)
        receipt["leader_sizing"] = certificate
        return {**sizes, **dict.fromkeys(exits, 0.0)}, None

    # Only a name without a grade is set aside; the risk model does not gate sizing.
    def _unavailable_holdings(self, session, held, exits, protected):
        return {
            name: {
                "status": "unavailable",
                "reason": "company_grade_unavailable",
                "symbols": [name],
                "decision_date": session,
            }
            for name, qty in held.items()
            if qty > 0 and name in protected and name not in exits
        }

    # Fill every leg at the next open. The execution-timing study measured
    # no fill convention, the learned 15-minute timing included, that beat
    # buying at the next open (within +-0.2 bp a session, none at t >= 2.5),
    # and the live timing's quote and clock guards left the paper account's
    # first timed intents unfilled for a whole session. A market-on-open
    # order has no such guards: the plan says what and how much, the opening
    # auction says the price. Exposure, not fill timing, is this policy's
    # answer to a selling tape.
    def plan(self, session, state, equity, held, prices, report, cash, blocked):
        from backend.agents.trading.desk import intraday_orders

        orders, updated, note = super().plan(
            session, state, equity, held, prices, report, cash, blocked
        )
        routed = [
            replace(
                order,
                execution_timing="next_open"
                if order.execution_timing == intraday_orders.INTRADAY_TIMING
                else order.execution_timing,
                reason="Grade-led leader-weight sizing adjustment"
                if order.reason == "Grade-led learned sizing adjustment"
                else order.reason,
            )
            for order in orders
        ]
        if routed and updated.allocation_state:
            updated.allocation_state["receipt"]["execution_timing"] = {
                "ordinary": "next_open",
                "company_exit": "next_open",
                "orders": {
                    order.client_order_id: order.execution_timing for order in routed
                },
            }
        return routed, updated, note
