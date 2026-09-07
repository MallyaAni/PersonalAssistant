"""The iMessage bridge's own refusals.

The bridge runs on a Mac and only sends there, but everything that decides
*whether* to send is pure and testable anywhere. Those are the parts worth
covering: this is the last hop before a message reaches a real person, and it
must refuse independently of whatever asked it to send.
"""

import base64
import os
import sys
from dataclasses import replace
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


def test_only_listed_attachment_types_are_accepted():
    # A PDF joined the list on 2026-09-02 (the assistant writes them); an
    # archive is the example of what still may not leave.
    encoded = base64.b64encode(_CALENDAR).decode()
    with pytest.raises(BridgeError, match="Unsupported attachment type"):
        decode_attachment("x.zip", "application/zip", encoded)


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


# The sign-up path is a third normalizer that must land in the same place: a
# number typed at sign-up (to_e164 -> matching_key) has to match what the bridge
# computes for the same person's incoming texts. Only the format was tested
# internationally before; this tests the agreement that actually failed in
# production, across countries.
@pytest.mark.parametrize(
    "e164",
    [
        "+17032613382",
        "+12025550100",
        "+442079460958",
        "+919876543210",
        "+81312345678",
        "+61293744000",
    ],
)
def test_signup_matching_key_agrees_with_the_bridge(e164):
    from backend.core.phone import matching_key

    assert matching_key(e164) == normalize_recipient(e164)


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
    # One database per test directory: a second config over the same
    # directory (a room config beside a plain one) shares it.
    if path.exists():
        return path
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
            item_type INTEGER DEFAULT 0,
            thread_originator_guid TEXT,
            cache_has_attachments INTEGER DEFAULT 0
        );
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            room_name TEXT,
            style INTEGER,
            chat_identifier TEXT,
            display_name TEXT,
            guid TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY,
            filename TEXT,
            mime_type TEXT,
            transfer_name TEXT,
            total_bytes INTEGER
        );
        CREATE TABLE message_attachment_join (
            message_id INTEGER, attachment_id INTEGER
        );
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
    reply_to_guid: str | None = None,
    # A room: its identifier (one chat row per identifier, shared across
    # inserts the way chat.db shares it), its name, everyone in it, and
    # whether the body carries Messages' mention marker.
    chat_identifier: str | None = None,
    chat_name: str = "",
    participants: tuple[str, ...] = (),
    # A mention: the mentioned account's handle, stored after the marker the
    # way Messages stores it (the rendered name is only in the body).
    mention: str | None = None,
    guid: str | None = None,
) -> None:
    db = sqlite3.connect(path)
    handle_id = db.execute("INSERT INTO handle (id) VALUES (?)", (sender,)).lastrowid
    blob = raw_blob
    if blob is None and (in_blob or mention):
        blob = _typedstream(body)
    if mention:
        target = mention.encode("utf-8")
        blob = (blob or b"") + b"\x86\x92\x84\x98\x98\x1c__kIMMentionConfirmedMention\x86\x92\x84\x98\x98" + bytes([len(target)]) + target + b"\x86\x86"
    message_id = db.execute(
        "INSERT INTO message (guid, text, attributedBody, handle_id, is_from_me,"
        " date, associated_message_type, thread_originator_guid)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            guid or f"guid-{handle_id}-{at_ns}",
            None if (in_blob or mention or raw_blob is not None) else body,
            blob,
            handle_id,
            1 if from_me else 0,
            at_ns,
            reaction,
            reply_to_guid,
        ),
    ).lastrowid
    in_room = group or chat_identifier is not None
    identifier = chat_identifier or ("chat12345" if group else None)
    chat_id = (
        db.execute("SELECT ROWID FROM chat WHERE chat_identifier = ?", (identifier,)).fetchone()
        if identifier
        else None
    )
    if chat_id is None:
        chat_id = (
            db.execute(
                "INSERT INTO chat (room_name, style, chat_identifier, display_name, guid)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    identifier if in_room else None,
                    43 if in_room else 45,
                    identifier,
                    chat_name or None,
                    f"iMessage;+;{identifier}" if in_room else None,
                ),
            ).lastrowid,
        )
        for person in participants:
            person_id = db.execute("INSERT INTO handle (id) VALUES (?)", (person,)).lastrowid
            db.execute(
                "INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)",
                (chat_id[0], person_id),
            )
    db.execute(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        (chat_id[0], message_id),
    )
    db.commit()
    db.close()
    return message_id


# Attach one file to an already-inserted message, the way Messages stores it.
def _attach_file(
    path: Path, message_id: int, file_path: Path, mime: str, name: str
) -> int:
    db = sqlite3.connect(path)
    attachment_id = db.execute(
        "INSERT INTO attachment (filename, mime_type, transfer_name, total_bytes)"
        " VALUES (?, ?, ?, ?)",
        (
            str(file_path),
            mime,
            name,
            file_path.stat().st_size if file_path.exists() else 0,
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO message_attachment_join (message_id, attachment_id) VALUES (?, ?)",
        (message_id, attachment_id),
    )
    db.commit()
    db.close()
    return attachment_id


def _incoming_config(
    tmp_path: Path,
    recipients: tuple[str, ...] = ("+15550100",),
    *,
    attachments: bool = False,
    groups: tuple[str, ...] = (),
    read_groups: bool = False,
    display_name: str = "",
    addresses: tuple[str, ...] = (),
) -> BridgeConfig:
    (tmp_path / "Attachments").mkdir(exist_ok=True)
    return BridgeConfig(
        token="secret",
        allowed_recipients=frozenset(normalize_recipient(r) for r in recipients),
        host="127.0.0.1",
        port=8010,
        grants_path=tmp_path / "granted.json",
        incoming_db=_chat_db(tmp_path),
        attachments_enabled=attachments,
        attachments_root=tmp_path / "Attachments",
        groups=frozenset(groups),
        read_groups=read_groups,
        display_name=display_name,
        addresses=frozenset(normalize_recipient(a) for a in addresses),
    )


# Apple's heart tapback is exposed for an exact GUID alongside the existing
# thumbs, so conversational acceptance can use the reaction named in the plan.
def test_a_heart_tapback_is_read_for_the_exact_sent_message(tmp_path):
    from server import read_tapbacks

    base = _incoming_config(tmp_path)
    config = replace(base, messages_db=base.incoming_db)
    db = sqlite3.connect(config.messages_db)
    handle_id = db.execute(
        "INSERT INTO handle (id) VALUES (?)", ("+15550100",)
    ).lastrowid
    db.execute(
        "INSERT INTO message (guid, text, is_from_me, date) VALUES (?, ?, ?, ?)",
        ("target-guid", "Want me to do that?", 1, _ns_ago(8)),
    )
    db.execute(
        "INSERT INTO message (guid, handle_id, is_from_me, date,"
        " associated_message_type, associated_message_guid)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            "reaction-guid",
            handle_id,
            0,
            _ns_ago(4),
            2000,
            "p:0/target-guid",
        ),
    )
    db.commit()
    db.close()

    (reaction,) = read_tapbacks(config, ["target-guid"])
    assert reaction["message_guid"] == "target-guid"
    assert reaction["reaction"] == "loved"
    assert reaction["sender"] == normalize_recipient("+15550100")
    assert reaction["at"] is not None


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
    _insert_incoming(config.incoming_db, "+19998887777", "private words", _ns_ago(5))

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
        config.incoming_db,
        "+15550100",
        "what the bridge sent",
        _ns_ago(5),
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


def test_a_very_long_body_uses_the_four_byte_length_and_survives(tmp_path):
    from server import incoming_messages

    # Bodies past 65,535 bytes use the 0x82 four-byte length form. Nothing
    # sends one on purpose, which is exactly why only a test will ever
    # exercise the branch before a real message needs it.
    config = _incoming_config(tmp_path)
    body = "long " * 15_000  # ~75KB, forces the 0x82 form
    _insert_incoming(
        config.incoming_db, "+15550100", body.strip(), _ns_ago(5), in_blob=True
    )

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == body.strip()


def test_an_unreadable_blob_is_skipped_not_mangled(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db,
        "+15550100",
        "",
        _ns_ago(5),
        raw_blob=b"\x04\x0bstreamtyped then garbage with no class marker",
    )

    # An exact body or nothing: a half-decoded fragment would be answered as if
    # the person had said it.
    assert incoming_messages(config, since_ns=_ns_ago(60))["messages"] == []


def test_a_readable_message_is_delivered_without_waiting_out_the_window(tmp_path):
    from server import incoming_messages

    # The settle window must not delay an ordinary message: a row whose body is
    # readable is returned at once, even one that arrived a moment ago. This is
    # the latency win over the old blanket age gate.
    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "just now", _ns_ago(0.5))

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == "just now"


def test_a_row_still_being_written_is_held_then_delivered(tmp_path):
    from server import incoming_messages

    # Messages inserts the row before attributedBody is finished. A poll landing
    # in that gap sees an unreadable young row: it must hold it (return nothing,
    # cursor not advanced past it), not skip past it - that lost a real message
    # once. When the write completes, the next poll delivers it whole.
    config = _incoming_config(tmp_path)
    at = _ns_ago(1)  # young, and not yet readable
    _insert_incoming(
        config.incoming_db, "+15550100", "", at,
        raw_blob=b"\x04\x0bstreamtyped still being written",
    )
    since = _ns_ago(60)

    first = incoming_messages(config, since_ns=since)
    assert first["messages"] == []
    assert first["cursor"] == since  # held: cursor not advanced past the row

    # The write completes and the body becomes readable.
    db = sqlite3.connect(config.incoming_db)
    db.execute("UPDATE message SET text = ? WHERE date = ?", ("finished writing", at))
    db.commit()
    db.close()

    second = incoming_messages(config, since_ns=first["cursor"])
    assert [m["text"] for m in second["messages"]] == ["finished writing"]


def test_an_old_unreadable_row_does_not_stall_the_poll(tmp_path):
    from server import incoming_messages

    # A row past the window that still will not decode is presumed genuinely
    # unreadable: skipped with the cursor advanced past it, so one bad row
    # cannot freeze the poll forever.
    config = _incoming_config(tmp_path)
    bad = _ns_ago(30)
    _insert_incoming(
        config.incoming_db, "+15550100", "", bad, raw_blob=b"\x04\x0bstreamtyped junk"
    )
    _insert_incoming(config.incoming_db, "+15550100", "after the bad row", _ns_ago(20))

    result = incoming_messages(config, since_ns=_ns_ago(60))
    assert [m["text"] for m in result["messages"]] == ["after the bad row"]


def test_the_first_cursor_starts_just_before_now(tmp_path):
    from server import _apple_time, incoming_messages

    config = _incoming_config(tmp_path)

    # "Start from now" starts a hair before now, so a message arriving during
    # the first connect is caught by the next poll rather than stepped over.
    result = incoming_messages(config, since_ns=-1)
    now = _apple_time(datetime.now(UTC))
    assert now - 5 * _NS <= result["cursor"] <= now


# --- attachments: pictures in, pictures out --------------------------------
#
# Outbound pictures ride the existing attachment arguments with their own
# magic-byte proofs. Inbound bytes leave only through attachment_payload,
# which re-proves who sent the file — an identifier alone is never a
# capability — and honors file paths only inside the Messages store.

# A real 1x1 PNG, used wherever tests need bytes that pass the magic check.
_JPEG_SMALL = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_an_outbound_png_attachment_decodes():
    name, content = decode_attachment(
        "generated.png", "image/png", base64.b64encode(_PNG_1PX).decode()
    )
    assert name == "generated.png"
    assert content == _PNG_1PX


def test_an_outbound_jpeg_attachment_decodes():
    jpeg = b"\xff\xd8\xff\xe0" + b"x" * 32
    name, _ = decode_attachment(
        "photo.jpeg", "image/jpeg", base64.b64encode(jpeg).decode()
    )
    assert name == "photo.jpeg"


def test_image_bytes_must_match_the_declared_type():
    # A PNG declared as JPEG is refused: the magic check is what keeps this
    # from becoming a general file-sending endpoint under image names.
    with pytest.raises(BridgeError, match="not image/jpeg"):
        decode_attachment(
            "photo.jpg", "image/jpeg", base64.b64encode(_PNG_1PX).decode()
        )


def test_an_oversized_image_is_refused():
    from server import MAX_IMAGE_ATTACHMENT_BYTES

    huge = base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_ATTACHMENT_BYTES
    ).decode()
    with pytest.raises(BridgeError, match="too large"):
        decode_attachment("big.png", "image/png", huge)


def test_attachments_are_not_listed_without_their_own_grant(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)  # attachments off
    message_id = _insert_incoming(
        config.incoming_db, "+15550100", "look at this", _ns_ago(5)
    )
    photo = config.attachments_root / "IMG_1.png"
    photo.write_bytes(_PNG_1PX)
    _attach_file(config.incoming_db, message_id, photo, "image/png", "IMG_1.png")

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert "attachments" not in message


def test_an_allowlisted_senders_photo_is_listed(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(
        config.incoming_db, "+15550100", "look at this", _ns_ago(5)
    )
    photo = config.attachments_root / "IMG_1.png"
    photo.write_bytes(_PNG_1PX)
    _attach_file(config.incoming_db, message_id, photo, "image/png", "IMG_1.png")

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    (listed,) = message["attachments"]
    assert listed["media_type"] == "image/png"
    assert listed["name"] == "IMG_1.png"
    assert listed["bytes"] == len(_PNG_1PX)
    assert listed["attachment_id"]


def test_the_attachment_placeholder_is_not_part_of_the_question(tmp_path):
    from server import incoming_messages

    # A photo-with-caption body embeds U+FFFC where the picture sits. The
    # placeholder is framing, not words — a real question arrived as
    # "￼how do i fix this bulge?" and the model should never see it.
    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(
        config.incoming_db,
        "+15550100",
        "￼how do i fix this?",
        _ns_ago(5),
        in_blob=True,
    )
    photo = config.attachments_root / "IMG_9.png"
    photo.write_bytes(_PNG_1PX)
    _attach_file(config.incoming_db, message_id, photo, "image/png", "IMG_9.png")

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == "how do i fix this?"


def test_a_photo_with_no_caption_is_still_a_message(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "", _ns_ago(5))
    photo = config.attachments_root / "IMG_2.png"
    photo.write_bytes(_PNG_1PX)
    _attach_file(config.incoming_db, message_id, photo, "image/png", "IMG_2.png")

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["text"] == ""
    assert message["attachments"]


def test_a_fetched_attachment_round_trips(tmp_path):
    from server import attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "pic", _ns_ago(5))
    photo = config.attachments_root / "IMG_3.png"
    photo.write_bytes(_PNG_1PX)
    attachment_id = _attach_file(
        config.incoming_db, message_id, photo, "image/png", "IMG_3.png"
    )

    payload = attachment_payload(config, str(attachment_id))
    assert payload["media_type"] == "image/png"
    assert payload["name"] == "IMG_3.png"
    assert base64.b64decode(payload["data_base64"]) == _PNG_1PX


def test_a_strangers_attachment_cannot_be_fetched_by_id(tmp_path):
    from server import attachment_payload

    # Knowing an identifier is not permission to read the file it names.
    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(
        config.incoming_db, "+19998887777", "private", _ns_ago(5)
    )
    photo = config.attachments_root / "IMG_4.png"
    photo.write_bytes(_PNG_1PX)
    attachment_id = _attach_file(
        config.incoming_db, message_id, photo, "image/png", "IMG_4.png"
    )

    assert attachment_payload(config, str(attachment_id)) == {"error": "not_found"}


def test_an_attachment_outside_the_messages_store_is_refused(tmp_path):
    from server import attachment_payload

    # A hostile database row must not be able to point the bridge at an
    # arbitrary file on the Mac.
    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "pic", _ns_ago(5))
    outside = tmp_path / "secret.png"
    outside.write_bytes(_PNG_1PX)
    attachment_id = _attach_file(
        config.incoming_db, message_id, outside, "image/png", "secret.png"
    )

    assert attachment_payload(config, str(attachment_id)) == {"error": "not_found"}


def test_fetching_without_the_grant_is_not_found(tmp_path):
    from server import attachment_payload

    config = _incoming_config(tmp_path, attachments=False)
    assert attachment_payload(config, "1") == {"error": "not_found"}


def test_a_video_attachment_is_refused(tmp_path):
    from server import attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "vid", _ns_ago(5))
    movie = config.attachments_root / "IMG_5.mov"
    movie.write_bytes(b"\x00" * 64)
    attachment_id = _attach_file(
        config.incoming_db, message_id, movie, "video/quicktime", "IMG_5.mov"
    )

    payload = attachment_payload(config, str(attachment_id))
    assert payload["error"] == "unsupported_type"
    assert "data_base64" not in payload


def test_an_oversized_fetch_reports_too_large(tmp_path, monkeypatch):
    import server as bridge_server
    from server import attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "pic", _ns_ago(5))
    photo = config.attachments_root / "IMG_6.png"
    photo.write_bytes(_PNG_1PX)
    attachment_id = _attach_file(
        config.incoming_db, message_id, photo, "image/png", "IMG_6.png"
    )

    monkeypatch.setattr(bridge_server, "MAX_INBOUND_ATTACHMENT_BYTES", 8)
    payload = attachment_payload(config, str(attachment_id))
    assert payload["error"] == "too_large"
    assert payload["bytes"] == len(_PNG_1PX)


@pytest.mark.skipif(sys.platform != "darwin", reason="sips ships with macOS")
def test_a_heic_photo_comes_back_as_jpeg(tmp_path):
    import subprocess

    from server import attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    source = config.attachments_root / "IMG_7.png"
    source.write_bytes(_PNG_1PX)
    heic = config.attachments_root / "IMG_7.heic"
    made = subprocess.run(
        ["sips", "-s", "format", "heic", str(source), "--out", str(heic)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0 or not heic.exists():
        pytest.skip("sips on this Mac cannot write HEIC")

    message_id = _insert_incoming(config.incoming_db, "+15550100", "pic", _ns_ago(5))
    attachment_id = _attach_file(
        config.incoming_db, message_id, heic, "image/heic", "IMG_7.heic"
    )

    payload = attachment_payload(config, str(attachment_id))
    assert payload["media_type"] == "image/jpeg"
    assert payload["name"] == "IMG_7.jpeg"
    assert base64.b64decode(payload["data_base64"])[:3] == b"\xff\xd8\xff"


def test_a_native_reply_carries_the_guid_it_answers(tmp_path):
    from server import incoming_messages

    # A long-press reply to an earlier bubble lets the sender point at a
    # specific past picture — the thread originator's guid rides along so the
    # caller can target it explicitly instead of the most recent one.
    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db,
        "+15550100",
        "make this one warmer",
        _ns_ago(5),
        reply_to_guid="the-hummingbird-bubble-guid",
    )

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["reply_to_guid"] == "the-hummingbird-bubble-guid"


def test_an_ordinary_message_has_no_reply_to_guid(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "just a message", _ns_ago(5))

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert "reply_to_guid" not in message


def test_a_captionless_attachment_guid_is_read_back_by_recency(tmp_path):
    from server import _apple_time, latest_sent_attachment_guid

    # A picture with no caption has no body to match on, so its guid is read
    # from the newest outgoing row carrying an attachment. This is the path the
    # worker's image sends take, and the bubble->artifact ledger depends on it.
    config = _incoming_config(tmp_path)
    db = sqlite3.connect(config.incoming_db)
    # An older captioned send and a newer attachment send; the attachment one
    # must win despite being an empty-body row.
    db.execute(
        "INSERT INTO message (guid, text, handle_id, is_from_me, date,"
        " associated_message_type, cache_has_attachments) VALUES (?,?,?,?,?,?,?)",
        ("older-text", "hello", 0, 1, _apple_time(datetime.now(UTC)) - 5 * _NS, 0, 0),
    )
    db.execute(
        "INSERT INTO message (guid, text, handle_id, is_from_me, date,"
        " associated_message_type, cache_has_attachments) VALUES (?,?,?,?,?,?,?)",
        ("the-photo", None, 0, 1, _apple_time(datetime.now(UTC)), 0, 1),
    )
    db.commit()
    db.close()

    assert latest_sent_attachment_guid(config) == "the-photo"


def test_an_empty_body_never_matches_a_text_guid(tmp_path):
    from server import _apple_time, latest_sent_guid

    # An empty body must not match the first NULL-text row it finds - the bug
    # that let a captionless send pin an unrelated bubble.
    config = _incoming_config(tmp_path)
    db = sqlite3.connect(config.incoming_db)
    db.execute(
        "INSERT INTO message (guid, text, handle_id, is_from_me, date,"
        " associated_message_type) VALUES (?,?,?,?,?,?)",
        ("some-null-row", None, 0, 1, _apple_time(datetime.now(UTC)), 0),
    )
    db.commit()
    db.close()

    assert latest_sent_guid(config, "+15550100", "") is None
    assert latest_sent_guid(config, "+15550100", "   ") is None


def test_a_sent_message_guid_can_be_read_back(tmp_path):
    from server import _apple_time, latest_sent_guid

    # The guid readback matches the newest outgoing row by body, and now works
    # under the incoming grant alone (messages_db unset) so an attachment send
    # can report its guid without the reactions grant.
    config = _incoming_config(tmp_path)  # incoming_db set, messages_db None
    db = sqlite3.connect(config.incoming_db)
    db.execute(
        "INSERT INTO message (guid, text, handle_id, is_from_me, date,"
        " associated_message_type) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "sent-guid-42",
            "here is your picture",
            0,
            1,
            _apple_time(datetime.now(UTC)),
            0,
        ),
    )
    db.commit()
    db.close()

    guid = latest_sent_guid(config, "+15550100", "here is your picture")
    assert guid == "sent-guid-42"


def test_incoming_coverage_is_reported_as_counts_only(tmp_path):
    import json

    from server import describe_incoming

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "readable", _ns_ago(5))
    _insert_incoming(
        config.incoming_db,
        "+19998887777",
        "",
        _ns_ago(4),
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


def test_a_reaction_rendered_as_text_is_not_a_message(tmp_path):
    from server import incoming_messages, is_tapback_text

    # Some senders' reactions arrive as an ordinary row whose body is the
    # rendered tapback. Routed as a message it was answered (2026-08-25).
    for body in (
        "Reacted ❤️ to “is there salsa dancing tomorrow?”",
        "Liked “Time to stretch”",
        "Laughed at “doggo”",
        "Emphasized “what's the weather in DC this weekend?”",
        "Removed a heart from “hey”",
    ):
        assert is_tapback_text(body), body
    for body in ("I liked the picture", "Loved it, thanks!", "reacted badly to the news"):
        assert not is_tapback_text(body), body

    config = _incoming_config(tmp_path)
    reaction_at, message_at = _ns_ago(5), _ns_ago(4)
    _insert_incoming(config.incoming_db, "+15550100", "Reacted ❤️ to “is there salsa dancing tomorrow?”", reaction_at)
    _insert_incoming(config.incoming_db, "+15550100", "is there salsa dancing tomorrow?", message_at)
    polled = incoming_messages(config, since_ns=_ns_ago(60))
    assert [m["text"] for m in polled["messages"]] == ["is there salsa dancing tomorrow?"]
    # The cursor moved past the reaction: it is not delivered later either.
    assert polled["cursor"] >= reaction_at


# --- Group chats: only what is addressed to this account leaves the Mac ---

_ROOM = "chat778899001122"
_ROOM_GUID = f"iMessage;+;{_ROOM}"
_PEOPLE = ("+15550100", "+15550101")


_BOT = "deep-matter@agentmail.to"


def _room_config(
    tmp_path: Path, *, read: bool = True, name: str = "Scout", addresses: tuple[str, ...] = (_BOT,)
) -> BridgeConfig:
    return _incoming_config(
        tmp_path, _PEOPLE, groups=(_ROOM,), read_groups=read, display_name=name, addresses=addresses
    )


def _room_messages(config: BridgeConfig) -> list[dict]:
    from server import incoming_messages

    return incoming_messages(config, since_ns=_ns_ago(120))["messages"]


def test_room_talk_not_addressed_to_the_account_is_forwarded_unaddressed(tmp_path):
    # Operator's decision, 2026-08-28: the assistant reads the whole room for
    # context and answers only what was for it. The bridge says which.
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "lunch friday?", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == ""
    assert message["text"] == "lunch friday?"
    assert message["chat_identifier"] == _ROOM


def test_a_reply_in_a_thread_on_the_accounts_bubble_is_addressed(tmp_path):
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "Thai on Friday?", _ns_ago(30),
        chat_identifier=_ROOM, chat_name="Lunch crew", participants=_PEOPLE, from_me=True, guid="bot-1",
    )
    _insert_incoming(
        db, "+15550101", "yes please", _ns_ago(5), chat_identifier=_ROOM, reply_to_guid="bot-1"
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == "reply"
    assert message["text"] == "yes please"
    # Addresses leave the bridge normalized, as they do for one-to-one rows.
    assert message["sender"] == normalize_recipient("+15550101")
    # Answered in the room, anchored to the bubble the person replied to.
    assert message["reply_to"] == _ROOM_GUID
    assert message["chat_guid"] == _ROOM_GUID
    assert message["chat_identifier"] == _ROOM
    assert message["chat_name"] == "Lunch crew"
    assert message["reply_to_guid"] == "bot-1"
    assert message["participants"] == sorted(normalize_recipient(p) for p in _PEOPLE)
    assert message["assistant_name"] == "Scout"


def test_a_thread_on_somebody_elses_bubble_is_not_addressed(tmp_path):
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "pizza?", _ns_ago(30), chat_identifier=_ROOM, participants=_PEOPLE, guid="jen-1"
    )
    _insert_incoming(db, "+15550101", "sure", _ns_ago(5), chat_identifier=_ROOM, reply_to_guid="jen-1")
    assert [m["addressed_by"] for m in _room_messages(config)] == ["", ""]


def test_a_mention_is_matched_on_the_accounts_address_whatever_name_it_renders_as(tmp_path):
    # Each person saves the contact under their own name; the mention stores
    # the handle. No display name configured at all here.
    config = _room_config(tmp_path, name="")
    _insert_incoming(
        config.incoming_db, "+15550100", "Ani's bot\xa0what's the weather friday", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE, mention=_BOT,
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == "mention"
    assert message["text"] == "Ani's bot\xa0what's the weather friday"


def test_a_mention_of_the_accounts_number_counts_too(tmp_path):
    config = _room_config(tmp_path, name="", addresses=(_BOT, "+1 (555) 020-0000"))
    _insert_incoming(
        config.incoming_db, "+15550100", "Scout are you there", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE, mention="+15550200000",
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == "mention"


def test_a_mention_of_somebody_else_is_not_addressed(tmp_path):
    config = _room_config(tmp_path, name="")
    _insert_incoming(
        config.incoming_db, "+15550100", "Jen are you coming", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE, mention="+15550101",
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == ""


def test_mention_targets_are_read_from_the_typedstream():
    from server import mention_targets

    blob = _typedstream("Scout how are you?") + (
        b"\x86\x92\x84\x96\x96\x1c__kIMMentionConfirmedMention\x86\x92\x84\x96\x96\x18deep-matter@agentmail.to\x86\x86"
    )
    assert mention_targets(blob) == {normalize_recipient(_BOT)}
    assert mention_targets(None) == set()
    assert mention_targets(_typedstream("no mention here")) == set()
    two = blob + b"\x86\x92\x84\x96\x96\x1c__kIMMentionConfirmedMention\x86\x92\x84\x96\x96\x0c+12079290146\x86\x86"
    assert mention_targets(two) == {normalize_recipient(_BOT), normalize_recipient("+12079290146")}


def test_the_accounts_name_as_a_word_is_addressed_whatever_the_case(tmp_path):
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "scout, thai or pizza?", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == "name"


def test_the_name_inside_another_word_is_not_addressed(tmp_path):
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "we went scouting yesterday", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    (message,) = _room_messages(config)
    assert message["addressed_by"] == ""


def test_room_rows_need_reading_switched_on(tmp_path):
    config = _room_config(tmp_path, read=False)
    _insert_incoming(
        config.incoming_db, "+15550100", "Scout, hi", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    assert _room_messages(config) == []


def test_a_room_not_on_the_list_is_never_read(tmp_path):
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "Scout, hi", _ns_ago(5),
        chat_identifier="chat999999999999", participants=_PEOPLE,
    )
    assert _room_messages(config) == []


def test_a_room_strangers_words_are_forwarded_flagged_not_dropped(tmp_path):
    # The operator's rule (2026-09-02 evening): the whole room is context and
    # only approved people are answered, so a stranger's words in a listed
    # room travel with sender_allowlisted false and the worker decides.
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550199", "Scout, hi", _ns_ago(5),
        chat_identifier=_ROOM, participants=(*_PEOPLE, "+15550199"),
    )
    (message,) = _room_messages(config)
    assert message["sender_allowlisted"] is False and message["sender"] == "15550199"


def test_a_room_tapback_rendered_as_text_is_skipped_even_with_the_name(tmp_path):
    config = _room_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "Loved “Scout: Thai on Friday?”", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    assert _room_messages(config) == []


def test_room_and_direct_messages_arrive_together_in_order(tmp_path):
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(db, "+15550100", "hi there", _ns_ago(10))
    _insert_incoming(
        db, "+15550101", "Scout, thai?", _ns_ago(5), chat_identifier=_ROOM, participants=_PEOPLE
    )
    direct, room = _room_messages(config)
    assert direct["text"] == "hi there"
    assert direct["reply_to"] == "+15550100"
    assert "chat_identifier" not in direct
    assert room["chat_identifier"] == _ROOM


def test_reading_rooms_needs_a_way_to_be_addressed(monkeypatch, tmp_path):
    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "secret")
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    monkeypatch.setenv("IMESSAGE_BRIDGE_GROUPS", f"{_ROOM}, iMessage;+;chat112233445566")
    monkeypatch.setenv("IMESSAGE_BRIDGE_READ_GROUPS", "1")
    monkeypatch.delenv("IMESSAGE_BRIDGE_DISPLAY_NAME", raising=False)
    monkeypatch.delenv("IMESSAGE_BRIDGE_ADDRESSES", raising=False)
    with pytest.raises(BridgeError):
        BridgeConfig.from_environment()
    monkeypatch.setenv("IMESSAGE_BRIDGE_ADDRESSES", f"{_BOT}, +1 555 020 0000")
    config = BridgeConfig.from_environment()
    assert config.groups == frozenset({_ROOM, "chat112233445566"})
    assert config.read_groups is True
    assert config.addresses == frozenset({normalize_recipient(_BOT), normalize_recipient("+15550200000")})
    assert config.display_name == ""
    monkeypatch.setenv("IMESSAGE_BRIDGE_DISPLAY_NAME", "Scout")
    assert BridgeConfig.from_environment().display_name == "Scout"


def test_chat_targets_are_recognised_by_shape():
    from server import normalize_chat_target

    assert normalize_chat_target(_ROOM) == _ROOM
    assert normalize_chat_target(_ROOM_GUID) == _ROOM
    assert normalize_chat_target(" iMessage;+;chat778899001122 ") == _ROOM
    assert normalize_chat_target("+15550100") is None
    assert normalize_chat_target("chat12") is None
    assert normalize_chat_target("chatroom") is None
    assert normalize_chat_target("") is None


def test_a_listed_room_is_a_valid_recipient_and_others_are_not(tmp_path):
    config = _room_config(tmp_path)
    assert check_recipient(config, _ROOM) == _ROOM_GUID
    assert check_recipient(config, _ROOM_GUID) == _ROOM_GUID
    with pytest.raises(BridgeError):
        check_recipient(config, "chat999999999999")
    with pytest.raises(BridgeError):
        check_recipient(_incoming_config(tmp_path), _ROOM)


def test_rooms_cannot_be_granted_by_callers(tmp_path):
    config = _room_config(tmp_path)
    with pytest.raises(BridgeError):
        store_grant(config, "chat999999999999")
    assert not config.grants_path.exists()


def test_sending_to_a_room_addresses_the_chat(tmp_path, monkeypatch):
    import server

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(server, "run_osascript", lambda script, args: calls.append((script, args)))
    monkeypatch.setattr(server, "latest_sent_guid", lambda *a, **k: "room-guid-1")
    config = _room_config(tmp_path)
    assert server.send_message(config, _ROOM, "Thai it is") == "room-guid-1"
    ((script, args),) = calls
    assert script is server._SEND_TEXT_TO_CHAT
    assert args[1] == _ROOM_GUID
    assert args[2] == "Thai it is"


def test_sending_to_a_person_still_uses_the_participant_script(tmp_path, monkeypatch):
    import server

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(server, "run_osascript", lambda script, args: calls.append((script, args)))
    monkeypatch.setattr(server, "latest_sent_guid", lambda *a, **k: None)
    config = _room_config(tmp_path)
    assert server.send_message(config, "+15550100", "hi") == "sent"
    ((script, args),) = calls
    assert script is server._SEND_TEXT
    assert args[1] == "+15550100"


def test_readback_after_a_room_send_is_scoped_to_that_room(tmp_path):
    from server import latest_sent_guid

    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "same words", _ns_ago(3), chat_identifier=_ROOM,
        participants=_PEOPLE, from_me=True, guid="in-room",
    )
    _insert_incoming(db, "+15550100", "same words", _ns_ago(1), from_me=True, guid="direct")
    assert latest_sent_guid(config, "+15550100", "same words") == "direct"
    assert latest_sent_guid(config, _ROOM_GUID, "same words", chat_identifier=_ROOM) == "in-room"


def test_a_room_picture_is_readable_only_when_rooms_are(tmp_path):
    from server import _owned_attachment

    config = _room_config(tmp_path)
    photo = config.attachments_root / "room.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)
    message_id = _insert_incoming(
        config.incoming_db, "+15550100", "Scout, what is this", _ns_ago(5),
        chat_identifier=_ROOM, participants=_PEOPLE,
    )
    attachment_id = _attach_file(config.incoming_db, message_id, photo, "image/jpeg", "room.jpg")
    assert _owned_attachment(config, attachment_id) is not None
    quiet = _room_config(tmp_path, read=False)
    assert _owned_attachment(quiet, attachment_id) is None


# A reply carries the guid of the bubble it answers, and nothing else. The
# words are in another row, and without them the caller knows a reply
# happened but not what it was about - which on 2026-08-30 was the whole
# failure: a run of "try again" retries in a group thread resolved against
# the most recent message instead of the aqueduct message being pointed at.
def test_a_reply_carries_what_the_replied_to_message_said(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "can you draw it as a diagram instead?",
        _ns_ago(60), guid="the-diagram-request",
    )
    _insert_incoming(
        config.incoming_db, "+15550100", "try again", _ns_ago(5),
        reply_to_guid="the-diagram-request",
    )

    message = incoming_messages(config, since_ns=_ns_ago(120))["messages"][-1]
    assert message["reply_to_guid"] == "the-diagram-request"
    assert message["reply_to_text"] == "can you draw it as a diagram instead?"


def test_a_reply_to_a_bubble_whose_words_are_in_the_blob_still_reads(tmp_path):
    # Recent macOS keeps the body in attributedBody and leaves `text` null.
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "draw the aqueduct", _ns_ago(60),
        guid="the-aqueduct-bubble", in_blob=True,
    )
    _insert_incoming(
        config.incoming_db, "+15550100", "try again", _ns_ago(5),
        reply_to_guid="the-aqueduct-bubble",
    )

    message = incoming_messages(config, since_ns=_ns_ago(120))["messages"][-1]
    assert "aqueduct" in message["reply_to_text"]


def test_an_ordinary_message_carries_no_replied_to_text(tmp_path):
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(config.incoming_db, "+15550100", "hello", _ns_ago(5))

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert "reply_to_text" not in message


def test_a_reply_to_a_bubble_that_is_gone_says_nothing_rather_than_failing(tmp_path):
    # An old bubble pruned out of chat.db, or one from before this account
    # existed. The reference is still reported; the words simply are not.
    from server import incoming_messages

    config = _incoming_config(tmp_path)
    _insert_incoming(
        config.incoming_db, "+15550100", "try again", _ns_ago(5),
        reply_to_guid="no-such-bubble",
    )

    (message,) = incoming_messages(config, since_ns=_ns_ago(60))["messages"]
    assert message["reply_to_guid"] == "no-such-bubble"
    assert "reply_to_text" not in message


# The two document types the assistant writes may leave, each proven by its
# first bytes like a picture is; anything else dressed in their name may not.
def test_an_outbound_pdf_attachment_decodes():
    pdf = b"%PDF-1.4\n" + b"x" * 64
    name, content = decode_attachment(
        "Amalfi itinerary.pdf", "application/pdf", base64.b64encode(pdf).decode()
    )
    assert name == "Amalfi itinerary.pdf"
    assert content == pdf


def test_an_outbound_word_file_decodes():
    docx = b"PK\x03\x04" + b"x" * 64
    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    name, _ = decode_attachment("Plan.docx", media, base64.b64encode(docx).decode())
    assert name == "Plan.docx"


def test_a_picture_dressed_as_a_pdf_is_refused():
    with pytest.raises(BridgeError):
        decode_attachment(
            "sneaky.pdf", "application/pdf", base64.b64encode(_PNG_1PX).decode()
        )


def test_a_pdf_must_be_named_as_one():
    pdf = b"%PDF-1.4\n" + b"x" * 64
    with pytest.raises(BridgeError, match="must be named"):
        decode_attachment("payload.sh", "application/pdf", base64.b64encode(pdf).decode())


# Auto rooms: with IMESSAGE_BRIDGE_GROUPS=auto the bridge reads any group
# whose every member is on the allowlist, so a room of approved people works
# the moment the account is added; a room with one stranger never leaves
# the Mac. Listed ids still count (2026-09-02).
def _auto_config(tmp_path, recipients, groups=()):
    from dataclasses import replace

    config = _incoming_config(tmp_path, recipients, groups=groups, read_groups=True, display_name="Scout")
    return replace(config, groups_auto=True)


def test_auto_mode_reads_a_room_whose_members_are_all_allowlisted(tmp_path):
    from server import incoming_messages

    people = ("+15550100", "+15550101")
    config = _auto_config(tmp_path, people)
    db = _chat_db(tmp_path)
    _insert_incoming(db, "+15550100", "Scout, thai or pizza?", _ns_ago(30), chat_identifier="chat900", chat_name="Dinner", participants=people, guid="a-1")
    _insert_incoming(db, "+15550101", "pizza", _ns_ago(20), chat_identifier="chat900", chat_name="Dinner", participants=people, guid="a-2")
    result = incoming_messages(config, 0)
    guids = [m["guid"] for m in result["messages"]]
    assert guids == ["a-1", "a-2"], result
    assert result["messages"][0]["addressed_by"] == "name" and not result["messages"][1].get("addressed_by")


def test_auto_mode_reads_a_room_with_a_stranger_and_flags_who_is_allowlisted(tmp_path):
    # The operator's rule (2026-09-02 evening): the whole room is context,
    # only approved people are answered - so a stranger's words travel,
    # flagged, and the worker decides. A room with no approved member is not read.
    from server import incoming_messages

    config = _auto_config(tmp_path, ("+15550100", "+15550101"))
    db = _chat_db(tmp_path)
    latest = _ns_ago(20)
    _insert_incoming(db, "+15550100", "Scout, hi", _ns_ago(30), chat_identifier="chat901", chat_name="Mixed", participants=("+15550100", "+15550101", "+15550199"), guid="s-1")
    _insert_incoming(db, "+15550199", "who is this?", latest, chat_identifier="chat901", chat_name="Mixed", participants=("+15550100", "+15550101", "+15550199"), guid="s-2")
    result = incoming_messages(config, 0)
    flags = {m["guid"]: m["sender_allowlisted"] for m in result["messages"]}
    assert flags == {"s-1": True, "s-2": False}
    assert result["cursor"] >= latest


def test_auto_mode_does_not_read_a_room_with_no_allowlisted_member(tmp_path):
    from server import incoming_messages

    config = _auto_config(tmp_path, ("+15550100",))
    db = _chat_db(tmp_path)
    _insert_incoming(db, "+15550198", "Scout, hi", _ns_ago(30), chat_identifier="chat903", chat_name="Strangers", participants=("+15550198", "+15550199"), guid="n-1")
    assert incoming_messages(config, 0)["messages"] == []


def test_a_one_to_one_stranger_is_still_filtered(tmp_path):
    from server import incoming_messages

    config = _auto_config(tmp_path, ("+15550100",))
    db = _chat_db(tmp_path)
    _insert_incoming(db, "+15550199", "hello?", _ns_ago(30), guid="o-1")
    assert incoming_messages(config, 0)["messages"] == []


def test_auto_mode_keeps_a_listed_room_even_with_a_stranger(tmp_path):
    from server import incoming_messages

    config = _auto_config(tmp_path, ("+15550100",), groups=("chat902",))
    db = _chat_db(tmp_path)
    _insert_incoming(db, "+15550100", "Scout, hi", _ns_ago(30), chat_identifier="chat902", chat_name="Listed", participants=("+15550100", "+15550199"), guid="l-1")
    result = incoming_messages(config, 0)
    assert [m["guid"] for m in result["messages"]] == ["l-1"]


def test_auto_is_parsed_beside_listed_ids(monkeypatch):
    from server import BridgeConfig as Config

    monkeypatch.setenv("IMESSAGE_BRIDGE_TOKEN", "t")
    monkeypatch.setenv("IMESSAGE_BRIDGE_RECIPIENTS", "+15550100")
    monkeypatch.setenv("IMESSAGE_BRIDGE_GROUPS", "auto, chat308729799386740866")
    monkeypatch.setenv("IMESSAGE_BRIDGE_READ_GROUPS", "true")
    monkeypatch.setenv("IMESSAGE_BRIDGE_DISPLAY_NAME", "Scout")
    config = Config.from_environment()
    assert config.groups_auto and "chat308729799386740866" in config.groups


# A picture over the inbound cap is shrunk on the Mac, not refused: a camera
# JPEG of 26 MB got "too_large" and the person was told it was still
# downloading (2026-09-02). sips is not here, so the shrink is stood in for;
# a non-image over the cap is still refused.
def test_an_oversized_picture_is_shrunk_to_fit_not_refused(tmp_path, monkeypatch):
    import server
    from server import MAX_INBOUND_ATTACHMENT_BYTES, attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "pic", _ns_ago(5))
    photo = config.attachments_root / "DSCF0818.JPG"
    photo.write_bytes(b"\xff\xd8" + b"\x00" * (MAX_INBOUND_ATTACHMENT_BYTES + 10))
    attachment_id = _attach_file(config.incoming_db, message_id, photo, "image/jpeg", "DSCF0818.JPG")
    asked: list[int] = []

    def shrink(source, directory, side):
        asked.append(side)
        target = directory / f"{source.stem}-{side}.jpeg"
        target.write_bytes(_JPEG_SMALL if side <= 1600 else b"\xff\xd8" + b"\x00" * (MAX_INBOUND_ATTACHMENT_BYTES + 1))
        return target

    monkeypatch.setattr(server, "_shrink_image", shrink)
    payload = attachment_payload(config, str(attachment_id))
    assert "error" not in payload, payload
    assert payload["media_type"] == "image/jpeg" and payload["name"] == "DSCF0818.jpeg"
    assert base64.b64decode(payload["data_base64"]) == _JPEG_SMALL
    assert asked == [2048, 1600], "each longest edge in turn until it fits"


def test_an_oversized_document_is_still_refused(tmp_path):
    from server import MAX_INBOUND_ATTACHMENT_BYTES, attachment_payload

    config = _incoming_config(tmp_path, attachments=True)
    message_id = _insert_incoming(config.incoming_db, "+15550100", "doc", _ns_ago(5))
    document = config.attachments_root / "big.pdf"
    document.write_bytes(b"%PDF-1.4" + b"\x00" * (MAX_INBOUND_ATTACHMENT_BYTES + 10))
    attachment_id = _attach_file(config.incoming_db, message_id, document, "application/pdf", "big.pdf")
    payload = attachment_payload(config, str(attachment_id))
    assert payload["error"] == "too_large"


# Carrying on your own request, which is how a person retries in a room.
#
# Groupie, 2026-09-07 01:36: "try again", sent as a reply anchored on the
# asker's own earlier "Scout whats going on today to do in the area for us?".
# The reply branch recognised only bubbles this account had sent, so quoting
# your own question addressed nobody and the assistant read the room and said
# nothing. Two minutes later the identical words, anchored on one of its own
# bubbles, were answered - which is exactly why it looked like it had ignored
# the first one.
def test_a_reply_to_your_own_addressed_question_is_addressed(tmp_path):
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "Scout whats going on today to do in the area for us?",
        _ns_ago(30), chat_identifier=_ROOM, participants=_PEOPLE, guid="ani-1",
    )
    _insert_incoming(
        db, "+15550100", "try again", _ns_ago(5),
        chat_identifier=_ROOM, reply_to_guid="ani-1",
    )
    addressed = [m["addressed_by"] for m in _room_messages(config)]
    assert addressed == ["name", "reply"], addressed
    # The question comes with it, so "try again" has something to retry.
    assert _room_messages(config)[1]["reply_to_text"].startswith("Scout whats going on")


# The bound on that rule, in both directions.
def test_a_reply_to_your_own_ordinary_message_is_not_addressed(tmp_path):
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "pizza tonight?", _ns_ago(30),
        chat_identifier=_ROOM, participants=_PEOPLE, guid="ani-2",
    )
    _insert_incoming(
        db, "+15550100", "actually never mind", _ns_ago(5),
        chat_identifier=_ROOM, reply_to_guid="ani-2",
    )
    assert [m["addressed_by"] for m in _room_messages(config)] == ["", ""]


def test_somebody_else_replying_to_your_question_stays_between_them(tmp_path):
    # The anchor was addressed to the assistant, but this is one member
    # answering another. Reading the room is not being spoken to.
    config = _room_config(tmp_path)
    db = config.incoming_db
    _insert_incoming(
        db, "+15550100", "Scout what is on this weekend?", _ns_ago(30),
        chat_identifier=_ROOM, participants=_PEOPLE, guid="ani-3",
    )
    _insert_incoming(
        db, "+15550101", "i already know, the fair", _ns_ago(5),
        chat_identifier=_ROOM, reply_to_guid="ani-3",
    )
    assert [m["addressed_by"] for m in _room_messages(config)] == ["name", ""]
