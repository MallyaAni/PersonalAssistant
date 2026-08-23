# Next session

Verified state as of 2026-08-23, commit `d7c8f8db` plus the compose change
below. `deep-matter.com` serves from spark1 with the Windows desktop powered
off, and everything below was checked by running it, not by reading it.

## Live and verified

| | |
|---|---|
| site | `deep-matter.com` 200, tunnel is a compose service on spark1 |
| database | 177 conversations, 37 tables, on spark1 |
| redis | 7,094 keys, iMessage cursor `imessage:chat:cursor` present |
| models | DeepSeek-V4-Flash TP=2 (spark1+spark2), Qwen3-VL-8B (spark2), nomic 768-dim (spark1) |
| deploy gate | `bash scripts/gate.sh` - 7 passed, 0 skipped, ~3 min; exits 1 with the router down |
| turn loop | shipped inert, `TURN_MAX_STEPS=1` in backend and discovery-worker |

## Both decisions taken, 2026-08-23

**The multi-step loop is on.** `TURN_MAX_STEPS=3` in backend, discovery-worker
and local-capabilities. Revert is the env var and a restart, never a rebuild.

**`db` and `redis` are Compose-managed.** Adopted with writers stopped so the
cursor could not move mid-swap: 7,074 keys and cursor
`809188673966836992` byte-identical across the move, 37 tables, 177
conversations. `db` kept `anios_pgdata`; `redis` moved from an anonymous volume
to the named `anios_redisdata`, restored from an RDB written into it *before*
the container was ever started - starting first would have let an empty redis
write its own empty dump over the volume. The pre-swap snapshot is kept at
`/tmp/redis-final.rdb` on spark1.

**A bare `docker compose up -d` on spark1 is safe again** now that both are
Compose-managed on named volumes. The warning that stood here is withdrawn.

**And `anios_db` has a backup for the first time.** `scripts/backup-db.sh` was
failing at `service "db" is not running`; it works now - 2.1 MB, 37 tables. The
"no backups" constraint that has shaped every decision this week is no longer
strictly true, though one dump is not a backup policy.

## Superseded: two decisions that were waiting

**1. Turn the multi-step loop on.** The code is deployed and its functional
tests pass at `steps_max=3`, but production runs at 1, so the loop body is
unreachable. Flipping it is an env change and a restart, never a rebuild:

```sh
# in ~/anios/.env on spark1
TURN_MAX_STEPS=3
docker compose up -d --no-deps backend discovery-worker local-capabilities
```

Then send, from the real iMessage thread:
`cancel the tesla reminder and remind me to take the bins out at 7pm`
and read the rows back. A passing pytest run is not this. Revert by setting it
to 1 and restarting.

**2. Adopt `db` and `redis` into the Compose project.** They run as standalone
containers on spark1 because that is how the migration started them, and
`scripts/deploy.sh` therefore fails at its backup step with
`service "db" is not running`. Adoption means stopping and removing both
containers and recreating them under Compose, which is why it has not been done
unattended.

- `db` is safe: it already uses the named volume `anios_pgdata` that Compose
  expects, so the data survives the recreate.
- `redis` is **not**. Its data is in an anonymous volume. Compose now declares a
  named `redisdata` volume, so a recreate starts it **empty** - and Redis holds
  the iMessage read cursor, so an empty start silently replays or skips
  messages. A snapshot is already taken at `/tmp/redis-adopt.rdb` on spark1
  (388,780 bytes, 7,094 keys); restore it into the new volume before starting
  the container, then check `dbsize` and that `imessage:chat:cursor` is set.

Until this is done, **never run a bare `docker compose up -d` on spark1** - it
would recreate redis against the new named volume and lose the cursor. Name the
app services explicitly, as the restart command above does.

## Open, measured, and owed

- **`opinion_about_image` routes to `edit_image` 4 times in 51.** The most
  expensive open routing defect: the interface state is checked *after* the
  decision, so with a picture in view a wrong choice mutates an owned artifact
  and spends a real generation. Held at the measured rate in
  `test_nothing_is_mistaken_for_an_image_edit` only so the gate can run.
- **`agent_config` 0/12.** Adding `manage_tasks(reschedule)` took Scout's own
  sweep schedule from no-tool to `manage_tasks`. Two tool-description wordings
  failed to separate them, because "change the schedule to 9:25pm" is a
  defensible reschedule. The fix is structural: agent configuration needs its
  own tool, or Scout's sweep needs to be an ordinary scheduled task.
- **`writing_followup` 6/12**, unchanged since before scheduling existed. Two
  of the four carry a time and the router reads a time as a scheduling signal.
- **Diffusion has no home yet.** FLUX.2-klein-4B (6.5 GB) load-on-demand fits
  spark1's ~9.9 GB free; klein-9B (12 GB) does not.
- **`discovery-worker` has no `ROUTING_LLM_MODEL`**, so iMessage routing falls
  back to `MAIN_LLM_*`. Same model today, so it is latent rather than broken.
