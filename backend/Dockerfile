# syntax=docker/dockerfile:1
FROM python:3.13.5-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh ./
RUN useradd --system --uid 10001 marketops && chmod +x docker-entrypoint.sh
USER marketops

EXPOSE 8000
# Exactly one worker: the simulator, sequence allocator, and connection registry are in-process
# (ADR 0002). Do not add --workers or replicas without a shared broadcast design.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
