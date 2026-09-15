"""The nightly lock: one process at a time, enforced by the operating system.

What has to hold: a second acquire in another process is refused while
the first holds the lock, and succeeds once it is released; the race
that undid the first version (an empty or half-written lock file seen by
a second process) cannot admit two holders, because the file's contents
decide nothing; a holder that dies releases the lock without cleanup;
concurrent starters admit exactly one; the note in the file names the
holder.
"""

import os
import subprocess
import sys
from pathlib import Path

from backend.market import nightly_lock

REPO = Path(__file__).resolve().parents[2]
HOLDER = """
import sys, time
from pathlib import Path
from backend.market import nightly_lock
lock = nightly_lock.acquire(Path(sys.argv[1]))
print("held" if lock else "refused", flush=True)
if lock:
    time.sleep(float(sys.argv[2]))
    nightly_lock.release(lock)
"""


def _holder(root: Path, seconds: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(root), str(seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )


def test_a_second_process_is_refused_while_the_first_holds_the_lock(tmp_path):
    first = _holder(tmp_path, 8.0)
    assert first.stdout.readline().strip() == "held"
    second = _holder(tmp_path, 0.0)
    out, _ = second.communicate(timeout=60)
    assert out.strip().splitlines()[-1] == "refused"
    first.kill()
    first.wait(timeout=30)
    # A dead holder needs no cleanup: the lock went with the process.
    lock = nightly_lock.acquire(tmp_path)
    assert lock is not None
    nightly_lock.release(lock)


def test_an_empty_or_half_written_lock_file_cannot_admit_two_holders(tmp_path):
    # The race Codex reproduced: the file exists but its note is not yet
    # written. Contents decide nothing; only the OS lock does.
    (tmp_path / nightly_lock.NAME).write_text("", encoding="utf-8")
    first = nightly_lock.acquire(tmp_path)
    assert first is not None
    second = _holder(tmp_path, 0.0)
    out, _ = second.communicate(timeout=60)
    assert out.strip().splitlines()[-1] == "refused"
    nightly_lock.release(first)
    third = _holder(tmp_path, 0.0)
    out, _ = third.communicate(timeout=60)
    assert out.strip().splitlines()[-1] == "held"


def test_concurrent_starters_admit_exactly_one(tmp_path):
    procs = [_holder(tmp_path, 4.0) for _ in range(4)]
    outs = [p.communicate(timeout=90)[0].strip().splitlines()[-1] for p in procs]
    assert outs.count("held") == 1, outs
    assert outs.count("refused") == 3, outs


def test_the_note_names_the_holder_and_release_frees_it(tmp_path):
    lock = nightly_lock.acquire(tmp_path)
    assert lock is not None
    nightly_lock.release(lock)
    # The note outlives the lock; on Windows the locked byte cannot be read
    # while held, so it is read after release on every platform.
    pid, started = nightly_lock.read(tmp_path / nightly_lock.NAME)
    assert pid == os.getpid()
    assert started == lock.started.replace(microsecond=0)
    again = nightly_lock.acquire(tmp_path)
    assert again is not None
    nightly_lock.release(again)
