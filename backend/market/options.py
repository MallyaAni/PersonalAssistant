"""Option open interest by strike: the put wall, the call wall, and a gamma proxy.

Traders read the strikes where open interest piles up as levels: the
put wall below the price, where dealers hedging short puts buy the dip,
and the call wall above it, where they sell the rip. The evidence that
is peer-reviewed is narrower than the practice: closes cluster at
strikes on expiration days (Ni, Pearson and Poteshman, JFE 2005) and
dealer gamma drives intraday momentum or reversal at the index level
(Baltussen, Da, Lammers and Martens, JFE 2021). Whether the walls say
anything over the desk's twenty-session horizon on these names is
untested, because nobody keeps a free history of open interest. This
module starts the history: the chain is fetched nightly for the book
names from Cboe's delayed feed and stored as an immutable frame per
session, so the question can be asked once a quarter of snapshots
exists.

Everything here is read-time arithmetic on stored rows. Nothing trades
on it.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

# Cboe's delayed chain: every listed contract with open interest, implied
# volatility and the greeks, and the underlying's price, no key needed.
CHAIN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
KIND = "options"
# Contracts further out than this are not kept: the book's horizon is
# twenty sessions and the walls a trader draws are the near ones.
MAX_DAYS = 180
# How far from the price a wall may sit before it is a curiosity rather
# than a level a trader would draw.
WALL_RANGE = 0.25
# The expiries a wall is read across: open interest is summed per strike
# over every expiry from tomorrow to this many days out. Reading one
# expiry at a time put ORCL's put wall on a weekly with 2,224 contracts
# while the monthly two days nearer held 55,000 at one strike.
WALL_DAYS = 60
# A strike needs this much open interest, summed, to be called a wall.
MIN_WALL_OI = 500
_SYMBOL = re.compile(r"^([A-Z.]+?)(\d{6})([CP])(\d{8})$")


@dataclass(frozen=True)
class ChainRow:
    """One contract, as the chain reported it."""

    expiry: date
    kind: str  # call or put
    strike: float
    open_interest: int
    volume: int
    implied_volatility: float
    gamma: float  # per share, from the feed


# One contract's required fields for OI concentration arithmetic only.
@dataclass(frozen=True)
class OIRow:
    """Expiry, side, raw strike and open interest, without optional greeks."""

    expiry: date
    kind: str
    strike: float
    open_interest: int


# OI concentration levels without a gamma estimate or fabricated default.
@dataclass(frozen=True)
class OILevels:
    """Levels aggregated across the eligible expiries at a raw reference price."""

    price: float
    expiry: date | None
    put_wall: float | None
    put_wall_oi: int
    call_wall: float | None
    call_wall_oi: int
    through: date | None = None


@dataclass(frozen=True)
class Walls:
    """The levels read off a chain at a price."""

    price: float
    expiry: date | None
    put_wall: float | None
    put_wall_oi: int
    call_wall: float | None
    call_wall_oi: int
    net_gamma: float  # dealer gamma proxy: calls long, puts short, shares per 1% move
    through: date | None = None  # the farthest expiry the walls were summed over


# An OCC-style symbol into (expiry, kind, strike), or None.
def parse_symbol(symbol: str) -> tuple[date, str, float] | None:
    """Return (expiry, "call"|"put", strike) from e.g. ADBE260911C00130000."""
    m = _SYMBOL.match(symbol)
    if not m:
        return None
    yymmdd, side, strike = m.group(2), m.group(3), m.group(4)
    try:
        expiry = datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None
    return expiry, ("call" if side == "C" else "put"), int(strike) / 1000.0


# Pure: a Cboe chain payload into the price and the rows worth keeping.
def parse_chain(
    payload: dict[str, Any], today: date, max_days: int = MAX_DAYS
) -> tuple[float | None, list[ChainRow]]:
    """Return (underlying price, rows) from a Cboe delayed-quotes payload."""
    data = payload.get("data") or {}
    price = data.get("current_price")
    rows: list[ChainRow] = []
    for row in data.get("options") or []:
        parsed = parse_symbol(str(row.get("option", "")))
        if parsed is None:
            continue
        expiry, kind, strike = parsed
        if (expiry - today).days > max_days or expiry < today:
            continue
        try:
            rows.append(
                ChainRow(
                    expiry=expiry,
                    kind=kind,
                    strike=strike,
                    open_interest=int(row.get("open_interest") or 0),
                    volume=int(row.get("volume") or 0),
                    implied_volatility=float(row.get("iv") or 0.0),
                    gamma=float(row.get("gamma") or 0.0),
                )
            )
        except (TypeError, ValueError):
            continue
    return (float(price) if price is not None else None), rows


# The frame stored per ticker per session.
def frame(rows: list[ChainRow]) -> dict[str, list]:
    """Return the columns of an options frame."""
    return {
        "expiry": [r.expiry.isoformat() for r in rows],
        "kind": [r.kind for r in rows],
        "strike": [r.strike for r in rows],
        "open_interest": [r.open_interest for r in rows],
        "volume": [r.volume for r in rows],
        "implied_volatility": [r.implied_volatility for r in rows],
        "gamma": [r.gamma for r in rows],
    }


def rows_from_frame(columns: dict[str, list]) -> list[ChainRow]:
    """Return the ChainRows of a stored frame."""
    return [
        ChainRow(
            expiry=date.fromisoformat(str(columns["expiry"][i])),
            kind=str(columns["kind"][i]),
            strike=float(columns["strike"][i]),
            open_interest=int(columns["open_interest"][i]),
            volume=int(columns["volume"][i]),
            implied_volatility=float(columns["implied_volatility"][i]),
            gamma=float(columns["gamma"][i]),
        )
        for i in range(len(columns.get("strike", [])))
    ]


# Sum eligible OI by strike and select each side's maximum, with nearer-strike ties.
def oi_levels(  # noqa: C901 - two sides, one pass each
    rows: Sequence[OIRow | ChainRow],
    price: float,
    today: date,
    min_days: int = 1,
    max_days: int = WALL_DAYS,
    min_oi: int = MIN_WALL_OI,
) -> OILevels:
    """Return OI levels within the price range, summed over eligible expiries."""
    eligible = sorted(
        {r.expiry for r in rows if min_days <= (r.expiry - today).days <= max_days}
    )
    expiry = eligible[0] if eligible else None
    through = eligible[-1] if eligible else None
    put_wall = call_wall = None
    put_oi = call_oi = 0
    if expiry is not None and price > 0:
        lo, hi = price * (1.0 - WALL_RANGE), price * (1.0 + WALL_RANGE)
        puts: dict[float, int] = {}
        calls: dict[float, int] = {}
        for r in rows:
            if r.expiry not in eligible or r.open_interest <= 0:
                continue
            if r.kind == "put" and lo <= r.strike <= price:
                puts[r.strike] = puts.get(r.strike, 0) + r.open_interest
            if r.kind == "call" and price <= r.strike <= hi:
                calls[r.strike] = calls.get(r.strike, 0) + r.open_interest
        for strike, oi in puts.items():
            if oi >= min_oi and (oi > put_oi or (oi == put_oi and strike > put_wall)):
                put_wall, put_oi = strike, oi
        for strike, oi in calls.items():
            if oi >= min_oi and (
                oi > call_oi or (oi == call_oi and strike < call_wall)
            ):
                call_wall, call_oi = strike, oi
    return OILevels(price, expiry, put_wall, put_oi, call_wall, call_oi, through)


# Combine the shared OI levels with the unchanged legacy all-row gamma proxy.
def walls(
    rows: list[ChainRow],
    price: float,
    today: date,
    min_days: int = 1,
    max_days: int = WALL_DAYS,
    min_oi: int = MIN_WALL_OI,
) -> Walls:
    """Return the Walls read off `rows` at `price`, summed over the near expiries."""
    levels = oi_levels(rows, price, today, min_days, max_days, min_oi)
    net = 0.0
    for r in rows:
        shares = r.gamma * r.open_interest * 100 * price * 0.01
        net += shares if r.kind == "call" else -shares
    return Walls(
        levels.price,
        levels.expiry,
        levels.put_wall,
        levels.put_wall_oi,
        levels.call_wall,
        levels.call_wall_oi,
        net,
        levels.through,
    )


# Fetch one name's chain. `transport` returns (status, headers, body)
# like the bars fetcher's; the parse is pure.
def fetch_chain(
    ticker: str, transport, today: date
) -> tuple[float | None, list[ChainRow]]:
    """Return (price, rows) for the name, or (None, []) when refused."""
    status, _headers, body = transport(CHAIN_URL.format(ticker=ticker))
    if status != 200:
        return None, []
    try:
        payload = json.loads(body)
    except ValueError:
        return None, []
    return parse_chain(payload, today)
