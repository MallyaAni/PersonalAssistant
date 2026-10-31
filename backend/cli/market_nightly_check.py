"""Ask the nightly's questions before it runs, and after.

    python -m backend.cli.market_nightly_check preflight --root <repo>
    python -m backend.cli.market_nightly_check health    --root <repo>
    python -m backend.cli.market_nightly_check freshness --root <repo>

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

`freshness` is the dead-man's switch for the case none of those cover: the
nightly never starts at all, so `health` never runs and never pages. A
separate 20:15 cron asks whether today's health verdict exists; a missing
or yesterday's verdict pages the operator.

All three write their verdict where a person or a later session can read it
(`data/market/desk/nightly-readiness.json`, `nightly-health.json`,
`nightly-freshness.json`) and page the operator through
`scripts/notify-operator.sh` when the verdict is red. None ever blocks the
nightly: `~/desk_daily.sh` runs each with `|| true`.
"""

import argparse
import contextlib
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
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["bash", str(script), message], check=False, timeout=30)


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


# Send one page for a red verdict.
def _page(root: Path, mode: str, session: str, reasons, notify) -> None:
    message = f"AniOS nightly {mode} failed for {session}: " + "; ".join(reasons[:3])
    if notify is None:
        _alert(root, message[:400])
    else:
        notify(message[:400])


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


# Admission as the nightly will find it, without broker or model inference.
def _admission_status(market: Path, admission):
    try:
        if admission is None:
            admitted = market_release_admission.check(market)
        else:
            admitted = admission()
        status = admitted.get("status") if isinstance(admitted, dict) else None
        if status != "ADMITTED":
            return status, f"trading admission {status or 'unknown'}"
        return status, None
    except Exception as exc:
        return "error", f"trading admission check failed: {exc}"


# The broker client, or the reason it could not be made.
def _broker_client(client):
    if client is not None:
        return client, None
    try:
        return alpaca_trading.client_from_env(), None
    except Exception as exc:
        return None, f"broker client unavailable: {exc}"


# The broker clock, and whether it says ordinary orders would be refused.
def _clock_status(client):
    try:
        clock = client.clock() or {}
        checks = {
            "is_open": clock.get("is_open"),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        }
        if clock.get("is_open") is not False:
            return checks, (
                "broker reports the market open; the nightly refuses ordinary orders"
            )
        return checks, None
    except Exception as exc:
        return "error", f"broker clock unavailable: {exc}"


# The funded guard's own reconciliation of broker equity, marks and cash.
def _account_status(client):
    try:
        account = client.account()
        positions = client.positions()
        held = {row.symbol: row.qty for row in positions}
        marks = {
            row.symbol: row.market_value / row.qty
            for row in positions
            if row.qty > 0
        }
        current, _, reason = joint_funded_policy._account(
            account.equity, held, marks, account.cash
        )
        checks = {
            "equity": account.equity,
            "cash": account.cash,
            "held": len(held),
            "reason": reason,
        }
        if reason:
            return checks, f"funded account guard: {reason}"
        total = sum(current.values()) + float(account.cash) / float(account.equity)
        if total > 1 + 1e-10:
            return checks, "funded weights plus cash exceed one"
        return checks, None
    except Exception as exc:
        return "error", f"broker account unavailable: {exc}"


# Whether today's history entry is present and stamped with today.
def _history_status(last, session):
    checks = {
        "history_session": last.get("session"),
        "history_written": last.get("written"),
        "plan": last.get("plan"),
    }
    if last.get("session") != session:
        return checks, (
            f"today's book was not written (last session {last.get('session')})"
        )
    written = last.get("written")
    if not written:
        return checks, "today's book has no written timestamp"
    try:
        stamp = datetime.fromisoformat(written)
    except ValueError:
        return checks, f"today's book has an unreadable written timestamp {written!r}"
    if (
        stamp.tzinfo is None
        or stamp.astimezone(calendar.NEW_YORK).date().isoformat() != session
    ):
        return checks, f"today's book was written at {written}, not today"
    return checks, None


# Whether the funded receipt is available, and why it is not.
def _receipt_status(state):
    receipt = (state.allocation_state or {}).get("receipt") or {}
    checks = {
        "receipt_status": receipt.get("status"),
        "receipt_reason": receipt.get("reason"),
    }
    if receipt.get("status") != "available":
        return checks, (
            f"funded receipt {receipt.get('status') or 'missing'}: "
            f"{receipt.get('reason') or 'no reason'}"
        )
    return checks, None


# Whether the plan note itself says the funded plan was unavailable.
def _plan_status(last):
    if last.get("plan") == "joint-funded-unavailable":
        return "plan note joint-funded-unavailable"
    return None


# How many orders the nightly refused, and the first one.
def _refused_status(last):
    refused = last.get("refused") or []
    if refused:
        return len(refused), f"{len(refused)} order(s) refused: {refused[0]}"
    return 0, None


# The last paper-book log line, when it reports a night that did not trade.
def _log_status(log_path):
    line = _last_paper_book(log_path)
    if line and ("not traded" in line or "joint-funded-unavailable" in line):
        return line, f"nightly log: {line}"
    return line, None


# Whether the strategy publication is for today.
def _publication_status(publication: Path, session: str):
    if not publication.exists():
        return None, "strategy publication missing"
    try:
        published = json.loads(publication.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "strategy publication unreadable"
    if published.get("session") != session:
        return published.get("session"), (
            f"strategy publication is for {published.get('session')}, not today"
        )
    return published.get("session"), None


# A closed day has no book to check, and a page on one would train the
# operator to ignore the alert.
def _closed_day(status) -> bool:
    return bool(status.get("calendar_known")) and not status.get("is_session")


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
    checks["admission"], reason = _admission_status(market, admission)
    if reason:
        reasons.append(reason)
    client, reason = _broker_client(client)
    if reason:
        checks["broker"] = "error"
        reasons.append(reason)
    if client is not None:
        checks["market_clock"], reason = _clock_status(client)
        if reason:
            reasons.append(reason)
        checks["account"], reason = _account_status(client)
        if reason:
            reasons.append(reason)
    session = str(calendar.exchange_status(now)["session"])
    result = _verdict("preflight", now, session, reasons, checks)
    _write_status(market / "desk" / "nightly-readiness.json", result)
    if reasons:
        _page(root, "preflight", session, reasons, notify)
    return result


# What the nightly wrote, and whether it was a book that could trade.
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
    if _closed_day(status):
        result = _verdict("health", now, session, [], {"session_open": False})
        _write_status(market / "desk" / "nightly-health.json", result)
        return result
    reasons = []
    checks = {"session_open": bool(status.get("open"))}
    if state is None:
        state = paper.load_state(market)
    history = state.history or []
    last = history[-1] if history else {}
    history_checks, reason = _history_status(last, session)
    checks.update(history_checks)
    if reason:
        reasons.append(reason)
    receipt_checks, reason = _receipt_status(state)
    checks.update(receipt_checks)
    if reason:
        reasons.append(reason)
    reason = _plan_status(last)
    if reason:
        reasons.append(reason)
    checks["refused"], reason = _refused_status(last)
    if reason:
        reasons.append(reason)
    checks["log_line"], reason = _log_status(log_path)
    if reason:
        reasons.append(reason)
    publication = market / "desk" / "strategy-recommendations" / "latest.json"
    checks["publication_session"], reason = _publication_status(publication, session)
    if reason:
        reasons.append(reason)
    result = _verdict("health", now, session, reasons, checks)
    _write_status(market / "desk" / "nightly-health.json", result)
    if reasons:
        _page(root, "health", session, reasons, notify)
    return result


# Today's health verdict, as the dead-man's switch reads it: written after
# tonight's nightly, stamped today, and green. A red verdict is still a
# verdict; it is reported here because the health check's page may not have
# reached the operator, and a second page on a bad night is cheaper than
# silence.
def _health_status(market: Path, session: str):
    path = market / "desk" / "nightly-health.json"
    checks = {"health_session": None, "health_at": None, "health_status": None}
    if not path.exists():
        return checks, "no nightly health verdict for today"
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return checks, "nightly health verdict unreadable"
    checks.update(
        health_session=verdict.get("session"),
        health_at=verdict.get("at"),
        health_status=verdict.get("status"),
    )
    if verdict.get("session") != session:
        return checks, (
            f"nightly health verdict is for {verdict.get('session')}, not today; "
            "the nightly may not have started"
        )
    written = verdict.get("at")
    try:
        stamp = datetime.fromisoformat(written)
    except (TypeError, ValueError):
        return checks, f"nightly health verdict has an unreadable timestamp {written!r}"
    if (
        stamp.tzinfo is None
        or stamp.astimezone(calendar.NEW_YORK).date().isoformat() != session
    ):
        return checks, f"nightly health verdict was written at {written}, not today"
    if verdict.get("status") != "ok":
        reasons = verdict.get("reasons") or []
        first = reasons[0] if reasons else "no reason recorded"
        return checks, f"nightly health verdict is red: {first}"
    return checks, None


# The dead-man's switch: today's nightly produced a health verdict at all.
# A closed day has no nightly to miss, and a page on one would train the
# operator to ignore the alert.
def freshness(
    root: Path,
    now: datetime | None = None,
    *,
    notify=None,
) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("a timezone-aware instant is required")
    market = _market_root(root)
    status = calendar.exchange_status(now)
    session = str(status["session"])
    if _closed_day(status):
        result = _verdict("freshness", now, session, [], {"session_open": False})
        _write_status(market / "desk" / "nightly-freshness.json", result)
        return result
    checks = {"session_open": bool(status.get("open"))}
    health_checks, reason = _health_status(market, session)
    checks.update(health_checks)
    reasons = [reason] if reason else []
    result = _verdict("freshness", now, session, reasons, checks)
    _write_status(market / "desk" / "nightly-freshness.json", result)
    if reasons:
        _page(root, "freshness", session, reasons, notify)
    return result


# Run one mode and exit red when the verdict is red.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the nightly before and after it runs."
    )
    parser.add_argument("mode", choices=("preflight", "health", "freshness"))
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
    elif args.mode == "health":
        result = health(root, now, log_path=Path(args.log))
    else:
        result = freshness(root, now)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
