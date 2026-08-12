"""The only thing here that deletes a user's bytes on its own initiative.

So the tests are mostly about what it refuses to do. Each one corresponds to a
distinct way this could destroy something irreplaceable: a reference it could
not read, a file written seconds before its row, a key pointing outside the
root it was given.
"""

from pathlib import Path

import pytest

from backend.artifacts.collection import (
    IncompleteReferencesError,
    Plan,
    apply_collection,
    plan_collection,
    referenced_keys,
)

_NOW = 1_800_000_000.0
_OLD = _NOW - 86_400


def _file(root: Path, key: str, size: int = 10, mtime: float = _OLD) -> Path:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_a_referenced_file_is_never_planned_for_removal(tmp_path: Path) -> None:
    _file(tmp_path, "user/keep.png")
    _file(tmp_path, "user/drop.png")

    plan = plan_collection(tmp_path, {"user/keep.png"}, now=_NOW)

    assert [key for key, _ in plan.orphans] == ["user/drop.png"]
    assert plan.referenced_files == 1


# A render writes its bytes before it records the row. Between those moments the
# file is unreferenced and completely legitimate.
def test_a_file_written_moments_ago_is_left_alone(tmp_path: Path) -> None:
    _file(tmp_path, "user/in-flight.pptx", mtime=_NOW - 30)

    plan = plan_collection(tmp_path, set(), grace_seconds=3600, now=_NOW)

    assert plan.orphans == ()
    assert plan.kept_young == 1


def test_sizes_are_measured_so_a_sweep_can_be_judged_before_it_runs(
    tmp_path: Path,
) -> None:
    _file(tmp_path, "user/a.png", size=100)
    _file(tmp_path, "user/b.png", size=250)
    _file(tmp_path, "user/kept.png", size=7)

    plan = plan_collection(tmp_path, {"user/kept.png"}, now=_NOW)

    assert plan.reclaimable_bytes == 350
    assert plan.referenced_bytes == 7


# Planning is not deleting. Everything is still there afterwards.
def test_planning_removes_nothing(tmp_path: Path) -> None:
    _file(tmp_path, "user/a.png")
    plan_collection(tmp_path, set(), now=_NOW)
    assert (tmp_path / "user/a.png").exists()


def test_applying_removes_only_what_was_planned(tmp_path: Path) -> None:
    _file(tmp_path, "user/keep.png")
    _file(tmp_path, "user/drop.png", size=40)

    plan = plan_collection(tmp_path, {"user/keep.png"}, now=_NOW)
    removed, reclaimed = apply_collection(tmp_path, plan)

    assert (removed, reclaimed) == (1, 40)
    assert (tmp_path / "user/keep.png").exists()
    assert not (tmp_path / "user/drop.png").exists()


def test_a_directory_left_empty_is_tidied_away(tmp_path: Path) -> None:
    _file(tmp_path, "lonely/only.png")

    apply_collection(tmp_path, plan_collection(tmp_path, set(), now=_NOW))

    assert not (tmp_path / "lonely").exists()


# A key that escaped its root could not delete anything outside it, the same
# rule a read is subject to.
def test_a_key_pointing_outside_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "precious.png"
    outside.write_bytes(b"do not touch")

    removed, _ = apply_collection(root, Plan(orphans=(("../precious.png", 12),)))

    assert removed == 0
    assert outside.exists()


def test_an_absolute_key_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "precious.png"
    outside.write_bytes(b"do not touch")

    removed, _ = apply_collection(tmp_path / "artifacts", Plan(
        orphans=((str(outside), 12),)
    ))

    assert removed == 0
    assert outside.exists()


class FailingSession:
    async def execute(self, *_: object) -> object:
        raise RuntimeError("connection lost")


# The catastrophic case. An unreadable table means an incomplete reference set,
# which is indistinguishable from a disk full of garbage — and the two have
# opposite correct responses. It must refuse rather than guess.
@pytest.mark.asyncio
async def test_unreadable_references_refuse_to_produce_a_set() -> None:
    with pytest.raises(IncompleteReferencesError):
        await referenced_keys(FailingSession())
