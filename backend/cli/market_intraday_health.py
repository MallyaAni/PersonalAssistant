"""Page the operator when the intraday board stops refreshing.

    python -m backend.cli.market_intraday_health --root <repo>

`market_balancer` runs every fifteen minutes in the regular session and
writes `data/market/desk/intraday.json` with an `as_of` stamp. When the
balancer stops - a bad deploy, a dead quote feed, a full disk - the
dashboard keeps serving the last candle and nothing says it is old. This
check runs after each balancer attempt: during the regular session it
requires an `as_of` no older than 30 minutes and pages through
`scripts/notify-operator.sh` when the plan is stale. Outside the session
there is nothing to refresh, and a closed day is green.

A red verdict repeats at most every 90 minutes, so a broken balancer pages
twice an hour rather than four times. The verdict is written to
`data/market/desk/intraday-health.json`. The check never blocks the
balancer: `~/desk_intraday.sh` runs it with `|| true` and keeps the
balancer's own exit status.
"""

import argparse
import contextlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.market import calendar

FILE = "intraday-health.json"
PLAN = "desk/intraday.json"
DEFAULT_MAX_AGE_MINUTES = 30
DEFAULT_REPEAT_MINUTES = 90


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


# Send one page for a red verdict.
def _page(root: Path, session: str, reasons, notify) -> None:
    message = f"AniOS intraday board is stale for {session}: " + "; ".join(
        reasons[:3]
    )
    if notify is None:
        _alert(root, message[:400])
    else:
        notify(message[:400])


# One verdict, with the reasons a person can act on.
def _verdict(now: datetime, session: str, reasons, checks) -> dict:
    return {
        "mode": "intraday",
        "at": now.isoformat(),
        "session": session,
        "status": "ok" if not reasons else "failed",
        "reasons": list(reasons),
        "checks": checks,
    }


# How old the board's last candle is, and why that is too old.
def _plan_status(market: Path, now: datetime, max_age: timedelta):
    path = market / PLAN
    checks = {"plan_as_of": None, "plan_age_minutes": None}
    if not path.exists():
        return checks, "intraday plan missing"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return checks, "intraday plan unreadable"
    written = plan.get("as_of")
    checks["plan_as_of"] = written
    try:
        stamp = datetime.fromisoformat(written)
    except (TypeError, ValueError):
        return checks, f"intraday plan has an unreadable as_of {written!r}"
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return checks, f"intraday plan as_of {written} has no timezone"
    age = now - stamp
    checks["plan_age_minutes"] = round(age.total_seconds() / 60, 1)
    if age < -timedelta(minutes=2):
        return checks, f"intraday plan as_of {written} is in the future"
    if age > max_age:
        minutes = round(age.total_seconds() / 60, 1)
        return checks, (
            f"intraday plan is stale: as_of {written} is {minutes} minutes old"
        )
    # The plan's session is the evening record it was built from, which is
    # the previous trading day during the current one; only as_of is the
    # freshness signal.
    return checks, None


# Whether this red verdict should page, and when the previous page was.
# A balancer that stays broken pages twice an hour, not on every attempt.
def _page_due(path: Path, now: datetime, repeat: timedelta):
    checks = {"last_page_at": None}
    if not path.exists():
        return checks, True
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return checks, True
    last = previous.get("last_page_at")
    checks["last_page_at"] = last
    if previous.get("status") != "failed" or not last:
        return checks, True
    try:
        stamp = datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return checks, True
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return checks, True
    return checks, now - stamp >= repeat


# The board's freshness during the regular session, and the page when it is old.
def check(
    root: Path,
    now: datetime | None = None,
    *,
    max_age_minutes: int = DEFAULT_MAX_AGE_MINUTES,
    repeat_minutes: int = DEFAULT_REPEAT_MINUTES,
    notify=None,
) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("a timezone-aware instant is required")
    market = _market_root(root)
    status = calendar.exchange_status(now)
    session = str(status["session"])
    calendar_known = bool(status.get("calendar_known"))
    session_open = bool(status.get("open"))
    checks = {"calendar_known": calendar_known, "session_open": session_open}
    # Outside the regular session there is no candle to refresh, and a
    # closed day has no board at all; a page then would train the operator
    # to ignore the alert.
    if not calendar_known or not status.get("is_session") or not session_open:
        result = _verdict(now, session, [], checks)
        _write_status(market / "desk" / FILE, result)
        return result
    plan_checks, reason = _plan_status(
        market, now, timedelta(minutes=max_age_minutes)
    )
    checks.update(plan_checks)
    reasons = [reason] if reason else []
    verdict_path = market / "desk" / FILE
    if reasons:
        page_checks, due = _page_due(
            verdict_path, now, timedelta(minutes=repeat_minutes)
        )
        checks.update(page_checks)
        if due:
            checks["last_page_at"] = now.isoformat()
            _page(root, session, reasons, notify)
    result = _verdict(now, session, reasons, checks)
    _write_status(verdict_path, result)
    return result


# Run one check and exit red when the verdict is red.
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the intraday board refreshed this candle."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--now")
    parser.add_argument(
        "--max-age-minutes", type=int, default=DEFAULT_MAX_AGE_MINUTES
    )
    parser.add_argument(
        "--repeat-minutes", type=int, default=DEFAULT_REPEAT_MINUTES
    )
    args = parser.parse_args(argv)
    try:
        now = _instant(args.now)
    except ValueError as exc:
        parser.error(str(exc))
    result = check(
        Path(args.root).resolve(),
        now,
        max_age_minutes=args.max_age_minutes,
        repeat_minutes=args.repeat_minutes,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
