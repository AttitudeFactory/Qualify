set shell := ["bash", "-cu"]

# `just` with no target lists the recipes.
default:
    @just --list

# One-command dev environment (the founder's ask): infra up -> migrate -> seed.
# `--wait` blocks until Postgres + Redis pass their healthchecks, so migrate never
# races a cold DB.
dev: up migrate seed

# Sync the default workspace env (backend + crm + dev; NO torch). Use
# `uv sync --group ml` when you need the models package.
sync:
    uv sync

up:
    docker compose up -d --wait

# DDL + RLS + roles, run as qualify_owner (see migrations/postgres/env.py).
migrate:
    uv run alembic upgrade head

# Reversible teardown of the schema (roles/tables/policies) — must land clean.
migrate-down:
    uv run alembic downgrade base

# Seeds the two real tenants via admin_session() (qualify_admin, BYPASSRLS):
# PuntoServis (CO, 1 owner seat) + the inmobiliaria (UY, 1 owner + N agents).
seed:
    uv run python -m qualify_api.seed

# QUA-66: register a new business (assigns a tenant_id automatically) — same service
# the /signup page uses. Prompts for the password. Example:
#   just register-business "Polet Bubble Tea" hlrd1993+polet@gmail.com VE America/Caracas USD
register-business name email country timezone currency:
    uv run python -m qualify_api.auth.provision register \
        --name "{{name}}" --email "{{email}}" --country "{{country}}" \
        --timezone "{{timezone}}" --currency "{{currency}}"

# QUA-66: attach a login to an EXISTING tenant (e.g. the seeded ones).
link-login tenant email:
    uv run python -m qualify_api.auth.provision link --tenant "{{tenant}}" --email "{{email}}"

# Default test pass: unit + db, never external network. Mirrors CI.
test:
    uv run pytest -m "not integration"

# Only the tests that need the local Postgres/Redis from docker-compose.
test-db:
    uv run pytest -m "db"

# Browser E2E suite (Playwright) — tests/e2e, organised by module × market niche.
# Boots its own `reflex run` in fake-auth mode (QUALIFY_AUTH_FAKE=1) on 3390/8390 and
# needs the compose Postgres up (`just up`). One-time setup:
#   uv sync --group e2e && uv run playwright install chromium
# To reuse an app you already have running in fake-auth mode (launch.json
# `qualify-crm-fake-auth`, port 3400): QUALIFY_E2E_BASE_URL=http://localhost:3400 just e2e
e2e *ARGS:
    PYTHONPATH=packages/api/src:packages/shared/src:packages/scraper/src:packages/creative/src:packages/models/src \
        uv run --no-sync pytest tests/e2e -o addopts="" -p no:cacheprovider --browser chromium {{ARGS}}

# Same, watching the browser (debug a flaky selector).
e2e-headed *ARGS:
    just e2e --headed --slowmo 250 {{ARGS}}

lint:
    uv run ruff check .

fmt:
    uv run ruff format .

# -v drops the pgdata volume: a clean slate for the next `just dev`.
down:
    docker compose down -v
