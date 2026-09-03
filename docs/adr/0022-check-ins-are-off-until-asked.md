# 0022 - Check-ins are off until asked, and asking is a skill

Date: 2026-09-02

## Status

Accepted.

## Context

ADR 0019 made a check-in a scheduled task the assistant arms itself after a
judgement on what the person mentioned. It worked as designed and people
did not like it: being asked "how did the offer on the car go?" by something
they never asked to follow them felt like being watched. The operator's rule
on 2026-09-02: off by default, on request.

## Decision

- Nothing about a check-in runs for anyone who has not asked. The switch is
  one preference on the profile (`preferences.check_ins`), read before the
  judgement starts; unreadable means off.
- Asking is a skill. The shipped pack `skills/check-ins.md` reaches the
  `manage_check_ins` tool, which the router may also choose directly, with
  four modes: on, off (which also drops what is waiting), once for one thing
  by name, and status.
- A once goes through the same `arm_check_in` as the judgement, under the
  same limits. The limits stay in code; the pack only reaches them.
- The outcome is reported through the scheduled-task record so the reply
  states what is now set, in the person's terms, never as an automation.

## Consequences

- The judgement, its prompt, and the limits are unchanged; they simply do
  not run until asked. The sweep now proves the off state as well as the on.
- A room opts in under its own id, so one member's ask does not change
  another's one-to-one setting.
- "Stop" is total: the habit and the waiting ones. A person who wants to
  keep one can set it again by name.
