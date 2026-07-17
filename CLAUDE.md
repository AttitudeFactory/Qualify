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

This repo is **pre-implementation** with respect to the actual product described below: there is no `docker-compose.yml`, no `packages/`, no `migrations/`, no `scripts/`, and no api/worker code yet. What exists on disk today is:

- `README.md` and two planning docs in `docs/` (see "What Qualify is").
- A bare `Qualify/` **Reflex** app produced by `reflex init` (`rxconfig.py`, `Qualify/Qualify.py`, `assets/`, `reflex.lock/`) — still the unmodified default welcome-page template. This scaffold exists because of the Agents/Reflex-skills instructions above, not because the planning docs call for Reflex: **neither `docs/plan-ingesta-social.md` nor `docs/ingenieria-inversa-stack-gtm.md` mentions Reflex**, and the planned Phase 1 architecture is FastAPI + Celery + ClickHouse services, not a Reflex app. Don't assume Reflex is the intended frontend for that pipeline unless the user says so — treat it as a separate, currently-unconnected scaffold.

Before assuming any file, service, or command exists, check the actual filesystem rather than trusting the docs, since the docs describe target architecture.

### Commands

The Reflex scaffold uses `uv` (`pyproject.toml` + `uv.lock`, Python >=3.12):

```bash
uv sync                 # install/sync dependencies into .venv
uv run reflex run       # start the Reflex dev server (frontend + backend)
```

Follow the **reflex-process-management** skill (see Agents section above) rather than running `reflex` commands ad hoc — it covers the correct start/reload/debug sequence. There is no lint or test tooling configured yet (no ruff/pytest config, no test files) — nothing to run there until it's added.

## What Qualify is

Qualify is a planned CRM/GTM platform that fuses AI-driven social listening (TikTok / Instagram Reels — video, audio, captions, comments) with a revenue-activation engine: it listens to everything said about a brand and its competitors on social, turns that into insights, and converts those insights directly into marketing/sales actions (creator/lead identification, smart replies, crisis alerts, campaigns).

Two source docs define the product and architecture:
- `docs/plan-ingesta-social.md` — detailed Phase 1 implementation plan: infra choices, ClickHouse schema, services/queues, payload contracts, phased task breakdown.
- `docs/ingenieria-inversa-stack-gtm.md` — reverse-engineering of the GTM tool stack (Zyte, DiscoLike, BetterContact, Trigify, PredictLeads, Warmly, Clay, Instantly, HeyReach, Zapmail) and how Qualify's architecture and roadmap map onto/against it.

## Planned architecture (Phase 1 pipeline)

```
Zyte (scraping) → Redis/Celery (queues) → CPU workers (ffmpeg, CLIP, spam/sentiment)
  → GPU serverless (vision + whisper) → ClickHouse (analytics + FTS + embeddings) + Cloudflare R2 (artifacts)
```

Design principle: each pipeline stage is idempotent and persists artifacts to R2 + state to Redis/ClickHouse before enqueuing the next stage. If the GPU is cold, jobs wait in `gpu_jobs` without blocking scrape or CLIP filtering.

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

```
Qualify/
├── docker-compose.yml       # ClickHouse, Redis, api, workers (local)
├── infra/                   # Terraform/Pulumi (later phase)
├── packages/
│   ├── shared/               # Pydantic schemas, IDs, R2 client
│   ├── scraper/               # Zyte client + TikTok/IG parsers
│   ├── pipeline/               # Celery tasks + orchestration
│   ├── models/                 # CLIP, robertuito wrappers
│   └── gpu-service/            # Modal/RunPod handler
├── migrations/clickhouse/    # Versioned DDL
└── scripts/                  # dev helpers, backfill
```

## Data model conventions (ClickHouse)

- Database `crm`, with logical prefixes `ingestion.*` (structured per-platform data) and `search.*` (unified text + vectors, consumed by later modules).
- Natural idempotency key is `(brand_id, platform, post_id)`; tables use `ReplacingMergeTree` keyed on `updated_at`/`created_at` for upserts, partitioned by `toYYYYMM(posted_date)`. **`ORDER BY` is immutable once chosen** — design it around expected filters (`brand_id`, `platform`, date range, `post_id`) before creating a table.
- Raw scrape payloads (Zyte hydration JSON) are always kept in R2 (`hydration_json_r2_key` etc.) so posts can be re-parsed without re-scraping — scraping costs money per request.
- `search.content_index` is a denormalized FTS table (one row per indexable text fragment: caption/frame/transcript/comment) using `tokenbf_v1`/`ngrambf_v1` bloom filter indexes for token and substring search.
- `search.embeddings` and the `signals.events` / `crm.creators` / `billing.usage_events` tables (see `docs/ingenieria-inversa-stack-gtm.md` §4.1) are designed but not yet implemented — they belong to later phases.
- Every derived signal or enrichment must carry **provenance**: the source `post_id`/`comment_id`/`source_id` it was computed from, plus a `detector_version`/`pipeline_version`. This is treated as a hard architectural rule across the docs, not a nice-to-have.

## Roadmap phase map

Consult this before adding scope to a task — it determines what's in-bounds now vs. later:

1. **Phase 1 (current)** — Social ingestion/enrichment pipeline for TikTok/IG Reels: scraping, frame/audio extraction, CLIP filtering, vision descriptions, transcription, comment sentiment, FTS index. This is the foundational data layer everything else builds on.
2. **Phase 2** — Social listening + AI Insights: saved queries/scheduler, sentiment/topic reporting, LLM summaries over `search.content_index`, real-time dashboards.
3. **Phase 3** — Signals layer (elevated priority per the GTM stack analysis) + advanced visual listening: typed, composable signal detectors with provenance (`signals.events`), in-video/audio mention alerts, logo/product detection, visual clustering.
4. **Phase 4** — Creator discovery + CRM: `crm.creators` with content-embedding centroids for lookalike/semantic search, contact waterfall enrichment (bio → link-in-bio → website → third-party API fallback), creator/lead scoring.
5. **Phase 5** — GTM activation: packaged "plays" (signal → enrich → AI-drafted action → push), RAG smart replies, credit-based billing (`billing.usage_events`), MCP server over the API, outbound integration via Instantly/HeyReach (buy, don't build).
6. **Phase 6** — Platform hardening: multi-tenant isolation, natural-language configuration co-pilot, unified social inbox, cross-channel context graph, observability/SLAs, infra scale-up.

Key strategic decisions carried across the docs — respect these when proposing designs:
- **Buy, don't build**: web access/proxies (Zyte), outbound email/LinkedIn sending, mailbox infra, B2B contact databases, company-intel crawling, generic spreadsheet-style orchestration (à la Clay). Qualify integrates with these via API rather than reimplementing them.
- **Build**: the social ingestion pipeline itself, the signals layer with provenance, creator lookalike discovery over proprietary content embeddings, and the cross-channel context graph — these are the differentiated core.
- Primary source content (actual video/audio/transcript) is treated as the trust advantage over competitors who rely on self-reported bio/metadata — preserve this "read the content, not the profile" principle in any discovery/scoring feature.
