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


# Settings the backend reads at request time and cannot fall back on. A
# service with an explicit `environment:` list and no `env_file:` receives
# exactly what that list names: a value present only in `.env` on the host
# never reaches the container, and the code silently uses its own default.
# `MARKET_DESK_USER` did that. Its default is "operator", the desk belongs
# to a named account, and every request to the Desk view answered 403 while
# `.env` on the deployment said the right thing all along.
_MUST_REACH_THE_BACKEND = ("MARKET_DESK_USER", "AUTH_LOCAL_USER_ID")


@pytest.mark.parametrize("name", _MUST_REACH_THE_BACKEND)
def test_the_backend_is_handed_the_settings_it_cannot_default(name: str):
    backend = _services().get("backend")
    assert backend, "the compose file has no backend service"
    assert "env_file" not in backend, (
        "the backend takes an explicit environment list; adding env_file here "
        "would change what this test means"
    )
    listed = backend.get("environment") or []
    assert any(str(entry).split("=", 1)[0] == name for entry in listed), (
        f"{name} is not passed to the backend container, so the code falls "
        f"back to its own default no matter what .env on the host says"
    )
