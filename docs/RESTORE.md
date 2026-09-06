# Restoring the database

This procedure was run end to end on 2026-08-23 against the live dump. It is
written down because a restore nobody has performed is a hope, not a plan, and
the two failure modes it protects against are both silent: a dump that will not
load, and a dump that loads into rows nobody can read.

## What exists

| | |
|---|---|
| Dump | `~/anios/data/backups/anios_db-YYYYMMDD-HHMMSS.sql.gz` on spark1, ~2.2 MB |
| Schedule | `anios-backup.timer`, nightly 03:30 with a 5-minute jitter, `Persistent=true` |
| Second copy | pushed to spark2 (`172.16.8.5:~/anios-backups`) by the same script |
| Retention | 30 days; dumps under 1 KB are deleted as failed runs |
| Key | `ENCRYPTION_KEY` and `SECRET_KEY`, escrowed off both Sparks |

The dump holds ciphertext for every sealed column. **It is not self-contained.**
Without `ENCRYPTION_KEY` the conversation turns, memory content, phone numbers
and artifact bytes in it are unrecoverable — not difficult, unrecoverable. The
key is deliberately not stored next to the dumps, and copying it there to make a
restore convenient would undo the reason the columns are encrypted at all.

## Restoring

Restore into a scratch database first, always. Loading a dump straight over a
live database replaces a working system with an untested one, and if the dump
turns out to be bad there is then nothing to go back to.

```bash
cd ~/anios
U=$(grep -m1 '^POSTGRES_USER=' .env | cut -d= -f2- | tr -d ' \r')

sg docker -c "docker compose exec -T db psql -U $U -d postgres -c 'CREATE DATABASE anios_restore_probe'"
gunzip -c data/backups/anios_db-<stamp>.sql.gz \
  | sg docker -c "docker compose exec -T db psql -U $U -d anios_restore_probe -v ON_ERROR_STOP=1 -q"
```

`ON_ERROR_STOP=1` matters. Without it psql reports success after skipping
statements it could not apply, which is how a partial restore passes for a
complete one.

## Settings a restored database does not bring with it

`ALTER DATABASE` settings live in the server's catalogue, so they survive
restarts and image rebuilds but not a database restored into a fresh volume.
Re-apply this one after any such restore:

```bash
docker exec anios_db psql -U postgres -d anios_db   -c "ALTER DATABASE anios_db SET idle_in_transaction_session_timeout = '5min';"
docker exec anios_db psql -U postgres -d anios_db -tc "show idle_in_transaction_session_timeout;"
```

Why it matters, measured: on 2026-09-06 one connection was left *idle in
transaction* holding a row lock on `visual_artifacts`. Nothing ended it. It
sat for fifteen hours, every `DELETE` on that table queued behind it, and
three deploy gates hung - one ran for four and a half hours instead of two
and a half minutes - until the owning container was restarted by hand. The
timeout ends such a session after five minutes on its own. It cannot fire on
a query that is doing work; only on a transaction whose client has stopped
talking.

## Proving the restore before trusting it

Two checks, because they fail independently.

**Every table, same row count.** Not a sampled few — a dump can restore most of
itself and lose one table to a broken constraint.

```bash
counts() { sg docker -c "docker compose exec -T db psql -U $U -d $1 -Atc \"select relname||'='||(xpath('/row/c/text()', query_to_xml('select count(*) c from '||quote_ident(relname), false, true, '')))[1]::text::int from pg_stat_user_tables order by relname\""; }
diff <(counts anios_db) <(counts anios_restore_probe)
```

Last run: 37 tables, 2,506 rows, identical.

**The key still reads the ciphertext.** This is the check that distinguishes a
backup from a file. Sample sealed values out of the restored database and
decrypt them with the escrowed key:

```python
from backend.core.crypto import get_field_cipher
cipher = get_field_cipher()          # reads ENCRYPTION_KEY from settings
cipher.decrypt(value)                # values beginning "enc:1:"
```

Last run: 65 sealed values sampled across the restored database, 65 decrypted,
0 failed. A failure here means the escrowed key is not the key that wrote the
dump, and no amount of re-restoring will fix it.

Drop the scratch database when finished. Only then consider promoting it.

## Point-in-time recovery

Since 2026-08-25 the database archives WAL (`archive_mode=on`, a segment
forced closed at least every five minutes) into the `walarchive` volume, and
every nightly run of `backup-db.sh` takes a base backup beside it, keeps a
week of both, stages the volume at `data/wal-archive/` on spark1, and rsyncs
that directory to each mirror under `wal-archive/`. So the dump answers "give
me last night", and this answers "give me 09:14 this morning".

Rehearsed end to end on 2026-08-25 into a scratch container (never the live
volumes): the newest base backup plus archived WAL promoted with 37 tables,
188 conversations, and the same newest turn as live. The steps, from any copy
of the archive:

1. Copy the archive somewhere writable: `cp -r data/wal-archive/. /tmp/pitr/archive/`
   (on a mirror, `~/anios-backups/wal-archive/`).
2. Unpack the newest base backup into an empty data directory:
   `tar -xzf /tmp/pitr/archive/base-<newest>/base.tar.gz -C /tmp/pitr/pgdata && mkdir -p /tmp/pitr/pgdata/pg_wal && touch /tmp/pitr/pgdata/recovery.signal && chmod 700 /tmp/pitr/pgdata`
3. Tell it where the WAL is, and optionally when to stop, by appending to
   `/tmp/pitr/pgdata/postgresql.auto.conf`:
   ```
   restore_command = 'cp /archive/%f %p'
   archive_mode = off
   # Optional. Omit both lines to replay everything archived (the latest
   # recoverable point). A time target must be at or before the last
   # committed transaction in the archive, or Postgres refuses to promote
   # with "recovery ended before configured recovery target was reached".
   recovery_target_time = '2026-08-25 09:14:00+00'
   recovery_target_action = 'promote'
   ```
4. Start a scratch Postgres on it, as your own user so the files stay yours:
   `docker run -d --name pitr --user "$(id -u):$(id -g)" -e POSTGRES_PASSWORD=x -v /tmp/pitr/pgdata:/var/lib/postgresql/data -v /tmp/pitr/archive:/archive:ro pgvector/pgvector:pg16`
5. Watch `docker logs pitr` for "restored log file", "consistent recovery
   state reached", and "database system is ready to accept connections";
   then `docker exec pitr psql -U postgres -d anios_db -c 'select count(*) from conversations'`
   and prove the sealed columns decrypt exactly as in the dump procedure above.
6. Only then decide what to do with it: dump it and restore that dump into
   the live cluster's scratch database, exactly as above. Never point the
   live container at a recovered data directory.

Two things the rehearsal taught: a freshly created `walarchive` volume is
root-owned, so `archive_command` fails silently until it is chowned to
postgres (`backup-db.sh` now does this before every base backup, and
`pg_stat_archiver.failed_count` is the number to watch); and `pg_basebackup
-X none` waits for archiving to catch up, so with a broken archive it hangs
rather than failing.

## What this still does not cover

Honest limits, so nobody reads the section above as more than it is.

- **Both copies are in one room.** spark1 and spark2 share power and network.
  This survives a disk, not a fire or a theft. A third copy on the Mac is the
  next step, chosen because it is already on around the clock for the bridge.
- **Up to five minutes of loss, not twenty-four hours** - since 2026-08-25,
  see the point-in-time section above. The archive lags the live database by
  at most `archive_timeout` (five minutes), and only what has been rsynced to
  a mirror survives the loss of spark1's disk, which happens nightly with the
  dump. A failure between two nightly runs can therefore lose up to a day of
  *archive* on the mirrors, though not on spark1 itself.
- **The dump file itself is not encrypted.** Sealed columns are ciphertext
  inside it, but anything unsealed — table structure, timestamps, non-sensitive
  columns — is readable by whoever holds the file.
- **Redis is not in the dump.** It holds the iMessage read cursor, and since
  2026-08-23 it has an append-only file (`appendfsync everysec`) so a crash
  costs about a second rather than up to an hour. It is not backed up, because
  everything in it is either expiring or rebuildable — except that cursor, whose
  loss replays recent messages rather than destroying anything.

## Durable runs under load

`backend/tests/test_run_capacity.py` is the recovery-under-contention drill
for `agent_runs`: twenty-four runs for six principals, three workers claiming
from one table, every run completed once with every receipt present (29.4 s
on the desktop through the tunnel, 2026-09-05). `test_run_drills.py` kills a
worker process mid-step and resumes the run in another. A restore of the
database mid-run is safe by the same guarantees: a `dispatched` row without
an outcome is reconciled, never retried blind.
