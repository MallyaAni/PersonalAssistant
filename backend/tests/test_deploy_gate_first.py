"""deploy.sh gates a commit before it touches anything the desk runs.

The cron jobs (the market balancer every 15 minutes, the 19:30 ET nightly)
run Python straight from the deploy checkout. deploy.sh used to pull into it
and build `:latest` before gating, so on 2026-10-02 a failed gate left cron,
the Vite dev server and the `:latest` images on the failed 0dfdcd89 while the
containers ran 8be5ecbe. These tests run the real script against a throwaway
git repository with stand-ins for the gate, docker, curl and pgrep, and hold
it to the new order: a failing gate leaves the checkout and the image tags
alone; a passing gate moves both; a second deploy is refused by the lock;
the checkout waits for a running balancer; the nightly window is refused;
a failure after the checkout moved is rolled back; --restore and --dry-run
do what they say.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


# Why the script cannot be exercised on this host, or "" when it can.
def _missing_tools() -> str:
    for tool in ("bash", "git", "flock"):
        if shutil.which(tool) is None:
            return f"{tool} is not on this host"
    probe = subprocess.run(
        ["bash", "-c", "declare -A x=(); echo ok"], capture_output=True, text=True
    )
    return "" if probe.returncode == 0 else "bash on this host cannot run the script"


pytestmark = pytest.mark.skipif(
    bool(_missing_tools()), reason=_missing_tools() or "tools present"
)

GATE_STUB = """#!/usr/bin/env bash
# Test stand-in for the gate: records where and how it ran, then passes or
# fails on request.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file=no; [[ -e "$here/.env" ]] && env_file=yes
echo "gate ${1:-routing} root=$here db=${ANIOS_GATE_DB:-} project=${COMPOSE_PROJECT_NAME:-} skip_infra=${ANIOS_GATE_SKIP_INFRA:-} deploy_head=$(git -C "$DEPLOY_DIR" rev-parse --short HEAD) env=$env_file" >> "$STUB_DIR/gate.log"
exit "${GATE_STUB_EXIT:-0}"
"""

DOCKER_STUB = r"""#!/usr/bin/env bash
# Test stand-in for docker: logs every call and keeps image tags as files.
echo "docker $*" >> "$STUB_DIR/docker.log"
images="$STUB_DIR/images"; mkdir -p "$images"
# The file that holds one image reference's id.
key() { local ref="$1" repo tag; if [[ "${ref##*/}" == *:* ]]; then repo="${ref%:*}"; tag="${ref##*:}"; else repo="$ref"; tag=latest; fi; echo "$images/${repo//\//_}@$tag"; }
case "$1" in
  compose)
    shift; root=""; rest=()
    while (($#)); do case "$1" in -f) root="$(dirname "$2")"; shift 2 ;; *) rest+=("$1"); shift ;; esac; done
    set -- "${rest[@]}"
    case "$1" in
      config) shift; [[ "${1:-}" == --images ]] && shift; for s in "$@"; do echo "${COMPOSE_PROJECT_NAME}-$s"; done ;;
      build) shift; head="$(git -C "$root" rev-parse --short HEAD)"; for s in "$@"; do echo "built-$head" > "$(key "${COMPOSE_PROJECT_NAME}-$s")"; done ;;
      ps) [[ -f "$STUB_DIR/infra_down" ]] || printf 'db\nredis\n' ;;
      run) [[ -f "$STUB_DIR/fail_migration" ]] && exit 1 ;;
    esac ;;
  image) f="$(key "${@: -1}")"; [[ -f "$f" ]] && cat "$f" || exit 1 ;;
  tag) if [[ -f "$(key "$2")" ]]; then cp "$(key "$2")" "$(key "$3")"; else echo "$2" > "$(key "$3")"; fi ;;
esac
exit 0
"""

PGREP_STUB = """#!/usr/bin/env bash
# Test stand-in for pgrep: a balancer "runs" while the busy file exists.
[[ -f "$STUB_DIR/busy" ]] && { echo 4242; exit 0; }
exit 1
"""

CURL_STUB = """#!/usr/bin/env bash
# Test stand-in for curl: the private route refuses anonymous access.
printf 401
"""

STUB_SCRIPT = """#!/usr/bin/env bash
# Test stand-in for a deploy helper script: records that it ran.
echo "$(basename "$0") $*" >> "$STUB_DIR/scripts.log"
"""


IDENTITY = ("-c", "user.name=Test", "-c", "user.email=test@example.invalid")


# Run a git command in a directory and return its output.
def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


# Write an executable file.
def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class Rig:
    """A bare origin, a seed clone to commit from, a deploy checkout, and stubs."""

    # Build the repositories, the stand-ins and the starting state.
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.seed = tmp / "seed"
        self.deploy = tmp / "deploy" / "anios"
        self.stubs = tmp / "stubs"
        self.bin = tmp / "bin"
        self.stubs.mkdir()
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True
        )
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.seed)], check=True)
        shutil.copy(SCRIPTS / "deploy.sh", self.seed / "deploy.sh.tmp")
        (self.seed / "scripts").mkdir()
        shutil.move(self.seed / "deploy.sh.tmp", self.seed / "scripts" / "deploy.sh")
        _exe(self.seed / "scripts" / "gate.sh", GATE_STUB)
        _exe(self.seed / "scripts" / "backup-db.sh", STUB_SCRIPT)
        _exe(self.seed / "scripts" / "post-deploy-checks.sh", STUB_SCRIPT)
        (self.seed / "docker-compose.yml").write_text("services: {}\n")
        (self.seed / ".gitignore").write_text("data/\n.env\n")
        (self.seed / "backend").mkdir()
        (self.seed / "backend" / "app.py").write_text("VERSION = 1\n")
        _git(self.seed, "add", "-A")
        _git(self.seed, *IDENTITY, "commit", "-qm", "first")
        _git(self.seed, "remote", "add", "origin", str(self.origin))
        _git(self.seed, "push", "-q", "origin", "main")
        self.deploy.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(self.deploy)], check=True
        )
        (self.deploy / "data").mkdir()
        (self.deploy / ".env").write_text("SECRET_KEY=test-only\n")
        self.first = _git(self.deploy, "rev-parse", "--short", "HEAD")
        (self.deploy / "data" / ".deployed-commit").write_text(self.first + "\n")
        _exe(self.bin / "docker", DOCKER_STUB)
        _exe(self.bin / "pgrep", PGREP_STUB)
        _exe(self.bin / "curl", CURL_STUB)
        (self.stubs / "images").mkdir()
        (self.stubs / "images" / "anios-backend@latest").write_text("old-image\n")

    # Push a new backend commit to origin and return its short SHA.
    def push_backend_change(self, version: int = 2) -> str:
        (self.seed / "backend" / "app.py").write_text(f"VERSION = {version}\n")
        _git(self.seed, *IDENTITY, "commit", "-qam", f"version {version}")
        _git(self.seed, "push", "-q", "origin", "main")
        return _git(self.seed, "rev-parse", "--short", "HEAD")

    # Run deploy.sh from the deploy checkout with the stand-ins on PATH.
    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        full_env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STUB_DIR": str(self.stubs),
            "DEPLOY_DIR": str(self.deploy),
            "ANIOS_DEPLOY_CLOCK": "1700",
            "ANIOS_DEPLOY_TICK_GUARD": "0",
            "ANIOS_DEPLOY_POLL_SECONDS": "1",
            **env,
        }
        return subprocess.run(
            ["bash", str(self.deploy / "scripts" / "deploy.sh"), "--skip-post", *args],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=120,
        )

    # The deploy checkout's short HEAD.
    def head(self) -> str:
        return _git(self.deploy, "rev-parse", "--short", "HEAD")

    # The id an image reference points at, or None.
    def image(self, repo: str, tag: str) -> str | None:
        f = self.stubs / "images" / f"{repo}@{tag}"
        return f.read_text().strip() if f.exists() else None

    # A stub log's lines, or [] when it was never written.
    def log(self, name: str) -> list[str]:
        f = self.stubs / name
        return f.read_text().splitlines() if f.exists() else []


# A fresh rig per test, in pytest's temporary directory.
@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


# A failing gate leaves the checkout, the marker and every image tag exactly
# as they were.
def test_a_failing_gate_changes_nothing(rig: Rig):
    target = rig.push_backend_change()
    result = rig.run(GATE_STUB_EXIT="1")
    assert result.returncode != 0
    assert "NOTHING CHANGED" in result.stderr
    assert rig.head() == rig.first
    assert (rig.deploy / "data" / ".deployed-commit").read_text().strip() == rig.first
    assert rig.image("anios-backend", "latest") == "old-image"
    assert rig.image("anios-backend", target) is None
    assert not any(
        " build " in line or " tag " in line or " up " in line
        for line in rig.log("docker.log")
    )
    # The gate ran on the target, in its own worktree, while the checkout stayed put.
    (gate_line,) = rig.log("gate.log")
    assert f"/.gate/{target}" in gate_line and f"deploy_head={rig.first}" in gate_line
    assert not (
        rig.deploy.parent / ".gate" / target
    ).exists(), "the gate worktree is removed"


# A passing gate moves the checkout, builds, tags the SHA and :latest, and
# records the marker.
def test_a_passing_gate_updates_checkout_images_and_marker(rig: Rig):
    target = rig.push_backend_change()
    result = rig.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert rig.head() == target
    assert (rig.deploy / "data" / ".deployed-commit").read_text().strip() == target
    assert rig.image("anios-backend", "latest") == f"built-{target}"
    assert rig.image("anios-backend", target) == f"built-{target}"
    unit, routing = rig.log("gate.log")
    for line in (unit, routing):
        assert f"root={rig.deploy.parent}/.gate/{target}" in line
        assert f"deploy_head={rig.first}" in line, "gated before the checkout moved"
        assert "project=anios" in line and "skip_infra=1" in line and "env=yes" in line
    assert unit.startswith("gate --unit") and "db=anios_gate_deploy" in unit
    assert not (rig.deploy.parent / ".gate" / target).exists()
    assert "backup-db.sh" in "\n".join(rig.log("scripts.log"))


# A second deploy is refused while the lock is held, before it gates or
# touches anything.
def test_the_lock_refuses_a_second_deploy(rig: Rig):
    rig.push_backend_change()
    lock = rig.deploy / "data" / ".deploy.lock"
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        result = rig.run()
    assert result.returncode != 0
    assert (
        "Another deploy holds" in result.stderr and "NOTHING CHANGED" in result.stderr
    )
    assert rig.head() == rig.first
    assert rig.log("gate.log") == []


# The checkout waits for a running balancer, then moves once it has finished.
def test_the_checkout_waits_for_a_running_balancer(rig: Rig):
    target = rig.push_backend_change()
    busy = rig.stubs / "busy"
    busy.write_text("")
    cleared: list[float] = []

    # Let the "balancer" finish a few seconds into the deploy.
    def finish_balancer():
        time.sleep(3)
        cleared.append(time.time())
        busy.unlink()

    threading.Thread(target=finish_balancer, daemon=True).start()
    result = rig.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "waiting for the running market_balancer" in result.stdout
    assert cleared, "the deploy finished before the balancer did"
    assert rig.head() == target


# A balancer that never finishes makes the deploy give up with nothing moved,
# after the gate ran.
def test_a_balancer_that_never_finishes_leaves_everything_alone(rig: Rig):
    target = rig.push_backend_change()
    (rig.stubs / "busy").write_text("")
    result = rig.run(ANIOS_DEPLOY_WAIT_SECONDS="2")
    assert result.returncode != 0
    assert "NOTHING CHANGED" in result.stderr
    assert len(rig.log("gate.log")) == 2
    assert rig.head() == rig.first
    assert rig.image("anios-backend", "latest") == "old-image"
    assert rig.image("anios-backend", target) is None


# Nothing starts between 19:20 and 19:55 ET, while the nightly runs.
def test_the_nightly_window_is_refused(rig: Rig):
    rig.push_backend_change()
    result = rig.run(ANIOS_DEPLOY_CLOCK="1930")
    assert result.returncode != 0
    assert "nightly" in result.stderr and "NOTHING CHANGED" in result.stderr
    assert rig.log("gate.log") == [] and rig.head() == rig.first


# A failure after the checkout moved but before the restart puts the checkout
# and :latest back.
def test_a_failed_migration_rolls_the_checkout_and_latest_back(rig: Rig):
    target = rig.push_backend_change()
    (rig.stubs / "fail_migration").write_text("")
    result = rig.run()
    assert result.returncode != 0
    assert "putting the checkout and :latest back" in result.stderr
    assert rig.head() == rig.first
    assert rig.image("anios-backend", "latest") == "old-image"
    assert (rig.deploy / "data" / ".deployed-commit").read_text().strip() == rig.first
    assert not any(" up -d backend" in line for line in rig.log("docker.log"))
    assert (
        rig.image("anios-backend", target) == f"built-{target}"
    ), "the gated build stays tagged by SHA"


# The startup self-check names both SHAs, and --restore checks the deployed
# commit out again.
def test_self_check_warns_and_restore_returns_to_the_deployed_commit(rig: Rig):
    ahead = rig.push_backend_change()
    _git(rig.deploy, "pull", "-q", "--ff-only")  # the hand pull this replaces
    assert rig.head() == ahead
    result = rig.run("--restore")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "WARNING" in result.stderr
        and ahead in result.stderr
        and rig.first in result.stderr
    )
    assert rig.head() == rig.first
    assert rig.log("gate.log") == [] and rig.log("docker.log") == []
    # Restored onto the branch, so the next deploy fast-forwards as usual.
    assert _git(rig.deploy, "rev-parse", "--abbrev-ref", "HEAD") == "main"


# --dry-run gates for real and then changes nothing.
def test_dry_run_gates_and_changes_nothing(rig: Rig):
    target = rig.push_backend_change()
    result = rig.run("--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dry run: nothing was changed" in result.stdout
    assert len(rig.log("gate.log")) == 2
    assert rig.head() == rig.first
    assert rig.image("anios-backend", target) is None
    assert not any(" build " in line for line in rig.log("docker.log"))


# Edits to tracked files in the checkout cannot be gated, so the deploy refuses them.
def test_uncommitted_tracked_edits_are_refused(rig: Rig):
    rig.push_backend_change()
    (rig.deploy / "backend" / "app.py").write_text("VERSION = 'hand edit'\n")
    result = rig.run()
    assert result.returncode != 0
    assert "uncommitted edits" in result.stderr
    assert rig.log("gate.log") == []


# The unit gate's database is configurable, so two gates need not share one.
def test_gate_sh_takes_its_database_and_infra_from_the_environment():
    gate = (SCRIPTS / "gate.sh").read_text(encoding="utf-8")
    assert 'gate_db="${ANIOS_GATE_DB:-anios_gate}"' in gate
    assert "ANIOS_GATE_SKIP_INFRA" in gate
    compose = (SCRIPTS.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${ANIOS_FUNCTIONAL_TESTS_IMAGE:-anios-functional-tests}" in compose
