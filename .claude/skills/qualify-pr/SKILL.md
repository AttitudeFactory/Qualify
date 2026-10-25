---
name: qualify-pr
description: How a change reaches main in Qualify — Meegle ticket first, branch `<type>/m-<id>-<slug>`, local CI checks, the PR title/description format, moving the ticket by hand, the `just merge` gate (agents merge through it with CI green; `--admin` is contingency only), what each GitHub Actions workflow does and the Actions-minutes budget. Use before opening any PR, when CI fails, when reading a run, or when touching .github/.
---

# Qualify — from change to pull request

## The procedure (every agent, every PR)

1. **Ticket first.** Find or create the Meegle ticket with the `meegle-ticket` skill (format: `docs/formato-tickets-meegle.md`). No ticket, no PR.
2. **Branch** `<type>/m-<id>-<slug>` off an up-to-date `origin/main` — the id must be right before the first push. Never commit or push to `main`.
3. **Conventional Commits in English**; end commit messages with the attribution line the session gives you.
4. **Checks before opening:** `just ci-lint`, `just ci-test`; `just test-db` (needs `just up`) if SQL changed; `just render-smoke` / `npm run typecheck` if `packages/render` changed.
5. **UX review — mandatory before `gh pr create` on any PR touching client-facing paths** (`Qualify/**`, `assets/**`, and client-string sources: message/reply/WhatsApp templates, invite and mail copy in `packages/api`): run the `ux-designer` subagent on the diff (local only — there is no UX job in GitHub Actions, founder 2026-10-23). **Always show its suggestions to the founder in the same turn**, and paste them into the PR description under a **«Sugerencias de UX»** section, each marked *aplicada* or *pendiente* with the reason. Suggestions only, never blocking; if it finds nothing, the section says «Sin sugerencias».
6. **Open the PR over REST** (`gh api repos/AttitudeFactory/Qualify/pulls …` — GraphQL is blocked in cloud sessions): title ends in `(m-<id>)`, description starts with `Resolves m-<id>`, says why, what and how to verify, and anything the founder must do before merging (secrets, server prep, auto-deploy off).
7. **Move the ticket to RESOLVED by hand** (`get_transitable_states` → `transition_state`); Meegle's completion rules do not fire yet.
8. **Merge through the gate (founder, 2026-10-23).** Agents may merge with `just merge <pr>` once CI is green, without asking — never with `gh pr merge` directly. (GitHub cannot approve one's own PR: `gh` runs as the founder, who authors the PRs, so "approve" means merging through the gate.) **Contingency only — never routine:** `just merge <pr> --admin` with red or missing checks is allowed when production is down or degraded and the PR is the fix, or when a red check is unrelated/flaky and blocks an urgent fix; state why in the PR (the recipe also posts a comment) and notify the founder right after. Deploying after the merge follows `qualify-prod-ops`.
9. In a squad, only the lead opens the PR; teammates leave changes in the tree.

## Reference (moved from CLAUDE.md on 2026-10-22)

### Merging to `main` — the rule and the gate

**Founder's rule (2026-10-05): nothing merges to `main` with CI red.** Since 2026-10-23 agents
hold merge authority through the gate, and the `--admin` bypass only under the contingency of
step 8. GitHub cannot enforce it on this plan (private
repo, organization on GitHub Free → branch protection and rulesets answer 403), so the
gate is `just merge <pr>`: it refuses unless `test` is green, and — **only when they reported** —
`docker-deploy`, `node-render` and `docker-render` too (they live in path-filtered workflows that
start no runner on PRs that do not touch their inputs); `just merge <pr> --admin` forces it and leaves a comment on the PR.
**Agents merge through `just merge`, never `gh pr merge` directly.** The recipe talks to GitHub over REST only (`gh api`): Claude Code cloud sessions have `gh` authenticated through an injected token but **GraphQL is blocked there**, so `gh pr view/checks/merge/comment` fail in the cloud while `gh api` works — keep any new gh tooling on REST. The ruleset to apply
the day the plan allows it is `infra/github/ruleset-main.json` (`just protect-main`).

### Every PR carries its Meegle ticket number

**Rule (2026-10-20): every PR names the Meegle ticket it delivers as `m-<work item id>`** — the
id is the number in the ticket URL (`…/issue/detail/24789646` → `m-24789646`; Cmd+Shift+C on the
ticket copies it). It goes in three places:

- **branch**: `<type>/m-<id>-<slug>` (`feat/m-24789646-dm-propuesto`);
- **PR title**, at the end: `feat(conversations): DM drafts from comment intents (m-24789646)`;
- **PR description**: `Resolves m-24789646` — the keyword is what lets the merge move the ticket.

Meegle is the only tracker (Linear is retired); no ticket → create or find one first, never open
the PR without it. **Create it with `/meegle-ticket`** (`.claude/skills/meegle-ticket/`, project skill:
every Claude Code session on this repo has it), in the format of `docs/formato-tickets-meegle.md`. Several tickets: `Resolves m-111, m-222`. Agents follow the same rule.

Why it matters: the Meegle **GitHub plugin** (Space configuration → Plug-ins → GitHub) receives
this repo's `pull_request`/`push` webhooks. `m-<id>` (or `f-<id>`, any case, anywhere in branch,
commit, title or description) **links** the PR to the ticket — it shows under the ticket's GitHub
tab. A completion rule is configured — **PR opened → `RESOLVED`** (review; planned rename «To Be
Reviewed») and **PR merged → `Done`**, the latter meant to be driven by `close|fix|resolve` (+ `-s`,
`-d`, `-ing`) followed by `m-<id>` — **but as of 2026-10-20 no completion rule moves anything**.
Measured on PRs #168, #169 and #170: the PR linked to the ticket and Meegle received every event
with 200, yet nothing moved — not Issues (rule on statuses; ticket in Backlog or In Progress; with
`m-<id>` or a bare number) and not Features (rule «PR merged → complete Backend Development» on the
node-driven Product Feature Request template, two test Features sitting in that node, with the
custom link pattern `[0-9]+` and again after setting it to `m-[0-9]+`; per-item «Upgrade Template»
changed nothing visible). Until Meegle fixes or explains it, **move the ticket by hand** (In
Progress → review → Done) when the PR opens and merges. The custom link pattern is now `m-[0-9]+`,
matching the documented syntax. Branch and commit links cannot be edited afterwards, so get the id right
before the first push. Reference: https://meegle.com/b/helpcenter/product/integration-github

The other direction is a GitHub **autolink** (repo Settings → Autolink references, id `18004011`):
every `m-<id>` in a PR title, description, comment or commit renders as a link to
`https://project.larksuite.com/5h2wsx/issue/detail/<id>`. It only resolves **Issues** (Features
live under `/story/detail/`), and GitHub offers autolinks on private repos only on paid plans, so
it may stop rendering once the org is back on GitHub Free (2026-11) — the Meegle side keeps working.


### CI (GitHub Actions, since 2026-10-05; minutes cut 2026-10-15)

Triggered by `pull_request` → `main` (never on drafts) and `workflow_dispatch`. **`ci` does not run on push to `main`**: the PR already passed the same gate and `just merge` refuses a red PR. Only `render` (when `packages/render/**` changes), `sonar` (opt-in) and `deploy` react to pushes to main. Older runs of the same PR are cancelled. **Budget: GitHub Free from 2026-11 = 2,000 Actions min/month, every job billed rounded up to the whole minute** (the org is on GitHub Enterprise, 50,000 min, until then). 2026-10-01..15 measured **4,294 billed min (~8,600/month) with 94 merges** — mostly short jobs paying a full minute each, CI repeated on main, Docker on every PR and a deploy per merge. Hence the shape below: **one** blocking job, Docker/Node/security only when their inputs change, Claude review on demand, and deploys switched from per-merge to daily (`QUALIFY_AUTO_DEPLOY=daily`) on **2026-11-12**. Every job has a timeout, uv/npm/Docker layers are cached, nothing uploads SARIF (needs Advanced Security). All actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`, weekly, grouped) bumps uv, npm (`packages/render`), actions and the render Dockerfile base image.

| Workflow / job | Runs | What | Blocks? |
|---|---|---|---|
| `ci` / `test` | every non-draft PR event (not on main) | ONE runner, ONE `uv sync`: `ruff check --output-format=github` (inline annotations) + `ruff format --check` → gitleaks over the PR's own commits → `pytest -m "not integration and not db and not slow"` + `--cov` per package (artifact, step summary, sticky PR comment via `.github/scripts/coverage_summary.py`) → Postgres 16 + Redis 7 service containers: `alembic upgrade head` → `downgrade base` (must leave no revision) → `upgrade head` → `pytest -m db` | **yes** (coverage % informs only; reversibility is a gate, ADR 27; gitleaks fails on a real secret) |
| `images` / `docker-deploy` | PR touching what the **build** depends on (`deploy/**`, `.dockerignore`, `pyproject.toml`/`uv.lock`/member manifests, `rxconfig.py`, `reflex.lock/**`) — **not** plain code PRs (`Qualify/**`, `packages/*/src/**`: `test` covers the code, and a build that breaks in `deploy` keeps the previous release live) and **not** on main | builds `deploy/Dockerfile` `web` + `app` (`push: false`, GHA cache), validates both Caddyfiles, then smoke: Reflex backend `/ping` 200 and Caddy serving `/`, `/login`, a dynamic route | **yes, when it ran** |
| `render` / `node-render` + `docker-render` | PR or main touching `packages/render/**` | `npm ci` + `npm run typecheck` (Node 22); `docker build` with `push: false` | **yes, when they ran** |
| `deploy` / `resolve` → `images` → `deploy` → `notify` | manual (`workflow_dispatch`), plus on its own per the repo variable `QUALIFY_AUTO_DEPLOY`: `merge` (or `true`) = every push to main; `daily` = 07:23 UTC, the tip of main only if GHCR has no image for it yet; anything else = manual only. Set to per-merge until **2026-11-12**, then `daily` | builds + pushes `ghcr.io/attitudefactory/qualify-{app,web,deploy}:<sha>` (arm64), ssh with a forced-command key that can only send `deploy <sha>` → `deploy/server-deploy.sh` (pull; migrate → up) + external smoke; `notify` posts a Lark card (outcome, commit/PR/author, trigger, stage durations, failed step) to Qualify-devs (`DEVOPS_WEBHOOK_URL`, optional `DEVOPS_WEBHOOK_SECRET`; `.github/scripts/deploy_notify.py`) | n/a (deploys, does not gate) |
| `security` / `sast`, `deps`, `repo` | weekly (Mon 06:17 UTC) on main, manual, and PRs touching dependencies, workflows, `deploy/**`, `infra/**`, Dockerfiles | semgrep + bandit (medium+); `pip-audit` over `uv export` (never `ml`) + `npm audit` high+; `trivy fs` + `gitleaks git` over the **full** history | trivy/semgrep/bandit/audits no (summary + artifact); **gitleaks yes** (redacted — rotate, then purge or allowlist in `.gitleaks.toml`) |
| `review` / `Claude auto-review` | **on demand only**: add the label `claude-review` to the PR (remove + re-add for another pass); `@claude` in a comment for anything else | review by Claude | no |
| `sonar` / `scan main` | push to main (code paths), only with the repo variable `SONAR_ENABLED=true` + secret `SONAR_TOKEN` | SonarQube Cloud (`sonarcloud.io`, ADR 40; free while the repo is public, where standard runners cost no minutes) | no |

Reproduce locally: `just ci-lint`, `just ci-test`, `just test-db` (needs `just up`), `just audit`. Reading a run: `gh run list --workflow ci --limit 5`, `gh run view <id>` (job list + durations), `gh run view <id> --log-failed` (only the failing steps), `gh run watch <id>`; scanner findings live in each run's **Summary** tab and in the `sast-reports` / `dependency-audits` / `repo-scans` artifacts. The `ml`/torch group is never installed in CI — `packages/models/tests` is not part of the gate (R11(b) above).
