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

# TLS group pinning, for the network rather than for security.
#
# python:3.12-slim now ships OpenSSL 3.5, which offers the post-quantum
# X25519MLKEM768 key share by default. Some middlebox between this machine
# and the internet silently drops the resulting ClientHello: the TCP
# connection completes and the handshake then hangs until it times out.
# Measured on spark1 on 2026-09-18 against pypi.org, same container, same
# second: the default groups time out after 8s, `Groups = x25519:secp256r1`
# completes TLS 1.3 in 0.01s. The host's own OpenSSL is 3.0.13, which never
# offers the post-quantum share, which is why pip worked from the host and
# failed inside every build.
#
# Both groups named here are the standard classical ones, so this costs
# nothing but the post-quantum hedge on this machine's build traffic.
# Delete the block once the network stops dropping those handshakes; the
# symptom is `pip install` looping on "Read timed out" while curl on the
# host is fine.
COPY docker/classic-tls-groups.cnf /etc/ssl/classic-tls-groups.cnf
ENV OPENSSL_CONF=/etc/ssl/classic-tls-groups.cnf

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
# The unit gate collects the market chronology tests, which import the
# exchange calendar even though production serving does not need it.
# Keep this range aligned with pyproject.toml's research extra; do not
# install the training stack just to validate saved research artifacts.
RUN pip install --no-cache-dir "pytest>=8.0.0" "pytest-asyncio>=0.23.0" \
    "pytest-xdist>=3.5.0" "ruff>=0.4.0" \
    "exchange-calendars>=4.13.2,<5.0.0"

# `runtime` is LAST on purpose. BuildKit's default target is the final stage and
# it does not build stages that target does not depend on, so every `build: .`
# service keeps producing the same image with no `target:` key anywhere. Adding
# `target: runtime` to six services would be a footgun: miss one and it silently
# ships pytest - and the test stage's tooling - into a serving container.
FROM base AS runtime

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
