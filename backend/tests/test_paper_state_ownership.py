"""Atomic native saves must retain the account owner's private read access.

These cases require an isolated Linux process running as root. They create only
fresh synthetic roots under the temporary directory; no deployed account is read
or repaired. A real UID/GID 1000 child creates or reopens the native state.
"""

import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

import pytest

from backend.agents.trading.desk import paper

ACCOUNT_UID = 1000
ACCOUNT_GID = 1000
REPOSITORY = Path(paper.__file__).resolve().parents[4]
CHILD_PROGRAM = """
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from backend.agents.trading.desk import paper
root = Path(sys.argv[2])
try:
    if sys.argv[3] == "create":
        state = paper.PaperState(
            sessions_seen=["2026-10-19"],
            history=[{"session": "2026-10-19", "label": "synthetic café", "opaque": float("nan")}],
        )
        paper.save_state(root, state)
    elif sys.argv[3] in ("mode600", "mode640"):
        paper.state_path(root).chmod({"mode600": 0o600, "mode640": 0o640}[sys.argv[3]])
    state = paper.load_state(root)
    print(json.dumps({"ok": True, "sessions_seen": state.sessions_seen}))
except Exception as error:
    print(json.dumps({"ok": False, "error": type(error).__name__, "errno": getattr(error, "errno", None)}))
"""


# Give real root and UID 1000 processes a fresh, traversable synthetic account.
@pytest.fixture
def owned_account():
    if sys.platform != "linux" or os.geteuid() != 0:
        pytest.skip("Real ownership transitions require an isolated Linux root fixture")
    with tempfile.TemporaryDirectory(prefix="paper-owner-regression-") as folder:
        container = Path(folder)
        container.chmod(0o755)
        root = container / "market"
        root.mkdir(mode=0o750)
        os.chown(root, ACCOUNT_UID, ACCOUNT_GID)
        directory = root / paper.PAPER_KIND
        directory.mkdir(mode=0o775)
        directory.chmod(0o775)
        os.chown(directory, ACCOUNT_UID, ACCOUNT_GID)
        yield root


# Create, read or set explicit private modes as the actual synthetic file owner.
def account_process(root, operation):
    assert operation in {"create", "read", "mode600", "mode640"}
    result = subprocess.run(
        [sys.executable, "-I", "-c", CHILD_PROGRAM, str(REPOSITORY), str(root), operation],
        cwd=REPOSITORY,
        user=ACCOUNT_UID,
        group=ACCOUNT_GID,
        extra_groups=[],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr, result.stderr
    assert len(result.stdout.encode()) < 4096
    return json.loads(result.stdout)


# Compute the unchanged native encoder's exact indented, non-normalized bytes.
def native_bytes(state):
    return json.dumps(state, indent=2, default=paper._state_json).encode("utf-8")


# Retain only the original file identity and access metadata needed by these cases.
def file_identity(path):
    value = path.stat()
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
    )


# A root rewrite must remain readable by the original owner without widening access.
@pytest.mark.parametrize("mode", [0o600, 0o640])
def test_root_save_preserves_existing_owner_mode_and_native_bytes(owned_account, mode):
    root = owned_account
    assert account_process(root, "create") == {
        "ok": True,
        "sessions_seen": ["2026-10-19"],
    }
    path = paper.state_path(root)
    assert account_process(root, {0o600: "mode600", 0o640: "mode640"}[mode])["ok"] is True
    original_inode = path.stat().st_ino
    state = paper.load_state(root)
    state.sessions_seen.append("2026-10-20")
    state.history.append({"session": "2026-10-20", "label": "synthetic 東京", "opaque": float("nan")})
    expected = native_bytes(state)
    assert b"NaN" in expected and b"\\u6771" in expected and not expected.endswith(b"\n")

    assert paper.save_state(root, state) == path

    # The old writer fails here with a real PermissionError after publishing root:0600.
    assert account_process(root, "read") == {
        "ok": True,
        "sessions_seen": ["2026-10-19", "2026-10-20"],
    }
    observed = path.stat()
    assert (observed.st_uid, observed.st_gid, stat.S_IMODE(observed.st_mode)) == (
        ACCOUNT_UID, ACCOUNT_GID, mode,
    )
    assert observed.st_ino != original_inode
    assert path.read_bytes() == expected
    assert native_bytes(state) == expected
    assert native_bytes(paper.load_state(root)) == expected
    assert {item.name for item in path.parent.iterdir()} == {"state.json"}


# Root birth inherits the account directory owner and keeps the new state private.
def test_root_birth_uses_account_directory_owner_with_private_mode(owned_account):
    root = owned_account
    path = paper.state_path(root)
    assert not path.exists()
    state = paper.PaperState(
        sessions_seen=["2026-10-19"],
        history=[{"session": "2026-10-19", "label": "synthetic café", "opaque": float("nan")}],
    )
    expected = native_bytes(state)

    assert paper.save_state(root, state) == path

    assert account_process(root, "read") == {
        "ok": True,
        "sessions_seen": ["2026-10-19"],
    }
    observed = path.stat()
    assert (observed.st_uid, observed.st_gid, stat.S_IMODE(observed.st_mode)) == (
        ACCOUNT_UID, ACCOUNT_GID, 0o600,
    )
    assert path.read_bytes() == expected
    assert native_bytes(state) == expected
    assert native_bytes(paper.load_state(root)) == expected
    assert {item.name for item in path.parent.iterdir()} == {"state.json"}


# A pre-replace encoding failure cannot alter or strand the original owner's file.
def test_failed_root_serialization_preserves_original_file_and_access(owned_account):
    root = owned_account
    assert account_process(root, "create")["ok"] is True
    path = paper.state_path(root)
    assert account_process(root, "mode640")["ok"] is True
    before_identity = file_identity(path)
    before_bytes = path.read_bytes()
    invalid = paper.PaperState(history=[{"unserializable": object()}])

    with pytest.raises(TypeError, match="not JSON serializable"):
        paper.save_state(root, invalid)

    assert file_identity(path) == before_identity
    assert path.read_bytes() == before_bytes
    assert account_process(root, "read") == {
        "ok": True,
        "sessions_seen": ["2026-10-19"],
    }
    assert {item.name for item in path.parent.iterdir()} == {"state.json"}


# Refused ownership preparation must fail before replacement of the readable original.
def test_failed_temporary_ownership_preserves_original_file(owned_account, monkeypatch):
    root = owned_account
    assert account_process(root, "create")["ok"] is True
    path = paper.state_path(root)
    before_identity = file_identity(path)
    before_bytes = path.read_bytes()
    state = paper.load_state(root)
    state.sessions_seen.append("2026-10-20")
    expected_input = native_bytes(state)
    attempts = []

    # Simulate an allocator refusing metadata on the newly allocated temporary inode.
    def refuse_ownership(*args, **kwargs):
        attempts.append((args, kwargs))
        raise PermissionError(errno.EPERM, "synthetic temporary ownership refusal")

    with monkeypatch.context() as patch:
        patch.setattr(paper.os, "fchown", refuse_ownership)
        patch.setattr(paper.os, "chown", refuse_ownership)
        with pytest.raises(PermissionError, match="synthetic temporary ownership refusal"):
            paper.save_state(root, state)

    assert len(attempts) == 1
    assert file_identity(path) == before_identity
    assert path.read_bytes() == before_bytes
    assert native_bytes(state) == expected_input
    assert account_process(root, "read") == {
        "ok": True,
        "sessions_seen": ["2026-10-19"],
    }
    assert {item.name for item in path.parent.iterdir()} == {"state.json"}
