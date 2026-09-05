# Durable runs: an agent's loop that outlives a turn

Status: built and unit-verified 2026-09-05 (Phase 3 of
[AGENT_PLATFORM_PLAN.md](AGENT_PLATFORM_PLAN.md)); no agent registers a
kind of run yet, so the worker loop is off (`AGENT_RUNS_ENABLED=false`) and
nothing creates a run in production. The migration (`20260905_0019`) is
applied to the live database.

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
   `router_unavailable`); budget and router failures are retried up to
   `AGENT_RUN_MAX_ATTEMPTS`.

Every guarantee is a test in `backend/tests/test_agent_runs.py`, driven
against the real schema with a scripted world, including a worker killed
after an effect and before its record closed.

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

## Worlds that exist

- `code_review` - the reviewer (`backend/agents/review/`): a read-only review
  of one commit, verified on the real model against a planted defect and an
  injected instruction.
- `security_review` - the security agent (`backend/agents/security/`): the
  reviewer's stages under a scope check and with shape searches, refusing
  any asset not in `SECURITY_AUTHORIZED_ASSETS` before a tool is called.

Both are created by `backend.cli.review_commit` today. A worker claims only
the kinds it hosts (`claim_next(kinds=...)`), so hosts sharing the table
never take each other's work.

## Not yet

- A chat turn that exceeds its budget creating a run is Phase 3's remaining
  slice and needs a conversation world.
- Approvals are rows; nothing yet asks the person in chat or on the phone.
- Restart mid-run is tested in-process (a `BaseException` in the step); a
  test that kills the worker process is Phase 7's drill.
