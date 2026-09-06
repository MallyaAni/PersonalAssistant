"""The deploy scripts parse, and the deploy does not wait on the live checks.

A shell script has no import to fail, so a typo in one is found by the person
running it, in the middle of a deploy. `bash -n` costs milliseconds and finds
exactly that class. The second property is the 2026-09-06 change: the live
checks verify a system that is already serving, so the deploy writes its
marker and detaches them rather than blocking for forty minutes on checks
that cannot change what is running.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SHELL_SCRIPTS = sorted(SCRIPTS.glob("*.sh"))


def test_there_are_shell_scripts_to_check():
    assert SHELL_SCRIPTS, "no scripts/*.sh found; this test is checking nothing"


# Whether this host has a bash that can actually parse anything. The one on
# a Windows developer's PATH is often a WSL relay stub that fails every call
# with "execvpe(/bin/bash) failed"; believing its verdict would fail every
# script here for a reason that has nothing to do with the scripts. In the
# container the deploy gate runs in, this probe passes and the checks run.
def _usable_bash() -> str:
    if shutil.which("bash") is None:
        return "bash is not on this host"
    probe = subprocess.run(["bash", "-n"], input="echo hi\n", capture_output=True, text=True)
    return "" if probe.returncode == 0 else f"bash on this host cannot parse: {probe.stderr.strip()[:120]}"


_NO_BASH = _usable_bash()


@pytest.mark.skipif(bool(_NO_BASH), reason=_NO_BASH or "bash is usable")
@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_the_script_parses(script: Path):
    # Fed on stdin, not by path: a bash that can parse may still be unable to
    # open `E:\...`.
    checked = subprocess.run(
        ["bash", "-n"],
        input=script.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
    )
    detail = (checked.stderr or checked.stdout).strip()[:800]
    assert checked.returncode == 0, f"{script.name} does not parse:\n{detail}"


def test_the_deploy_detaches_the_live_checks_and_records_their_verdict():
    deploy = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    checks = SCRIPTS / "post-deploy-checks.sh"
    assert checks.is_file(), "the live checks have their own script"
    # The marker is written before the checks start: at that point the system
    # is up, healthy and serving this commit.
    assert deploy.index('step "Result"') < deploy.index('step "Post-deploy checks"')
    # Detached by default, waitable on request, skippable as before.
    assert "setsid nohup bash" in deploy and "post-deploy-checks.sh" in deploy
    assert "--wait-post" in deploy and "--skip-post" in deploy
    # A red check still pages, and leaves a verdict a later session can read.
    body = checks.read_text(encoding="utf-8")
    assert "notify-operator.sh" in body
    assert ".post-deploy-status" in body
    # Both live checks survived the move.
    assert "backend.cli.sweep_journeys" in body
    assert "backend.cli.exercise_search_scenarios" in body
