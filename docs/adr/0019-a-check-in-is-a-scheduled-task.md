# 0019 - A check-in is a scheduled task, not a new kind of thing

Date: 2026-08-30

## Status

Accepted.

## Context

The operator asked for the assistant to come back to things on its own: "how
was the visit to national harbor?" after an outing, and an occasional check on
how they are doing when they had said they were unwell.

Neither is a request. The router fires on what a person asks for, so nothing on
the existing path would ever notice either one.

The obvious shape for this is a new subsystem: a table of things the person
mentioned, a worker that sweeps it, a delivery path, a way to cancel one. All
four already exist for scheduled tasks, and a second copy of each would be a
second thing to keep correct - a second delivery path to fix when a channel
changes, a second cancel vocabulary for the person to learn.

## Decision

A check-in is an ordinary one-off scheduled task, distinguished by a `kind`
column - `checkin:event` or `checkin:wellbeing` against a reminder's
`reminder` - and nothing else. Only the noticing is new.

`scheduled_tasks` already stores a `once` cadence with a calendar day, a local
hour and a timezone. The task runner already claims a due run under a lease,
converses in the task's own thread, and delivers per channel. The picker
already resolves "cancel the national harbor one" against the person's own
words. A check-in inherits all of it by being one.

The judgement that arms a check-in is separate from the memory proposal agent,
even though both read every message. That agent had a schedule field once and
it was removed on 2026-08-26, after "send another don tito reminder at 7" was
captured as Scout's standing cadence and applied. Cadence has one writer for
that reason. Adding a second timing judgement to the same call would repeat the
mistake, and the same agent's own comments record that added prompt text
crowded out ordinary capture - measured again on 2026-08-30, where 99 words
about instructions dropped a plain fact from 4/4 to 1/4.

Every limit that keeps check-ins civil is in code, not in the prompt: how many
may wait, how far apart, in which threads, at which hours. The judgement is
free to say yes as often as it likes and still arm nothing.

## Consequences

A check-in appears in "what reminders do I have?" and is cancelled the same way
as any other. That is intended: a thing the assistant armed on its own should
be at least as easy to call off as one the person asked for.

Group rooms arm nothing. Asking a room how one member's health is would put a
fact about them in front of everyone, and the group thread already shows
everyone what everyone said. If group event check-ins are wanted later, they
are a per-kind rule in `checkin_arming`, not a new mechanism.

`kind` defaults to `reminder` at the column level, so any writer that does not
know about check-ins still produces a reminder rather than a null.

A person who has already been checked on three times without those firing gets
nothing further until some of them do. That is the cap doing its job, and the
trace says `too_many_waiting` when it happens.
