# Qualify production server — operating notes for Claude

Installed as `/opt/qualify/CLAUDE.md` by `just claude-bootstrap` (source:
`deploy/claude-server.md` in the repo; edit it there, not here). Full runbook, in Spanish:
`docs/despliegue-hetzner.md`.

You are running **on the production server** of `https://qualify.attitudefactory.co`, as the
`deploy` user. `deploy` is in the `docker` group: you effectively have root, and real customer
data lives here. Act like an on-call engineer, not like a developer on a laptop.

## Ground rules

- **Read-only first.** Look before you change: `qdc ps`, `qdc logs --tail=200 <svc>`, health checks.
- **Ask before anything that changes the running system**: deploy, rollback, restart, `up`,
  `run`, `exec` that writes, editing files under `/opt/qualify`. Say what you will run and why.
- **Never** run `docker compose down -v`, `docker volume rm/prune`, `docker system prune`, or
  anything that drops a database or the `pgdata` volume. There is no undo.
- **Never read, print or edit `/opt/qualify/.env.prod`.** Everything you read goes into this
  conversation. Secrets change from the founder's Mac with `just env-push` (§7 of the runbook).
- **Never add `ports:` to `postgres` or `redis`.** Docker's iptables bypass `ufw`; only Caddy
  is published, and that is the only reason the firewall holds.
- **Never build on this server.** Images come from GHCR, built by GitHub Actions.
- The optional `calendar-worker` profile **publishes for real** to customers' social accounts.
  Do not start it, and do not change `COMPOSE_PROFILES`, without an explicit request.
- Report outcomes faithfully: if a health check fails, say so with the output.

## Layout

```
/opt/qualify/
├── .env.prod              secrets (off limits, see above)
├── current -> releases/<sha>   the live release; deploy/release.env names its images
├── releases/<sha>/        last 5 releases (compose file + scripts from qualify-deploy:<sha>)
├── backups/               nightly pg_dump at 03:15 UTC (backup.log)
└── bin/server-deploy.sh   the fixed deploy script (also the CI deploy key's forced command)
```

Services (`qdc config --services`): `caddy` (only thing on 80/443), `api` (FastAPI), `reflex`
(Reflex backend + websocket), `postgres` (pgvector/pg16), `redis`, `webhook-worker` (QUA-147:
settles recorded Meta webhooks, read-only toward Meta, never publishes), `migrate` (one-shot), and
the optional profiles `calendar-worker` and `render`.

## Commands

`qdc` is `docker compose` bound to the live release and its env files — always use it instead
of a bare `docker compose` (without `release.env`, Compose would look for `:latest` and build).

| Task | Command |
|---|---|
| Containers | `qdc ps` |
| Logs | `qdc logs --tail=200 <svc>` (no `-f`: it never returns) |
| Which commit is live | `cat /opt/qualify/current/deploy/release.env` |
| Health | `curl -fsS -o /dev/null -w '%{http_code}\n' https://qualify.attitudefactory.co/ping` (also `/`, `/login`) |
| Restart one service | `qdc restart <svc>` (ask first) |
| Deploy a commit | `/opt/qualify/bin/server-deploy.sh deploy <40-hex sha>` (ask first) |
| Roll back | `/opt/qualify/bin/server-deploy.sh rollback <40-hex sha>` — same without `migrate` (ask first) |
| Backup now | `/opt/qualify/current/deploy/backup-db.sh` |
| psql (read-only queries) | `qdc exec -T postgres psql -U qualify_owner qualify -c '<SELECT …>'` |
| Resources | `docker stats --no-stream`, `df -h`, `free -h` |

About deploys:

- `server-deploy.sh` only deploys a sha whose images **already exist in GHCR**
  (`ghcr.io/attitudefactory/qualify-{app,web,deploy}:<sha>`), i.e. commits the `deploy`
  workflow built. A brand-new commit of `main` is deployed by that workflow, not from here;
  this session is for status, diagnosis, restarts, rollbacks and backups.
- One deploy at a time: the script takes a lock and refuses a second run.
- **Rolling back across a migration** must use `rollback` (it skips `migrate`): the older image
  does not know the newer Alembic revision. It is only safe because migrations are
  expand → contract. If in doubt, stop and ask.
- If health checks fail after `up`, the new release is already live and `current` points at it.
  Recover by rolling back to the previous sha (the previous `releases/` entry).
- The script refuses when `COMPOSE_PROFILES` includes `render` (its image is not published
  yet); that case is deployed from the founder's Mac with `just deploy`.
