"""Operational policy every service must agree on, asserted rather than reviewed.

`local-capabilities` was the only service in the file with no `restart:` key.
Nothing noticed until a host reboot, when every sibling came back and it did
not - the MCP capabilities server was simply absent, and tool calls had nothing
to reach. Reviewing a 900-line compose file by eye does not catch an omission
that looks exactly like the surrounding lines; comparing services to each other
does.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _services() -> dict[str, dict]:
    parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return {
        name: body
        for name, body in (parsed.get("services") or {}).items()
        if isinstance(body, dict)
    }


# The services that are supposed to be running. A profile-gated service is
# opt-in and started by hand for a particular job, so "did it come back after a
# reboot" is not a question about it.
def _always_on() -> dict[str, dict]:
    return {
        name: body for name, body in _services().items() if not body.get("profiles")
    }


def test_the_compose_file_is_parseable_and_has_services():
    services = _services()

    assert len(services) >= 8, sorted(services)


# The defect this file was written for.
@pytest.mark.parametrize("name", sorted(_always_on()))
def test_every_service_survives_a_reboot(name: str):
    body = _always_on()[name]

    policy = body.get("restart")
    assert policy, (
        f"{name} declares no restart policy, so it will not come back after a "
        f"host reboot while every other service does"
    )
    # `no` and `on-failure` both leave a cleanly-stopped container down, which
    # is exactly what a reboot produces.
    assert policy in {"always", "unless-stopped"}, (
        f"{name} uses restart: {policy}, which does not survive a reboot"
    )


# A container name is what every operational command and every one of these
# checks refers to; an unnamed service gets a generated name that changes with
# the project directory.
@pytest.mark.parametrize("name", sorted(_always_on()))
def test_every_service_has_a_stable_container_name(name: str):
    assert _always_on()[name].get("container_name"), name
