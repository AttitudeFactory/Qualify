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

# Recompute stored referentes computed by an older algorithm (PHASED_PLAN_VERSION went up).
# SPENDS Scrape Creators credits — always look first:
#   just refresh-referentes --dry-run
#   just refresh-referentes --max-credits 40 [--tenant <uuid>] [--brand <uuid>]
refresh-referentes *args:
    uv run --no-sync python -m Qualify.refresh_referentes {{args}}

# Classify, with Claude (Haiku 4.5), the catalog hashtags the rules left open.
# SPENDS Anthropic credits (~$0.005 per batch of 80) — look first:
#   just classify-hashtags --dry-run
#   just classify-hashtags --max-batches 10
classify-hashtags *args:
    uv run --no-sync python -m Qualify.classify_hashtags {{args}}

# QUA-111: the calendar executor (claim → publish → advance → settle). PUBLISHES FOR REAL
# to the connected accounts of the tenants in scope. Scope is mandatory:
#   just calendar-tick --tenant <uuid>     # one tick, that tenant only (use this locally)
#   just calendar-tick --all-tenants       # one tick, every tenant (production; e.g. cron)
calendar-tick *args:
    uv run --no-sync python -m qualify_api.planner.worker --once {{args}}

# QUA-111: the calendar worker — a tick every --interval seconds (default 60) until Ctrl+C.
#   just calendar-worker --tenant <uuid>
#   just calendar-worker --all-tenants [--interval 60]
calendar-worker *args:
    uv run --no-sync python -m qualify_api.planner.worker {{args}}

# Default test pass: unit + db, never external network. Mirrors CI.
# Tests use `qualify_test` + Redis db 15, NEVER the dev `qualify` (root conftest.py aborts
# otherwise). Data a run leaves in `qualify_test` is kept for inspection — no auto reset.
test:
    uv run pytest -m "not integration"

# Only the tests that need the local Postgres/Redis from docker-compose.
test-db:
    uv run pytest -m "db"

# DROP + CREATE + migrate `qualify_test` and flush Redis db 15. Explicit and destructive
# ONLY for the test database — refuses to run against `qualify`.
test-db-reset:
    uv run python testing/testdb.py reset

# A clean `qualify_test`, then the default test pass.
test-fresh:
    uv run pytest --reset-test-db -m "not integration"

lint:
    uv run ruff check .

fmt:
    uv run ruff format .

# -v drops the pgdata volume: a clean slate for the next `just dev`.
down:
    docker compose down -v

# Remotion Studio on the host (hot reload) for authoring packages/render templates.
render-dev:
    cd packages/render && npm install && npm run dev

# Rebuild the render service image (packages/render/Dockerfile). `just up` starts it.
render-build:
    docker compose build render

render-logs:
    docker compose logs -f render

# End-to-end smoke test against the running render service (uploads, renders, downloads).
render-smoke base="http://127.0.0.1:3200":
    packages/render/scripts/smoke.sh {{base}}
