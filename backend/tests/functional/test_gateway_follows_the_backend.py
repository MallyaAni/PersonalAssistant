"""Move the backend, and see whether the gateway still reaches it.

The config check in `test_gateway_config.py` asserts the *spelling* that makes
this work - a variable upstream and a resolver. Spelling is a proxy: its first
version failed by matching the comment that quotes the old directive, which is
exactly how a textual guard drifts away from the thing it stands for.

This asserts the property instead. The backend is forced onto a different
address on the Docker network, with a placeholder parked on the old one so it
genuinely cannot land back where it started, and the gateway is never reloaded.
That is precisely the condition that returned 502 on every API call while a
completely healthy backend ran behind it.
"""

import json
import shutil
import subprocess
import time

import pytest

GATEWAY = "anios_gateway"
BACKEND = "anios_backend"
PLACEHOLDER = "anios_ip_placeholder_test"


def _docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=180
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def _running(name: str) -> bool:
    return bool(_docker("ps", "-q", "-f", f"name=^{name}$", check=False))


def _address() -> str:
    raw = _docker(
        "inspect", "-f", "{{json .NetworkSettings.Networks}}", BACKEND
    )
    return next(iter(json.loads(raw).values()))["IPAddress"]


def _network() -> str:
    raw = _docker(
        "inspect", "-f", "{{json .NetworkSettings.Networks}}", BACKEND
    )
    return next(iter(json.loads(raw)))


def _gateway_answers() -> int:
    # Through the gateway's own published port rather than the public
    # hostname, so this measures the proxy hop and not the tunnel in front of
    # it. 401 is the healthy answer here: the session route is reachable and
    # says "not signed in". A 502 means the proxy could not connect at all.
    out = _docker(
        "exec",
        GATEWAY,
        "sh",
        "-c",
        "wget -q -S -O /dev/null http://127.0.0.1:8080/api/v1/auth/session "
        "2>&1 | grep -m1 HTTP/ || true",
        check=False,
    )
    digits = [part for part in out.split() if part.isdigit()]
    return int(digits[0]) if digits else 0


@pytest.fixture
def _stack_is_up():
    if shutil.which("docker") is None:
        pytest.skip("docker is not available on this host")
    if not (_running(GATEWAY) and _running(BACKEND)):
        pytest.skip("the gateway and backend must both be running")
    yield
    _docker("rm", "-f", PLACEHOLDER, check=False)


def test_the_gateway_follows_the_backend_to_a_new_address(_stack_is_up):
    network = _network()
    before = _address()
    started = _docker("inspect", "-f", "{{.State.StartedAt}}", GATEWAY)

    assert _gateway_answers() != 502, "the gateway was already failing"

    # Park something on the current address so the backend cannot simply be
    # given it back, which is what makes this a real move.
    _docker("stop", BACKEND)
    _docker(
        "run", "-d", "--name", PLACEHOLDER, "--network", network,
        "--ip", before, "alpine", "sleep", "300",
        check=False,
    )
    _docker("start", BACKEND)

    try:
        # A 502 immediately after the move is not the defect: the backend needs
        # a few seconds to bind its port, and until it does the proxy has
        # nothing to reach at either address. The property is that the gateway
        # recovers on its own, so this waits for a non-502 answer rather than
        # for the first answer of any kind - 502 being truthy is what made an
        # earlier version of this loop stop at exactly the wrong moment.
        status = 502
        for _ in range(40):
            time.sleep(2)
            status = _gateway_answers()
            if status and status != 502:
                break

        assert _address() != before, (
            "the backend came back on the same address, so this proved nothing"
        )
        # The gateway must not have been restarted or reloaded by any of this.
        assert _docker("inspect", "-f", "{{.State.StartedAt}}", GATEWAY) == started

        assert status != 502, (
            f"the gateway answered 502 after the backend moved from {before} "
            f"to {_address()}, so it is still caching the old address"
        )
        assert status, "the gateway did not answer at all"
    finally:
        _docker("rm", "-f", PLACEHOLDER, check=False)
