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

This repo is **mostly pre-implementation** with respect to the actual product described below: there is no `docker-compose.yml`, no `migrations/`, no `scripts/`, no api/worker code, and no ClickHouse/Postgres yet. The one exception is `packages/models/` — see below. What exists on disk today is:

- `README.md` (the most current, living summary of vision/architecture/roadmap) and five planning docs in `docs/` (see "What Qualify is" for what each one covers).
- `packages/models/` — a standalone `uv` project (own `pyproject.toml`/`.venv`, not part of a workspace yet) implementing Fase 1 Parte 1: the multimodal analysis cascade (filter, vision, transcription, sentiment) as composable, typed functions with a `Provider` abstraction (local `transformers` for the small models, HF Inference Providers for the hosted VLM/ASR ones — swappable for self-hosted later, no rewrite). Runs against fixtures in `tests/fixtures/` (a real public TikTok sample video, frame + audio extracted via `ffmpeg`), not against live scraping — Parte 2 (scraping) and Parte 3 (ClickHouse/Celery/Postgres orchestration) don't exist yet. See `docs/plan-ingesta-social.md` §0 for the Parte 1/2/3 ordering and why it's sequenced this way, and `docs/modelos-multimodal-fase1.md` for the model choices this package implements.
- A `Qualify/` **Reflex** app (`rxconfig.py`, `Qualify/Qualify.py`, `assets/`, `reflex.lock/`) — as of the "mentions dashboard scaffold" commit it's no longer the default welcome-page template: it has a sidebar/topbar/stats-row/filter-bar/mentions-table UI, a SQLModel-backed `db.py` with seed data, and a `DashboardState` loading mentions on page load. **Reflex is now the decided CRM UI** (see `docs/arquitectura.md` §2 and §6 ADR 8), replacing the earlier Next.js placeholder. It's still exploratory and unconnected to the real Fase 1 pipeline — it runs against local SQLite/seed data, not ClickHouse.

Before assuming any file, service, or command exists, check the actual filesystem rather than trusting the docs, since the docs describe target architecture.

### Commands

The Reflex scaffold uses `uv` (`pyproject.toml` + `uv.lock`, Python >=3.12):

```bash
uv sync                 # install/sync dependencies into .venv
uv run reflex run       # start the Reflex dev server (frontend + backend)
```

Follow the **reflex-process-management** skill (see Agents section above) rather than running `reflex` commands ad hoc — it covers the correct start/reload/debug sequence. There is no lint or test tooling configured yet (no ruff/pytest config, no test files) — nothing to run there until it's added.

## What Qualify is

**Goal and audience:** Qualify is a planned agentive CRM/GTM platform for marketing/growth/community teams at brands who today juggle two separate categories of tool: social-listening platforms (Buzzmonitor-style) to *understand* the conversation, and GTM/CRM/outbound tools (Viralnetix-style) to *act* on it. Qualify fuses both: it listens to everything said about a brand and its competitors on TikTok / Instagram Reels — video, audio, captions, comments, not just text — turns that into AI-driven insights (sentiment, themes, crisis alerts, audience mapping), and converts those insights directly into marketing/sales actions (creator/lead identification and scoring, smart replies, campaign activation) without manual work in between.

Four source docs define the product and architecture — treat `README.md` as the current living summary and these as the detailed backing docs:
- `docs/plan-ingesta-social.md` — detailed Phase 1 implementation plan: infra choices, ClickHouse schema, services/queues, payload contracts, phased task breakdown.
- `docs/ingenieria-inversa-stack-gtm.md` — reverse-engineering of the GTM tool stack (Zyte, DiscoLike, BetterContact, Trigify, PredictLeads, Warmly, Clay, Instantly, HeyReach, Zapmail) and how Qualify's architecture and roadmap map onto/against it.
- `docs/arquitectura.md` — full-system architecture across all phases: monolithic-modular core + async workers, two data planes (Postgres for CRM transactional state, ClickHouse for analytics), a LangGraph agentive orchestrator that turns domain events into workflows, C4/sequence diagrams, and ADRs. The Phase 1 pipeline described below is one module of this larger system, not the whole planned architecture.
- `docs/alternativas-fase1.md` — buy-vs-build market research for Phase 1's three blocks (proxy rotation, social listening, outreach), with vendor options and pricing.
- `docs/modelos-multimodal-fase1.md` — open-weight model selection for the multimodal cascade (CLIP filter, vision/VLM, transcription), researched against the live Hugging Face Hub, with the specific checkpoints to use and why.

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
├── Qualify/                  # Reflex app: CRM UI + dashboards (rxconfig.py, state, components) — exists today
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

Note: the `gpu-enrichment` row above (Moondream2 + faster-whisper) reflects `docs/plan-ingesta-social.md`'s original technical plan. `docs/modelos-multimodal-fase1.md` supersedes the specific checkpoints (`moondream/moondream3-preview` + `openai/whisper-large-v3-turbo` + `google/siglip2-base-patch16-224`, fallback `Qwen/Qwen3-VL-4B-Instruct`) — same open-weight approach, updated to what's current on the Hub. These weights can be served either via HF Inference Endpoints (buy, no GPU infra needed to start) or self-hosted on RunPod/Modal later, with no pipeline rewrite — see that doc's closing section. Still pending: validating these checkpoints against the golden-set evaluation described in `docs/arquitectura.md` §7 before committing in code.

### Phase 1 target state

What must exist at the end of Phase 1 (per `docs/plan-ingesta-social.md` + `docs/alternativas-fase1.md`):

- **Ingestion pipeline running end-to-end:** scraping (Zyte) → frame/audio extraction (ffmpeg) → CLIP-style filter (`siglip2-base`) → vision (`moondream3-preview`) + transcription (`whisper-large-v3-turbo`) → comment sentiment (robertuito) → all materialized into `search.content_index` (ClickHouse) with FTS. Specific checkpoints and rationale in `docs/modelos-multimodal-fase1.md`.
- **Vendor decisions locked for all three Phase 1 blocks** (decision made, not necessarily every feature built): proxies → Zyte, fallback Decodo/Bright Data; ingestion → either Zyte scraping built in-house or EnsembleData/Data365 bought as an API (evaluate real cost before committing); transcription/vision hosting → start via HF Inference Endpoints (buy, no GPU infra), migrate to self-hosted RunPod/Modal once volume justifies it — same checkpoints either way, no pipeline rewrite; **outreach → vendor decided (Zapmail/Smartlead/Prospeo) but the outreach feature itself is still Phase 5 work** — see the roadmap note below, this isn't a contradiction between `README.md` and the phase map.
- **Phase 1 principle:** only orchestration (Celery) and the multimodal analysis layer (the differentiator) get built; everything else (proxies, raw ingestion, transcription, email infra) is bought via API.

## Data model conventions (ClickHouse)

- Database `crm`, with logical prefixes `ingestion.*` (structured per-platform data) and `search.*` (unified text + vectors, consumed by later modules).
- Natural idempotency key is `(brand_id, platform, post_id)`; tables use `ReplacingMergeTree` keyed on `updated_at`/`created_at` for upserts, partitioned by `toYYYYMM(posted_date)`. **`ORDER BY` is immutable once chosen** — design it around expected filters (`brand_id`, `platform`, date range, `post_id`) before creating a table.
- Raw scrape payloads (Zyte hydration JSON) are always kept in R2 (`hydration_json_r2_key` etc.) so posts can be re-parsed without re-scraping — scraping costs money per request.
- `search.content_index` is a denormalized FTS table (one row per indexable text fragment: caption/frame/transcript/comment) using `tokenbf_v1`/`ngrambf_v1` bloom filter indexes for token and substring search.
- `search.embeddings` and the `signals.events` / `crm.creators` / `billing.usage_events` tables (see `docs/ingenieria-inversa-stack-gtm.md` §4.1) are designed but not yet implemented — they belong to later phases.
- Every derived signal or enrichment must carry **provenance**: the source `post_id`/`comment_id`/`source_id` it was computed from, plus a `detector_version`/`pipeline_version`. This is treated as a hard architectural rule across the docs, not a nice-to-have.

## Roadmap phase map

Consult this before adding scope to a task — it determines what's in-bounds now vs. later:

1. **Phase 1 (current)** — Social ingestion/enrichment pipeline for TikTok/IG Reels: scraping, frame/audio extraction, CLIP filtering, vision descriptions, transcription, comment sentiment, FTS index. This is the foundational data layer everything else builds on. Per `docs/alternativas-fase1.md`, Phase 1 also locks the buy-vs-build vendor decision for outreach infra (Zapmail/Smartlead/Prospeo) — but building the outreach *feature* is still Phase 5, see below. Don't read "outreach" appearing in both places as a doc inconsistency.
2. **Phase 2** — Social listening + AI Insights: saved queries/scheduler, sentiment/topic reporting, LLM summaries over `search.content_index`, real-time dashboards.
3. **Phase 3** — Signals layer (elevated priority per the GTM stack analysis) + advanced visual listening: typed, composable signal detectors with provenance (`signals.events`), in-video/audio mention alerts, logo/product detection, visual clustering.
4. **Phase 4** — Creator discovery + CRM: `crm.creators` with content-embedding centroids for lookalike/semantic search, contact waterfall enrichment (bio → link-in-bio → website → third-party API fallback), creator/lead scoring.
5. **Phase 5** — GTM activation: packaged "plays" (signal → enrich → AI-drafted action → push), RAG smart replies, credit-based billing (`billing.usage_events`), MCP server over the API, outbound integration via Instantly/HeyReach or Smartlead+Zapmail (buy, don't build — vendor already selected in Phase 1).
6. **Phase 6** — Platform hardening: multi-tenant isolation, natural-language configuration co-pilot, unified social inbox, cross-channel context graph, observability/SLAs, infra scale-up.

Key strategic decisions carried across the docs — respect these when proposing designs:
- **Buy, don't build**: web access/proxies (Zyte), outbound email/LinkedIn sending, mailbox infra, B2B contact databases, company-intel crawling, generic spreadsheet-style orchestration (à la Clay). Qualify integrates with these via API rather than reimplementing them.
- **Build**: the social ingestion pipeline itself, the signals layer with provenance, creator lookalike discovery over proprietary content embeddings, and the cross-channel context graph — these are the differentiated core.
- Primary source content (actual video/audio/transcript) is treated as the trust advantage over competitors who rely on self-reported bio/metadata — preserve this "read the content, not the profile" principle in any discovery/scoring feature.

## Stack (tentative)

Python 3.11+ · FastAPI · Celery + Redis 7 · PostgreSQL (CRM transactional state) · ClickHouse (analytics/listening) · Cloudflare R2 · Zyte API · `google/siglip2-base-patch16-224` (CLIP-style zero-shot filter) · `moondream/moondream3-preview` (vision, fallback `Qwen/Qwen3-VL-4B-Instruct`) or Gemini Flash · `openai/whisper-large-v3-turbo` (transcription, self-hosted via faster-whisper or bought via Groq — same weights) · `pysentimiento/robertuito-sentiment-analysis` (sentiment) · `MoritzLaurer/bge-m3-zeroshot-v2.0` (text zero-shot topic/intent classifier, proposed for the Phase 3 typed-signals detection primitive — not yet committed, see below) · sentence-transformers · LangGraph (agentive orchestrator) · Reflex (CRM UI/dashboards) · HF Inference Endpoints (to start, no GPU infra) → RunPod/Modal (GPU serverless, once volume justifies self-hosting) · Hetzner VPS · Instantly/HeyReach or Smartlead+Zapmail (outreach, buy) · Prospeo (email finding, buy) · Shopify API (attribution)

This is tentative: the buy-vs-build research in `docs/alternativas-fase1.md` (e.g. ingestion via EnsembleData/Data365 instead of Zyte scrapers built in-house) can still move pieces of this stack before Phase 1 implementation starts. The multimodal checkpoints specifically come from `docs/modelos-multimodal-fase1.md` and still need golden-set validation (`docs/arquitectura.md` §7) before being locked into code. Don't treat any single vendor/model choice as final until it shows up in code or a merged ADR. The zero-shot text classifier is a Phase 3 proposal, not a Phase 1 commitment: `packages/models/NOTES_pain_signal_feasibility.md` (datasci, 2026-07-18) found that the committed sentiment model (3-class polarity) can't carry most pain-point/intent signals (payment complaints, brand-deal friction, sponsorship intent) that the Phase 3 typed-signals library (`docs/backlog-features-gtm.md` P3-1) needs — this checkpoint is the proposed detection primitive that closes that gap. See `docs/modelos-multimodal-fase1.md` "Clasificador zero-shot de texto" for the full candidate table and cost analysis.

## Conventions

- **Language:** product docs (`README.md`, everything under `docs/`) are Spanish; `CLAUDE.md` and code (including identifiers, comments, docstrings) stay English.
- **Commits:** Conventional Commits in English (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, ...).
- **Code style:** `ruff` for both lint and format once real Python code exists under `packages/`; type hints are required on every new function/method signature. Not wired into `pyproject.toml` yet since `packages/` doesn't exist — apply this from the first commit that adds code there.
- **Tooling: always use `uv`, never bare `pip`/`conda`.** Project dependencies via `uv add` / `uv sync` / `uv run`; standalone CLI tools (e.g. the Hugging Face Hub `hf` CLI) via `uv tool install` rather than a curl-installer or a global `pip install`. This keeps every tool isolated from the system/anaconda Python and reproducible from `pyproject.toml` + `uv.lock`.
