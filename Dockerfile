FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    # The repo MCP server (the reviewer's only window onto code) shells out
    # to git, so every image - serving and test - carries it.
    git \
    # Renders diagram flowcharts to PNG for channels with no browser to run
    # mermaid in - an iMessage bubble cannot execute JavaScript, and a
    # diagram's whole point is legible text a phone can see.
    graphviz \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Test tooling, in its own stage so the six serving images never carry it.
#
# Deliberately not `pip install -e ".[dev]"`: that re-resolves pyproject's
# [project] dependencies block, which duplicates requirements.txt with looser
# pins, and a gate measuring a different dependency set than production
# measures the wrong thing. PYTHONPATH=/app already makes `backend` importable
# and `COPY . .` already ships backend/tests, so the project needs no install.
#
# Keep these floors in step with pyproject's [project.optional-dependencies] dev.
FROM base AS test
# git already comes from the base stage (the repo MCP server needs it in
# every image); only the test tooling is added here.
# ruff is here for the gate, not for style: test_no_undefined_names.py runs
# its F821 check over backend and scripts, because on 2026-09-06 a branch
# calling an unimported name passed the whole suite and the gate, and failed
# every clock-stopped turn live for ten hours.
# pytest-xdist runs the routing gate's five suites at once. See the
# distribution note in scripts/gate.sh for why it is by file and not by
# test.
RUN pip install --no-cache-dir "pytest>=8.0.0" "pytest-asyncio>=0.23.0" \
    "pytest-xdist>=3.5.0" "ruff>=0.4.0"

# `runtime` is LAST on purpose. BuildKit's default target is the final stage and
# it does not build stages that target does not depend on, so every `build: .`
# service keeps producing the same image with no `target:` key anywhere. Adding
# `target: runtime` to six services would be a footgun: miss one and it silently
# ships pytest - and the test stage's tooling - into a serving container.
FROM base AS runtime

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
