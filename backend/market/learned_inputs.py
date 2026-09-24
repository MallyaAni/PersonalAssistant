"""Freeze the inputs the experimental desk learner actually saw each night.

These records are prospective observations, not reconstructed historical
features or executable recommendations.  A later training adapter must use
``captured_at`` as the availability time and reconcile price bases before
forming forward-return labels.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import fundamentals_asof, growth_pilot, language
from backend.market.store import MarketStore

SCHEMA = "desk-learned-inputs/1"


# Preserve missing or invalid numerical evidence as JSON null, never zero.
def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


# Copy one feature vector with stable names and explicit missing values.
def _named(names: tuple[str, ...], values: np.ndarray) -> dict[str, float | None]:
    return {name: _number(value) for name, value in zip(names, values, strict=True)}


# Measure the last twenty sessions' range on one split-adjusted price basis.
def _adjusted_range20(panel, last: int, column: int) -> float | None:
    if last < 19:
        return None
    highs = panel.high[last - 19 : last + 1, column]
    lows = panel.low[last - 19 : last + 1, column]
    closes = panel.close[last - 19 : last + 1, column]
    adjusted = panel.adj_close[last - 19 : last + 1, column]
    if (
        not np.isfinite(closes).all()
        or not np.isfinite(adjusted).all()
        or np.any(closes <= 0)
        or np.any(adjusted <= 0)
        or not np.isfinite(highs).all()
        or not np.isfinite(lows).all()
    ):
        return None
    ratio = adjusted / closes
    return _number((np.max(highs * ratio) - np.min(lows * ratio)) / adjusted[-1])


# Select only releases whose reaction session had begun by this observation.
def _known_tone(store: MarketStore, ticker: str, session: date):
    frame = store.read_frame(language.TONE_KIND, ticker, session)
    if frame is None:
        return ()
    return tuple(
        row
        for row in language.records_from_frame(frame[0])
        if row.reaction_date <= session
    )


# Freeze same-vintage desk, price, filing and release inputs after the record.
def build(
    record: dict, panel, store: MarketStore, record_sha256: str, captured_at: datetime
) -> dict:
    """Return a JSON-ready observation; missing evidence remains explicit."""
    session = date.fromisoformat(record["session"])
    record_written = datetime.fromisoformat(record["written"])
    if (
        captured_at.tzinfo is None
        or record_written.tzinfo is None
        or captured_at < record_written
        or captured_at.date() < session
    ):
        raise ValueError("desk record lacks a valid observation timestamp")
    if str(panel.dates[-1]) != record["session"]:
        raise ValueError("panel session differs from the saved desk record")
    if len(record_sha256) != 64:
        raise ValueError("source record hash is required")

    data, fundamental_values, fundamental_names = fundamentals_asof.features(
        panel, fundamentals_asof.load_versions(store, panel, session)
    )
    last = len(panel.dates) - 1
    price_count = len(growth_pilot.FEATURE_NAMES)
    known_tone = {
        ticker: _known_tone(store, ticker, session) for ticker in panel.tickers
    }
    tone_values = language.tone_features(panel, known_tone)
    bar_sources = dict(
        zip(panel.tickers, store.describe(panel.tickers, session), strict=True)
    )
    book_weights = {
        row["ticker"]: _number(row.get("weight"))
        for row in record.get("book", ())
    }
    rows = {}
    for column, ticker in enumerate(panel.tickers):
        tone = known_tone[ticker][-1] if known_tone[ticker] else None
        grade = (record.get("grades") or {}).get(ticker) or {}
        bar_source = bar_sources[ticker]
        fundamental_asof = store._latest_of_kind(
            fundamentals_asof.KIND, ticker, session
        )
        tone_asof = store._latest_of_kind(language.TONE_KIND, ticker, session)
        # A valid bar on this session is required for a tradable observation.
        current_bar = all(
            _number(getattr(panel, field)[last, column]) is not None
            for field in ("open", "high", "low", "close", "adj_close", "volume")
        )
        previous = None
        if tone is not None:
            previous = {
                "accession": tone.accession,
                "reaction_date": tone.reaction_date.isoformat(),
                "prompt_version": tone.prompt_version,
                "model": tone.model,
            }
        rows[ticker] = {
            "desk_grade": grade.get("grade"),
            "desk_score": _number(grade.get("score")),
            "desk_side": grade.get("side"),
            "recorded_book_weight": book_weights.get(ticker),
            "current_bar_present": current_bar,
            "current_bar_complete": bool(
                current_bar
                and bar_source
                and bar_source.complete_through
                and bar_source.complete_through >= session
            ),
            "bar_source_asof": (
                bar_source.asof.isoformat() if bar_source else None
            ),
            "bar_source_complete_through": (
                bar_source.complete_through.isoformat()
                if bar_source and bar_source.complete_through
                else None
            ),
            "price": {
                name: _number(getattr(panel, name)[last, column])
                for name in ("open", "high", "low", "close", "adj_close", "volume")
            },
            "price_features": _named(
                growth_pilot.FEATURE_NAMES,
                fundamental_values[last, column, :price_count],
            ) | {"range20_adjusted": _adjusted_range20(panel, last, column)},
            "fundamental_features": _named(
                tuple(fundamental_names[price_count:]),
                fundamental_values[last, column, price_count:],
            ),
            "fundamental_source_asof": (
                fundamental_asof.isoformat() if fundamental_asof else None
            ),
            "desk_fundamental_rank": _number(
                (grade.get("ranks") or {}).get("fundamental")
            ),
            "tone": previous,
            "tone_source_asof": tone_asof.isoformat() if tone_asof else None,
            "tone_features": _named(
                language.FEATURE_NAMES,
                tone_values[last, column],
            ),
        }
    return {
        "schema": SCHEMA,
        "session": session.isoformat(),
        "captured_at": captured_at.isoformat(),
        "record_written_at": record_written.isoformat(),
        "record_sha256": record_sha256,
        "code_revision": (record.get("provenance") or {}).get("code_revision"),
        "incumbent_rule": ((record.get("provenance") or {}).get("rule") or {}),
        "price_basis": (
            "daily raw OHLC and retrospectively adjusted close, "
            "each frozen at capture"
        ),
        "membership_basis": (
            "recorded desk grades; historical index membership not established"
        ),
        "benchmark": panel.benchmark,
        "universe": list(panel.tickers),
        "market_features": _named(
            (
                *growth_pilot.FEATURE_NAMES,
                "breadth",
                "fomc_ahead_30",
                "fomc_since_30",
            ),
            data.market[last],
        ),
        "regime": record.get("regime"),
        "stocks": rows,
    }


# Publish one byte-stable file, refusing to revise an earlier observation.
def capture(record_path: Path, record: dict, panel, store: MarketStore) -> Path:
    """Write the prospective input snapshot once, without overwriting."""
    path = Path(store.root) / "learned_inputs" / f"asof={record['session']}.json"
    digest = sha256(record_path.read_bytes()).hexdigest()
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("record_sha256") != digest:
            raise FileExistsError(f"existing learned observation differs: {path}")
        return path
    payload = build(record, panel, store, digest, datetime.now(tz=UTC))
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".learned-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise FileExistsError(
                f"learned observation appeared during capture: {path}"
            ) from None
    finally:
        os.unlink(temporary)
    return path
