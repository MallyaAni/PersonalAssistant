"""The iMessage bridge's own refusals.

The bridge runs on a Mac and only sends there, but everything that decides
*whether* to send is pure and testable anywhere. Those are the parts worth
covering: this is the last hop before a message reaches a real person, and it
must refuse independently of whatever asked it to send.
"""

import base64
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "bridges" / "imessage_mac")
)

from server import (  # noqa: E402
    MAX_ATTACHMENT_BYTES,
    BridgeConfig,
    BridgeError,
    check_recipient,
    decode_attachment,
    normalize_recipient,
)

_CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def _config(recipients: tuple[str, ...] = ("+15550100",)) -> BridgeConfig:
    return BridgeConfig(
        token="secret",
        allowed_recipients=frozenset(normalize_recipient(r) for r in recipients),
        host="127.0.0.1",
        port=8010,
    )


def test_recipients_compare_by_digits_not_formatting():
    # "+1 (555) 010-0" and "+15550100" are one person.
    assert normalize_recipient("+1 (555) 010-0") == normalize_recipient("+15550100")
    assert normalize_recipient("Person@Example.com") == "person@example.com"


def test_a_recipient_off_the_allowlist_is_refused():
    with pytest.raises(BridgeError, match="allowlist"):
        check_recipient(_config(), "+19999999999")


def test_the_refusal_does_not_echo_the_recipient():
    # Otherwise the error becomes a way to probe who is on the list.
    with pytest.raises(BridgeError) as caught:
        check_recipient(_config(), "+19999999999")
    assert "9999999999" not in str(caught.value)


def test_an_allowed_recipient_passes_in_its_original_form():
    assert check_recipient(_config(), " +1 (555) 010-0 ") == "+1 (555) 010-0"


def test_a_blank_recipient_is_refused():
    with pytest.raises(BridgeError, match="required"):
        check_recipient(_config(), "   ")


def test_a_config_without_a_token_refuses_to_start(monkeypatch):
    # An unauthenticated send-as-me endpoint must not be what you get by
    # forgetting to configure one.
    monkeypatch.delenv("IMESSAGE_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    with pytest.raises(BridgeError, match="IMESSAGE_BRIDGE_TOKEN"):
        BridgeConfig.from_environment()


def test_a_config_without_recipients_refuses_to_start(monkeypatch):
    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "secret")
    monkeypatch.delenv("IMESSAGE_BRIDGE_RECIPIENTS", raising=False)
    with pytest.raises(BridgeError, match="RECIPIENTS"):
        BridgeConfig.from_environment()


def test_no_attachment_is_a_valid_send():
    assert decode_attachment(None, None, None) is None


def test_only_calendar_attachments_are_accepted():
    encoded = base64.b64encode(_CALENDAR).decode()
    with pytest.raises(BridgeError, match="Unsupported attachment type"):
        decode_attachment("x.ics", "application/pdf", encoded)


def test_a_path_traversal_filename_is_reduced_to_its_name():
    # The name reaches the filesystem, so it must not be able to escape.
    name, _ = decode_attachment(
        "../../etc/evil.ics", "text/calendar", base64.b64encode(_CALENDAR).decode()
    )
    assert name == "evil.ics"
    assert "/" not in name


def test_a_non_ics_suffix_is_refused():
    with pytest.raises(BridgeError, match="Only .ics"):
        decode_attachment(
            "payload.sh", "text/calendar", base64.b64encode(_CALENDAR).decode()
        )


def test_bytes_that_are_not_a_calendar_are_refused():
    # Cheap proof the content matches the declared type, so this cannot be used
    # to drop an arbitrary file onto the Mac.
    encoded = base64.b64encode(b"#!/bin/sh\nrm -rf /\n").decode()
    with pytest.raises(BridgeError, match="not an iCalendar"):
        decode_attachment("x.ics", "text/calendar", encoded)


def test_invalid_base64_is_refused():
    with pytest.raises(BridgeError, match="base64"):
        decode_attachment("x.ics", "text/calendar", "not base64!!!")


def test_an_oversized_attachment_is_refused():
    huge = base64.b64encode(b"BEGIN:VCALENDAR" + b"x" * MAX_ATTACHMENT_BYTES).decode()
    with pytest.raises(BridgeError, match="too large"):
        decode_attachment("x.ics", "text/calendar", huge)


def test_a_valid_calendar_attachment_decodes():
    name, content = decode_attachment(
        "discoveries.ics", "text/calendar", base64.b64encode(_CALENDAR).decode()
    )
    assert name == "discoveries.ics"
    assert content == _CALENDAR
