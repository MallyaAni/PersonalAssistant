"""A setting that names a limit has to actually reach the code that applies it.

This is the defect class this repository keeps producing, not an instance of
it. Three times in one day a number appeared to be configurable and was not:
search results clipped by a constant while `SEARCH_MAX_CONTENT_CHARS` said
otherwise, a payload bound that ignored the setting named after it, and
`SEARCH_RESULT_CHARS`/`SEARCH_PAYLOAD_CHARS` defined in settings, listed in
`inherit_env`, asserted in a test, and set by nothing - so the subprocess used
its own defaults and editing the setting changed nothing at all.

The existing test asked whether the name appeared in `inherit_env`. It passed
the whole time the wiring was broken, because appearing in `inherit_env` only
means "pass this through if you have it" - and nothing had it.

An MCP server runs as a subprocess whose entire environment is what
`inherit_env` names and what the parent actually holds. So both halves have to
be true, and this checks both by reading the source rather than by listing
names a person has to remember to update.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SERVERS = _ROOT / "backend" / "mcp" / "servers"

# Read from the process environment on purpose and supplied by other means:
# secrets come from `.env`, and a path has a working default.
_NOT_A_TUNABLE = {
    "SEARCH_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "SEARCH_BASE_URL",
    "GOOGLE_SEARCH_QUOTA_DB_PATH",
}


def _env_names_read_by(module: Path) -> set[str]:
    """Every environment variable the module reads, taken from its source."""
    source = module.read_text(encoding="utf-8")
    return set(re.findall(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']", source))


def _compose() -> str:
    return (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def _env_file() -> str:
    path = _ROOT / ".env"
    if not path.exists():  # pragma: no cover - depends on the checkout
        pytest.skip("no .env in this checkout")
    return path.read_text(encoding="utf-8")


def _server_modules() -> list[Path]:
    return [
        path for path in sorted(_SERVERS.glob("*.py")) if path.name != "__init__.py"
    ]


def test_there_are_server_modules_to_check():
    # If this file is ever moved, the checks below would pass vacuously.
    assert _server_modules(), "found no MCP server modules to check"


# Half one: the subprocess can only see what `inherit_env` forwards.
@pytest.mark.parametrize("module", _server_modules(), ids=lambda p: p.name)
def test_every_variable_a_server_reads_is_forwarded_to_it(module: Path):
    declared = _env_file()
    if "inherit_env" not in declared:  # pragma: no cover
        pytest.skip("MCP servers are not configured here")

    missing = [
        name
        for name in sorted(_env_names_read_by(module))
        if f'"{name}"' not in declared
    ]

    assert not missing, (
        f"{module.name} reads {missing} but they are not in inherit_env, "
        "so the subprocess sees its own defaults instead"
    )


# Half two, and the one the previous test could not see: forwarding a variable
# the parent does not hold forwards nothing.
@pytest.mark.parametrize("module", _server_modules(), ids=lambda p: p.name)
def test_every_tunable_a_server_reads_is_actually_set(module: Path):
    compose = _compose()
    declared = _env_file()

    unset = [
        name
        for name in sorted(_env_names_read_by(module))
        if name not in _NOT_A_TUNABLE
        and f"{name}=" not in compose
        and not re.search(rf"^{name}=", declared, re.MULTILINE)
    ]

    assert not unset, (
        f"{module.name} reads {unset}, which are forwarded but never set, so "
        "the subprocess falls back to its own defaults and the setting is "
        "decorative. Set them in docker-compose.yml."
    )


# A setting whose value the application also owns must agree with the value the
# subprocess would otherwise default to, or the same limit means two things
# depending on which side of the process boundary you read it from.
def test_the_declared_default_matches_what_the_server_falls_back_to():
    from backend.config.settings import settings

    source = (_SERVERS / "internet.py").read_text(encoding="utf-8")
    for name in ("SEARCH_RESULT_CHARS", "SEARCH_PAYLOAD_CHARS"):
        found = re.search(
            rf"os\.getenv\(\s*[\"']{name}[\"']\s*,\s*[\"'](\d+)[\"']", source
        )
        assert found, f"{name} is no longer read with a literal default"
        assert int(found.group(1)) == getattr(settings, name), (
            f"{name} defaults to {found.group(1)} in the server but "
            f"{getattr(settings, name)} in settings"
        )


# The payload has to stay under the generic bound, or truncation of untrusted
# tool output lands mid-JSON and corrupts a result rather than shortening it.
def test_the_search_payload_stays_under_the_generic_tool_bound():
    from backend.config.settings import settings

    assert settings.SEARCH_PAYLOAD_CHARS < settings.MCP_MAX_RESULT_CHARS
