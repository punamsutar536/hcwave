# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# hcwave backend image – one image, three roles selected by the command:
#   hcwave-api      FastAPI public (:8000) + internal (:8001) listeners
#   hcwave-worker   Service Bus / Redis queue consumer (:8080 health)
#   hcwave-jobs X   scheduled job (Kubernetes CronJob)
# Build from the repository root:  docker build -f services/backend/Dockerfile .
# -----------------------------------------------------------------------------
# Base image is a build arg so regulated environments can pull it from their
# own mirror (e.g. <acr>.azurecr.io/library/python:3.12-slim).
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY services/backend/pyproject.toml services/backend/README.md ./
COPY services/backend/src ./src
# EXTRAS selects cloud adapters: "azure" (default), "portable" or "azure,portable".
ARG EXTRAS=azure,portable
# Optional corporate CA bundle for TLS-inspecting proxies:
#   docker build --secret id=ca_bundle,src=/path/ca.pem ...
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi \
 && python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install ".[${EXTRAS}]"

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="hcwave-backend" \
      org.opencontainers.image.description="Hospital AI Wave 1 backend (API, worker, jobs)"
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HCWAVE_CONFIG_DIR=/app/config \
    HCWAVE_ENV_FILE=/nonexistent/.env \
    APP_ENV=prod
RUN groupadd --system --gid 10001 hcwave \
 && useradd --system --uid 10001 --gid hcwave --home-dir /app --shell /usr/sbin/nologin hcwave \
 && apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY config ./config
COPY services/backend/alembic.ini ./alembic.ini
COPY services/backend/migrations ./migrations
USER 10001:10001
EXPOSE 8000 8001 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["hcwave-api"]
