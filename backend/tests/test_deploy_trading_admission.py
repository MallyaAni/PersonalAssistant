"""The real deploy flow must not call stale learned-source approval a green release."""

import os
import shutil
import subprocess

import pytest

from backend.tests.test_deploy_gate_first import (
    IDENTITY,
    SCRIPTS,
    Rig,
    _git,
    _missing_tools,
)

pytestmark = pytest.mark.skipif(
    bool(_missing_tools()), reason=_missing_tools() or "tools present"
)


# Give the throwaway release an installed selector so mandatory admission is exercised.
def installed(rig):
    path = rig.deploy / "data/market/desk/learned-holding/config.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"installed":true}')


# Stale approval stops before checkout, build, selectors or publication markers.
def test_stale_approval_preflight_changes_nothing_even_with_skip_post(tmp_path):
    rig = Rig(tmp_path)
    target = rig.push_backend_change()
    installed(rig)
    result = rig.run(ADMISSION_PREFLIGHT_EXIT="1")
    assert result.returncode != 0
    assert "Candidate trading approval failed" in result.stderr
    assert rig.head() == rig.first
    assert not any(" build " in row for row in rig.log("docker.log"))
    assert (rig.deploy / "data/.deployed-commit").read_text().strip() == rig.first
    assert not any(row.startswith("activate ") for row in rig.log("admission.log"))
    assert "deployed " + target not in result.stdout


# Healthy gateway responses cannot hide failed host or container admission.
@pytest.mark.parametrize(
    "failure",
    [
        {"ADMISSION_HOST_EXIT": "1"},
        {"ADMISSION_CONTAINER_EXIT": "1"},
        {"ADMISSION_CONTAINER_SOURCE": "different-actual-container-source"},
    ],
)
def test_actual_runtime_admission_failure_prevents_success_marker(tmp_path, failure):
    rig = Rig(tmp_path)
    target = rig.push_backend_change()
    installed(rig)
    result = rig.run(**failure)
    assert result.returncode != 0
    assert rig.head() == target
    assert (rig.deploy / "data/.deployed-commit").read_text().strip() == rig.first
    assert "deployed " + target not in result.stdout
    assert not any("market_event_recovery" in row for row in rig.log("docker.log"))


# Bundle activation follows gates and build, before actual runtime admission.
def test_reviewed_bundle_activation_precedes_runtime_admission_and_marker(tmp_path):
    rig = Rig(tmp_path)
    target = rig.push_backend_change()
    installed(rig)
    result = rig.run(
        ANIOS_TRADING_APPROVAL_BUNDLE=str(tmp_path / "operator-reviewed.json"),
        ANIOS_TRADING_APPROVAL_BUNDLE_SHA256="a" * 64,
    )
    assert result.returncode == 0, result.stderr
    actions = [row.split()[0] for row in rig.log("admission.log")]
    assert actions == ["preflight", "activate", "check"]
    order = rig.log("order.log")
    backup = next(i for i, row in enumerate(order) if row.startswith("backup-db.sh"))
    migrate = next(i for i, row in enumerate(order) if "alembic upgrade head" in row)
    activate = order.index("activate")
    restart = next(
        i for i, row in enumerate(order) if i > activate and " up -d backend" in row
    )
    assert backup < migrate < activate < restart < order.index("check")
    admission_step = result.stdout.index("Installed trading source admission")
    assert admission_step < result.stdout.index("deployed " + target)
    assert len(rig.log("gate.log")) == 2
    assert "deployed " + target in result.stdout
    assert (rig.deploy / "data/.deployed-commit").read_text().strip() == target


# A failed gate never even opens the approval activation boundary.
def test_failed_gate_cannot_activate_supplied_reviewed_bundle(tmp_path):
    rig = Rig(tmp_path)
    rig.push_backend_change()
    installed(rig)
    result = rig.run(
        GATE_STUB_EXIT="1",
        ANIOS_TRADING_APPROVAL_BUNDLE="reviewed.json",
        ANIOS_TRADING_APPROVAL_BUNDLE_SHA256="a" * 64,
    )
    assert result.returncode != 0
    assert not rig.log("admission.log")
    assert rig.head() == rig.first


# A failed migration restores old code before any approval selector changes.
def test_migration_failure_does_not_activate_reviewed_approval(tmp_path):
    rig = Rig(tmp_path)
    rig.push_backend_change()
    installed(rig)
    (rig.stubs / "fail_migration").touch()
    result = rig.run(
        ANIOS_TRADING_APPROVAL_BUNDLE="reviewed.json",
        ANIOS_TRADING_APPROVAL_BUNDLE_SHA256="a" * 64,
    )
    assert result.returncode != 0
    assert rig.head() == rig.first
    actions = rig.log("admission.log")
    assert [row.split()[0] for row in actions] == ["preflight"]


# The frontend short path retains the synchronous actual policy admission requirement.
def test_frontend_only_cannot_bypass_stale_approval(tmp_path):
    rig = Rig(tmp_path)
    installed(rig)
    (rig.seed / "frontend").mkdir()
    (rig.seed / "frontend/app.ts").write_text("export const current = true;\n")
    _git(rig.seed, "add", "frontend")
    _git(rig.seed, *IDENTITY, "commit", "-qm", "frontend")
    _git(rig.seed, "push", "-q", "origin", "main")
    result = rig.run(ADMISSION_CONTAINER_EXIT="1")
    assert result.returncode != 0
    assert not rig.log("gate.log")
    assert (rig.deploy / "data/.deployed-commit").read_text().strip() == rig.first


# A candidate script can bootstrap the guard into an older checkout lacking its helper.
def test_first_guarded_upgrade_uses_candidate_script_and_gate_tree_helper(tmp_path):
    rig = Rig(tmp_path)
    installed(rig)
    # Commit an old installed deployer with no admission helper as the starting version.
    for tree in (rig.seed, rig.deploy):
        (tree / "scripts/deploy.sh").write_text("#!/bin/bash\nexit 88\n")
        (tree / "backend/cli/market_release_admission.py").unlink()
    _git(rig.seed, "add", "-A")
    _git(rig.seed, *IDENTITY, "commit", "-qm", "old deployer")
    _git(rig.seed, "push", "-q", "origin", "main")
    _git(
        rig.deploy,
        "checkout",
        "--",
        "scripts/deploy.sh",
        "backend/cli/market_release_admission.py",
    )
    _git(rig.deploy, "pull", "--ff-only", "origin", "main")
    rig.first = rig.head()
    (rig.deploy / "data/.deployed-commit").write_text(rig.first + "\n")
    shutil.copy(SCRIPTS / "deploy.sh", rig.seed / "scripts/deploy.sh")
    shutil.copy(
        SCRIPTS.parent / "backend/cli/market_release_admission.py",
        rig.seed / "backend/cli/market_release_admission.py",
    )
    _git(rig.seed, "add", "-A")
    target = rig.push_backend_change()
    env = {
        **os.environ,
        "PATH": f"{rig.bin}:{os.environ['PATH']}",
        "STUB_DIR": str(rig.stubs),
        "DEPLOY_DIR": str(rig.deploy),
        "ANIOS_DEPLOY_CLOCK": "1700",
        "ANIOS_DEPLOY_TICK_GUARD": "0",
        "ANIOS_DEPLOY_POLL_SECONDS": "1",
        "ANIOS_TRADING_PYTHON": str(rig.bin / "trading-python"),
    }
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "deploy.sh"),
            "--deploy-dir=" + str(rig.deploy),
            "--skip-post",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert rig.head() == target
    preflight = rig.log("admission.log")[0]
    assert "/.gate/" in preflight
    assert "deploy=" + rig.first in preflight


# Neither post mode emits green or runs paid checks after failed admission.
@pytest.mark.parametrize("cheap", [False, True])
def test_post_marks_failed_when_actual_trading_admission_is_red(tmp_path, cheap):
    rig = Rig(tmp_path)
    installed(rig)
    shutil.copy(
        SCRIPTS / "post-deploy-checks.sh", rig.deploy / "scripts/post-deploy-checks.sh"
    )
    env = {
        **os.environ,
        "PATH": f"{rig.bin}:{os.environ['PATH']}",
        "STUB_DIR": str(rig.stubs),
        "DEPLOY_DIR": str(rig.deploy),
        "ANIOS_TRADING_PYTHON": str(rig.bin / "trading-python"),
        "ADMISSION_CONTAINER_EXIT": "1",
    }
    args = ["bash", str(rig.deploy / "scripts/post-deploy-checks.sh")]
    result = subprocess.run(
        args + (["--cheap"] if cheap else []) + [rig.first],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode != 0
    expected = "FAILED (cheap)" if cheap else "FAILED (trading admission)"
    assert expected in (rig.deploy / "data/.post-deploy-status").read_text()
    assert "all green" not in result.stdout
    assert not any("sweep_journeys" in row for row in rig.log("docker.log"))
