"""Date the market evidence separately from when a process wrote a snapshot."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SNAPSHOT_SECONDS = 900
BAR_SECONDS = 1800


# Accept only timezone-aware timestamps that can be compared unambiguously.
def timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


# Describe the actual candle age; a newly fetched old candle stays old.
def quote_status(quote: dict, now: datetime) -> dict:
    bar = timestamp(quote.get("bar"))
    age = (now - bar).total_seconds() if bar else None
    local = bar.astimezone(NEW_YORK) if bar else None
    current = bool(
        local
        and local.date() == now.astimezone(NEW_YORK).date()
        and local.weekday() < 5
        and 570 <= local.hour * 60 + local.minute < 960
        and age is not None
        and 0 <= age <= BAR_SECONDS
    )
    return {
        "data_at": bar.isoformat() if bar else None,
        "data_age_seconds": age,
        "stale": not current,
    }


# Annotate every quote so one fresh ticker cannot conceal missing or old data.
def describe(snapshot: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    written = timestamp(snapshot.get("as_of"))
    age = (now - written).total_seconds() if written else None
    quotes = snapshot.get("quotes") or {}
    status = {ticker: quote_status(quote, now) for ticker, quote in quotes.items()}
    stale = [ticker for ticker, item in status.items() if item["stale"]]
    dates = [item["data_at"] for item in status.values() if item["data_at"]]
    return {
        **snapshot,
        "age_seconds": age,
        "data_at": min(dates) if dates else None,
        "quote_status": status,
        "stale_symbols": stale,
        "stale": not quotes
        or bool(stale)
        or age is None
        or not 0 <= age <= SNAPSHOT_SECONDS,
    }


# Re-grade only a fresh candle that extends the exact evening decision in use.
def grade_inputs(
    snapshot: dict, record: dict, now: datetime | None = None
) -> tuple[dict, dict]:
    now = now or datetime.now(UTC)
    snapshot = describe(snapshot, now)
    session = record.get("session")
    written = timestamp(snapshot.get("as_of"))
    if (
        not session
        or snapshot.get("decision_session") != session
        or written is None
        or not 0 <= (now - written).total_seconds() <= SNAPSHOT_SECONDS
    ):
        return {}, {}
    eligible = {
        ticker
        for ticker, status in snapshot["quote_status"].items()
        if not status["stale"]
        and timestamp(status["data_at"]).astimezone(NEW_YORK).date().isoformat()
        > session
    }
    inputs = [
        {
            ticker: read
            for ticker, read in (snapshot.get(name) or {}).items()
            if ticker in eligible
        }
        for name in ("technical", "value")
    ]
    return inputs[0], inputs[1]
