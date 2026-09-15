"""One nightly at a time: an operating-system lock held for the whole run.

On 2026-09-15 the previous night's run was still scoring releases when
the next session's cron would have started another instance on top of
it, both writing the same partitions and both able to place paper orders.
The first version of this lock created the file exclusively and then
wrote its contents; between those two steps a second process could read
an empty file, call it stale and delete it, and both would run. Codex
reproduced that takeover the same day.

Now the lock is the operating system's: the file is opened without
exclusivity and an advisory lock is taken on it (`flock` on POSIX,
`msvcrt.locking` on Windows) and held, with the descriptor open, until
the process releases it or dies. A dead holder's lock vanishes with it,
so there is no staleness rule to get wrong. The file's contents, the pid
and start time, are only for a person reading it.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

NAME = "nightly.lock"

if os.name == "posix":
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)

else:  # Windows
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@dataclass(frozen=True)
class Lock:
    """A held lock: the file, the open descriptor and what the file says."""

    path: Path
    fd: int
    pid: int
    started: datetime


# Read a lock file's note; None when it cannot be read as one. Informational
# only: whether the lock is held is the operating system's answer.
def read(path: Path) -> tuple[int, datetime] | None:
    """Return (pid, started) from a lock file, or None."""
    try:
        pid_text, started_text = path.read_text(encoding="utf-8").split("\n")[:2]
        return int(pid_text), datetime.fromisoformat(started_text)
    except (OSError, ValueError):
        return None


# Take the lock, or return None with the holder's note printed.
def acquire(root: Path, now: datetime | None = None) -> Lock | None:
    """Hold an OS lock on the lock file; None when another process holds it."""
    now = now or datetime.now(tz=UTC)
    path = Path(root) / NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    # The Windows byte-range lock needs a byte to cover; give the file one
    # before locking so an empty file locks the same way as a written one.
    if os.fstat(fd).st_size == 0:
        # Another process may already hold the byte; then the write fails
        # and the lock attempt below reports the refusal.
        with contextlib.suppress(OSError):
            os.write(fd, b"\n")
    if not _try_lock(fd):
        os.close(fd)
        held = read(path)
        who = (
            f"pid {held[0]}, started {held[1].isoformat(timespec='seconds')}"
            if held
            else "holder unknown"
        )
        print(f"nightly: another run holds {path} ({who}); refusing to start")
        return None
    note = f"{os.getpid()}\n{now.isoformat(timespec='seconds')}\n".encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, note)
    os.fsync(fd)
    return Lock(path, fd, os.getpid(), now)


def release(lock: Lock | None) -> None:
    """Release the OS lock and close the descriptor; the file stays for the note."""
    if lock is None:
        return
    _unlock(lock.fd)
    with contextlib.suppress(OSError):
        os.close(lock.fd)
