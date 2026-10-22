---
name: qualify-team-po
description: Handoff squad — turns research, client requests or founder decisions into challenged, dev-ready Meegle tickets and a paste-ready /qualify-team-dev prompt; the main thread drafts with qualify-backlog, the architect (and datasci for AI items) challenge as subagents. Use when the founder types /qualify-team-po or asks to plan an epic from a doc.
disable-model-invocation: true
argument-hint: "<input docs or decision, and the scope>"
---

# Handoff squad

Load `qualify-lead`, `qualify-context` and `qualify-backlog`. $ARGUMENTS names the inputs and
scope (e.g. "docs/epica-anuncios-meta.md — entrega 1"). If empty, list the recent docs in
`docs/index.md` «Empezar por acá» and ask which one.

1. **Draft** the stories in the main thread with `qualify-backlog` (this is writing, not code):
   historia, criteria with Spanish copy, evidence, priority/size, dependencies, owner area,
   parking lot. Write the draft to `docs/backlog-<tema>.md` or `docs/epica-<tema>.md`.
2. **Challenge in parallel** (one message):
   - `principal-architect`: "Read this draft file. For each item: what already exists on disk,
     consistency with signed ADRs and hard rules, hidden dependencies (migrations, App Review,
     secrets, server prep). Return per-item verdicts: ok / change / needs the founder. If a
     decision firms up, draft the ADR."
   - `data-scientist-fde`, only if items touch classifiers, prompts or generation models: "Per AI
     item: cost per client per month, whether it can be measured on real data before shipping,
     vendor data terms. Verify live. Return per-item verdicts; write nothing."
3. **Resolve:** apply the changes; where the two disagree, give each the other's verdict once and
   decide, or mark "needs the founder".
4. **File** the surviving items in Meegle (`meegle-ticket`; epic = Feature, stories = Issues).
5. **Deliver:** one PR with the doc changes (`qualify-pr`); never merge. Synthesis: ticket ids
   and doc, top 3 items with rationale, conflicts needing the founder, and the paste-ready
   `/qualify-team-dev` prompt quoted verbatim.
