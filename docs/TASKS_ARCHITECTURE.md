# Scheduled tasks: "schedule anything" from a text

Status: design approved by the operator 2026-08-22, implementation in
progress. Scout stays as it is until this is proven; it becomes one *kind*
of task afterwards.

## The one sentence

A scheduled task is a user's own instruction, run later as an ordinary
conversation turn under their identity, with its reply delivered to
wherever they talk to AniOS. Nothing conversational is reimplemented: the
turn is the same `/chat` path the browser and the iMessage worker use -
memory, search, weather, images, diagrams, all of it.

## Why this shape

Three rules of this repository decide it:

- **Intent is model-decided, never pattern-matched.** "Remind me every
  weekday at 7 to check the Spark temps" is understood by the router as a
  native tool call (`schedule_task`) with the instruction, cadence, and
  time as fields - the same mechanism that decides to search or draw. No
  syntax, no keywords, no "/remind". Over iMessage it is just a text.
- **Reuse the machinery that already survived production.** Scout's run
  queue (leases, exactly-once slots, heartbeats, retry with a deadline) and
  its cadence math (`discovery/schedule.py`, DST-correct) are generic; only
  their names say "discovery". Tasks get a sibling queue with the same
  guarantees rather than a second invention.
- **Channels are adapters.** Identity (who is this address), delivery
  (bubbles, images), and ingestion are a `Channel` contract. iMessage is
  the first implementation - it exists today as the worker - and WhatsApp
  or OpenClaw implement the same contract without the scheduler learning
  anything new.

## Data

`scheduled_tasks` - one row per standing instruction:
user_id, instruction (the user's words, encrypted at rest like every other
user text), cadence (`once` | `daily` | `weekdays` | `weekly`), hour,
minute, weekday, on_date (for `once`), timezone (from the user's locality,
never guessed - the existing Scout rule), channel, conversation_id (every
task owns a conversation thread, so web users see each run's reply in the
sidebar like any other conversation), next_run_at, enabled, last_run_at,
last_status.

`scheduled_task_runs` - one row per fired slot: task_id, scheduled_for
(unique per task - exactly-once), status queued/running/ready/delivered/
failed/cancelled, worker lease, attempt_count, output (the reply text),
error_code, timestamps. Mirrors `discovery_runs` so the worker loop is a
copy of a known-good shape, not a new one.

## Scheduling from conversation

The router gains two built-ins, declared like every other:

- `schedule_task(instruction, cadence, hour, minute, weekday?, on_date?)` -
  the model rewrites the request as a self-contained instruction ("text me
  Arlington's weather") and resolves "tomorrow morning" / "every weekday at
  7" into fields against today's date. Timezone comes from the profile; with
  none, the reply asks for the place first (existing pattern).
- `manage_tasks(operation: list | cancel | pause | resume, which?)` - the
  model names the task by description; the handler matches semantically
  against the user's tasks (a model judgement, not string matching).

The conversation service executes either and replies in its own words with
the confirmation and the first run time in local time. Gated functionally:
real phrasings must route to the right tool with the right fields.

## Running

The discovery worker process hosts a second loop (like the iMessage chat
loop): enqueue due tasks -> claim with a lease -> run the instruction
through `/chat` as the user (bearer, task's conversation_id, metadata
channel + scheduled_task) -> deliver the TurnResult through the user's
channel -> mark delivered -> advance next_run_at, or disable a `once`.
A scheduled turn carries its own prompt block (`prompts/reply/
scheduled_task.md`): "this is a task the person set up earlier, running
now - do it, don't ask whether they meant it", gated against the real
reply model.

## Delivery

`Channel.deliver(user_id, TurnResult)`: iMessage = the worker's existing
bubble-and-image path to the user's subscribed address; web = the reply is
already in the task's conversation thread (a notification surface comes
later). Digests, reminders, weather, "check whether the cable is in stock
at Rockville and tell me" - all the same path.

## Scout afterwards

Scout's sweep is a task whose runner is `DiscoveryRunner` instead of a
chat turn. Its schedule, subscribers, and digest delivery map onto the
task tables one for one. That migration is a separate, later change.

## Out of scope now

Cron expressions, multiple times per day, task chaining, editing an
instruction in place (cancel and re-create is the v1), WhatsApp/OpenClaw
adapters (the contract is defined so they drop in).

## Status (2026-08-22): built, v1

What exists, and where:

- Router: `schedule_task` and `manage_tasks` built-ins in
  `backend/services/main_action_selector.py` (`ScheduleTaskAction`,
  `ManageTasksAction`). Gated on the live router in
  `backend/tests/functional/test_scheduled_task_behaviour.py` - both the
  DeepSeek router passes all routing cases.
- Bookkeeping: `ConversationService._apply_task_action` saves, lists,
  cancels, pauses, resumes; the result rides into the ordinary reply as
  `context["task_outcome"]` and the model words the confirmation from it
  (`prompts/reply/task_outcome.md`). Which task "the weather one" means is
  the model's call (`backend/tasks/picker.py`, `prompts/tasks/pick.md`);
  the picker is handed the assistant's previous reply so "this" means
  what was just discussed, and is offered "none" so a referent that is
  not a task - Scout's own schedule, a setting - moves nothing (2026-08-26:
  "adjust this to daily at 3pm", said about Scout, moved a stretch
  reminder). The same previous reply reaches the memory proposal agent,
  whose `schedule` field is Scout's sweep cadence and never a reminder's
  time.
  Timezone comes from the primary locality; none means the reply asks for
  the city and nothing is saved.
- Storage: `backend/models/scheduled_task.py`, migration
  `20260822_0005` (additive, applied), `backend/tasks/repository.py`.
- Runner: `backend/workers/task_runner.py`, a loop in the discovery worker
  process (`SCHEDULED_TASKS_ENABLED`, `SCHEDULED_TASKS_POLL_SECONDS`,
  `SCHEDULED_TASK_LEASE_SECONDS`). A firing posts the instruction to
  `/chat` on the task's own conversation with `metadata.scheduled_task`,
  which appends `prompts/reply/scheduled_task.md`; iMessage tasks deliver
  through the chat worker's bubble path to the subscribed address, web
  tasks keep their output on the run row.
- Wording: `backend/tasks/describe.py` renders cadence and next run in the
  person's zone for both the picker and the reply context.

- Scout's own cadence: `scout_schedule` (`backend/tools/scout_schedule.py`),
  a separate row since 2026-08-26 so the router chooses between two named
  things. With only `manage_tasks` offered, "change the schedule to
  9:25pm" after talk of Scout was read as a task reschedule (measured
  2026-08-23; no wording of the description moved it), and on 2026-08-26
  "adjust this to daily at 3pm", said about Scout, moved a stretch
  reminder. The action lands in `ConversationService._apply_scout_schedule`
  -> `discovery_runs.upsert_schedule` in the primary locality's timezone,
  and rides into the reply as `context["scout_schedule_outcomes"]`, kept
  apart from task outcomes so the sweep is never reported as a reminder.

- Undo: every cancel, reschedule, pause, resume, and Scout schedule
  change is written to `scheduled_task_changes` with what it replaced
  (snapshots sealed like the instruction; migration `20260826_0010`).
  `manage_tasks(operation="undo")` puts the latest one back: a cancelled
  task is re-created under its old id from its snapshot, a moved one moves
  back, Scout's schedule returns to what it was or to none. The undo is
  recorded but never undoable, so "undo" twice walks back two changes.
  Added 2026-08-26 after a misread referent moved a reminder the person
  could not put back.
- Automatic memory saves are on the same record: each saver returns a
  receipt (`kind`, id or fact keys, a short value) written as a
  `memory`/`save` change, and undo takes it back via
  `ConversationService._forget_saved` (2026-08-27).
- One writer for Scout's schedule: the memory proposal agent no longer has
  a `schedule` field; `scout_schedule` is the only path that changes
  `discovery_schedules` from conversation.
- Every turn saves a trace with the conversation row
  (`extra_data["trace"]`: route, picker input/output, proposals saved,
  outcomes, search) - `python -m backend.cli.explain_turn --user <id>`
  prints the last turns decrypted with it.

Not yet: a web surface for runs (output is stored, nothing shows it), the
Scout-as-task migration, WhatsApp/OpenClaw adapters, edit-in-place.

### Verified end to end (2026-08-22)

A one-time task scheduled through `/chat` as the operator ("at 2:42pm today
text me a one-line hello") was saved, fired, and delivered to the phone.
It fired early: the router dated "today" in 2024, from its training era,
because nothing told it when now is. Fixed two ways - the router is now
handed the current date, time, and weekday in the primary locality zone
(`ConversationService._local_now` -> `select(local_now=...)`), and a stated
once-date already in the past is discarded in favour of the time rule
(`_once_date`). Both gated: `test_tomorrow_resolves_against_the_persons_clock`
on the DeepSeek router, and the structural repair test.

## Tools, skills, and what the person sees (2026-08-22, second pass)

**Folders.** Built-in tools now live one module each under `backend/tools/`
(row + parser; `registry.py` is the only list) and the router, the reply
prompt's capability list, the web status line, and the iMessage waiting
bubble all read from there. Skills live under `backend/skills/` (packs on
disk, the taught-skill store, skills-as-router-tools) with the shipped
packs in the top-level `skills/` folder. Adding a Google Drive or Instagram
tool is a module in `backend/tools/` (or an MCP server, which needs nothing
here); adding a routine everyone gets is a markdown file in `skills/`.

**Skills.** A skill is a named instruction the model invokes by meaning:
each one is offered to the router as its own tool (`skill__<slug>`), so
"brief me" reaches "morning brief" through its description. Invoking one
routes the skill's instruction again with the ordinary tools (search,
weather, images...) and appends `prompts/reply/skill_invoked.md` so the
reply carries it out. Teaching one ("when I say X, do Y") is `save_skill`;
listing and deleting is `manage_skills`; both report through
`prompts/reply/skill_outcome.md`. A skill can be scheduled like anything
else ("every weekday at 7, run my morning brief"). Tables: `user_skills`
(migration `20260822_0006`, applied). Gates:
`functional/test_skills_behaviour.py`.

**Status.** The turn emits one `action` SSE event after routing: the
capability label, the one detail worth showing, and a playful waiting line
with an emoji from the tool's own pool. The web UI shows the waiting line
while the answer streams and the plain record afterwards; the iMessage
worker uses it as the "still working" bubble instead of a random
pleasantry. Skills and tasks are visible and removable in the new
Automations panel (`/api/v1/automations/{user_id}`).

## A set of tasks, and a change that did not happen (2026-09-02)

- "Delete the paused ones" names a set; `pick_many` returns every id the
  words cover. Its answer budget is sized to the ids offered (64 + 40 per
  id): saved items carry UUIDs, and a fixed 64 held one and not two, so the
  call truncated, parsed as nothing, and the outcome was `not_found` while
  the reply said both were deleted (the deploy sweep, kept turn). Measured
  after the fix: the set over real UUIDs with the live hint, 3/3.
- A `not_found` outcome is rendered as flatly as "nothing to undo": NO task
  was cancelled, paused, resumed, or moved this turn. Held on the real reply
  model, 3/3: the reply never reports a deletion the record does not carry.

## What a firing is not allowed to do (2026-08-22, audit pass)

An audit of the firing path, prompted by a reminder that answered "I can't
control a stove", found the defects below. All are fixed and gated; the
numbers are the audit's own ranking.

**A firing could reschedule or cancel itself (worst).** `metadata
["scheduled_task"]` was read in exactly one place - to append a prompt
block. Nothing was gated. A stored instruction reads exactly like a
request to schedule ("remind me every morning to take my meds"), so the
router called `schedule_task` again: the person got a confirmation instead
of their reminder and a second task appeared, then four. `manage_tasks`
was worse - the picker returns the single candidate without asking the
model, so a hard delete followed. Fixed at two walls: `AUTOMATION_TOOLS`
(`backend/tools/registry.py`) are withheld from the router when the turn
is unattended, and `_task_turn_context` refuses to write on a fired turn
whatever the router said. Gated live on the DeepSeek router with five plausible
instructions, plus the converse - the same words typed by a person still
schedule.

**Silence was the default failure.** Any exception or empty reply closed
the run `failed` and sent nothing; `attempt_count` was incremented and
never read; a `once` task was already disabled, so a model timeout meant
the reminder simply never arrived and nothing said so. Now: a failure with
attempts left is requeued (`finish` returns `requeued`/`failed`/`not_mine`),
and a run finally given up on sends one short line on its own channel.

**A stale slot fired at the wrong hour.** A worker down from 3am to 11pm
delivered the 7am briefing at 11pm. Slots more than `SCHEDULED_TASK_STALE_
SECONDS` (1h) late are skipped, the task having already advanced.

**The lease was never renewed.** `renew_lease` existed and no one called
it, so a slow generation could lapse its own lease and be re-claimed and
re-delivered by a second worker. `TaskRunner` now renews while the turn
runs, and `finish` refuses a run another worker holds.

**Memory was written on every firing.** The instruction was classified and
persisted once per firing - the same fact 365 times a year, unattended.
Scheduled turns are exempt; the person's original setup turn was
classified normally.

**A deck scheduled weekly delivered "follow job <uuid> in Presentations
while we keep chatting"** to a phone, forever, with no deck. Delegation is
not offered to a firing.

**A once-date could be armed in the past.** `_once_date` compared dates but
not times, so at 6:05pm "remind me at 5" armed today's 5pm slot and fired
within thirty seconds. It now requires the whole instant to be ahead.

Known and accepted: a firing's first turn has no thread history, so an
instruction naming an earlier conversation has nothing to resolve against -
the reply block handles it by writing the useful version rather than
reporting the gap. Carrying the creating conversation's history into the
firing is the next improvement.


## Quiet firings — 2026-08-25

A conditional task ("message me if search credits are low", "tell me when
the price is under 40") fires on its schedule whether or not the condition
holds. The reply prompt for scheduled turns (`prompts/reply/scheduled_task.md`)
tells the model to answer with exactly `NOTHING_TO_REPORT` when it does not,
and `TaskRunner._deliver` finishes such a run as `quiet` without sending
(`backend/tasks/quiet.py`). The token is a single fixed word rather than a
judgement about the prose, so a real message can never be mistaken for
silence. `test_scheduled_quiet_behaviour.py` holds the model to both halves
against the real reply model: silence at 200 of 1,000 credits, the number at
993.

The first such task: the operator's "message me each morning if search
credits are below 100", which reads the internet server's `search_credits`
tool - the key's own usage from the provider, offered to operators only.

## Time facts, after the trivia morning (2026-09-03)

The morning after the group's Wednesday trivia, the daily chess tip wished
them "fun at trivia later", and asked about it the reply said the reminder
was "still sitting there at 6pm today". Three rules now hold, in code:

- The system prompt states the date, the weekday and the local time in the
  person's zone, not the date alone (`graph._build_system_prompt`).
- A memory is saved with its relative day words written as the dates they
  meant (`backend/core/relative_days.py`), and every recalled memory carries
  the day it was noted (`graph._dated_memory`).
- A one-off task that has fired is described as "(done - it has fired)",
  never "(paused)" (`backend/tasks/describe.py`).

Pinned by `test_relative_days.py`, `test_task_describe.py`, and
`functional/test_time_awareness_behaviour.py` on the real reply model.
