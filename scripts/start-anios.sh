#!/usr/bin/env bash
# Start the whole AniOS stack with one command, including the local ComfyUI
# image backend.
#
#   bash scripts/start-anios.sh
#
# ComfyUI runs on the host (using the install at COMFYUI_HOST_PATH) because the
# backend targets host.docker.internal:8188 and the host path is far lighter than
# the GPU container image. To use the containerized ComfyUI instead, skip the
# host step below and run: docker compose --profile comfyui up -d

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/docker-compose.yml")

# Read one non-secret operator setting from the local environment file. Values
# are taken literally: this is not a shell sourcing, so nothing in .env can run.
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

# Report whether a loopback service is accepting TCP connections. Bash opens the
# socket directly so this needs no netcat, which Git Bash does not ship.
port_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- 3>&-
}

# How many rotating dumps to retain below data/backups.
backup_keep=10

# Dump the database before anything alters its schema. Nothing else in this
# stack protects it: archive_mode is off and there is no backup job, so a lost
# table is lost permanently. Restore one with:
#
#   gunzip -c data/backups/<file>.sql.gz \
#     | docker compose exec -T db psql -U postgres -d anios_db
backup_database() {
    local user db dir stamp target tables old
    user="$(env_value POSTGRES_USER postgres)"
    db="$(env_value POSTGRES_DB anios_db)"

    # A fresh install has nothing to lose, and dumping an empty schema on every
    # start would push real backups out of the retention window.
    tables="$("${compose[@]}" exec -T db psql -U "$user" -d "$db" -tAc \
        "select count(*) from information_schema.tables where table_schema = 'public'" \
        2>/dev/null || printf '0')"
    tables="$(printf '%s' "$tables" | tr -cd '0-9')"
    if [[ -z "$tables" || "$tables" == '0' ]]; then
        echo 'No existing schema to back up.'
        return
    fi

    dir="$root/data/backups"
    mkdir -p "$dir"
    stamp="$(date +%Y%m%d-%H%M%S)"
    target="$dir/anios_db-$stamp.sql.gz"

    if "${compose[@]}" exec -T db pg_dump -U "$user" -d "$db" --clean --if-exists \
        | gzip >"$target"; then
        echo "Backed up $tables tables to data/backups/$(basename "$target")"
    else
        rm -f "$target"
        echo 'WARNING: database backup failed; continuing without one.' >&2
        return
    fi

    while IFS= read -r old; do
        [[ -n "$old" ]] && rm -f "$old"
    done < <(ls -1t "$dir"/anios_db-*.sql.gz 2>/dev/null | tail -n +$((backup_keep + 1)))
}

# Compile one bounded generation and embedding path before user traffic arrives.
warm_vllm() {
    curl -fsS -X POST 'http://127.0.0.1:8003/v1/chat/completions' \
        -H 'Content-Type: application/json' \
        -d '{"model":"qwen/qwen3.5-4b","messages":[{"role":"user","content":"Reply with exactly READY"}],"max_tokens":16,"temperature":0,"reasoning_effort":"none"}' \
        >/dev/null

    curl -fsS -X POST 'http://127.0.0.1:8004/v1/embeddings' \
        -H 'Content-Type: application/json' \
        -d '{"model":"text-embedding-nomic-embed-text-v1.5","input":["search_document: AniOS startup warmup"]}' \
        >/dev/null
}

# 1) Start the embedding service. The generation and vision models no longer
# live in this Compose project - they run on the DGX Sparks, started by
# ~/ds4-tp2.sh and ~/vlm-serve.sh there - so there is no ordering constraint
# left to respect here.
echo 'Starting vLLM embedding service ...'
"${compose[@]}" up -d --wait --wait-timeout 900 vllm-embedding

# 2) Pay one-time JIT costs before the first user request.
echo 'Warming vLLM generation and embedding paths ...'
warm_vllm

# 3) ComfyUI on the host, unless something already listens on 8188. Starting it
# after vLLM avoids competing with CUDA graph and KV-cache initialization.
comfy_started=0
if port_open 8188; then
    echo 'ComfyUI already running on :8188.'
else
    comfy="$(env_value COMFYUI_HOST_PATH 'E:/AI/ComfyUI')"
    python_bin=''
    for candidate in \
        "$comfy/.venv/Scripts/python.exe" \
        "$comfy/python_embeded/python.exe" \
        "$comfy/.venv/bin/python"; do
        if [[ -x "$candidate" || -f "$candidate" ]]; then
            python_bin="$candidate"
            break
        fi
    done
    [[ -n "$python_bin" ]] || python_bin='python'

    if [[ ! -f "$comfy/main.py" ]]; then
        echo "WARNING: ComfyUI not found at $comfy. Set COMFYUI_HOST_PATH in .env; image generation will be unavailable until it runs." >&2
    else
        echo "Starting ComfyUI from $comfy ..."
        # Detached and surviving this shell, with output kept for diagnosis
        # rather than discarded, since a failed start is otherwise silent.
        (
            cd "$comfy"
            nohup "$python_bin" main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch \
                >"$comfy/comfyui-startup.log" 2>&1 &
        )
        comfy_started=1
    fi
fi

# 4) Bring the database schema up to date before anything reads it. Compose
# starts services but never applies migrations, so without this a fresh clone
# comes up against a database with no tables and every request fails. It runs
# inside the backend image, which already carries Alembic and the driver.
echo 'Applying database migrations ...'
"${compose[@]}" up -d --wait db
backup_database
if ! "${compose[@]}" run --rm -e POSTGRES_HOST=db backend python -m alembic upgrade head; then
    echo 'Database migration failed; not starting the application.' >&2
    exit 1
fi

# 5) Start the remaining application services after inference is ready.
echo 'Starting AniOS application services ...'
"${compose[@]}" up -d

# 6) Wait for the backend, then report.
printf 'Waiting for backend '
for _ in $(seq 1 40); do
    if curl -fsS --max-time 3 'http://localhost:8000/health' >/dev/null 2>&1; then
        break
    fi
    printf '.'
    sleep 3
done
printf '\n'

# ComfyUI loads models for well over a minute. Without this the closing report
# races its startup and claims image generation is unavailable on a run that in
# fact just launched it.
if [[ "$comfy_started" -eq 1 ]]; then
    printf 'Waiting for ComfyUI '
    for _ in $(seq 1 40); do
        if port_open 8188; then
            break
        fi
        printf '.'
        sleep 3
    done
    printf '\n'
fi

echo ''
echo 'AniOS is up:'
echo '  Frontend  http://localhost:5173'
echo '  API       http://localhost:8000  (docs at /docs)'
if port_open 8188; then
    echo '  ComfyUI   http://localhost:8188  (image generation ready)'
else
    echo '  ComfyUI   not detected on :8188 - image generation will be unavailable.'
fi
