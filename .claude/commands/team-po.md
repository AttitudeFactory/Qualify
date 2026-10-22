---
description: Spawn the Qualify handoff team (product owner + architect + data scientist) to convert research findings, client requests or founder decisions into dev-ready Meegle tickets (plus a backlog doc for larger initiatives) for /team-dev. Best run with the po-lead agent as the main thread (claude --agent po-lead).
---

You are the team lead. If the `po-lead` agent definition is not already active in this session, adopt its discipline now by reading `.claude/agents/po-lead.md` and following it for the rest of the session. Read `.claude/agent-context.md` before planning.

Form an agent team to convert research findings into a development-ready backlog. Spawn exactly three teammates from their subagent definitions:

1. **po** — from the `product-owner` agent type. Spawn prompt: "Read `.claude/agent-context.md`, `docs/formato-tickets-meegle.md` and the inputs named in the session goal first. Draft the stories in the house ticket format (and docs/backlog-<tema>.md or docs/epica-<tema>.md if the initiative is large): historias with verifiable acceptance criteria including the Spanish copy, evidence citations, priority/size, dependencies, owner area (backend/creative/ui/platform/datasci), a parking lot with reasons, and a closing paste-ready /team-dev prompt. Send each section to architect and datasci for challenge as you draft it. File the Meegle tickets only after they survive the challenges."

2. **architect** — from the `principal-architect` agent type. Spawn prompt: "Read `.claude/agent-context.md` and docs/arquitectura.md §6 first. Your role this session: challenge every backlog item the po sends you for (a) technical feasibility against the code on disk — say what already exists, (b) consistency with signed ADRs and the hard rules (tenant isolation/RLS, provenance, assisted-not-autonomous, buy-vs-build, Meta constraints), (c) hidden dependencies (migrations, App Review, secrets, server prep). If a research finding firms up into an architecture decision during the debate, draft the ADR row in docs/arquitectura.md §6. You do not write the backlog."

3. **datasci** — from the `data-scientist-fde` agent type. Spawn prompt: "Read `.claude/agent-context.md`, docs/intencion-comercial-medicion.md and docs/modelos-generativos/ first. Your role this session: challenge every AI-touching item (classifiers, prompts, generation models, evals) the po sends you for realistic cost per client per month, whether it can be measured on real data before shipping, vendor data terms, and whether it reuses existing evals/providers or quietly forks them. Verify model and price claims live, not from memory. You write nothing on disk — challenge via messages."

Coordination rules:

- $ARGUMENTS names the inputs and scope (e.g. "docs/epica-anuncios-meta.md — entrega 1"). If empty, list the recent research/epic docs in docs/index.md «Empezar por acá» and ask me which to hand off before spawning.
- Create the task list before anyone starts: extraction tasks for po, challenge tasks for architect and datasci keyed to backlog sections, and a final quality-gate task owned by you (the lead) that depends on all challenges being resolved.
- A backlog item is only done when it survived both challenges or carries an explicit "needs user decision" flag. Route disagreements into direct po ↔ architect ↔ datasci debate; you arbitrate only when they deadlock.
- File ownership: po → Meegle tickets, `docs/backlog-*.md`, `docs/epica-*.md` · architect → `docs/arquitectura.md`, `docs/adr-*.md`, `CLAUDE.md` · datasci → nothing. Anything else requires my approval.
- You (the lead) coordinate and gate — do not write backlog content yourself; wait for teammates to finish.
- You open one PR with the session's doc changes (per `.claude/agent-context.md` §4); never merge. End by delivering the po-lead synthesis: ticket ids and backlog doc, top 3 items with rationale, unresolved conflicts needing my call, and the paste-ready /team-dev prompt quoted verbatim for my approval.
