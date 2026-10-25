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

# Invite someone to register their own business — the ONLY way in for the MVP. Stores a
# single-use, 7-day invite and emails it via Resend (QUALIFY_RESEND_API_KEY /
# QUALIFY_MAIL_FROM; signed as QUALIFY_INVITE_SIGNER). The link is printed too, so it can be
# shared by hand. Name, business and note are optional:
#   just invite maria@arepera.com María "Arepera La Nona" "Como hablamos hoy, aquí va tu acceso."
invite email name="" business="" note="":
    uv run python -m qualify_api.auth.provision invite --email "{{email}}" \
        --name "{{name}}" --business "{{business}}" --note "{{note}}"

# QUA-66: register a new business (assigns a tenant_id automatically) — same service
# the /registro page uses. Prompts for the password. Example:
#   just register-business "Polette" hlrd1993+polet@gmail.com VE America/Caracas USD
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

# m-24828907: the piece purge — R2 files of pieces 90 days past their last use. The
# calendar worker already runs it daily, for real (QUALIFY_PIECE_PURGE_EXECUTE=0 turns that
# off); this runs it once, now. DRY RUN unless --execute. Scope is mandatory:
#   just piece-purge --tenant <uuid> [--execute]     # use this locally
#   just piece-purge --all-tenants [--execute]       # production
piece-purge *args:
    uv run --no-sync python -m qualify_api.planner.worker --purge-pieces {{args}}

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

# Requeue Instagram `comments` recorded as unsupported before their handler existed, so
# own-post comments that @mention the account become mentions. Dry run unless --execute.
#   just webhook-requeue-comments [--account <ig_account_id>] [--execute]
webhook-requeue-comments *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --requeue-comments {{args}}

# m-24789472: requeue Instagram postbacks (Ice Breakers, buttons, menu) recorded as
# `unsupported` before Conversaciones read them. Dry run unless --execute.
#   just webhook-requeue-postbacks [--account <ig_account_id>] [--execute]
webhook-requeue-postbacks *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --requeue-postbacks {{args}}

# WA-06: manual smoke of the WhatsApp Cloud API client against the test number. DEV ONLY —
# reads QUALIFY_WA_SYSTEM_USER_TOKEN and QUALIFY_WA_PHONE_NUMBER_ID from the environment,
# sends for real, prints only the wamid(s).
#   just whatsapp-smoke --to +57300... --text "hola" [--buttons] [--phone-number]
whatsapp-smoke *args:
    uv run --no-sync python -m qualify_api.whatsapp.smoke {{args}}

# WA-05: connect a WhatsApp Business number to a tenant (administrative, no OAuth). The
# system-user token comes from QUALIFY_WA_SYSTEM_USER_TOKEN in the environment of THIS ONE
# process only: it is verified (/debug_token + GET /{phone_number_id}), encrypted into
# oauth_credentials and never printed. Re-running rotates the credential and refreshes the
# number's metadata. Exit 2 = token rejected/missing scopes, 3 = Meta auth error (nothing
# written in either case).
#   QUALIFY_WA_SYSTEM_USER_TOKEN=... just whatsapp-connect --tenant <uuid> --brand <uuid> \
#       --waba-id <id> --phone-number-id <id>
whatsapp-connect *args:
    uv run --no-sync python -m qualify_api.whatsapp.connect {{args}}

# WA-08: the WhatsApp outbox sender (claim → 24 h window → pacing → send → settle). SENDS
# FOR REAL from the connected numbers of the tenants in scope. Scope is mandatory:
#   just whatsapp-tick --tenant <uuid>     # one pass, that tenant only (use this locally)
#   just whatsapp-tick --all-tenants       # one pass, every tenant (production)
whatsapp-tick *args:
    uv run --no-sync python -m qualify_api.whatsapp.worker --once {{args}}

# WA-08: the WhatsApp worker — a pass every --interval seconds (default 5) until Ctrl+C.
#   just whatsapp-worker --tenant <uuid>
#   just whatsapp-worker --all-tenants [--interval 5]
whatsapp-worker *args:
    uv run --no-sync python -m qualify_api.whatsapp.worker {{args}}

# QUA-226: the private-conversations outbox sender (claim → 24 h window → channel send →
# settle). With the real channel it SENDS FOR REAL through Instagram; with
# QUALIFY_CONVERSATIONS_DM_CHANNEL=memory nothing leaves the process. Scope is mandatory:
#   just conversations-tick --tenant <uuid> [--sync]   # one pass (use this locally)
#   just conversations-tick --all-tenants [--sync]     # one pass, every tenant (production)
conversations-tick *args:
    uv run --no-sync python -m qualify_api.conversations.worker --once {{args}}

# QUA-226: the conversations worker — a pass every --interval seconds (default 5) until
# Ctrl+C; `--sync` adds the Instagram reconciliation poll (at most every --sync-interval
# seconds, default 300 — Development Mode budgets 200 calls/h per Page/app pair).
#   just conversations-worker --tenant <uuid> [--sync]
#   just conversations-worker --all-tenants [--sync] [--interval 5] [--sync-interval 300]
conversations-worker *args:
    uv run --no-sync python -m qualify_api.conversations.worker {{args}}

# QUA-226: one pass of the reconciliation poll only (no sending).
#   just conversations-sync --tenant <uuid>
conversations-sync *args:
    uv run --no-sync python -m qualify_api.conversations.worker --once --sync-only {{args}}

# QUA-226: seed sample private conversations through the IN-MEMORY channel so /conversations
# can be validated on localhost without Meta. Refuses unless
# QUALIFY_CONVERSATIONS_DM_CHANNEL=memory is set (same value the app must run with).
#   QUALIFY_CONVERSATIONS_DM_CHANNEL=memory just conversations-seed --tenant <uuid> [--connection <uuid>]
conversations-seed *args:
    uv run --no-sync python -m qualify_api.conversations.devseed {{args}}

# m-24789644 (R1): does Meta serve a story's comments? Read-only probe for one REAL
# connection, with `story_comments` still off; prints a JSON report (no tokens, no comment
# text). Steps and how to record the result: docs/conversaciones-limitaciones-meta.md.
#   just story-probe --tenant <uuid> --connection <uuid>
story-probe *args:
    uv run --no-sync python -m qualify_api.inbox.story_probe {{args}}

# m-24852202: optional, one-off — keep in R2 the picture of publications monitored before
# pictures were stored. One Meta read per publication (200/hour ledger); idempotent.
#   just inbox-thumbs-backfill --tenant <uuid> --connection <uuid> [--limit 50]
inbox-thumbs-backfill *args:
    uv run --no-sync python -m qualify_api.inbox.thumbnails_backfill {{args}}

# m-24852203: dev-only Meta READ simulator for Interacciones. Run the app with
# QUALIFY_META_READS=fixture (synthetic dev/meta-fixtures/inbox.json, any connection, no
# token); refused where QUALIFY_DEPLOY_ENV=production. Replies/publishing stay real.
# This recipe writes a LOCAL fixture from a connection's own rows (real data: keep it out
# of git) to use with QUALIFY_META_READS_FIXTURE=<path>.
#   just inbox-fixture-export --tenant <uuid> --connection <uuid> --out <path>
inbox-fixture-export *args:
    uv run --no-sync python -m qualify_api.inbox.fixture_export {{args}}

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

# m-24852538: webhook-worker's peak memory under its prod mem_limit, LOCALLY (idle, a webhook
# batch, one Alta prefill with fake vendors; `-- --sentiment` adds robertuito). Throwaway
# Postgres on a docker network with no route out; never touches production. Image: build
# `docker build -f deploy/Dockerfile --target deps -t qualify-memtest:deps .` first, or pass
# a CI image. `MEM_LIMIT=320m just mem-webhook-worker` tries another cap.
mem-webhook-worker image="qualify-memtest:deps" *args:
    deploy/measure/webhook-worker-memory.sh {{image}} -- {{args}}

# pg_dump now (the nightly cron runs the same script on the server).
deploy-backup target:
    deploy/deploy.sh backup {{target}}

# The VPS edge proxy (deploy/edge/): the only listener on 80/443, TLS for every product on the
# box, owned by none of them. Copies deploy/edge/ to the server and runs install.sh there
# (idempotent). One-time cutover from the old setup (Qualify's Caddy on 80/443):
#   just edge-install <target> --wait-for-ports   # leave it waiting, THEN deploy Qualify
# Later route changes: edit deploy/edge/Caddyfile, run `just edge-install <target>` again.
# Runbook: docs/despliegue-hetzner.md, "Proxy de entrada".
edge-install target *args:
    ssh {{target}} 'rm -rf /tmp/qualify-edge && mkdir -p /tmp/qualify-edge'
    scp -q deploy/edge/Caddyfile deploy/edge/docker-compose.yml deploy/edge/.env.example deploy/edge/install.sh {{target}}:/tmp/qualify-edge/
    ssh -t {{target}} 'bash /tmp/qualify-edge/install.sh {{args}}'

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

# The lint steps of the `test` job: ruff check + format --check.
ci-lint:
    uv run --no-sync ruff check .
    uv run --no-sync ruff format --check .

# `test` job: offline tests with coverage per package. XML in coverage.xml, table in
# coverage-summary.md (what the PR comment shows). `db` tests run later in the same job
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

# --- ScrapeCreators CLI (.claude/skills/qualify-scrapecreators) --------------------
# Runs the official CLI with the project's key. Live calls spend credits.
[positional-arguments]
sc *args:
    @if [ -z "${SCRAPECREATORS_API_KEY:-}" ] && [ -f .env ]; then export SCRAPECREATORS_API_KEY="$(grep -m1 '^SCRAPECREATORS_API_KEY=' .env | cut -d= -f2- | tr -d "\"' ")"; fi; [ -n "${SCRAPECREATORS_API_KEY:-}" ] || { echo "Falta SCRAPECREATORS_API_KEY (.env o shell)" >&2; exit 1; }; command -v scrapecreators >/dev/null || { echo "Instala la CLI: npm install -g @scrapecreators/cli" >&2; exit 1; }; scrapecreators "$@"

# --- Langfuse autoalojado (docs/plan-observabilidad-langfuse.md §3, etapa A) ----------
# Its own compose project: `just down` never touches the traces. UI on http://localhost:3100.
langfuse := "docker compose -f infra/langfuse/docker-compose.yml"

# Writes infra/langfuse/.env with random secrets, the first user and the project keys.
# Never overwrites an existing one (its secrets encrypt Langfuse's data).
langfuse-init:
    uv run --no-sync python infra/langfuse/init_env.py

# Starts Langfuse and waits until its API answers.
langfuse-up: langfuse-init
    {{langfuse}} up -d --wait
    for i in $(seq 1 90); do curl -fsS http://localhost:3100/api/public/health >/dev/null 2>&1 && { echo "Langfuse listo: http://localhost:3100"; exit 0; }; sleep 2; done; echo "Langfuse no respondió en 3 minutos: just langfuse-logs" >&2; exit 1

# Stops Langfuse and KEEPS its data (no -v).
langfuse-down:
    {{langfuse}} down

langfuse-logs *args:
    {{langfuse}} logs -f {{args}}

# Drops Langfuse's volumes: every trace, dataset and score. infra/langfuse/.env stays.
langfuse-reset:
    {{langfuse}} down -v

# Score configs + the «Revisión de imagen y video» annotation queue (plan §8). Once per
# Langfuse server; idempotent.
langfuse-setup:
    PYTHONUTF8=1 uv run --no-sync --env-file .env python -c "from qualify_api.creative.review import main; raise SystemExit(main())"

# Model experiments in Langfuse (docs/plan-observabilidad-langfuse.md §7). They SPEND REAL
# MONEY (Claude calls) and need `just langfuse-up`; never part of CI.
# `just eval-copy --limit 3` is a pilot; `--configs opus-5.5@low` runs one config.
eval-copy *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/copy_ai/run_experiment.py {{args}}

eval-hashtags *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/hashtag_ai/run_experiment.py {{args}}

# Fase 6 (plan §7): referentes (real labelled accounts), Brand Kit documents (fictional),
# ad-image scenes (Seedream, images go to the review queue) and local Whisper (needs `ml`).
eval-referentes *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/referentes_ai/run_experiment.py {{args}}

eval-documentos *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/brief_ai/run_experiment.py {{args}}

eval-escenas *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/scenes_ai/run_experiment.py {{args}}

# m-24849234: Seedream 5.0 pro color/texture matrix. `--dry-run` quotes it and sends nothing;
# a paid run needs --i-have-spend-authorization (the founder authorizes each one).
eval-plantillas *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py {{args}}

# The scene images from Langfuse to packages/api/evals/scenes_ai/imagenes/ (git-ignored).
eval-escenas-imagenes:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/scenes_ai/export_images.py

# ATENDER-4a (m-24848532): comment triage (Haiku 5.5) + public drafts for any comment.
# `--agreement` is free (κ only); `--classify`, `--baseline` and `--drafts` call Claude.
eval-replies *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/replies_ai/run_experiment.py {{args}}

# PB-6 (m-24852200): real cost of one Alta prefill — LIVE credits + tokens, local stack only.
eval-precarga *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/alta_prefill_cost/run_experiment.py {{args}}

eval-voz *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/voice_ai/run_experiment.py {{args}}

# Once per machine: the six Colombian Spanish recordings (OpenSLR 72, ~31 MB, git-ignored).
eval-voz-audio:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/voice_ai/fetch_audio.py

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
    # `test` must always report. The others live in path-filtered workflows (images.yml,
    # render.yml) that start no runner when the PR does not touch their inputs, so they are
    # required only when they reported — and then they must be green.
    required="test"
    required_if_present="docker-deploy node-render docker-render"
    pr_state=$(gh api "$repo/pulls/{{pr}}" --jq '"\(.state) \(.merged) \(.head.sha)"')
    read -r state merged sha <<<"$pr_state"
    [ "$state" = open ] || { echo "just merge: #{{pr}} no está abierto (state=$state merged=$merged)." >&2; exit 1; }
    rollup=$(
      gh api "$repo/commits/$sha/check-runs?per_page=100" --jq '.check_runs[] | "\(.name)=\((.conclusion // .status) | ascii_upcase)"'
      gh api "$repo/commits/$sha/status" --jq '.statuses[] | "\(.context)=\(.state | ascii_upcase)"'
    )
    missing=""; failed=""
    for job in $required $required_if_present; do
      state=$(printf '%s\n' "$rollup" | awk -F= -v j="$job" '$1==j {print $2; exit}')
      case "${state:-}" in
        SUCCESS|SKIPPED) ;;
        "") case " $required " in *" $job "*) missing="$missing $job" ;; esac ;;
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

# Playwright browser tests (tests/e2e) — never part of CI. Boots the app on 3390/8390 with
# fake auth and open signup, or uses QUALIFY_E2E_BASE_URL. Needs the compose Postgres
# (`just up`) and a Chromium (`uv run --with playwright playwright install chromium`).
e2e *ARGS:
    uv run --no-sync --with pytest-playwright pytest tests/e2e -p no:cacheprovider -o addopts="--import-mode=importlib" {{ARGS}}
