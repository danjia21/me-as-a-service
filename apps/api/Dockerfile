FROM ghcr.io/astral-sh/uv:0.11.31 AS uv

FROM python:3.12.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build/apps/api

COPY --from=uv /uv /usr/local/bin/uv
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/apps/api/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAAS_ENVIRONMENT=production

RUN groupadd --gid 10001 maas \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin maas

WORKDIR /app

COPY --from=builder /build/apps/api/.venv /app/.venv
COPY --chown=maas:maas apps/api/src /app/apps/api/src
COPY --chown=maas:maas apps/api/migrations /app/apps/api/migrations
COPY --chown=maas:maas instance/example /app/instance/example

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]

CMD ["python", "-m", "me_as_a_service"]
