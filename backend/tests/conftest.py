import os
from pathlib import Path

# Set before anything imports backend.config.settings, which builds its
# singleton at import time. This makes Settings skip the repository's `.env`,
# so a test run sees the declared defaults plus whatever a test sets itself.
# Without it the developer's own deployment config decides test outcomes: this
# repository's `.env` sets AUTH_REQUIRED=true, which made every test touching a
# protected route fail on a real workstation and pass on a clean checkout.
os.environ["ANIOS_TEST_MODE"] = "1"

# Pytest creates several event loops, so async database uses get fresh connections.
os.environ.setdefault("DATABASE_USE_NULL_POOL", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")


# The one thing still taken from `.env`, and only this one.
#
# Ignoring the file wholesale is right for behavioural flags: a developer's
# AUTH_REQUIRED must not decide whether a test passes. It is wrong for the
# encryption key, because several tests read tables in the shared development
# database that already hold rows sealed with the deployed key - listing
# invitations returns every invitation, not only the ones the test created -
# and no substitute key can decrypt those. Passing it through keeps that
# dependency explicit and narrow instead of pulling in the whole file.
def _inherit_encryption_key() -> None:
    if os.environ.get("ENCRYPTION_KEY"):
        return
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "ENCRYPTION_KEY" and value.strip():
            os.environ["ENCRYPTION_KEY"] = value.strip()
            return


_inherit_encryption_key()
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("POSTGRES_HOST", "localhost")
