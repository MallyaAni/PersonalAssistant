#!/usr/bin/env bash
# Is every backup copy fresh? Page the operator if any is not.
#
#   bash scripts/check-backup-freshness.sh
#
# The nightly unit pages on a *failure*. This covers the other way a backup
# dies: silently. A timer that stopped firing, a mirror host whose key was
# rotated, a disk that filled between runs - none of those exit non-zero on
# the night it matters, because nothing ran. So once a week, ask the only
# question that counts: on every copy, is there a dump newer than 36 hours?
# Thirty-six, not twenty-four, so one late night does not page a phone.
#
# Exits 0 when every copy is fresh, 1 when any is stale - and on stale it has
# already sent the alert, best-effort, through notify-operator.sh. Host-level
# and ssh/find only, like the backup itself, so it works when the app is down.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
max_age_hours="${BACKUP_MAX_AGE_HOURS:-36}"

# Same .env reading as backup-db.sh: line endings stripped, interior spaces
# kept, because BACKUP_MIRROR_HOST is a whitespace-separated list.
env_get() {
    grep -m1 -E "^\s*$1\s*=" "$root/.env" 2>/dev/null | cut -d= -f2- \
        | tr -d '\r\n' | sed -E 's/^ +| +$//g'
}
mirror_hosts="${BACKUP_MIRROR_HOST:-$(env_get BACKUP_MIRROR_HOST)}"
mirror_dir="${BACKUP_MIRROR_PATH:-$(env_get BACKUP_MIRROR_PATH)}"
mirror_dir="${mirror_dir:-~/anios-backups}"

stale=()

# The local copy. `find -mmin` rather than parsing the dated filename: the
# name says when the dump was meant for, the mtime says when it was written.
local_dir="$root/data/backups"
if [[ -z "$(find "$local_dir" -name 'anios_db-*.sql.gz' -mmin "-$((max_age_hours * 60))" 2>/dev/null | head -1)" ]]; then
    stale+=("spark1:$local_dir")
fi

# Each mirror, over the same key-based ssh the backup uses. An unreachable
# mirror counts as stale: the copy may be there, but a copy that cannot be
# reached cannot be restored from either.
for host in $mirror_hosts; do
    fresh="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" \
        "find $mirror_dir -name 'anios_db-*.sql.gz' -mmin -$((max_age_hours * 60)) 2>/dev/null | head -1" 2>/dev/null)"
    if [[ -z "$fresh" ]]; then
        stale+=("$host:$mirror_dir")
    fi
done

if [[ ${#stale[@]} -eq 0 ]]; then
    echo "backup freshness: every copy has a dump newer than ${max_age_hours}h"
    exit 0
fi

message="AniOS: no backup newer than ${max_age_hours}h on: ${stale[*]}. Check: systemctl status anios-backup.timer on spark1"
echo "$message" >&2
bash "$root/scripts/notify-operator.sh" "$message"
exit 1
