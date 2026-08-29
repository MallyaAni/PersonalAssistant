# ADR 0016: A group is an account

- Status: Accepted; implemented and deployed 2026-08-28 (first in 5c634e8; current in cecb2f6 - unit 2059, routing 7/7, the sweep green with all eight group journeys, harness green). Live in the operator's group "Groupie" the same day: mention, thread reply, name, everyday facts, weather for the speaker's city; the reminder-on-the-speaker's-clock fix is the last live finding and shipped in cecb2f6.
- Date: 2026-08-28

## Context

The operator wants to add the assistant to an iMessage group with one or more
approved users and have that group behave as its own session: shared memory
(recipes tried together, plans, Scout sweeps on shared interests, digests
posted into the thread), each member's tastes used from their own memory
without repeating private facts, and statements like "Jen and I" or "us"
attributed to the right people.

Every durable record in AniOS is owned by exactly one `user_id` — the invariant
[ADR 0011](0011-sharing-by-copy-on-accept.md) counted at 133 sites and chose to
keep rather than dilute with `OR shared_with_me` reads. Conversation history is
keyed by `(conversation_id, user_id)`; the Scout schedule is unique per user;
subscribers, tasks, skills and the search budget are per user. The iMessage
bridge maps one sender address to one account and, by documented posture
(`docs/SECURITY.md`), reads no group chat at all: "no sender's prompt carries
another account's memory."

A group session therefore needs an owner that the existing machinery already
understands, a boundary that keeps other members' private memory out of the
group's prompt, and a rule for whose store a statement made in the group goes to.

## Decision

**A group is an account.** Each approved group gets its own `user_id` of the
form `group:<slug>` — a real `user_accounts` row that cannot log in — and a
membership table listing the approved member accounts. Everything the group
learns or schedules is owned by that account, so history, working memory,
summaries, Scout interests, locality, schedule, subscribers, tasks, skills and
the search allowance work unchanged.

A turn in the group **runs as the group account**, with the speaker carried in
the turn's metadata and rendered in the transcript ("Ani: …"). The prompt gets
the group's own memory (the ordinary per-user path) plus a **read-only
projection of members' tastes** — interests, likes, city-level home, preferred
name — through an allowlist door modelled on `backend/discovery/personal_context.py`.
Nothing else from a member's store can reach a group prompt, by construction.

**Writes go per owner, decided by meaning.** The memory proposal agent is handed
the roster and returns, for each proposal, whom it is *about* — the speaker, a
named member, or the group — constrained by schema to those values (no
patterns). A pure policy then maps kind × about to owners: tastes about a named
member go to that member's store with provenance (`stated_by`, `in_group`);
personal facts go to the speaker's store when about the speaker and to the
group's when about the group, and **never to another member on someone else's
word**; a preferred name or reply style is never written from a group turn.

**The bridge decides what is addressed to the assistant**, on the Mac, by shape:
an inline reply anywhere in a thread anchored on one of the assistant's own
bubbles, an @mention or the assistant's name in a top-level message, the next
message from a person the assistant asked something, and a tapback on its
bubble. Whether a burst of small messages is complete, and whether it calls for
a reply, is judged by the routing model with a schema — not by a timer. Nothing
else in a group leaves the Mac.

**Membership is all-or-nothing and automatic.** A group is provisioned on the
first addressed message when every participant resolves to an approved account;
otherwise the assistant stays silent there and the operator is told once.

Digests and reminders for the group are delivered **into the group chat**
through a subscriber whose address is the chat itself.

## Decision widened, 2026-08-28 (same day)

The first cut projected members' tastes only. After the first live turn
could not say the operator's own name, the operator decided: "non sensitive
memory data should be known automatically in group chats where all users
are approved". A member's name, likes, home area and everyday remembered
statements now reach the room; what is sensitive is judged by meaning
(`backend/memory/share_screen.py`) and never does. The ownership rule is
unchanged: nothing is written into another member's memory on someone
else's word.

Later the same day, for schedules on common interests: a group's Scout is
seeded from the interests two or more members share
(`backend/groups/shared_interests.py`), and a member's memories are read
by relevance to the message, not only by recency.

Later still: the operator decided the assistant "must be reading every
message for context". Every allowlisted member's message in a listed room
now leaves the Mac and is stored under the group's conversation (answered
turns and observed ones alike), and the memory agent reads observed messages
too. Only an addressed message is answered.

## Consequences

- One guest search allowance per group, shared by every member's asks there.
- "Forget me" for a member removes their own rows, including tastes attributed
  to them from a group; the group's store is deleted with the group.
- The operator's own hand-typed bubbles in a group are indistinguishable from
  the assistant's for inline replies while the Mac's account is the assistant's;
  a dedicated Apple ID removes that.
- `group:<slug>` deliberately bypasses `normalize_user_id`; no route may issue it
  a browser session, and new user-id validation must be checked against it.
- The transcript gains speaker names in five renderers (reply assembly, the
  follow-up resolver, the router's history window, the coordinator's digest,
  the summary digest).

## Rejected

- **A merged per-turn memory of all members** — reads across stores at turn time
  are exactly what ADR 0011 rejected; the tastes door is narrow, typed and the
  only door.
- **Reading all group chatter and letting the model decide when to speak** —
  contradicts the posture that unaddressed text never leaves the Mac.
- **A time window after the assistant's reply as an implicit trigger** — a
  person can answer at any time; threads are the natural, time-free anchor.
- **A quiet-gap timer to coalesce bursts** — replaced by a semantic completeness
  judgement, which also stops replies to every "ok".
