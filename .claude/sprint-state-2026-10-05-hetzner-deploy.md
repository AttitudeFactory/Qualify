# Sprint state 2026-10-05 — Hetzner VPS deploy (pipeline-engineer, worktree agent-a6b946f32687ac752)

Branch: feat/deploy-hetzner-vps (off origin/main 1c9c503).

## Verified findings (disk, 2026-10-05)
- Calendar worker is EMBEDDED in the Reflex backend by default (`Qualify/Qualify.py` lifespan,
  `qualify_api/planner/embedded.py`); `QUALIFY_CALENDAR_WORKER=off` disables it. Prod reflex
  service MUST set it off, else a deploy publishes for real.
- `Qualify/capabilities.py` imports `qualify_models.permission_capability` at top level; pure
  module, so container uses PYTHONPATH=packages/models/src (same trick as CI) w/o ml group.
- Reflex backend extra routes (api_transformer): `/avatar/{network}/{handle}`, `/r2media/{token}`.
  FastAPI app: `/api/*` and `/public/media/{token}` (Meta fetcher, unauthenticated) — both to api.
- Roles created by migrations 0001/0002 with dev passwords (app_dev/admin_dev/credential_dev);
  prod must ALTER ROLE after `alembic upgrade head`.
- `/api/connections/callback` returns JSON (no redirect back to UI) — open UX item for App Review.
- Reflex in lock: 0.9.12 (main venv has 0.9.7). Reflex config honours REFLEX_* env (api_url etc).
- `.gitignore` has `.env.*` -> `deploy/.env.prod.example` needs a `!` exception.

## Cross-agent findings (2026-10-05) — docs/plan-cicd-staging.md landed TODAY (d37ec73)
- It says the **CX22 no longer exists** (Hetzner repriced 2026-06-15); CX23 = 2 vCPU/4 GB successor,
  CX33 (4/8) recommended esp. with Remotion. Brief says CX22 -> doc uses CX23 (CX33 if render on).
- It plans GHCR images built in CI + forced-command ssh key; brief asks build-on-host from the Mac.
  Followed the brief; compose is image-tag keyed so a GHCR pull swap is small. Flag to lead.
- BUG in plan §5.7.4: `QUALIFY_PUBLIC_MEDIA_BASE_URL=https://.../public/media` would double the
  path — `config.PublicMediaSettings.public_media_url` appends `/public/media/{token}` itself.
  Correct value = bare origin. Recorded in docs/despliegue-hetzner.md; plan doc not mine to edit.
- Auth session lives ONLY in Reflex backend state (`AuthState._access_token`); a backend restart
  without persisted state logs everyone out -> mount a volume on /app/.states (disk state mgr).

## Machine trap (founder's Mac, 2026-10-05)
- `docker pull`/`docker build` HANG forever with zero output (also explains the 20h-old errored
  `packages/render` builds in `docker buildx history ls`). Cause: the `desktop` credential helper
  in ~/.docker/config.json. Container networking is fine. Workaround used (no change to the
  user's config): DOCKER_CONFIG=<dir with {} config.json + symlink cli-plugins> and
  DOCKER_HOST=unix:///Users/herwin/.docker/run/docker.sock — pulls then complete in seconds.

## Progress
- [x] Dockerfile + .dockerignore (written; first `--target app` build in progress 22:48, slow)
- [x] compose prod + Caddyfile (written, unverified)
- [x] env example (+ .gitignore `!deploy/.env.prod.example`)
- [x] deploy.sh / bootstrap / backup (shellcheck clean)
- [x] docs/despliegue-hetzner.md (+ prioridad doc status, justfile deploy* recipes)
- [x] local verification (project qualify-smoke, torn down with down -v): images build, migrations
  0001->0040 on empty DB, roles get prod passwords (dev ones rejected), /ping 200, /login 200,
  /drafts/x 200 (SPA fallback), callback 403, /public/media 404, /r2media 404, ws 101 + real
  browser redirect via on_load, calendar-worker profile ticks (0 tenants), backup+restore OK.
  Fix found: /app and /app/.web must be writable by the runtime user (Reflex writes a marker).
- [x] ruff clean (repo), offline pytest 2684 passed (main venv + PYTHONPATH; db suite not run: no compose PG on 5432); commit + PR
