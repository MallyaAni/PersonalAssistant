"""Ask the nightly's questions before it runs, and after.

    python -m backend.cli.market_nightly_check preflight --root <repo>
    python -m backend.cli.market_nightly_check health    --root <repo>

The 19:30 nightly can stop without crashing, and when it does the dashboard
keeps showing yesterday's book and nobody is told. It has happened three
ways:

* a release/admission mismatch made the nightly print
  "paper book: not traded (ValueError: Exact reviewed learned holding release
  required)" on 2026-10-14, 15 and 16 - three sessions without a rebalance
  while the account fell about ten percent;
* the funded guard refused an account whose broker marks did not add up and
  the plan became "joint-funded-unavailable" on 2026-10-29;
* a broker clock that reports the market open makes the nightly refuse every
  ordinary order ("orders are queued for the next open after the close").

`preflight` checks the same three inputs before the decision window:
trading admission, the broker clock, and the funded account reconciliation
the nightly itself applies (`joint_funded_policy._account`). `health` runs
after the nightly and checks what it wrote: today's history entry, an
available funded receipt, no refused orders, a strategy publication for
today, and the last "paper book" line in the log.

Both write their verdict where a person or a later session can read it
(`data/market/desk/nightly-readiness.json`, `nightly-health.json`) and page
the operator through `scripts/notify-operator.sh` when the verdict is red.
Neither ever blocks the nightly: `~/desk_daily.sh` runs each with `|| true`.
"""

import argparse
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.cli import market_release_admission
from backend.market import alpaca_trading, calendar, joint_funded_policy


# The market store under a repo root, or the root itself when it is one.
def _market_root(root: Path) -> Path:
    root = Path(root)
    market = root / "data" / "market"
    return market if market.is_dir() else root


# Require an explicit instant rather than guessing a timezone.
def _instant(value: str | None) -> datetime:
    now = datetime.fromisoformat(value) if value else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("a timezone-aware instant is required")
    return now


# Write the verdict atomically so a reader never sees a partial file.
def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


# Page the operator, best effort: a broken bridge must not change the verdict.
def _alert(root: Path, message: str) -> None:
    script = Path(root) / "scripts" / "notify-operator.sh"
    if not script.exists():
        return
    try:
        subprocess.run(["bash", str(script), message], check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


# One verdict, with the reasons a person can act on.
def _verdict(mode: str, now: datetime, session: str, reasons, checks) -> dict:
    return {
        "mode": mode,
        "at": now.isoformat(),
        "session": session,
        "status": "ok" if not reasons else "failed",
        "reasons": list(reasons),
        "checks": checks,
    }


# The last line the nightly printed about the paper book, or None.
def _last_paper_book(log_path: Path | None) -> str | None:
    if log_path is None:
        return None
    path = Path(log_path)
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines[-400:]):
        if "paper book" in line:
            return line.strip()
    return None


# The three inputs the nightly needs; mirrors what it does with each.
def preflight(
    root: Path,
    now: datetime | None = None,
    *,
    client=None,
    admission=None,
    notify=None,
) -> dict:
    now = now or datetime.now(UTC)
    market = _market_root(root)
    reasons = []
    checks = {}
    if admission is None:
        admission = lambda: market_release_admission.check(market)
    try:
        admitted = admission()
        checks["admission"] = (
            admitted.get("status") if isinstance(admitted, dict) else None
        )
        if checks["admission"] != "ADMITTED":
            reasons.append(f"trading admission {checks['admission'] or 'unknown'}")
    except Exception as exc:
        checks["admission"] = "error"
        reasons.append(f"trading admission check failed: {exc}")
    if client is None:
        try:
            client = alpaca_trading.client_from_env()
        except Exception as exc:
            checks["broker"] = "error"
            reasons.append(f"broker client unavailable: {exc}")
    if client is not None:
        try:
            clock = client.clock() or {}
            checks["market_clock"] = {
                "is_open": clock.get("is_open"),
                "next_open": clock.get("next_open"),
                "next_close": clock.get("next_close"),
            }
            if clock.get("is_open") is not False:
                reasons.append(
                    "broker reports the market open; the nightly refuses "
                    "ordinary orders"
                )
        except Exception as exc:
            checks["market_clock"] = "error"
            reasons.append(f"broker clock unavailable: {exc}")
        try:
            account = client.account()
            positions = client.positions()
            held = {row.symbol: row.qty for row in positions}
            marks = {
                row.symbol: row.market_value / row.qty
                for row in positions
                if row.qty > 0
            }
            current, reserve, reason = joint_funded_policy._account(
                account.equity, held, marks, account.cash
            )
            checks["account"] = {
                "equity": account.equity,
                "cash": account.cash,
                "held": len(held),
                "reason": reason,
            }
            if reason:
                reasons.append(f"funded account guard: {reason}")
            elif (
                sum(current.values()) + float(account.cash) / float(account.equity)
                > 1 + 1e-10
            ):
                reasons.append("funded weights plus cash exceed one")
        except Exception as exc:
            checks["account"] = "error"
            reasons.append(f"broker account unavailable: {exc}")
    session = str(calendar.exchange_status(now)["session"])
    result = _verdict("preflight", now, session, reasons, checks)
    _write_status(market / "desk" / "nightly-readiness.json", result)
    if reasons:
        message = (
            f"AniOS nightly preflight failed for {session}: "
            + "; ".join(reasons[:3])
        )
        (notify or (lambda text: _alert(root, text)))(message[:400])
    return result


# What the nightly wrote, and whether it was a book that can trade.
def health(
    root: Path,
    now: datetime | None = None,
    *,
    log_path=None,
    state=None,
    notify=None,
) -> dict:
    now = now or datetime.now(UTC)
    market = _market_root(root)
    status = calendar.exchange_status(now)
    session = str(status["session"])
    # A holiday has no book to check, and a red page on one would train the
    # operator to ignore the alert.
    if status.get("calendar_known") and not status.get("is_session"):
        result = _verdict("health", now, session, [], {"session_open": False})
        _write_status(market / "desk" / "nightly-health.json", result)
        return result
    reasons = []
    checks = {"session_open": bool(status.get("open"))}
    if state is None:
        state = paper.load_state(market)
    history = state.history or []
    last = history[-1] if history else {}
    checks["history_session"] = last.get("session")
    checks["history_written"] = last.get("written")
    checks["plan"] = last.get("plan")
    if last.get("session") != session:
        reasons.append(
            f"today's book was not written (last session {last.get('session')})"
        )
    else:
        written = last.get("written")
        if not written:
            reasons.append("today's book has no written timestamp")
        else:
            try:
                stamp = datetime.fromisoformat(written)
                if (
                    stamp.tzinfo is None
                    or stamp.astimezone(calendar.NEW_YORK).date().isoformat()
                    != session
                ):
                    reasons.append(f"today's book was written at {written}, not today")
            except ValueError:
                reasons.append(
                    f"today's book has an unreadable written timestamp {written!r}"
                )
    receipt = ((state.allocation_state or {}).get("receipt") or {})
    checks["receipt_status"] = receipt.get("status")
    checks["receipt_reason"] = receipt.get("reason")
    if receipt.get("status") != "available":
        reasons.append(
            f"funded receipt {receipt.get('status') or 'missing'}: "
            f"{receipt.get('reason') or 'no reason'}"
        )
    if last.get("plan") == "joint-funded-unavailable":
        reasons.append("plan note joint-funded-unavailable")
    refused = last.get("refused") or []
    checks["refused"] = len(refused)
    if refused:
        reasons.append(f"{len(refused)} order(s) refused: {refused[0]}")
    log_line = _last_paper_book(log_path)
    checks["log_line"] = log_line
    if log_line and (
        "not traded" in log_line or "joint-funded-unavailable" in log_line
    ):
        reasons.append(f"nightly log: {log_line}")
    publication = market / "desk" / "strategy-recommendations" / "latest.json"
    checks["publication_session"] = None
    if not publication.exists():
        reasons.append("strategy publication missing")
    else:
        try:
            published = json.loads(publication.read_text(encoding="utf-8"))
            checks["publication_session"] = published.get("session")
            if published.get("session") != session:
                reasons.append(
                    f"strategy publication is for {published.get('session')}, not today"
                )
        except (OSError, ValueError):
            reasons.append("strategy publication unreadable")
    result = _verdict("health", now, session, reasons, checks)
    _write_status(market / "desk" / "nightly-health.json", result)
    if reasons:
        message = (
            f"AniOS nightly health failed for {session}: "
            + "; ".join(reasons[:3])
        )
        (notify or (lambda text: _alert(root, text)))(message[:400])
    return result


# Run one mode and exit red when the verdict is red.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the nightly before and after it runs."
    )
    parser.add_argument("mode", choices=("preflight", "health"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--log", default=str(Path.home() / "desk_daily.log"))
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    try:
        now = _instant(args.now)
    except ValueError as exc:
        parser.error(str(exc))
    root = Path(args.root).resolve()
    if args.mode == "preflight":
        result = preflight(root, now)
    else:
        result = health(root, now, log_path=Path(args.log))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
