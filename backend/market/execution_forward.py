"""Frozen forward execution evidence and conditional funded comparison; no orders.

This is a single-session component diagnostic, not broker-fill or alpha proof.
The actual incumbent decision and explicit bounded contract see identical data.
"""

import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from backend.agents.trading.desk import intraday_orders
from backend.market import bounded_execution as bounded
from backend.market import calendar, entry_timing, execution_quotes

VERSION = "funded-execution-forward/1"
PLAN = (
    Path(__file__).parents[2] / "docs/research/funded-execution-forward-2026-10-02.md"
)
AGE = 30
SPREAD = 25
TRIGGER_AGE = 900
COSTS = (10, 25)


# Serialize evidence deterministically and refuse nonfinite values.
def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


# Bind an artifact to its exact bytes without including authentication material.
def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


# Pin the decision implementation and registered budgets used by this experiment.
def identity():
    files = [
        Path(m.__file__) for m in (intraday_orders, entry_timing, bounded, calendar)
    ]
    files += [Path(__file__), PLAN]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


# Write a complete exclusive artifact without replacing any previous evidence.
def exclusive(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


# Refuse invalid cash or quantities instead of repairing an account silently.
def amount(value, *, whole=False):
    if isinstance(value, bool):
        raise ValueError("Explicit nonnegative account numbers required")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (whole and number % 1):
        raise ValueError("Invalid cash or whole-share quantity")
    return int(number) if whole else number


# Normalize only starting cash and shares; never copy account identifiers.
def account(cash, holdings):
    return {
        "cash": amount(cash),
        "holdings": {
            s: amount(q, whole=True) for s, q in sorted(holdings.items()) if q
        },
    }


# Keep raw source timestamps and receipt times even when a packet is unavailable.
def observation(snapshot, latch, packet, now):
    if now.utcoffset() is None:
        raise ValueError("Aware observation time required")
    attached = bounded.with_quotes(snapshot, packet)
    stamp = bounded.instant(snapshot.get("as_of"))
    return {
        "observed_at": now.isoformat(),
        "snapshot": attached,
        "latch": deepcopy(latch),
        "packet": deepcopy(packet),
        "timing_available": bool(stamp and stamp <= now),
        "source_hashes": {"snapshot": digest(snapshot), "latch": digest(latch)},
    }


# Freeze all ordinary unsent intents and their budgets before later quote outcomes.
def manifest(rows, starting, first, revision):
    now = bounded.instant(first["observed_at"])
    if now is None:
        raise ValueError("Aware observation time required")
    starting = account(starting["cash"], starting["holdings"])
    day = now.astimezone(entry_timing.NEW_YORK).date()
    clock = entry_timing.session_clock(day)
    if not entry_timing._is_session(day) or not clock["open"] <= now < clock["close"]:
        raise ValueError("A live regular session is required")
    seen, opportunities = set(), []
    for original in rows:
        row = deepcopy(original)
        if (
            row.get("sent")
            or row.get("sending")
            or row.get("event_id")
            or row.get("priority")
            or row.get("execute_on") != day.isoformat()
            or row.get("execution_timing") != entry_timing.RULE
        ):
            continue
        cid = row.get("client_order_id")
        if (
            not isinstance(cid, str)
            or not cid.strip()
            or cid in seen
            or not isinstance(row.get("symbol"), str)
            or not row["symbol"].strip()
            or row.get("side") not in ("buy", "sell")
        ):
            raise ValueError("Unique order identity and side required")
        seen.add(cid)
        qty = amount(row["qty"], whole=True)
        if not qty:
            raise ValueError("Positive whole-share plan required")
        row = {
            k: row[k]
            for k in (
                "client_order_id",
                "symbol",
                "side",
                "execute_on",
                "execution_timing",
            )
        }
        row["qty"] = qty
        held = starting["holdings"].get(row["symbol"], 0)
        intent = (
            "entry"
            if row["side"] == "buy"
            else "exit"
            if held and qty >= held
            else "trim"
        )
        timed, quote = evidence_for(row, first, now, day)
        limit = timed.get("level")
        if intent == "exit":
            bid = (
                bounded.positive((quote or {}).get("bid"))
                if mark_quote(quote, now, day)
                else None
            )
            limit = bid * (1 - SPREAD / 10000) if bid else None
        error = None
        try:
            bound = bounded.bind(
                row,
                limit_price=limit,
                decision_at=now.isoformat(),
                expires_at=clock["close"].isoformat(),
                quote_source=(first["packet"] or {}).get("feed"),
                max_quote_age_seconds=AGE,
                max_trigger_age_seconds=TRIGGER_AGE,
                max_spread_bps=SPREAD,
                intent=intent,
            )
        except (ValueError, TypeError):
            bound, error = row, "Initial price or quote-feed anchor unavailable"
        opportunities.append({"order": bound, "intent": intent, "unavailable": error})
    return {
        "version": VERSION,
        "revision": revision,
        "implementation": identity(),
        "session": day.isoformat(),
        "started_at": now.isoformat(),
        "starting": deepcopy(starting),
        "opportunities": opportunities,
        "first": first,
        "budgets": {"quote_age": AGE, "spread_bps": SPREAD, "trigger_age": TRIGGER_AGE},
        "costs_bps": list(COSTS),
        "adoption_eligible": False,
    }


# Reuse causal timing evidence and preserve the original executable quote.
def evidence_for(row, obs, now, day):
    quote = (obs["snapshot"].get("quotes") or {}).get(row["symbol"]) or {}
    latch = entry_timing.row_for(obs.get("latch"), row["symbol"], day)
    timed = entry_timing.timing(latch, quote, row["side"], now, day)
    return timed, quote.get("execution_quote")


# Append an ordered hash-linked observation under a single-writer lock.
def append(folder, obs):
    import fcntl

    folder = Path(folder)
    with (folder / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        frozen = json.loads((folder / "manifest.json").read_text())
        if frozen["implementation"] != identity():
            raise ValueError("Experiment implementation changed")
        paths = sorted(folder.glob("[0-9]*.json"))
        previous = json.loads(paths[-1].read_text()) if paths else None
        prior_obs = previous["observation"] if previous else frozen["first"]
        now, prior = (
            bounded.instant(obs["observed_at"]),
            bounded.instant(prior_obs["observed_at"]),
        )
        if (
            now is None
            or now <= prior
            or now.astimezone(entry_timing.NEW_YORK).date().isoformat()
            != frozen["session"]
        ):
            raise ValueError("Observations must advance within the declared session")
        sequence = len(paths) + 1
        row = {
            "sequence": sequence,
            "previous": digest(previous or frozen),
            "observation": obs,
        }
        exclusive(folder / f"{sequence:08d}.json", row)
        return row


# Verify the entire immutable chain before evaluating any policy or outcomes.
def load(folder):
    folder = Path(folder)
    frozen = json.loads((folder / "manifest.json").read_text())
    if frozen["version"] != VERSION or frozen["implementation"] != identity():
        raise ValueError("Experiment version or code identity changed")
    prior, observations = frozen, [frozen["first"]]
    for i, path in enumerate(sorted(folder.glob("[0-9]*.json")), 1):
        row = json.loads(path.read_text())
        if row["sequence"] != i or row["previous"] != digest(prior):
            raise ValueError("Evidence chain is incomplete or altered")
        now, previous = (
            bounded.instant(row["observation"]["observed_at"]),
            bounded.instant(observations[-1]["observed_at"]),
        )
        if (
            now is None
            or now <= previous
            or now.astimezone(entry_timing.NEW_YORK).date().isoformat()
            != frozen["session"]
        ):
            raise ValueError("Evidence time or session is inconsistent")
        observations.append(row["observation"])
        prior = row
    return frozen, observations


# Observe read-only inputs without putting any research files under the live root.
def collect(root, folder, now=None, reader=None):
    root, folder = Path(root).resolve(), Path(folder).resolve()
    if folder.is_relative_to(root):
        raise ValueError("Research output must be outside the production root")
    frozen = json.loads((folder / "manifest.json").read_text())
    symbols = {o["order"]["symbol"] for o in frozen["opportunities"]}
    symbols |= set(frozen["starting"]["holdings"]) | {"SPY", "QQQ"}
    day = datetime.fromisoformat(frozen["session"]).date()
    snapshot_bytes = (root / "desk/live.json").read_bytes()
    snapshot = json.loads(snapshot_bytes)
    latch = entry_timing.load(root, day)
    packet = (reader or execution_quotes.fetch)(sorted(symbols))
    from datetime import UTC

    observed = (now or (lambda: datetime.now(UTC)))()
    obs = observation(snapshot, latch, packet, observed)
    obs["original_snapshot_sha256"] = hashlib.sha256(snapshot_bytes).hexdigest()
    return append(folder, obs)


# Accept fresh causal bid/ask marks without mistaking a single venue for the NBBO.
def mark_quote(quote, now, day):
    if not isinstance(quote, dict) or quote.get("price_basis") != "raw":
        return False
    event, received = (
        bounded.instant(quote.get("timestamp")),
        bounded.instant(quote.get("received_at")),
    )
    clock = entry_timing.session_clock(day)
    bid, ask = bounded.positive(quote.get("bid")), bounded.positive(quote.get("ask"))
    return bool(
        event
        and received
        and clock["open"] <= event <= received <= now
        and (now - event).total_seconds() <= AGE
        and bid
        and ask
        and bid <= ask
        and quote.get("source") in ("sip", "iex")
    )


# Value every owned share or explicitly withhold the incomplete account return.
def equity(book, quotes):
    missing = sorted(s for s, q in book["holdings"].items() if q and s not in quotes)
    value = (
        None
        if missing
        else book["cash"]
        + sum(q * quotes[s]["bid"] for s, q in book["holdings"].items() if q)
    )
    return value, missing


# Use common quote eligibility and the actual decision functions for each arm.
def decision(opportunity, obs, mode, now, day):
    row = opportunity["order"]
    if opportunity["unavailable"]:
        return None, opportunity["unavailable"], None
    if not obs["timing_available"]:
        return None, "Source snapshot time unavailable or future-dated", None
    timed, quote = evidence_for(row, obs, now, day)
    cfg = row["execution_policy"]
    error = bounded.quote_error(
        quote, cfg, now, entry_timing.session_clock(day)["open"]
    )
    if error:
        return None, error, quote
    use = (
        row
        if mode == "bounded"
        else {k: v for k, v in row.items() if k != "execution_policy"}
    )
    candle = (obs["snapshot"].get("quotes") or {}).get(row["symbol"]) or {}
    verdict = intraday_orders.decide(
        use,
        entry_timing.row_for(obs.get("latch"), row["symbol"], day),
        candle,
        now,
        day,
    )
    send = verdict["send"]
    if send == intraday_orders.MOC:
        return None, "Closing auction unsupported", quote
    reason = verdict.get("guard", {}).get("reason") or timed["reason"]
    return send, reason, quote


# Make one conditional displayed-liquidity attempt without borrowing or uncovered sales.
def attempt(book, row, quote, cost, liquidity, available_cash, mode):
    side, symbol = row["side"], row["symbol"]
    price = float(quote["ask"] if side == "buy" else quote["bid"])
    size = quote["ask_size"] if side == "buy" else quote["bid_size"]
    if float(size) % 1:
        return {"status": "unsupported_fractional_quote_size", "filled_qty": 0}, 0
    key = (symbol, quote["source"], quote["timestamp"], side)
    room = max(0, int(size) - liquidity.get(key, 0))
    qty = min(row["qty"], room)
    if side == "buy":
        worst = (
            float(row["execution_policy"]["limit_price"])
            if mode == "bounded"
            else price
        )
        qty = min(qty, math.floor((available_cash + 1e-10) / (worst * (1 + cost))))
    else:
        qty = min(qty, book["holdings"].get(symbol, 0))
    notional, fee = qty * price, qty * price * cost
    book["cash"] += -notional - fee if side == "buy" else notional - fee
    book["holdings"][symbol] = book["holdings"].get(symbol, 0) + (
        qty if side == "buy" else -qty
    )
    book["fees"] += fee
    book["turnover"] += notional
    liquidity[key] = liquidity.get(key, 0) + qty
    return {
        "status": "filled" if qty == row["qty"] else "partial" if qty else "unfilled",
        "filled_qty": qty,
        "unfilled_qty": row["qty"] - qty,
        "price": price,
        "fee": fee,
    }, notional + fee if side == "buy" else 0


# Replay one arm with frozen starting shares, common intents and causal sale funding.
def replay(frozen, observations, mode, bps):
    book = {**deepcopy(frozen["starting"]), "fees": 0.0, "turnover": 0.0}
    outcomes = {
        o["order"]["client_order_id"]: {
            "status": "never_attempted",
            "filled_qty": 0,
            "blocked": {},
        }
        for o in frozen["opportunities"]
    }
    marks, liquidity, event_values, last_events = [], {}, {}, {}
    day = datetime.fromisoformat(frozen["session"]).date()
    for obs in observations:
        now = bounded.instant(obs["observed_at"])
        quotes = {
            s: q["execution_quote"]
            for s, q in (obs["snapshot"].get("quotes") or {}).items()
            if mark_quote(q.get("execution_quote"), now, day)
        }
        for s, quote in quotes.items():
            key = (s, quote["source"], quote["timestamp"])
            values = tuple(quote.get(k) for k in ("bid", "ask", "bid_size", "ask_size"))
            if key in event_values and event_values[key] != values:
                raise ValueError("Conflicting quote event identity")
            series = (s, quote["source"])
            event = bounded.instant(quote["timestamp"])
            if key not in event_values and event < last_events.get(series, event):
                raise ValueError("Distinct quote events arrived out of order")
            last_events[series] = max(event, last_events.get(series, event))
            event_values[key] = values
        start_cash, spent = book["cash"], 0.0
        for opportunity in frozen["opportunities"]:
            row = opportunity["order"]
            result = outcomes[row["client_order_id"]]
            if result["status"] != "never_attempted":
                continue
            send, reason, quote = decision(opportunity, obs, mode, now, day)
            if not send:
                result["blocked"][reason] = result["blocked"].get(reason, 0) + 1
                continue
            fill, used = attempt(
                book,
                row,
                quote,
                bps / 10000,
                liquidity,
                max(0, start_cash - spent),
                mode,
            )
            result.update(fill, attempted_at=obs["observed_at"])
            spent += used
        value, missing = equity(book, quotes)
        marks.append({"at": obs["observed_at"], "equity": value, "missing": missing})
    return {
        "mode": mode,
        "cost_bps": bps,
        "book": book,
        "opportunities": outcomes,
        "marks": marks,
    }


# Compare funded total gains without annualizing a partial-session diagnostic.
def compare(folder):
    frozen, observations = load(folder)
    day = datetime.fromisoformat(frozen["session"]).date()
    now = bounded.instant(observations[0]["observed_at"])
    first_quotes = {
        s: q["execution_quote"]
        for s, q in observations[0]["snapshot"].get("quotes", {}).items()
        if mark_quote(q.get("execution_quote"), now, day)
    }
    initial, missing = equity(frozen["starting"], first_quotes)
    end = observations[-1]
    now = bounded.instant(end["observed_at"])
    final_quotes = {
        s: q["execution_quote"]
        for s, q in end["snapshot"].get("quotes", {}).items()
        if mark_quote(q.get("execution_quote"), now, day)
    }
    results = []
    for cost in COSTS:
        for mode in ("incumbent", "bounded"):
            result = replay(frozen, observations, mode, cost)
            final = result["marks"][-1]["equity"]
            result["total_gain"] = (
                final - initial if initial is not None and final is not None else None
            )
            result["total_return"] = (
                result["total_gain"] / initial
                if initial and result["total_gain"] is not None
                else None
            )
            values = [m["equity"] for m in result["marks"]]
            complete = initial is not None and all(v is not None for v in values)
            peak, loss = initial or 0, 0.0
            for value in values if complete else []:
                peak = max(peak, value)
                loss = max(loss, 1 - value / peak) if peak else loss
            result["max_drawdown_loss"] = loss if complete else None
            result["turnover_one_way"] = (
                result["book"]["turnover"] / initial if initial else None
            )
            result["benchmarks"] = {}
            for symbol in ("SPY", "QQQ"):
                start, finish = first_quotes.get(symbol), final_quotes.get(symbol)
                ref = (
                    initial * finish["bid"] / (start["ask"] * (1 + cost / 10000))
                    if initial and start and finish
                    else None
                )
                result["benchmarks"][symbol] = {
                    "ending_reference_value": ref,
                    "excess_gain": final - ref
                    if final is not None and ref is not None
                    else None,
                }
            results.append(result)
    return {
        "version": VERSION,
        "manifest_sha256": digest(frozen),
        "observations": len(observations),
        "started_at": frozen["started_at"],
        "ended_at": end["observed_at"],
        "starting_value": initial,
        "missing_starting_marks": missing,
        "results": results,
        "adoption_eligible": False,
        "method": (
            "Single-session fixed-intent displayed-quote diagnostic; "
            "no broker, midpoint, auction or annualized performance claim"
        ),
    }
