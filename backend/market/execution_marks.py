"""Delayed consolidated outcome labels, separate from frozen execution decisions."""

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from backend.market import alpaca, alpaca_trading, entry_timing
from backend.market import bounded_execution as bounded
from backend.market import execution_forward as forward

VERSION = "execution-endpoint-labels/3"
PLAN = (
    Path(__file__).parents[2] / "docs/research/funded-execution-valuation-2026-10-02.md"
)
URL = "https://data.alpaca.markets/v2/stocks/quotes"


# Validate original receipt bytes and terminal closing outcomes before using prices.
def auction_receipt(receipt, order, start, close):
    if receipt["http_status"] != 200:
        return None
    body = receipt["body"].encode()
    if hashlib.sha256(body).hexdigest() != receipt["body_sha256"]:
        raise ValueError("Paper receipt bytes changed")
    row = json.loads(receipt["body"])
    submitted = bounded.instant(row.get("submitted_at"))
    received = bounded.instant(receipt.get("received_at"))
    if (
        any(row.get(k) != order[k] for k in ("client_order_id", "symbol", "side"))
        or row.get("type") != "market"
        or row.get("time_in_force") != "cls"
        or submitted is None
        or not start <= submitted < close
        or received is None
        or received < close
    ):
        raise ValueError("Receipt is not this cohort's closing order")
    if row.get("status") not in ("filled", "expired", "canceled", "rejected"):
        return None
    qty = forward.amount(row.get("filled_qty"), whole=True)
    requested = forward.amount(row.get("qty"), whole=True)
    if qty > requested or requested > order["qty"]:
        raise ValueError("Broker quantities exceed the frozen opportunity")
    price = bounded.positive(row.get("filled_avg_price"))
    filled = bounded.instant(row.get("filled_at"))
    if qty and (price is None or filled is None or not submitted <= filled <= close):
        raise ValueError("Closing fill price/time unavailable")
    if row["status"] == "filled" and not qty:
        raise ValueError("Filled receipt has no shares")
    return {
        "qty": qty,
        "price": price,
        "status": row["status"],
        "filled_at": row.get("filled_at"),
    }


# Resolve only unsupported auctions from matched receipts under unchanged cash stress.
def observed_auctions(frozen, proxy, receipts):
    if not receipts["complete"] or receipts["manifest_sha256"] != forward.digest(
        frozen
    ):
        raise ValueError("Complete matched paper receipt evidence required")
    rows = {row["client_order_id"]: row for row in receipts["receipts"]}
    expected = {op["order"]["client_order_id"] for op in frozen["opportunities"]}
    if len(rows) != len(receipts["receipts"]) or set(rows) != expected:
        raise ValueError("Common receipt opportunity identities required")
    result = deepcopy(proxy)
    start = bounded.instant(frozen["started_at"])
    close = entry_timing.session_clock(start.astimezone(entry_timing.NEW_YORK).date())[
        "close"
    ]
    for arm in result["results"]:
        if arm["mode"] != "incumbent":
            continue
        book, cash, spent = arm["book"], arm["book"]["cash"], 0.0
        for op in frozen["opportunities"]:
            order = op["order"]
            outcome = arm["opportunities"][order["client_order_id"]]
            if outcome["status"] != "unsupported_auction":
                continue
            observed = auction_receipt(
                rows[order["client_order_id"]], order, start, close
            )
            if observed is None:
                continue
            qty, used = auction_fill(
                book, order, observed, arm["cost_bps"] / 10000, max(0, cash - spent)
            )
            spent += used
            outcome.update(
                status="observed_auction_" + observed["status"],
                observed_filled_qty=observed["qty"],
                filled_qty=qty,
                unfilled_qty=order["qty"] - qty,
                filled_at=observed["filled_at"],
            )
        arm["execution_complete"] = not any(
            o["status"] == "unsupported_auction" for o in arm["opportunities"].values()
        )
    result["valuation_horizon"] = "regular_close_with_observed_paper_auctions"
    result["observed_quote_ended_at"] = proxy["ended_at"]
    result["ended_at"] = close.isoformat()
    result["paper_receipt_sha256"] = forward.digest(receipts)
    return result


# Apply observed auction quantities without borrowing or same-batch sale funding.
def auction_fill(book, order, observed, rate, cash):
    qty, price = observed["qty"], observed["price"]
    if qty and order["side"] == "buy":
        qty = min(qty, math.floor(cash / (price * (1 + rate))))
    elif qty:
        qty = min(qty, book["holdings"].get(order["symbol"], 0))
    used = 0
    if qty:
        notional, fee = forward.post_fill(
            book, order["symbol"], order["side"], qty, price, rate
        )
        used = notional + fee if order["side"] == "buy" else 0
    return qty, used


# Preserve paper-broker receipts for frozen IDs using GET only, without headers.
def capture_receipts(frozen, output, *, client=None, clock=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    client = client or alpaca_trading.client_from_env()
    if client.base_url != alpaca_trading.PAPER_URL:
        raise ValueError("Paper-only receipt evidence required")
    clock = clock or (lambda: datetime.now(UTC))
    rows = []
    for opportunity in frozen["opportunities"]:
        order = opportunity["order"]
        query = urlencode({"client_order_id": order["client_order_id"]})
        status, body = client.transport(
            "GET",
            client.base_url + "/orders:by_client_order_id?" + query,
            client.headers,
            None,
        )
        row = {
            "client_order_id": order["client_order_id"],
            "received_at": clock().isoformat(),
            "http_status": status,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body": body.decode("utf-8"),
        }
        rows.append(row)
        if status not in (200, 404):
            forward.exclusive(
                output,
                {
                    "manifest_sha256": forward.digest(frozen),
                    "complete": False,
                    "receipts": rows,
                },
            )
            raise ValueError(f"Paper receipt unavailable: HTTP {status}")
        if status == 200:
            payload = json.loads(row["body"])
            if any(
                payload.get(k) != order[k]
                for k in ("client_order_id", "symbol", "side")
            ):
                raise ValueError("Paper receipt does not match the frozen order")
    result = {
        "manifest_sha256": forward.digest(frozen),
        "complete": True,
        "receipts": rows,
        "role": "Observed paper-broker outcomes only; never new orders",
    }
    forward.exclusive(output, result)
    return result


# Preserve sub-microsecond quote ordering without floating-point epoch conversion.
def nanos(value):
    moment = bounded.instant(value)
    if moment is None:
        raise ValueError("Aware source timestamp required")
    tail = value.partition(".")[2]
    fraction = tail.split("+")[0].split("-")[0].rstrip("Z") if tail else ""
    if fraction and (not fraction.isdigit() or len(fraction) > 9):
        raise ValueError("Invalid source timestamp precision")
    delta = moment.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        (delta.days * 86400 + delta.seconds) * 1_000_000_000
        + delta.microseconds * 1000
        + int(fraction[6:9].ljust(3, "0") or "0")
    )


# Retain every original page and enforce the exact historical SIP request chain.
def fetch_window(symbols, at, folder, *, request=None, headers=None, clock=None):
    clock = clock or (lambda: datetime.now(UTC))
    request = request or alpaca.alpaca_transport
    if at.utcoffset() is None or clock() < at + timedelta(minutes=16):
        raise ValueError("Wait at least 16 minutes for delayed SIP outcome labels")
    folder = Path(folder)
    folder.mkdir(mode=0o700)
    params = {
        "symbols": ",".join(sorted(symbols)),
        "start": (at - timedelta(seconds=forward.AGE)).isoformat(),
        "end": at.isoformat(),
        "feed": "sip",
        "asof": "-",
        "currency": "USD",
        "sort": "asc",
        "limit": 10000,
    }
    pages, seen, token = [], set(), None
    for index in range(100):
        query = {**params, **({"page_token": token} if token else {})}
        status, body = request(
            URL + "?" + urlencode(query), headers or alpaca.credentials()
        )
        received = clock()
        page = {
            "request": query,
            "received_at": received.isoformat(),
            "status": status,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body": body.decode("utf-8"),
        }
        forward.exclusive(folder / f"{index:04d}.json", page)
        if status != 200:
            raise ValueError(f"Historical SIP unavailable: HTTP {status}")
        payload = json.loads(page["body"])
        if not isinstance(payload.get("quotes"), dict):
            raise ValueError("Historical quote mapping required")
        pages.append(page)
        token = payload.get("next_page_token")
        if token is None:
            packet = {"at": at.isoformat(), "pages": pages, "request": params}
            forward.exclusive(folder / "complete.json", packet)
            return packet
        if not isinstance(token, str) or not token or token in seen:
            raise ValueError("Invalid or repeated pagination token")
        seen.add(token)
    raise ValueError("Historical quote pagination incomplete")


# Validate complete response bytes, actual label availability and pagination links.
def pages(packet, at):
    expected = packet["request"]
    token, seen = None, set()
    if not 1 <= len(packet["pages"]) <= 100:
        raise ValueError("Bounded complete quote pages required")
    for index, page in enumerate(packet["pages"]):
        query = {**expected, **({"page_token": token} if token else {})}
        body = page["body"].encode()
        received = bounded.instant(page["received_at"])
        if (
            page["request"] != query
            or page["status"] != 200
            or hashlib.sha256(body).hexdigest() != page["body_sha256"]
            or received is None
            or received < at + timedelta(minutes=16)
        ):
            raise ValueError("Quote page provenance inconsistent")
        payload = json.loads(page["body"])
        if not isinstance(payload.get("quotes"), dict):
            raise ValueError("Historical quote mapping required")
        token = payload.get("next_page_token")
        if token is None and index != len(packet["pages"]) - 1:
            raise ValueError("Disconnected historical quote pages")
        if token is not None and (
            not isinstance(token, str) or not token or token in seen
        ):
            raise ValueError("Invalid quote pagination chain")
        if token:
            seen.add(token)
        yield payload["quotes"]
    if token is not None:
        raise ValueError("Incomplete historical quote pages")


# Reuse only a completed validated immutable window, never refetch its source bytes.
def endpoint(symbols, at, folder, **kwargs):
    folder = Path(folder)
    if folder.exists():
        packet = json.loads((folder / "complete.json").read_text())
        if packet["at"] != at.isoformat():
            raise ValueError("Existing endpoint belongs to another observation")
        marks(packet, symbols)
        return packet
    packet = fetch_window(symbols, at, folder, **kwargs)
    marks(packet, symbols)
    return packet


# Keep latest source events and retain ambiguity when their timestamps tie.
def latest_events(packet, at, symbols):
    start = nanos((at - timedelta(seconds=forward.AGE)).isoformat())
    end = nanos(at.isoformat())
    latest = {}
    for quotes in pages(packet, at):
        for symbol, rows in quotes.items():
            if symbol not in symbols or not isinstance(rows, list):
                raise ValueError("Unexpected symbol or quote rows")
            for row in rows:
                stamp = nanos(row.get("t"))
                if not start <= stamp <= end:
                    raise ValueError("Quote event outside the declared endpoint window")
                if symbol not in latest or stamp > latest[symbol][0]:
                    latest[symbol] = (stamp, row)
                elif stamp == latest[symbol][0] and latest[symbol][1] != row:
                    latest[symbol] = (stamp, None)
    return latest


# Qualify the latest consolidated quote without skipping invalid or wide events.
def marks(packet, symbols):
    at = bounded.instant(packet.get("at"))
    expected = packet.get("request", {})
    if at is None or expected.get("feed") != "sip" or expected.get("asof") != "-":
        raise ValueError("Explicit consolidated raw symbol provenance required")
    if (
        expected.get("start") != (at - timedelta(seconds=forward.AGE)).isoformat()
        or expected.get("end") != at.isoformat()
        or expected.get("symbols") != ",".join(sorted(symbols))
        or expected.get("currency") != "USD"
        or expected.get("sort") != "asc"
        or expected.get("limit") != 10000
    ):
        raise ValueError("Endpoint request does not match frozen symbols/time")
    latest = latest_events(packet, at, symbols)
    qualified, missing = {}, {}
    for symbol in sorted(symbols):
        row = latest.get(symbol, (None, {}))[1]
        if row is None:
            missing[symbol] = "Latest timestamp has ambiguous consolidated quotes"
            continue
        bid, ask = bounded.positive(row.get("bp")), bounded.positive(row.get("ap"))
        if (
            not bid
            or not ask
            or bid > ask
            or bounded.positive(row.get("bs")) is None
            or bounded.positive(row.get("as")) is None
        ):
            missing[symbol] = "Latest consolidated quote missing, invalid or crossed"
        elif (ask - bid) / ((ask + bid) / 2) * 10000 > forward.SPREAD:
            missing[symbol] = "Latest consolidated spread exceeds fixed 25 bp"
        else:
            qualified[symbol] = {"bid": bid, "ask": ask, "at": row["t"]}
    return qualified, missing


# Value unchanged execution books using labels that were unavailable to decisions.
def supplement(frozen, proxy, first_packet, last_packet):
    if proxy["manifest_sha256"] != forward.digest(frozen):
        raise ValueError("Proxy report does not belong to the frozen cohort")
    symbols = set(frozen["starting"]["holdings"]) | {"SPY", "QQQ"}
    symbols |= {o["order"]["symbol"] for o in frozen["opportunities"]}
    start = bounded.instant(frozen["started_at"])
    end = bounded.instant(proxy["ended_at"])
    closing = entry_timing.session_clock(
        start.astimezone(entry_timing.NEW_YORK).date()
    )["close"]
    final_at = (
        closing
        if proxy.get("valuation_horizon")
        else min(end, closing - timedelta(microseconds=1))
    )
    if (
        end < start
        or end.astimezone(entry_timing.NEW_YORK).date()
        != start.astimezone(entry_timing.NEW_YORK).date()
    ):
        raise ValueError("Single ordered session required")
    if any(
        bounded.instant(outcome["attempted_at"]) > final_at
        for result in proxy["results"]
        for outcome in result["opportunities"].values()
        if outcome.get("attempted_at")
    ):
        raise ValueError("Execution after the regular valuation endpoint")
    if (
        first_packet["at"] != start.isoformat()
        or last_packet["at"] != final_at.isoformat()
    ):
        raise ValueError("Valuation endpoints do not match the frozen experiment")
    first, first_missing = marks(first_packet, symbols)
    last, last_missing = marks(last_packet, symbols)
    initial, missing = forward.equity(frozen["starting"], first)
    results = []
    for original in proxy["results"]:
        book = original["book"]
        ending, missing_end = forward.equity(book, last)
        if not original["execution_complete"]:
            ending = None
        benchmarks = {}
        for symbol in ("SPY", "QQQ"):
            ref = (
                initial
                * last[symbol]["bid"]
                / (first[symbol]["ask"] * (1 + original["cost_bps"] / 10000))
                if initial and symbol in first and symbol in last
                else None
            )
            benchmarks[symbol] = {
                "ending_reference_value": ref,
                "excess_gain": ending - ref
                if ending is not None and ref is not None
                else None,
            }
        gain = ending - initial if initial is not None and ending is not None else None
        results.append(
            {
                "mode": original["mode"],
                "cost_bps": original["cost_bps"],
                "ending_value": ending,
                "total_gain": gain,
                "total_return": gain / initial
                if gain is not None and initial
                else None,
                "execution_complete": original["execution_complete"],
                "ending_cash": book["cash"] if original["execution_complete"] else None,
                "ending_exposure": (ending - book["cash"]) / ending if ending else None,
                "fees": book["fees"] if original["execution_complete"] else None,
                "turnover_one_way": book["turnover"] / initial if initial else None,
                "missing_ending_marks": missing_end,
                "benchmarks": benchmarks,
                "max_drawdown_loss": None,
            }
        )
    for result in results:
        control = next(
            r
            for r in proxy["results"]
            if r["mode"] == "incumbent" and r["cost_bps"] == result["cost_bps"]
        )
        candidate = next(
            r
            for r in proxy["results"]
            if r["mode"] == result["mode"] and r["cost_bps"] == result["cost_bps"]
        )
        result["gain_vs_incumbent"], result["missing_pair_marks"] = difference(
            candidate["book"], control["book"], last
        )
        if not candidate["execution_complete"] or not control["execution_complete"]:
            result["gain_vs_incumbent"] = None
        result["unsupported_auction_orders"] = [
            cid
            for cid, outcome in candidate["opportunities"].items()
            if outcome["status"] == "unsupported_auction"
        ]
    return {
        "version": VERSION,
        "manifest_sha256": forward.digest(frozen),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        "started_at": start.isoformat(),
        "valuation_ended_at": final_at.isoformat(),
        "starting_value": initial,
        "missing_starting_marks": missing,
        "unavailable_quotes": {"start": first_missing, "end": last_missing},
        "packet_sha256": [forward.digest(first_packet), forward.digest(last_packet)],
        "paper_receipt_sha256": proxy.get("paper_receipt_sha256"),
        "results": results,
        "adoption_eligible": False,
        "method": (
            "Delayed SIP closing valuation; "
            "observed paper auctions under cash/cost stress; "
            "bounded attempts remain conditional"
            if proxy.get("paper_receipt_sha256")
            else "Delayed SIP endpoint valuation only; "
            "original conditional IEX attempts unchanged"
        ),
    }


# Cancel identical holdings when measuring paired gain without inventing total NAV.
def difference(candidate, control, quotes):
    quantities = {
        symbol: candidate["holdings"].get(symbol, 0)
        - control["holdings"].get(symbol, 0)
        for symbol in set(candidate["holdings"]) | set(control["holdings"])
    }
    missing = sorted(s for s, qty in quantities.items() if qty and s not in quotes)
    delta = (
        candidate["cash"]
        - control["cash"]
        + sum(qty * quotes[s]["bid"] for s, qty in quantities.items() if qty)
        if not missing
        else None
    )
    return delta, missing
