"""Watch a name in real time and say when it crosses a trailing stop.

    python -m backend.cli.market_watch IREN --stop 0.12
    python -m backend.cli.market_watch IREN --stop 0.12 --high 46.10 --interval 20
    python -m backend.cli.market_watch IREN NVDA --stop 0.08 --floor 38.00

What it is
----------
A position bought on a dip that then ran twenty-five percent in five
sessions has, by this book's history, no edge either way from there and
a fat left tail: the worst tenth of such moves gave back a quarter
within twenty sessions. The one decision left is how much of that tail
to carry, and a trailing stop is how the answer is enforced. This
watches the price and says when the stop is hit. It places no order: the
person's brokerage is theirs, and the desk never logs into it.

How it reads
------------
Alpaca's free market-data feed, the latest trade every `--interval`
seconds, under the same keys the desk uses. The running high starts at
`--high` when given (the high since the entry, from the person's own
record) and otherwise at the first print seen. The stop is `--stop` off
that high; `--floor` is an absolute level below which it also fires.
Each poll prints the last price, the high, the stop level and the room
left; a cross prints in capitals with a bell and keeps printing until
the watch is stopped, because a missed alert is the one that matters.

It is deliberately dumb. No prediction, no re-arming, no averaging: the
book's measurement is that after such a move nothing predicts the turn,
so the tool's whole job is to notice a level and say so.
"""

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.market.alpaca import AlpacaUnavailableError, credentials

ENV_FILE = Path(".env")
KEYS = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")

LATEST_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
TIMEOUT = 15.0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Watch a trailing stop.")
    parser.add_argument("symbols", nargs="+")
    parser.add_argument(
        "--stop", type=float, default=0.12, help="fraction off the high"
    )
    parser.add_argument("--high", type=float, default=None, help="the high so far")
    parser.add_argument("--floor", type=float, default=None, help="an absolute level")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds")
    parser.add_argument("--once", action="store_true", help="one poll, then exit")
    return parser


# The Alpaca keys from the environment, else from the repository's .env,
# which is where the desk keeps them and is never committed. Nothing is
# printed; the values go into this process only.
def keys_from_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Return the APCA keys found in `path`, without touching the environment."""
    found: dict[str, str] = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        if name.strip() in KEYS:
            found[name.strip()] = value.strip().strip('"').strip("'")
    return found


# Headers for the feed: the environment first, the .env file second.
def headers_for_feed() -> dict[str, str]:
    """Return the auth headers, reading .env when the environment lacks them."""
    try:
        return credentials()
    except AlpacaUnavailableError:
        for name, value in keys_from_env_file().items():
            os.environ.setdefault(name, value)
        return credentials()


# The latest trade price for one symbol, or None when the feed has none.
def latest_price(symbol: str, headers: dict, get=None) -> float | None:
    """Return the last trade price, or None if unavailable."""
    getter = get or httpx.get
    response = getter(
        LATEST_URL.format(symbol=symbol), headers=headers, timeout=TIMEOUT
    )
    if response.status_code != 200:
        return None
    trade = response.json().get("trade") or {}
    price = trade.get("p")
    return float(price) if price else None


# The state of one watched name: its running high and whether it fired.
class Watch:
    """A trailing stop on one symbol, updated print by print."""

    def __init__(
        self, symbol: str, stop: float, high: float | None, floor: float | None
    ):
        self.symbol = symbol
        self.stop = stop
        self.high = high
        self.floor = floor
        self.fired = False

    # The level the stop sits at now, or None before any print.
    def level(self) -> float | None:
        """Return the current stop level."""
        if self.high is None:
            return None
        trailing = self.high * (1.0 - self.stop)
        return max(trailing, self.floor) if self.floor else trailing

    # Fold in a print; return the line to show.
    def update(self, price: float) -> str:
        """Update the high and the fired state; return a status line."""
        self.high = price if self.high is None else max(self.high, price)
        level = self.level()
        room = (price - level) / price if level else float("nan")
        hit = level is not None and price <= level
        self.fired = self.fired or hit
        stamp = datetime.now(UTC).astimezone().strftime("%H:%M:%S")
        line = (
            f"{stamp} {self.symbol:6} last {price:8.2f}  high {self.high:8.2f}  "
            f"stop {level:8.2f}  room {room:+6.1%}"
        )
        if self.fired:
            line += "   *** STOP HIT ***\a"
        return line


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    headers = headers_for_feed()
    watches = [Watch(s.upper(), args.stop, args.high, args.floor) for s in args.symbols]
    print(
        f"watching {', '.join(w.symbol for w in watches)}: {args.stop:.0%} off the high"
        + (f", floor {args.floor:.2f}" if args.floor else "")
        + f", every {args.interval:.0f}s. No orders are placed."
    )
    while True:
        for watch in watches:
            price = latest_price(watch.symbol, headers)
            if price is None:
                print(f"{watch.symbol}: no print from the feed")
                continue
            print(watch.update(price), flush=True)
        if args.once:
            return
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
