"""Research-only funded quote replay with the pinned native Nautilus engine.

This is a conditional displayed-liquidity simulation, never proof of broker fills.
Candles decide timing; only distinct, timestamped raw bid/ask observations update
the execution book. Missing quotes retain opportunities without invented fills.
No provider, broker, production policy or inference service is called here.
"""

import hashlib
import json
import math
from copy import deepcopy
from decimal import Decimal
from importlib.metadata import version
from types import SimpleNamespace

from backend.agents.trading.desk import intraday_orders
from backend.market import bounded_execution as bounded
from backend.market import entry_timing

ENGINE_VERSION = "1.231.0"
SCHEMA = "nautilus-quote-replay/1"
MODES = ("incumbent", "bounded")


# Reject nonfinite numbers without accepting booleans as portfolio values.
def number(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError("Explicit finite number required")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Explicit finite number required") from exc
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError("Invalid portfolio number")
    return result


# Convert aware observation times to UTC nanoseconds without assuming a timezone.
def nanos(value):
    moment = bounded.instant(value)
    if moment is None:
        raise ValueError("Explicit aware timestamp required")
    return int(moment.timestamp() * 1_000_000_000)


# Validate shared replay evidence before either policy can see any outcomes.
def prepare(payload):
    if (
        payload.get("schema") != SCHEMA
        or payload.get("price_basis") != "raw"
        or payload.get("quantity_unit") != "shares"
    ):
        raise ValueError("Explicit replay schema, raw basis and share units required")
    number(payload.get("starting_cash"), positive=True)
    number(payload.get("cost_bps"))
    number(payload.get("legacy_quote_age_seconds"), positive=True)
    if any(number(qty) for qty in payload.get("initial_holdings", {}).values()):
        raise ValueError("Initial holdings unsupported; replay from a flat account")
    if (
        not isinstance(payload.get("opportunities"), list)
        or not payload["opportunities"]
    ):
        raise ValueError("At least one retained opportunity required")
    seen, events = set(), []
    for opportunity in payload["opportunities"]:
        row = opportunity.get("order", {})
        cfg = row.get("execution_policy")
        error = bounded.contract_error(row, cfg)
        if error:
            raise ValueError(error)
        if row["execute_on"] != payload.get("session"):
            raise ValueError("Single declared session required; no split conversion")
        cid = row["client_order_id"]
        if cid in seen:
            raise ValueError("Duplicate opportunity identity")
        seen.add(cid)
        observations = opportunity.get("observations", [])
        if not isinstance(observations, list):
            raise ValueError("Observation list required")
        events.extend(observation_events(cid, observations))
    return sorted(events, key=lambda item: (item[0], item[1]))


# Refuse reordered observations and future latch evidence before native replay.
def observation_events(cid, observations):
    previous, events = -1, []
    for observation in observations:
        ns = nanos(observation.get("observed_at"))
        if ns <= previous:
            raise ValueError("Opportunity observations must strictly advance")
        previous = ns
        latch = observation.get("latch")
        for key in ("buy_trigger", "sell_trigger"):
            trigger = (latch or {}).get(key)
            if trigger and (
                nanos(trigger.get("seen_at")) > ns
                or nanos(trigger.get("bar")) + 900_000_000_000 > ns
            ):
                raise ValueError("Latch contains future information")
        events.append((ns, cid, deepcopy(observation)))
    return events


# Qualify native execution quotes equally for both arms without candle synthesis.
def quote_error(quote, row, now, age):
    if now.date().isoformat() != row["execute_on"]:
        return "Observation belongs to another session"
    cfg = {**row["execution_policy"], "max_quote_age_seconds": age}
    error = bounded.quote_error(
        quote, cfg, now, entry_timing.session_clock(now.date())["open"]
    )
    if error:
        return error
    if any(float(quote[key]) % 1 for key in ("bid_size", "ask_size")):
        return "Whole-share quote quantities required"
    if any(
        Decimal(str(quote[key])) != Decimal(str(quote[key])).quantize(Decimal("0.0001"))
        for key in ("bid", "ask")
    ):
        return "Quote precision exceeds the declared native instrument"
    return None


# Load only the pinned optional native dependency when research is requested.
def native_api():
    if version("nautilus_trader") != ENGINE_VERSION:
        raise RuntimeError(f"Install nautilus_trader=={ENGINE_VERSION}")
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import MakerTakerFeeModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import CustomData, DataType, QuoteTick
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
    from nautilus_trader.model.identifiers import (
        ClientId,
        ClientOrderId,
        InstrumentId,
        Symbol,
        Venue,
    )
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.trading.strategy import Strategy

    return SimpleNamespace(
        BacktestEngine=BacktestEngine,
        MakerTakerFeeModel=MakerTakerFeeModel,
        BacktestEngineConfig=BacktestEngineConfig,
        LoggingConfig=LoggingConfig,
        Data=Data,
        USD=USD,
        CustomData=CustomData,
        DataType=DataType,
        QuoteTick=QuoteTick,
        AccountType=AccountType,
        OmsType=OmsType,
        OrderSide=OrderSide,
        TimeInForce=TimeInForce,
        ClientId=ClientId,
        ClientOrderId=ClientOrderId,
        InstrumentId=InstrumentId,
        Symbol=Symbol,
        Venue=Venue,
        Equity=Equity,
        Money=Money,
        Price=Price,
        Quantity=Quantity,
        Strategy=Strategy,
    )


# Build an optional custom-data class without importing native code at startup.
def observation_class(api):
    # Carry observations through the engine even when market quotes are missing.
    class Observation(api.Data):
        # Preserve the exact decision clock and original opportunity evidence.
        def __init__(self, cid, evidence, timestamp):
            self.cid, self.evidence = cid, evidence
            self._timestamp = timestamp

        # Expose the observation clock rather than a fabricated exchange event.
        @property
        def ts_event(self):
            return self._timestamp

        # Order native callbacks after contemporaneous received quote events.
        @property
        def ts_init(self):
            return self._timestamp

    return Observation


# Define raw-basis whole-share equities and explicit per-side research costs.
def native_instruments(api, rows, venue, rate):
    instruments = {}
    for symbol in sorted({row["symbol"] for row in rows.values()}):
        instruments[symbol] = api.Equity(
            instrument_id=api.InstrumentId(api.Symbol(symbol), venue),
            raw_symbol=api.Symbol(symbol),
            currency=api.USD,
            price_precision=4,
            price_increment=api.Price.from_str("0.0001"),
            lot_size=api.Quantity.from_int(1),
            maker_fee=rate,
            taker_fee=rate,
            ts_event=0,
            ts_init=0,
        )
    return instruments


# Preserve the full opportunity denominator including empty observation lists.
def outcome_rows(rows):
    return {
        cid: {
            "client_order_id": cid,
            "symbol": row["symbol"],
            "side": row["side"],
            "planned_qty": row["qty"],
            "attempted_qty": 0,
            "filled_qty": 0,
            "status": "never_attempted",
            "observations": [],
        }
        for cid, row in rows.items()
    }


# Create a native strategy with a shared guard and the native funded ledger.
def replay_class(api, context):
    # Delegate matching, liquidity consumption, fees and balances to Nautilus.
    class Replay(api.Strategy):
        # Track native orders and commission events without creating another ledger.
        def __init__(self):
            super().__init__()
            self.orders, self.commissions = {}, []

        # Subscribe to causal observation events, including missing evidence.
        def on_start(self):
            self.subscribe_data(context.data_type, client_id=context.client)

        # Evaluate one opportunity against quotes already received by the engine.
        def on_data(self, data):
            observe_native(self, api, context, data)

        # Retain actual native commissions separately from simulated gross proceeds.
        def on_order_filled(self, event):
            self.commissions.append(event.commission.as_double())

    return Replay


# Make one causal attempt; native matching settles it before the next callback.
def observe_native(strategy, api, ctx, data):
    row, evidence = ctx.rows[data.cid], data.evidence
    result = ctx.outcomes[data.cid]
    if data.cid in strategy.orders or result["status"] == "unsupported_closing_auction":
        return
    now = bounded.instant(evidence["observed_at"]).astimezone(entry_timing.NEW_YORK)
    candle = deepcopy(evidence.get("candle") or {})
    quote = evidence.get("execution_quote")
    candle["execution_quote"] = quote
    tested = (
        row
        if ctx.mode == "bounded"
        else {k: v for k, v in row.items() if k != "execution_policy"}
    )
    verdict = intraday_orders.decide(
        tested, evidence.get("latch"), candle, now, now.date()
    )
    reason = quote_error(quote, row, now, ctx.payload["legacy_quote_age_seconds"])
    receipt = {
        "observed_at": evidence["observed_at"],
        "state": (verdict.get("guard") or verdict["timed"]).get("state"),
        "quote_event_at": (quote or {}).get("timestamp"),
        "missing_evidence": reason,
    }
    result["observations"].append(receipt)
    if not verdict["send"] or reason:
        return
    if verdict["send"] == intraday_orders.MOC:
        receipt["state"] = "unsupported_closing_auction"
        result["status"] = "unsupported_closing_auction"
        return
    submit_native(strategy, api, ctx, data, row, quote, receipt)


# Size only from current native cash and owned shares, accounting for costs.
def submit_native(strategy, api, ctx, data, row, quote, receipt):
    instrument = ctx.instruments[row["symbol"]]
    cash = strategy.cache.account_for_venue(ctx.venue).balance_free(api.USD).as_double()
    price = (
        float(row["execution_policy"]["limit_price"])
        if ctx.mode == "bounded"
        else float(quote["ask"])
    )
    if row["side"] == "buy":
        qty = min(row["qty"], math.floor(cash / (price * (1 + float(ctx.rate)))))
    else:
        qty = min(
            row["qty"], max(0, int(strategy.portfolio.net_position(instrument.id)))
        )
    if qty <= 0:
        receipt["state"] = "unfunded" if row["side"] == "buy" else "no_holding"
        return
    args = dict(
        instrument_id=instrument.id,
        order_side=api.OrderSide.BUY if row["side"] == "buy" else api.OrderSide.SELL,
        quantity=instrument.make_qty(qty),
        client_order_id=api.ClientOrderId(data.cid),
        time_in_force=api.TimeInForce.IOC,
    )
    order = (
        strategy.order_factory.limit(price=instrument.make_price(price), **args)
        if ctx.mode == "bounded"
        else strategy.order_factory.market(**args)
    )
    strategy.orders[data.cid] = order
    ctx.outcomes[data.cid].update(
        attempted_qty=qty, status="submitted", attempted_at=data.evidence["observed_at"]
    )
    strategy.submit_order(order)


# Add each distinct source quote once, refusing conflicting identity reuse.
def native_data(api, ctx, events):
    data, quote_keys, last_quotes = [], {}, {}
    for index, (ns, cid, evidence) in enumerate(events):
        row = ctx.rows[cid]
        now = bounded.instant(evidence["observed_at"]).astimezone(entry_timing.NEW_YORK)
        quote = evidence.get("execution_quote")
        if (
            quote_error(quote, row, now, ctx.payload["legacy_quote_age_seconds"])
            is None
        ):
            key = (row["symbol"], quote["source"], quote["timestamp"])
            values = tuple(quote[k] for k in ("bid", "ask", "bid_size", "ask_size"))
            if key in quote_keys and quote_keys[key] != values:
                raise ValueError(
                    "Conflicting quote under the same source event identity"
                )
            if key not in quote_keys:
                latest = last_quotes.get(row["symbol"])
                if latest and nanos(quote["timestamp"]) < nanos(latest["timestamp"]):
                    raise ValueError(
                        "Distinct quote source events arrived out of order"
                    )
                instrument = ctx.instruments[row["symbol"]]
                data.append(
                    api.QuoteTick(
                        instrument_id=instrument.id,
                        bid_price=instrument.make_price(quote["bid"]),
                        ask_price=instrument.make_price(quote["ask"]),
                        bid_size=instrument.make_qty(quote["bid_size"]),
                        ask_size=instrument.make_qty(quote["ask_size"]),
                        ts_event=nanos(quote["timestamp"]),
                        ts_init=ns,
                    )
                )
                quote_keys[key] = values
                last_quotes[row["symbol"]] = quote
        data.append(
            api.CustomData(
                ctx.data_type, ctx.Observation(cid, evidence, ns + index + 1)
            )
        )
    return data, quote_keys, last_quotes


# Summarize native terminal fills while retaining all blocked opportunities.
def native_report(api, ctx, engine, strategy, quote_keys, last_quotes):
    for cid, order in strategy.orders.items():
        filled = int(order.filled_qty.as_double())
        result = ctx.outcomes[cid]
        result.update(
            filled_qty=filled,
            native_status=str(order.status),
            status="filled"
            if filled == result["attempted_qty"]
            else "partial"
            if filled
            else "unfilled",
            average_fill_price=float(order.avg_px)
            if order.avg_px is not None
            else None,
        )
    account = engine.cache.account_for_venue(ctx.venue)
    cash = (
        account.balance_total(api.USD).as_double()
        if account is not None
        else number(ctx.payload["starting_cash"], positive=True)
    )
    holdings = {
        symbol: float(engine.portfolio.net_position(item.id))
        for symbol, item in ctx.instruments.items()
    }
    marked = cash + sum(
        qty * float(last_quotes[symbol]["bid"])
        for symbol, qty in holdings.items()
        if qty
    )
    digest = hashlib.sha256(
        json.dumps(ctx.payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    complete = not any(
        result["status"] == "unsupported_closing_auction"
        for result in ctx.outcomes.values()
    )
    return {
        "schema": SCHEMA,
        "engine": "nautilus_trader",
        "engine_version": ENGINE_VERSION,
        "mode": ctx.mode,
        "input_sha256": digest,
        "opportunities": list(ctx.outcomes.values()),
        "starting_cash": ctx.payload["starting_cash"],
        "execution_complete": complete,
        "known_cash": cash,
        "known_holdings": holdings,
        "ending_cash": cash if complete else None,
        "ending_holdings": holdings if complete else None,
        "ending_bid_marked_equity": marked if complete else None,
        "commissions": sum(strategy.commissions),
        "distinct_quote_events": len(quote_keys),
        "fill_evidence": "conditional_displayed_liquidity_simulation",
        "broker_fill_proof": False,
        "initial_account": "flat",
    }


# Run a flat-funded native backtest with quote-only execution and no network calls.
def run(payload, *, mode):
    if mode not in MODES:
        raise ValueError("Unknown execution comparison arm")
    events = prepare(payload)
    api = native_api()
    rows = {
        item["order"]["client_order_id"]: deepcopy(item["order"])
        for item in payload["opportunities"]
    }
    venue, client = api.Venue("REPLAY"), api.ClientId("OBSERVATIONS")
    observation_type = observation_class(api)
    rate = Decimal(str(payload["cost_bps"])) / Decimal(10000)
    ctx = SimpleNamespace(
        rows=rows,
        payload=payload,
        mode=mode,
        rate=rate,
        venue=venue,
        client=client,
        instruments=native_instruments(api, rows, venue, rate),
        outcomes=outcome_rows(rows),
        Observation=observation_type,
        data_type=api.DataType(observation_type),
    )
    engine = api.BacktestEngine(
        api.BacktestEngineConfig(logging=api.LoggingConfig(bypass_logging=True))
    )
    try:
        engine.add_venue(
            venue=venue,
            oms_type=api.OmsType.NETTING,
            account_type=api.AccountType.CASH,
            base_currency=api.USD,
            starting_balances=[api.Money(payload["starting_cash"], api.USD)],
            fee_model=api.MakerTakerFeeModel(),
            liquidity_consumption=True,
            bar_execution=False,
            trade_execution=False,
            allow_cash_borrowing=False,
        )
        for instrument in ctx.instruments.values():
            engine.add_instrument(instrument)
        data, quote_keys, last_quotes = native_data(api, ctx, events)
        if data:
            engine.add_data(data, client_id=client)
        strategy = replay_class(api, ctx)()
        engine.add_strategy(strategy)
        if data:
            engine.run()
        return native_report(api, ctx, engine, strategy, quote_keys, last_quotes)
    finally:
        engine.dispose()


# Compare both execution arms on exactly the same retained opportunity dataset.
def compare(payload):
    return {
        "incumbent": run(payload, mode="incumbent"),
        "bounded": run(payload, mode="bounded"),
    }
