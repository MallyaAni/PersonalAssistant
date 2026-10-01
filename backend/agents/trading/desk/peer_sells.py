"""Sector-aware sells (S2): don't sell into the name's own peer group's rally.

Built for `docs/research/sector-sells-plan-2026-10-01.md`, behind the
`SECTOR_SELLS` switch, which is OFF unless set. The peer group, sigma_g,
R_g and both triggers are `backend.market.peer_groups`, the module the study
priced them with; nothing here restates a constant.

The switch takes one of four values:

* ``off`` (the default): nothing below runs and the paper orders are the
  board's `dip_or_close` orders, bit for bit.
* ``g1``: a downgrade sell (the name graded below A at the decision) whose
  peer group's first-bar return R_g is above sigma_g is not sent that
  session; the nightly re-plans it (a name regraded A is simply not sold).
* ``g2``: the same sells, when R_g > ln(1.01), skip the 1% pop trigger and
  go in at the close (market-on-close in the close window).
* ``g3``: G1's deferral for trims (graded A/A+) and exits graded C; a
  grade-B exit is left to the control.

The scope reads the point-in-time grade the study read: a name that is not
a member of the book at the decision counts as C. FOMC event and priority
orders are in no scope.

**The nightly** (`market_daily`) writes every book name's peer group, its
sigma_g, its scope grade and the close each R_g is measured from beside the
record (`<record folder>/sector-peers.json`), from the decision's own panel,
so the executor needs only the peers' first 15-minute bars, which the
balancer's entry-timing latch already holds (`first_bar.close`).

**The executor** (`intraday_orders.send_due`) asks `review` once per sell,
on the first candle after its session's opening bar is known, and records the
verdict on the pending row (`peer_rule`). Any missing piece - no peer file,
a file for another session, no group for the name, fewer than 3 of the 5
peers' first bars on file, an exception - records the control with the
reason and the order runs exactly as without the switch.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import grading
from backend.market import calendar, deskrecord, entry_timing
from backend.market import peer_groups as pg

# The switch: its environment variable, its values and its default.
ENV = "SECTOR_SELLS"
OFF = "off"
G1 = "g1"
G2 = "g2"
G3 = "g3"
MODES = (OFF, G1, G2, G3)
SECTOR_SELLS = OFF
# The verdicts recorded on a pending sell.
DEFER = "defer"
CLOSE = "close"
CONTROL = "control"
# The file beside the record, and the row key the verdict lives under.
FILE = "sector-peers.json"
ROW_KEY = "peer_rule"
NEW_YORK = calendar.NEW_YORK
# The grades each mode reads: downgrades (below A) for G1/G2; trims and C
# exits (not B) for G3.
_BELOW_A = (grading.B, grading.C)
_NOT_B = (grading.A_PLUS, grading.A, grading.C)
SCOPE = {G1: _BELOW_A, G2: _BELOW_A, G3: _NOT_B}


# The switch as set: the environment's SECTOR_SELLS when it is one of the
# four values, else the module default; with a reason when a value set in
# the environment was not understood (the switch then stays off).
def mode(environ: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """Return (mode, problem or None)."""
    env = os.environ if environ is None else environ
    raw = env.get(ENV)
    if raw is None or not str(raw).strip():
        return (SECTOR_SELLS if SECTOR_SELLS in MODES else OFF), None
    value = str(raw).strip().lower()
    if value in MODES:
        return value, None
    return OFF, f"{ENV}={raw!r} is not one of {', '.join(MODES)}; the switch is off"


# ----------------------------------------------------------------------------
# The nightly: every book name's peer group at the decision session.
# ----------------------------------------------------------------------------


# Every name's peer group at the panel's last session t, point in time:
# the 60-session residual correlations and sigma_g through t
# (`peer_groups.groups_at`, the study's own computation), the peers among
# the book's members at t (`membership`, the (T, N) grid; the benchmark is
# never a peer), each name's grade at t and the one the scope reads (C when
# the name is not a member at t), and every peer's close at t, the base of
# its first-bar return. Names with no group are listed without peers.
def compute(
    panel: Any, membership: np.ndarray, letters: Mapping[str, str]
) -> dict[str, Any]:
    """Return the peer block for the panel's last session."""
    tickers = tuple(str(t) for t in panel.tickers)
    market = tickers.index(str(panel.benchmark))
    mask = np.asarray(membership, dtype=bool).copy()
    mask[:, market] = False
    returns, masked, mkt, ok = pg.prepare(panel.adj_close, market, mask)
    t = len(panel.dates) - 1
    members, corr, sigma, has = pg.groups_at(returns, masked, mkt, ok[t], t)
    closes = np.asarray(panel.close, dtype=float)[t]
    names: dict[str, Any] = {}
    used: set[int] = set()
    for j, ticker in enumerate(tickers):
        if j == market:
            continue
        grade = letters.get(ticker)
        entry: dict[str, Any] = {
            "grade": grade,
            "scope_grade": grade if mask[t, j] else grading.C,
            "member": bool(mask[t, j]),
            "peers": [],
            "corr": [],
            "sigma_g": None,
        }
        if has[j]:
            entry["peers"] = [tickers[int(p)] for p in members[j]]
            entry["corr"] = [float(c) for c in corr[j]]
            entry["sigma_g"] = float(sigma[j])
            used.update(int(p) for p in members[j])
        names[ticker] = entry
    return {
        "session": str(np.datetime64(panel.dates[t], "D")),
        "benchmark": str(panel.benchmark),
        "parameters": {
            "k": pg.K_PEERS,
            "corr_sessions": pg.CORR_SESSIONS,
            "sigma_sessions": pg.PEER_SIGMA_SESSIONS,
            "min_priced": pg.MIN_PRICED_PEERS,
            "close_threshold": pg.CLOSE_THRESHOLD,
        },
        "names": names,
        "closes": {
            tickers[j]: float(closes[j])
            for j in sorted(used)
            if math.isfinite(float(closes[j])) and closes[j] > 0
        },
    }


# The block for a desk report's decision: its own panel, the point-in-time
# membership the study reads and the report's grades at the last session.
def from_report(report: Any) -> dict[str, Any]:
    """Return `compute` on the report's panel, membership and grades."""
    from backend.agents.trading.desk import point_in_time

    panel = report.panel
    tickers = tuple(str(t) for t in panel.tickers)
    membership = point_in_time.eligibility(panel.dates, tickers)
    last = len(panel.dates) - 1
    letters = {
        ticker: report.graded.letter(last, column)
        for column, ticker in enumerate(tickers)
        if ticker != panel.benchmark
    }
    return compute(panel, membership, letters)


# Where a session's peer file lives: beside its record.
def path(root: Path | str, session: str) -> Path:
    """Return the sector-peers file of `session`."""
    return deskrecord.folder(Path(root), str(session)) / FILE


# Write a session's peer block beside its record, atomically. Refuses when
# the session has no record (the folder must be a record's) and, unless
# `overwrite`, when the file already exists.
def write(root: Path | str, block: Mapping[str, Any], overwrite: bool = False) -> Path:
    """Write the block; return its path."""
    session = str(block["session"])
    target = path(root, session)
    if not (target.parent / "desk.json").exists():
        raise FileNotFoundError(f"no desk record for {session}")
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(block, indent=1), encoding="utf-8")
    temporary.replace(target)
    return target


# A session's peer block, or None when it is absent or unreadable.
def load(root: Path | str, session: str) -> dict[str, Any] | None:
    """Return the peer block of `session`, else None."""
    try:
        data = json.loads(path(root, session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ----------------------------------------------------------------------------
# The executor: one verdict per sell, recorded on the row.
# ----------------------------------------------------------------------------


# Whether a pending row is a sell any mode may judge: an ordinary sell on
# the board's intraday rule (never an FOMC event or priority order).
def judgeable(row: Mapping[str, Any], intraday_timing: str) -> bool:
    """Return True for an ordinary intraday sell."""
    return (
        row.get("side") == "sell"
        and row.get("execution_timing") == intraday_timing
        and not row.get("event_id")
        and not row.get("priority")
    )


# A recorded verdict's action, or None when the row has none.
def action(row: Mapping[str, Any]) -> str | None:
    """Return "defer", "close", "control" or None."""
    rule = row.get(ROW_KEY)
    return rule.get("action") if isinstance(rule, dict) else None


# Whether the row was held for the session by the deferral.
def deferred(row: Mapping[str, Any]) -> bool:
    """Return True when the recorded verdict is a deferral."""
    return action(row) == DEFER


# Whether the row waits for the close instead of the pop trigger.
def at_close(row: Mapping[str, Any]) -> bool:
    """Return True when the recorded verdict is the market-on-close rule."""
    return action(row) == CLOSE


# A first-bar log return: ln(first-bar close / close at t), None unless
# both are positive and finite.
def _first_return(first: object, base: object) -> float | None:
    """Return ln(first / base) or None."""
    try:
        a, b = float(first), float(base)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(b) and a > 0 and b > 0):
        return None
    return math.log(a / b)


# The name's entry in the session's peer block when the mode may judge it,
# else the plain reason it cannot: no file, another session's file, the name
# not listed, its grade out of the mode's scope, or no peer group.
def _entry(
    symbol: str, session: str, block: Mapping[str, Any] | None, mode_: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (entry or None, problem or None)."""
    if mode_ not in SCOPE:
        return None, f"switch {mode_!r} judges nothing"
    if block is None:
        return None, f"no peer file for the {session} decision"
    if str(block.get("session")) != session:
        return None, (
            f"the peer file is for {block.get('session')}, the order for {session}"
        )
    entry = (block.get("names") or {}).get(symbol)
    if not isinstance(entry, dict):
        return None, f"{symbol} is not in the {session} peer file"
    grade = entry.get("scope_grade")
    if grade not in SCOPE[mode_]:
        return entry, f"out of scope for {mode_.upper()} (grade {grade})"
    if len(entry.get("peers") or []) != pg.K_PEERS or entry.get("sigma_g") is None:
        return entry, f"{symbol} had no peer group on {session}"
    return entry, None


# The verdict on one sell under `mode`, from the session's peer block and
# today's latch, as the dict recorded on the row: the action (defer, close
# or control), the reason in plain words, and every number it was decided
# on (the peers, each peer's first-bar return, R_g, sigma_g, the threshold
# and the count priced). Never raises on missing data: each gap is a
# control verdict that says which piece was missing.
def judge(
    row: Mapping[str, Any],
    block: Mapping[str, Any] | None,
    latch: Mapping[str, Any] | None,
    mode_: str,
    now: datetime,
) -> dict[str, Any]:
    """Return the verdict for one pending sell."""
    symbol = str(row.get("symbol") or "")
    session = str(row.get("session") or "")
    out: dict[str, Any] = {
        "mode": mode_,
        "action": CONTROL,
        "decided_at": now.isoformat(timespec="seconds"),
        "session": session,
    }

    # Record a control verdict with its reason.
    def control(reason: str) -> dict[str, Any]:
        out["reason"] = reason
        return out

    entry, problem = _entry(symbol, session, block, mode_)
    if entry is not None:
        out["grade"] = entry.get("scope_grade")
    if problem is not None:
        return control(problem)
    peers = [str(p) for p in entry["peers"]]
    sigma = entry["sigma_g"]
    out["peers"] = peers
    out["sigma_g"] = float(sigma)
    symbols = (latch or {}).get("symbols") or {}
    closes = block.get("closes") or {}
    returns = {
        p: _first_return(
            ((symbols.get(p) or {}).get("first_bar") or {}).get("close"),
            closes.get(p),
        )
        for p in peers
    }
    out["peer_returns"] = returns
    morning, priced = pg.group_morning(returns.values())
    out["priced"] = priced
    out["morning"] = morning
    if morning is None:
        return control(
            f"only {priced} of {len(peers)} peers' first bars on file "
            f"(needs {pg.MIN_PRICED_PEERS})"
        )
    if mode_ == G2:
        out["threshold"] = pg.CLOSE_THRESHOLD
        if bool(pg.close_fires(morning)):
            out["action"] = CLOSE
            out["reason"] = "peer group's first bar above +1%"
            return out
        return control("peer group's first bar not above +1%")
    out["threshold"] = float(sigma)
    if bool(pg.defer_fires(morning, sigma)):
        out["action"] = DEFER
        out["reason"] = "peer group's first bar above its usual daily move"
        return out
    return control("peer group's first bar not above its usual daily move")


# Judge every unjudged sell among `rows` (today's unsent orders) whose
# session's opening bar is known, under `mode_`, and record the verdict on
# the row. `opened(row)` says whether the row's own open is known yet (its
# timing is past pre-open), so a verdict is made on the first candle that
# carries the opening bar and never before. Returns the log lines; any
# exception while judging a row records a control verdict naming it.
def review(
    rows: Iterable[dict],
    root: Path | str,
    latch: Mapping[str, Any] | None,
    mode_: str,
    now: datetime,
    intraday_timing: str,
    opened: Callable[[dict], bool],
) -> list[str]:
    """Record a verdict on each newly judgeable row; return log lines."""
    lines: list[str] = []
    blocks: dict[str, dict[str, Any] | None] = {}
    for row in rows:
        if not judgeable(row, intraday_timing) or ROW_KEY in row:
            continue
        try:
            if not opened(row):
                continue
            session = str(row.get("session") or "")
            if session not in blocks:
                blocks[session] = load(root, session)
            verdict = judge(row, blocks[session], latch, mode_, now)
        except Exception as exc:  # noqa: BLE001 - the control always survives
            verdict = {
                "mode": mode_,
                "action": CONTROL,
                "decided_at": now.isoformat(timespec="seconds"),
                "session": str(row.get("session") or ""),
                "reason": f"error while judging ({type(exc).__name__}: {exc})",
            }
        row[ROW_KEY] = verdict
        lines.append(log_line(row, verdict))
    return lines


# One verdict as the balancer's log line.
def log_line(row: Mapping[str, Any], verdict: Mapping[str, Any]) -> str:
    """Return e.g. "peer rule G1: sell 14 COHR DEFER (R_g +4.10% > ...)"."""
    head = (
        f"peer rule {str(verdict.get('mode')).upper()}: {row.get('side')} "
        f"{row.get('qty')} {row.get('symbol')} {str(verdict.get('action')).upper()}"
    )
    morning = verdict.get("morning")
    numbers = ""
    if morning is not None:
        numbers = (
            f" R_g {morning * 100:+.2f}% vs {float(verdict['threshold']) * 100:.2f}%"
            if verdict.get("threshold") is not None
            else f" R_g {morning * 100:+.2f}%"
        )
        count = len(verdict.get("peers") or [])
        numbers += f", {verdict.get('priced')} of {count} peers"
    return f"{head} ({verdict.get('reason')}{';' if numbers else ''}{numbers})"


# The orders the board's control rule would send now for a row on the
# market-on-close verdict: nothing before the close window, then exactly
# the control's own close-window order (market-on-close before its cutoff,
# a market order after it), and never on a session where the control would
# send nothing (its timing must be acting: triggered or close).
def close_only(timed: Mapping[str, Any], now: datetime, today: date) -> str | None:
    """Return "moc", "market" or None for a row waiting for the close."""
    if timed.get("state") not in entry_timing.ACTING:
        return None
    clock = entry_timing.session_clock(today)
    if clock["cutoff"] <= now < clock["moc"]:
        return "moc"
    if clock["moc"] <= now < clock["close"]:
        return "market"
    return None


# ----------------------------------------------------------------------------
# The board's sentences.
# ----------------------------------------------------------------------------


# A log return as the board prints a move: the geometric move in percent,
# signed, to one decimal (two when one would print the same as `other`).
def _move(value: float, other: str | None = None) -> str:
    """Return e.g. "+4.1%"."""
    pct = math.expm1(value) * 100.0
    text = f"{pct:+.1f}%"
    if other is not None and text.lstrip("+") == other:
        text = f"{pct:+.2f}%"
    return text


# The grey note under a held or close-only sell, from its recorded numbers;
# None for any other row. Every number is the verdict's own.
def board_note(row: Mapping[str, Any]) -> str | None:
    """Return the plain sentence for a sell the peer rule held or moved."""
    rule = row.get(ROW_KEY)
    if not isinstance(rule, dict) or rule.get("action") not in (DEFER, CLOSE):
        return None
    morning = rule.get("morning")
    if morning is None:
        return None
    peers = ", ".join(str(p) for p in rule.get("peers") or [])
    if rule["action"] == CLOSE:
        return f"Selling at the close: its peer group ({peers}) opened {_move(morning)}"
    sigma = float(rule.get("sigma_g") or 0.0)
    usual = f"{sigma * 100:.1f}%"
    opened = _move(morning, usual)
    if len(opened) > len(f"{math.expm1(morning) * 100:+.1f}%"):
        # The two printed alike at one decimal: both go to two.
        usual = f"{sigma * 100:.2f}%"
    return (
        f"Held: its peer group ({peers}) opened {opened}, above its usual daily "
        f"move {usual}; sale re-planned tonight"
    )


# ----------------------------------------------------------------------------
# The nightly's account of last session's deferred sells.
# ----------------------------------------------------------------------------


# What tonight's plan did with each sell the deferral held last session:
# planned again, or not sold because the name was regraded A/A+, or not
# sold because tonight's plan has no sell of it for another reason.
# `held` maps client order id to the pending row as it was before the
# reconcile; `orders` are tonight's planned orders; `grades` tonight's.
def replanned(
    held: Mapping[str, Mapping[str, Any]],
    orders: Iterable[Any],
    grades: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Return one record per deferred sell with what the nightly did."""
    selling = {str(o.symbol) for o in orders if getattr(o, "side", None) == "sell"}
    out: list[dict[str, Any]] = []
    for cid, row in sorted(held.items()):
        if not deferred(row):
            continue
        symbol = str(row.get("symbol") or "")
        grade = grades.get(symbol)
        if symbol in selling:
            outcome = "sell planned again"
        elif grade in (grading.A_PLUS, grading.A):
            outcome = f"not sold: regraded {grade}"
        else:
            outcome = "not sold: tonight's plan has no sell of it"
        out.append(
            {
                "client_order_id": cid,
                "symbol": symbol,
                "qty": int(row.get("qty") or 0),
                "decided": row.get("session"),
                "deferred_on": row.get("execute_on"),
                "grade_tonight": grade,
                "outcome": outcome,
                "rule": dict(row.get(ROW_KEY) or {}),
            }
        )
    return out
