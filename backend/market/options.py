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


# The walls at a price: the strike with the most put open interest at or
# below the price and the most call open interest at or above it, within
# WALL_RANGE, on the nearest expiry at least `min_days` away (a chain
# that expires tomorrow is noise for a twenty-session book). The gamma
# proxy sums open interest times the feed's gamma across every stored
# expiry with the usual dealer-side convention, calls long and puts
# short, as shares dealers must trade per one percent move.
def walls(rows: list[ChainRow], price: float, today: date, min_days: int = 5) -> Walls:
    """Return the Walls read off `rows` at `price`."""
    eligible = sorted({r.expiry for r in rows if (r.expiry - today).days >= min_days})
    expiry = eligible[0] if eligible else None
    put_wall = call_wall = None
    put_oi = call_oi = 0
    if expiry is not None and price > 0:
        lo, hi = price * (1.0 - WALL_RANGE), price * (1.0 + WALL_RANGE)
        for r in rows:
            if r.expiry != expiry or r.open_interest <= 0:
                continue
            if r.kind == "put" and lo <= r.strike <= price and r.open_interest > put_oi:
                put_wall, put_oi = r.strike, r.open_interest
            if (
                r.kind == "call"
                and price <= r.strike <= hi
                and r.open_interest > call_oi
            ):
                call_wall, call_oi = r.strike, r.open_interest
    net = 0.0
    for r in rows:
        shares = r.gamma * r.open_interest * 100 * price * 0.01
        net += shares if r.kind == "call" else -shares
    return Walls(price, expiry, put_wall, put_oi, call_wall, call_oi, net)


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
