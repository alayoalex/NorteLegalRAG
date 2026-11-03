# Una sola imagen para api, worker y migrate: mismo código, distinto comando.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencias primero, para que cambiar código no invalide esta capa.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# Sin root. El directorio existe antes de montar el volumen para heredar el propietario.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/blobs \
    && chown -R app:app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "norte_legal.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
