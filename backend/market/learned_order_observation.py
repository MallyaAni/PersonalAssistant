"""Immutable learned order observations; never broker fills or fresh predictions."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing, execution_quotes, learned_live_timing
from backend.market import forward_probability_timing as timing
from backend.market.live_probability_timing import POLICY

CONTRACT = "learned-order-observation/1"


# Bind the original planned quantity and session independently of later broker status.
def identity(row):
    return {
        key: row.get(key)
        for key in (
            "client_order_id",
            "symbol",
            "side",
            "qty",
            "session",
            "execute_on",
            "execution_timing",
            "timing_policy",
        )
    }


# Bind the code that inferred, retained and displayed this recorded observation.
def _sources():
    from backend.agents.trading.desk import intraday_orders

    return {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            Path(intraday_orders.__file__),
            Path(learned_live_timing.__file__),
            Path(timing.__file__),
        )
    }


# Store shared forecast evidence once and leave only its reference in pending rows.
def retain(root, observations, now):
    if not observations:
        return False
    shared, verdicts = None, {}
    for row, verdict in observations:
        timed = deepcopy(verdict["timed"])
        receipt = timed.pop("forward_receipt")
        digest = timed.pop("forward_receipt_sha256")
        cid = row["client_order_id"]
        if (
            row.get("timing_policy") != POLICY
            or timed["policy"] != POLICY
            or timed["intent_id"] != cid
            or timed["symbol"] != row["symbol"]
            or timed["side"] != row["side"]
            or timed["desired_qty"] != row["qty"]
            or entry_timing._instant(timed["at"]) != now
            or timed["state"] not in ("execute", "wait", "unavailable", "no_trade")
            or (verdict["send"] is not None) != (timed["state"] == "execute")
            or digest != timing._digest(receipt)
            or cid in verdicts
            or (shared is not None and shared != receipt)
            or "inference" not in receipt
            or receipt["account"]["receipt"].get("basis")
            == "manual_personal_inputs_not_broker_verified"
        ):
            raise ValueError("Original shared paper timing verdict required")
        shared = receipt
        verdicts[cid] = {"intent": identity(row), "timed": timed}
    batch = {
        "contract": CONTRACT,
        "observed_at": shared["decided_at"],
        "sources": _sources(),
        "forward_receipt": shared,
        "forward_receipt_sha256": timing._digest(shared),
        "verdicts": verdicts,
    }
    reference = timing._store_inference(root, batch, timing._digest(batch))
    changed = False
    for row, _ in observations:
        changed |= row.get("timing_observation") != reference
        row["timing_observation"] = deepcopy(reference)
    return changed


# Resolve authenticated JSON only within the original private immutable evidence folder.
def _read(root, reference):
    if set(reference) != {"path", "sha256"}:
        raise ValueError("Exact observation reference required")
    digest = reference["sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Original observation hash required")
    relative = Path(paper.PAPER_KIND) / "forecast-evidence" / (digest + ".json")
    if reference["path"] != str(relative):
        raise ValueError("Observation must remain in its evidence folder")
    path = Path(root) / relative
    if not path.resolve().is_relative_to((Path(root) / relative.parent).resolve()):
        raise ValueError("Observation path escaped its evidence folder")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError("Original observation bytes differ")
    return json.loads(raw)


# Authenticate the original inference, funding snapshot and shared clock together.
def _batch(root, reference):
    batch = _read(root, reference)
    receipt = batch["forward_receipt"]
    inferred = _read(root, receipt["inference"])
    account = receipt["account"]
    if (
        batch["contract"] != CONTRACT
        or batch["forward_receipt_sha256"] != timing._digest(receipt)
        or receipt["contract"] != timing.CONTRACT
        or inferred["contract"] != timing.CONTRACT
        or receipt["source_identity"]["observation"] != receipt["inference"]["sha256"]
        or receipt["source_identity"]["model_receipt"] != inferred["model_receipt"]
        or receipt["source_identity"]["residual_receipt"]
        != inferred["residual_receipt"]
        or account["receipt_sha256"] != timing._digest(account["receipt"])
        or receipt["decided_at"] != batch["observed_at"]
        or receipt["completed_at"] != inferred["observation"]["completed_at"]
    ):
        raise ValueError("Original linked forecast, clock and account required")
    current = (
        batch["sources"] == _sources()
        and inferred["sources"] == timing._inference_sources()
    )
    try:
        current &= (
            sha256((Path(root) / learned_live_timing.CONFIG).read_bytes()).hexdigest()
            == inferred["live_dispatch"]["config_sha256"]
        )
    except (OSError, KeyError, TypeError):
        current = False
    return batch, current


# Distinguish a fresh compatible observation from a historical model verdict.
def _current(batch, source_current, now, held, equity, budget, price, timed):
    observed = entry_timing._instant(batch["observed_at"])
    account = batch["forward_receipt"]["account"]["receipt"]
    clock = entry_timing.session_clock(now.astimezone(entry_timing.NEW_YORK).date())
    return bool(
        source_current
        and observed
        and clock["open"] <= now < clock["final"]
        and 0 <= (now - observed).total_seconds() < execution_quotes.MAX_AGE_SECONDS
        and account.get("reason") == ""
        and equity == account.get("nav")
        and budget == account.get("budget")
        and held == account.get("held")
        and price is not None
        and price == timed.get("observed_price")
        and observed.astimezone(entry_timing.NEW_YORK).date()
        == now.astimezone(entry_timing.NEW_YORK).date()
    )


# Read each shared batch once; invalid or mismatched rows have no usable observation.
def for_rows(root, rows, now, *, held, equity, budget, prices):
    cache, result = {}, {}
    for row in rows:
        reference = row.get("timing_observation")
        if not reference or row.get("timing_policy") != POLICY:
            continue
        try:
            key = timing._digest(reference)
            if key not in cache:
                cache[key] = _batch(root, reference)
            batch, source_current = cache[key]
            value = batch["verdicts"][row["client_order_id"]]
            timed = value["timed"]
            if (
                value["intent"] != identity(row)
                or timed["policy"] != POLICY
                or timed["intent_id"] != row["client_order_id"]
                or timed["at"] != batch["observed_at"]
                or timed["state"] not in ("execute", "wait", "unavailable", "no_trade")
            ):
                continue
            result[row["client_order_id"]] = {
                key: timed.get(key)
                for key in (
                    "policy",
                    "state",
                    "reason",
                    "observed_qty",
                    "observed_price",
                )
            }
            result[row["client_order_id"]].update(
                observed_at=batch["observed_at"],
                evidence_sha256=reference["sha256"],
                current=_current(
                    batch,
                    source_current,
                    now,
                    held,
                    equity,
                    budget,
                    prices.get(row["symbol"]),
                    timed,
                ),
                fill_proven=False,
            )
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return result


# Explain the learned session clock without applying the incumbent percent trigger.
def clock_status(observation, now):
    try:
        day = now.astimezone(entry_timing.NEW_YORK).date()
        status = calendar.exchange_status(now)
        if not status["calendar_known"] or not status["is_session"]:
            return "waiting", "Exchange session unavailable"
        clock = entry_timing.session_clock(day)
    except (TypeError, ValueError):
        return "waiting", "Exchange session unavailable"
    if now < clock["open"] + entry_timing.BAR:
        return "planned", "Awaiting completed 15-minute bar"
    if now >= clock["close"]:
        return "missed", "No submission before session close"
    if now >= clock["final"]:
        return "due", "Session completion due; fill unconfirmed"
    if not observation:
        return "waiting", "Learned forecast unavailable"
    if not observation["current"]:
        return "waiting", "Awaiting current learned decision"
    if observation["state"] == "execute":
        return "due", "Learned timing ready; submission unconfirmed"
    return "waiting", observation["reason"] or "Learned timing waiting"


# Name learned ordinary timing and its actual session deadline without a price level.
def when(day, session):
    clock = entry_timing.session_clock(session)
    deadline = entry_timing._clock(clock["final"])
    return f"{day} · learned timing; session completion {deadline} ET"


# Describe shared timing only when its ordinary orders use one known policy.
def plan_timing(state):
    from backend.agents.trading.desk import intraday_orders
    from backend.market.joint_funded_policy import MARKET_TIMED_POLICY, TIMED_POLICY
    from backend.market.learned_holding_transition import POLICY as RETAINED_POLICY

    tags = {
        row.get("timing_policy") or intraday_orders.INTRADAY_TIMING
        for row in state.pending
        if row.get("execution_timing") == intraday_orders.INTRADAY_TIMING
        and not row.get("event_id")
    }
    if len(tags) > 1:
        return "order-specific", "Order-specific timing; see each order"
    if tags == {POLICY} or (
        not tags
        and state.policy_version in (MARKET_TIMED_POLICY, TIMED_POLICY, RETAINED_POLICY)
    ):
        return POLICY, "Ordinary orders use learned timing; company exits at the open"
    if tags and tags != {intraday_orders.INTRADAY_TIMING}:
        return "unavailable", "Timing policy unavailable"
    return None, None
