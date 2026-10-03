"""Strict archived-basket inputs with explicitly different raw SIP references.

The last regular SIP close is a reference proxy, not an official-close
attestation. Historical completed-bar clocks are synthetic; the source files
were published after the session and are never represented as live receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.market import calendar
from backend.market import sequential_shadow_context as history
from backend.market.sip_cube import SessionCube

REFERENCE_BASIS = "raw_SIP_last_regular_close_proxy_not_official_close"


# Retain the complete recorded basket beside its causal context and outcome sources.
@dataclass(frozen=True)
class RecordedTimingInputs:
    session: date
    context: history.ShadowContext
    cubes: dict[str, SessionCube]
    initial_cash: float
    holdings: dict[str, int]
    intents: tuple[dict, ...]
    initial_marks: dict[str, float]
    final_marks: dict[str, float]
    provenance: dict


# Refuse unsafe file names instead of silently changing a recorded symbol.
def _symbol(value):
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError("Recorded symbol must be an explicit safe file name")
    if value in (".", ".."):
        raise ValueError("Recorded symbol must be an explicit safe file name")
    return value


# Preserve nonnegative cash and exact positive whole-share quantities.
def _number(value, label, *, whole=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite numeric value")
    if not np.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    if whole and (value <= 0 or int(value) != value):
        raise ValueError(f"{label} must be positive whole shares")
    return int(value) if whole else float(value)


# Validate the prior account and every planned row without combining duplicates.
def _snapshot(record, prior, session, captured, digest):
    paper = record.get("paper")
    if not isinstance(paper, dict) or paper.get("session") != prior.isoformat():
        raise ValueError("Recorded paper account must belong to the prior session")
    published = history._instant(paper.get("written"), "Paper account")
    closed = datetime.combine(prior, calendar.session_close(prior), calendar.NEW_YORK)
    if (
        not closed
        <= published
        <= history._instant(record.get("written"), "Record")
        <= captured
    ):
        raise ValueError("Paper account publication was unavailable before the clock")
    cash = _number(paper.get("cash"), "Recorded cash")
    positions, planned = paper.get("positions"), paper.get("planned")
    if not isinstance(positions, list) or not isinstance(planned, list):
        raise ValueError("Explicit recorded positions and planned lists required")
    holdings = {}
    for row in positions:
        if not isinstance(row, dict):
            raise ValueError("Recorded position must be an object")
        symbol = _symbol(row.get("symbol"))
        if symbol in holdings:
            raise ValueError("Duplicate recorded positions cannot be inferred")
        holdings[symbol] = _number(row.get("qty"), "Position quantity", whole=True)
    intents = tuple(
        _intent(row, index, session, digest) for index, row in enumerate(planned)
    )
    return cash, holdings, intents


# Preserve each original planned row and its position in the authenticated record.
def _intent(row, index, session, digest):
    if not isinstance(row, dict):
        raise ValueError("Every planned row must be an object")
    _symbol(row.get("symbol"))
    if row.get("side") not in ("buy", "sell"):
        raise ValueError("Every planned row needs an explicit buy or sell side")
    if row.get("execute_on") != session.isoformat():
        raise ValueError("Every planned row must execute on the actual session")
    qty = _number(row.get("qty"), "Planned quantity", whole=True)
    if not isinstance(row.get("reason"), str) or not row["reason"].strip():
        raise ValueError("Recorded planned reason must be retained explicitly")
    if row.get("kind") is not None and not isinstance(row["kind"], str):
        raise ValueError("Recorded planned kind must be text or null")
    intent = dict(row)
    intent.update(id=f"{digest}:{index}", intent_id=f"{digest}:{index}", qty=qty)
    return intent


# Decode one original parquet byte stream while pinning its metadata and hash.
def _table(path, sources):
    table = pq.read_table(pa.BufferReader(history._read(path, sources)))
    metadata = {
        key.decode(): value.decode()
        for key, value in (table.schema.metadata or {}).items()
    }
    sources[str(Path(path).absolute())]["metadata"] = metadata
    return table.to_pydict(), metadata


# Require the exact ordered regular grid and retain an optional unused closing row.
def _sip(path, symbol, day, captured, sources, *, prior=False):
    columns, metadata = _table(path, sources)
    expected_meta = {
        "ticker": symbol,
        "kind": "bars_15m_sip",
        "source": "alpaca-sip",
        "feed": "sip",
        "adjustment": "raw",
        "timeframe": "15Min",
        "session_date": day.isoformat(),
        "session_close": "16:00:00",
        "bars_expected": "26",
        "bar_count": "26",
        "complete": "true",
        "schema": "2",
    }
    if any(metadata.get(key) != value for key, value in expected_meta.items()):
        raise ValueError("Explicit complete raw SIP metadata required")
    revision = metadata.get("source_revision")
    if not revision or revision.strip().lower() in ("unknown", "unavailable"):
        raise ValueError("SIP source revision required")
    published = history._instant(metadata.get("fetched_at"), "SIP source")
    opening = datetime.combine(day, time(9, 30), calendar.NEW_YORK)
    closing = datetime.combine(day, time(16), calendar.NEW_YORK)
    if published < closing or (prior and published > captured):
        raise ValueError("SIP publication is incompatible with its source role")
    fields = ("open", "high", "low", "close", "volume")
    if not {"start", *fields} <= columns.keys():
        raise ValueError("Raw SIP columns required")
    starts = [history._instant(value, "SIP bar") for value in columns["start"]]
    expected = [opening + timedelta(minutes=15 * slot) for slot in range(26)]
    if starts not in (expected, expected + [closing]):
        raise ValueError("Exact ordered unique 26-slot SIP grid required")
    if metadata.get("auction_bar") != ("true" if len(starts) == 27 else "false"):
        raise ValueError("Optional closing-row metadata does not match original bytes")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for field in fields
        for value in columns[field]
    ):
        raise ValueError("SIP prices and volume must have numeric source cells")
    try:
        values = np.column_stack(
            [np.asarray(columns[key], dtype=float) for key in fields]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("SIP prices and volume must be numeric") from exc
    if (
        values.shape != (len(starts), 5)
        or not np.isfinite(values).all()
        or np.any(values[:, :4] <= 0)
        or np.any(values[:, 4] < 0)
        or np.any(values[:, 2] > np.minimum(values[:, 0], values[:, 3]))
        or np.any(values[:, 1] < np.maximum(values[:, 0], values[:, 3]))
    ):
        raise ValueError("Malformed raw SIP OHLCV cells")
    return values[:26], published


# Disclose missing action publication proof and refuse action-affected source intervals.
def _actions(path, prior, session, sources):
    columns, _ = _table(path, sources)
    if not {"action_date", "kind", "value"} <= columns.keys():
        raise ValueError("Explicit archived corporate-action columns required")
    for value, kind, amount in zip(
        columns["action_date"], columns["kind"], columns["value"], strict=True
    ):
        try:
            when = date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Corporate action date must be explicit") from exc
        if not isinstance(kind, str) or not kind:
            raise ValueError("Corporate action kind must be explicit")
        _number(amount, "Corporate action value")
        if prior <= when <= session:
            raise ValueError(
                "Corporate action in prior-to-session interval unsupported"
            )


# Read only exact prior/current partitions and retain all recorded basket identities.
def load(market_root, session):
    root = Path(market_root)
    session = date.fromisoformat(str(session))
    years, sessions = calendar.reviewed_sessions()
    if (
        session.year not in years
        or not np.is_busday(np.datetime64(session, "D"), busdaycal=sessions)
        or calendar.session_close(session) != calendar.REGULAR_CLOSE
    ):
        raise ValueError("A reviewed full regular session is required")
    prior = np.busday_offset(
        np.datetime64(session, "D"), -1, busdaycal=sessions
    ).astype(object)
    captured = datetime.combine(session, time(9, 45), calendar.NEW_YORK)
    record_path = root / "desk" / f"asof={prior}" / "desk.json"
    sources = {}
    record = json.loads(history._read(record_path, sources))
    digest = sources[str(record_path.absolute())]["sha256"]
    cash, holdings, intents = _snapshot(record, prior, session, captured, digest)
    context = history.load_context(
        record_path, root / "bars" / f"asof={prior}", session, captured
    )
    for path, receipt in context.provenance["sources"].items():
        if path in sources and sources[path]["sha256"] != receipt["sha256"]:
            raise ValueError("Concurrent research record change prevents a stable read")
        sources[path] = receipt
    names = sorted(set(holdings) | {row["symbol"] for row in intents} | {"SPY", "QQQ"})
    cubes, initial, final, outcomes = {}, {}, {}, {}
    for symbol in names:
        previous, _ = _sip(
            root / "bars_15m_sip" / f"asof={prior}" / f"{symbol}.parquet",
            symbol,
            prior,
            captured,
            sources,
            prior=True,
        )
        current, stamp = _sip(
            root / "bars_15m_sip" / f"asof={session}" / f"{symbol}.parquet",
            symbol,
            session,
            captured,
            sources,
        )
        _actions(
            root / "actions" / f"asof={session}" / f"{symbol}.parquet",
            prior,
            session,
            sources,
        )
        initial[symbol], final[symbol] = float(previous[-1, 3]), float(current[-1, 3])
        arrays = [current[:, i][None].copy() for i in range(5)]
        cube = SessionCube(
            symbol,
            np.array([session], dtype="datetime64[D]"),
            *arrays,
            np.array([initial[symbol]]),
            {},
            np.array([np.nan]),
            np.array([np.nan]),
        )
        for array in (
            cube.dates,
            *arrays,
            cube.prior_close,
            cube.auction_open,
            cube.auction_volume,
        ):
            array.setflags(write=False)
        cubes[symbol] = cube
        outcomes[symbol] = stamp.isoformat()
    history._check_unchanged(sources)
    provenance = {
        "schema": "recorded-timing-inputs/1",
        "session": session.isoformat(),
        "prior_session": prior.isoformat(),
        "record_sha256": digest,
        "required_symbols": names,
        "original_planned_rows": len(intents),
        "context": context.provenance,
        "context_clock": captured.isoformat(),
        "context_clock_is_synthetic": True,
        "historical_prefix_receipts_available": False,
        "raw_reference_basis": REFERENCE_BASIS,
        "training_prior_anchor_equivalent": False,
        "official_close_attestation": False,
        "ratio_scaling_used": False,
        "closing_row_used": False,
        "corporate_actions_publication_verified": False,
        "absence_of_corporate_actions_proven": False,
        "outcome_sources_published_at": outcomes,
        "sources": sources,
    }
    return RecordedTimingInputs(
        session, context, cubes, cash, holdings, intents, initial, final, provenance
    )
