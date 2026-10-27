# Repository Guidelines

## Project Structure & Module Organization

Qualify is a production multi-tenant app (Reflex frontend + modular-monolith backend) on a Python 3.12+ `uv` workspace. The root `pyproject.toml` is virtual (`package = false`) and only owns the shared lock, venv, and dev tooling.

- `Qualify/` — Reflex app (client screens); design system in `Qualify/ui/` (rules: `docs/design-system.md`).
- `packages/<name>/src/qualify_<name>/` — `api` (backend features: connections, publishing, planner, inbox, conversations, whatsapp, creative, auth…), `shared` (the ONLY sanctioned DB doors — `tenant_session`, `admin_session`, `credential_session`, `webhook_session`, `webhook_worker_session` — plus R2 storage), `creative`, `scraper`, `models`.
- `packages/render/` — Node.js/Remotion render service; excluded from the uv workspace (no pyproject.toml).
- `migrations/postgres/` — Alembic, the whole schema with RLS (run as `qualify_owner`, see `migrations/postgres/env.py`).
- `deploy/`, `infra/`, `.github/` — Hetzner production deploy, Langfuse stack, CI/CD.
- `docs/` — Spanish product/architecture docs; start at `docs/index.md`; ADRs in `docs/arquitectura.md` §6 + `docs/adr-*.md`.
- `graphify-out/` — knowledge graph; prefer `graphify query "<question>"` over wide greps for architecture questions.

Deeper context lives in `CLAUDE.md` and the `qualify-*` skills (`.claude/skills/`): `qualify-context` (product), `qualify-dev-env` (commands/traps), `qualify-pr`, `qualify-migration`, `qualify-copy-es` (client-facing Spanish), `qualify-ux`.

## Build, Test, and Development Commands

Use `uv` (never pip/conda). The `justfile` requires Bash; on Windows, use a Bash-capable environment (Git Bash).

- `uv sync`: backend + crm + dev groups. The `ml` group (torch) is deliberately excluded — use `uv sync --group ml` only for `packages/models` work, and beware: alternating plain and `--group ml` syncs on the shared `.venv` is a known corruption source.
- `just dev`: docker compose up (`--wait`) → `alembic upgrade head` → seed. `just down -v` tears down including the pgdata volume.
- `uv run reflex run`: run the Reflex app locally.
- `just ci-lint` / `just fmt`: ruff check + format --check (as CI) / apply formatting.
- `just test`: unit + db tests, `-m "not integration"` — mirrors CI. Root `addopts` already excludes `integration` and `slow` from every pytest run.
- `just ci-test`: offline tests with per-package coverage, as CI. `integration` never runs in CI.
- `just test-db` / `just test-db-reset` / `just test-fresh`: db-marked tests / destructive reset of `qualify_test` only / reset + full pass.
- Single test: `uv run pytest packages/api/tests/test_x.py::test_y` (offline tests need no services; `db`-marked ones need `just up` first).
- `just merge <pr>`: the merge gate (GitHub Free has no branch protection — this script is the rule). Refuses unless required checks are green; `--admin` forces deliberately.
- `just render-dev` / `just render-build` / `just render-smoke`: Remotion Studio / render Docker image / e2e smoke against the running service.
- `just e2e`: Playwright tests in `tests/e2e` — never part of CI; needs compose Postgres and Chromium.

## Workers & Money-Spending Commands (gotcha)

- Worker recipes (`calendar-tick/worker`, `whatsapp-tick/worker`, `conversations-*`, `creative-tick/worker`, `webhook-*`) **publish or send for real**. Locally always scope with `--tenant <uuid>`; `--all-tenants` is production-only.
- Purge/backfill recipes are dry runs unless `--execute`.
- `just refresh-referentes`, `just classify-hashtags`, and every `just eval-*` recipe **spend real credits/money** (ScrapeCreators, Anthropic, BytePlus) — check `--dry-run` first; evals also need `just langfuse-up`.

## Coding Style & Naming Conventions

Four-space indentation, type hints on every signature, ruff line-length 100, rules `E`/`F`/`I`/`UP`. Ruff excludes `.claude/`, `.agents/`, and `docs/` (agent infra and Spanish prose with illustrative Python — linting them caused a week of false-red CI). `snake_case` modules/functions, `PascalCase` classes. Language split: code, commits, `CLAUDE.md`/`AGENTS.md` and skills in English; `docs/`, `README.md`, and all client-facing strings in Spanish (per `qualify-copy-es`). Keep heavy ML deps opt-in (`uv sync --group ml`).

## Testing Guidelines

pytest + pytest-asyncio (`asyncio_mode = "auto"`); files `test_*.py`, functions `test_*`. Tests live in package `tests/` dirs and alongside Reflex code in `Qualify/`. Markers: `integration` (external network/paid vendors — never CI), `db` (needs compose Postgres/Redis), `slow` (opt-in benchmarks).

- Every run is force-isolated to `qualify_test` + Redis db 15; the root `conftest.py` **aborts** if any DSN points at the dev `qualify` database. Data a run leaves behind is kept for inspection — reset explicitly with `--reset-test-db` / `just test-db-reset`.
- `testpaths` in `pyproject.toml` is an AUDITED allow-list: `packages/shared/tests/test_gate_coverage.py` fails if any `packages/*/tests` dir is neither listed there nor in the `[[tool.qualify.test-gate.excluded]]` deny-list. New package test dirs must be added to one or the other.
- `packages/models/tests` is excluded from the gate (needs the `ml` group); run it explicitly: `uv run --no-sync pytest packages/models/tests`.
- importlib import mode + no `__init__.py` under tests dirs — same-named test modules across packages are expected.
- CI publishes coverage reports; no numeric minimum is configured.

## Commit & Pull Request Guidelines

Before creating or publishing any pull request, always run the project's `ux-designer` agent and the `review-agent` skill on the final merge diff. Resolve confirmed code defects, rerun the affected checks, and record UX suggestions and any remaining limitations in the PR description. For changes without a client-facing impact, the UX agent must explicitly report that scope and whether it has any suggestions. Do not replace either review with a self-review or CI; report unavailable review capabilities explicitly.

Do not create or publish a pull request without the user's explicit authorization. Prepare changes locally and wait for authorization before pushing a branch for a PR or opening the PR. Preserve existing PRs unless the user explicitly asks to close or delete them.

Do not merge a pull request or enable auto-merge without the user's explicit authorization for that merge. Authorization to prepare, push, or open a PR does not authorize merging it, even when all checks pass. After authorization, use the repository's merge gate (`just merge <pr>`).

Before closing a pull request, whether by merging or closing without merge, update its linked Meegle ticket with the final scope, current workflow status, PR link, validation results, and remaining work or limitations. Read the ticket back to verify the update before closing the PR. Never mark undelivered work as completed; record the actual outcome. This requirement does not authorize closing or merging a PR without the user's explicit approval.

Follow Conventional Commits in English, such as `feat(creative): add queue monitoring (m-24852167)`. Link the Meegle ticket in each PR, describe behavior changes and validation, and include screenshots for UI changes. Require green applicable CI checks before merging; use `just merge <pr>`.

## Security & Configuration

Use `.env.example` as the configuration reference; never commit secrets (`.env` is local; `just env-push` copies keys to production without exposing values). Access databases ONLY through the `qualify_shared.db` session doors — every table has `tenant_id` + RLS with the `NULLIF(current_setting('app.tenant_id', true), '')::uuid` policy, and the doors set that GUC. Hard rules (from `CLAUDE.md`): one Postgres for transactional + analytical data (no new datastore/vendor without an options table and the founder's decision); provenance on every derived row; idempotency on every outbox/webhook/worker; assisted, never autonomous publishing.
