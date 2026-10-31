#!/usr/bin/env bash
# Ask whether tonight's nightly produced a health verdict at all, and page if not.
#
#   bash scripts/check-nightly-freshness.sh
#
# ~/desk_daily.sh runs the nightly and then scripts/check-nightly-health.sh,
# but if the nightly never starts (cron dead, wrapper broken, disk full) the
# health check never runs either and nobody is told. This is the dead-man's
# switch: a separate 20:15 ET cron asks whether data/market/desk/
# nightly-health.json is today's. Exit 1 means the verdict was red.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${ANIOS_TRADING_PYTHON:-$HOME/research-venv/bin/python}"
if [[ ! -x "$python" ]]; then python=python3; fi
cd "$root"
exec "$python" -m backend.cli.market_nightly_check freshness --root "$root"
