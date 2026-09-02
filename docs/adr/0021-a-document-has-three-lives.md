# 0021 - A document has three lives

Date: 2026-09-02. Status: accepted.

## Context

Documents shared with the assistant had no age: an itinerary for a trip in
October would rank against every later document forever, and "when is the
Pompeii excursion" would be answered from it a year on. The obvious rule -
delete after the trip - throws away "what hotel did we stay at", which is a
real question two years later.

## Decision

Retention treats a document as three things with three lifetimes:

- **The file** is never deleted on a date. Deletion is a human act.
- **Its weight in retrieval** retires after the event. The digest step reads
  the last date a document is about; a grace period later it is archived,
  and archived documents are read only when nothing current answers or when
  the person pinned the document. The reply is told a passage is archived and
  its last date.
- **Its facts** split into durable (saved as before) and dated (saved with an
  expiry on the same day, leaving through memory's existing purge).

## Consequences

- An undated document (a lease, a recipe) never archives; the digest returns
  no date for it.
- The date is read by a model. It is measured on an itinerary and a recipe
  and held at three reps, like every judgement here.
- A question about the past reaches an archived document without the person
  doing anything; a question about the present is never answered from one
  while a current document can answer it.
