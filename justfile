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
# off); this runs it once, now. DRY RUN unless --execute. It also runs VE-12 RA5
# (m-24921060): the reel cuts (`source-window-*.mp4`) of part folders, 30 days after
# they were written, nothing else of the piece. Scope is mandatory:
#   just piece-purge --tenant <uuid> [--execute]     # use this locally
#   just piece-purge --all-tenants [--execute]       # production
#   just piece-purge --tenant <uuid> --pending [--execute]  # m-24973446: delete what R2
#     kept of pieces purged for the app only (bucket lock on t/); dry run without --execute
piece-purge *args:
    uv run --no-sync python -m qualify_api.planner.worker --purge-pieces {{args}}

# m-24823681: consumption ledger daily-sync to Meegle (no --tenant scope: it reads every
# «Alta de cliente» with ledger rows cross-tenant via admin_session). The node-completion
# path is the primary trigger; this is the catch-up. Meegle accepts a repeated comment.
#   just consumption-tick                # one pass, then exit
#   just consumption-worker              # a pass every 24 h until Ctrl+C
consumption-tick *args:
    uv run --no-sync python -m qualify_api.consumption.worker --once {{args}}

consumption-worker *args:
    uv run --no-sync python -m qualify_api.consumption.worker {{args}}

# m-24973635: an Alta client's own logo files + colours into its Brand Kit (draft or
# adopted). WRITES Postgres + R2: --dry-run first; never locally (.env points at the prod
# bucket). Usage: just alta-brand-files --meegle-item <id> --file KIND:NAME=PATH ... --colors ...
alta-brand-files *args:
    uv run --no-sync python -m qualify_api.meegle.alta_brand_files {{args}}

# m-24852145: plans Básico / Plus / Pro, assigned to the business's SUBSCRIPTION (ADR 43).
# Team only (admin_session). Upgrade applies now, downgrade from the next month:
#   just set-plan --tenant <uuid> --plan plus --reason "Pidió más videos" --by herwin@attitudefactory.co
#   just set-plan --tenant <uuid> --plan basico --from 2026-12 --reason "..." --by ...
#   just set-plan --tenant <uuid> --plan ilimitado --reason "Negocio del fundador" --by ...  (internal, never billed)
set-plan *args:
    uv run --no-sync python -m qualify_api.plans.cli set {{args}}

# m-24852145: `just plans` = the catalog in force; `just plans --tenant <uuid>` = the plan
# history of that business's subscription (who, when, why, previous and new plan).
plans *args:
    uv run --no-sync python -m qualify_api.plans.cli history {{args}}

# m-24852129: after the payment, add ONE of the fixed 90-day packs — «+2 videos»,
# «+20 creaciones» or «+10 vistas previas» (never a free quantity). Team only (admin_session):
#   just add-pack --tenant <uuid> --paquete "+2 videos" --reason "Pidió más" --by herwin@attitudefactory.co [--support <id>] [--usd 29] [--payment-ref "..."]
add-pack *args:
    uv run --no-sync python -m qualify_api.plans.cli add-pack {{args}}

# m-24852129: the packs of a business — what is left, when each expires, what was paid.
packs *args:
    uv run --no-sync python -m qualify_api.plans.cli packs {{args}}

# m-24852129: stop a pack counting from now on (never deleted): just revoke-pack <id> --reason "..." --by ...
revoke-pack *args:
    uv run --no-sync python -m qualify_api.plans.cli revoke-pack {{args}}

# m-24852145: cost against charge per subscription and month (team only; never shown in
# the app): just plan-report [--month 2026-10] [--tenant <uuid>]
plan-report *args:
    uv run --no-sync python -m qualify_api.plans.report {{args}}

# m-24852145 (D18): the plan's USD cap alert, once per subscription and month, to Lark
# (QUALIFY_SUPPORT_WEBHOOK_URL). Never pauses anything. The calendar worker runs it daily.
plan-cost-alerts *args:
    uv run --no-sync python -m qualify_api.plans.cost_alerts {{args}}

# m-24852492: compare our Seedance tasks (creative_vendor_tasks) with BytePlus's own task
# list — billed videos not collected, tasks without a piece, pieces without a task.
# READ-ONLY (sends and pays nothing); exit 2 = something to look at. The calendar worker
# already recovers billed videos on its own (QUALIFY_VENDOR_RECOVERY=off turns it off).
#   just creative-tasks-report --tenant <uuid> [--days 7] [--json]   # use this locally
#   just creative-tasks-report --all-tenants [--days 7] [--json]     # production
creative-tasks-report *args:
    uv run --no-sync python -m qualify_api.creative.vendor_reconcile {{args}}

# m-24852158: BytePlus's queue as we live it — tasks at once (p50/p95/max per model
# group), queue wait and render, per day and hour, plus the epic's three triggers.
# READ-ONLY, team only (admin_session; no owner screen reads it).
#   just creative-queue-report [--days 7] [--tz America/Bogota] [--tenant <uuid>] [--json]
creative-queue-report *args:
    uv run --no-sync python -m qualify_api.creative.vendor_queue_report {{args}}

# QUA-147: the Meta webhook intake processor. Settles recorded changes (mentions ->
# resolution + ingestion; every other field, comments included -> `unsupported`).
#   just webhook-tick                 # one batch, then exit
#   just webhook-worker [--interval 5]    # a batch every N s until Ctrl+C; also runs the
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

# m-25018661: requeue Instagram DMs a person unsent (`is_deleted`), recorded as
# `unsupported` before the handler erased them, so the stored copy and the original
# changes are erased. Needs an explicit scope; dry run unless --execute.
#   just webhook-requeue-deleted (--account <ig_account_id> | --all-accounts) [--execute]
webhook-requeue-deleted *args:
    uv run --no-sync python -m qualify_api.webhooks.worker --requeue-deleted {{args}}

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

# m-24955918 (ADR 47): the Galería's media-worker — prepares business videos (FFmpeg,
# H.264 + AAC, first 60 s) and reconciles R2 folders daily. Writes to R2 FOR REAL.
#   just media-worker --tenant <uuid> [--once | --reconcile]   # locally, always --tenant
#   just media-worker --all-tenants                             # production only
media-worker *args:
    uv run --no-sync python -m qualify_api.catalog.media_worker {{args}}

# m-24852163 (ADR 41): the generation queue worker — claims `creative_jobs` fairly (lanes,
# 3 reserved slots, 2 per business, aging), submits to BytePlus once, polls by id, settles;
# plus the recovery of billed BytePlus videos (m-24852492). Once the generator enqueues
# (m-24852166) it SENDS BILLED TASKS TO BYTEPLUS FOR REAL. Scope is mandatory:
#   just creative-tick --tenant <uuid>     # one round, that tenant only (use this locally)
#   just creative-worker --tenant <uuid>   # a round every --interval seconds (default 2)
#   just creative-worker --all-tenants     # production (the compose service)
creative-tick *args:
    uv run --no-sync python -m qualify_api.creative.worker --once {{args}}

creative-worker *args:
    uv run --no-sync python -m qualify_api.creative.worker {{args}}

# m-24854855 (ADR 42 R8): the reels worker — enqueues the weekly «Ideas para tus reels» run
# of every brand opened in the 14 days before its Monday 06:00 local, and runs the queue
# (manual runs first). Only with --all-tenants: an ok run's ideas go to the shared reel
# analysis, each pass drains that queue (the pass of `just reel-analysis-tick`) and its
# 30-day-old sources are purged daily; --tenant never writes those global rows nor R2. A
# run PAYS ScrapeCreators credits and Claude FOR REAL (QUALIFY_SCRAPECREATORS_PAID=0 makes
# it read nothing). Scope is mandatory:
#   just reels-tick --tenant <uuid> [--batch N]   # one pass, that tenant only (use this locally)
#   just reels-tick --tenant <uuid> --dry-run     # what a pass would enqueue now; writes nothing
#   just reels-worker --tenant <uuid>             # a pass every --interval seconds (default 5)
#   just reels-worker --all-tenants               # production (the compose service)
reels-tick *args:
    uv run --no-sync python -m qualify_api.referentes.worker --once {{args}}

reels-worker *args:
    uv run --no-sync python -m qualify_api.referentes.worker {{args}}

# ADR 44 F9 (VE-12, the R8 slice): delete the reel sources and frames the shared analysis
# stored in R2 more than 30 days ago. The reels-worker service does it at start and daily;
# this runs it once, now. DRY RUN unless --execute. Global (the sources belong to no
# business): no --tenant.
#   just reel-purge             # report what would be deleted
#   just reel-purge --execute   # delete for real
reel-purge *args:
    uv run --no-sync python -m qualify_api.referentes.reel_retention {{args}}

# m-24921056 (ADR 44, VE-04a): the shared reel-analysis queue — claims a row (a URL still to
# download first, then what a business asked for), downloads the reel FROM THE NETWORK'S CDN
# for real (no ScrapeCreators credits), stores it under public/reel-analyses/ in R2 FOR REAL.
# Paying is opt-in: only with QUALIFY_REEL_ANALYSIS_DESCRIBE=1 (or --describe for one run) and
# QUALIFY_ANTHROPIC_API_KEY does it describe the reel with Haiku FOR REAL (VE-04c, m-24921058,
# ~USD 0.0055 a typical reel, at most 0.0099; cost on the row); --download-only forces it off.
# Global by design: no --tenant (the rows
# belong to no business). Runs as qualify_reels_worker (QUALIFY_REELS_WORKER_DSN). R8 runs
# the same pass inside the reels-worker service.
#   just reel-analysis-tick [--max 5]      # one pass, then exit
#   just reel-analysis-worker [--interval 5]
reel-analysis-tick *args:
    uv run --no-sync python -m qualify_api.referentes.reel_analysis_worker --once {{args}}

reel-analysis-worker *args:
    uv run --no-sync python -m qualify_api.referentes.reel_analysis_worker {{args}}

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

# m-24957283 (CM-9): the ONE-TIME copy of the uploads volume to R2. DRY RUN unless --apply;
# --delete-local is a separate run. Writes to R2 FOR REAL with --apply: never run it
# locally against the .env's bucket (it is production). Production runbook:
# docs/mudanza-subidas-r2.md §4.
#   just uploads-to-r2 --tenant <uuid> [--apply | --delete-local] [--root uploads]
uploads-to-r2 *args:
    uv run --no-sync python -m qualify_api.creative.local_media_move {{args}}

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

# Read-only ads observations. Local scope is mandatory; no all-tenant wrapper.
ads-reads-tick tenant limit="100":
    uv run --no-sync python -m qualify_api.ads.reads_cli --tenant {{tenant}} --once --limit {{limit}}

ads-reads-worker tenant interval="60" limit="100":
    uv run --no-sync python -m qualify_api.ads.reads_cli --tenant {{tenant}} --interval {{interval}} --limit {{limit}}

# Synthetic real-DB load and GET-only fake Meta; disposable no-egress Docker network.
mem-ads-reads-worker image="qualify-memtest:deps":
    bash deploy/measure/ads-reads-workload-memory.sh {{image}}

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

# Measure the creative queue in an isolated no-egress test stack, with fake vendors.
mem-creative-worker image="qualify-memtest:deps" *args:
    deploy/measure/creative-worker-memory.sh {{image}} {{args}}

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

# Stage named keys with backup + 0600, without restarting; deploy applies role passwords.
#   just env-stage qualify-prod --dry-run QUALIFY_DB_CREATIVE_WORKER_PASSWORD
#   just env-stage qualify-prod QUALIFY_DB_CREATIVE_WORKER_PASSWORD
env-stage target *keys:
    deploy/deploy.sh env-stage {{target}} {{keys}}

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

# `test` job (m-24971869): import + dry-compile the whole Reflex app, as `reflex export` does
# in deploy.yml — catches a broken import or page that pytest never loads. No bun, no network.
# PYTHONPATH as in deploy/Dockerfile: qualify_models is on the path, never synced.
ci-compile:
    PYTHONPATH=packages/models/src uv run --no-sync python .github/scripts/reflex_compile_check.py

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

# m-24987158: seasonal stickers, recipe C (Remotion) next to recipe E (Pillow), on a
# placeholder brand. Writes only to <out> (never R2: the local .env is the PROD bucket).
bench-stickers out base="http://127.0.0.1:3200":
    uv run --no-sync python packages/creative/scripts/bench_stickers.py {{out}} --url {{base}}

# --- ScrapeCreators CLI (.claude/skills/qualify-scrapecreators) --------------------
# Runs the official CLI with the project's key. Live calls spend credits.
[positional-arguments]
sc *args:
    @if [ -z "${SCRAPECREATORS_API_KEY:-}" ] && [ -f .env ]; then export SCRAPECREATORS_API_KEY="$(grep -m1 '^SCRAPECREATORS_API_KEY=' .env | cut -d= -f2- | tr -d "\"' ")"; fi; [ -n "${SCRAPECREATORS_API_KEY:-}" ] || { echo "Falta SCRAPECREATORS_API_KEY (.env o shell)" >&2; exit 1; }; command -v scrapecreators >/dev/null || { echo "Instala la CLI: npm install -g @scrapecreators/cli" >&2; exit 1; }; scrapecreators "$@"

# ADR 42 R2 (m-24854847): reads the balance from the vendor's free route and records it in
# `vendor_balance`. The way back after a 402 stop or a balance under the 500-credit floor,
# once the plan is topped up. Spends no credits. LOCAL: loads the key and the DSNs from the
# checkout's `.env` (`--env-file`), so it writes the dev database; it fails loudly if the
# write fails. PRODUCTION (on the server, with the `dc` alias of docs/despliegue-hetzner.md
# §7): `dc exec api python -c "from qualify_api.vendors.scrapecreators import refresh_balance; print(refresh_balance())"`
sc-balance-refresh:
    uv run --no-sync $([ -f .env ] && echo --env-file .env) python -c "from qualify_api.vendors.scrapecreators import refresh_balance; print(refresh_balance())"

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

# BytePlus concurrency: demand + queue simulation behind docs/escalar-generacion-concurrencia.md
# §3 (m-24855154). Offline, stdlib only, seeded: `just sim-concurrencia --replicas 5`.
sim-concurrencia *args:
    PYTHONUTF8=1 uv run --no-sync python -m qualify_creative.concurrency_sim {{args}}

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

# m-24854495: the sentiment golden set + blind labelling kit (offline, no API). Real
# comments are written OUTSIDE the repo (~/qualify-eval-data/sentiment/). Subcommands:
# public | anonymize --raw <csv> | build [--real <jsonl>] | merge --sheet name=<csv> ...
sentiment-kit *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/replies_ai/sentiment_kit.py {{args}}

# PB-6 (m-24852200): real cost of one Alta prefill — LIVE credits + tokens, local stack only.
eval-precarga *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/alta_prefill_cost/run_experiment.py {{args}}

# m-25017274: «Mejorar mi texto» — six fictional food briefs, two presses each, how much
# the answers repeat (similarity), new numbers and cost. Spends ≈ USD 0.08 per run.
eval-mejorar-texto *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/mejorar_texto/run_experiment.py {{args}}

eval-voz *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/voice_ai/run_experiment.py {{args}}

# VE-14 (m-24921071): «Proponerme las partes» over REAL briefs (cases.json, git-ignored).
# `--dry-run` quotes and sends nothing; a paid run stops at `--cap-usd` (default 1.50).
eval-partes *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/proponer_partes/run_experiment.py {{args}}

# Once per machine: the six Colombian Spanish recordings (OpenSLR 72, ~31 MB, git-ignored).
eval-voz-audio:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/voice_ai/fetch_audio.py

# VE-05 (m-24921050): cut F1 at ±0.25 s and people/face accuracy of the reel analysis against
# the human sheet docs/modelos-generativos/ve05-anotacion-cortes-rostros.csv. Offline, free.
eval-cortes-rostros *args:
    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/reel_shots_ai/score.py {{args}}

# m-24852161: fingerprints (never values) of the BytePlus keys in .env — the eval key
# (QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY) must differ from the app's and from production's
# (QUALIFY_BYTEPLUS_ARK_PROD_KEY_FINGERPRINT). Exit 1 on a clash. Calls nothing.
byteplus-llaves *args:
    PYTHONUTF8=1 uv run --no-sync python -m qualify_api.evals.byteplus_eval_guard {{args}}

# --- Puerta de merge (infra/github/README.md) ---------------------------------------
# Sin branch protection en GitHub Free, la regla "CI en verde para mergear" vive aquí:
# `just merge 81` se niega si falta o falló alguno de los checks requeridos; un admin puede
# forzar a propósito con `just merge 81 --admin` (queda un comentario en el PR).
# `--check-only` corre toda la puerta (CI + migraciones) y para antes del merge.
# La guarda de migraciones (`just migration-guard`, m-24971869) corre siempre, también con
# `--admin`: dos migraciones con el mismo número o una rama de Alembic rompen cada deploy.
#
# REST only (`gh api`), never `gh pr view/merge/comment`: those go through GraphQL, which
# Claude Code cloud sessions cannot reach — this way the same gate works from the Mac and
# from the cloud. The rollup = latest check run per name + commit statuses on the PR head.
merge pr *flags:
    #!/usr/bin/env bash
    set -euo pipefail
    repo=repos/AttitudeFactory/Qualify
    admin=false; check_only=false
    for flag in {{flags}}; do
      case "$flag" in
        --admin) admin=true ;;
        --check-only) check_only=true ;;
        *) echo "just merge: opción desconocida '$flag' (válidas: --admin, --check-only)." >&2; exit 2 ;;
      esac
    done
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
    if [ -n "$missing$failed" ] && [ "$admin" != true ]; then
      echo "just merge: NO se mergea #{{pr}}." >&2
      [ -n "$failed" ] && echo "  checks fallidos o en curso:$failed" >&2
      [ -n "$missing" ] && echo "  checks sin reportar:$missing" >&2
      echo "  Un administrador puede forzar a propósito: just merge {{pr}} --admin" >&2
      exit 1
    fi
    # Not bypassed by --admin: CI ran against an older main, and a parallel merge may have
    # taken this PR's migration number since (0131, 0134 and 0136 on 2026-11-06).
    # Blind spot: a merge landing on main between this check and the PUT (~1 s) goes unseen —
    # the merge API can pin the PR head (`sha`) but not the base.
    "{{just_executable()}}" --justfile "{{justfile()}}" migration-guard {{pr}} main "$sha"
    if [ "$check_only" = true ]; then
      echo "just merge --check-only: #{{pr}} pasa la puerta en $sha (no se mergea)."
      exit 0
    fi
    if [ "$admin" = true ] && [ -n "$missing$failed" ]; then
      gh api "$repo/issues/{{pr}}/comments" -f body="Merge forzado por un administrador con \`just merge --admin\` con checks pendientes o fallidos:$failed$missing" >/dev/null
    fi
    # `sha` pins the merge to the head that was checked: a push after the check is refused.
    gh api -X PUT "$repo/pulls/{{pr}}/merge" -f merge_method=merge -f sha="$sha" --jq '"#{{pr}}: \(.message) (\(.sha))"'

# Guarda de migraciones de `just merge` (m-24971869). Sola, en seco: `just migration-guard
# <pr> [base] [sha]` contra cualquier ref de GitHub, o `just migration-guard <base>..<head>`
# contra un repo git local (antes de abrir el PR; también es como se prueba). Silenciosa y
# exit 0 si el PR no toca migrations/postgres/versions/. Si lo toca, se niega cuando:
#   - modifica una migración que ya está en `base` (Alembic no re-corre una aplicada);
#   - borra o renombra una cuya `revision` desaparece (cada deploy siguiente: «Can't locate
#     revision»). Renumerar una que no se desplegó, como #510, sí pasa: su número sigue en base;
#   - agrega una con un número que `base` ya tiene, o cuyo nombre no empieza por su `revision`;
#   - su primera migración nueva no parte de las cabezas de `base`: un id si hay una cabeza,
#     o exactamente la tupla de todas si hay varias (revision de merge de Alembic);
#   - `base` (sin lo que el PR quita) tiene dos archivos con el mismo número.
# Supuestos: los ids de `base` salen del prefijo del nombre (`revision` == prefijo, se
# verifica en todos), las cabezas se calculan leyendo todos los archivos de `base`, y la API
# de contenidos lista hasta 1000 archivos por directorio. `down_revision` en tupla, en una
# línea. En modo rango hay que hacer `git fetch` antes: se niega si `base` está detrás de origin.
migration-guard pr base="main" sha="":
    #!/usr/bin/env bash
    set -euo pipefail
    repo=repos/AttitudeFactory/Qualify
    dir=migrations/postgres/versions
    pr="{{pr}}"; base="{{base}}"; sha="{{sha}}"
    # Data sources: GitHub (REST only) for a PR number, local git for `<base>..<head>`.
    if [[ "$pr" == *..* ]]; then
      base=${pr%%..*}; sha=${pr##*..}; label="$pr"
      # A stale local base would list main's newer files as "added" and pass: refuse unless
      # the base already contains the remote tip (`git fetch` first, then origin/main..HEAD).
      bname=${base#origin/}
      if git show-ref --verify -q "refs/remotes/origin/$bname"; then
        remote_tip=$(git ls-remote origin "refs/heads/$bname" 2>/dev/null | cut -f1) || remote_tip=""
        if [ -z "$remote_tip" ]; then
          echo "just migration-guard: aviso — no se pudo leer origin/$bname; se compara contra el $base local." >&2
        elif ! git merge-base --is-ancestor "$remote_tip" "$base" 2>/dev/null; then
          echo "just migration-guard: $base está detrás de origin ($bname = ${remote_tip:0:8}): corre \`git fetch origin\` y usa origin/$bname..HEAD." >&2
          exit 1
        fi
      fi
      changes() { git diff --name-status -M "$base...$sha" -- "$dir" | awk -F'\t' '
        $1=="A" {print "added", $2, "-"} $1=="M" {print "modified", $2, "-"} $1=="D" {print "removed", $2, "-"}
        $1 ~ /^R/ {print "renamed", $3, $2} $1 ~ /^C/ {print "copied", $3, $2}'; }
      raw() { git show "$2:$1"; }
      list_base() { git ls-tree --name-only "$base" "$dir/" | sed 's|.*/||'; }
    else
      label="#$pr"
      [ -n "$sha" ] || sha=$(gh api "$repo/pulls/$pr" --jq .head.sha)
      changes() { gh api "$repo/pulls/$pr/files?per_page=100" --paginate --jq \
        ".[] | \"\(.status) \(.filename) \(.previous_filename // \"-\")\""; }
      raw() { gh api -H "Accept: application/vnd.github.raw" "$repo/contents/$1?ref=$2"; }
      list_base() { gh api "$repo/contents/$dir?ref=$base" --jq '.[] | select(.type=="file") | .name'; }
    fi
    rev_of() { sed -nE "s/^revision(: [^=]+)? = ['\"]([^'\"]+)['\"][[:space:]]*(#.*)?$/\2/p" | head -n1; }
    # One id, or every id of a one-line tuple (merge revision), sorted; empty = unreadable.
    downs_of() { { sed -nE 's/^down_revision(: [^=]+)? = (.*)$/\2/p' | head -n1 |
      grep -oE "['\"][^'\"]+['\"]" | tr -d "'\"" | sort -u | paste -sd ' ' -; } || true; }
    is_mig() { awk -v d="$dir/" -v c="$1" '{ if (index($c, d) == 1 && $c ~ /\.py$/) print $c }'; }
    problems=""
    add() { problems="$problems"$'\n'"  $*"; }
    ch=$(changes)
    added=$(printf '%s\n' "$ch" | awk '$1=="added"||$1=="renamed"||$1=="copied"' | is_mig 2)
    gone=$(printf '%s\n' "$ch" | awk '$1=="removed" {print $1, $2} $1=="renamed" {print $1, $3}' | is_mig 2)  # paths
    edited=$(printf '%s\n' "$ch" | awk '$1=="modified"||$1=="changed"' | is_mig 2)
    [ -n "$added$gone$edited" ] || exit 0
    for path in $edited; do
      add "${path##*/} ya está en $base y el PR la modifica: Alembic no vuelve a correr una migración aplicada, así que producción y una base nueva quedan distintas. Escribe una migración nueva (y si es para unir dos cabezas, una de merge)."
    done
    kept=$(list_base | awk '/\.py$/' | { grep -vxF -f <(printf '%s\n' "$gone" | sed '/^$/d; s|.*/||') || true; } | sort)
    kept_revs=$(printf '%s\n' "$kept" | sed '/^$/d; s/_.*//' | sort -u)
    dups=$(printf '%s\n' "$kept" | sed '/^$/d; s/_.*//' | sort | uniq -d)
    for r in $dups; do
      add "$base ya tiene dos migraciones $r ($(printf '%s\n' "$kept" | awk -F_ -v r="$r" '$1==r' | paste -sd ' ' -)): arregla main primero, renumerando la que no se desplegó (como #510)."
    done
    # Heads = base revisions that no base file names as down_revision. Every base file is
    # read (8 in parallel: ~140 raw reads, a few seconds), so a fork far back is still seen.
    export -f raw rev_of downs_of; export repo dir base
    # shellcheck disable=SC2016 # expanded by the inner bash, per file
    wrows=$(printf '%s\n' "$kept" | sed '/^$/d' | xargs -P 8 -I{} bash -c \
      'b=$(raw "$dir/$1" "$base") || b=""; printf "%s|%s|%s\n" "$(printf "%s\n" "$b" | rev_of)" "$(printf "%s\n" "$b" | downs_of)" "$1"' _ {})
    bad=$(printf '%s\n' "$wrows" | awk -F'|' 'NF == 3 { split($3, p, "_"); if ($1 != p[1]) print $3 " (" $1 ")" }')
    while IFS= read -r b; do
      [ -z "$b" ] || add "$b en $base: revision distinta del número del nombre, o no se pudo leer; revisa a mano."
    done <<<"$bad"
    heads=$(printf '%s\n' "$wrows" | sed '/^$/d' | awk -F'|' '{rev[NR]=$1; nm[NR]=$3; n=split($2, a, " "); for (i=1; i<=n; i++) ref[a[i]]=1}
      END {for (i=1; i<=NR; i++) if (!(rev[i] in ref)) print rev[i] "|" nm[i]}')
    head_ids=$(printf '%s\n' "$heads" | cut -d'|' -f1 | sed '/^$/d' | sort -u | paste -sd ' ' -)
    head_desc=$(printf '%s\n' "$heads" | cut -d'|' -f2 | paste -sd ' ' -)
    rows=""; new_revs=""
    for path in $added; do
      body=$(raw "$path" "$sha")
      rev=$(printf '%s\n' "$body" | rev_of); downs=$(printf '%s\n' "$body" | downs_of); name=${path##*/}
      if [ -z "$rev" ] || [ -z "$downs" ]; then
        add "$name: no se pudo leer revision/down_revision (una tupla tiene que ir en una sola línea)."
        continue
      fi
      [ "$rev" = "${name%%_*}" ] || add "$name declara revision '$rev', pero su nombre empieza por '${name%%_*}': nombre y revision tienen que coincidir."
      taken=$(printf '%s\n' "$kept" | awk -F_ -v r="$rev" '$1==r' | paste -sd ' ' -)
      [ -z "$taken" ] || add "$base ya tiene la migración $rev ($taken); el PR agrega $name."
      rows="$rows$rev|$downs|$name"$'\n'; new_revs="$new_revs $rev"
    done
    # shellcheck disable=SC2086 # word splitting intended: one revision per line
    all_revs=$(printf '%s\n' $kept_revs $new_revs)
    for entry in $gone; do
      r=$(raw "$entry" "$base" | rev_of); name=${entry##*/}
      if ! printf '%s\n' "$all_revs" | awk -v r="$r" '$0 == r {f = 1} END {exit !f}'; then
        add "el PR quita $name (revision $r), que ya está en $base: si se desplegó, cada deploy siguiente falla con «Can't locate revision». Para deshacerla, escribe una migración nueva."
      fi
    done
    low=""
    if [ -n "$rows" ]; then
      IFS='|' read -r low_rev low_downs low_name < <(printf '%s' "$rows" | sort | head -n1)
      low="$low_rev"
      if [ "$low_downs" != "$head_ids" ]; then
        case "$head_ids" in
          *" "*) add "$base tiene varias cabezas ($head_desc) y $low_name parte de ($low_downs): la primera migración nueva tiene que ser una de merge con down_revision = exactamente esas cabezas." ;;
          *) add "$low_name ($low_rev) parte de ($low_downs), pero la última migración de $base es $head_ids ($head_desc)." ;;
        esac
      fi
    fi
    if [ -n "$problems" ]; then
      echo "just merge: NO se mergea $label — sus migraciones chocan con $base:$problems" >&2
      echo "  Mergea main en la rama y renumera o escribe una migración nueva — skill qualify-migration." >&2
      echo "  --admin no salta esta guarda: una migración repetida, borrada o editada rompe cada deploy." >&2
      exit 1
    fi
    if [ -n "$low" ]; then
      echo "just merge: migraciones de $label OK sobre $base ($low parte de $head_ids)."
    else
      echo "just merge: migraciones de $label OK sobre $base (no agrega; lo que quita conserva cada revision)."
    fi

# Aplica la regla de `main` (requiere GitHub Team o repo público; ver infra/github/README.md).
protect-main:
    gh api -X POST repos/AttitudeFactory/Qualify/rulesets --input infra/github/ruleset-main.json

# Playwright browser tests (tests/e2e) — never part of CI. Boots the app on 3390/8390 with
# fake auth and open signup, or uses QUALIFY_E2E_BASE_URL. Needs the compose Postgres
# (`just up`) and a Chromium (`uv run --with playwright playwright install chromium`).
e2e *ARGS:
    uv run --no-sync --with pytest-playwright pytest tests/e2e -p no:cacheprovider -o addopts="--import-mode=importlib" {{ARGS}}

# m-24955929: Galería → Crear → «Por aprobar» (photo + clip, cut, choose, create), at
# 360 px and desktop. The app it boots — and media-worker — run on a fake bucket
# (QUALIFY_OBJECT_STORE_DIR, a temp dir) with fake copy (QUALIFY_COPY_FAKE=1): never the
# real R2, no paid call. Needs ffmpeg and the compose Postgres/Redis (`just up`); the run
# creates/migrates `qualify_test` itself, never the dev `qualify`.
e2e-galeria *ARGS:
    uv run --no-sync --with pytest-playwright pytest tests/e2e/test_galeria_to_por_aprobar.py -p no:cacheprovider -o addopts="--import-mode=importlib" {{ARGS}}

# m-24852167: team-only, read-only queue/slots/waits report; no generation or messages.
creative-queue *args:
    uv run --no-sync python -m qualify_api.creative.worker.queue_cli {{args}}

# m-24789547: scoped IG/FB deletion; dry run unless --execute. Always --tenant UUID.
# Manual support request: --tenant UUID --connection UUID --request --execute.
# Automatic production scheduling lives in connection-purge-worker (no cron setup).
connection-purge *args:
    uv run --no-sync python -m qualify_api.connections.purge_cli {{args}}

# Local scheduler loop, dry-run unless --execute. Scope is mandatory in the recipe.
connection-purge-worker tenant *args:
    uv run --no-sync python -m qualify_api.connections.purge_worker --tenant {{tenant}} {{args}}

# Isolated real loop, throwaway PostgreSQL + fake R2, no egress or production credentials.
mem-connection-purge-worker image="qualify-memtest:deps" *args:
    bash deploy/measure/connection-purge-worker-memory.sh {{image}} {{args}}
