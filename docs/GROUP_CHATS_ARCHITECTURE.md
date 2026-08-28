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
  every later message in that thread, from anyone, at any time), an @mention or
  its name, the next message from someone it asked a question, or a tapback on
  its bubble meaning "yes, do that".
- A burst of small messages ("ok" / "thai then" / "friday?") gets one answer,
  once the person has finished; "sounds good, thanks" gets none.
- It knows what members like (interests, cuisines, activities, home area) from
  what they already told it in private - and never repeats a private fact.
- "Jen and I love Thai food" is remembered for both; "we love hiking" for the
  group; "Jen is allergic to peanuts" is not written into Jen's memory on
  someone else's word.
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
- One session per chat (`imessage:chat:group:{chat_digest}`); speaker and every
  participant resolved through `_account_for`; any unresolved participant →
  silent and one operator alert (`OPERATOR_ALERT_PHONE`, dedup per chat).
- Provisioning is automatic on the first addressed message when all resolve.
- The turn runs as the group with `metadata = {channel: "imessage_group",
  speaker_id, speaker_name, chat_digest, addressed_by}`; replies, acks and
  pictures go to the chat.
- Burst judgement: after each addressed fragment, `judge_readiness(last_bubble,
  fragments)` (routing model, schema `{complete, needs_reply}`) decides whether
  to keep listening, answer the whole burst, or stay quiet. Applied to one-to-one
  chats too.

### Reply pipeline
- `GroupTurn` from the metadata: group, speaker, members with tastes.
- Transcript labels through `backend/services/transcript.py` in the reply
  assembly, the follow-up resolver, the router's history window, and the two
  digesters.
- `backend/memory/tastes.py`: the only door from a member's store to a group
  prompt - interests, likes, city-level home, preferred name; screened by
  `OutboundPrivacyPolicy`; bounded.
- `prompts/reply/imessage_group.md`: a shared thread, address the named speaker,
  others read along, use only what this context holds.

### Memory attribution
- `proposal_agent.propose(..., roster=)` uses a group decision whose kinds carry
  `about` (schema enum: `speaker`, member ids, `group`); no `preferred_name` or
  `response_style` fields at all.
- `backend/memory/attribution.owners_for` (pure): tastes → every named member
  (+ group when named); personal facts → speaker if about the speaker, group if
  about the group, never another member.
- `_persist_memory_proposals` writes per owner with provenance and records a
  change per owner so "forget that" works from that owner's own thread.

### Delivery
- `SUBSCRIBER_CHANNELS` gains `imessage_group`; the channel map sends it through
  the same Messages channel; no bridge grant is attempted for a chat.
- Scout for the group needs nothing new: its schedule, interests and locality
  live under the group id; `deliver` fans out to the group's subscriber.

### Admin
- `GET /admin/groups`, `POST /admin/groups/{id}/disable|enable`,
  `DELETE /admin/groups/{id}`.

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
  the third-person-fact case), `test_group_reply_behaviour.py`,
  `test_group_privacy_behaviour.py` (a private fact never appears),
  `test_turn_readiness_behaviour.py` (bursts).
- HTTP: sweep journeys "group: …" with database assertions.
- Manual acceptance on the Mac with the operator's second number and one friend.

## Status
| Part | State |
|---|---|
| Design, ADR | written 2026-08-28 |
| Bridge group reads and chat sends | not started |
| Data model, migration, provisioning | not started |
| Worker session, membership wall, readiness judgement | not started |
| Reply pipeline, tastes door, transcript labels | not started |
| Memory attribution and per-owner writes | not started |
| Delivery to the chat | not started |
| Admin | not started |
| Sweep journeys, docs, diagrams | not started |
