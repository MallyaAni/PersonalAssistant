"""One nightly at a time: a lock file under the store that a second run respects.

On 2026-09-15 the previous night's run was still scoring releases when
the next session's cron would have started another instance on top of
it, both writing the same partitions and both able to place paper orders.
The lock is a file created exclusively; it names the process and the
start time, so a person can see who holds it. A lock left behind by a
process that died is taken over: on POSIX when the process is gone, and
anywhere when the file is older than the longest run a nightly may
legitimately take.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

NAME = "nightly.lock"
STALE_AFTER = timedelta(hours=20)


@dataclass(frozen=True)
class Lock:
    """A held lock: the file and what it says."""

    path: Path
    pid: int
    started: datetime


# Whether the process named in a lock file is still alive; unknowable on
# Windows without extra tooling, so there only the age decides.
def _alive(pid: int) -> bool | None:
    if os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# Read a lock file; None when it cannot be read as one.
def read(path: Path) -> Lock | None:
    """Return the Lock a file describes, or None."""
    try:
        pid_text, started_text = path.read_text(encoding="utf-8").split("\n")[:2]
        return Lock(path, int(pid_text), datetime.fromisoformat(started_text))
    except (OSError, ValueError):
        return None


# A lock is stale when its process is known dead, or when it is older than
# any legitimate run.
def stale(lock: Lock, now: datetime | None = None) -> bool:
    """Return True when the lock's holder cannot still be running."""
    now = now or datetime.now(tz=UTC)
    alive = _alive(lock.pid)
    if alive is False:
        return True
    if alive is True:
        return False  # a running holder is never taken over, however long it runs
    started = lock.started
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return now - started > STALE_AFTER


# Take the lock, or return None with the holder printed.
def acquire(root: Path, now: datetime | None = None) -> Lock | None:
    """Create the lock file exclusively; None when another run holds it."""
    now = now or datetime.now(tz=UTC)
    path = Path(root) / NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            held = read(path)
            if held is not None and not stale(held, now):
                print(
                    f"nightly: another run holds {path} (pid {held.pid}, started "
                    f"{held.started.isoformat(timespec='seconds')}); refusing to start"
                )
                return None
            print(f"nightly: taking over a stale lock at {path}")
            try:
                path.unlink()
            except OSError:
                return None
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n{now.isoformat(timespec='seconds')}\n")
        return Lock(path, os.getpid(), now)
    return None


def release(lock: Lock | None) -> None:
    """Remove the lock file this process created."""
    if lock is None:
        return
    held = read(lock.path)
    if held is not None and held.pid == lock.pid:
        with contextlib.suppress(OSError):
            lock.path.unlink()
