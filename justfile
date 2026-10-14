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

# QUA-147: the Meta webhook intake processor. Settles recorded changes (mentions ->
# resolution + ingestion; every other field, comments included -> `unsupported`).
#   just webhook-tick                 # one batch, then exit
#   just webhook-worker [--interval 30]   # a batch every N s until Ctrl+C; also runs the
#                                         # 29-day retention purge at start and every 24 h
webhook-tick *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --once {{args}}

webhook-worker *args:
    uv run --no-sync python -m qualify_api.webhooks.worker {{args}}

# QUA-147: retention purges. DRY RUN unless --execute (they print what they would delete).
#   just webhook-purge [--execute]                        # > 29 days, never pending/processing
#   just webhook-purge-account <ig_account_id> [--execute]  # one account, any state (QUA-127)
webhook-purge *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --purge {{args}}

webhook-purge-account account *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --purge-account {{account}} {{args}}

# WA-06: manual smoke of the WhatsApp Cloud API client against the test number. DEV ONLY —
# reads QUALIFY_WA_SYSTEM_USER_TOKEN and QUALIFY_WA_PHONE_NUMBER_ID from the environment,
# sends for real, prints only the wamid(s).
#   just whatsapp-smoke --to +57300... --text "hola" [--buttons] [--phone-number]
whatsapp-smoke *args:
    uv run --no-sync python -m qualify_api.whatsapp.smoke {{args}}

# --- Production (Hetzner VPS, docs/despliegue-hetzner.md) ---------------------------------
# `target` = the server's ssh target, e.g. deploy@203.0.113.10.
#   just deploy deploy@<ip>               # origin/main
#   just deploy deploy@<ip> <sha|branch>  # a specific ref (rollback = an older sha)
# Ship a COMMITTED ref to the server: build there, migrate, restart, print health.
deploy target ref="origin/main":
    deploy/deploy.sh deploy {{target}} {{ref}}

# Containers + health checks through Caddy.
deploy-status target:
    deploy/deploy.sh status {{target}}

# Follow production logs: all services, or one (api | reflex | caddy | migrate | postgres | redis).
deploy-logs target service="":
    deploy/deploy.sh logs {{target}} {{service}}

# pg_dump now (the nightly cron runs the same script on the server).
deploy-backup target:
    deploy/deploy.sh backup {{target}}

# Values never reach argv or the terminal; the output shows an 8-char sha256 fingerprint per
# key, and a backup of .env.prod is kept. --dry-run compares without writing.
#   just env-push qualify-prod SCRAPECREATORS_API_KEY [MORE_KEYS...]
#   just env-push qualify-prod --dry-run SCRAPECREATORS_API_KEY
# Copy KEYs from your local .env into .env.prod; recreate only the services they change.
env-push target *keys:
    deploy/deploy.sh env-push {{target}} {{keys}}

# Claude Code on the server as `deploy`, for Remote Control (docs/despliegue-hetzner.md §13).
# `target` must log in as ROOT (the `qualify-prod` alias). Login is by hand afterwards.
#   just claude-bootstrap qualify-prod
claude-bootstrap target:
    ssh {{target}} 'bash -s' < deploy/bootstrap-claude.sh
    ssh {{target}} 'cat > /opt/qualify/CLAUDE.md && chmod 644 /opt/qualify/CLAUDE.md' < deploy/claude-server.md

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

# --- CI mirrors (.github/workflows/ci.yml) ------------------------------------------
# Same commands the workflow runs, so a red job can be reproduced here before pushing.

# `lint` job: ruff check + format --check (the workflow installs only the `dev` group).
ci-lint:
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .

# `test` job: offline tests with coverage per package. XML in coverage.xml, table in
# coverage-summary.md (what the PR comment shows). `db` tests run in the `test-db` job
# (`just test-db` here); `integration` never runs in CI.
ci-test:
    uv run --no-sync pytest -m "not integration and not db and not slow" \
        --cov=packages/api/src --cov=packages/shared/src --cov=packages/scraper/src \
        --cov=packages/creative/src --cov=Qualify \
        --cov-report=xml:coverage.xml --cov-report=term-missing:skip-covered
    uv run --no-sync coverage json -o coverage.json
    uv run --no-sync python .github/scripts/coverage_summary.py coverage.json | tee coverage-summary.md

# `deps` job of security.yml: known vulnerabilities in the locked default groups (never
# `ml`/torch) via pip-audit, plus `npm audit` for packages/render when it exists. Needs
# network (advisory DBs); informational, exit code is not a gate.
audit:
    uv export --frozen --no-hashes --no-emit-workspace --no-annotate --no-header -o requirements.txt
    -uvx "pip-audit==2.10.1" -r requirements.txt --no-deps --desc on
    if [ -f packages/render/package-lock.json ]; then (cd packages/render && npm audit --audit-level=high); fi

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

# --- Puerta de merge (infra/github/README.md) ---------------------------------------
# Sin branch protection en GitHub Free, la regla "CI en verde para mergear" vive aquí:
# `just merge 81` se niega si falta o falló alguno de los checks requeridos; un admin puede
# forzar a propósito con `just merge 81 --admin` (queda un comentario en el PR).
#
# REST only (`gh api`), never `gh pr view/merge/comment`: those go through GraphQL, which
# Claude Code cloud sessions cannot reach — this way the same gate works from the Mac and
# from the cloud. The rollup = latest check run per name + commit statuses on the PR head.
merge pr *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    repo=repos/AttitudeFactory/Qualify
    required="changes lint test test-db node-render docker-deploy"
    pr_state=$(gh api "$repo/pulls/{{pr}}" --jq '"\(.state) \(.merged) \(.head.sha)"')
    read -r state merged sha <<<"$pr_state"
    [ "$state" = open ] || { echo "just merge: #{{pr}} no está abierto (state=$state merged=$merged)." >&2; exit 1; }
    rollup=$(
      gh api "$repo/commits/$sha/check-runs?per_page=100" --jq '.check_runs[] | "\(.name)=\((.conclusion // .status) | ascii_upcase)"'
      gh api "$repo/commits/$sha/status" --jq '.statuses[] | "\(.context)=\(.state | ascii_upcase)"'
    )
    missing=""; failed=""
    for job in $required; do
      state=$(printf '%s\n' "$rollup" | awk -F= -v j="$job" '$1==j {print $2; exit}')
      case "${state:-}" in
        SUCCESS|SKIPPED) ;;
        "") missing="$missing $job" ;;
        *) failed="$failed $job=$state" ;;
      esac
    done
    if [ -n "$missing$failed" ] && [ "{{flags}}" != "--admin" ]; then
      echo "just merge: NO se mergea #{{pr}}." >&2
      [ -n "$failed" ] && echo "  checks fallidos o en curso:$failed" >&2
      [ -n "$missing" ] && echo "  checks sin reportar:$missing" >&2
      echo "  Un administrador puede forzar a propósito: just merge {{pr}} --admin" >&2
      exit 1
    fi
    if [ "{{flags}}" = "--admin" ] && [ -n "$missing$failed" ]; then
      gh api "$repo/issues/{{pr}}/comments" -f body="Merge forzado por un administrador con \`just merge --admin\` con checks pendientes o fallidos:$failed$missing" >/dev/null
    fi
    # `sha` pins the merge to the head that was checked: a push after the check is refused.
    gh api -X PUT "$repo/pulls/{{pr}}/merge" -f merge_method=merge -f sha="$sha" --jq '"#{{pr}}: \(.message) (\(.sha))"'

# Aplica la regla de `main` (requiere GitHub Team o repo público; ver infra/github/README.md).
protect-main:
    gh api -X POST repos/AttitudeFactory/Qualify/rulesets --input infra/github/ruleset-main.json
