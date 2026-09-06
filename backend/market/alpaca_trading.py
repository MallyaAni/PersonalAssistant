"""The Alpaca paper-trading account: read it, place orders on it.

The desk decides at the close what the book should be at the next open;
this is the hand that carries it out on the paper account, and the eyes
that read back the equity, the positions and their profit or loss. Orders
are market-on-open, the same fill the backtest assumes. Every call goes
through one small request function with the keys from the environment,
and a transport can be passed in so the logic is tested without a network.
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib import error, request

PAPER_URL = "https://paper-api.alpaca.markets/v2"
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class AlpacaTradingError(RuntimeError):
    """The account could not be read or an order was refused."""


@dataclass(frozen=True, slots=True)
class Position:
    """One held position as the account reports it."""

    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float
    current_price: float
    unrealized_pl: float


@dataclass(frozen=True, slots=True)
class Account:
    """The account's money."""

    equity: float
    cash: float
    buying_power: float
    last_equity: float


# The default transport: one HTTPS request with the JSON body given.
def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    """Return (status, body) for the request."""
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=60) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()


class AlpacaTradingClient:
    """The paper account through the REST API."""

    def __init__(
        self,
        key: str,
        secret: str,
        base_url: str = PAPER_URL,
        transport: Transport = urllib_transport,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.transport = transport

    # One request; a non-2xx status is an error with the body's message.
    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        payload = json.dumps(body).encode() if body is not None else None
        status, raw = self.transport(
            method, self.base_url + path, self.headers, payload
        )
        text = raw.decode("utf-8", "replace") if raw else ""
        if status >= 300:
            raise AlpacaTradingError(f"{method} {path} -> {status}: {text[:300]}")
        return json.loads(text) if text else None

    # The account's money.
    def account(self) -> Account:
        """Return the Account."""
        data = self._call("GET", "/account")
        return Account(
            equity=float(data["equity"]),
            cash=float(data["cash"]),
            buying_power=float(data["buying_power"]),
            last_equity=float(data.get("last_equity", data["equity"])),
        )

    # Every open position.
    def positions(self) -> list[Position]:
        """Return the positions held."""
        rows = self._call("GET", "/positions") or []
        return [
            Position(
                symbol=row["symbol"],
                qty=float(row["qty"]),
                market_value=float(row["market_value"]),
                avg_entry_price=float(row["avg_entry_price"]),
                current_price=float(row["current_price"]),
                unrealized_pl=float(row["unrealized_pl"]),
            )
            for row in rows
        ]

    # Whether the market is open now and when it next opens.
    def clock(self) -> dict[str, Any]:
        """Return the market clock."""
        return self._call("GET", "/clock")

    # Orders waiting to fill.
    def open_orders(self) -> list[dict[str, Any]]:
        """Return the open orders."""
        return self._call("GET", "/orders?status=open&limit=500") or []

    # Cancel every open order, so a day's plan never stacks on the last one.
    def cancel_open_orders(self) -> None:
        """Cancel all open orders."""
        self._call("DELETE", "/orders")

    # A whole-share market order for the next open.
    def submit_market_on_open(self, symbol: str, qty: int, side: str) -> dict[str, Any]:
        """Submit a market-on-open order and return the order as accepted."""
        if qty <= 0:
            raise AlpacaTradingError(f"{symbol}: quantity must be positive")
        if side not in ("buy", "sell"):
            raise AlpacaTradingError(f"{symbol}: side must be buy or sell")
        return self._call(
            "POST",
            "/orders",
            {
                "symbol": symbol,
                "qty": str(int(qty)),
                "side": side,
                "type": "market",
                "time_in_force": "opg",
            },
        )


# The client from the environment's keys, or an error naming the missing one.
def client_from_env(transport: Transport = urllib_transport) -> AlpacaTradingClient:
    """Return the paper client for APCA_API_KEY_ID / APCA_API_SECRET_KEY."""
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        raise AlpacaTradingError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required")
    base = os.environ.get("APCA_API_BASE_URL", PAPER_URL)
    if "paper" not in base:
        raise AlpacaTradingError("only the paper endpoint is allowed here")
    return AlpacaTradingClient(key, secret, base, transport)
