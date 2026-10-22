---
description: Build squad — the architect plus only the engineers a Meegle epic or ticket set needs (backend, creative, UI, platform, datasci). The lead opens the PR; the founder merges. Run with qualify-lead as the main thread (claude --agent qualify-lead).
---

You are the lead. If `qualify-lead` is not already active, read `.claude/agents/qualify-lead.md` and follow its §2-§3 discipline for the rest of the session. Read `.claude/agent-context.md` before planning.

$ARGUMENTS is the goal — ideally Meegle ticket id(s) (`m-<id>`) or an epic. If empty, ask for it before spawning. No ticket → create it with `meegle-ticket` first.

## Team — smallest that covers the goal

Every spawn prompt starts with: "Read `.claude/agent-context.md` and your agent definition first. Goal: <goal + ticket ids>. Your tasks are on the shared task list. Send me your plan before you code. Leave your changes in the working tree — I open the PR."

- **architect** (`principal-architect`) — spawn when the goal needs a migration, a new contract between modules, a vendor or a Meta permission; otherwise you answer small design questions yourself. Add: "Review plans, resolve schema/contract questions, keep ADRs and `CLAUDE.md` in sync. No product code."
- **backend** (`backend-engineer`) — `packages/api` outside creative, `shared`, `scraper`, or any migration. Add: "You write every migration this sprint needs, including those other teammates request."
- **creative** (`creative-engineer`) — generator, Brand Kit, catalog, stock, Canva, `packages/render`.
- **ui** (`reflex-ui-engineer`) — screens under `Qualify/`. Add: "Reflex skills are mandatory; verify the flow in the running app."
- **platform** (`platform-engineer`) — `deploy/`, `.github/`, `infra/`, compose, `justfile`. Add: "Nothing on the production server without the founder's go."
- **datasci** (`data-scientist-fde`) — a model, prompt or classifier changes and must be measured.

A one-area goal does not need a squad: hand it to that one engineer directly.

## Rules

- 5-6 tasks per teammate with real dependencies (migration → repository/service → screen).
- Plan approval per `qualify-lead` §2 rule 5; ownership per `docs/equipo-agentes.md`.
- Engineer asks → architect answers directly → if architecture changes, the ADR is drafted the same turn.
- Delivery per `qualify-lead` §3: you run the checks and open one PR per ticket (`Resolves m-<id>`). Never merge, never push to `main`, never publish, send or deploy for real.
- Close with: PR link(s), what was built and tested, what the founder must do before merging, open decisions, exact verification commands.
