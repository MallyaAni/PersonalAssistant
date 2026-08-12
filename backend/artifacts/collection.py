"""Reclaiming stored bytes that no row points at any more.

Every artifact write goes through one store, which returns an opaque key that is
recorded in a `storage_key` column. A file under the storage root whose key
appears in no such column is therefore unreachable: nothing can read it, nothing
can delete it through the ordinary path, and it will sit there for the life of
the disk. On this machine that was 460 MB of 556 MB — mostly rendered decks
whose rows are long gone.

This is deliberately the most conservative thing in the codebase, because it is
the only thing here that deletes a user's bytes on its own initiative.

Three guards, each for a distinct way this could destroy data:

- **The reference set must be complete.** It is gathered from every column that
  can hold a key, and if gathering fails the collection refuses rather than
  treating "no references found" as "nothing is referenced". A caller pointed at
  an empty database would otherwise delete everything.
- **Young files are never touched.** A render writes bytes before its row is
  committed, so a file created seconds ago may belong to a job still running.
  Anything newer than the grace period is left for the next sweep.
- **It reports before it deletes.** The default is to plan and return the plan.
  Deleting requires asking for it explicitly.
"""

import logging
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any

logger = logging.getLogger(__name__)

# How recently a file may have been written and still be considered live.
#
# A presentation render writes its bytes and then records the row; between those
# two moments the file is unreferenced and entirely legitimate. An hour is far
# longer than that gap and costs only a delayed sweep.
DEFAULT_GRACE_SECONDS = 3600

# Where storage keys live. Every column that can point at a file belongs here,
# and adding a table that stores one without adding it here would make this
# delete that table's files.
KEY_SOURCES: tuple[tuple[str, str], ...] = (
    ("visual_artifacts", "storage_key"),
    ("presentation_revisions", "storage_key"),
)


class IncompleteReferencesError(RuntimeError):
    """Signals that the set of referenced keys could not be trusted."""


@dataclass(frozen=True, slots=True)
class Plan:
    """What a sweep would remove, and what it deliberately left alone."""

    orphans: tuple[tuple[str, int], ...] = field(default=())
    kept_young: int = 0
    referenced_files: int = 0
    referenced_bytes: int = 0

    @property
    def reclaimable_bytes(self) -> int:
        return sum(size for _, size in self.orphans)


# Gather every key any row still points at.
#
# Raises rather than returning a partial set: a half-read reference set is
# indistinguishable from a disk full of garbage, and the two have opposite
# correct responses.
async def referenced_keys(session: Any) -> set[str]:
    from sqlalchemy import text

    keys: set[str] = set()
    for table, column in KEY_SOURCES:
        try:
            result = await session.execute(
                text(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
            )
        except Exception as exc:
            raise IncompleteReferencesError(
                f"Could not read {table}.{column}; refusing to collect"
            ) from exc
        keys.update(str(key) for (key,) in result.all() if key)
    return keys


# The key a file under the root would have been stored as.
#
# Keys are written with forward slashes whatever the platform, so a Windows path
# has to be normalized or every file looks unreferenced.
def _key_for(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# Decide what is safe to remove, without removing anything.
def plan_collection(
    root: Path,
    referenced: Iterable[str],
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
    now: float | None = None,
) -> Plan:
    live = set(referenced)
    moment = now if now is not None else time()
    orphans: list[tuple[str, int]] = []
    kept_young = 0
    referenced_files = 0
    referenced_bytes = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        key = _key_for(path, root)
        size = path.stat().st_size
        if key in live:
            referenced_files += 1
            referenced_bytes += size
            continue
        if moment - path.stat().st_mtime < grace_seconds:
            # Possibly a job that has written its bytes and not yet its row.
            kept_young += 1
            continue
        orphans.append((key, size))

    return Plan(
        orphans=tuple(orphans),
        kept_young=kept_young,
        referenced_files=referenced_files,
        referenced_bytes=referenced_bytes,
    )


# Carry out a plan, and tidy the directories it empties.
#
# A key is resolved against the root the same way a read is, so a key that
# escaped the root could not be deleted even if one somehow reached here.
def apply_collection(root: Path, plan: Plan) -> tuple[int, int]:
    removed = 0
    reclaimed = 0
    for key, size in plan.orphans:
        candidate = Path(key)
        if candidate.is_absolute() or ".." in candidate.parts:
            logger.warning("Refusing to collect an unsafe key: %s", key)
            continue
        path = (root / candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            logger.warning("Refusing to collect a key outside the root: %s", key)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove %s", key, exc_info=True)
            continue
        removed += 1
        reclaimed += size

    for directory in sorted(root.rglob("*"), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            # Racing with a write that just recreated it is fine; the next
            # sweep tidies whatever is still empty then.
            with suppress(OSError):
                directory.rmdir()
    return removed, reclaimed
