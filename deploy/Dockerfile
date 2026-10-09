# syntax=docker/dockerfile:1.7
#
# Qualify production images, built from the repo root:
#
#   docker build -f deploy/Dockerfile --target app .   # Python: FastAPI api, Reflex backend,
#                                                      # migrations, calendar worker
#   docker build -f deploy/Dockerfile --target web .   # Caddy + the static Reflex frontend
#
# Why ONE Python image for both the FastAPI api and the Reflex backend: they share the
# exact same dependency closure. The Reflex process already imports `qualify_api` in-process
# (connections/publishing services, and `inbox_provider.py` drives `create_app()` through
# `httpx.ASGITransport`), so a separate "api-only" image would hold the same packages and
# only add a second build to keep in sync. The two containers differ only by command.
#
# Why a SECOND image for the frontend: `reflex export --frontend-only` produces static
# files, so the frontend needs no Python/Node process in production at all — Caddy (already
# the TLS terminator) serves them directly. The export toolchain (bun, node_modules) stays
# in a throwaway build stage and never reaches a runtime image.
#
# Never installed: the full `ml` group (whisper, torchvision, accelerate, av) and `dev`.
# `qualify_models` is put on PYTHONPATH instead (same mechanism the root pytest config uses
# in CI) because the CRM imports its PURE `permission_capability` table at module load.
# What IS installed from that world is the `sentiment` group — CPU-only torch +
# transformers + huggingface_hub — because robertuito runs on this VPS (founder decision,
# zero API cost), with its weights baked into the image at build time (see `deps`).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29
ARG CADDY_IMAGE=caddy:2.10-alpine
# Reflex 0.9.12 requires bun >= 1.4.0 (reflex_base.constants.Bun.MIN_VERSION) and uses one
# found on PATH instead of downloading its own — same pattern as Reflex's official
# docker-example/production-compose.
ARG BUN_IMAGE=oven/bun:1.4

FROM ${UV_IMAGE} AS uv
FROM ${BUN_IMAGE} AS bun

# --------------------------------------------------------------------------------------
# deps: the locked virtualenv (backend + crm groups), workspace members installed editable
# --------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Layer 1: third-party dependencies only, keyed on the lock + every member's manifest (a
# workspace sync needs all members' pyproject.toml present, even the ones not installed).
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml packages/api/README.md packages/api/
COPY packages/creative/pyproject.toml packages/creative/README.md packages/creative/
COPY packages/docs-harvester/pyproject.toml packages/docs-harvester/README.md packages/docs-harvester/
COPY packages/models/pyproject.toml packages/models/README.md packages/models/
COPY packages/scraper/pyproject.toml packages/scraper/README.md packages/scraper/
COPY packages/shared/pyproject.toml packages/shared/README.md packages/shared/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --group sentiment

# robertuito's weights (~435 MB), fetched once at build so a container never downloads them
# on its first analysis — plus one real classification, so a model or runtime that cannot
# run in this image fails the BUILD, not a user's "Analizar sentimiento" click. Placed
# BEFORE the sources so code changes never re-download it. Must equal
# `qualify_models.sentiment.MODEL_ID` (asserted by packages/api/tests/test_deploy_image.py).
ARG SENTIMENT_MODEL_ID=pysentimiento/robertuito-sentiment-analysis
ENV HF_HOME=/app/.cache/huggingface
RUN /app/.venv/bin/python -c "import sys; from transformers import pipeline; \
print(pipeline(task='text-classification', model=sys.argv[1])('me encanta')[0])" \
    "${SENTIMENT_MODEL_ID}"

# Layer 2: the workspace sources, then install the members themselves.
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group sentiment

# The Reflex app itself (repo-root layout: rxconfig.py + Qualify/ + assets/ + reflex.lock/).
COPY rxconfig.py alembic.ini ./
COPY reflex.lock ./reflex.lock
COPY assets ./assets
COPY migrations ./migrations
COPY Qualify ./Qualify
COPY deploy/bootstrap_db_roles.py ./deploy/bootstrap_db_roles.py

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/packages/models/src" \
    PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    HF_HOME=/app/.cache/huggingface

# --------------------------------------------------------------------------------------
# frontend-build: `reflex export --frontend-only` → static files
# --------------------------------------------------------------------------------------
FROM deps AS frontend-build
# bun comes from its official image (no curl/unzip, no download from Reflex's install
# script on every build); the cache mount keeps bun's package cache across builds.
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
# The public origin is baked into the static bundle (env.json): it is where the browser
# opens the `/_event` websocket and fetches `/_upload/*`. Caddy serves frontend and backend
# on this same origin, so there is no CORS and no second hostname.
ARG QUALIFY_PUBLIC_URL=https://qualify.attitudefactory.co
ENV REFLEX_API_URL=${QUALIFY_PUBLIC_URL} \
    REFLEX_DEPLOY_URL=${QUALIFY_PUBLIC_URL}
RUN --mount=type=cache,target=/root/.bun/install/cache \
    reflex export --frontend-only --no-zip --loglevel info \
 && test -f .web/backend/stateful_pages.json \
 && mkdir -p /srv \
 && cp -a .web/build/client/. /srv/

# --------------------------------------------------------------------------------------
# deploy-bundle: the deploy/ directory of this commit, nothing else (`--target deploy-bundle`)
# --------------------------------------------------------------------------------------
# Published next to qualify-app/qualify-web by the CD workflow. The server's forced command
# (deploy/server-deploy.sh) takes the compose file and scripts of a release FROM this image,
# never from whoever holds the ssh key: the key can only deploy a commit CI already published.
FROM scratch AS deploy-bundle
COPY deploy /deploy

# --------------------------------------------------------------------------------------
# web: Caddy (automatic TLS) + the exported frontend
# --------------------------------------------------------------------------------------
FROM ${CADDY_IMAGE} AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-build /srv /srv

# --------------------------------------------------------------------------------------
# app: runtime for api / reflex backend / migrate / calendar-worker (command per service)
# --------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS app
# No apt packages: a `--backend-only` prod backend never touches the JS toolchain (bun,
# curl, unzip), same as Reflex's official production image.
RUN groupadd --system --gid 10001 qualify \
 && useradd --system --uid 10001 --gid qualify --home-dir /app --shell /usr/sbin/nologin qualify \
 && mkdir -p /data/uploaded_files /data/avatars \
 && chown -R qualify:qualify /data
WORKDIR /app
COPY --from=deps --chown=qualify:qualify /app /app
# Writable by the runtime user: /app itself, `.web` (even a skip-compile prod backend writes
# its stateful-pages marker there on boot) and `.states` (Reflex's disk state manager keeps
# per-tab state there — the login lives in it, see Qualify/auth_state.py; created now so the
# named volume mounted on it inherits this ownership).
RUN chown qualify:qualify /app \
 && install -d -o qualify -g qualify /app/.web /app/.states
# `.web/backend` from the export: its stateful_pages.json makes the prod backend evaluate
# only the stateful pages on boot instead of every page (reflex/compiler/compiler.py),
# which shortens the restart window of every deploy. Without it the marker would be
# rebuilt on each boot inside a container that a deploy throws away.
COPY --from=frontend-build --chown=qualify:qualify /app/.web/backend /app/.web/backend
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/packages/models/src" \
    PYTHONUNBUFFERED=1 \
    REFLEX_TELEMETRY_ENABLED=false \
    HF_HOME=/app/.cache/huggingface \
    REFLEX_UPLOADED_FILES_DIR=/data/uploaded_files \
    QUALIFY_AVATAR_DIR=/data/avatars \
    QUALIFY_RENDER_TEMPLATES_DIR=/app/packages/render/templates
USER qualify
EXPOSE 8000
# The default command is the FastAPI api; compose overrides it per service.
CMD ["uvicorn", "--factory", "qualify_api.http.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
