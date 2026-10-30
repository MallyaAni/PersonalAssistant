#!/usr/bin/env bash
# Verify the 19:30 nightly actually wrote today's book, and page if it did not.
#
#   bash scripts/check-nightly-health.sh
#
# The nightly is green to cron even when it refuses to trade: "paper book: not
# traded (ValueError: ...)" and "joint-funded-unavailable" are printed and the
# process exits 0. This reads the state and the log the nightly just wrote,
# writes data/market/desk/nightly-health.json and alerts through
# scripts/notify-operator.sh when today's book is missing, the funded receipt
# is unavailable, orders were refused, or the publication is stale.
#
# ~/desk_daily.sh runs it with `|| true` so it never changes the nightly's
# exit status. Exit 1 means the verdict was red.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${ANIOS_TRADING_PYTHON:-$HOME/research-venv/bin/python}"
if [[ ! -x "$python" ]]; then python=python3; fi
cd "$root"
exec "$python" -m backend.cli.market_nightly_check health \
    --root "$root" --log "${DESK_DAILY_LOG:-$HOME/desk_daily.log}"
