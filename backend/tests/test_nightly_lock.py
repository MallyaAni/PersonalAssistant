"""The nightly lock: one run at a time, a dead holder's lock taken over.

What has to hold: a second acquire while the first is held is refused and
says who holds it; release frees it; a lock older than a legitimate run
is taken over; a lock written by another process's pid is not released by
this one.
"""

from datetime import UTC, datetime, timedelta

from backend.market import nightly_lock


def test_second_acquire_is_refused_until_release(tmp_path, capsys):
    first = nightly_lock.acquire(tmp_path)
    assert first is not None
    assert nightly_lock.acquire(tmp_path) is None
    out = capsys.readouterr().out
    assert "another run holds" in out
    assert str(first.pid) in out
    nightly_lock.release(first)
    assert nightly_lock.acquire(tmp_path) is not None


def test_a_lock_older_than_a_run_is_taken_over(tmp_path, capsys):
    long_ago = datetime.now(tz=UTC) - timedelta(hours=30)
    (tmp_path / nightly_lock.NAME).write_text(
        f"999999\n{long_ago.isoformat(timespec='seconds')}\n", encoding="utf-8"
    )
    lock = nightly_lock.acquire(tmp_path)
    assert lock is not None
    assert "taking over a stale lock" in capsys.readouterr().out
    assert nightly_lock.read(tmp_path / nightly_lock.NAME).pid == lock.pid


def test_release_leaves_another_processes_lock_alone(tmp_path):
    lock = nightly_lock.acquire(tmp_path)
    (tmp_path / nightly_lock.NAME).write_text(
        f"{lock.pid + 1}\n{datetime.now(tz=UTC).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    nightly_lock.release(lock)
    assert (tmp_path / nightly_lock.NAME).exists()


def test_an_unreadable_lock_file_is_treated_as_stale(tmp_path):
    (tmp_path / nightly_lock.NAME).write_text("garbage", encoding="utf-8")
    assert nightly_lock.acquire(tmp_path) is not None
