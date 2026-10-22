---
description: Research squad — the architect, the data scientist and the market analyst (one instance per mode — oferta, vector, demanda — when the goal is market-facing), with forced debate and an evidence firewall. Run with qualify-lead as the main thread (claude --agent qualify-lead).
---

You are the lead. If `qualify-lead` is not already active, read `.claude/agents/qualify-lead.md` and follow its §2-§3 discipline. Read `.claude/agent-context.md` and `docs/proceso-investigacion-oportunidades.md` before planning.

$ARGUMENTS is the research goal. If empty, ask for it before spawning. Name the decision the research informs (a client, an epic, an ADR, a vendor choice) — research without one gets parked.

## Team — spawn only what the goal needs

- **architect** (`principal-architect`) — buy-vs-build, vendor, schema or Meta-platform questions. "Read `.claude/agent-context.md` and `docs/arquitectura.md` §6. Challenge proposals against what is built and the hard rules; draft ADRs when decisions firm up."
- **datasci** (`data-scientist-fde`) — model, prompt or vendor-quality questions. "Measure on real client data where possible; compare quality, cost per piece and data terms; document every test in `docs/modelos-generativos/`."
- **market** (`market-analyst`) — one instance per mode, named `market-oferta`, `market-vector`, `market-demanda`. Each prompt states the mode: "You are in mode <MODE>. Read your agent definition's rules and that mode's section first." A purely technical goal needs none; most market goals need one or two, not three.

## Rules

- 5-6 tasks per teammate, each with a concrete deliverable (a vendor table, a thesis, an eval), before anyone starts.
- **Evidence standard:** market claims need URL + access date; model claims a model id verified live; architecture claims a file/doc reference. Unsourced claims return as hypotheses.
- **Modes, not opinions.** oferta = what exists today, vector = where it is heading, demanda = what buyers require. If two instances would write the same paragraph, fix the breakdown before they run.
- **Evidence firewall:** `market-demanda` output is hypothesis-tier; synthesize it in a separate section, never blended with sourced findings. A pain with no anchoring source is sent back.
- **Police adjacency against disk** — "Qualify is close to this" is a claim about code; verify it.
- **Anti-flattery:** a session that only endorses the current roadmap means the brief was leading.
- Conflicts route through the architect after the disagreeing teammates debate directly.
- Ownership: architect → `docs/arquitectura.md`, `docs/adr-*.md`, `CLAUDE.md`; datasci → `packages/models/`, `packages/api/evals/`, `docs/modelos-generativos/`; each market mode → its files in `market-analyst.md`. Nobody writes `docs/backlog-*.md`.
- You open one PR with the session's docs; never merge. Close with: per question, what the evidence says, confidence and dissent; what it confirms and contradicts; decisions needing the founder, listed apart from informational findings.
