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
8. **Workers in production** run `--all-tenants`; locally they never do. Local-model sentiment
   (robertuito, torch) is **off** unless `QUALIFY_SENTIMENT_ENABLED` is set (m-24854340): it
   peaks at ~904 MiB and OOM-killed `webhook-worker` (cap 320m). Do not turn it on in
   `.env.prod`; sentiment is moving to Claude Haiku. `webhook-worker` logs `sentiment=off` at start.
9. **Memory caps** (`mem_limit` = `memswap_limit` per service in
   `deploy/docker-compose.prod.yml`, m-24852229): a change that adds work to a worker loop is
   measured under its cap before it is turned on. `just mem-webhook-worker` (m-24852538,
   `deploy/measure/`) runs webhook-worker's real loop in the prod image against a throwaway
   Postgres on a network with no route out (fake vendors, never Meegle): idle, a webhook
   batch, one Alta prefill; `-- --sentiment` adds robertuito (~900 MiB: it does not fit any
   worker cap). Copy its shape for other workers.
10. **Health review every 4 h:** read-only (`deploy-status`, `deploy-logs`, the last deploy runs);
   anything wrong is alerted to the founder. No remediation without asking.

## In an outage

Status and logs first, then the last deploy (`gh run list --workflow deploy --limit 5`), then
propose — don't execute — the rollback to the founder. A forward fix may ship as a PR merged with
`just merge <pr> --admin` if its checks are red or missing (contingency rule in `qualify-pr`),
then deployed and verified with `just deploy-status`. `engineering:incident-response` for the
write-up.

## Generation queue operations (m-24852167)

`just creative-queue [--tenant <uuid>] [--json]` is read-only: lane/status counts,
actual occupied vendor slots, queue-wait p50/p95 over the last hour/day, top waiting
tenant ids, expired leases and daily concurrency p95 over the last seven days (UTC,
sampled at submission, the same definition as MEDIR). The team's admin role reads
queue metadata only; the creative-worker door reads slots. No new DB grants.

Creative-worker records a Redis beat after each successful claim round; the independent
calendar-worker checks it every minute. Redis also stores incident latches with SET NX:
one accepted webhook message while a condition remains active; recovery clears the latch
and a recurrence alerts again. Failed deliveries are retried. No client names, phones,
emails, prompts, raw vendor errors or webhook URLs enter the alerts. The channel reuses
`QUALIFY_SUPPORT_WEBHOOK_URL`; no new secret is required. Redis failure logs degradation
without stopping generation/publication; it prevents alerting/deduplication until recovery.
Redis persistence is the existing Redis volume/snapshot: losing it may repeat alerts.

- **Wait p95 >5 min (last hour):** inspect jobs/slots and vendor timings; consider the
  Phase 2 decision, never turn on paid priority by itself.
- **Daily simultaneous p95 ≥5 (any day in the rolling week):** prepare the BytePlus
  capacity request (m-24852172); no automatic account/capacity changes.
- **429 QuotaExceeded:** inspect the vendor/account quota. The job is deferred, not
  billed again. One incident until five minutes without another such response.
- **Final <24 h before its deadline, unfinished:** inspect its queued/submitted state
  and vendor task id; do not blindly resubmit an already billed task.
- **No beat >5 min:** inspect creative-worker status/logs, its queue-role credentials
  and the last deploy. The watchdog has a five-minute grace at first observation. Follow
  the normal deploy/restart authorization rules above; the alarm changes nothing itself.


### Uncertain paid submissions (m-24852166)

`creative.worker.submission_uncertain job_id=<internal id>` means the remote POST may
have been accepted but its id could not be checkpointed. This is not a retryable vendor
failure. The job stays queued with a future `not_before` and continues holding its slot
until the provider's maximum 48-hour lifetime. `just creative-queue --json` exposes that
occupied capacity, the queued count and expired slot leases; use the internal job id from
worker logs to reconcile through its tenant session. No prompt, credential or raw vendor
response is logged. Do not clear the eligibility fence or submit another paid task blindly.
If the id was checkpointed, normal recovery polls that same id immediately. The client
sees a review message with no retry action; the team must resolve the incident first.
