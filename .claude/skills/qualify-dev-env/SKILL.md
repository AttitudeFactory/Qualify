---
name: qualify-dev-env
description: Qualify's local development environment — every `just` recipe (dev stack, migrations, tests, workers that publish or send for real, evals, Langfuse, render), and the known traps of the shared uv venv (macOS hidden .pth files, sync alternation, missing jiwer, PYTHONPATH bypass, editing an applied migration). Use when setting up, running tests, when imports fail after a sync, or before running any worker or tick locally.
---

# Qualify — local environment and its traps

Run `just --list` for the live recipe list; the notes below are what the list does not say.

**Workers that act for real** (`calendar-tick`, `whatsapp-tick`, `conversations-tick` and their `*-worker` loops) publish or send through the real Meta/WhatsApp APIs. Locally always pass `--tenant <uuid>`, never `--all-tenants`: the dev database holds dozens of test tenants.

## Reference (moved from CLAUDE.md on 2026-10-22)

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
just ci-lint      # the lint steps of the CI `test` job (ruff check + format --check), no sync
just ci-test      # the offline-tests step of the CI `test` job: offline tests + coverage per package
just audit        # pip-audit over the lock + npm audit (packages/render) — informational
just down         # docker compose down -v — DROPS the pgdata volume
just calendar-tick --tenant <uuid>     # QUA-111: one Planificador tick — PUBLISHES FOR REAL
just calendar-worker --tenant <uuid>   # QUA-111: a tick every 60 s until Ctrl+C
just whatsapp-tick --tenant <uuid>     # WA-08: one pass of the WhatsApp outbox sender — SENDS FOR REAL
just whatsapp-worker --tenant <uuid>   # WA-08: a pass every 5 s until Ctrl+C (locally always --tenant)
just conversations-tick --tenant <uuid> [--sync]    # QUA-226: one pass of the DM outbox sender (+ Instagram poll) — SENDS FOR REAL unless QUALIFY_CONVERSATIONS_DM_CHANNEL=memory
just conversations-worker --tenant <uuid> [--sync]  # QUA-226: a pass every 5 s until Ctrl+C
just conversations-seed --tenant <uuid>             # QUA-226: sample DMs through the in-memory channel (needs QUALIFY_CONVERSATIONS_DM_CHANNEL=memory)
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
