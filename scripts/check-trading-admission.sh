#!/usr/bin/env bash
# Verify installed paper approval on the actual cron host and application container.
set -euo pipefail
root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [[ ! -f "$root/data/market/desk/learned-holding/config.json" ]]; then
    echo '{"status":"NOT_CONFIGURED"}'
    exit 0
fi
python="${ANIOS_TRADING_PYTHON:-$HOME/research-venv/bin/python}"
if [[ -z "${ANIOS_TRADING_PYTHON:-}" && ! -x "$python" ]]; then python=python3; fi
host="$(cd "$root" && PYTHONPATH="$root" "$python" -m backend.cli.market_release_admission check --root "$root/data/market")"
container="$(docker compose -f "$root/docker-compose.yml" exec -T backend python -m backend.cli.market_release_admission check --root /app/data/market </dev/null)"
"$python" -c 'import json,sys; host=json.loads(sys.argv[1]); container=json.loads(sys.argv[2]); assert host==container and host["status"]=="ADMITTED", "HOST/CONTAINER trading admission differs"; print(json.dumps({"host_and_container":"ADMITTED",**host},sort_keys=True))' "$host" "$container"
