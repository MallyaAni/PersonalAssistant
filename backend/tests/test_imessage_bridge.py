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


def test_the_sending_account_can_be_pinned(monkeypatch):
    # With two Apple IDs signed into Messages, "the first iMessage account" is
    # a tie-break deciding which identity this Mac speaks as. The pin makes it
    # an operator decision instead.
    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "secret")
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    monkeypatch.setenv("IMESSAGE_BRIDGE_ACCOUNT_ID", "  ABCD-1234  ")
    assert BridgeConfig.from_environment().account_id == "ABCD-1234"


def test_no_pin_means_the_first_account_still_sends(monkeypatch):
    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "secret")
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    monkeypatch.delenv("IMESSAGE_BRIDGE_ACCOUNT_ID", raising=False)
    assert BridgeConfig.from_environment().account_id == ""


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


# --- reading incoming messages, so allowlisted senders can converse -----------
#
# This is the one capability that returns message bodies, and everything that
# decides *whose* bodies and *which* rows is pure SQL plus set logic against a
# BridgeConfig, so it is covered here against a fixture database with the real
# Messages schema shapes. What cannot be covered off the Mac — whether the
# operator's own texts arrive as incoming rows after the account split, and the
# extractor's coverage on genuine attributedBody blobs — is verified live via
# read_messages and describe_messages_access.

import sqlite3  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402


# A synthetic attributedBody blob in the layout real Macs write: streamtyped
# header, NSAttributedString then the string class chain, the \x01+ type code,
# a one/two/four-byte length, then the UTF-8 payload.
def _typedstream(body: str) -> bytes:
    payload = body.encode("utf-8")
    if len(payload) < 0x80:
        length = bytes([len(payload)])
    elif len(payload) <= 0xFFFF:
        length = b"\x81" + len(payload).to_bytes(2, "little")
    else:
        length = b"\x82" + len(payload).to_bytes(4, "little")
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84"
        b"\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92"
        b"\x84\x84\x84\x0fNSMutableString\x01\x84\x84\x08NSString\x01"
        b"\x84\x84\x08NSObject\x00\x85\x84\x01+"
        + length
        + payload
        + b"\x86\x84\x02iI\x01"
    )


# The minimal slice of the Messages schema the incoming query touches.
def _chat_db(tmp_path: Path) -> Path:
    path = tmp_path / "chat.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT,
            text TEXT,
            attributedBody BLOB,
            handle_id INTEGER,
            is_from_me INTEGER DEFAULT 0,
            date INTEGER,
            associated_message_type INTEGER DEFAULT 0,
            associated_message_guid TEXT,
            item_type INTEGER DEFAULT 0
        );
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, room_name TEXT, style INTEGER);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        """
    )
    db.commit()
    db.close()
    return path


_NS = 1_000_000_000


# Apple-epoch nanoseconds for "now minus this many seconds ago".
def _ns_ago(seconds: float) -> int:
    from server import _apple_time

    return _apple_time(datetime.now(UTC) - timedelta(seconds=seconds))


# One incoming row, wired through handle and chat the way Messages stores it.
def _insert_incoming(
    path: Path,
    sender: str,
    body: str,
    at_ns: int,
    *,
    in_blob: bool = False,
    group: bool = False,
    from_me: bool = False,
    reaction: int = 0,
    raw_blob: bytes | None = None,
) -> None:
    db = sqlite3.connect(path)
    handle_id = db.execute(
        "INSERT INTO handle (id) VALUES (?)", (sender,)
    ).lastrowid
    blob = raw_blob
    if blob is None and in_blob:
        blob = _typedstream(body)
    message_id = db.execute(
        "INSERT INTO message (guid, text, attributedBody, handle_id, is_from_me,"
        " date, associated_message_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"guid-{handle_id}-{at_ns}",
            None if (in_blob or raw_blob is not None) else body,
            blob,
            handle_id,
            1 if from_me else 0,
            at_ns,
            reaction,
        ),
    ).lastrowid
    chat_id = db.execute(
        "INSERT INTO chat (room_name, style) VALUES (?, ?)",
        ("chat12345" if group else None, 43 if group else 45),
    ).lastrowid
    db.execute(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        (chat_id, message_id),
    )
    db.commit()
    db.close()


def _incoming_config(
    tmp_path: Path, recipients: tuple[str, ...] = ("+15550100",)
) -> BridgeConfig:
    return BridgeConfig(
        token="secret",
        allowed_recipients=frozenset(normalize_recipient(r) for r in recipients),
        host="127.0.0.1",
        port=8010,
        grants_path=tmp_path / "granted.json",
        incoming_db=_chat_db(tmp_path),
    )


def test_incoming_reading_is_off_unless_the_operator_grants_it(monkeypatch, tmp_path):
    from server import incoming_messages

    # The grant is its own deliberate decision, never inherited from the
    # reactions grant or from installing the bridge.
    monkeypatch.delenv("IMESSAGE_BRIDGE_READ_INCOMING", raising=False)
    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "secret")
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    monkeypatch.setenv("IMESSAGE_BRIDGE_READ_REACTIONS", "true")
    assert BridgeConfig.from_environment().incoming_db is None

    result = incoming_messages(_config(), since_ns=0)
    assert result["messages"] == []


def test_a_message_from_an_allowlisted_sender_comes_back_whole(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "see you at 7?", _ns_ago(5))

    result = incoming_messages(config, since_ns=_ns_ago(60))
    (message,) = result["messages"]
    assert message["text"] == "see you at 7?"
    # The identity key is the same normalization AniOS applies, so the backend
    # can match it against its own records without re-normalizing.
    assert message["sender"] == normalize_recipient("+15550100")
    assert message["reply_to"] == "+15550100"
    assert message["guid"]
    assert message["sent_at"].startswith("20")


def test_a_strangers_message_never_leaves_the_bridge(tmp_path):
    import json

    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+19998887777", "private words", _ns_ago(5)
    )

    # Serialize the whole answer: neither the body nor the address may appear
    # anywhere in what leaves this function, not merely outside "messages".
    answer = json.dumps(incoming_messages(config, since_ns=_ns_ago(60)))
    assert "private words" not in answer
    assert "9998887777" not in answer


def test_the_cursor_advances_past_a_strangers_messages(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    at = _ns_ago(5)
    _insert_incoming(config.incoming_db, "+19998887777", "spam", at)

    # A stranger texting constantly must not stall the poll at the same cursor
    # forever.
    result = incoming_messages(config, since_ns=_ns_ago(60))
    assert result["messages"] == []
    assert result["cursor"] == at


def test_group_chat_messages_are_excluded(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "hi from the group", _ns_ago(5), group=True
    )

    # A room is not a person who was allowlisted: someone else's words in a
    # group the allowlisted sender belongs to must never come along.
    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []


def test_only_messages_after_the_cursor_return(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    at = _ns_ago(30)
    _insert_incoming(config.incoming_db, "+15550100", "already seen", at)

    # Strict >: the row at the cursor itself was delivered by the poll that
    # produced that cursor.
    assert incoming_messages(config, since_ns=at)["messages"] == []


def test_a_negative_cursor_starts_from_now(tmp_path):
    from server import _apple_time, incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "old history", _ns_ago(3600))

    # A first-time caller gets a cursor, never a replay of the archive.
    result = incoming_messages(config, since_ns=-1)
    assert result["messages"] == []
    assert abs(result["cursor"] - _apple_time(datetime.now(UTC))) < 5 * _NS


def test_the_batch_cap_leaves_no_gap(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    base = _ns_ago(60)
    for step in range(4):
        _insert_incoming(
            config.incoming_db, "+15550100", f"message {step}", base + step * _NS
        )

    first = incoming_messages(config, since_ns=base - _NS, limit=2)
    assert [m["text"] for m in first["messages"]] == ["message 0", "message 1"]
    # The cursor is the last *scanned* row, so the next poll continues exactly
    # where this one stopped.
    second = incoming_messages(config, since_ns=first["cursor"], limit=2)
    assert [m["text"] for m in second["messages"]] == ["message 2", "message 3"]


def test_a_sender_is_matched_however_the_number_is_written(tmp_path):
    from server import incoming_messages

    # Apple's canonical handle and the operator's allowlist spelling disagree;
    # they are still one person.
    config = _incoming_config(tmp_path, recipients=("737-202-5933",))
    _insert_incoming(config.incoming_db, "+17372025933", "it's me", _ns_ago(5))

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == "it's me"


def test_a_grant_file_sender_may_converse(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+17032613382", "approved late", _ns_ago(5))

    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []
    store_grant(config, "+17032613382")
    # Read fresh, like every other allowlist check: an approval works now,
    # without a bridge restart.
    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == "approved late"


def test_reactions_are_not_messages(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "Loved a message", _ns_ago(5), reaction=2001
    )

    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []


def test_outgoing_rows_are_not_incoming(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "what the bridge sent", _ns_ago(5),
        from_me=True,
    )

    # Otherwise every reply the bridge sends comes back as a message to answer,
    # and the assistant talks to itself forever.
    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []


def test_the_body_is_read_out_of_the_attributed_blob(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "ok", _ns_ago(5), in_blob=True)

    # Most real bodies live in the blob with text NULL — and short ones like
    # "ok" are exactly what the old fragment heuristic dropped.
    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == "ok"


def test_an_emoji_body_survives_extraction(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    body = "sounds great 🎷🎶 — see you então!"
    long_body = "y" * 200  # forces the two-byte 0x81 length form
    _insert_incoming(config.incoming_db, "+15550100", body, _ns_ago(10), in_blob=True)
    _insert_incoming(
        config.incoming_db, "+15550100", long_body, _ns_ago(5), in_blob=True
    )

    texts = [
        m["text"] for m in incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    ]
    assert texts == [body, long_body]


def test_an_unreadable_blob_is_skipped_not_mangled(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "", _ns_ago(5),
        raw_blob=b"\x04\x0bstreamtyped then garbage with no class marker",
    )

    # An exact body or nothing: a half-decoded fragment would be answered as if
    # the person had said it.
    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []


def test_a_row_still_being_written_is_not_skipped_forever(tmp_path, monkeypatch):
    import server as bridge_server
    from server import incoming_messages

    # Messages inserts the row before attributedBody is finished. A poll that
    # lands in the gap must leave the row for the next poll, not advance the
    # cursor past it — that lost a real message once, provably: the poll's own
    # cursor came back equal to a message it never returned.
    config = _incoming_config(tmp_path)
    old = _ns_ago(30)
    young = _ns_ago(1)
    _insert_incoming(config.incoming_db, "+15550100", "settled", old)
    _insert_incoming(config.incoming_db, "+15550100", "mid-write", young)

    first = incoming_messages(config, since_ns=_ns_ago(60))
    assert [m["text"] for m in first["messages"]] == ["settled"]
    assert first["cursor"] == old  # not advanced past the young row

    # The next poll, once the row has settled, picks it up whole.
    monkeypatch.setattr(bridge_server, "SETTLE_SECONDS", 0)
    second = incoming_messages(config, since_ns=first["cursor"])
    assert [m["text"] for m in second["messages"]] == ["mid-write"]


def test_the_first_cursor_also_respects_the_settle_window(tmp_path):
    from server import _apple_time, incoming_messages

    config = _incoming_config(tmp_path)

    # "Start from now" is really "start from the settle boundary": a message
    # arriving in the window right before the first poll belongs to the next
    # poll, not to nobody.
    result = incoming_messages(config, since_ns=-1)
    assert result["cursor"] <= _apple_time(datetime.now(UTC)) - 2 * _NS


def test_incoming_coverage_is_reported_as_counts_only(tmp_path):
    import json

    from server import describe_incoming

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "readable", _ns_ago(5))
    _insert_incoming(
        config.incoming_db, "+19998887777", "", _ns_ago(4),
        raw_blob=b"\x04\x0bstreamtyped junk",
    )

    described = describe_incoming(config)
    assert described["readable"] is True
    assert described["incoming_last_day"] == 2
    assert described["incoming_decodable_last_day"] == 1
    # Counts and shapes only — no body, no address, from either sender.
    text = json.dumps(described)
    assert "5550100" not in text
    assert "9998887777" not in text
