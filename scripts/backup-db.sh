#!/usr/bin/env bash
# Back up the database now, without restarting anything.
#
#   bash scripts/backup-db.sh
#
# Startup takes a backup, but startup can be weeks apart, and everything added
# in between is unprotected. This is the one to run before anything risky and
# before moving the stack to another machine.
#
# Restore with:
#   gunzip -c data/backups/<file>.sql.gz \
#     | docker compose exec -T db psql -U postgres -d anios_db

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml")

user="postgres"
database="anios_db"
if [[ -f "$root/.env" ]]; then
    # Strip CR as well as spaces: this stack came off a Windows box, and a
    # single CRLF line ending would make `pg_dump -U postgres\r` fail.
    user="$(grep -m1 -E '^\s*POSTGRES_USER\s*=' "$root/.env" | cut -d= -f2- | tr -d ' \r' || echo postgres)"
    database="$(grep -m1 -E '^\s*POSTGRES_DB\s*=' "$root/.env" | cut -d= -f2- | tr -d ' \r' || echo anios_db)"
fi
user="${user:-postgres}"
database="${database:-anios_db}"

directory="$root/data/backups"
mkdir -p "$directory"
target="$directory/${database}-$(date +%Y%m%d-%H%M%S).sql.gz"

# Written to a .partial and promoted only once it is proven a real dump, so a
# failed pg_dump cannot leave a stub file that becomes the newest "backup".
# With pipefail a dump failure aborts the script; the trap clears the partial
# on any exit so nothing half-written survives.
partial="$target.partial"
trap 'rm -f "$partial" 2>/dev/null || true' EXIT

"${compose[@]}" exec -T db pg_dump -U "$user" -d "$database" --clean --if-exists \
    | gzip >"$partial"

tables="$(gunzip -c "$partial" | grep -c '^CREATE TABLE' || true)"
if [[ "${tables:-0}" -lt 1 ]]; then
    echo "ERROR: dump produced no tables; not writing a backup" >&2
    exit 1
fi
mv "$partial" "$target"
echo "Backed up $tables tables to data/backups/$(basename "$target")"

# Point-in-time recovery needs two things the dump is not: a base backup of
# the data directory, and every WAL segment written since it. The db container
# archives segments into the walarchive volume on its own (compose sets
# archive_mode=on with a five-minute archive_timeout); this takes the base
# backup beside them, keeps a week of both, and copies the volume out to the
# host so the mirror loop below can ship it. Never fatal: the dump above is
# still a backup, and a PITR gap is reported, not silently swallowed.
if "${compose[@]}" exec -T db sh -c 'd="/wal-archive/base-$(date +%Y%m%d-%H%M%S)" && mkdir -p "$d" && pg_basebackup -U "'"$user"'" -D "$d" -Ft -z -X none -c fast && find /wal-archive -maxdepth 1 -name "base-*" -type d -mtime +7 -exec rm -rf {} + ; find /wal-archive -maxdepth 1 -type f -mtime +7 -delete' \
    && mkdir -p "$root/data/wal-archive" \
    && "${compose[@]}" cp db:/wal-archive/. "$root/data/wal-archive/" >/dev/null; then
    # The staging copy is pruned on the volume's own terms, because `cp` adds
    # and never removes; the mirrors then follow the staging copy exactly.
    find "$root/data/wal-archive" -maxdepth 1 -name 'base-*' -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
    find "$root/data/wal-archive" -maxdepth 1 -type f -mtime +7 -delete 2>/dev/null || true
    segments="$(find "$root/data/wal-archive" -maxdepth 1 -type f | wc -l | tr -d ' ')"
    echo "Base backup taken; $segments archived WAL files staged in data/wal-archive"
else
    echo "WARNING: base backup or WAL archive copy failed - the dump is fine, point-in-time recovery is not current" >&2
fi

# A dump that never leaves the machine is not a backup.
#
# Both the database volume and this directory live on the same NVMe device, so
# one drive failure took the data and every copy of it together. Pushing to the
# other Spark is not offsite - a fire takes both - but it survives the failure
# that actually happens, which is one disk.
#
# Never fatal. A backup that succeeded locally and could not be copied is still
# a backup, and exiting non-zero here would abort the deploy that called it.
# Read the mirror target from .env like the database settings above, not only
# from the environment. Setting it in .env and finding the script had ignored it
# is the shape of mistake this whole section exists to prevent.
# Strip line endings only - a CRLF in .env would otherwise leave a
# trailing carriage return on the hostname and every ssh silently fail - and
# trim the edges. Interior spaces stay: they separate the mirror hosts, and
# stripping them fused two targets into one unreachable name on 2026-08-24.
if [[ -z "${BACKUP_MIRROR_HOST:-}" && -f "$root/.env" ]]; then
    BACKUP_MIRROR_HOST="$(grep -m1 -E '^\s*BACKUP_MIRROR_HOST\s*=' "$root/.env" | cut -d= -f2- | tr -d '\r\n' | sed -E 's/^ +| +$//g' || true)"
fi
if [[ -z "${BACKUP_MIRROR_PATH:-}" && -f "$root/.env" ]]; then
    BACKUP_MIRROR_PATH="$(grep -m1 -E '^\s*BACKUP_MIRROR_PATH\s*=' "$root/.env" | cut -d= -f2- | tr -d '\r\n' | sed -E 's/^ +| +$//g' || true)"
fi

# BACKUP_MIRROR_HOST is a whitespace-separated LIST, so a third copy (the Mac)
# joins spark2 rather than replacing it. One shared path applies to all; keep
# it off any iCloud-synced directory on a Mac target. A per-host failure is
# named and never fatal - a backup that could not be copied is still a backup.
if [[ -n "${BACKUP_MIRROR_HOST:-}" ]]; then
    mirror_dir="${BACKUP_MIRROR_PATH:-~/anios-backups}"
    for host in $BACKUP_MIRROR_HOST; do
        if ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" "mkdir -p $mirror_dir" \
            && scp -o BatchMode=yes -o ConnectTimeout=10 -q "$target" "$host:$mirror_dir/"; then
            echo "Mirrored to $host:$mirror_dir"
            # The WAL archive rides along, incrementally: rsync sends only new
            # segments and removes what the archive has pruned, so the mirror
            # holds what the volume holds, a week deep. Without this the
            # archive would survive exactly the failure the dump already
            # survives - one disk - and not the one PITR is for.
            if [[ -d "$root/data/wal-archive" ]] && command -v rsync >/dev/null 2>&1; then
                rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=10" --delete "$root/data/wal-archive/" "$host:$mirror_dir/wal-archive/" \
                    && echo "WAL archive mirrored to $host:$mirror_dir/wal-archive" \
                    || echo "WARNING: could not mirror the WAL archive to $host" >&2
            fi
            # Prune the mirror on the same terms as the local copy; without this
            # the remote keeps every dump forever, noticed only when its disk
            # fills. Bodies of the two finds kept on one line each so no
            # backslash-continuation can swallow a later argument.
            ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" \
                "find $mirror_dir -name '${database}-*.sql.gz' -type f -mtime +30 -delete; find $mirror_dir -name '${database}-*.sql.gz' -type f -size -1k -delete" \
                || echo "WARNING: mirrored to $host, but could not prune old dumps there" >&2
        else
            echo "WARNING: could not mirror to $host - check its reachability and key" >&2
        fi
    done
else
    echo "WARNING: BACKUP_MIRROR_HOST is unset, so this backup is on the same disk as the database" >&2
fi

# Keep a month of daily dumps rather than every dump ever. Old enough to cover
# a problem noticed late, bounded enough that nobody has to think about it.
find "$directory" -name "${database}-*.sql.gz" -type f -mtime +30 -delete 2>/dev/null || true
# A zero-length or near-empty dump is a failed run wearing a filename. Remove
# them so the newest file is always a real backup.
find "$directory" -name "${database}-*.sql.gz" -type f -size -1k -delete 2>/dev/null || true

# Sealed columns are unreadable without the key, so a backup taken with
# encryption on is only as recoverable as the key is.
if grep -q '^ENCRYPTION_KEY=.' "$root/.env" 2>/dev/null; then
    echo "ENCRYPTION_KEY is set — keep it with this backup or the dump cannot be read."
fi
