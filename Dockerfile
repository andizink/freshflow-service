# syntax=docker/dockerfile:1
# Multi-stage build: dependencies resolved with uv in a builder stage,
# runtime stage is a minimal python:3.12-slim image running as non-root.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /usr/sbin/nologin freshflow

WORKDIR /app

COPY --from=builder --chown=freshflow:freshflow /app/.venv /app/.venv
COPY --from=builder --chown=freshflow:freshflow /app/app /app/app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    FRESHFLOW_DB_PATH=/data/freshflow.db

RUN mkdir -p /data && chown freshflow:freshflow /data

USER freshflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
