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

## What this still does not cover

Honest limits, so nobody reads the section above as more than it is.

- **Both copies are in one room.** spark1 and spark2 share power and network.
  This survives a disk, not a fire or a theft. A third copy on the Mac is the
  next step, chosen because it is already on around the clock for the bridge.
- **Up to 24 hours of loss.** Nightly dumps with `archive_mode=off` and
  `wal_level=replica` means point-in-time recovery is not available; a failure
  at 03:29 loses the day. WAL archiving is the fix if that window is too wide.
- **The dump file itself is not encrypted.** Sealed columns are ciphertext
  inside it, but anything unsealed — table structure, timestamps, non-sensitive
  columns — is readable by whoever holds the file.
- **Redis is not in the dump.** It holds the iMessage read cursor, and since
  2026-08-23 it has an append-only file (`appendfsync everysec`) so a crash
  costs about a second rather than up to an hour. It is not backed up, because
  everything in it is either expiring or rebuildable — except that cursor, whose
  loss replays recent messages rather than destroying anything.
