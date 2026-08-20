"""A test result must not depend on the developer's own deployment config.

Settings are built once at import from `.env`, so whatever that file says has
governed every test run on a machine that has one. Three separate
investigations were spent on failures it caused: two artifact tests that
returned 401 because the file sets AUTH_REQUIRED=true, and one admin test that
passed only because it also sets AUTH_COOKIE_SECURE=true, which made the test
client silently drop a cookie the test had not accounted for. Each looked like
a bug in the feature under test.
"""

import os
from pathlib import Path

from backend.config.settings import Settings, settings

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def test_the_suite_runs_with_the_env_file_switched_off():
    assert os.environ.get("ANIOS_TEST_MODE"), (
        "conftest must set ANIOS_TEST_MODE before backend.config.settings is "
        "imported, or the deployment's .env decides test outcomes"
    )
    assert Settings.model_config.get("env_file") is None


# The two the repository actually sets, named individually: a default that
# silently follows the file again would otherwise only surface as an unrelated
# test failing on one machine.
def test_deployment_flags_take_their_declared_defaults():
    assert settings.AUTH_REQUIRED is False
    assert settings.AUTH_COOKIE_SECURE is False


def test_no_declared_default_is_overridden_by_the_env_file():
    if not ENV_FILE.is_file():
        return

    named = {
        line.partition("=")[0].strip()
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    # ENCRYPTION_KEY is deliberately inherited: several tests read rows in the
    # shared development database that were sealed with the deployed key, and
    # no substitute can decrypt those. Everything else must come from defaults.
    inherited_on_purpose = {"ENCRYPTION_KEY"}
    # Both built fresh, and neither is the process-wide singleton: tests are
    # free to mutate that one, and comparing against it would report another
    # test's unrestored assignment as an `.env` leak. The question here is only
    # whether constructing Settings the way the application does reads the file.
    as_the_app_builds_it = Settings()  # type: ignore[call-arg]
    without_the_file = Settings(_env_file=None)  # type: ignore[call-arg]

    leaked = [
        name
        for name in sorted(named - inherited_on_purpose)
        if name in Settings.model_fields
        and getattr(as_the_app_builds_it, name) != getattr(without_the_file, name)
    ]
    assert not leaked, f"these settings still follow .env during tests: {leaked}"
