---
name: qualify-backlog
description: How Qualify turns evidence (client requests, founder decisions, research) into a prioritized backlog — stories with verifiable acceptance criteria and Spanish copy, evidence, priority/size, dependencies and owner area, filed as Meegle tickets (epic = Feature, story = Issue) plus a docs/backlog-*.md or docs/epica-*.md for large initiatives. Use when asked to plan an epic, write stories, groom or reprioritize the queue.
---

# Qualify — from evidence to backlog

Inputs: the founder's decision, a client's request (who, when), research docs
(`docs/index.md` «Empezar por acá», `docs/registro-validacion-features.md`). No evidence → the
item is labeled hypothesis. Format of every ticket: `docs/formato-tickets-meegle.md`; file them
with `meegle-ticket`.

## Every story has

1. **Historia** — «Como [dueño/a o equipo de un negocio concreto: el local de comida, la
   inmobiliaria, la agencia de viajes…], quiero…, para…». User value, not a task.
2. **Criterios de aceptación** verificables — including the exact Spanish copy the client will
   read (`qualify-copy-es`), tenant isolation, and `just ci-test` for code.
3. **Evidencia** — doc + section, client request, or founder decision.
4. **Prioridad** (P0-P3 per the format doc) **y tamaño** (S/M/L), **dependencias**, and the
   **owner area** (backend / creative / ui / platform / datasci).
5. **Fuera de alcance** — explicit.

A multi-PR initiative is a Feature `Épica — <tema>` with Issues linked through the Feature field;
past a handful of stories, also write `docs/backlog-<tema>.md` or `docs/epica-<tema>.md`
(Spanish) with the ticket ids.

## Rules

- **Signed decisions are constraints** (`qualify-context` §3): assisted replies, no TikTok
  scheduling, buy-vs-build. A story that contradicts one goes to the architect/founder first.
- **Real client value first:** prefer what unblocks a current client or the Meta App Review;
  park the rest with a reason.
- **Challenge before filing:** have `principal-architect` check feasibility against the code on
  disk and hidden dependencies (migrations, App Review, secrets, server prep), and
  `data-scientist-fde` check cost and measurability of AI items. File only what survived, or
  flag it "needs the founder".
- Close with a paste-ready prompt for `/qualify-team-dev` naming the owner of each item.
