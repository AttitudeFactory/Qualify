---
name: qualify-team-dev
description: Build squad for a Meegle epic or ticket set that crosses areas — the main thread leads, Qualify subagents (architect + only the engineers whose paths the goal touches) implement in parallel on Opus, the lead opens the PR. Use when the founder types /qualify-team-dev or asks to build something that spans backend, generator, UI, platform or evals.
disable-model-invocation: true
argument-hint: "<m-id(s) or epic, and the goal>"
---

# Build squad

Load `qualify-lead` and `qualify-context`. $ARGUMENTS is the goal — ideally Meegle ticket id(s)
or an epic. If empty, ask. No ticket → create it with `meegle-ticket` first.

**A goal that touches one area is not a squad:** hand it to that engineer directly.

## 1. Plan (main thread)

- Read the ticket and the code areas involved (or send `Explore` if it is wide).
- Break the goal into tasks per area with dependencies: migration → repository/service →
  screen; eval before a prompt swap.
- Decide who is needed: `principal-architect` only when there is a migration, a cross-module
  contract, a new vendor or a Meta permission; then only the engineers whose paths are touched.

## 2. Design gate (if the architect is involved)

Spawn `principal-architect` first with the tickets and your task breakdown: "Return the schema /
contracts / module boundaries the engineers must follow, any ADR needed, and risks. Do not write
product code." Its answer goes into every engineer's brief.

## 3. Build

Spawn the engineers **in one message** (parallel) when their paths are disjoint; in sequence
when one needs the other's output. Each brief (see `qualify-lead` §2) says: ticket, its tasks,
the architect's decisions, its paths only, "plan first, then implement; run `just ci-lint` and
the tests for your package; leave changes in the working tree; return files changed, tests run
and anything unresolved". Engineers preload their skills (`qualify-migration`,
`qualify-copy-es`, …) through their agent definition.

## 4. Review and deliver

- Read each diff; send problems back to the same subagent with `SendMessage`.
- Cross-area seams (a service and the screen that calls it): give one engineer the other's diff
  and ask it to find mismatches.
- Run `just ci-lint`, `just ci-test` (and `just test-db` if SQL changed) **through a subagent**
  that returns only the verdict and failing lines.
- Open the PR per `qualify-pr`; merge and deploy are the main thread's, per `qualify-pr` and
  `qualify-prod-ops`. Never publish or send for real.
- Synthesis: PR link(s), what was built and tested, what the founder must do before merging,
  open decisions, exact verification commands.
