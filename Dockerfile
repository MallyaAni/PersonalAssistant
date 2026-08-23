FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
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
RUN pip install --no-cache-dir "pytest>=8.0.0" "pytest-asyncio>=0.23.0"

# `runtime` is LAST on purpose. BuildKit's default target is the final stage and
# it does not build stages that target does not depend on, so every `build: .`
# service keeps producing the same image with no `target:` key anywhere. Adding
# `target: runtime` to six services would be a footgun: miss one and it silently
# ships pytest - and the test stage's tooling - into a serving container.
FROM base AS runtime

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
