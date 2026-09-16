"""Optional report files beside the records: written atomically, never fatal.

The nightly writes several evidence blocks after paper trading and before
the record: the FOMC gate, execution quality, the reversal shadows. On
2026-09-15 Codex showed that a failed write of one of them escaped its
guard and would have left orders placed with no record saved. Every such
write now goes through here: the block is serialised to a temporary file
in the same directory and renamed into place, so a reader never sees a
half-written file, and any failure is reported and swallowed, because a
report is evidence and never a reason to lose the record.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


# Write `block` to `target` atomically; return True, or False having said why.
def write_json(target: Path, block: dict, label: str) -> bool:
    """Serialise and rename into place; never raise."""
    try:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(block, handle, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return True
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\n{label}: not written ({type(exc).__name__}: {exc})")
        return False


# Read a block written by write_json; None when missing, torn or unreadable.
def read_json(target: Path) -> dict | None:
    """Return the block, or None."""
    target = Path(target)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
