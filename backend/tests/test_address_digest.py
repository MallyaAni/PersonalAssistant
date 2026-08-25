"""The contact digest must be keyed, spelling-stable, and actually used.

An unkeyed SHA-256 over the phone-number keyspace is exhaustible offline, so
the digest that carries allowlist lookups is an HMAC. These pin the three
properties the migration relies on - not the old hash, equivalent across the
ways one person writes their own number, moved by the key - and inspect the
four consumer files so nobody can quietly reintroduce the unkeyed path.
"""

import hashlib
from pathlib import Path

from backend.config.settings import settings
from backend.core.phone import matching_key
from backend.discovery.addressing import address_digest, normalize_address
from backend.discovery.types import label_digest


def test_the_digest_is_not_the_unkeyed_hash():
    assert address_digest("2025550143") != label_digest("2025550143")
    assert address_digest("2025550143") != hashlib.sha256(b"2025550143").hexdigest()


def test_spellings_of_one_number_share_a_digest():
    spellings = ["+1 202-555-0143", "(202) 555-0143", "2025550143"]
    digests = {address_digest(normalize_address(item)) for item in spellings}
    assert len(digests) == 1
    # The sign-up path digests matching_key(); it must land in the same place.
    assert address_digest(matching_key("+1 202 555 0143")) in digests


def test_the_digest_moves_with_the_key(monkeypatch):
    before = address_digest("2025550143")
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "another-key-entirely")
    assert address_digest("2025550143") != before


def test_the_digest_still_fits_the_column():
    value = address_digest("2025550143")
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


# Source inspection, like the approval-order test in the sign-up suite: the
# fix is only as good as every call site using it, and a future edit that
# reaches for the old function again must fail here, not in a dump.
def test_no_address_path_still_uses_the_unkeyed_digest():
    backend = Path(__file__).resolve().parents[1]
    for relative in (
        "api/v1/auth.py",
        "api/v1/admin.py",
        "discovery/subscribers.py",
        "workers/imessage_chat.py",
    ):
        source = (backend / relative).read_text()
        assert "label_digest(matching_key" not in source, relative
        assert "label_digest(normalize_address" not in source, relative
        assert "label_digest(normalized" not in source, relative
