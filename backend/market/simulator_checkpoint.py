"""Opt-in in-memory `/4` forks; no alternate order planner or fill engine.

Preparation freezes caller-owned market arrays against accidental mutation and
binds them to one report. Checkpoints are research objects, not live account
state. A continuation requires the same allocator callable and configuration.
That allocator must be a causal, stateless row-local policy; identity checks
cannot establish purity of arbitrary caller-provided Python code.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# Make a separately owned, immutable array for an observational callback.
def readonly(values, dtype=None):
    value = np.array(values, dtype=dtype, copy=True)
    value.setflags(write=False)
    return value


@dataclass(frozen=True)
class ResearchContext:
    """Only the current close and account state, never future market rows."""

    t: int
    session: str
    symbols: tuple[str, ...]
    prices: np.ndarray
    held_units: np.ndarray
    cash: float
    nav: float
    incumbent_units: np.ndarray
    buy_allowed: np.ndarray
    current_targets: np.ndarray
    opened: np.ndarray
    last_rebalance: int
    next_rebalance: int
    rebalanced: bool
    cost_bps: float


@dataclass(frozen=True)
class ResearchOrder:
    """An ordinary-session unit proposal and explicitly suppressed retry names."""

    units: Any
    blocked_deferred_symbols: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchCheckpoint:
    """All incumbent account/clock state immediately before a decision session."""

    t: int
    prepared_identity: str
    configuration: str
    allocator_identity: int
    cost_bps: float
    shares: np.ndarray
    cash: float
    traded: float
    opened: tuple[tuple[int, int], ...]
    paid: tuple[tuple[int, float], ...]
    trades: tuple[Any, ...]
    next_rebalance: int
    last_rebalance: int
    rebalance_weights: tuple[tuple[str, float], ...]
    pending_deferred: tuple[tuple[str, float], ...]
    event_baseline: np.ndarray | None
    event_sold: np.ndarray | None
    previous_scale: float
    previous_brake: float
    rebalances: int
    dip_adds: int


# Expand a run's arguments once so omitted and explicit defaults bind identically.
def _options(report, supplied):
    from backend.agents.trading.desk import simulate

    bound = inspect.signature(simulate.run).bind_partial(report, **supplied)
    bound.apply_defaults()
    return bound.arguments


# Restrict forks to the explicitly tested incumbent execution family.
def validate_options(values):
    prohibited = (
        "use_exits",
        "funded_allocation",
        "entry_gate",
        "band_dip_buy",
        "trend_gated_exit",
        "trend_brake",
        "midcycle_sweep",
        "reset_topup",
        "midcycle_trims",
        "index_eligible",
    )
    present = [key for key in prohibited if values[key]]
    nullable = (
        "dip",
        "exits",
        "weight_filter",
        "brake_path_override",
        "benchmark_prices",
        "excluded_symbols_by_session",
    )
    present += [key for key in nullable if values[key] is not None]
    if not values["live_midcycle"]:
        present.append("live_midcycle=False")
    if values["midcycle_entries"] != "breakout":
        present.append("midcycle_entries")
    if values["allocation_policy"] != "vol_trend":
        present.append("allocation_policy")
    if present:
        raise ValueError(
            "Research forks reject incompatible options: " + ", ".join(present)
        )


# Bind every execution option while excluding observations, cost and allocation hooks.
def configuration(values):
    ignored = {
        "report",
        "since",
        "allocator",
        "cost_bps",
        "journal",
        "research_hook",
        "research_capture",
        "research_resume",
        "research_stop",
        "research_prepared",
    }
    pieces = []
    for key, value in sorted(values.items()):
        if key in ignored:
            continue
        if isinstance(value, np.ndarray):
            digest = hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
            value = (str(value.dtype), value.shape, digest)
        pieces.append((key, repr(value)))
    return repr(pieces)


# Identify every array the incumbent planner or its market preparation reads directly.
def _sources(report):
    panel = report.panel
    return tuple(
        (key, getattr(panel, key))
        for key in ("dates", "open", "high", "low", "close", "adj_close", "volume")
    ) + (("grades", report.graded.grades),)


@dataclass(frozen=True)
class PreparedResearch:
    """Market-only arrays reused by short forks, with a source/configuration binding."""

    report: Any
    source_panel: Any
    sources: tuple[Any, ...]
    identity: str
    signature: str
    fired: Any
    blocked: Any
    trend_up: Any
    dips: Any
    live_bands: Any
    opens: np.ndarray
    stamps: tuple[str, ...]

    # Refuse a different report, configuration or accidentally un-frozen source.
    def validate(self, report, options):
        if report is not self.report:
            raise ValueError("Research preparation belongs to a different report")
        if report.panel is not self.source_panel:
            raise ValueError("Research preparation source changed its panel")
        validate_options(options)
        if configuration(options) != self.signature:
            raise ValueError("Research preparation configuration differs")
        current = _sources(report)
        if any(
            key != old_key or array is not old_array or array.flags.writeable
            for (key, array), (old_key, old_array) in zip(
                current, self.sources, strict=True
            )
        ):
            raise ValueError("Research preparation source changed or became writable")


# Prepare invariant market signals once; no holdings or allocator output is cached.
def prepare_research(report, **options):
    from backend.agents.trading.desk import entry, simulate

    values = _options(report, options)
    validate_options(values)
    sources = _sources(report)
    digest = hashlib.sha256()
    digest.update(repr(tuple(report.panel.tickers)).encode())
    for name, array in sources:
        digest.update(name.encode())
        digest.update(str(array.dtype).encode())
        digest.update(repr(array.shape).encode())
        digest.update(np.ascontiguousarray(array).tobytes())
        array.setflags(write=False)
    signals = simulate._signals_for(
        report,
        values["entry_gate"],
        values["block_overbought"],
        values["band_dip_buy"],
        values["trend_gated_exit"],
        values["dip"],
    )
    frozen_signals = tuple(
        None if array is None else readonly(array) for array in signals
    )
    bands = entry.bollinger_z(report.panel.adj_close)
    return PreparedResearch(
        report,
        report.panel,
        sources,
        digest.hexdigest(),
        configuration(values),
        *frozen_signals,
        readonly(bands),
        readonly(simulate.adjusted_open(report.panel)),
        tuple(str(day) for day in report.panel.dates),
    )


# Capture immutable incumbent state without copying the report or future market rows.
def capture(prepared, options, t, book, state, trades):
    return ResearchCheckpoint(
        t=t,
        prepared_identity=prepared.identity,
        configuration=prepared.signature,
        allocator_identity=id(options["allocator"]),
        cost_bps=float(options["cost_bps"]),
        shares=readonly(book.shares),
        cash=float(book.cash),
        traded=float(book.traded),
        opened=tuple(book.opened.items()),
        paid=tuple(book.paid.items()),
        trades=trades,
        next_rebalance=state["next_rebalance"],
        last_rebalance=state["last_rebalance"],
        rebalance_weights=tuple(state["rebalance_weights"].items()),
        pending_deferred=tuple(state["pending_deferred"].items()),
        event_baseline=None
        if state["event_baseline"] is None
        else readonly(state["event_baseline"]),
        event_sold=None
        if state["event_sold"] is None
        else readonly(state["event_sold"]),
        previous_scale=state["previous_scale"],
        previous_brake=state["previous_brake"],
        rebalances=state["rebalances"],
        dip_adds=state["dip_adds"],
    )


# Reject a checkpoint from a different account definition before touching book state.
def validate_resume(checkpoint, prepared, options):
    if not isinstance(checkpoint, ResearchCheckpoint):
        raise ValueError("research_resume must be a ResearchCheckpoint")
    if (
        checkpoint.prepared_identity != prepared.identity
        or checkpoint.configuration != prepared.signature
        or checkpoint.allocator_identity != id(options["allocator"])
        or checkpoint.cost_bps != float(options["cost_bps"])
    ):
        raise ValueError(
            "Research checkpoint source, options, allocator or cost differs"
        )
    if not 0 <= checkpoint.t < len(prepared.report.panel.dates):
        raise ValueError("Research checkpoint session is outside the panel")
    if checkpoint.shares.shape != (len(prepared.report.panel.tickers),):
        raise ValueError("Research checkpoint holdings do not align with the panel")
    if (
        not np.isfinite(checkpoint.shares).all()
        or (checkpoint.shares < 0).any()
        or not np.isfinite(checkpoint.cash)
        or checkpoint.cash < 0
        or not np.isfinite(checkpoint.traded)
        or checkpoint.traded < 0
    ):
        raise ValueError("Research checkpoint balances must be finite and nonnegative")


# Isolate callback output and permit no malformed orders or unknown retry symbols.
def apply_order(proposal, context, pending):
    if not isinstance(proposal, ResearchOrder):
        raise ValueError("research_hook must return ResearchOrder or None")
    units = np.asarray(proposal.units, dtype=float)
    if (
        units.shape != context.held_units.shape
        or not np.isfinite(units).all()
        or (units < 0).any()
    ):
        raise ValueError("Research order units must be aligned, finite and nonnegative")
    blocked = frozenset(proposal.blocked_deferred_symbols)
    if not blocked.issubset(context.symbols):
        raise ValueError("Research order names an unknown deferred symbol")
    if not isinstance(proposal.metadata, dict):
        raise ValueError("Research order metadata must be a JSON object")
    try:
        metadata = json.loads(json.dumps(proposal.metadata, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("Research order metadata must be finite JSON") from exc
    return (
        units.copy(),
        {s: q for s, q in pending.items() if s not in blocked},
        metadata,
        blocked,
    )
