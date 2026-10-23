---
name: qualify-prod-ops
description: Operating Qualify's production — the Hetzner VPS shared with Pedidos, the edge Caddy, how deploys happen (deploy.yml, QUALIFY_AUTO_DEPLOY, just deploy), rollbacks, secrets with just env-push, backups, logs, the remote qualify-prod Claude session, and what must be prepared before merging a change that needs the server. Use for any question or action about production, deploys, secrets or outages.
---

# Qualify — production operations

The runbook is `README.md` «Operación en producción» and `docs/despliegue-hetzner.md` — read the
relevant part before acting; this skill holds the rules around it.

## Rules

1. **Deploys are delegated (founder, 2026-10-23).** Agents may deploy without asking, only
   through the documented paths (`deploy.yml` / `gh workflow run deploy`, `just deploy`), and
   must verify with `just deploy-status qualify-prod` right after; a failed deploy is reported to
   the founder. **Still ask the founder first:** `just down` (drops the volume), restoring a
   backup, a rollback, `env-push` of a new key, `edge-install` (cuts Pedidos 1-2 s), and any
   restart outside a deploy. Read-only is always fine: `just deploy-status qualify-prod`,
   `just deploy-logs qualify-prod [service]`, `gh run list --workflow deploy`.
2. **Only the documented paths:** `deploy.yml` (auto per `QUALIFY_AUTO_DEPLOY`: `merge` until
   2026-11-12, then `daily`), `gh workflow run deploy -f ref=<40-char sha>`, `just deploy`,
   `just env-push`, `just edge-install`, and the remote session's rollback. Never `docker compose`
   or edit `.env.prod` by hand on the server.
3. **A change that needs the server first** (new env var, edge proxy, volume): announce it to
   the founder and say so in the PR; auto-deploy goes off, the server is prepared, the deploy is
   run by hand, auto-deploy goes back on. Once announced, the agent may execute those steps
   (the ask-first items of rule 1 still need the founder's yes).
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
9. **Health review every 4 h:** read-only (`deploy-status`, `deploy-logs`, the last deploy runs);
   anything wrong is alerted to the founder. No remediation without asking.

## In an outage

Status and logs first, then the last deploy (`gh run list --workflow deploy --limit 5`), then
propose — don't execute — the rollback to the founder. A forward fix may ship as a PR merged with
`just merge <pr> --admin` if its checks are red or missing (contingency rule in `qualify-pr`),
then deployed and verified with `just deploy-status`. `engineering:incident-response` for the
write-up.
