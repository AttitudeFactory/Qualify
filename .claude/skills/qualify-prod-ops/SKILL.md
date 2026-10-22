---
name: qualify-prod-ops
description: Operating Qualify's production — the Hetzner VPS shared with Pedidos, the edge Caddy, how deploys happen (deploy.yml, QUALIFY_AUTO_DEPLOY, just deploy), rollbacks, secrets with just env-push, backups, logs, the remote qualify-prod Claude session, and what must be prepared before merging a change that needs the server. Use for any question or action about production, deploys, secrets or outages.
---

# Qualify — production operations

The runbook is `README.md` «Operación en producción» and `docs/despliegue-hetzner.md` — read the
relevant part before acting; this skill holds the rules around it.

## Rules

1. **Ask the founder before any action on production** — restart, rollback, `env-push`,
   `edge-install`, restoring a backup. Read-only is fine: `just deploy-status qualify-prod`,
   `just deploy-logs qualify-prod [service]`, `gh run list --workflow deploy`.
2. **Only the documented paths:** `deploy.yml` (auto per `QUALIFY_AUTO_DEPLOY`: `merge` until
   2026-11-12, then `daily`), `gh workflow run deploy -f ref=<40-char sha>`, `just deploy`,
   `just env-push`, `just edge-install`, and the remote session's rollback. Never `docker compose`
   or edit `.env.prod` by hand on the server.
3. **A change that needs the server first** (new env var, edge proxy, volume): say so in the PR;
   the founder turns auto-deploy off, prepares the server, deploys by hand, turns it back on.
4. **Rollback across a migration** needs `skip_migrate=true`; it only works while the migration
   was additive.
5. **Secrets:** never in git, arguments or the terminal. `just env-push qualify-prod --dry-run KEY`
   first; some keys are refused on purpose (README table). Check a vendor key works before
   pushing it (e.g. ScrapeCreators credit balance).
6. **The edge proxy is shared with Pedidos:** changes cut both for 1-2 s and ship with
   `just edge-install` from an up-to-date `main`.
7. **Actions minutes are a budget** (GitHub Free from 2026-11: 2,000 min/month, each job rounded
   up to a minute). A new job or trigger states its minute cost.
8. **Workers in production** run `--all-tenants`; locally they never do.

## In an outage

Status and logs first, then the last deploy (`gh run list --workflow deploy --limit 5`), then
propose — don't execute — the rollback to the founder. `engineering:incident-response` for the
write-up.
