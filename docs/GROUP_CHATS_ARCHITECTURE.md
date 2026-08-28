# Group chats - design and status

The assistant in an iMessage group with approved users, as its own session.
Decision record: [ADR 0016](adr/0016-a-group-is-an-account.md). Status:
**in implementation (2026-08-28)**; each part below is marked as it lands.

## What a person sees

- Someone adds the assistant (the Mac's iMessage account) to a group with
  friends who are approved users. The first time it is addressed, the group is
  set up on its own; if anyone in the group is not an approved user it stays
  silent and the operator gets one text.
- It answers when addressed: tap-and-hold → Reply on any of its bubbles (and
  every later message in that thread, from anyone, at any time), an @mention, or
  its name as a word. Two more triggers are designed and not yet built - the
  next message from someone it asked a question, and a tapback on its bubble
  meaning "yes, do that" - because both need the Mac to forward an unaddressed
  message on the backend's say-so (see Status).
- A burst of small messages ("ok" / "thai then" / "friday?") gets one answer,
  once the person has finished; "sounds good, thanks" gets none.
- It knows what members like - their name and the interests they follow - from
  what they already told it in private, and nothing else of theirs: not where
  they live, not what they said in a private conversation. Asked for a member's
  private detail in the room, it says that is theirs to share (operator's
  decision, 2026-08-28: tastes only).
- "Jen and I love Thai food" is remembered for Ani (their own share) and for the
  group with its source ("said by Ani"); "we love hiking" for the group; "Jen is
  allergic to peanuts" is the group's knowledge with its source and is never
  written into Jen's memory on someone else's word.
- Scout digests on the group's shared interests and the group's reminders
  arrive in the group thread.

## Design

### A group is an account
`user_id = group:<slug>` (`slug` = first 12 hex of the keyed digest of the chat
guid), a `user_accounts` row with an unusable password and `is_admin=False`, a
profile row, a subscriber row whose address is the chat guid on the
`imessage_group` channel, and `conversation_groups` / `conversation_group_members`
rows. Everything the group owns lives under that `user_id`.

### Bridge (Mac) - `bridges/imessage_mac/server.py`
- Grants: `IMESSAGE_BRIDGE_READ_GROUPS` (off by default, needs `READ_INCOMING`),
  `IMESSAGE_BRIDGE_GROUPS` (allowlisted `chatNNN` identifiers; env only, grants
  never widen it), `IMESSAGE_BRIDGE_DISPLAY_NAME` (the contact name others see).
- `incoming_messages` keeps `room_name IS NULL` for one-to-one rows and adds the
  allowlisted-group branch. A group row is returned only when the sender is
  allowlisted **and** the message is addressed: reply-thread (its
  `thread_originator_guid` is a from-me guid in that chat - chat.db is the
  ledger, the bridge stays stateless), mention (`kIMMention` bytes in
  `attributedBody` plus the display name), name (whole word). Payload gains
  `chat_guid`, `chat_identifier`, `chat_name`, `participants` (from
  `chat_handle_join`), `addressed_by`.
- Sending to a group uses the `chat id "iMessage;+;chatNNN"` AppleScript form
  (verified to resolve on this Mac, 2026-08-28); `check_recipient` accepts an
  allowlisted chat target; guid readback is scoped per chat.

### Worker - `backend/workers/imessage_chat.py`
- A room's message (`chat_identifier` on the payload) takes its own path,
  `_handle_room_message`: the speaker and every participant are resolved through
  `_account_for` (the subscriber allowlist); any unresolved participant → the
  row is finished silently and the operator gets one text per room per day
  (`OPERATOR_ALERT_PHONE`, dedup in Redis `imessage:chat:room_alert:{digest}`;
  nothing about the strangers is sent).
- Provisioning is automatic on the first addressed message when all resolve
  (`_group_for`: `ConversationGroupRepository.provision`, idempotent per chat;
  membership re-synced on every message; departed members are marked as left,
  never deleted). A disabled group finishes rows silently.
- One session per group: the ordinary `imessage:chat:conversation:{user_id}`
  key under the group's user id, with the same idle window as a person's thread.
- The turn runs as the group with `metadata = {channel: "imessage_group",
  group: {chat_name, speaker_user_id, members, addressed_by, assistant_name}}`
  (`assistant_name` is the bridge's display name - what a mention renders and
  what the room calls the assistant; the reply prompt says "in this chat you
  are called X"); the pipeline fills in `speaker_name` and `group_user_id`. Replies, acks, and pictures go to
  the chat (`reply_to` is the chat guid). A photo in the room is a vision turn
  under the group.
- Burst judgement (`_collect`): every addressed text fragment - room or
  one-to-one - is appended to a pending record keyed by the reply address, and
  `POST /chat/readiness` (`services/readiness.py`, routing model, schema
  `{complete, needs_reply, reason}`, `prompts/routing/readiness.md`) is asked
  whether the person has finished and whether an answer is wanted. Not finished
  → keep listening; finished and wanted → one turn for the joined fragments;
  finished and unwanted ("thanks!") → no bubble. A pending burst older than
  `IMESSAGE_CHAT_BURST_CAP_SECONDS` (90 s) is answered by the next poll. The
  judgement fails open to answering; `IMESSAGE_CHAT_READINESS_ENABLED=false`
  restores answer-every-message.

### Reply pipeline
- `ConversationService._attach_group` puts the room on the turn context:
  members through the taste allowlist, the speaker's name (written back onto
  the request metadata, so the stored turn's `extra_data.group.speaker_name`
  says who spoke), and a `group` entry in the turn trace.
- Transcript labels through `backend/services/transcript.py` (`speaker_label`,
  `user_content`) in the reply assembly (`agents/reply/nodes.py`), the
  follow-up resolver, the router's history window, and the planner history -
  "Jen: thai?" where a one-to-one turn is the bare query, byte for byte.
- `backend/memory/tastes.py` (`TasteProjection`): the only door from a member's
  store to a group prompt - profile name and Scout interest labels, at most 8;
  a member whose profile cannot be read stays on the roster as "Member n".
  Home area, semantic facts, relationships are deliberately not read here.
- `prompts/reply/imessage_group.md`, appended after `imessage_style` when
  `channel == "imessage_group"`: the chat's name, who is speaking, each member's
  likes, and the rule that everything else about a member is theirs to share.

### Memory attribution
- `proposal_agent.propose(..., speaker=, roster=)` adds
  `prompts/memory/proposal_group.md` and a decision with `about`: a list of
  roster names or "the group", read for meaning ("Jen and I", "us", "the two
  of us"); every proposal of the turn carries it. Without a roster the call is
  unchanged.
- `backend/memory/attribution.owners_for` (pure): named the speaker, or nothing
  → the speaker's own store plus the group's copy with its source; named the
  group, another member, or an outsider → the group's store only, with its
  source. `with_provenance` puts the source in the words ("… (said by Ani)")
  because the group's memory is read without the roster.
- `_owned_copies` in the conversation service applies the profile rule on top:
  a name, style, or locality is only ever the speaker's; an interest is the
  speaker's, or the group's when the fact is about the group; never another
  member's.
- `_persist_memory_proposals` writes each copy through the ordinary saver
  under its owner and records a change per owner (`scheduled_task_changes`),
  so "forget that" works from the group and from a member's own thread.

### Delivery
- `SUBSCRIBER_CHANNELS` gains `imessage_group`; the channel map sends it through
  the same Messages channel; no bridge grant is attempted for a chat.
- Scout for the group needs nothing new: its schedule, interests and locality
  live under the group id; `deliver` fans out to the group's subscriber.

### Admin
- `GET /admin/groups` (members and state; never the chat address),
  `POST /admin/groups/{id}/enabled?enabled=true|false`, `DELETE /admin/groups/{id}`
  (the same schema-driven purge account deletion runs, then the group rows).

## Proof

Edge cases every suite must cover (the operator's standing instruction,
2026-08-28: thorough functional testing with edge cases):
- Triggers: a reply in a thread anchored on the assistant's bubble from a
  *different* member than the one who started it; a reply to the operator's
  own hand-typed bubble; a mention of another contact whose text also names the
  assistant; the assistant's name inside a word ("scouting") - not a trigger;
  a tapback on someone else's bubble - not a trigger; an unaddressed message
  from an allowlisted member - never leaves the Mac.
- Bursts: "ok" / "thai then" / "friday?" → one answer after the last; "sounds
  good, thanks" → silence; a question fragment that ends mid-thought ("what
  about") → keep listening; a fragment arriving after the answer started → the
  next turn; two members bursting at once in one thread → two turns, not one.
- Membership: an unapproved number added mid-conversation → silence from the
  next message and one alert; a member leaving; two groups sharing members
  (no cross-talk of memory); the speaker is the operator; a group of exactly
  two; the assistant addressed before provisioning completes twice (idempotent).
- Memory: "Jen and I", "us", "she" after Jen is named, "my sister" who is not a
  member, "Jen is allergic to peanuts" (nobody's store), "I'm vegetarian" (the
  speaker's), a member's "forget me" removing attributed tastes, a private 1:1
  fact asked about in the group (never repeated), "forget that" from the group
  (only the group's own change).
- Delivery and limits: a digest into the chat; a group reminder firing into the
  chat with no speaker; the group's search allowance used up ("Heads up" names
  the group's allowance); a picture in the group with the desktop off.
- Unit: bridge fixture with groups (addressed vs unaddressed, strangers, other
  chats, sends), worker (membership wall, one alert, provisioning, chat replies),
  repository, attribution policy, per-owner persistence, transcript labels.
- Real model: `functional/test_group_attribution_behaviour.py` (phrasings and
  the third-person-fact case), `test_group_reply_behaviour.py` (a member's
  taste steers a suggestion; a private detail is theirs to share; the speaker
  is addressed), `test_burst_readiness_behaviour.py` (fifteen bursts plus the
  room aside).
- HTTP: sweep journeys "group: …" - the room is provisioned for the sweep with a
  second member "Jen" who likes thai food; a plan lands in the group's memory
  and not the member's; a dinner suggestion; a private address told in Jen's
  own thread never appears in the room.
- Manual acceptance on the Mac with the operator's second number and one friend.

Unit: `test_imessage_bridge.py` (rooms: 19 cases), `test_imessage_group_worker.py`,
`test_conversation_groups.py`, `test_group_admin_routes.py`, `test_memory_attribution.py`,
`test_transcript_labels.py`, `test_group_tastes.py`, `test_readiness_judgement.py`,
`test_readiness_api.py`, `test_memory_proposal_roster.py`, `test_task_runner.py`
(group delivery).

## Status
| Part | State |
|---|---|
| Design, ADR | written 2026-08-28 |
| Bridge group reads and chat sends | built 2026-08-28; unit-tested (rooms fixture); a live `chat id` send awaits the operator's acceptance chat |
| Data model, migration, provisioning | built; migration `20260828_0011`; repository tested against the database |
| Worker session, membership wall, readiness judgement | built; unit-tested; readiness pinned on the real routing model |
| Reply pipeline, tastes door, transcript labels | built; group reply pinned on the real reply model |
| Memory attribution and per-owner writes | built; attribution pinned on the real routing model |
| Delivery to the chat | built (`imessage_group` channel, task runner) |
| Admin | built; routes tested |
| Sweep journeys, docs, diagrams | built; verified by deploy (see CHANGELOG) |
| Pending-question and tapback triggers | not built - need a bridge tool that forwards one member's next message on request |
| Manual acceptance on the Mac | pending: list the acceptance chat in `IMESSAGE_BRIDGE_GROUPS`, set `IMESSAGE_BRIDGE_READ_GROUPS` and `IMESSAGE_BRIDGE_DISPLAY_NAME`, restart the bridge |
