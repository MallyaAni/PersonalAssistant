#!/usr/bin/env bash
# Page when the intraday board stops refreshing during the regular session.
#
#   bash scripts/check-intraday-health.sh
#
# ~/desk_intraday.sh runs it after each fifteen-minute balancer attempt with
# `|| true`, so a red verdict never changes the balancer's exit status. Exit
# 1 means the verdict was red.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${ANIOS_TRADING_PYTHON:-$HOME/research-venv/bin/python}"
if [[ ! -x "$python" ]]; then python=python3; fi
cd "$root"
exec "$python" -m backend.cli.market_intraday_health --root "$root"
