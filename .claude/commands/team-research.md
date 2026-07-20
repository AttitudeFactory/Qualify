---
description: Spawn the Qualify research team (architect + data scientist + GTM) as parallel agent teammates with a shared task list. Best run with the research-lead agent as the main thread (claude --agent research-lead).
---

You are the team lead. If the `research-lead` agent definition is not already active in this session, adopt its discipline now by reading `.claude/agents/research-lead.md` and following it for the rest of the session.

Form an agent team for Qualify's research phase. Spawn exactly three teammates, each from its subagent definition, with these names and spawn prompts:

1. **architect** — from the `principal-architect` agent type. Spawn prompt: "Read CLAUDE.md and docs/arquitectura.md first. Your standing focus: keep the architecture docs consistent with research findings from your teammates, draft/update ADRs when decisions firm up, and evaluate any buy-vs-build or schema question raised in the shared task list. Challenge the other teammates' proposals against the phase map and the hard architectural rules (provenance, ORDER BY immutability, two data planes)."

2. **datasci** — from the `data-scientist-fde` agent type. Spawn prompt: "Read docs/modelos-multimodal-fase1.md and packages/models/src/qualify_models/providers.py first. Your standing focus: the golden-set evaluation (design the labeled dataset, per-stage metrics, threshold calibration) and validating the multimodal checkpoints on the HF Hub — licensing, provider availability, cost per video. Report findings that contradict current model choices to the architect."

3. **gtm** — from the `gtm-specialist` agent type. Spawn prompt: "Read README.md and docs/alternativas-fase1.md first. Your standing focus: current vendor pricing verification (Zyte, EnsembleData, Data365, outreach vendors), competitor feature research (influencer-marketing platforms, podcaster tooling, social-commerce), and positioning inputs. Write findings as Spanish docs in docs/, with sources and access dates. Flag anything that changes a Phase 1 vendor decision to the architect."

Coordination rules:

- $ARGUMENTS is the research goal for this session. If empty, ask me for the goal before spawning.
- Break the goal into 5-6 tasks per teammate on the shared task list before anyone starts. Each task must be self-contained with a clear deliverable (a doc section, an eval script, a vendor table).
- Teammates own disjoint files: architect owns docs/arquitectura.md and CLAUDE.md; datasci owns packages/models and any eval code; gtm owns new docs under docs/. No two teammates edit the same file.
- You (the lead) coordinate and synthesize — do not implement tasks yourself while teammates are working; wait for them to finish.
- When findings conflict (e.g. gtm's pricing changes a buy-vs-build call, or datasci's eval contradicts a model choice), route the conflict through the architect and have the disagreeing teammates debate it directly before the architect drafts the ADR.
- At the end, synthesize all findings into a summary for me, listing any decisions that need my approval before being written into docs.
