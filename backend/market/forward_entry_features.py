"""Original entry features from prior daily history and an actually observed prefix.

The caller authenticates source bytes and grade publication. These pure
observations neither acquire prices nor construct labels, future fills or orders.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as clocks
from backend.market import learned_entry_data as original
from backend.market.daily_arithmetic_bridge import _as_of, _hash


# Preserve the registered raw prefix ratios, including missing and malformed bars.
def _prefix(record, starts, completed, observed):
    if not isinstance(record, dict):
        raise ValueError("Explicit prefix record required")
    published = _as_of(record["published_at"])
    received = [_as_of(value) for value in record["starts"]]
    if received != starts or not completed <= published <= observed:
        raise ValueError("Consecutive completed and actually published prefix required")
    arrays = []
    for name in ("open", "high", "low", "close", "volume"):
        values = np.asarray(record[name])
        if values.shape != (len(starts),) or values.dtype.kind not in "fiu":
            raise ValueError("Aligned numeric raw prefix columns required")
        arrays.append(values.astype(np.float64, copy=True))
    prior = np.asarray(record["prior_close"])
    if prior.ndim != 0 or prior.dtype.kind not in "fiu":
        raise ValueError("Explicit raw prior-close scalar required")
    prior = float(prior)
    opening, high, low, closing, volume = arrays
    valid = bool(
        np.isfinite(prior)
        and prior > 0
        and all(np.isfinite(value).all() for value in arrays)
        and np.all(opening > 0)
        and np.all(low > 0)
        and np.all(volume >= 0)
        and np.all(low <= np.minimum(opening, closing))
        and np.all(high >= np.maximum(opening, closing))
        and np.all(high >= low)
    )
    with np.errstate(all="ignore"):
        count = np.arange(1, len(starts) + 1)
        running_high = np.maximum.accumulate(high)
        running_low = np.minimum.accumulate(low)
        width = running_high - running_low
        running_volume = np.cumsum(volume)
        vwap = np.cumsum(closing * volume) / running_volume
        moves = np.log(closing / np.concatenate(([prior], closing[:-1])))
        mean = np.cumsum(moves) / count
        variance = np.cumsum(moves**2) / count - mean**2
        location = np.divide(
            closing - running_low, width, out=np.full_like(width, 0.5), where=width > 0
        )
        values = np.stack(
            (
                np.full(len(starts), np.log(opening[0] / prior)),
                np.log(closing / opening[0]),
                moves,
                width / prior,
                location,
                closing / vwap - 1,
                np.sqrt(np.maximum(variance, 0)),
                count / 26,
            ),
            axis=-1,
        )
    valid = valid and bool(running_volume[-1] > 0 and np.isfinite(values[-1]).all())
    clocks = np.array(
        [value.astimezone(UTC).replace(tzinfo=None) for value in received],
        dtype="datetime64[ns]",
    )
    identity = {
        **{
            name: _hash(value)
            for name, value in zip(
                ("open", "high", "low", "close", "volume"), arrays, strict=True
            )
        },
        "starts": _hash(clocks),
        "prior_close": _hash(np.array(prior)),
        "published_at": published.isoformat(),
    }
    return values[-1], valid, identity


# Score only the latest completed regular prefix using exactly the original history.
def observe(panel, grades, eligible, prefixes, *, observed_at, daily_as_of):
    dates, prices, symbols, grades, eligible = original._validate_panel(
        panel, grades, eligible
    )
    observed, daily_clock = _as_of(observed_at), _as_of(daily_as_of)
    session = observed.date()
    years, calendar = exchange.reviewed_sessions()
    expected = np.arange(dates[0], np.datetime64(session))
    expected = expected[np.is_busday(expected, busdaycal=calendar)]
    opening = datetime.combine(session, exchange.REGULAR_OPEN, exchange.NEW_YORK)
    closing = datetime.combine(
        session, exchange.session_close(session), exchange.NEW_YORK
    )
    count = int((observed - opening).total_seconds() // 900)
    if (
        session.year not in years
        or any(day.astype(object).year not in years for day in dates)
        or not np.is_busday(np.datetime64(session), busdaycal=calendar)
        or not np.array_equal(dates, expected)
        or not 1 <= count <= original.DECISIONS
        or observed > closing
        or datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        )
        > daily_clock
        or daily_clock > observed
        or not isinstance(prefixes, dict)
        or set(prefixes) - set(symbols)
    ):
        raise ValueError(
            "Complete prior history and current regular observation required"
        )
    completed = opening + timedelta(minutes=15 * count)
    starts = [opening + timedelta(minutes=15 * index) for index in range(count)]
    # The missing current-day row supplies a clock, never an official price.
    padded_prices = np.vstack((prices, np.full(len(symbols), np.nan)))
    context, available = original._daily_context(
        padded_prices,
        np.vstack((grades, np.full(len(symbols), -1))),
        np.vstack((eligible, np.zeros(len(symbols), dtype=bool))),
        symbols.index("SPY"),
    )
    values = np.full(
        (len(symbols), len(original.FEATURE_NAMES)), np.nan, dtype=np.float32
    )
    valid = np.zeros(len(symbols), dtype=bool)
    identities = {}
    for stock, symbol in enumerate(symbols):
        if symbol not in prefixes:
            continue
        prefix, good, identities[symbol] = _prefix(
            prefixes[symbol], starts, completed, observed
        )
        values[stock, :13] = context[-1, stock]
        values[stock, 13:] = prefix
        valid[stock] = good and available[-1, stock]
    root = Path(__file__).resolve().parents[2]
    sources = (
        Path(__file__),
        Path(original.__file__),
        Path(exchange.__file__),
        Path(clocks.__file__),
        exchange.HISTORICAL_SESSIONS_PATH,
        exchange.HOLIDAYS_PATH,
        exchange.EARLY_CLOSES_PATH,
    )
    return {
        "features": values,
        "valid": valid,
        "symbols": symbols,
        "feature_names": original.FEATURE_NAMES,
        "session": session.isoformat(),
        "clock": count - 1,
        "completed_at": completed.isoformat(),
        "observed_at": observed.isoformat(),
        "daily_as_of": daily_clock.isoformat(),
        "timing_supported": completed + timedelta(minutes=15) < closing and count <= 23,
        "identity": {
            "prior_dates": _hash(dates),
            "prior_prices": _hash(prices),
            "prior_grades": _hash(grades),
            "prior_eligible": _hash(eligible),
            "prefixes": identities,
            "sources": {
                str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
                for path in sources
            },
        },
    }
