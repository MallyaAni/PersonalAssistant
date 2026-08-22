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
  Spark reply model and the production 4B router pass all routing cases.
- Bookkeeping: `ConversationService._apply_task_action` saves, lists,
  cancels, pauses, resumes; the result rides into the ordinary reply as
  `context["task_outcome"]` and the model words the confirmation from it
  (`prompts/reply/task_outcome.md`). Which task "the weather one" means is
  the model's call (`backend/tasks/picker.py`, `prompts/tasks/pick.md`).
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
on the Spark reply model and the 4B router, and the structural repair test.
