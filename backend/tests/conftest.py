import os

# Pytest creates several event loops, so async database uses get fresh connections.
os.environ.setdefault("DATABASE_USE_NULL_POOL", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("POSTGRES_HOST", "localhost")


import pytest


# Tests run against the developer's own `.env`, and this repository's sets
# AUTH_REQUIRED=true for the deployed stack. pydantic-settings reads that file,
# so any test exercising a protected route through TestClient got 401 on a
# machine with a real `.env` and passed on one without - which is how two
# artifact tests failed intermittently for reasons that had nothing to do with
# artifacts. The suite pins the flag off; the tests that are *about*
# authentication set it back to True themselves, and that assignment still wins
# inside the test.
@pytest.fixture(autouse=True)
def auth_disabled_unless_a_test_says_otherwise():
    from backend.config.settings import settings

    original = settings.AUTH_REQUIRED
    settings.AUTH_REQUIRED = False
    yield
    settings.AUTH_REQUIRED = original
