---
name: compass-skill-synthesis
description: COMPASS protocol — when an agent or squad detects a capability gap (no existing skill or specialist covers a recurring need), synthesize a new skill (SKILL.md + optional executable Python) and assign it to the best-qualified agent. Use when a task fails or stalls because "no skill covers this", when the same ad-hoc procedure gets re-derived across sessions, or when the second-brain routes a request that fits no specialist. Not for one-off tasks — synthesis requires expected reuse.
---

# COMPASS: Cooperative Multi-Agent Planning with Adaptive Skill Synthesis

Detect what's missing → synthesize it as an executable/instructable skill → hand it to the best-qualified teammate. This is the project's mechanism for growing the skill library deliberately instead of re-deriving procedures every session.

Grounding: adapted from Li, Zhao & Pajarinen, *Cooperative Multi-Agent Planning with Adaptive Skill Synthesis* (arXiv:2502.10148). The paper's core mechanisms map here as: skills = executable Python functions **with documentation**, retrieved semantically via that documentation (→ the SKILL.md frontmatter `description` is the retrieval index — write it as trigger conditions, it's what other agents match against); synthesis trigger = "task reasoning identifies inadequate skill alignment" (→ the gap signals below); and a closed-loop cycle of Perception → Task Reasoning → Actor → **Self-Reflection** (→ steps 1-6 plus the reflection step). COMPASS is training-free — no RL; improvement comes from library growth and reflection, which is exactly what this harness can do.

## When to trigger (gap detection)

Any of these is a COMPASS signal — the agent that notices it reports the gap to the session lead or `qualify-second-brain` instead of silently improvising:

1. A task requires a procedure that no installed skill (`.claude/skills/`) covers and no agent definition documents.
2. The same multi-step procedure has been improvised ad hoc in ≥2 sessions (check `.claude/compass-sage/ledger.md` for repeated `improvised` entries).
3. A specialist declines a task as out-of-scope and no other specialist's charter covers it.
4. A vendor/tool integration (Zyte, ClickHouse, HF, R2, outreach APIs) is being scripted inline instead of through a reusable interface.

## Synthesis procedure

1. **Specify the gap** in one paragraph: what capability is missing, which task(s) failed or stalled without it, and the expected reuse (which phases/squads will need it again). No expected reuse → stop, solve inline, log it as `improvised` in the ledger (see the SAGE skill) so repetition becomes detectable.
2. **Check for near-misses first**: an existing skill that almost covers it should be *extended* (edit its SKILL.md, or add a script to its directory) rather than duplicated. Read `.claude/skills/` and `docs/equipo-agentes.md` before creating anything.
3. **Synthesize the skill** at `.claude/skills/<kebab-name>/`:
   - `SKILL.md` with `name` + `description` frontmatter. The description must state the trigger conditions ("Use when…") — that is what makes the skill discoverable by other agents.
   - When the capability is procedural code (a parser probe, a cost calculator, a fixture generator), include executable Python under the skill directory (e.g. `scripts/<name>.py`), typed, runnable via `uv run`, with a usage example in the SKILL.md. Executable beats prose when the procedure is deterministic.
   - English, per project convention.
4. **Assign to the best-qualified agent** — the one whose file-ownership and charter (per `docs/equipo-agentes.md`) matches the skill's domain, not whoever discovered the gap. Add the skill to that agent's "Skills at your disposal" section in `.claude/agents/<agent>.md`, with a one-line "use when" note.
5. **Register**: add a row to the skills table in `docs/equipo-agentes.md`, and log a `synthesized` entry in `.claude/compass-sage/ledger.md` (skill name, gap it closes, assigned agent, date).
6. **Prove it once**: the assigned agent (not the synthesizer) runs the skill on the originating task. If it doesn't work in their hands, the synthesis isn't done — iterate before closing.
7. **Self-reflect** (the paper's closed-loop step): after the proving run, the assignee writes 2-3 sentences of verbal feedback — what the skill got right, what was ambiguous or wrong in its instructions, what a future user needs to know — into the ledger entry's note. The synthesizer folds that feedback into the SKILL.md before the synthesis is closed. A skill that ships without a reflection pass is a first draft, not a library entry.

## Bootstrapping (seeding the library from past demonstrations)

The paper bootstraps its skill library from expert demonstrations before live synthesis. Our equivalent: past sessions where a procedure was improvised successfully *are* the demonstrations. On request ("bootstrap skills", "COMPASS bootstrap") or when the ledger accumulates `improvised` entries: review them plus recent git history/session summaries, identify successfully-improvised procedures with expected reuse, and synthesize skills from those *proven* traces (steps 3-7 above) rather than waiting for the ≥2-repetition trigger. Skills distilled from a working trace start higher-quality than skills invented from a spec.

## Sharing rules

- The synthesizer and the assignee are usually different agents — COMPASS is cooperative. The synthesizer writes for the assignee's context (their charter, their conventions), not their own.
- A skill assigned to one specialist is still invocable by anyone; assignment means *ownership* (that agent maintains it and is the default executor), not exclusivity.
- New skills that encode an architectural decision (a schema helper, a queue convention) need `principal-architect` sign-off before assignment — synthesis must not become a side channel around ADRs.
- **Partial observability is the default** (each agent sees only its own context window — the paper's core constraint). Anything a teammate will need must travel explicitly: leads relay findings between teammates ("multi-hop"), spawn prompts carry self-contained briefs, and durable knowledge lands in `docs/`, skills, or the ledger — never assume another agent saw this session.
