# Repository Guidelines

Qualify is a multi-tenant marketing CRM (Reflex UI + FastAPI-backed modular monolith) built as a Python 3.12+ uv workspace. Cross-client roles and skills live in `.agents/skills/`; load `qualify-context` and the relevant workflow skill before nontrivial work. Claude Code retains its original `CLAUDE.md`, `.claude/agents/` and `.claude/skills/` unchanged. Docs in `docs/` are Spanish prose and describe intent — trust the filesystem and config over docs.

## Structure

- `Qualify/` — the Reflex app (client-facing screens); colocated UI tests are collected by root pytest.
- `packages/<name>/src/qualify_<name>/` — `api` (backend monolith + workers), `shared` (the **only** sanctioned DB doors: `tenant_session`, `admin_session`, `credential_session`, `webhook_session`, … + R2), `scraper`, `creative`, `models` (ML), `docs-harvester`.
- `packages/render/` — Node 22+/TypeScript Remotion service. **Excluded from the uv workspace** (no pyproject.toml); manage it with npm inside that directory only.
- `migrations/postgres/` — Alembic: whole schema, RLS policies and DB roles (roles are created by migrations, not compose).
- `tests/e2e/` — Playwright; never part of CI (`just e2e`, needs `just up` + installed Chromium).

## Commands

- `just dev` — docker compose up (Postgres 16, Redis 7, render) + `alembic upgrade head` + seed. `just down` **always drops the pgdata volume** (`down -v`).
- `uv sync` — default groups are backend + crm + dev; **torch/`ml` is deliberately excluded**. Use `uv sync --group ml` only for `packages/models` work, and run its tests with `uv run --no-sync pytest packages/models/tests`.
- `uv run reflex run` — launch the CRM. Reflex loads `.env` only because `rxconfig.py` sets `env_file=".env"`; production overrides config via `REFLEX_<FIELD>` env vars.
- `just ci-lint` then `just ci-test` — CI mirrors of the lint and offline-test steps; run both before pushing. `just lint` / `just fmt` modify files.
- `just test` — unit + db, offline; the db tests need the compose stack (`just up`). `just test-db` — only `db`-marked tests. `just test-fresh` — reset `qualify_test` first. Single test: `uv run pytest path/to/test_file.py::test_name`.
- `just merge <pr>` — the merge gate (GitHub Free has no branch protection): refuses unless required checks are green. `--admin` is a logged contingency only.
- Renderer: in `packages/render/`, `npm install`, `npm run typecheck`, `npm run bundle`; or `just render-dev` (Remotion Studio), `just render-smoke`.
- Always `uv`, never `pip`/`conda`. Many justfile recipes use `uv run --no-sync` on purpose — a stray `uv sync` with different groups can disrupt the shared `.venv`.

## Testing quirks

- Root `conftest.py` **aborts any pytest run** whose DSN doesn't point at a `*_test` database or whose Redis URL is db 0. Tests default to `qualify_test` + Redis 15, never the dev `qualify` database. Data left behind is kept for inspection; reset explicitly (`just test-db-reset` or `--reset-test-db`).
- Markers: `db` (needs compose Postgres/Redis), `integration` (external network/paid vendors — never in CI), `slow` (opt-in benchmarks). Default `addopts` excludes `integration` and `slow`.
- `testpaths` in `pyproject.toml` is an **audited allow-list**: `packages/shared/tests/test_gate_coverage.py` fails if any `packages/*/tests` dir is neither listed there nor in the justified deny-list (`[[tool.qualify.test-gate.excluded]]`). Adding a package means deciding its gate status explicitly.
- CI order in the `test` job: ruff check → ruff format --check → gitleaks (PR commits) → offline pytest with coverage → **migration reversibility gate** (`alembic upgrade head` → `downgrade base` → `upgrade head` must land clean) → `pytest -m db`. Any new migration must be fully reversible.
- An autouse fixture strips Langfuse keys — tests never export traces; a test needing tracing configures its own client.

## Danger: workers act for real

`just calendar-tick`, `whatsapp-tick`, `creative-tick`, `conversations-tick`, `webhook-tick` and their `*-worker` variants **publish, send and spend real money** (Meta posts, WhatsApp messages, BytePlus billed renders). Scope is mandatory: locally always `--tenant <uuid>`, never `--all-tenants`. Purge/backfill recipes are dry-run unless `--execute`. `just eval-*` experiments spend real Claude/BytePlus credits and are never part of CI.

## Conventions

- Ruff: line-length 100, rules `E`, `F`, `I`, `UP`; `extend-exclude` covers `.claude`, `.agents`, `docs` (agent infra and Spanish prose — don't lint-fix them). Pre-commit runs ruff through uv.
- Type hints on every signature; UI files follow `*_state.py`, `*_provider.py`, `*_vm.py`.
- Language: `docs/` and `README.md` in Spanish; code, commits and skills in English; client-facing strings in Spanish per the `qualify-copy-es` skill.
- Commits/PRs: Conventional Commits with the Meegle ticket, e.g. `feat(creative): add queue recovery (m-24852160)`; branch names, PR titles and `Resolves m-<number>` include the `m-<id>`.
- Hard rules (see CLAUDE.md): every table has `tenant_id` + RLS; DB access only through `qualify_shared.db` doors; provenance on derived rows; idempotency on every outbox/webhook/worker; one Postgres for everything (no new datastores/vendors without a founder decision).

## Environment & deploy

- `.env.example` is the config reference (copy to `.env`, gitignored). Without DSN vars, code defaults to localhost `qualify`. `QUALIFY_AUTH_FAKE=1` / `QUALIFY_SIGNUP_OPEN=1` are dev/test only.
- Production is a Hetzner VPS behind a shared edge Caddy: `just deploy <ssh-target> [ref]`, `just deploy-status`, `just deploy-logs`, `just env-push <target> KEY...` (copies secrets from local `.env` without printing them). Details: `docs/despliegue-hetzner.md` and the `qualify-prod-ops` skill.
- `graphify-out/` holds a knowledge graph of the repo; `graphify query "<question>"` answers codebase questions, `graphify update .` refreshes it after changes.

## Client capabilities

- Use a named native subagent when supported. Otherwise give a generic subagent the role's
  `SKILL.md` path and a self-contained brief. If delegation is unavailable, apply the role
  in the current thread and state that limitation; do not claim a separate review occurred.
- Inherit the active session's model, provider, tools and permissions. Claude model aliases
  apply only to Claude adapters. Tool names and plugin skills depend on the client; use
  available equivalents and disclose capabilities that prevent completing a task.
- Before changing Reflex code, load `reflex-docs`, `setup-python-env` and
  `reflex-process-management`. If missing, install with `npx skills add reflex-dev/agent-skills`
  or follow the Reflex installation instructions in `CLAUDE.md` before editing.

## How to work here

- **Delegate code generation and log-heavy work to a subagent when supported** (founder, 2026-10-22):
  writing code → the Qualify area role with the active session model; test runs, CI logs,
  builds, wide searches → a
  subagent that returns only the verdict. The main thread routes, decides and summarizes. Routing
  table and briefs: **`qualify-lead`** skill.
- **Roles** (cross-client instructions: `.agents/skills/<role>/SKILL.md`; Codex adapters in
  `.codex/agents/`; existing Claude definitions remain in `.claude/agents/`): `backend-engineer`,
  `creative-engineer`, `reflex-ui-engineer`, `platform-engineer`, `data-scientist-fde`,
  `principal-architect`, `market-analyst`, `product-owner`, `ux-designer` (UX only: client profile,
  research, mockups, and the mandatory local suggestions-only review before opening any PR that
  touches client-facing paths). Ownership map: `docs/equipo-agentes.md`.
- **Squads** are skills the founder triggers: `/qualify-team-dev`, `/qualify-team-po`,
  `/qualify-team-research`. Agent teams (experimental) are off.
- **Every change ships as a PR with its Meegle ticket; agents may merge it with `just merge <pr>`
  once CI is green** (`--admin` only as a production contingency) and deploy through the
  documented paths (founder, 2026-10-23) — full procedure, CI table and Actions budget:
  **`qualify-pr`**; what still needs the founder: **`qualify-prod-ops`**.
  Tickets: `meegle-ticket`. Client onboarding: `meegle-altas`.
