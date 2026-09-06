"""No shipped module may use a name it never defined or imported.

On 2026-09-06 a hand-off branch called `status_of` without importing it. The
branch runs only when a turn's wall clock runs out with steps taken, no unit
test executed that path, and the test that covered it read the function's
source text rather than running it. So the unit suite passed, the deploy gate
passed, and every such turn failed live for ten hours with a NameError the
person saw as "I hit a problem answering that."

A checker finds this in a second and does not care how rare the branch is.
Ruff's F821 is already configured for this project (`pyproject.toml`); this
puts it in the gate, where a green suite means the code at least resolves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_module_uses_an_undefined_name():
    found = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821", "--output-format", "concise", "backend", "scripts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # Ruff missing is not a licence to ship undefined names, and it must not
    # read as "no undefined names found" either: it is installed in the test
    # image for this check (Dockerfile, test stage) and is a dev dependency.
    if "No module named ruff" in found.stderr or "No module named" in found.stderr:
        raise AssertionError(
            "ruff is not installed here, so undefined names went unchecked. "
            "It is a dev dependency (pyproject.toml) and is installed in the "
            f"Dockerfile's test stage.\n{found.stderr.strip()[:300]}"
        )
    if found.returncode not in (0, 1):
        raise AssertionError(f"could not run ruff: exit {found.returncode}\n{found.stderr.strip()[:400]}")
    assert found.returncode == 0, f"undefined names:\n{found.stdout.strip()[:2000]}"
