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
    load_grants,
    normalize_recipient,
    store_grant,
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


# --- granting a recipient the operator approved in AniOS ----------------------
#
# Approving a subscription in AniOS and listing the number on the Mac were two
# records of one decision, kept by hand, and they drifted: a subscriber was
# approved, her digest was built on time, and the bridge refused it at the last
# hop. The grant path exists to make one approval reach both.


def _granting_config(tmp_path: Path, recipients: tuple[str, ...] = ("+15550100",)):
    return BridgeConfig(
        token="secret",
        allowed_recipients=frozenset(normalize_recipient(r) for r in recipients),
        host="127.0.0.1",
        port=8010,
        grants_path=tmp_path / "granted.json",
    )


def test_granting_is_refused_unless_the_operator_turned_it_on():
    # Letting AniOS extend the allowlist is a larger permission than sending to
    # a fixed list, so it is never acquired by simply installing the bridge.
    with pytest.raises(BridgeError, match="does not accept grants"):
        store_grant(_config(), "+15550111")


def test_a_granted_recipient_becomes_sendable(tmp_path):
    config = _granting_config(tmp_path)

    with pytest.raises(BridgeError, match="allowlist"):
        check_recipient(config, "+17032613382")

    assert store_grant(config, "+17032613382") is True
    # No restart between the grant and the send: an approval has to work now,
    # which is exactly what a startup-cached allowlist could not do.
    assert check_recipient(config, "+17032613382") == "+17032613382"


def test_a_grant_is_matched_however_the_number_was_written(tmp_path):
    config = _granting_config(tmp_path)
    store_grant(config, "+1 (703) 261-3382")

    assert check_recipient(config, "7032613382") == "7032613382"


def test_granting_the_same_person_twice_is_not_an_error(tmp_path):
    config = _granting_config(tmp_path)

    assert store_grant(config, "+17032613382") is True
    assert store_grant(config, "7032613382") is False


def test_someone_already_in_the_environment_list_is_not_regranted(tmp_path):
    config = _granting_config(tmp_path, ("+15550100",))
    assert store_grant(config, "+15550100") is False


def test_the_operators_own_list_survives_a_deleted_grant_file(tmp_path):
    config = _granting_config(tmp_path, ("+15550100",))
    store_grant(config, "+17032613382")
    config.grants_path.unlink()

    # Deleting the file revokes every grant at once and leaves the operator's
    # own choices untouched.
    assert check_recipient(config, "+15550100") == "+15550100"
    with pytest.raises(BridgeError, match="allowlist"):
        check_recipient(config, "+17032613382")


def test_a_corrupt_grant_file_never_widens_the_allowlist(tmp_path):
    config = _granting_config(tmp_path)
    config.grants_path.write_text("{not json", encoding="utf-8")

    assert load_grants(config) == frozenset()
    with pytest.raises(BridgeError, match="allowlist"):
        check_recipient(config, "+17032613382")


@pytest.mark.parametrize(
    "written",
    [
        "+17032613382",
        "17032613382",
        "7032613382",
        "+1 (703) 261-3382",
        "703-261-3382",
        "me@icloud.com",
        "ME@iCloud.com",
    ],
)
def test_the_bridge_and_anios_agree_on_every_way_a_number_is_written(written):
    # These are two programs on two machines that must reach the same answer,
    # and nothing else forces them to. Keeping "+" on this side once made
    # "+1703..." and "703..." different people to the bridge and the same person
    # to AniOS, so an approved recipient was refused at the last hop for writing
    # her number the other way.
    from backend.discovery.addressing import normalize_address

    assert normalize_recipient(written) == normalize_address(written)


def test_the_apple_epoch_survives_a_round_trip():
    from datetime import UTC, datetime

    from server import _apple_epoch, _apple_time

    # The `date` column counts nanoseconds from 2001, not seconds from 1970, and
    # the two differ by 31 years — enough that reading one as the other puts a
    # reaction in 1970 and silently outside every window that looks for it.
    moment = datetime(2026, 8, 11, 0, 45, 26, tzinfo=UTC)

    assert _apple_epoch(_apple_time(moment)) == moment.isoformat()


def test_a_reaction_time_the_database_cannot_supply_is_not_invented():
    from server import _apple_epoch

    # A null or unreadable date records the reaction without a time rather than
    # dropping it: knowing someone liked a find matters more than knowing when.
    assert _apple_epoch(None) is None
    assert _apple_epoch("not a number") is None
