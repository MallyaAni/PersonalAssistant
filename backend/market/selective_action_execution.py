"""Sparse, holdings-aware interventions through the unchanged /4 fill rules.

The policy changes one ordinary plan per reset cycle. A selected action is not
a fill, and accepting /4 is no intervention rather than a claim to hold still.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk import policy_v4, simulate
from backend.market import profit_taking
from backend.market.daily_action_execution import PricedExecution
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.market.selective_action_model import ACTIONS, action_features
from backend.market.simulator_checkpoint import ResearchOrder

POLICY = "selective-action-advantage/1"
PLAN = "docs/research/selective-actions-plan-2026-09-29.md"
OPPORTUNITY_AGES = (0, 5, 10, 15)
MIN_ADVANTAGE = 0.0005
MAX_INCREMENT = 0.02
MIN_INCREMENT = 0.005
EPSILON = 1e-12


@dataclass(frozen=True)
class ActionCandidate:
    """One current feasible change to one symbol's incumbent proposed units."""

    symbol: str
    index: int
    action: str
    units: float
    features: np.ndarray
    incremental_weight: float
    incumbent_units: float
    held_units: float

    # Own the feature row so the caller cannot rewrite a selected intervention.
    def __post_init__(self):
        row = np.array(self.features, dtype=float, copy=True)
        if row.shape != (33,) or not np.isfinite(row).all():
            raise ValueError("candidate requires 33 finite current features")
        if self.action not in ACTIONS:
            raise ValueError("candidate action must be Buy, Add, Trim or Sell")
        if (
            not all(
                np.isfinite(value)
                for value in (
                    self.units,
                    self.incremental_weight,
                    self.incumbent_units,
                    self.held_units,
                )
            )
            or min(self.units, self.incumbent_units, self.held_units) < 0
        ):
            raise ValueError("candidate units and incremental weight must be finite")
        row.setflags(write=False)
        object.__setattr__(self, "features", row)


# Validate the current ordinary planning boundary without looking at future prices.
def _current(context, daily_features_row):
    names = tuple(context.symbols)
    arrays = [
        np.asarray(getattr(context, name), dtype=float)
        for name in (
            "prices",
            "held_units",
            "incumbent_units",
            "current_targets",
            "opened",
        )
    ]
    features = np.asarray(daily_features_row, dtype=float)
    allowed = np.asarray(context.buy_allowed, dtype=bool)
    if any(value.shape != (len(names),) for value in arrays) or allowed.shape != (
        len(names),
    ):
        raise ValueError("current context vectors must align with symbols")
    if features.shape != (len(names), 22) or len(set(names)) != len(names):
        raise ValueError("current daily features must align with unique symbols")
    prices, held, incumbent, targets, opened = arrays
    if (
        not np.isfinite(held).all()
        or not np.isfinite(incumbent).all()
        or not np.isfinite(targets).all()
        or np.any(held < 0)
        or np.any(incumbent < 0)
        or not np.isfinite(context.nav)
        or context.nav <= 0
        or not np.isfinite(context.cash)
        or context.cash < -EPSILON
        or not np.isfinite(context.cost_bps)
        or not 0 <= context.cost_bps < 10000
    ):
        raise ValueError("current account must be finite, long-only and funded")
    return names, prices, held, incumbent, targets, opened, allowed, features


# Enumerate only feasible current changes, reserving fees on every incumbent buy.
def candidates(context, daily_features_row) -> list[ActionCandidate]:
    names, prices, held, incumbent, targets, opened, allowed, rows = _current(
        context, daily_features_row
    )
    valid_price = np.isfinite(prices) & (prices > 0)
    fee = float(context.cost_bps) / 10000
    incumbent_buys = np.maximum(incumbent - held, 0)
    # An unpriced incumbent buy makes its cash reservation unknown, never free.
    reservation = (
        float(np.dot(incumbent_buys[valid_price], prices[valid_price])) * (1 + fee)
        if not np.any((incumbent_buys > EPSILON) & ~valid_price)
        else float("inf")
    )
    cash_room = max(0.0, float(context.cash) - reservation)
    nav = float(context.nav)
    result = []
    for j, symbol in enumerate(names):
        if not valid_price[j] or not np.isfinite(rows[j]).all():
            continue
        price = float(prices[j])
        options = []
        if allowed[j] and incumbent[j] >= held[j] - EPSILON:
            extra_notional = min(
                MAX_INCREMENT * nav,
                cash_room / (1 + fee),
                max(0.0, policy_v4.HOLD_CAP * nav - incumbent[j] * price),
            )
            if extra_notional / nav >= MIN_INCREMENT - EPSILON:
                options.append(
                    (
                        "Buy" if held[j] == 0 else "Add",
                        incumbent[j] + extra_notional / price,
                    )
                )
        if held[j] > 0:
            if held[j] / 2 < incumbent[j] - EPSILON:
                options.append(("Trim", held[j] / 2))
            if incumbent[j] > EPSILON:
                options.append(("Sell", 0.0))
        for action, units in options:
            increment = float((units - incumbent[j]) * price / nav)
            held_change = float((units - held[j]) * price / nav)
            if min(abs(increment), abs(held_change)) < MIN_INCREMENT - EPSILON:
                continue
            age = (
                int(context.t) - int(opened[j]) if held[j] > 0 and opened[j] >= 0 else 0
            )
            feature = action_features(
                rows[j],
                held_weight=float(held[j] * price / nav),
                cash_share=max(0.0, float(context.cash)) / nav,
                target_gap=float(targets[j] - held[j] * price / nav),
                holding_age=age,
                sessions_to_reset=max(0, int(context.next_rebalance) - int(context.t)),
                signed_incremental_weight=increment,
                incumbent_weight=float(incumbent[j] * price / nav),
                action=action,
            )
            result.append(
                ActionCandidate(
                    symbol,
                    j,
                    action,
                    float(units),
                    feature,
                    increment,
                    float(incumbent[j]),
                    float(held[j]),
                )
            )
    return sorted(result, key=lambda item: (item.symbol, item.action))


# Record decision-time action meaning without claiming its eventual execution.
def _selection(candidate, context, score):
    return {
        "symbol": candidate.symbol,
        "index": candidate.index,
        "action": candidate.action,
        "session": context.session,
        "session_index": int(context.t),
        "reset_session_index": int(context.last_rebalance),
        "units": candidate.units,
        "held_units": candidate.held_units,
        "incumbent_units": candidate.incumbent_units,
        "incremental_weight": candidate.incremental_weight,
        "predicted_advantage": score,
        "features": candidate.features.tolist(),
    }


# Retain fixed ceilings without introducing sub-floor trades or cancelling /4 exits.
def _apply_locks(context, units, locks):
    for symbol, ceiling in locks.items():
        index = context.symbols.index(symbol)
        incumbent = float(context.incumbent_units[index])
        held = float(context.held_units[index])
        capped = min(float(units[index]), ceiling)
        if (
            capped != incumbent
            and abs(capped - held) * float(context.prices[index]) / context.nav
            < MIN_INCREMENT - EPSILON
        ):
            capped = min(incumbent, held)
        units[index] = capped
    return units


# Apply a one-shot proposal and persistent reductions after every ordinary planner.
class ForcedAction:
    """One registered counterfactual intervention, never a later second choice."""

    # Start without a lock; the same-state fork applies the action only at start_t.
    def __init__(self, start_t, candidate):
        self.start_t = int(start_t)
        self.candidate = candidate
        self.applied = False
        self.cycle = None
        self.lock = None

    # Keep a reduction's original unit ceiling until the simulator actually resets.
    def __call__(self, context):
        if self.cycle is not None and context.last_rebalance != self.cycle:
            self.lock = None
        selected = None
        units = np.array(context.incumbent_units, dtype=float, copy=True)
        if not self.applied and context.t == self.start_t:
            candidate = self.candidate
            if context.symbols[candidate.index] != candidate.symbol:
                raise ValueError("forced candidate symbol differs from resumed account")
            if not np.isclose(
                units[candidate.index],
                candidate.incumbent_units,
                rtol=1e-10,
                atol=EPSILON,
            ):
                raise ValueError(
                    "forced candidate no longer matches its incumbent plan"
                )
            if not np.isclose(
                context.held_units[candidate.index],
                candidate.held_units,
                rtol=1e-10,
                atol=EPSILON,
            ):
                raise ValueError("forced candidate no longer matches its held units")
            units[candidate.index] = candidate.units
            self.applied, self.cycle = True, context.last_rebalance
            if candidate.action in ("Trim", "Sell"):
                self.lock = candidate.units
            selected = _selection(candidate, context, None)
        if selected is None and self.lock is None:
            return None
        locks = {} if self.lock is None else {self.candidate.symbol: self.lock}
        units = _apply_locks(context, units, locks)
        return ResearchOrder(
            units,
            tuple(locks),
            {
                "controller": "forced-counterfactual",
                "selected_intervention": selected,
                "reduction_locks": locks,
            },
        )


class Controller:
    """Select from the account's own current state at four opportunities per reset."""

    # Own price features and keep model inference separate from the execution state.
    def __init__(self, daily_data, family, training=None):
        if family not in ("momentum", "mean", "ridge", "tree"):
            raise ValueError("unknown selective action family")
        if family != "momentum" and training is None:
            raise ValueError("learned and mean controllers require past-fitted models")
        self.features = np.array(daily_data.features, dtype=float, copy=True)
        self.dates = np.array(daily_data.dates, dtype="datetime64[D]", copy=True)
        self.symbols = tuple(daily_data.tickers)
        self.feature_names = tuple(daily_data.feature_names)
        if self.features.shape != (len(self.dates), len(self.symbols), 22):
            raise ValueError("daily data must align dates, symbols and 22 features")
        self.stock20 = self.feature_names.index("stock_log_return_20")
        self.spy20 = self.feature_names.index("spy_log_return_20")
        self.features.setflags(write=False)
        self.dates.setflags(write=False)
        self.family, self.training = family, training
        self.cycle = None
        self.selected = False
        self.locks = {}
        self.selections = []
        self.opportunities = 0

    # Score current candidates with the registered control or the year's fitted model.
    def _scores(self, available, session):
        if self.family == "momentum":
            scores = np.asarray(
                [
                    item.incremental_weight
                    * (item.features[self.stock20] - item.features[self.spy20])
                    for item in available
                ]
            )
        else:
            scores = np.asarray(
                self.training.predict(
                    self.family,
                    session,
                    np.stack([item.features for item in available]),
                    np.asarray([item.action for item in available]),
                ),
                dtype=float,
            )
        if scores.shape != (len(available),) or not np.isfinite(scores).all():
            raise ValueError("candidate predictions must be finite and aligned")
        return scores

    # Reevaluate only current candidates; reductions still constrain later planners.
    def __call__(self, context):
        if (
            tuple(context.symbols) != self.symbols
            or not 0 <= context.t < len(self.dates)
            or str(self.dates[context.t]) != context.session
        ):
            raise ValueError(
                "controller data differs from the current account boundary"
            )
        if context.last_rebalance != self.cycle:
            self.cycle, self.selected, self.locks = context.last_rebalance, False, {}
        units = np.array(context.incumbent_units, dtype=float, copy=True)
        selected = None
        age = int(context.t) - int(context.last_rebalance)
        if (
            not self.selected
            and age in OPPORTUNITY_AGES
            and context.session >= "2019-01-01"
        ):
            self.opportunities += 1
            available = candidates(context, self.features[context.t])
            if available:
                scores = self._scores(available, context.session)
                best = int(np.argmax(scores))
                if scores[best] > MIN_ADVANTAGE:
                    candidate = available[best]
                    units[candidate.index] = candidate.units
                    if candidate.action in ("Trim", "Sell"):
                        self.locks[candidate.symbol] = candidate.units
                    self.selected = True
                    selected = _selection(candidate, context, float(scores[best]))
                    self.selections.append(selected)
        units = _apply_locks(context, units, self.locks)
        if selected is None and not self.locks:
            return None
        return ResearchOrder(
            units,
            tuple(self.locks),
            {
                "controller": self.family,
                "selected_intervention": selected,
                "reduction_locks": dict(self.locks),
            },
        )


# Count only genuine unit changes; no fill is never an executed Hold.
def _changes(before, after):
    changes = {}
    for index, (left, right) in enumerate(zip(before, after, strict=True)):
        tolerance = EPSILON * max(1.0, abs(left), abs(right))
        if right > left + tolerance:
            changes[index] = "Buy" if left <= tolerance else "Add"
        elif right < left - tolerance:
            changes[index] = "Sell" if right <= tolerance else "Trim"
    return changes


# Reconcile each selected symbol's immediate submission, fills and cancelled sale.
def _selected_observations(snapshot):
    observations = {}
    for event in snapshot["events"]:
        if event["type"] == "decision":
            selected = (
                event["metadata"].get("research_order", {}).get("selected_intervention")
            )
            if selected is not None:
                index = selected["index"]
                observations[event["decision_id"]] = {
                    **selected,
                    "decision_id": event["decision_id"],
                    "submitted_units": event["submitted_units"][index],
                    "observed_filled_units": 0.0,
                    "observed_notional": 0.0,
                    "observed_fees": 0.0,
                    "cancelled_sell": False,
                }
            continue
        row = observations.get(event.get("decision_id"))
        if row is None:
            continue
        index = row["index"]
        if event["type"] == "fill_batch":
            row["observed_filled_units"] += event["filled_units"][index]
            row["observed_notional"] += event["notional"][index]
            row["observed_fees"] += event["fees"][index]
        elif (
            event["type"] == "adjustment"
            and event["reason"] == "green-open sell suppression"
        ):
            row["cancelled_sell"] = bool(
                row["submitted_units"] < row["held_units"] - EPSILON
                and event["submitted_units"][index] >= row["held_units"] - EPSILON
            )
    return list(observations.values())


# Keep selected interventions, complete submitted plans and observed fills distinct.
def _diagnostics(snapshot, controller):  # noqa: C901 - distinct journal event meanings
    counts = {
        name: dict.fromkeys(ACTIONS, 0)
        for name in ("selected", "submitted", "executed")
    }
    positions = np.zeros(len(snapshot["manifest"]["symbols"]))
    decisions, cancelled, daily = {}, 0, []
    for event in snapshot["events"]:
        kind = event["type"]
        if kind in ("open_account", "mark"):
            positions = np.asarray(event["positions"], dtype=float)
            if kind == "mark":
                daily.append(
                    {
                        "session": event["session"],
                        "cash": event["cash"],
                        "nav": event["nav"],
                        "cash_share": event["cash"] / event["nav"],
                        "traded": event["traded"],
                    }
                )
        elif kind == "decision":
            submitted = np.asarray(event["submitted_units"], dtype=float)
            decisions[event["decision_id"]] = (positions.copy(), submitted.copy())
            for action in _changes(positions, submitted).values():
                counts["submitted"][action] += 1
            selected = (
                event["metadata"].get("research_order", {}).get("selected_intervention")
            )
            if selected is not None:
                counts["selected"][selected["action"]] += 1
        elif kind == "adjustment" and event["reason"] == "green-open sell suppression":
            before, submitted = decisions[event["decision_id"]]
            adjusted = np.asarray(event["submitted_units"], dtype=float)
            cancelled += int(
                ((submitted < before - EPSILON) & (adjusted >= before - EPSILON)).sum()
            )
        elif kind == "fill_batch":
            for action in _changes(
                event["positions_before"], event["positions_after"]
            ).values():
                counts["executed"][action] += 1
            positions = np.asarray(event["positions_after"], dtype=float)
    previous_traded, previous_nav, turnover = 0.0, None, 0.0
    for row in daily:
        row["notional_traded"] = row["traded"] - previous_traded
        row["turnover"] = row["notional_traded"] / previous_nav if previous_nav else 0.0
        turnover += row["turnover"]
        previous_traded, previous_nav = row["traded"], row["nav"]
    selections = [] if controller is None else list(controller.selections)
    if sum(counts["selected"].values()) != len(selections):
        raise ValueError("selected interventions differ from recorded decisions")
    return {
        "action_counts": counts,
        "selected_interventions": selections,
        "selected_symbol_observations": _selected_observations(snapshot),
        "opportunities": 0 if controller is None else controller.opportunities,
        "cancelled_sell_intents": cancelled,
        "daily": daily,
        "turnover": turnover,
        "mean_cash_share": float(np.mean([row["cash_share"] for row in daily])),
        "no_intervention_meaning": (
            "Accept the /4 plan, which may itself buy, add, trim or sell."
        ),
        "submitted_and_executed_basis": (
            "Whole account plans and observed fills, including /4 and event "
            "activity; not causal attribution to selected interventions."
        ),
        "selected_basis": (
            "One decision-time intervention at most per actual reset cycle, "
            "including cancelled actions."
        ),
        "selected_symbol_observation_basis": (
            "Actual selected-symbol units, notional and fees for the linked "
            "decision only, including the incumbent portion; not causal "
            "attribution or later reduction-lock retries."
        ),
    }


# Price one unchanged-cadence account and reject unreconciled cash, fills or marks.
def price(
    restricted,
    mask,
    daily_data,
    training,
    since,
    cost_bps,
    *,
    family="original_v4",
    name=None,
    research_prepared=None,
) -> PricedExecution:
    panel = restricted.panel
    membership = np.array(mask, dtype=bool, copy=True)
    if membership.shape != panel.adj_close.shape:
        raise ValueError("membership must align with the price panel")
    controller = (
        None if family == "original_v4" else Controller(daily_data, family, training)
    )
    name = name or f"{POLICY}:{family}"
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id=f"{name}:{since}:{cost_bps}",
        account_id=f"research:{name}",
        policy_id=name,
        cost_bps=cost_bps,
        provenance={
            "study": POLICY,
            "family": family,
            "specification": PLAN,
            "rebalance": 20,
            "event_lifecycle_owns_event_sessions": True,
            "historical_availability_verified": False,
            "adoption_eligible": False,
        },
    )
    result = simulate.run(
        restricted,
        since=since,
        allocator=policy_v4.allocator(membership),
        cost_bps=cost_bps,
        journal=journal,
        research_hook=controller,
        research_prepared=research_prepared,
        **profit_taking.control_options(panel),
    )
    snapshot = journal.snapshot()
    verification = verify_snapshot(snapshot)
    if not verification["ok"]:
        raise ValueError(
            f"selective account failed independent replay: {verification['errors']}"
        )
    marks = verification["marks"]
    if [row["session"] for row in marks] != [str(value) for value in result.dates]:
        raise ValueError("journal and simulator calendars differ")
    np.testing.assert_allclose(
        [row["nav"] for row in marks], result.equity, rtol=1e-10, atol=1e-12
    )
    np.testing.assert_allclose(
        verification["total_traded"], result.traded, rtol=1e-10, atol=1e-12
    )
    return PricedExecution(
        result, journal, verification, _diagnostics(snapshot, controller)
    )
