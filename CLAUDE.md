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

Guidance for Claude Code in this repository. **Kept short on purpose** (Anthropic recommends
<200 lines for an always-loaded file): procedures and history live in `qualify-*` skills under
`.claude/skills/`, which load only when relevant.

## What Qualify is

A production multi-tenant app (Attitude Factory) for small businesses in Colombia, Venezuela and
Uruguay: Brand Kit + catalog → AI-generated pieces with human approval → publishing to
Instagram/Facebook → comments, Instagram Direct and WhatsApp with assisted replies → soon Meta
ads. The original vision (social listening + GTM over TikTok/IG video) is the long-term direction
and is mostly unbuilt. **Load the `qualify-context` skill** for the business, the clients, the app
module by module, the signed decisions and the house rules.

> ⚠ **Read the filesystem, not docs, for what exists.** Docs (this file included) describe intent
> and drift; `ls`, `git log`, `gh pr list` and the code do not.

## How to work here

- **Always delegate code generation and log-heavy work to a subagent** (founder, 2026-10-22):
  writing code → the Qualify area agent on Opus; test runs, CI logs, builds, wide searches → a
  subagent that returns only the verdict. The main thread routes, decides and summarizes. Routing
  table and briefs: **`qualify-lead`** skill.
- **Subagents** (`.claude/agents/`, each preloads its `qualify-*` skills): `backend-engineer`,
  `creative-engineer`, `reflex-ui-engineer`, `platform-engineer`, `data-scientist-fde`,
  `principal-architect`, `market-analyst`, `product-owner`. Ownership map: `docs/equipo-agentes.md`.
- **Squads** are skills the founder triggers: `/qualify-team-dev`, `/qualify-team-po`,
  `/qualify-team-research`. Agent teams (experimental) are off.
- **Every change ships as a PR with its Meegle ticket; nobody but the founder merges**
  (`just merge <pr>`, CI green) — full procedure, CI table and Actions budget: **`qualify-pr`**.
  Tickets: `meegle-ticket`. Client onboarding: `meegle-altas`.

## Skills index (Qualify's own)

| Skill | Use it when |
|---|---|
| `qualify-context` | Any work or question about the product, clients, status |
| `qualify-lead` | Delegating, coordinating subagents, status briefs |
| `qualify-pr` | Opening a PR, CI failures, `.github/` |
| `qualify-dev-env` | `just` recipes, tests, venv/uv traps, running workers locally |
| `qualify-migration` | Any Alembic revision (RLS, numbering, reversibility) |
| `qualify-copy-es` | Any text a client reads |
| `qualify-measure` | Changing a prompt/model/vendor, building an eval, documenting a model test |
| `qualify-prod-ops` | Production, deploys, secrets, outages |
| `qualify-lark-admin` | Meegle work items and space config, Lark admin — via MCP, `meegle`/`lark-cli` or Chrome |
| `qualify-backlog` | Writing stories / planning an epic |
| `qualify-history` | Earned-media pipeline, roadmap phases, why a past decision was made |
| `qualify-team-dev` / `-po` / `-research` | The founder asks for a squad |

## Repo map

| Path | What |
|---|---|
| `Qualify/` | Reflex app (the screens clients use); design system in `Qualify/ui/`, rules in `docs/design-system.md` |
| `packages/api/` | `qualify_api` — the modular-monolith backend (connections, publishing, planner, inbox, intent, conversations, whatsapp, creative, catalog, auth, meegle…) |
| `packages/shared/` | The only sanctioned DB doors (`tenant_session`, `admin_session`, `credential_session`) + R2 |
| `packages/creative/`, `packages/render/` | Generation providers and pricing; the Remotion render service (the repo's one Node runtime) |
| `packages/models/`, `packages/scraper/` | Multimodal model wrappers and scrapers — libraries/spikes, not a running pipeline |
| `migrations/postgres/` | Alembic — the whole schema, with RLS |
| `deploy/`, `.github/`, `infra/` | Production on Hetzner, CI/CD |
| `docs/` | Spanish product/architecture docs; start at `docs/index.md`; ADRs in `docs/arquitectura.md` §6 + `docs/adr-*.md` |

## Commands (details and traps: `qualify-dev-env`)

```bash
just dev        # up + migrate + seed — the local stack from cold
just ci-lint    # ruff check + format --check, as CI
just ci-test    # offline tests + coverage, as CI
just test-db    # tests that need the compose Postgres/Redis
just merge <pr> # the merge gate — founder only
```

Workers (`*-tick`, `*-worker`) **publish or send for real**: locally always `--tenant <uuid>`.

## Hard rules

- **Tenant isolation:** every table has `tenant_id` + RLS with the
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` policy; DB access only through
  `qualify_shared.db.session`.
- **One Postgres** for transactional and analytical data (ADR 31); no new datastore, runtime or
  vendor without an options table and the founder's decision.
- **Provenance** on every derived row (source id + model/prompt/pipeline version);
  **idempotency** on every outbox, webhook and worker.
- **Assisted, never autonomous** for anything sent or published; no TikTok scheduled publishing.
- **Buy commodity, build the core.** Raw scrape payloads are kept so data can be re-parsed.

## Conventions

- **Language:** `docs/` and `README.md` in Spanish; `CLAUDE.md`, skills, agents and code in English;
  client-facing strings in Spanish per `qualify-copy-es`.
- **Commits:** Conventional Commits in English.
- **Code:** `ruff` (line-length 100, `E`/`F`/`I`/`UP`), type hints on every signature, tests
  offline (`-m "not integration"`).
- **Tooling:** always `uv`, never `pip`/`conda`; standalone CLIs via `uv tool install`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
