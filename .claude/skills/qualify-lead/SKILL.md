---
name: qualify-lead
description: How the main thread leads work on Qualify — routing a request to the right Qualify subagent (backend, creative, reflex-ui, platform, datasci, architect, market-analyst) and model, the rule that code generation and log-heavy tasks ALWAYS go to a subagent, writing self-contained briefs, coordinating several subagents without implementing, delivering one PR, and the status brief. Use at the start of a session that will delegate, before spawning any Qualify subagent, and when asked "¿cómo va…?".
---

# Qualify — leading from the main thread

The main thread routes, decides and remembers; subagents do the heavy work and return a summary.
Load `qualify-context` first if it is not loaded.

## 1. The delegation rule (founder, 2026-10-22)

**Always send code generation, and any task that produces a lot of output (test runs, CI logs,
builds, wide searches), to a subagent** — on Opus 5.5 for writing code, or the best-fit model for
the task. The main thread keeps only conclusions.

| Work | Send to | Model |
|---|---|---|
| Backend code: `packages/api` (not creative), `shared`, `scraper`, migrations, workers | `backend-engineer` | opus |
| Generator, Brand Kit, catalog, stock, Canva, `packages/render` | `creative-engineer` | opus |
| Screens under `Qualify/`, design system, E2E | `reflex-ui-engineer` | opus |
| UX only: client profile, user research, flow mockups, critique of a screen or a PR's client-facing changes | `ux-designer` | opus |
| `deploy/`, `.github/`, `infra/`, compose, `justfile`, production questions | `platform-engineer` | opus |
| Evals, golden sets, model/vendor tests, `packages/models` | `data-scientist-fde` | opus |
| Architecture, schema design, ADRs, Meta constraints, docs↔code audit | `principal-architect` | opus |
| Market research (name the mode: oferta / vector / demanda) | `market-analyst` | sonnet |
| Run the test suite / read a CI run / read long logs — verdict only | `general-purpose` with `model: sonnet` (or `haiku` for plain log reading) | — |
| Find where something is across many files | `Explore` | — |

Small things stay in the main thread: answering from what is already loaded, a one-line config
or doc edit, reading one known file.

## 2. Writing the brief

The subagent sees nothing of this conversation. Every brief has: the goal and the Meegle ticket
(`m-<id>`); what is already known or ruled out; the files to start from; the scope boundary (what
not to touch); what to return (a summary under ~300 words, the files changed, the commands to
verify); and "leave changes in the working tree — the main thread opens the PR". Ask for the
verdict and the failing lines, never the full log.

## 3. Several subagents at once

- Launch independent ones in the same message so they run in parallel; give each a disjoint set
  of paths (ownership in `docs/equipo-agentes.md`). Two subagents never edit the same file.
- Dependent work runs in order (migration → service → screen); pass the previous result, or its
  file paths, in the next brief.
- Subagents cannot talk to each other. To make them challenge each other, give the second one
  the first one's output (or file) and ask it to find what is wrong. To continue a subagent,
  `SendMessage` to it instead of spawning a new one.
- **A rate-limited subagent is not dead.** Before respawning: `SendMessage` it, check the
  filesystem for its work, ask the founder if unsure. A monthly spend limit is not resumable —
  write `.claude/sprint-state-<date>-<topic>.md` and stop.
- Don't implement while subagents work; wait for them, then review their diff.
- Prefer the smallest setup: one subagent beats three. For large fan-outs the founder can
  explicitly ask for a workflow.

## 4. Delivery and synthesis

- You open the PR (`qualify-pr`): run the checks through a subagent, commit, open, move the
  ticket. Never merge, never deploy, publish or send for real.
- Synthesis, same shape every time: PR link(s); what was built or found and how to verify; what
  the founder must do before merging; decisions that need him; next.
- **Status brief** when asked: shipped (merged PRs/deploys), in flight (open PRs, Meegle in
  progress), blocked or waiting on the founder, next. Sources: `git log`, `gh pr list` (REST in
  the cloud), the Meegle queue (`meegle`).

## 5. Memory and the skill library

- A decision, blocker or client request not in `docs/`, an ADR or Meegle should not evaporate:
  file the ticket (`meegle-ticket`) or note it for its owner.
- When the business or app changes, update `qualify-context` (through a PR).
- `sage-skill-evolution`: log delegated-task outcomes in `.claude/compass-sage/ledger.md`;
  `compass-skill-synthesis` when a procedure is improvised twice — new procedures become
  `qualify-*` skills. Never "evolve" the protected invariants (CLAUDE.md hard rules, ownership,
  the PR/merge rule).
