"""Move the paper account's queued orders onto the board's intraday rule, once.

The nightly of 2026-09-29 queued its orders the old way (buys for the next
open, sells for the next close) hours before the board's rule became the paper
account's (`desk/intraday_orders.py`). The operator asked for the new rule to
apply from the next session rather than the one after, so this command:

1. finds the ordinary orders still pending from the latest decision that are
   not on the intraday rule (FOMC event and priority orders are never touched);
2. refuses when their execution session's open has already passed, since the
   opening buys may have filled;
3. cancels each at the broker by the desk's own client order id, and only an
   order whose cancel the broker CONFIRMS with nothing filled is moved: its
   row is rewritten, same symbol, side, shares, reason and plan leg, with a
   fresh client order id, `execution_timing = dip_or_close`, the session it
   executes on, and `replaced` naming the cancelled id. Any other outcome
   (unconfirmed, already gone, partly filled) leaves the row exactly as it was.

The balancer then sends the moved orders on the board's rule. The default is a
dry run that prints the plan and touches nothing; `--apply` does it.

Run it on spark1 the way the nightly runs (the deploy clone, `.env` exported,
the Alpaca paper keys in the environment), never inside the backend container,
whose root-owned writes the nightly could not read back:

    python -m backend.cli.market_paper_retime
    python -m backend.cli.market_paper_retime --apply
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.agents.trading.desk import intraday_orders, paper
from backend.config.settings import settings
from backend.market import entry_timing


# The pending rows this command may move: ordinary orders of one decision not
# yet on the intraday rule. FOMC event and priority orders keep their timing.
def movable(state: paper.PaperState) -> list[dict]:
    """Return the pending rows that could move onto the intraday rule."""
    return [
        row
        for row in state.pending
        if not row.get("event_id")
        and not row.get("priority")
        and row.get("execution_timing") != intraday_orders.INTRADAY_TIMING
    ]


# The session the moved orders execute on, or a reason they cannot move: rows
# from more than one decision, a date the calendar does not cover, or a
# session whose open has already passed.
def target_session(rows: list[dict], now: datetime) -> tuple[date | None, str | None]:
    """Return (execution session, None) or (None, why the rows cannot move)."""
    decided = {str(row.get("session") or "") for row in rows}
    if len(decided) != 1:
        return None, f"pending orders come from {len(decided)} decisions; move none"
    try:
        upcoming = intraday_orders.next_session(date.fromisoformat(decided.pop()))
    except ValueError:
        return None, "the pending orders carry no valid decision session"
    if upcoming is None:
        return None, "the calendar does not cover the next session"
    opens = entry_timing.session_clock(upcoming)["open"]
    if now >= opens:
        return None, (
            f"the {upcoming.isoformat()} session opened at {opens.isoformat()}; "
            "its opening orders may have filled"
        )
    return upcoming, None


# Rewrite one confirmed-cancelled row onto the intraday rule under a fresh id.
def moved(row: dict, state: paper.PaperState, upcoming: date) -> dict:
    """Return the row on the intraday rule, with a new client order id."""
    seq = state.order_seq
    state.order_seq += 1
    return {
        **row,
        "client_order_id": paper.order_id(
            str(row.get("session")), str(row.get("symbol")), str(row.get("side")), seq
        ),
        "execution_timing": intraday_orders.INTRADAY_TIMING,
        "execute_on": upcoming.isoformat(),
        "replaced": row.get("client_order_id"),
    }


# Move the queued orders (see the module docstring); return the printed lines.
def retime(
    root: Path | str,
    now: datetime,
    client_factory: Callable[[], Any],
    apply: bool,
) -> list[str]:
    """Plan or apply the move of the queued orders onto the intraday rule."""
    if now.tzinfo is None:
        raise ValueError("retime requires a timezone-aware now")
    root = Path(root)
    with paper.transaction(root):
        state = paper.load_state(root)
        rows = movable(state)
        if not rows:
            return ["nothing to move: no queued ordinary orders are pending"]
        upcoming, refusal = target_session(rows, now)
        if refusal:
            return [f"refused: {refusal}"]
        assert upcoming is not None
        lines = [
            f"{'moving' if apply else 'would move'} {len(rows)} orders onto the "
            f"board's rule for {upcoming.isoformat()}:"
        ]
        lines += [
            f"  {row['side']:4} {int(row['qty']):5d} {row['symbol']:6} "
            f"{intraday_orders.why(row)[1]}  ({row['client_order_id']})"
            for row in rows
        ]
        if not apply:
            return lines + ["dry run: nothing cancelled, nothing written (--apply)"]
        outcomes = client_factory().cancel_orders(
            [str(r["client_order_id"]) for r in rows]
        )
        kept = 0
        for row in rows:
            outcome = outcomes.get(str(row["client_order_id"]))
            if outcome != "cancelled":
                kept += 1
                lines.append(
                    f"  kept {row['symbol']} as queued: the cancel was {outcome}"
                )
                continue
            index = state.pending.index(row)
            state.pending[index] = moved(row, state, upcoming)
            lines.append(
                f"  moved {row['side']} {row['qty']} {row['symbol']} -> "
                f"{state.pending[index]['client_order_id']}"
            )
        paper.save_state(root, state)
        lines.append(
            f"done: {len(rows) - kept} moved, {kept} kept as queued; the balancer "
            "sends the moved ones on the board's rule"
        )
        return lines


# The command's arguments.
def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=settings.MARKET_DATA_ROOT,
        help="desk data root (the nightly's default)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="cancel and move (default: dry run)"
    )
    return parser


# Entry point: print the plan, or apply it with --apply.
def main() -> None:
    """Run the command."""
    from backend.market import alpaca_trading

    args = build_parser().parse_args()
    for line in retime(
        Path(args.data_dir),
        datetime.now(UTC),
        alpaca_trading.client_from_env,
        args.apply,
    ):
        print(line)


if __name__ == "__main__":
    main()
