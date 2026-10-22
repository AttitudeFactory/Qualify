---
name: qualify-team-research
description: Research squad — the main thread leads, Qualify subagents investigate in parallel (market-analyst in one or more modes — oferta, vector, demanda — plus principal-architect and/or data-scientist-fde when the question needs them), then challenge each other's output; evidence firewall for hypothesis-tier sales rehearsals. Use when the founder types /qualify-team-research or asks for market, vendor, model or architecture research that informs a decision.
disable-model-invocation: true
argument-hint: "<research question and the decision it informs>"
---

# Research squad

Load `qualify-lead` and `qualify-context`, and read `docs/proceso-investigacion-oportunidades.md`.
$ARGUMENTS is the question. If empty, ask. Name the decision it informs (a client, an epic, an
ADR, a vendor choice) — research without one gets parked.

## 1. Who

- `market-analyst` — one instance per mode the question needs (`oferta` what exists today,
  `vector` where it is heading, `demanda` what buyers require). Most questions need one or two.
- `principal-architect` — buy-vs-build, vendor, schema or Meta-platform questions.
- `data-scientist-fde` — model, prompt or vendor-quality questions (measures on real data).

## 2. Investigate (parallel)

Spawn them in one message. Each brief: the question, the decision it informs, its deliverable
(a vendor table, theses, an eval) and its output file (ownership in `docs/equipo-agentes.md`),
"flush each section to disk as you finish it", and "return a summary with sources".

## 3. Challenge

Give each subagent the others' files once (`SendMessage`) and ask what is wrong, unsourced or
contradicted. Route conflicts on architecture to the architect.

## 4. Rules you enforce

- **Evidence:** market claims need URL + access date; model claims a model id verified live;
  architecture claims a file/doc reference. Unsourced → hypothesis.
- **Modes, not opinions:** if two instances write the same paragraph, the breakdown was wrong.
- **Firewall:** `demanda` output is hypothesis-tier; it goes in a separate section of your
  synthesis, never blended with sourced findings. A pain with no source is sent back.
- **Adjacency against disk:** "Qualify is close to this" is a claim about code — verify it.
- **Anti-flattery:** a session that only endorses the roadmap means the brief was leading.

## 5. Deliver

One PR with the session's docs (`qualify-pr`); never merge. Synthesis: per question, what the
evidence says, confidence and dissent; what it confirms and contradicts; decisions needing the
founder, listed apart from informational findings.
