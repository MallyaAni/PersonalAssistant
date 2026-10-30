#!/usr/bin/env bash
# Ask the 19:30 nightly's questions before it runs, and page on a bad answer.
#
#   bash scripts/check-nightly-readiness.sh
#
# The nightly can stop without crashing: a release/admission mismatch prints
# "paper book: not traded", the funded guard prints "joint-funded-unavailable",
# and a broker clock that reports the market open refuses every ordinary
# order. This checks the same admission, clock and account inputs first,
# writes data/market/desk/nightly-readiness.json and alerts through
# scripts/notify-operator.sh.
#
# It never blocks the nightly: ~/desk_daily.sh runs it with `|| true`, so a
# false alarm cannot cost the session. Exit 1 means the verdict was red.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The paper client reads os.environ directly; cron starts with a bare
# environment. Take only the two Alpaca values, as desk_daily.sh does, so
# nothing else in .env is exported.
APCA_API_KEY_ID="$(grep -m1 '^APCA_API_KEY_ID=' "$root/.env" 2>/dev/null | cut -d= -f2-)"
APCA_API_SECRET_KEY="$(grep -m1 '^APCA_API_SECRET_KEY=' "$root/.env" 2>/dev/null | cut -d= -f2-)"
export APCA_API_KEY_ID APCA_API_SECRET_KEY
python="${ANIOS_TRADING_PYTHON:-$HOME/research-venv/bin/python}"
if [[ ! -x "$python" ]]; then python=python3; fi
cd "$root"
exec "$python" -m backend.cli.market_nightly_check preflight \
    --root "$root" --log "${DESK_DAILY_LOG:-$HOME/desk_daily.log}"
