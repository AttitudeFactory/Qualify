---
name: qualify-context
description: What Qualify is today — the business (Attitude Factory, the multi-business operator model, the real clients and markets, Meta verification status), the application as built (each screen and its module, data, AI vendors, workers, what is still unbuilt), the signed decisions not to undo, and the house rules with pointers to the procedure skills. Load at the start of any work on Qualify and for any product, client, roadmap or status question.
---

# Qualify — what it is today, and the house rules

The single place where the business and application reality is kept current. Every Qualify
agent preloads this skill; the main thread loads it for any product, client or status question.
When the business changes, update this file.

**Snapshot: 2026-10-22** (`main` at `ebe14e6`, migration head `0076_piece_media_retention`).
A snapshot decays. The standing rule still applies: **read the filesystem, not docs, for what
exists** — `ls`, `git log`, `gh pr list` beat any paragraph here, including this one.

## 1. The business

- **Who:** Attitude Factory (founder: Herwin). Qualify is its product. Team in Lark: Herwin
  (founder), Darwin (cofounder), and developers Yesika, Deivid and Raul. Realtor-side clients sit
  in a separate Lark department and stay out of internal channels.
- **Model (signed 2026-08-16):** the *multi-business operator* — one installation serving N
  businesses, **`1 login = 1 tenant = 1 negocio`**, no switcher (change business = logout +
  login). `docs/modelo-negocio-operador-multi-emprendimiento.md`. Agency-managed service for third
  parties also exists (`docs/oferta-mercado-agencia-gestionada.md`).
- **Real users today** are businesses the founder operates or administers: food/beverage
  (Bianki — shawarma and salads; Polette — frozen yogurt, formerly «Polet Bubble Tea»; both in
  Korner, San Cristóbal; PuntoServis), real estate (the realtor,
  Táchira/Cúcuta), a travel agency in Cúcuta. Markets: Colombia, Venezuela, Uruguay. Spanish
  speakers, small businesses, not enterprise marketing teams.
- **Signup is invite-code only** (`just invite …`); client onboarding («Alta de cliente») is run
  from Meegle — skill `meegle-altas`.
- **Meta:** business portfolio **verified 2026-10-05**; the app is Live; App Review is the open
  administrative clock (publishing/messaging scopes, and now `ads_management` for ADR 38).
  Standard access works for assets the founder administers (ADR 29).
- **Domains:** product landing `qualify.la` (Vercel); company domain `attitudefactory.co`.

## 2. The application, as built

Production runs on a Hetzner VPS (`qualify-prod`) behind its own edge Caddy; deploys go through
GitHub Actions (`deploy.yml`), runbook in `README.md` and `docs/despliegue-hetzner.md`.

| Area (UI name) | Code | What it does |
|---|---|---|
| Auth / signup | `qualify_api.auth`, `Qualify/auth_*` | Supabase identity, tenant in `app_metadata`, invite codes |
| Cuentas conectadas | `qualify_api.connections` | Meta OAuth (Facebook Login for Business), FSM, encrypted credentials |
| Brand Kit | `qualify_api.creative.brand_*`, `Qualify/brand_*` | Logo, palette, typography, tone, avatar |
| Catálogo | `qualify_api.catalog` | Products + photos/clips normalized at upload |
| Crear pieza / generador | `qualify_api.creative`, `packages/creative`, `packages/render` | Angles proposed by Claude (ADR 32 «Motor de Ángulos»), images/video/voice via BytePlus (Seedream, Seedance, OmniHuman, Seed Speech), Remotion templates, Pixabay stock, Canva; pricing table versioned in `qualify_creative/pricing_data/` |
| Planificador | `qualify_api.planner`, `publishing` | Calendar + worker that publishes approved pieces to IG/FB |
| Interacciones | `qualify_api.inbox`, `intent`, `replies` | Comments on own media, commercial intent by Claude Haiku (golden set: `docs/intencion-comercial-medicion.md`) |
| Conversaciones | `qualify_api.conversations`, `followups` | Instagram Direct, assisted replies through an approved outbox |
| WhatsApp | `qualify_api.whatsapp` | Cloud API module (built 2026-10-14) |
| Referentes / Descubrir reels | `qualify_api.referentes`, `Qualify/reels_discovery.py` | Top reels of reference accounts via ScrapeCreators, filtered by Claude |
| Menciones, leads, growth, creators | `qualify_api.mentions`, `leads`, `growth`, `creators` | Earlier listening/CRM surfaces, partially wired |
| Meegle integration | `qualify_api.meegle`, `mail` | Onboarding engine, Resend invitation email |

- **Data:** one Postgres (ADR 31). Every tenant table has RLS (`tenant_id` +
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid`); DB access only through
  `qualify_shared.db.session` (`tenant_session` / `admin_session` / `credential_session`).
  Media in Cloudflare R2. **There is no ClickHouse and no Celery**: background work is CLI loop
  workers (`just calendar-worker`, `whatsapp-worker`, `conversations-worker`, `webhook-worker`).
- **AI vendors in use:** Anthropic Claude (copy, angles, intent, filters — Haiku for
  classification), BytePlus ModelArk (generation; the authorized presets cede data to BytePlus,
  so client data only through unauthorized custom endpoints), ScrapeCreators (reels), Langfuse
  (tracing + evals: `just eval-*`, `packages/api/evals/`). HeyGen is **obsolete** (2026-10-16).
- **Still unbuilt from the original plan:** the Zyte → queue → multimodal-cascade ingestion
  pipeline and the `ingestion`/`search`/`signals` schemas. `packages/models` (SigLIP, Qwen3-VL,
  whisper, robertuito) and `packages/scraper` exist as libraries/spikes, not as a running pipeline.
- **Next on the roadmap (as of the snapshot):** Meta ads from Qualify (ADR 38, epic
  `m-24828970`), piece retention (ADR 39), stock integration. Check Meegle for the live queue.

## 3. Decisions an agent must not undo

ADR log: `docs/arquitectura.md` §6, plus `docs/adr-NN-*.md` for the long ones (32, 34, 38, 39).

- **Buy commodity, build the differentiated core** — generation, reels data, sending infra are
  bought; the angle engine, intent, assisted replies and the CRM are ours.
- **Replies are assisted, never autonomous** (draft + human approval). Generation has double
  approval (pick the angle, approve the piece) before publishing.
- **TikTok scheduled publishing is blocked** (unaudited clients force private accounts).
- **Paid ads are now in scope** — ADR 38 lifted ADR 21's organic-first rule for Meta ads.
- **Provenance** on every derived signal (source id + model/prompt/pipeline version).
- **Tenant isolation:** RLS on every table; nothing persisted client-side without a `tenant_id`
  namespace; logout destroys the Reflex state.

## 4. House rules (details live in the named skills)

- **Delivery = a pull request, never a merge** — `qualify-pr`.
- **Environment, tests, workers that act for real** — `qualify-dev-env`. `uv` only; prefer
  `uv run --no-sync`; never `--all-tenants` locally.
- **Schema changes** — `qualify-migration` (RLS in the same revision, reversible, one owner).
- **Text a client will read** — `qualify-copy-es` (Spanish, no anglicisms, no slang).
- **Model/prompt changes and vendor tests** — `qualify-measure` (measure before shipping,
  document the same turn in `docs/modelos-generativos/`).
- **Anything touching production** — `qualify-prod-ops` (ask first; documented paths only).
- **Long tasks** — `durable-findings`: flush to disk as you go.
- **Why things are the way they are** (original vision, earned-media pipeline, phase map) —
  `qualify-history`.
- Code, identifiers and `CLAUDE.md` in English; `docs/` and `README.md` in Spanish. `ruff` clean,
  type hints on every signature, tests offline.
- Tools: the tracker is **Meegle** (Linear is retired); team chat is **Lark**; browser tasks go
  through Claude in Chrome (the founder's logged-in sessions).
