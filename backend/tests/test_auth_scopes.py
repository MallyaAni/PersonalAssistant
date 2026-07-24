import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

import pytest
from fastapi.testclient import TestClient

from backend.config.settings import settings
from backend.core.auth import (
    SCOPE_MEMORY,
    SCOPE_MEMORY_READ,
    SCOPE_MEMORY_WRITE,
    SCOPE_VISION,
    _scope_satisfied,
    issue_user_token,
    verify_user_token,
)
from backend.main import app


def test_an_unrestricted_token_carries_no_scope_claim():
    identity = verify_user_token(issue_user_token("u"))
    assert identity.scopes is None


def test_a_scoped_token_round_trips_its_scopes():
    token = issue_user_token("u", scopes=[SCOPE_MEMORY_READ])
    assert verify_user_token(token).scopes == frozenset({SCOPE_MEMORY_READ})


def test_issuing_an_unknown_scope_is_rejected():
    with pytest.raises(ValueError, match="unknown scopes"):
        issue_user_token("u", scopes=["memory:delete-everything"])


def test_scope_satisfaction_rules():
    # Unrestricted grants everything.
    assert _scope_satisfied(None, SCOPE_MEMORY_WRITE) is True
    # A group scope grants its children.
    assert _scope_satisfied(frozenset({SCOPE_MEMORY}), SCOPE_MEMORY_WRITE) is True
    # A read scope does not grant a write.
    assert _scope_satisfied(frozenset({SCOPE_MEMORY_READ}), SCOPE_MEMORY_WRITE) is False
    # An exact match is enough.
    assert _scope_satisfied(frozenset({SCOPE_MEMORY_READ}), SCOPE_MEMORY_READ) is True


def test_route_enforcement_respects_least_privilege():
    read_token = issue_user_token("scope_user", scopes=[SCOPE_MEMORY_READ])
    vision_token = issue_user_token("scope_user", scopes=[SCOPE_VISION])
    group_token = issue_user_token("scope_user", scopes=[SCOPE_MEMORY])
    full_token = issue_user_token("scope_user")

    settings.AUTH_REQUIRED = True
    try:
        with TestClient(app) as client:

            def get_memory(token: str):
                return client.get(
                    "/api/v1/memory/scope_user",
                    headers={"Authorization": f"Bearer {token}"},
                )

            def delete_memory(token: str):
                return client.delete(
                    "/api/v1/memory/scope_user",
                    headers={"Authorization": f"Bearer {token}"},
                )

            # A read scope reads but cannot delete.
            assert get_memory(read_token).status_code == 200
            assert delete_memory(read_token).status_code == 403
            # A scope for a different subsystem cannot read memory at all.
            assert get_memory(vision_token).status_code == 403
            # A group scope satisfies the read child.
            assert get_memory(group_token).status_code == 200
            # An unrestricted token is unaffected by scope checks.
            assert get_memory(full_token).status_code == 200
    finally:
        settings.AUTH_REQUIRED = False
