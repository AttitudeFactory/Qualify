---
description: Spawn the Qualify development team for one Meegle epic or ticket set — the architect plus only the engineers the goal needs (backend, creative, UI, platform, datasci). The lead opens the PR; the founder merges. Best run with the dev-lead agent as the main thread (claude --agent dev-lead).
---

You are the team lead. If the `dev-lead` agent definition is not already active in this session, adopt its discipline now by reading `.claude/agents/dev-lead.md` and following it for the rest of the session. Read `.claude/agent-context.md` before planning.

$ARGUMENTS is the sprint goal — ideally Meegle ticket id(s) (`m-<id>`) or an epic. If empty, ask me for the goal and its tickets before spawning anything. If the goal has no ticket, create it with the `meegle-ticket` skill first.

## Team

Always spawn the **architect**; spawn an engineer **only if the goal touches its paths** (sessions die to spend limits — fewer teammates is safer). Every spawn prompt starts with: "Read `.claude/agent-context.md` and your agent definition first. The sprint goal is: <goal + ticket ids>. Your tasks are on the shared task list. Plan before you code and send the plan to the lead. Leave your changes in the working tree — the lead opens the PR."

1. **architect** — `principal-architect`. Add: "You review plans, resolve schema/contract/module-boundary questions the engineers raise, and keep `docs/arquitectura.md`, ADRs and `CLAUDE.md` in sync with what gets built. You do not write product code."
2. **backend** — `backend-engineer`, if the goal touches `packages/api` (outside creative), `packages/shared`, `packages/scraper` or needs a migration. Add: "You write every migration this sprint needs, including the ones other teammates request."
3. **creative** — `creative-engineer`, if it touches the generator, Brand Kit, catalog, stock, Canva or `packages/render`.
4. **ui** — `reflex-ui-engineer`, if it touches screens under `Qualify/`. Add: "Reflex skills are mandatory; verify the flow in the running app."
5. **platform** — `platform-engineer`, if it touches `deploy/`, `.github/`, `infra/`, compose files or the `justfile`. Add: "Nothing on the production server without my explicit go."
6. **datasci** — `data-scientist-fde`, if a model, prompt or classifier changes and needs measuring. Add: "Measure on real data, document the test in `docs/modelos-generativos/`."

## Coordination rules

- Break the goal into 5-6 self-contained tasks per teammate on the shared task list before anyone starts, with real dependencies (e.g. "migration" blocks "repository + service" blocks "screen").
- **Require plan approval** for every engineer. Approve only plans that: (1) test offline via `just ci-test`, (2) respect the ownership map, (3) keep RLS, idempotency, provenance and the price guard where they apply, (4) defer schema/contract decisions to the architect, (5) put user-facing strings in plain Spanish.
- **File ownership** — the map in `.claude/agents/dev-lead.md` rule 4. Anything outside it requires my approval: surface it, don't edit.
- You coordinate, review and synthesize — no implementing while teammates work; wait for them to finish.
- Decisions flow: engineer asks → architect answers directly → if it changes documented architecture, the architect drafts the ADR in the same turn.
- **Delivery:** when all tasks pass, you run `just ci-lint`, `just ci-test` (and `just test-db` if SQL changed), then commit on `<type>/m-<id>-<slug>` and open the PR per `.claude/agent-context.md` §4 (`Resolves m-<id>`). Never merge, never push to `main`, never run anything that publishes, sends or deploys for real.
- At the end, give me: the PR link(s), what was built and tested, what I must do before merging (secrets, server prep, auto-deploy off), open decisions, and the exact verification commands.
