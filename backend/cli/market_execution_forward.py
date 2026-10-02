"""Record a frozen paper execution cohort or compare it; never submit an order."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import alpaca_trading, entry_timing, execution_quotes
from backend.market import execution_forward as forward


# Freeze a consistent broker account, paper intents and first received quote packet.
def initialize(root, folder, revision, client=None, reader=None, clock=None):
    root, folder = Path(root).resolve(), Path(folder).resolve()
    if folder.is_relative_to(root) or folder.exists():
        raise ValueError("Use a new research directory outside the production root")
    clock = clock or (lambda: datetime.now(UTC))
    client = client or alpaca_trading.client_from_env()
    before = forward.account(
        client.account().cash, {p.symbol: p.qty for p in client.positions()}
    )
    state_bytes = paper.state_path(root).read_bytes()
    state = json.loads(state_bytes)
    now = clock()
    day = now.astimezone(entry_timing.NEW_YORK).date()
    symbols = {
        r["symbol"] for r in state["pending"] if r.get("execute_on") == day.isoformat()
    }
    symbols |= set(before["holdings"]) | {"SPY", "QQQ"}
    snapshot_bytes = (root / "desk/live.json").read_bytes()
    snapshot = json.loads(snapshot_bytes)
    latch = entry_timing.load(root, day)
    packet = (reader or execution_quotes.fetch)(sorted(symbols))
    after = forward.account(
        client.account().cash, {p.symbol: p.qty for p in client.positions()}
    )
    if before != after or state_bytes != paper.state_path(root).read_bytes():
        raise ValueError(
            "Starting account or plan changed during capture; no cohort created"
        )
    obs = forward.observation(snapshot, latch, packet, clock())
    frozen = forward.manifest(state["pending"], before, obs, revision)
    import hashlib

    frozen["original_source_sha256"] = {
        "paper_state": hashlib.sha256(state_bytes).hexdigest(),
        "live_snapshot": hashlib.sha256(snapshot_bytes).hexdigest(),
    }
    folder.mkdir(mode=0o700, parents=True)
    forward.exclusive(folder / "manifest.json", frozen)
    return frozen


# Run a bounded read-only collection loop and stop at the declared session close.
def record(root, folder, seconds, interval):
    if not 1 <= interval <= 60 or not 0 <= seconds <= 24 * 3600:
        raise ValueError("Bounded duration and 1–60 second interval required")
    frozen = json.loads((folder / "manifest.json").read_text())
    closing = entry_timing.session_clock(
        datetime.fromisoformat(frozen["session"]).date()
    )["close"]
    deadline = time.monotonic() + seconds
    count = 0
    while datetime.now(UTC) < closing:
        forward.collect(root, folder)
        count += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    return {
        "observations_added": count,
        "status": "recorded" if count else "session_closed",
    }


# Expose explicit initialization, bounded recording and exclusive report creation.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("initialize", "record", "compare", "value"))
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--seconds", type=int, default=0)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mode in ("initialize", "record") and not args.data_dir:
        parser.error("--data-dir required for read-only capture")
    if args.mode == "initialize":
        if not args.revision:
            parser.error("--revision required to identify the source")
        result = initialize(args.data_dir, args.folder, args.revision)
        summary = {
            "status": "frozen",
            "opportunities": len(result["opportunities"]),
            "session": result["session"],
        }
    elif args.mode == "record":
        summary = record(args.data_dir, args.folder, args.seconds, args.interval)
    elif args.mode == "value":
        if not args.output or args.output.exists():
            parser.error("--output must name a new report artifact")
        result = valuate(args.folder, args.output)
        summary = {
            "status": "diagnostic",
            "observations": result["proxy"]["observations"],
            "adoption_eligible": False,
        }
    else:
        if not args.output or args.output.exists():
            parser.error("--output must name a new report artifact")
        result = forward.compare(args.folder)
        forward.exclusive(args.output, result)
        summary = {
            "status": "diagnostic",
            "observations": result["observations"],
            "adoption_eligible": False,
        }
    print(json.dumps(summary))
    return 0


# Capture fixed delayed endpoint labels and evaluate the frozen cohort only once.
def valuate(folder, output, *, request=None, headers=None, clock=None):
    from datetime import timedelta

    from backend.market import bounded_execution as bounded
    from backend.market import execution_marks

    clock = clock or (lambda: datetime.now(UTC))
    frozen, observations = forward.load(folder)
    start = bounded.instant(frozen["started_at"])
    closing = entry_timing.session_clock(
        start.astimezone(entry_timing.NEW_YORK).date()
    )["close"]
    end = min(
        bounded.instant(observations[-1]["observed_at"]),
        closing - timedelta(microseconds=1),
    )
    if clock() < end + timedelta(minutes=16):
        raise ValueError("Wait for both delayed SIP endpoint windows")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    evidence = output.with_suffix(".evidence")
    evidence.mkdir(mode=0o700, exist_ok=True)
    symbols = set(frozen["starting"]["holdings"]) | {"SPY", "QQQ"}
    symbols |= {o["order"]["symbol"] for o in frozen["opportunities"]}
    packets = [
        execution_marks.endpoint(
            symbols, at, evidence / label, request=request, headers=headers, clock=clock
        )
        for label, at in (("start", start), ("end", end))
    ]
    proxy = forward.compare(folder)
    result = {
        "proxy": proxy,
        "consolidated": execution_marks.supplement(frozen, proxy, *packets),
    }
    forward.exclusive(output, result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
