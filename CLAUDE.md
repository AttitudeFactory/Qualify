<!-- reflex managed begin (do not edit inside this block; add custom content outside the markers) -->
# Agents

This project uses the **Reflex agent skills** — up-to-date knowledge for building full-stack Python web apps with [Reflex](https://reflex.dev). Install them first, then use them as described below.

## Installing the Skills

Before working on this project, make sure the Reflex skills are available to you.

### Claude Code

If the skills are not already available, install them yourself by running these shell commands:

```bash
claude plugin marketplace add reflex-dev/agent-skills
claude plugin install reflex@reflex-agent-skills
```

Newly installed plugins load on the next session. After installing, tell the user to restart the session so the skills auto-load; until then, read the skill files directly from `~/.claude/plugins/` when you need them.

### Other agents (Cursor, OpenCode, Codex, Pi)

```
npx skills add reflex-dev/agent-skills
```

Or clone https://github.com/reflex-dev/agent-skills and copy the `skills/` folders into your agent's skill directory (see the repo README for paths).

### Verifying

Before writing or editing any Reflex code, confirm these three skills are available: `reflex-docs`, `setup-python-env`, and `reflex-process-management`. If they are not, STOP and run the install step above — do not proceed without them.

## Using the Skills

### Reflex documentation

For anything about Reflex APIs — components, state management, events, styling, database, routing, authentication — use the **reflex-docs** skill rather than relying on memory. It carries current, version-accurate docs.

### Initializing a new Reflex project

When starting a new Reflex project or setting up a development environment, you **must** follow the **setup-python-env** skill before doing anything else.

Do not skip any steps. Do not assume a virtual environment or Reflex is already available — always verify first by following the skill's instructions in order.

After the environment is ready and Reflex is installed, run:

```bash
reflex init
```

Then proceed with the user's request.

### Managing a Reflex process

When you need to compile, run, reload, or debug a Reflex application, follow the **reflex-process-management** skill for the correct sequence and error investigation steps.
<!-- reflex managed end -->

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

**Updated 2026-08-06.** The "mostly pre-implementation" era is over: the repo now has a real `uv` workspace, a Postgres/Redis compose stack, four Alembic revisions with RLS, and five workspace packages. What is **still** absent is the analytical plane — **no `ingestion`/`search`/`signals` schemas, no Celery workers, no R2 client, no `scripts/`** (all Fase 1 Parte 3, not started). Since ADR 31 (2026-08-05) that plane is Postgres, so building it means new Alembic revisions in the database that already runs, not a new service.

> ⚠ **Read the filesystem, not this file, for what exists.** This is a standing house rule and it has repeatedly earned its keep — the deliberately-preserved `STALE` item on `revoke.py` below is the canonical example of why.
>
> **What changed (2026-08-06): the premise that used to justify the rule is dead, the rule is not.** This block used to say the entire Sprint 1 tree was uncommitted working state and that `git log` could not be trusted. Verified today: `git status --porcelain` returns **zero** files and `main` is at `0fa3805` (PR #5 merged). Everything described below is committed. That makes `git log` *usable* — it does **not** make this file, or any doc under `docs/`, authoritative about what is on disk. Docs describe target state and drift from it; the filesystem does not.

What exists on disk today:

- `README.md` (the most current, living summary of vision/architecture/roadmap) and **30** docs in `docs/` (see "What Qualify is" for the main ones; `docs/index.md` is the map).
- **`uv` workspace at the root** (`pyproject.toml` with `[tool.uv.workspace] members = ["packages/*"]`, Python >=3.12) — ADR 26. `ruff` (line-length 100, `E`/`F`/`I`/`UP`) and `pytest` are configured here, with markers `integration` (external network/paid vendors/model weights — never in CI) and `db` (needs the compose Postgres/Redis). `asyncio_mode = "auto"`.
- **`docker-compose.yml`** — `postgres` + `redis` only. Per ADR 31 there is no ClickHouse service to add; what Parte 3 must change is the Postgres **image** to `pgvector/pgvector:pg16`.
- **`migrations/postgres/`** — Alembic (ADR 27). *(Count below is the 2026-08-06 snapshot; as of 2026-10-06 head is `0040_calendar_event_output_port` (after `0039_brand_typography`) and the dev `qualify` DB was observed at 0029 — run `just migrate` before using the app against dev data.)* **Four** revisions as of that snapshot, all applied: `0001_tenancy_foundation` (tenants/users/tenant_members/brands + the three roles + RLS), `0002_connections` (platform_apps/social_connections/oauth_credentials/connection_events + `qualify_credential`), `0003_publishing` (`publish_attempts`, `scheduled_posts`) and `0004_inbox` (`threads`, `messages`). **`0003`/`0004` are the schema base Sprint 3 builds on — do not plan Meta publishing/inbox work as if the tables were still to be created.** Runs as `qualify_owner`. RLS policies use `NULLIF(current_setting('app.tenant_id', true), '')::uuid` — see §6 ruling R7 in `docs/arquitectura.md` for why the `NULLIF` is load-bearing and must not be "simplified" away.
- **`packages/api/`** — `qualify_api`: the `tenancy` models, the `connections` module (crypto, events, fsm, locks, models, resolver + the C-04 OAuth flow), and the seed.
- **`packages/shared/`** — `qualify_shared`: the sanctioned DB doors. `tenant_session` (RLS-scoped, request path), `admin_session` (BYPASSRLS, provisioning/seed only), `credential_session` (the narrow `qualify_credential` role that alone may read `oauth_credentials.ciphertext`). A static test forbids constructing an `Engine`/`Session` anywhere else.
- **`packages/scraper/`** — `qualify_scraper`: Zyte client + TikTok/IG parsers + the `payload_schema_version = 2` raw-payload envelope (ADR 18/22) and `raw_payload_key()`.
- `packages/models/` — Fase 1 Parte 1: the multimodal analysis cascade (filter, vision, transcription, sentiment) as composable, typed functions with a `Provider` abstraction (local `transformers` for the small models, HF Inference Providers for the hosted VLM/ASR ones — swappable for self-hosted later, no rewrite). Now a workspace member, but its heavy deps live in the `ml` group, so a default `uv sync` does **not** install torch and a bare `uv run pytest` does **not** collect its suite. Runs against fixtures in `tests/fixtures/` (a real public TikTok sample video, frame + audio extracted via `ffmpeg`), not live scraping. Also holds `permission_capability.py` (C-05, the scope→capability matrix). See `docs/plan-ingesta-social.md` §0 for the Parte 1/2/3 ordering and `docs/modelos-multimodal-fase1.md` for the model choices.
  - **`hooks/` (added by PR #5, 2026-08-05) — a spike, not a pipeline.** Structured extraction of *hook* features over the first 3 s of a video across three channels (spoken/shown/on-screen text), with a CLI. It introduces **no Celery, no Redis as a queue, and no analytical schema**; it writes CSV/JSONL to disk and stops there. Treat it as a research artifact on the `Provider` seam, not as Parte 3 arriving early. Notes: `packages/models/NOTES_hook_pattern_spike.md` (Fases A/B delivered, C blocked on the founder, D designed but has no data).
- `packages/docs-harvester/` — tooling for harvesting the Meta platform doc corpus that ADR 25 and the `[V]` scope research cite.
- **`packages/render/` (added 2026-10-05) — the Remotion render service, the repo's ONE Node runtime.** Founder decision of 2026-10-05: the template engine is Remotion, the Pillow render (`qualify_creative/templates/`, the 2026-08-18 POC) is abandoned for rendering — Pillow stays only for photo normalization at upload. `packages/render/CONTRACT.md` is the contract both sides build against (typed-port manifests, immutable versions, several outputs per run, per-output status, HTTP API on 3200, `asset://` references); `docs/plan-mvp-plantillas-remotion.md` is the plan, `docs/backlog-motor-plantillas-remotion.md` the stories (`MP-00…13`). It runs **in Docker from phase 1**: service `render` in `docker-compose.yml`, started by `just up`; `just render-dev` opens Remotion Studio on the host for authoring, `just render-build` rebuilds the image, `just render-smoke` exercises the running service. Composition ids are `<template-id>-v<version>--<port>` (Remotion allows only `[A-Za-z0-9-]`). FFmpeg is NOT in the image (Remotion bundles its own); the `ffmpeg` binary is a Python-side dependency, used by `qualify_creative.video.normalize` at catalog upload (H.264, ≤15 s, no audio).
  - Python half: `qualify_creative.render` (manifest/registry/props/recipes/client/adapter — `RemotionTemplateAdapter` is a `GenerationProvider`, `GenerationTask.TEMPLATE_RENDER`, pricing entry `remotion_selfhost` = explicit `0.00` while the Free License applies to a team of ≤3), wired into `MediaProducer` for `ContentKind.TEMPLATE` (enabled since 2026-10-05; it requires ≥1 product photo). Migration **0038** adds `brand_products`, `product_media`, `template_runs` (its `id` IS the render `jobId`), `image_assets.output_port`/`template_run_id`, `content_drafts.campaign_id`. The product catalog lives in `qualify_api.catalog` (`CatalogService` normalizes every photo and clip at upload).
- A `Qualify/` **Reflex** app — the decided CRM UI (`docs/arquitectura.md` §2, §6 ADR 8), replacing the earlier Next.js placeholder. It now holds **two halves at different maturity levels**, and the distinction matters:
  - **C-06 connected-accounts UI** (`connections_page.py`, `connections_state.py`, `connections_vm.py`, `connections_provider.py`, `capabilities.py`, `tenant.py`) — **wired to the real backend**: it reads through `qualify_shared.db.session.tenant_session` against Postgres and imports the real `qualify_api.connections` FSM/models and the `qualify_models` capability matrix. Not a mock. Its tests are collected by the root `pytest` run.
  - **Mentions dashboard** (sidebar/topbar/stats-row/filter-bar/mentions-table, SQLModel-backed `db.py`, `DashboardState`) — still exploratory, still on local SQLite/seed data, still unconnected to the Fase 1 pipeline (the Fase 1 analytical schemas do not exist yet).
  - **Design system (2026-08-18)** — `Qualify/ui/` (`tokens.py`, `layout.py`, `primitives.py`) + `assets/qualify.css` + the theme in `rxconfig.py` (teal accent, slate gray, IBM Plex Sans/Mono). Every page is built as `app_shell(page_header(...), page_body(...))`; states use `signal_pill`/`tone_badge` by **tone** (`ok`/`warn`/`error`/`info`/`neutral`), never a raw Radix colour name. Rules and rationale: `docs/design-system.md`; living style guide at the `/design` route (no login, not in the sidebar). New screens follow §9.1 of that doc.

Before assuming any file, service, or command exists, check the actual filesystem rather than trusting the docs, since the docs describe target architecture.

### Sprint 1 state (Fase 1 Parte 4-A, "núcleo compartido de cuentas conectadas") — LANDED; re-verified 2026-08-06

Six stories, specced in `docs/refinamiento-sprint1.md` (§C-01…§C-06) with the binding architect rulings R1-R8 in `docs/arquitectura.md` §6. This section used to read "five built, C-04 PARTIAL" after a session was cut on a spend limit. **Re-verified against disk today: both concrete C-04 gaps are closed.** Sprint 3 can treat the connected-accounts core as a foundation, not as a half-built dependency.

- **C-01 tenancy foundation, C-02 envelope v2, C-03 connections custody+FSM, C-05 capability matrix, C-06 connections UI** — built, tests green.
- **C-04 OAuth connect flow.** Landed: `state_token`, `meta_oauth`, `credential_reader`, `repository`, `service`, `verifier`, `read`, the HTTP routes, and `access_posture` wiring. Former gap list, with today's measurement:
  1. ~~The FSM edge `(REVOKED, VERIFY_FAIL) → DEGRADED` — approved by the architect but no code, no test.~~ **CLOSED. Verified 2026-08-06: the edge is in `packages/api/src/qualify_api/connections/fsm.py:75-78` (`REVOKED` + `VERIFY_FAIL` → `DEGRADED` / `DomainEventName.DEGRADED`), covered in `packages/api/tests/test_connections_fsm.py`.** Rationale it implements, unchanged (§6 ruling on C-04 Q2): a `revoked` row pointing at a freshly rotated credential is a status field lying about its own row.
  2. ~~`revoke_connection` service — does not exist; C-06 needs it.~~ **STALE — closed. Verified on disk 2026-07-30: `packages/api/src/qualify_api/connections/revoke.py` exists (idempotent) and is exported from the `connections/__init__.py` seam.** Left visible rather than deleted because it is the canonical example of why the house rule holds: read the filesystem, not this file, for what exists.
  3. The interface contract to the Reflex UI — **not re-verified in this pass; status unknown, treat as open.** C-06 does read the real backend through `tenant_session`, so whatever remains here is a contract-formalization question, not a wiring one.

Full handoff, including who was mid-what: `.claude/sprint-state-2026-07-26-c04-inflight.md`.

**Resolved 2026-07-26 — ADR 25 is signed.** The login fork (Facebook Login for Business) is now `[APROBADO]` in `docs/arquitectura.md` §6, signed by the founder on 2026-07-26 unchanged. This closes the doc/code inconsistency that used to sit here: the decision was already materialized in applied DDL (`social_connections.linked_page_id NOT NULL`) with all of C-04 written against it, and the docs now say so too. Nothing to change in code — build on it as settled. Two properties of the row remain operationally load-bearing and are **not** softened by the signature: (a) the linked Facebook Page is a **hard precondition**, enforced as post-consent enumeration in the OAuth callback (ruling R4), not as pre-auth detection; and (b) the publish scope has **four spellings in circulation** — never hardcode one from documentation, resolve it empirically against the authorization endpoint.

### Merging to `main` — the rule and the gate

**Founder's rule (2026-10-05): nothing merges to `main` with CI red; only a repository
administrator may bypass, deliberately.** GitHub cannot enforce it on this plan (private
repo, organization on GitHub Free → branch protection and rulesets answer 403), so the
gate is `just merge <pr>`: it refuses unless the required checks (`lint`, `test`, `test-db`,
`node-render`) are green; `just merge <pr> --admin` forces it and leaves a comment on the PR.
**Agents merge through `just merge`, never `gh pr merge` directly.** The ruleset to apply
the day the plan allows it is `infra/github/ruleset-main.json` (`just protect-main`).

### Commands

A `justfile` is the entry point for everything backend. Prefer it over ad-hoc commands — the recipes encode ordering that is easy to get wrong (e.g. `dev` = `up` → `migrate` → `seed`):

```bash
just dev          # up + migrate + seed — the full local stack from cold
just up           # docker compose up -d --wait (postgres + redis)
just migrate      # alembic upgrade head, as qualify_owner
just migrate-down # alembic downgrade base — must land clean (reversibility is a gate)
just seed         # the two real tenants, via admin_session()
just test         # uv run pytest -m "not integration"  — mirrors CI
just test-db      # only the tests needing the compose Postgres/Redis
just lint / fmt   # ruff check . / ruff format .
just ci-lint      # exactly the CI `lint` job (ruff check + format --check), no sync
just ci-test      # exactly the CI `test` job: offline tests + coverage per package
just audit        # pip-audit over the lock + npm audit (packages/render) — informational
just down         # docker compose down -v — DROPS the pgdata volume
just calendar-tick --tenant <uuid>     # QUA-111: one Planificador tick — PUBLISHES FOR REAL
just calendar-worker --tenant <uuid>   # QUA-111: a tick every 60 s until Ctrl+C
```

The calendar executor (QUA-111, `packages/api/src/qualify_api/planner/worker.py`) publishes due, approved `calendar_events` through `PublishService`. **Locally always pass `--tenant`:** `--all-tenants` is the production discovery, and this dev database holds dozens of test tenants it would act on. Decision, guarantees and UML: `docs/automatizacion-calendario-qua111.md`.

Four operational traps worth knowing before you touch this stack:

- **Editing an already-applied Alembic revision does not re-run it.** `just migrate` will no-op. Since nothing is deployed, migrations are edited **in place** (ADR 27 ruling R8a), so re-verifying a migration change means `just down` → `just dev` — a full recreate, not a re-migrate.
- **Do not run `uv sync`/`uv venv` while other agents are working.** The shared workspace `.venv` has been broken by concurrent `uv` runs before; `uv run --no-sync pytest ...` is the safe read-only form.
- **Do not alternate `uv sync` ↔ `uv sync --group ml` — this, not concurrency, is what actually breaks the venv.** Observed twice in sequence on 2026-07-26 with a single agent running, so the trap above does not explain it: toggling between the default groups (no `ml`) and `--group ml` corrupts the shared venv's editable-install mechanism. The packages still appear in `uv pip list`, but `import qualify_models` (etc.) fails exactly as if the venv had never been synced. The only fix that worked both times was `rm -rf .venv && uv sync --group ml`. Practical rule: always sync with `--group ml` (the `Qualify/` tests are in `testpaths` now and import `qualify_models` for real), and prefer `uv run --no-sync` for everything read-only.
  - **ROOT CAUSE FOUND (2026-08-18) — and it is neither alternation nor concurrency: macOS `UF_HIDDEN` on the `.pth` files.** Something on this machine batch-applies the BSD `hidden` flag to files under the repo (observed on `.venv/lib/python3.12/site-packages/*.pth` in both the main checkout and a worktree, timestamps minutes after a clean sync that had verifiably worked), and **CPython ≥3.12 `site.py` silently skips hidden `.pth` files** — which is exactly uv's editable-install mechanism for workspace members. That reproduces every documented symptom: `uv pip list` still shows the packages (dist-info is read directly), imports fail "as if never synced", and `rm -rf .venv && uv sync` *sometimes* fixes it (until the flag gets re-applied). **The cheap fix, before any venv rebuild:** diagnose with `ls -lO .venv/lib/python3.12/site-packages/*.pth` (the word `hidden` in the flags column is the tell) and repair with `chflags nohidden .venv/lib/python3.12/site-packages/*.pth` — one second instead of minutes. Newly created files do NOT inherit the flag; the applier is unidentified (candidates: Finder/iCloud tooling), so the flag can return — re-run the `chflags` line, don't nuke the venv.
  - **Measured later the same day, in a worktree under `.claude/worktrees/`: the flag returns in under 2 seconds and covers the ENTIRE `.venv` tree (225/225 entries in site-packages, plus every ancestor up to the worktree root)** — consistent with something recursively hiding every dot-directory (`.claude/`, `.venv/`) and re-asserting it continuously. In that situation `chflags` is a losing race. **The bypass that does not depend on the flag at all: `PYTHONPATH=packages/api/src:packages/shared/src:packages/scraper/src:packages/models/src`** — Python 3.12 skips hidden `.pth` files but never skips `PYTHONPATH`. `.claude/launch.json` (`qualify-crm`) sets it for `reflex run`; export it likewise before `uv run --no-sync pytest` when a worktree venv is affected.
- **`jiwer` is missing from the shared root venv — and a full fresh sync does NOT fix it.** Re-measured 2026-08-08 immediately after a clean `rm -rf .venv && uv sync --group ml` (the C3 ritual): `import jiwer` still fails. This **disproves** the earlier "partial-sync gap" diagnosis — the real cause is that a workspace-root `uv sync` installs member packages' *dependencies* but **not their `[dependency-groups]`** (`jiwer` lives in `packages/models/pyproject.toml` `[dependency-groups].eval`). Do not "fix" this by experimenting with `--all-packages`/group flags — that risks the alternation trap above. Working, measured workaround: `uv run --no-sync --with jiwer pytest packages/models/tests -m "not integration" -q` → **288/288 green (2026-08-08)**. Does not touch CI (the root gate does not collect that directory).

For the Reflex UI specifically, follow the **reflex-process-management** skill (see Agents section above) rather than running `reflex` commands ad hoc.

**Test state as of 2026-08-08** (re-measured after the Sprint 3 overnight run + C3): **398/398 green offline** (`uv run --no-sync pytest -m "not integration" -q`) and **40/40 against live Docker** (`-m db`). The shared venv was rebuilt clean via the C3 ritual on 2026-08-08: the bare interpreter now imports all four packages (`.venv/bin/python -c "import qualify_models, qualify_shared, qualify_api, qualify_scraper"` passes), `boto3`/`botocore` are declared in `qualify-shared` and `uvicorn` in `qualify-api`, and `s3.py`'s lazy import moved to module level (the static guard in `test_object_store_sanctity.py` remains). The previously-known non-idempotent query in `test_connections_schema.py` is fixed (it now filters by `connection_id`), so the `db` suite can be re-run without a `docker compose down -v` in between.

**Both numbers cover the root `testpaths` only** (`packages/api|shared|scraper/tests` + `Qualify/`). `packages/models/tests` is deliberately excluded from the root gate (R11(b) — collecting it would drag the `ml`/torch group into the default run), so **neither number says anything about the models suite** — see the `jiwer` trap above before claiming it passes (with the `--with jiwer` workaround it measured 288/288 offline on 2026-08-08).

### CI (GitHub Actions, since 2026-10-05)

Two workflows under `.github/workflows/`, both triggered by `pull_request` → `main`, `workflow_dispatch`, and (`ci` only) `push` to `main` — **never** by pushes to other branches, so a PR costs one run per push, not two. Older runs of the same PR are cancelled. The repo is private on GitHub Free (2,000 Actions min/month): every job has a timeout, uv/npm/Docker layers are cached, and nothing uploads SARIF (needs Advanced Security). All actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`, weekly, grouped) bumps uv, npm (`packages/render`), actions and the render Dockerfile base image.

| Workflow / job | Runs | What | Blocks? |
|---|---|---|---|
| `ci` / `lint` | always | `ruff check .` + `ruff format --check .` (dev group only) | **yes** |
| `ci` / `test` | always | `pytest -m "not integration and not db and not slow"` + `--cov` per package; `coverage.xml`/`.json` as artifact, per-package table in the step summary and a sticky PR comment (`.github/scripts/coverage_summary.py`) | **yes** (coverage % informs only) |
| `ci` / `test-db` | always | Postgres 16 + Redis 7 service containers, `alembic upgrade head` → `downgrade base` (must leave no revision) → `upgrade head`, then `pytest -m db` | **yes** (reversibility is a gate, ADR 27) |
| `ci` / `node-render` | if `packages/render/package.json` exists | `npm ci` + `npm run typecheck` (Node 22, npm cache) | **yes** |
| `ci` / `docker-render` | if `packages/render/Dockerfile` exists AND (PR touches `packages/render/**` OR main) | `docker build` with `push: false`, GHA layer cache | **yes** |
| `security` / `sast` | PR, weekly (Mon 06:17 UTC), manual | semgrep (`p/ci`+`p/python`+`p/github-actions`, no account, metrics off) + bandit (medium+) over `packages/*/src` and `Qualify/` | no (summary + artifact) |
| `security` / `deps` | same | `pip-audit` over `uv export` of the locked default groups (never `ml`) + `npm audit --audit-level=high` in `packages/render` | no |
| `security` / `repo` | same | `trivy fs` (vuln + secret + misconfig, HIGH/CRITICAL) + `gitleaks git` over the full history (binary from the release, checksum-verified; the official Action needs an org licence) | trivy no; **gitleaks yes** when it finds a committed secret (redacted output — rotate, then purge or allowlist in `.gitleaks.toml`) |

Reproduce locally: `just ci-lint`, `just ci-test`, `just test-db` (needs `just up`), `just audit`. Reading a run: `gh run list --workflow ci --limit 5`, `gh run view <id>` (job list + durations), `gh run view <id> --log-failed` (only the failing steps), `gh run watch <id>`; scanner findings live in each run's **Summary** tab and in the `sast-reports` / `dependency-audits` / `repo-scans` artifacts. The `ml`/torch group is never installed in CI — `packages/models/tests` is not part of the gate (R11(b) above).

**Goal and audience:** Qualify is a planned agentive CRM/GTM platform for marketing/growth/community teams at brands who today juggle two separate categories of tool: social-listening platforms (Buzzmonitor-style) to *understand* the conversation, and GTM/CRM/outbound tools (Viralnetix-style) to *act* on it. Qualify fuses both: it listens to everything said about a brand and its competitors on TikTok / Instagram Reels — video, audio, captions, comments, not just text — turns that into AI-driven insights (sentiment, themes, crisis alerts, audience mapping), and converts those insights directly into marketing/sales actions (creator/lead identification and scoring, smart replies, campaign activation) without manual work in between.

Four source docs define the product and architecture — treat `README.md` as the current living summary and these as the detailed backing docs:
- `docs/plan-ingesta-social.md` — detailed Phase 1 implementation plan: infra choices, the analytical schema contract (§3, Postgres DDL since ADR 31), services/queues, payload contracts, phased task breakdown.
- `docs/ingenieria-inversa-stack-gtm.md` — reverse-engineering of the GTM tool stack (Zyte, DiscoLike, BetterContact, Trigify, PredictLeads, Warmly, Clay, Instantly, HeyReach, Zapmail) and how Qualify's architecture and roadmap map onto/against it.
- `docs/arquitectura.md` — full-system architecture across all phases: monolithic-modular core + async workers, two logical data planes on one engine (Postgres: `public` for CRM transactional state, `ingestion`/`search`/`signals` for analytics — ADR 31), a LangGraph agentive orchestrator that turns domain events into workflows, C4/sequence diagrams, and ADRs. The Phase 1 pipeline described below is one module of this larger system, not the whole planned architecture.
- `docs/alternativas-fase1.md` — buy-vs-build market research for Phase 1's three blocks (proxy rotation, social listening, outreach), with vendor options and pricing.
- `docs/modelos-multimodal-fase1.md` — open-weight model selection for the multimodal cascade (CLIP filter, vision/VLM, transcription), researched against the live Hugging Face Hub, with the specific checkpoints to use and why.

## Planned architecture (Phase 1 pipeline)

```
Zyte (scraping) → Redis/Celery (queues) → CPU workers (ffmpeg, CLIP, spam/sentiment)
  → GPU serverless (vision + whisper) → Postgres analytical schemas (facts + FTS + embeddings) + Cloudflare R2 (artifacts)
```

Design principle: each pipeline stage is idempotent and persists artifacts to R2 + state to Redis/Postgres before enqueuing the next stage. If the GPU is cold, jobs wait in `gpu_jobs` without blocking scrape or CLIP filtering.

Planned services (Python monorepo, Python 3.11+):

| Service | Runtime | Responsibility |
|---|---|---|
| api | FastAPI | Brand CRUD, enqueue URLs/handles, status queries, basic FTS search |
| scheduler | Celery Beat | Periodic monitoring of configured accounts/hashtags |
| scrape-worker | Celery | Zyte → parse hydration JSON → upload R2 → insert posts |
| extract-worker | Celery | ffmpeg keyframes (1fps + scene detect) + audio WAV |
| clip-filter-worker | Celery | CLIP zero-shot filter → marks `clip_selected` |
| gpu-enrichment | RunPod/Modal endpoint | Moondream2 (vision) + faster-whisper (transcription) |
| comment-worker | Celery | Spam rules + robertuito sentiment + insert comments |
| index-worker | Celery | Materializes rows into `search.content_index` (+ embeddings in later phases) |

Planned queues (Celery over Redis Streams): `scrape_jobs → extract_jobs → filter_jobs → gpu_jobs` / `comment_jobs → index_jobs`, with a `dead_letter_queue` after 3 retries (exponential backoff).

Planned repo layout:

Target layout, annotated with what is real as of 2026-07-26 — the tree below is the *plan*, and roughly half of it does not exist yet:

```
Qualify/
├── Qualify/                  # ✅ Reflex app: CRM UI + dashboards + C-06 connections UI
├── justfile                  # ✅ dev/up/migrate/seed/test/lint/down (not in the original plan)
├── docker-compose.yml        # ⚠  EXISTS but postgres + redis ONLY — no api/worker services; image must become pgvector/pgvector:pg16
├── infra/                    # ❌ Terraform/Pulumi (later phase)
├── packages/
│   ├── api/                  # ✅ FastAPI + tenancy + connections (not in the original plan; ADR 1 modular monolith)
│   ├── shared/               # ⚠  EXISTS as the sanctioned DB doors; the R2 client + Pydantic ID layer are NOT there yet
│   ├── scraper/              # ✅ Zyte client + TikTok/IG parsers + envelope v2
│   ├── pipeline/             # ❌ Celery tasks + orchestration (Parte 3)
│   ├── models/               # ✅ SigLIP/VLM/whisper/robertuito wrappers + C-05 capability matrix
│   ├── docs-harvester/       # ✅ Meta doc-corpus tooling (not in the original plan)
│   └── gpu-service/          # ❌ Modal/RunPod handler
├── migrations/
│   ├── postgres/             # ✅ Alembic 0001-0004 — since ADR 31 this is the ONLY migration path, analytical plane included
│   └── (no clickhouse/)      # ❌ removed by ADR 31 — the analytical schema is Alembic too
└── scripts/                  # ❌ dev helpers, backfill — superseded in practice by the justfile
```

Note: the `gpu-enrichment` row above (Moondream2 + faster-whisper) reflects `docs/plan-ingesta-social.md`'s original technical plan. `docs/modelos-multimodal-fase1.md` supersedes the specific checkpoints (`moondream/moondream3-preview` + `openai/whisper-large-v3-turbo` + `google/siglip2-base-patch16-224`, fallback `Qwen/Qwen3-VL-4B-Instruct`), updated to what's current on the Hub. Most of these weights can be served either via HF Inference Endpoints (buy, no GPU infra needed to start) or self-hosted on RunPod/Modal later, with no pipeline rewrite — see that doc's closing section. Still pending: validating these checkpoints against the golden-set evaluation described in `docs/arquitectura.md` §7 before committing in code.

**Correction on the vision checkpoint (verified live against the Hub 2026-07-21, `packages/models/NOTES_fase0_agentive_layer.md` §1.2; folded into `docs/arquitectura.md` §6 ADR 19 addendum).** Do not describe this stack as uniformly "open-weight", and do not treat `moondream/moondream3-preview` as the working vision path:

- It is **BSL 1.1** (Business Source License, licensor M87 Labs) — *not* open-weight. Hub metadata says `license: other`; the Additional Use Grant allows production use except offering the work to third parties hosted/embedded to compete with M87's paid versions; Change Date two years post-release, then Apache-2.0. Qualify's use is probably permitted, but that is a legal read, not an engineering one. ADR 13 rejected CC-BY-NC embedding models on commercial grounds — **BSL needs the same explicit test, not an implicit pass.**
- **9.27B params (~18.5 GB) and zero Inference Providers** → "buy it hosted to start" is not available for this checkpoint; it requires a real GPU from day one, inverting the buy-first sequencing.
- **It has never been run in this repo** (local cache holds 16 KB, no weights). `Qwen/Qwen3-VL-4B-Instruct` — documented as the *fallback* — is the de-facto vision checkpoint and the only one that has ever worked, with single-provider risk (featherless-ai).

`docs/modelos-multimodal-fase1.md` still carries the uncorrected vision row; fixing it is a pending action (that file was not in the architect's ownership for the 2026-07-23 session).

### Phase 1 target state

What must exist at the end of Phase 1 (per `docs/plan-ingesta-social.md` + `docs/alternativas-fase1.md`):

- **Ingestion pipeline running end-to-end:** scraping (Zyte) → frame/audio extraction (ffmpeg) → CLIP-style filter (`siglip2-base`) → vision (`Qwen3-VL-4B-Instruct` de facto; `moondream3-preview` unvalidated and BSL-licensed — see the vision-checkpoint correction above) + transcription (`whisper-large-v3-turbo`) → comment sentiment (robertuito) → all materialized into `search.content_index` (Postgres, `tsvector` + GIN) with FTS. Specific checkpoints and rationale in `docs/modelos-multimodal-fase1.md`.
- **Analytical schemas live in Postgres** (`ingestion`/`search`/`signals`), created by Alembic with RLS in the same revision as each table — see `docs/plan-ingesta-social.md` §3.15 for the acceptance checklist.
- **Vendor decisions locked for all three Phase 1 blocks** (decision made, not necessarily every feature built): proxies → Zyte, fallback Decodo/Bright Data; ingestion → either Zyte scraping built in-house or EnsembleData/Data365 bought as an API (evaluate real cost before committing); transcription/vision hosting → start via HF Inference Endpoints (buy, no GPU infra), migrate to self-hosted RunPod/Modal once volume justifies it — same checkpoints either way, no pipeline rewrite; **outreach → vendor decided (Zapmail/Smartlead/Prospeo) but the outreach feature itself is still Phase 5 work** — see the roadmap note below, this isn't a contradiction between `README.md` and the phase map.
- **Phase 1 principle:** only orchestration (Celery) and the multimodal analysis layer (the differentiator) get built; everything else (proxies, raw ingestion, transcription, email infra) is bought via API.

## Data model conventions (analytical plane = PostgreSQL)

> **Engine reversed 2026-08-05 — ADR 31, founder's call.** The analytical plane is **PostgreSQL**, not ClickHouse: at the real volume (~12.5M rows/year) none of ADR 3's three justifications hold. ClickHouse returns at a measured threshold (`search.content_index` > 100M rows, or p95 > 2s with tuned indexes, or a customer generating > 5,000 posts/day). **When a research or market doc in `docs/` says "ClickHouse", read "the analytical plane"** — those docs record analyses written before the reversal and their conclusions are engine-independent; they were deliberately not rewritten.

- Same database as the CRM, in separate schemas: `ingestion` (structured per-platform facts), `search` (unified text + vectors), `signals` (typed derived signals). The transactional plane stays in `public`. Full DDL: `docs/plan-ingesta-social.md` §3.
- **Two data planes are still two planes** — but the separation is now module discipline (each module writes its own schema), not physical impossibility. Reads may `JOIN` across them; that is the point of the reversal.
- Natural idempotency key is `(brand_id, platform, post_id)`, materialized as a **`UNIQUE` constraint** plus `INSERT … ON CONFLICT DO UPDATE` with a monotonic guard (`WHERE EXCLUDED.updated_at > …`) so a late retry never overwrites newer state. Dedup is a guarantee at INSERT time, not an eventual merge.
- **Indexes are no longer irreversible.** Design them around expected filters (`tenant_id`, `brand_id`, date range, `content_type`), but getting one wrong is a `CREATE INDEX`, not a re-ingest. The one remaining expensive change is converting a populated table to partitioned — threshold and warning in `plan-ingesta-social.md` §3.1(e).
- **RLS on every analytical table** (`tenant_id NOT NULL` + `ENABLE` + `FORCE` + the `NULLIF(current_setting('app.tenant_id', true), '')::uuid` policy of migration 0001). This retires the contrapartida ADR 24 had accepted, where earned-media rows did not self-isolate. One deliberate exception: `ingestion.raw_payloads` is brand-agnostic by design (ADR 18) and holds only a public URL and a hash.
- Raw scrape payloads (Zyte hydration JSON) are always kept in R2 (`hydration_json_r2_key` etc.) so posts can be re-parsed without re-scraping — scraping costs money per request. **This is what keeps ADR 31 reversible:** the analytical plane is reconstructible, so migrating to ClickHouse later is an ETL over regenerable data.
- `search.content_index` is a denormalized FTS table (one row per indexable text fragment: caption/frame/transcript/comment) using a generated `tsvector` + GIN for token search and `pg_trgm` + GIN for substring.
- `search.embeddings_text_*` (one table per `(modality, model, dim)` — ADR 11 survives, `pgvector` also needs a fixed dim), `signals.events`, `crm.creator_centroids_text` and `billing.usage_events` are designed but not implemented — later phases. Do **not** create them in Parte 3.
- Every derived signal or enrichment must carry **provenance**: the source `post_id`/`comment_id`/`source_id` it was computed from, plus `detector_version`/`pipeline_version` (and `<x>_model_revision` for anything a model wrote). This is a hard architectural rule across the docs, not a nice-to-have, and it is engine-independent.

## Roadmap phase map

Consult this before adding scope to a task — it determines what's in-bounds now vs. later:

1. **Phase 1 (current)** — Social ingestion/enrichment pipeline for TikTok/IG Reels: scraping, frame/audio extraction, CLIP filtering, vision descriptions, transcription, comment sentiment, FTS index. This is the foundational data layer everything else builds on. Per `docs/alternativas-fase1.md`, Phase 1 also locks the buy-vs-build vendor decision for outreach infra (Zapmail/Smartlead/Prospeo) — but building the outreach *feature* is still Phase 5, see below. Don't read "outreach" appearing in both places as a doc inconsistency. Phase 1 also gains a **Parte 4 — first-party (connected-account) ingestion via the Meta platform API** (sibling of Parte 2 scraping, hard-dependent on Parte 3), which is where the signed Parte 4-A/4-B dogfooding slices land (see ADR 21/22/24 and the reclassification note below).
2. **Phase 2** — Social listening + AI Insights: saved queries/scheduler, sentiment/topic reporting, LLM summaries over `search.content_index`, real-time dashboards.
3. **Phase 3** — Signals layer (elevated priority per the GTM stack analysis) + advanced visual listening: typed, composable signal detectors with provenance (`signals.events`), in-video/audio mention alerts, logo/product detection, visual clustering.
4. **Phase 4** — Creator discovery + CRM: `crm.creators` with content-embedding centroids for lookalike/semantic search, contact waterfall enrichment (bio → link-in-bio → website → third-party API fallback), creator/lead scoring.
5. **Phase 5** — GTM activation: packaged "plays" (signal → enrich → AI-drafted action → push), RAG smart replies, credit-based billing (`billing.usage_events`), MCP server over the API, outbound integration via Instantly/HeyReach or Smartlead+Zapmail (buy, don't build — vendor already selected in Phase 1).
6. **Phase 6** — Platform hardening: **residual** multi-tenant isolation only (resource quotas, compute isolation, full multi-tenant audit — the `tenant_id` identifier + Postgres RLS + tenant-scoped R2 keying moved forward to foundation, see ADR 24), natural-language configuration co-pilot, the **cross-channel unified** social inbox + cross-channel context graph (the *single-channel* inbox for a tenant's own connected accounts moved forward to Parte 4-B, see ADR 21/24 — a mailbox is not a unified inbox until it unifies more than one channel), observability/SLAs, infra scale-up.

> **MULTI-TENANCY LEAVES PHASE 6 — APROBADO (firmado por el fundador 2026-07-24, B0-6/A5-3, ADR 24).** Phase 6 lists "multi-tenant isolation" last. That ordering assumed single-tenant-until-scale, and **that premise is now false: there are two real tenants on day one.** Ruling: the **identifier** `tenant_id` and its propagation are **foundation, not hardening**, and so are Postgres RLS and the tenant-scoped R2 keying of ADR 22. Rate-limit fair-share is a later layer; resource quotas and full multi-tenant audit stay in Phase 6 — moving the whole block would be as wrong as moving none. Decisive reason: **the identifier ends up in the analytical schema's keys** (at the time, a ClickHouse `ORDER BY` prefix, which was immutable — ADR 31 later removed that irreversibility, but the ruling stands and is now enforced by RLS), and it is greenfield *right now* (zero occurrences of `tenant_id`/`workspace_id` in the repo, verified) — this is the last cheap window. Note `brand_id` does **not** merge into it: `brand_id` = what is observed, `tenant_id` = who may see it, and merging them would break ADR 18's surviving "N brands share one scrape" economy. Separately, the **unified social inbox** conflict splits: a single-channel inbox for a tenant's connected accounts comes now (Parte 4-B), while the *unified cross-channel* inbox stays Phase 6 — **a mailbox is not a unified inbox until it unifies more than one channel.**

> **RECLASSIFICATION — APROBADO, firmado por el fundador 2026-07-24 (B0-6/A5-3) y aplicado.** The numbered map above still orders **the product** (multi-tenant SaaS over earned media). On top of it the founder signed a **dogfooding track over own media** that draws concrete slices forward, recorded as **ADR 21 (APROBADO)** in `docs/arquitectura.md` §6:
> - **Parte 4-A (now, was Fase 5):** publishing reels/stories/organic promos to accounts the operator administers — built thin, it is commodity.
> - **Parte 4-B (now):** the *single-channel* DM/comment inbox for the tenant's own connected accounts (Postgres plane, least blocked by the Fase 1 Parte 3 critical path), plus **assisted** replies (draft + human approval). **Autonomous** replies stay permanently out — a precision problem (65% precision = 1 in 3 drafts wrong), not a phase problem. The *cross-channel unified* inbox stays Fase 6.
> - **Out / unchanged:** **scheduled publishing to TikTok is blocked, not scheduled** — per TikTok's own docs an unaudited API client forces the posting account itself to be private, regardless of who owns it, with no engineering mitigation; multi-agent seats remain unphased (they are customer one — the realtor — not customer zero). Paid advertising (Marketing API / `ads_management`) is a deferred future research/ADR item, not in ADR 21's organic-first scope.
>
> The one verification (task V1 — whether the IG publish/messaging permissions are Advanced-only by nature) that could have overturned the Meta half is now **CLOSED**: access level is a property of the app and the scenario, not of the permission — no "Advanced-only permission" trap exists. Note the boundary the reclassification rests on: standard access (Development Mode) is proven **review-free** for customer zero, but **not proven functionally complete for publishing** — Advanced Access + App Review + Business Verification still bind at **customer one**, and that administrative clock should start week 0 (see the ADR 21 enmienda in §6).
>
> **OPEN TENSION flagged 2026-07-30 (architect; `docs/arquitectura.md` §6, "Revisión 2026-07-30" at the end of the ADR 19 support note) — do not resolve it by writing more Parte 4 code without asking.** ADR 21 (a) says Parte 4-A is *"commodity, built thin"*, and the build/buy list below has no row for owned-media publishing/DM fan-out. Verified against Zernio's real endpoint reference (3.6 MB OpenAPI dump, not marketing): **an aggregator sells the whole of Parte 4-A + 4-B for $1–6/connected-account/month, operating under an app already through Meta's App Review *and* TikTok's audit** — the exact administrative clock the paragraph above says binds at customer one. Applying `CLAUDE.md`'s own rule, that is **buy**, not build-thin. What this would displace is real and should be named before anyone decides: `packages/api/src/qualify_api/connections/` (Sprint 1, C-03/C-04) and `packages/api/src/qualify_api/publishing/`. **What it displaces nothing of: Partes 1-3.** No aggregator sells earned-media reads on TikTok or Instagram — zero endpoints, at any price — so the scraper, the multimodal cascade, and ADR 17 are untouched. Founder-gated; nothing changes in the list below until then.

> **REFINEMENT 2026-07-29 (ADR 29, `[PROPUESTO]` and GATED — architect ruling; `docs/arquitectura.md` §6, ADR 29 row + the "Enmienda a ADR 21 / ADR 24 (2026-07-29)" block).** Three corrections to the paragraph above. None reverses it; all three widen the cheap side of the boundary.
>
> 1. **New founder-supplied fact:** the founder is **also the builder and administrator of the realtor's software stack**. Customer one is therefore **not** an arm's-length client. Docs written before today describe it as external; that is no longer accurate. The boundary that matters is not "customer zero vs customer one" — it is **assets the founder administers vs assets he does not**. The first customer whose assets he does *not* administer is **customer two**.
> 2. **The administrative clock does not block *building or testing* the multi-tenant path.** Meta's own documented test configuration for the Tech Provider token flow is *"the tester must have a role on the app **and full control of the client business**"* — which the founder satisfies for customer one. So asset delegation, `client_business_id`, granular tokens and client-side revocation are all buildable and verifiable under Standard Access with **no App Review**. The clock blocks going to **production** with customer one, not the engineering.
> 3. **"Access level is a property of the app and the scenario, not of the permission" is imprecise** — it is a property of the **(app, permission) pair**. V1 stays closed (no permission is Advanced-only by nature), but App Review is granted **per permission**, so the messaging half can be submitted without dragging the publishing half. The **App Mode** (Development vs Live) *is* app-global, and there is an unresolved 2018-changelog ambiguity about whether Standard-Access permissions keep working for role-holders once an app goes Live — see (d) in that amendment; it must be settled by the same empirical test ADR 21 already requires.

Key strategic decisions carried across the docs — respect these when proposing designs:
- **Buy, don't build**: web access/proxies (Zyte), outbound email/LinkedIn sending, mailbox infra, B2B contact databases, company-intel crawling, generic spreadsheet-style orchestration (à la Clay). Qualify integrates with these via API rather than reimplementing them.
- **Build**: the social ingestion pipeline itself, the signals layer with provenance, creator lookalike discovery over proprietary content embeddings, and the cross-channel context graph — these are the differentiated core.
- Primary source content (actual video/audio/transcript) is treated as the trust advantage over competitors who rely on self-reported bio/metadata — preserve this "read the content, not the profile" principle in any discovery/scoring feature.

## Stack (tentative)

Python 3.11+ · FastAPI · Celery + Redis 7 · PostgreSQL (both planes: CRM transactional state + analytics/listening, ADR 31) · `pgvector` (Fase 4) · Cloudflare R2 · Zyte API · `google/siglip2-base-patch16-224` (CLIP-style zero-shot filter) · `Qwen/Qwen3-VL-4B-Instruct` (vision, de-facto — the only vision path ever run here; `moondream/moondream3-preview` is BSL 1.1, 9.27B, no hosted provider, never run — see the correction above) or Gemini Flash · `openai/whisper-large-v3-turbo` (transcription, self-hosted via faster-whisper or bought via Groq — same weights) · `pysentimiento/robertuito-sentiment-analysis` (sentiment) · `MoritzLaurer/bge-m3-zeroshot-v2.0` (text zero-shot topic/intent classifier, proposed for the Phase 3 typed-signals detection primitive — not yet committed, see below) · sentence-transformers · LangGraph (agentive orchestrator) · Reflex (CRM UI/dashboards) · HF Inference Endpoints (to start, no GPU infra) → RunPod/Modal (GPU serverless, once volume justifies self-hosting) · Hetzner VPS · Instantly/HeyReach or Smartlead+Zapmail (outreach, buy) · Prospeo (email finding, buy) · Shopify API (attribution)

This is tentative: the buy-vs-build research in `docs/alternativas-fase1.md` (e.g. ingestion via EnsembleData/Data365 instead of Zyte scrapers built in-house) can still move pieces of this stack before Phase 1 implementation starts. The multimodal checkpoints specifically come from `docs/modelos-multimodal-fase1.md` and still need golden-set validation (`docs/arquitectura.md` §7) before being locked into code. Don't treat any single vendor/model choice as final until it shows up in code or a merged ADR. The zero-shot text classifier is a Phase 3 proposal, not a Phase 1 commitment: `packages/models/NOTES_pain_signal_feasibility.md` (datasci, 2026-07-18) found that the committed sentiment model (3-class polarity) can't carry most pain-point/intent signals (payment complaints, brand-deal friction, sponsorship intent) that the Phase 3 typed-signals library (`docs/backlog-features-gtm.md` P3-1) needs — this checkpoint is the proposed detection primitive that closes that gap. See `docs/modelos-multimodal-fase1.md` "Clasificador zero-shot de texto" for the full candidate table and cost analysis.

## Conventions

- **Language:** product docs (`README.md`, everything under `docs/`) are Spanish; `CLAUDE.md` and code (including identifiers, comments, docstrings) stay English.
- **Commits:** Conventional Commits in English (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, ...).
- **Code style:** `ruff` for both lint and format — **configured** in the root `pyproject.toml` (line-length 100, `select = ["E", "F", "I", "UP"]`); run via `just lint` / `just fmt`. Type hints are required on every new function/method signature.
- **Tooling: always use `uv`, never bare `pip`/`conda`.** Project dependencies via `uv add` / `uv sync` / `uv run`; standalone CLI tools (e.g. the Hugging Face Hub `hf` CLI) via `uv tool install` rather than a curl-installer or a global `pip install`. This keeps every tool isolated from the system/anaconda Python and reproducible from `pyproject.toml` + `uv.lock`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
