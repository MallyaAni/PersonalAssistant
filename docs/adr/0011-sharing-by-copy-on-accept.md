# ADR 0011: Sharing by copy on accept

- Status: Accepted, not yet implemented
- Date: 2026-08-02

## Context

Invited accounts made a second person real ([ADR 0010](0010-invite-identity-and-revocable-sessions.md)),
and the first thing two people want is to give each other something — a family
recipe being the case that prompted this.

Every durable record in AniOS is owned by exactly one `user_id`. That invariant
is not a convention; it is load-bearing in **133 places** across the backend,
**33 of them in deletion and export alone**. Sharing has to be designed against
that number rather than around it.

There is also direct evidence of what happens when a subsystem escapes a global
invariant. Ambient discovery grew outside the memory subsystem, and the
consequence was not theoretical: a full "forget me" silently left behind where
the user lived, what they liked, everything they had been shown, and other
people's phone numbers. That was one subsystem missing from one code path.

## Decision

**Sharing copies on accept. It never grants access into someone else's store.**

Sharing an item mints an expiring one-time share code, exactly as an account
invitation does. The recipient opens it, sees a preview of what they are about
to take, and accepts. Acceptance writes a **new record owned by the recipient**,
carrying provenance naming who shared it and when.

The shared copy is a snapshot, not a live view. The sharer's later edits do not
propagate; sending an updated version is a new share.

Provenance is retained permanently and is user-visible, because for this
category of content the origin is part of the value. "Grandmother's lasagna" is
a different thing from a recipe found on the internet, and the system should be
able to say which it holds.

### What this buys

- **Every existing query, deletion, and export path stays correct, untouched.**
  No read becomes `WHERE user_id = me OR shared_with_me(...)`, so there are not
  133 opportunities to leak or to silently omit.
- **"Forget me" stays honest.** Deleting an account cannot reach into another
  person's data, and cannot silently break something they were given.
- **It fits the approval model already in place.** A shared item arrives as a
  proposal and becomes a fact only when the recipient accepts, which is exactly
  how memory capture from conversation already works.
- **Search works without a second place to look.** An accepted item lands in the
  recipient's ordinary memory and artifact stores, so asking "what was mum's
  lasagna recipe" finds it. A "shared with me" silo would be a worse product as
  well as a worse design.

### From the recipient's side

The flow is deliberately the same shape as an account invitation, because that
machinery exists, is tested, and is already understood by anyone who has joined:

1. the sharer picks one item and gets a link or code;
2. they send it however they like — iMessage, if the bridge is running;
3. the recipient sees **a preview before accepting**, so nothing enters their
   memory sight-unseen;
4. accepting files it away as theirs, attributed.

Sharing is **per item and explicit**. There is no "share my recipes" folder
operation, because memory holds sensitive things and a sweep is how the wrong
one leaves. A share code that has not been accepted can be withdrawn.

The recipient does not have to be an AniOS user yet: a share code can accompany
a registration invitation, so the first thing a new person receives is the thing
they were actually sent.

## Consequences

- **Acceptance cannot be undone by the sharer.** Once someone has the recipe, it
  is theirs, in the same way an already-delivered message is. The interface must
  not offer an "unshare" that does not exist. Withdrawal applies only before
  acceptance.
- Storage is duplicated per recipient. For hand-shared items this is negligible,
  and it is the cost of the ownership invariant holding.
- A correction after sharing requires re-sharing. Acceptable for recipes;
  wrong for anything that must stay current.
- **Per-user envelope encryption stays cheap.** ADR 0010 lists it as planned.
  Under copy-on-accept, sharing is a decrypt-and-re-encrypt at one boundary.
  Under a live grant it would require cross-user key access on every read, which
  is a substantially harder system to get right.

## Rejected: access-control grants

A `shared_items` grant table consulted by every read is the conventional answer
and was rejected. It requires editing 133 query sites; each one missed is either
a disclosure or an invisible omission, and the discovery deletion bug is direct
evidence that this project does miss them. It also makes deletion ambiguous —
whether removing an owner's record should remove a reader's access to something
they were given — and turns per-user encryption into a key-sharing problem.

## Rejected: live synchronized copies

Keeping both sides in step reopens the ownership question the copy exists to
settle: whose version is authoritative, and what happens to the other when one
account is deleted. For hand-shared content, a snapshot is also the more honest
artifact — it is the version that person actually gave you.

## Where a live grant is right, and already exists

Ambient discovery's subscription feed is the counter-example worth preserving. A
subscriber holds a token addressing a read-only view, revocable by rotating the
token, and no row in anyone's private store. If a shared, always-current family
collection is ever wanted, that is the pattern to extend — a shared space with
its own feed — rather than threading permissions through everyone's private
tables.
