#!/usr/bin/env bash
# Verify that Alembic builds the whole schema from nothing.
#
#   bash scripts/verify-migrations.sh
#
# This runs against a throwaway database created for the run and dropped
# afterwards. The real database is never touched. Proving a migration path by
# emptying anios_db destroys real conversations, memory, and presentations, and
# that loss is permanent: archive_mode is off and there is no WAL to replay.

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml")

env_value() {
    local name="$1" fallback="$2" line value
    if [[ -f "$root/.env" ]]; then
        line="$(grep -m 1 -E "^[[:space:]]*${name}[[:space:]]*=" "$root/.env" || true)"
        if [[ -n "$line" ]]; then
            value="${line#*=}"
            value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
            if [[ -n "$value" ]]; then
                printf '%s' "$value"
                return
            fi
        fi
    fi
    printf '%s' "$fallback"
}

user="$(env_value POSTGRES_USER postgres)"
real_db="$(env_value POSTGRES_DB anios_db)"
scratch="migration_check_$$"

psql_admin() {
    "${compose[@]}" exec -T db psql -U "$user" -d postgres -v ON_ERROR_STOP=1 "$@"
}

# Drop the scratch database however this script exits, including on failure, so
# a failed run never leaves a stray database behind. FORCE closes any connection
# Alembic left open.
cleanup() {
    psql_admin -q -c "drop database if exists \"$scratch\" with (force)" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Creating throwaway database $scratch ..."
"${compose[@]}" up -d --wait db >/dev/null
psql_admin -q -c "create database \"$scratch\""

# Refuse to continue if the scratch name somehow resolved to the real database.
if [[ "$scratch" == "$real_db" ]]; then
    echo "Refusing to run: scratch name collides with $real_db." >&2
    exit 1
fi

echo 'Applying migrations from an empty schema ...'
"${compose[@]}" run --rm \
    -e POSTGRES_HOST=db \
    -e POSTGRES_DB="$scratch" \
    backend python -m alembic upgrade head

tables="$("${compose[@]}" exec -T db psql -U "$user" -d "$scratch" -tAc \
    "select count(*) from information_schema.tables where table_schema = 'public'")"
tables="$(printf '%s' "$tables" | tr -cd '0-9')"

head_rev="$("${compose[@]}" exec -T db psql -U "$user" -d "$scratch" -tAc \
    'select version_num from alembic_version')"
head_rev="$(printf '%s' "$head_rev" | tr -d '\r\n ')"

if [[ "$tables" -lt 2 ]]; then
    echo "FAILED: migrations produced $tables tables." >&2
    exit 1
fi

echo ''
echo "Migrations build cleanly: $tables tables at head $head_rev."
echo "$real_db was not touched."
