# Durable runs: an agent's loop that outlives a turn

Status: live. The worker loop is on (`AGENT_RUNS_ENABLED=true` on
spark1) and the kinds registered in `backend/workers/run_worker.py` create
runs in production - a turn that runs out of clock hands its remainder to
one, and the review agents use them for work that outlives a request. Built
and unit-verified 2026-09-05 as Phase 3 of
[AGENT_PLATFORM_PLAN.md](AGENT_PLATFORM_PLAN.md); the migration
(`20260905_0019`) is applied to the live database.

The default in `backend/config/settings.py` is still `false`, so a checkout
without the deployment's `.env` behaves as though runs do not exist. The
deployment's settings live in `~/anios/.env` on spark1, not in this
repository.

## The one sentence

A run is the turn's step loop - decide, act, observe, decide - hosted by a
worker over leased rows in PostgreSQL, so it survives a restart, waits for a
person when a step needs approval, can be cancelled from outside, and
finishes only when its acceptance criteria are met.

## Why this shape

- **The chat turn cannot host it** (ADR 0012): a disconnected stream stops
  every downstream node, and persistence has to happen before the final
  yield. Anything longer than a turn is a worker's job.
- **The lease pattern already survived production** (`scheduled_task_runs`,
  `discovery_runs`): claimed with a lease, reclaimed when it lapses, closed by
  one write. Runs copy it rather than adding a second runtime.
- **Idempotency is the actual work.** A checkpointer that re-executes a node
  from its top still duplicates an effect unless every effect is keyed. So
  every action is recorded with the natural key its tool's effect contract
  declares (`backend/core/effects.py`), before it runs.

## Data (`backend/models/agent_run.py`)

| Table | One row per | Carries |
| --- | --- | --- |
| `agent_runs` | job | principal (`user_id`), actor, kind, objective, acceptance criteria, budget, step ceiling, creation allowance, status, lease, cancel flag, result, `tenant_id` |
| `agent_run_actions` | step | sequence, tool, arguments, idempotency key, creates, status (`dispatched` → `succeeded` / `failed` / `refused` / `unknown`), outcome, the line the next decision reads |
| `agent_run_approvals` | question to a person | tool, hash of the exact arguments, target, summary, expiry, status (`pending` → `granted` / `denied` / `expired` → `consumed`) |
| `agent_run_events` | thing that happened | the audit trail |

Run statuses: `queued`, `running`, `waiting_approval`, `completed`, `failed`,
`cancelled`. Objective, acceptance, arguments, outcomes, summaries and event
detail are sealed like every other user text.

## The controller's guarantees (`backend/runs/controller.py`)

1. **Recorded before it runs.** A worker killed mid-call leaves a
   `dispatched` row, never nothing.
2. **A succeeded step is never redone.** On resume the world's key finds the
   earlier row; its recorded outcome stands in for the call.
3. **An unheard-from step is reconciled, never retried blind.** The world is
   asked what happened. If it cannot say, the run fails with `unknown_effect`
   for a person to look at. If it says the effect never landed, the step is
   done once, as a fresh row.
4. **An approval binds one exact call.** The run parks with a pending
   approval for the tool and the hash of its arguments. A yes is consumed by
   that call and no other; a no fails the run with `approval_denied`; a yes
   past its expiry is refused.
5. **A cancel is honoured between steps.** Read before every decision; a
   queued or parked run is cancelled outright.
6. **Completion is evidence.** The world's `verify` decides; the router
   declining is never, by itself, done. A bound stop names its error
   (`budget`, `ceiling`, `repeated`, `creation_allowance`, `needs_input`,
   `router_unavailable`, `refused`); budget and router failures are retried
   up to `AGENT_RUN_MAX_ATTEMPTS`.
7. **A run calls only what it was granted.** Each kind has a `Grant` - the
   tool names it may ever call - fixed in the worker's registry beside its
   world (`run_worker.py::GRANTS`, `backend/runs/grants.py`) and checked by
   the controller before any step is dispatched. A step outside it is
   recorded as refused and the run fails with `unauthorized_tool`, not
   retried, whatever talked the world into asking. A kind with a world but
   no grant does not run (`no_grant`).
8. **Claiming is fair across principals.** `claim_next` orders by how many
   runs the same principal already has running, then by age, so one
   person's queue does not hold every worker.
9. **Every effect has a receipt.** `effects_without_receipt` names any
   terminal step with no outcome, no finish time or no principal; the suite
   asserts it is empty over the rows it made.

Every guarantee is a test in `backend/tests/test_agent_runs.py`, driven
against the real schema with a scripted world, including a worker killed
after an effect and before its record closed. `test_run_drills.py` kills a
real worker process mid-step and resumes the run elsewhere.
`test_run_capacity.py` drives twenty-four runs for six principals through
three concurrent workers on one table: every run completed, every effect
once, no run held twice, no receipt missing (29.4 s on the desktop against
the tunnelled database, 2026-09-05).

## What an agent supplies (`backend/runs/worlds.py`)

A `RunWorld`: `decide`, `apply`, `tool_name`, `arguments`, `key`, `creates`,
`describe`, `needs_approval`, `approval_summary`, `reconcile`, `verify`. The
controller owns the guarantees; the world owns the judgement. An agent
registers a factory for its kind in `backend/workers/run_worker.py::WORLDS`;
a kind nobody registered fails the run with `no_world` rather than guessing.

## Hosting and control

- The worker loop runs in the discovery worker process behind
  `AGENT_RUNS_ENABLED`, on its own poll (`AGENT_RUN_POLL_SECONDS`), renewing
  the lease every third of `AGENT_RUN_LEASE_SECONDS`.
- `/api/v1/runs/{user_id}`: list and inspect (`runs:read`), cancel and
  decide an approval (`runs:act`). Every route checks the session owns the
  user and holds the scope.
- **The person can answer from chat.** Every turn's context lists the runs
  waiting on the person's yes (`runs_waiting`), so the reply mentions them
  and the next turn's router sees it in the history. A yes or a no is routed
  by the router to the `manage_runs` tool row (`backend/tools/manage_runs.py`)
  and carried out by `backend/services/run_answers.py`: one waiting run is
  the one; several and a number from the list picks that one; several and no
  number is a question back, never a guess from the words. The decision goes
  through the same repository method the API uses, so a yes from chat binds
  the same exact call. The reply is told what happened (`reply/run_outcome`)
  and says the run will go ahead - never that the step is done.
- **The person hears how it ended.** After each attempt the worker hands the
  run to `RunDelivery` (`backend/runs/delivery.py`): a completed, failed or
  approval-waiting stop is sent, as a short summary with no evidence in it,
  on the channel the run was asked from, to the address the person enrolled
  for that channel (the discovery subscribers). A web run is not pushed -
  the API and the card are its delivery - and every outcome is an event on
  the run: `delivered`, `delivery_skipped` with why, or `delivery_failed`
  with the channel's error. A failed delivery is never a failed run.

## Worlds that exist

- `code_review` - the reviewer (`backend/agents/review/`): a read-only review
  of one commit, verified on the real model against a planted defect and an
  injected instruction.
- `security_review` - the security agent (`backend/agents/security/`): the
  reviewer's stages under a scope check and with shape searches, refusing
  any asset not in `SECURITY_AUTHORIZED_ASSETS` before a tool is called.

- `chat_continuation` - a chat turn's unfinished work (`backend/agents/chat/`):
  a turn whose step loop stopped on its wall clock or step ceiling with the
  router still naming steps creates one, carrying the person's words, the
  step lines the turn recorded and the turn's channel. The world asks the
  same router for the next step, shown every step so far, and carries it out
  through the same executor - over the API with a short-lived `chat` token
  (`/api/v1/chat/{user_id}/steps/decide` and `/apply`), since the worker is
  another process. Its grant is the built-in tools whose contracts allow a
  later step plus reads through any MCP server (`mcp:read`); a step that
  sends, spends or changes something outside this system parks the run for
  the person's yes. Done when the router declines after its steps were
  carried out; `needs_input` when the router needs something the message did
  not say. The reply of the cut-short turn says the rest continues
  (`reply/handed_off`), never that it is done.

- `experience_review` - the experience reviewer (`backend/agents/experience/`):
  one run per person per day over their last day's turns and rooms, one
  model judgement checked against each turn's record, a wrong memory
  forgotten on the person's yes, the rest reported with its evidence.
  Created by `schedule_experience_reviews` in the run worker at
  `AGENT_EXPERIENCE_REVIEW_HOUR_UTC`, or by `backend.cli.review_experience`.

The reviews are created by `backend.cli.review_commit` today; the
continuation by the turn itself, only while `AGENT_RUNS_ENABLED` is on in the
API process (a promise nobody works is worse than none). A worker claims only
the kinds it hosts (`claim_next(kinds=...)`), so hosts sharing the table
never take each other's work.

## Not yet

- An approval can be answered from chat (`manage_runs`, below) or the runs
  API; nothing yet lets a person answer by a tapback or a phone reply
  outside a conversation turn.
- A continuation carries the person's words and the step lines, not the
  turn's retrieved context or history; a step that needed them is decided
  afresh by the router from the words alone.
- The grant is a set of tool names checked in this process, not a token
  another service could verify; that is D8's second shape.
- Retention deletes finished runs with their actions, approvals and events
  after `AGENT_RUN_RETENTION_DAYS`; there is no redaction short of deletion.
