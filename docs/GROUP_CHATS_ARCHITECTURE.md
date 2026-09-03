# Group chats - design and status

The assistant in an iMessage group with approved users, as its own session.
Decision record: [ADR 0016](adr/0016-a-group-is-an-account.md). Status:
**in implementation (2026-08-28)**; each part below is marked as it lands.

## What a person sees

- Someone adds the assistant (the Mac's iMessage account) to a group with
  friends who are approved users. The first time it is addressed, the group is
  set up on its own; if anyone in the group is not an approved user it stays
  silent and the operator gets one text.
- It reads every message in the group for context - what the members say to
  each other is the room's memory too ("we all settled on thai for friday",
  said between two members, sticks) - and answers only when addressed:
  tap-and-hold → Reply on any of its bubbles (and every later message in that
  thread, from anyone, at any time), an @mention, or its name as a word.
  Operator's decision, 2026-08-28: "it must be reading every message for
  context". Two more triggers are designed and not yet built - the
  next message from someone it asked a question, and a tapback on its bubble
  meaning "yes, do that" - because both need the Mac to forward an unaddressed
  message on the backend's say-so (see Status).
- A burst of small messages ("ok" / "thai then" / "friday?") gets one answer,
  once the person has finished; "sounds good, thanks" gets none.
- It knows the non-sensitive things about members - their name, what they
  like, the city they live around, and the everyday things they have told it
  ("I drive a red Mini") - from what they already told it in private, judged
  by meaning; nothing sensitive (health, money, legal, relationships, exact
  addresses, credentials, anything said to be private) reaches the room, and
  asked for such a thing it says that is theirs to share. Operator's decision,
  2026-08-28, widening the first cut's "tastes only": "non sensitive memory
  data should be known automatically in group chats where all users are
  approved" - the first live turn could not say the operator's own name.
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
  never widen it), `IMESSAGE_BRIDGE_ADDRESSES` (this account's own email and
  number - what a mention is matched on) and, optionally,
  `IMESSAGE_BRIDGE_DISPLAY_NAME` (a name to answer to as a word).
- `incoming_messages` keeps `room_name IS NULL` for one-to-one rows and adds the
  allowlisted-group branch. Every allowlisted sender's row in a listed room is
  returned, marked with how it addressed the account or `addressed_by: ""`
  when it did not (the first cut forwarded addressed rows only; the operator
  widened it the same day). Addressed means: reply-thread (its
  `thread_originator_guid` is a from-me guid in that chat - chat.db is the
  ledger, the bridge stays stateless), mention (the handle stored after
  `__kIMMentionConfirmedMention` in `attributedBody` is one of the bridge's
  addresses - measured 2026-08-28: a mention rendered "Scout" carried
  `deep-matter@agentmail.to`, so the name each person saved the contact
  under does not matter), name (whole word, only when a display name is set). Payload gains
  `chat_guid`, `chat_identifier`, `chat_name`, `participants` (from
  `chat_handle_join`), `addressed_by`.
- Sending to a group uses the `chat id "iMessage;+;chatNNN"` AppleScript form
  (verified to resolve on this Mac, 2026-08-28); `check_recipient` accepts an
  allowlisted chat target; guid readback is scoped per chat.

### Worker - `backend/workers/imessage_chat.py`
- A room's message (`chat_identifier` on the payload) takes its own path,
  `_handle_room_message`: an unaddressed one is *observed* - posted to
  `POST /chat/observe`, which stores it under the group's conversation as a
  turn with no reply and runs the memory agent on it with the roster, so the
  next answered turn's history and the group's memory hold what the room
  said; an addressed one is answered. The speaker and every participant are resolved through
  `_account_for` (the subscriber allowlist); any unresolved participant → the
  row is finished silently and the operator gets one text per room per day
  (`OPERATOR_ALERT_PHONE`, dedup in Redis `imessage:chat:room_alert:{digest}`;
  nothing about the strangers is sent).
- Admission at the bridge (2026-09-02): with `IMESSAGE_BRIDGE_GROUPS=auto`
  the Mac reads any group whose every member is on its allowlist (the
  environment's recipients plus the grants AniOS makes at approval), so a
  room of approved people works the moment the account is added to it; a
  room with one stranger in it is scanned past and nothing said there leaves
  the Mac. Listed chat ids still count beside `auto`. The worker's own rule
  stands on top: every participant must resolve to an approved account, or
  the room is silent and the operator is told once. Approval in deep-matter
  is therefore the only step: it grants the number on the bridge and makes
  the person answerable in any room made of approved people.
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
- Nothing addressed to the assistant is lost to a restart: a turn that finds
  the backend away (connection refused, 502-504) or a room whose database
  cannot be reached is parked in Redis (`imessage:chat:parked`) with its
  guid left open, retried at the start of every poll for
  `IMESSAGE_CHAT_RETRY_MINUTES` (10), told once after
  `IMESSAGE_CHAT_RETRY_NOTICE_SECONDS` (60) that the answer is coming, and
  only then given the fixed apology. Operator's question, 2026-08-28.
- Burst judgement (`_collect`): every addressed text fragment - room or
  one-to-one - is appended to a pending record keyed by the reply address, and
  `POST /chat/readiness` (`services/readiness.py`, routing model, schema
  `{complete, needs_reply, accepts_offer, reason}`,
  `prompts/routing/readiness.md`) is asked
  whether the person has finished and whether an answer is wanted. Not finished
  → keep listening; finished and wanted → one turn for the joined fragments;
  finished and unwanted ("thanks!") → no bubble - except that a reply to the
  assistant's own bubble or a mention is a deliberate address and is always
  answered ("we are a groupie!!" got silence on the first live day); for those
  the judgement decides completeness only. A pending burst older than
  `IMESSAGE_CHAT_BURST_CAP_SECONDS` (45 s) is answered by the next poll. The
  judgement fails open to answering; `IMESSAGE_CHAT_READINESS_ENABLED=false`
  restores answer-every-message.
- Positive tapbacks reuse that judgement without widening what the bridge can
  read. Each sent Scout text bubble's GUID, body, account, destination, and room
  context are held in a bounded seven-day Redis ledger. The worker calls
  `read_reactions_by_guid` only with those GUIDs; ❤️/👍 becomes an ordinary
  contextual "yes, do that" turn only when `accepts_offer=true`. Choices, open
  questions, completed actions, answers, and social bubbles remain silent. A
  Redis `SET NX` receipt consumes an accepted reaction once. Judge outage fails
  closed and retries; it never guesses an external action. The bridge returns
  a reactor address only when it is allowlisted. A room acceptance then maps
  that address to a current member and replaces `speaker_user_id`; a missing,
  unknown, or departed reactor is refused rather than borrowing the original
  speaker's identity.

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
  store to a group prompt - profile name (or the account's username as a first
  name, "ani.mallya" → "Ani", when no name is on record; the first live turn
  addressed the operator as "Member 2"), Scout interest labels (at most 8),
  the city-level home locality, and up to 6 remembered statements: first the
  member's memories nearest the message (the same relevance search a
  one-to-one turn runs, so an older recipe is found for a recipe question),
  then the recent ones through Scout's own `PersonalContextReader` (approved
  facts and recent semantic memories, leaving out visual-analysis memories - descriptions of generated
  pictures are not facts about anyone; secrets, card numbers and personal
  medical/financial/legal framing screened deterministically; bounded) and
  then judged by meaning by
  `backend/memory/share_screen.py` (`prompts/memory/share_in_group.md`, routing
  model, schema; verdicts cached per statement; fails closed - without a
  judgement nothing is shared). A member whose profile cannot be read stays on
  the roster as "Member n".
- One bounded exception, for the turn only: "here", "near me", "tomorrow" in
  a room are the *speaker's* - the group has no home place - so the speaker's
  own primary locality (city-level, the same `_primary_place` a one-to-one
  turn uses) grounds their turn's place and clock. It is used to answer and
  to route (weather, nearby), never stated as a fact about them; the first
  live group turn answered "weather here today?" for no place at all
  (2026-08-28). Sweep journey "group: weather here is the speaker's here".
- The follow-up resolver's reading (subject and restatement) is rendered
  last in the turn context for every branch, not only handed to the router
  and the search rounds: in a room the roster pulls the reply toward the
  members' interests, and "what do you think we'd like" after ice cream was
  answered with nights out (2026-08-28).
- `prompts/reply/imessage_group.md`, appended after `imessage_style` when
  `channel == "imessage_group"`: the chat's name, who is speaking, each member's
  likes, home area and everyday statements, and the rule that everything else
  about a member - and anything sensitive - is theirs to share.

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

### The group's own Scout
- A group's Scout runs on the group's interest rows. When a group is
  provisioned and whenever its membership changes, the interests two or more
  members hold are written to the group with provenance `shared_by_members`
  and the ones no longer shared are removed (`backend/groups/shared_interests.py`);
  what the room adds itself carries its own provenance and is never touched.
  A home locality is seeded only when every member's primary locality agrees;
  a room with members in two cities is asked where. The sweep's schedule is
  set in the room the way a person sets theirs ("scout, run weekly on
  Sundays"). Operator's intent, 2026-08-28: schedules on common interests and
  shared cooking.

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
| Sweep journeys, docs, diagrams | built; eight group journeys; deploy #19 (cecb2f6, 2026-08-28) ran the whole sweep green with no gaps |
| Pending-question trigger | not built - needs a scoped expectation for one member's next otherwise-unaddressed message |
| Positive tapback trigger | candidate built 2026-08-29; bridge/worker/API 179/179 focused tests on the Mac (178 passed plus one expected macOS-only skip on Linux), readiness 33/33 and offered-search routing 1/1 on the real model; live Mac acceptance and deploy pending |
| Manual acceptance on the Mac | 2026-08-28 in the operator's group "Groupie" (`chat308729799386740866`, both members approved): @mention forwarded, group provisioned, answered in the chat in 22 s; tap-and-hold reply forwarded and answered (late - the burst judge's fault, fixed); the weather answer was for "Here, Somalia" (fixed: the tool refuses a non-place, a room runs on the speaker's place). Re-test after deploy dd3cc92e: mention, thread reply, "thanks!" |
