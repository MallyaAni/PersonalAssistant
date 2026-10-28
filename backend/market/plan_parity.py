"""Tonight's paper plan against the account simulator's plan, checked every night.

The paper account is planned by `joint_funded_policy`, `nightly_plan` and
`paper` (the leader sizing through `grade_led_leader_policy`, the FOMC cycle
through `event_execution`); the backtest, the chart replay and the desk's
"Historical simulation" box are `policy_book.simulate`. The two share
`leader_weights`, and `backend/tests/test_policy_book.py` checks them on made-up
books. This module checks them on the real account every night: it hands the
simulator's own planner (`policy_book.plan_target`, `plan_orders`, `funded`,
`cycle_cut`, `cycle_restore`, the functions `simulate` plans with) the inputs
the live plan had - tonight's grades, trailing closes, band block and P/E
tilt from the desk report, and the account's shares, prices, equity, cash and
FOMC snapshot from the record - and compares the two plans name by name.

**Where it runs.** In the 20:40 replay job
(`backend/cli/market_policy_replay_research.py`), right after the replay,
with the report the replay was built from. The replay waits for tonight's
record, rebuilds the same report the nightly decided from (same store, same
code, `fundamentals="current"`) and already runs the simulator, so the check
costs nothing there, sits outside the release-bound nightly, and its verdict
is written by about 20:45 - long before the orders fill at the next open.
A rebuilt report whose grades differ from the ones the plan recorded is
reported as an input mismatch, never silently compared.

**What is compared.**

* The policy: the record's paper plan must be the rule the simulator runs
  (`grade_led_leader_policy.POLICY`). Anything else is a mismatch.
* The path: whether tonight is an ordinary night or an FOMC cycle night, by
  the simulator's own rule (`event_risk.live_path` and the open snapshot)
  against the plan's (`joint_funded.status == "event_priority"`).
* Ordinary night, inputs: the grades the plan recorded (`receipt.grades`) and
  its band-blocked names (`receipt.buy_blocked`) against the report's.
* Ordinary night, sizing: the simulator's target weights against the plan's
  leader sizes before the grade preservation (`receipt.sizing_model_targets`),
  to `TOLERANCE`. Both are `leader_weights` on the same closes; there is no
  rounding at this stage, so any difference is a divergence.
* Ordinary night, holdings: the weight each name will have after tonight's
  orders against the simulator's target. The allowed band is derived from the
  simulator's own order rule (`plan_orders`): a resize smaller than the
  minimum trade (`Rule.min_trade`, 1% of equity) is not traded, a gap inside
  half a share is not traded, a trade rounds to the nearest whole share, and a
  held name the grade keeps is never rounded to nothing (one share). So for a
  name with price p on equity E the post-plan weight may sit within
  max(min_trade, p/E) of the target, and must be exactly zero where the target
  is zero. Buys come only from cash on hand: when the simulator's buys need
  more than that cash, each is scaled by s = cash / need (`funded`), and the
  lower edge of a buy's band moves to current + s * (target - current).
* FOMC night, holdings in shares: the cycle's arithmetic on the account's
  snapshot - cut the reduced share of each snapshot name, hold, or restore to
  the snapshot (at the decision close on the eve, at the next open after it)
  - against the shares the plan will hold after its orders. There is no
  rounding and no minimum trade in the cycle, so the shares must match
  exactly, except that a restoration may fall short by what the cash on hand
  cannot fund at the planner's reserved price allowance
  (`event_execution.CLOSE_ALLOWANCE`).

`run` writes `<root>/desk/plan_parity.json`: one row per session, replaced
when the session is checked again, the last 90 days kept. The API serves the
row for the record the board shows, and the Paper account view shows a red
banner on a mismatch, as it does for the grade check (`grade_parity`).
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from pathlib import Path

import numpy as np

from backend.market import grade_led_leader_policy as leader
from backend.market import policy_book
from backend.market.labels import (
    DeskAction,
    OrderSide,
    PlanParity,
    PlanParityKind,
    PlanPath,
    as_member,
    parse,
)

VERSION = "plan-parity/1"
FILE = "plan_parity.json"
TOLERANCE = 1e-9
KEEP_DAYS = 90
# The desk actions that are buys and sells of shares.
BUYS = frozenset({DeskAction.BUY, DeskAction.ADD})
SELLS = frozenset({DeskAction.SELL, DeskAction.TRIM})


def path(root: Path) -> Path:
    """Return `<root>/desk/plan_parity.json`."""
    return Path(root) / "desk" / FILE


# The shares each name changes by in tonight's plan: the orders sent tonight,
# plus the orders the plan holds for the balancer (an FOMC restoration at the
# decision close), which the record carries on the name's action row.
def live_orders(paper: dict) -> dict[str, int]:
    """Return {symbol: signed shares} of the record's paper plan."""
    signed: dict[str, int] = {}
    for order in paper.get("orders") or []:
        side = parse(OrderSide, order["side"])
        qty = int(order["qty"])
        signed[order["symbol"]] = signed.get(order["symbol"], 0) + (
            qty if side is OrderSide.BUY else -qty
        )
    for row in paper.get("actions") or []:
        name, qty = row.get("ticker"), row.get("order_quantity")
        if not name or name in signed or not qty:
            continue
        action = as_member(DeskAction, row.get("action"))
        if action in BUYS:
            signed[name] = int(qty)
        elif action in SELLS:
            signed[name] = -int(qty)
    return signed


def _result(session, policy, verdict_rows, **fields) -> dict:
    return {
        "version": VERSION,
        "date": session,
        "checked_at": datetime.now(UTC).isoformat(),
        "verdict": PlanParity.MISMATCH if verdict_rows else PlanParity.OK,
        "ok": not verdict_rows,
        "policy": policy,
        "simulator_policy": leader.POLICY,
        "mismatches": verdict_rows,
        **fields,
    }


# The simulator's view of tonight: an ordinary night, or a night of the FOMC
# cycle with its snapshot and what the cycle does tonight ("cut", "hold" or
# "restore"). `cycle` is the snapshot the account holds (the record's), and
# `factor` the simulator's own exposure path at this close.
def _simulator_path(day, factor, cycle, held):
    from backend.agents.trading.desk import event_risk, intraday_orders
    from backend.market.calendar import fomc_decisions

    if cycle:
        decision = _date.fromisoformat(str(cycle["decision_date"]))
        base = {k: float(v) for k, v in (cycle.get("baseline") or {}).items()}
        if day >= decision:
            restored = all(held.get(n, 0.0) >= q for n, q in base.items())
            return (PlanPath.ORDINARY, None, None) if restored else (
                PlanPath.EVENT, base, "restore"
            )
    elif factor == event_risk.REDUCED and any(m >= day for m in fomc_decisions()):
        decision = next(m for m in fomc_decisions() if m >= day)
        base = {n: q for n, q in held.items() if q > 0}
    else:
        return PlanPath.ORDINARY, None, None
    cut = {n: math.floor(q * event_risk.REDUCED) for n, q in base.items() if q > 0}
    done = all(held.get(n, 0.0) <= base[n] - q for n, q in cut.items() if q > 0)
    if not done:
        return PlanPath.EVENT, base, "cut"
    eve = intraday_orders.next_session(day) == decision
    return PlanPath.EVENT, base, "restore" if eve else "hold"


# The FOMC night: shares after the plan against the cycle's arithmetic.
def _event_rows(paper, report, base, stage, held, signed):
    from backend.agents.trading.desk import event_execution

    universe = sorted(set(base) | set(held) | set(signed))
    shares = np.array([float(held.get(n, 0.0)) for n in universe])
    snapshot = np.array([float(base.get(n, 0.0)) for n in universe])
    after = shares.copy()
    if stage == "cut":
        for j, q in policy_book.cycle_cut(snapshot).items():
            after[j] -= min(q, shares[j])
    elif stage == "restore":
        for j, q in policy_book.cycle_restore(snapshot, shares).items():
            after[j] += q
    prices = _prices(paper, report, held)
    price = np.array([prices.get(n, math.nan) for n in universe])
    cash = float(paper.get("cash") or 0.0)
    # What the cash on hand funds of the restoration at the planner's reserve.
    need = sum(
        (after[j] - shares[j]) * price[j]
        for j in range(len(universe))
        if after[j] > shares[j] and np.isfinite(price[j])
    ) * (1 + event_execution.CLOSE_ALLOWANCE)
    scale = min(1.0, max(0.0, cash) / need) if need > 0 else 1.0
    rows, names = [], {}
    for j, name in enumerate(universe):
        live = shares[j] + signed.get(name, 0)
        want = after[j]
        low = want
        if want > shares[j]:
            low = shares[j] + math.floor((want - shares[j]) * scale)
        names[name] = {"held": shares[j], "live": live, "simulator": want, "low": low}
        if not (low - TOLERANCE <= live <= want + TOLERANCE):
            rows.append(
                {
                    "kind": PlanParityKind.HOLDING,
                    "ticker": name,
                    "live": live,
                    "simulator": want,
                    "low": low,
                    "high": want,
                    "detail": f"shares after tonight's plan: live {live:g}, "
                    f"simulator {want:g} (FOMC {stage})",
                }
            )
    return rows, names, {"stage": stage, "cash_scale": scale}


# The prices the planner valued the account at: a held name at its broker
# mark, any other name at the report's last close.
def _prices(paper, report, held):
    panel = report.panel
    t = len(panel.dates) - 1
    prices = {
        n: float(panel.close[t, j])
        for j, n in enumerate(panel.tickers)
        if np.isfinite(panel.close[t, j]) and panel.close[t, j] > 0
    }
    for row in paper.get("positions") or []:
        qty = float(row.get("qty") or 0)
        if qty > 0 and row.get("market_value") is not None:
            prices[row["symbol"]] = float(row["market_value"]) / qty
    return prices


# The inputs the plan recorded against the report's: each name's grade
# (`receipt.grades`) and the band-blocked names (`receipt.buy_blocked`).
def _input_rows(receipt, tickers, grades, band) -> list[dict]:
    rows: list[dict] = []
    recorded = receipt.get("grades") or {}
    for j, name in enumerate(tickers):
        if name in recorded and int(recorded[name]) != int(grades[j]):
            rows.append(
                {
                    "kind": PlanParityKind.INPUTS,
                    "ticker": name,
                    "live": int(recorded[name]),
                    "simulator": int(grades[j]),
                    "detail": "grade the plan recorded differs from the report's",
                }
            )
    live = set(receipt.get("buy_blocked") or [])
    blocked = {tickers[j] for j in np.flatnonzero(band)}
    for name in sorted(blocked ^ live):
        rows.append(
            {
                "kind": PlanParityKind.INPUTS,
                "ticker": name,
                "live": name in live,
                "simulator": name in blocked,
                "detail": "band buy block differs",
            }
        )
    return rows


# The simulator's leader targets against the plan's own leader sizes.
def _sizing_rows(model, target, names) -> list[dict]:
    rows = []
    for j, name in names:
        live = float(model.get(name, 0.0))
        if abs(live - float(target[j])) > TOLERANCE:
            rows.append(
                {
                    "kind": PlanParityKind.SIZING,
                    "ticker": name,
                    "live": live,
                    "simulator": float(target[j]),
                    "detail": f"leader target differs by more than {TOLERANCE:g}",
                }
            )
    return rows


# One name's allowed post-plan weight around the simulator's target `want`:
# exactly its current weight when protected, exactly zero when the target is
# zero, else within max(min trade, one share) of it, the lower edge of a buy
# moved to what the cash on hand funds (`scale`).
def _band(rule, want, now, unit, scale, protected) -> tuple[float, float]:
    if protected:
        return now, now
    if want <= 0:
        return 0.0, 0.0
    width = max(rule.min_trade, unit)
    low = now + scale * (want - now) if want > now else want
    return low - width, want + width


# The ordinary night: inputs, sizing to `TOLERANCE`, holdings in the band.
def _ordinary_rows(paper, report, held, signed, rule):
    from backend.agents.trading.desk import exit as exit_analyst

    receipt = (paper.get("joint_funded") or {}).get("receipt") or {}
    if (
        receipt.get("status") != "available"
        or receipt.get("session") != paper.get("session")
    ):
        detail = (
            "the plan wrote no available sizing receipt for this session "
            f"(status {receipt.get('status')!r}, reason {receipt.get('reason')!r})"
        )
        return [{"kind": PlanParityKind.INPUTS, "detail": detail}], {}, {}
    panel = report.panel
    t = len(panel.dates) - 1
    tickers = list(panel.tickers)
    compared = [
        (j, n)
        for j, n in enumerate(tickers)
        if n not in policy_book.INDICES and n != panel.benchmark
    ]
    grades = np.asarray(report.graded.grades[t], dtype=int)
    band = np.asarray(exit_analyst.evidence(panel).signalled(), dtype=bool)[t]
    rows = _input_rows(receipt, tickers, grades, band)
    equity = float(receipt["observed_equity"])
    cash = float(receipt["observed_cash"])
    current = {k: float(v) for k, v in (receipt.get("current_weights") or {}).items()}
    # The planner's own price for a held name, decoded from its recorded
    # weight, equity and shares (the later positions read can mark differently).
    prices = _prices(paper, report, held)
    prices.update(
        {n: current[n] * equity / q for n, q in held.items() if current.get(n, 0) > 0}
    )
    shares = np.array([held.get(n, 0.0) for n in tickers])
    price = np.array([prices.get(n, math.nan) for n in tickers])
    adj = np.asarray(panel.adj_close, dtype=float)
    tilts = leader.report_pe_tilts(report)
    hold = rule.entry_grade if rule.hold_grade is None else rule.hold_grade
    target, protected = policy_book.plan_target(
        rule,
        policy_book.sizable(adj, tickers, panel.benchmark)[t],
        grades,
        np.where((shares > 0) & (grades < hold), 1, 0),
        shares,
        band,
        adj,
        t,
        np.array([current.get(n, 0.0) for n in tickers]),
        None if tilts is None else tilts[t],
    )
    rows += _sizing_rows(receipt.get("sizing_model_targets") or {}, target, compared)
    _, buys = policy_book.plan_orders(rule, target, shares, price, equity, protected)
    need = sum(q * price[j] for j, q in buys.items()) * (1 + rule.cost_bps / 1e4)
    scale = min(1.0, max(0.0, cash) / need) if need > 0 else 1.0
    names = {}
    for j, name in compared:
        after = shares[j] + signed.get(name, 0)
        if not (target[j] > 0 or shares[j] > 0 or after > 0):
            continue
        unit = price[j] / equity if np.isfinite(price[j]) else math.inf
        live = after * unit if after else 0.0
        now = shares[j] * unit if shares[j] else 0.0
        want = float(target[j])
        low, high = _band(rule, want, now, unit, scale, protected[j])
        names[name] = {
            "held": shares[j],
            "after": after,
            "live": live,
            "simulator": want,
            "low": low,
            "high": high,
        }
        if not (low - TOLERANCE <= live <= high + TOLERANCE):
            rows.append(
                {
                    "kind": PlanParityKind.HOLDING,
                    "ticker": name,
                    "live": live,
                    "simulator": want,
                    "low": low,
                    "high": high,
                    "detail": "weight after tonight's plan is outside the "
                    "simulator's rounding and minimum-trade band",
                }
            )
    return rows, names, {"cash_scale": scale, "equity": equity, "cash": cash}


# The comparison on data in hand: the saved record and the desk report the
# plan was decided from (its last session the record's). Pure: reads and
# writes nothing.
def compare(record: dict, report, rule: policy_book.Rule | None = None) -> dict:
    """Return the plan parity result for `record` on `report`."""
    from backend.agents.trading.desk import event_risk

    rule = rule or policy_book.Rule()
    session = record["session"]
    panel = report.panel
    last = str(panel.dates[-1])[:10]
    if last != session:
        raise ValueError(f"the report ends on {last}, not the record's {session}")
    paper = record.get("paper") or {}
    # Records from before the paper block named its policy carry it only on
    # their targets.
    policy = paper.get("policy") or (record.get("targets") or {}).get("policy")
    if policy != leader.POLICY:
        row = {
            "kind": PlanParityKind.POLICY,
            "live": policy,
            "simulator": leader.POLICY,
            "detail": f"the paper plan ran {policy or 'no named policy'}; "
            f"the simulator runs {leader.POLICY}",
        }
        return _result(session, policy, [row], path=None, live_path=None)
    held = {
        row["symbol"]: float(row["qty"])
        for row in paper.get("positions") or []
        if float(row.get("qty") or 0) > 0
    }
    signed = live_orders(paper)
    allocation = paper.get("joint_funded") or {}
    live_path = (
        PlanPath.EVENT
        if allocation.get("status") == "event_priority" and "receipt" not in allocation
        else PlanPath.ORDINARY
    )
    t = len(panel.dates) - 1
    shim = policy_book._Shim(
        panel.dates, panel.tickers, np.asarray(panel.adj_close, float), panel.benchmark
    )
    factor = float(event_risk.live_path(shim)[t]) if rule.fomc else 1.0
    cycle = (paper.get("event_risk") or {}).get("cycle") or {}
    day = _date.fromisoformat(session)
    sim_path, base, stage = _simulator_path(day, factor, cycle, held)
    if sim_path != live_path:
        row = {
            "kind": PlanParityKind.PATH,
            "live": live_path,
            "simulator": sim_path,
            "detail": f"the plan took the {live_path} path; the simulator "
            f"takes the {sim_path} path",
        }
        return _result(session, policy, [row], path=sim_path, live_path=live_path)
    if sim_path == PlanPath.EVENT:
        rows, names, extra = _event_rows(paper, report, base, stage, held, signed)
        basis = (
            "FOMC cycle: shares after tonight's plan against the cycle's cut, "
            "hold or restoration of the account's snapshot, exactly; a "
            "restoration may fall short only by what cash on hand cannot fund"
        )
    else:
        rows, names, extra = _ordinary_rows(paper, report, held, signed, rule)
        basis = (
            "ordinary night: leader target weights to "
            f"{TOLERANCE:g}; weight after tonight's plan within "
            f"max({rule.min_trade:g}, one share) of the target, zero where the "
            "target is zero, buys scaled by the cash on hand"
        )
    return _result(
        session, policy, rows, path=sim_path, live_path=live_path, basis=basis,
        names=names, **extra,
    )


# A check that could not run, in the result's shape, so a failure is shown.
def unavailable(day, exc: BaseException) -> dict:
    """Return an unavailable result for `day` explaining `exc`."""
    return {
        "version": VERSION,
        "date": str(day) if day else None,
        "checked_at": datetime.now(UTC).isoformat(),
        "verdict": PlanParity.UNAVAILABLE,
        "ok": False,
        "mismatches": [],
        "note": f"{type(exc).__name__}: {exc}",
    }


# One line for the job's log.
def line(result: dict) -> str:
    """Return the log line for `result`."""
    verdict = parse(PlanParity, result.get("verdict"))
    head = f"plan parity {result.get('date')}: {verdict.upper()}"
    if verdict is PlanParity.UNAVAILABLE:
        return f"{head} ({result.get('note')})"
    if verdict is PlanParity.OK:
        return f"{head} ({result.get('path')} path)"
    names = sorted({m["ticker"] for m in result["mismatches"] if m.get("ticker")})
    kinds = sorted({m["kind"] for m in result["mismatches"]})
    return (
        f"PLAN PARITY MISMATCH {result.get('date')}: {', '.join(kinds)}"
        + (f" - {', '.join(names)}" if names else "")
    )


def load(root: Path) -> dict:
    """Return {"version", "rows": [...]} from the parity file."""
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "rows": []}
    rows = data.get("rows") if isinstance(data, dict) else None
    return {"version": VERSION, "rows": list(rows or [])}


# The stored row for one session, or None; what the API hands the board.
def for_session(root: Path, session: str | None) -> dict | None:
    """Return the plan parity row checked for `session`."""
    if not session:
        return None
    for row in load(root)["rows"]:
        if row.get("date") == session:
            return row
    return None


# Append or replace the row for its date and keep the last `KEEP_DAYS`.
def write(root: Path, result: dict) -> Path:
    """Write `result` into the parity file and return the path."""
    rows = [r for r in load(root)["rows"] if r.get("date") != result["date"]]
    rows.append(result)
    rows.sort(key=lambda r: r.get("date") or "")
    newest = rows[-1].get("date")
    if newest:
        floor = _date.fromisoformat(newest) - timedelta(days=KEEP_DAYS)
        rows = [
            r for r in rows if r.get("date") and _date.fromisoformat(r["date"]) >= floor
        ]
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"version": VERSION, "rows": rows}, indent=2, default=float),
        encoding="utf-8",
    )
    return target


# The check end to end, writing its row. The replay job passes the report it
# built and the record of its session; the CLI rebuilds the report for a past
# session from the store (`desk.run` as of that session, the nightly's
# fundamentals mode). A check that raises is written as unavailable.
def run(root: Path, date=None, *, report=None, record: dict | None = None) -> dict:
    """Return the plan parity result for `date` (latest record), having written it."""
    result = check(root, date, report=report, record=record)
    if result.get("date"):
        write(root, result)
    return result


# The same check without writing: the result, or an unavailable result.
def check(root: Path, date=None, *, report=None, record: dict | None = None) -> dict:
    """Return the plan parity result for `date` (latest record)."""
    from backend.market import deskrecord

    root = Path(root)
    session = None
    try:
        if record is None:
            if date is None:
                record, _previous = deskrecord.latest_pair(root)
            else:
                record = deskrecord.load(root, str(date))
            if record is None:
                raise FileNotFoundError(
                    f"no desk record for {date or 'the latest session'} under {root}"
                )
        session = record["session"]
        if report is None:
            from backend.agents.trading.desk import desk as trading_desk
            from backend.market.store import MarketStore

            report = trading_desk.run(
                MarketStore(root),
                _date.fromisoformat(session),
                fundamentals=trading_desk.FUNDAMENTALS_CURRENT,
            )
        result = compare(record, report)
    except Exception as exc:  # noqa: BLE001 - reported as unavailable, never lost
        result = unavailable(session or date, exc)
    return result
