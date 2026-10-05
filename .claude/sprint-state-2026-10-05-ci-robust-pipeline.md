# Sprint state — `ci/robust-pipeline` (DevOps, 2026-10-05)

Agent: ci-engineer (pipeline-engineer role, DevOps hat). Branch `ci/robust-pipeline` from
`origin/main` @ `86382cd`. Flushed per section (durable-findings Rule 1).

## Verified facts (disk / GitHub, not belief)

- Existing `.github/workflows/ci.yml`: single `test` job, `push: ["**"]` + `pull_request`,
  `uv sync` (unlocked), ruff, `alembic upgrade head`, `pytest -m "not integration"`.
  Last main run: 1m12s for the whole job (37338436707).
- `packages/render/` on main holds only `CONTRACT.md`. PR #65 (`feat/motor-plantillas-remotion`)
  adds `package.json` (scripts: `typecheck` = `tsc --noEmit`, engines node>=22), `package-lock.json`,
  `Dockerfile` (node:22-bookworm-slim, `npm ci --omit=dev`, `npx remotion browser ensure`,
  `remotion bundle`) and adds a `render` service to `docker-compose.yml`.
- Root `conftest.py` + `testing/testdb.py`: when `db` tests are selected, `ensure()` creates
  `qualify_test` and runs `alembic upgrade head` itself; DSNs default to `*_test` targets.
  All DSN vars: `QUALIFY_APP_DSN`, `QUALIFY_ADMIN_DSN`, `QUALIFY_CREDENTIAL_DSN`,
  `QUALIFY_MIGRATION_DSN`, `QUALIFY_REDIS_URL`.
- `pyproject.toml`: `addopts` already excludes `integration` and `slow`; default groups
  `backend`, `crm`, `dev`; `ml` excluded. ruff excludes `.claude`, `.agents`, `docs` only, so
  `.github/scripts/*.py` IS linted.
- `uv lock` (no sync, no venv) added `pytest-cov 7.1.0` + `coverage 7.16.2` to `uv.lock`
  as pure additions (115 lines, nothing else re-resolved). Safe for `uv sync --locked` in CI.
- Action pins resolved 2026-10-05 via `gh api` (tag -> commit SHA):
  checkout v7.0.1 3d3c42e5aac5ba805825da76410c181273ba90b1 · setup-uv v10.2.0
  c18668ad3cf93ea998bef934396af7bb5c839dc7 · setup-node v7.0.0
  820762786026740c76f36085b0efc47a31fe5020 · upload-artifact v7.0.1
  043fb46d1a93c77aae656e7c1c64a875d1fc6a0a · setup-buildx-action v4.4.1
  f87e5991a6d7451dcb8d9637bfbc97413f497069 · build-push-action v7.4.0
  c3c9e263c25d99ce0380d002d59b67737d91b0dc · paths-filter v4.0.3
  ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d · trivy-action v0.36.0
  ed142fd0673e97e23eac54620cfb913e5ce36c25 · gitleaks v8.30.1 · semgrep 1.179.0 ·
  bandit 1.9.4 · pip-audit 2.10.1.

## Findings that change other agents' assumptions

- **`pytest -m "not db"` needed Postgres anyway** (first `ci` run, job `test`, 37340016521):
  root `conftest.py::pytest_collection_modifyitems` computed `needs_db` over the full
  collection because pytest's own `-m` deselection is a later-running built-in hook.
  Fixed with `@pytest.hookimpl(trylast=True)` on that hook in `conftest.py`. Anyone running
  the offline suite on a machine without Docker was hitting this silently (locally Postgres
  is always up, which is why nobody noticed).
- `test-db` (upgrade -> downgrade base -> upgrade -> `pytest -m db`) passed first time: 1m04s.

- **`Qualify/test_referentes_review.py::test_the_manual_pseudo_phase_is_never_recomputed`
  reached the real Postgres without a `db` marker** (second `ci` run, 2581 passed / 1 failed):
  it called `monkeypatch.undo()`, which also undid the `repo` fixture's `rp.REPOSITORY`
  patch, so `plan_refresh` went through the SQL repository. Fixed with a nested
  `pytest.MonkeyPatch.context()`. Locally invisible because Postgres is always up.
- **gitleaks full-history scan: 334 hits, zero real credentials** (classified by rule/path,
  values never printed): 321 = content hashes in `graphify-out/cache/stat-index.json`;
  6 = Meta CDN nonces in `packages/docs-harvester/tests/fixtures/*.html`; 2 = fixture ids in
  `packages/scraper/tests`; 3 = vendored docs (`reference/`, `.agents/`); 1 = the documented
  dev-only Fernet default in `connections/crypto.py:22`; 1 = an e2e persona password in
  `tests/e2e/personas.py:62` (commit 8cc309d9, file since deleted). Paths allowlisted in
  `.gitleaks.toml`, the two code hits pinned by fingerprint in `.gitleaksignore`. The
  founder should confirm the e2e persona password never guarded a real account.
- semgrep p/ci flags `${{ }}` expressions inside `run:` scripts as parse errors; summaries
  now pass step outcomes through `env:` (also the script-injection-safe pattern).

## Decisions taken (and why)

- Coverage comment: `py-cov-action/python-coverage-comment-action` needs `contents: write`
  (stores badge data on a branch). Rejected for least-privilege; instead
  `.github/scripts/coverage_summary.py` parses `coverage.xml` -> per-package table into
  `$GITHUB_STEP_SUMMARY` and a sticky PR comment via `gh api` (`pull-requests: write` only).
- No SARIF upload anywhere (private repo without Advanced Security).
- gitleaks via docker image (`ghcr.io/gitleaks/gitleaks`), not the Action (org license).

## Progress log

- [x] Branch created, context read, versions resolved.
- [x] `pyproject.toml` + `uv.lock` (pytest-cov).
- [x] ci.yml (changes/lint/test/test-db/node-render/docker-render), `.github/scripts/coverage_summary.py`
- [x] security.yml (sast/deps/repo)
- [x] dependabot.yml, PR template, CODEOWNERS, .gitignore (coverage outputs)
- [x] justfile (`ci-lint`, `ci-test`, `audit`) + CLAUDE.md "### CI" section
- [ ] push, PR, green runs (local validation: YAML parses, ruff clean; `just` not installed
      locally so recipes are unverified until someone runs them)
