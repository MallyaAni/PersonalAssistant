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

# Sealed columns are unreadable without the key, so a backup taken with
# encryption on is only as recoverable as the key is.
if grep -q '^ENCRYPTION_KEY=.' "$root/.env" 2>/dev/null; then
    echo "ENCRYPTION_KEY is set — keep it with this backup or the dump cannot be read."
fi
