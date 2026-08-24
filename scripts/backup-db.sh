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
    user="$(grep -m1 -E '^\s*POSTGRES_USER\s*=' "$root/.env" | cut -d= -f2- | tr -d ' ' || echo postgres)"
    database="$(grep -m1 -E '^\s*POSTGRES_DB\s*=' "$root/.env" | cut -d= -f2- | tr -d ' ' || echo anios_db)"
fi
user="${user:-postgres}"
database="${database:-anios_db}"

directory="$root/data/backups"
mkdir -p "$directory"
target="$directory/${database}-$(date +%Y%m%d-%H%M%S).sql.gz"

"${compose[@]}" exec -T db pg_dump -U "$user" -d "$database" --clean --if-exists \
    | gzip >"$target"

tables="$(gunzip -c "$target" | grep -c '^CREATE TABLE' || true)"
echo "Backed up $tables tables to data/backups/$(basename "$target")"

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
if [[ -z "${BACKUP_MIRROR_HOST:-}" && -f "$root/.env" ]]; then
    BACKUP_MIRROR_HOST="$(grep -m1 -E '^\s*BACKUP_MIRROR_HOST\s*=' "$root/.env" | cut -d= -f2- | tr -d ' ' || true)"
    BACKUP_MIRROR_PATH="${BACKUP_MIRROR_PATH:-$(grep -m1 -E '^\s*BACKUP_MIRROR_PATH\s*=' "$root/.env" | cut -d= -f2- | tr -d ' ' || true)}"
fi

if [[ -n "${BACKUP_MIRROR_HOST:-}" ]]; then
    mirror_dir="${BACKUP_MIRROR_PATH:-~/anios-backups}"
    if ssh -o BatchMode=yes -o ConnectTimeout=10 "$BACKUP_MIRROR_HOST"         "mkdir -p $mirror_dir" 2>/dev/null        && scp -o BatchMode=yes -o ConnectTimeout=10 -q         "$target" "$BACKUP_MIRROR_HOST:$mirror_dir/" 2>/dev/null; then
        echo "Mirrored to $BACKUP_MIRROR_HOST:$mirror_dir"
    else
        echo "WARNING: could not mirror to $BACKUP_MIRROR_HOST - this copy is on one disk only" >&2
    fi
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
