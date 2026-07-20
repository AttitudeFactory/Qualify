---
name: sage-skill-evolution
description: SAGE protocol — outcome-driven improvement of the agent/skill library. Log task outcomes per agent+skill to .claude/compass-sage/ledger.md; when an agent fails repeatedly at a subtask (≥2 failures with the same skill set), rebalance the load to a better-fit agent or rewrite the failing SKILL.md/agent definition. Use at end of squad sessions (log outcomes), when a task has failed twice (trigger evolution), or when asked to audit which skills/agents underperform.
---

# SAGE: Self-Improving Agents with Skill Libraries

The library of agents and skills is not static — it evolves against evidence. SAGE is the project's substitute for RL fine-tuning (GRPO-style reward optimization is not available at the harness level): instead of gradient updates, we do **outcome logging → failure-threshold triggers → load rebalancing or SKILL.md rewrites**, which optimizes the same objective (per-subtask success ratio) through the artifacts we *can* modify — skill instructions, agent charters, and task routing.

## The ledger (reward signal)

`.claude/compass-sage/ledger.md` is the shared outcome record. One line per entry, append-only, newest last:

```
| date | agent | skill(s) used | task (short) | outcome | note |
```

- `outcome` ∈ `success` · `partial` · `failure` · `improvised` (no skill covered it — COMPASS signal).
- **Who logs**: each squad lead logs their teammates' outcomes at end-of-session synthesis; `qualify-second-brain` logs outcomes of directly-delegated tasks; any agent may log its own `failure`/`improvised` immediately.
- Log *task-level* outcomes, not keystroke-level. A sprint task = one entry. Keep notes to one clause — why it failed, not a narrative.
- Honest negatives are the point: a ledger of only successes teaches nothing. `partial` and `failure` entries are more valuable than `success` ones.

## Evolution triggers (the policy-update rule)

Check the ledger before assigning work. Act when a pattern crosses a threshold:

| Pattern in ledger | Action |
|---|---|
| Same agent fails the same subtask type **≥2×** with its current skill set | **Rebalance first**: reassign the task type to a better-fit agent (update routing guidance in `qualify-second-brain.md` and/or the squad command). Rebalancing is cheaper and more reversible than rewriting. |
| Task type fails **≥2× across different agents** using the same skill | The skill itself is the problem: **rewrite its SKILL.md** — sharpen trigger conditions, fix wrong steps, add the failure case explicitly, or add executable code where prose was ambiguous. Log a `skill-rewrite` entry citing the failures that motivated it. |
| `improvised` appears **≥2×** for the same procedure | Escalate to COMPASS (`compass-skill-synthesis`): synthesize the missing skill. |
| An assigned skill goes **unused** across ≥3 sessions of its owner working in-domain | The description's trigger conditions aren't firing — rewrite the frontmatter `description` (that's what agents match against), or unassign it and note why in `docs/equipo-agentes.md`. |
| An agent's charter repeatedly forces it to decline in-domain-looking work | Rewrite the agent's `.claude/agents/<name>.md` scope section — charters are macro-instructions and are as rewritable as SKILL.md files. |

## Rewrite discipline

1. **Evidence first**: every rewrite cites the ledger entries (dates) that motivated it, in the commit/summary and in a `skill-rewrite` ledger entry. No vibes-based rewrites.
2. **One variable at a time**: rebalance OR rewrite, not both at once — otherwise the next outcomes can't be attributed.
3. **Smallest change that could fix the failure mode**: sharpen a trigger description before restructuring a whole skill; restructure before splitting into two skills.
4. **Verify the update**: the next same-type task after a rewrite is the eval. Its ledger entry should reference the rewrite so the before/after is visible.
5. **Protected invariants** — never "evolved away" by this loop: the non-negotiable architectural rules in `CLAUDE.md` (provenance, ORDER BY immutability, two data planes, buy-vs-build, idempotency), file-ownership boundaries, and the no-commit/no-push rule. If a failure pattern seems to demand changing one of these, that's a user decision, not a SAGE rewrite.
6. Rewrites of *agent charters* for squad members go through the relevant lead + `principal-architect` when they touch ownership boundaries; skill rewrites within an agent's own domain need no approval beyond the evidence rule.

## Periodic audit (optional, on request)

When asked for a "SAGE audit": aggregate the ledger by agent and by skill, report success ratios, flag every pattern from the trigger table that has crossed threshold but not yet been acted on, and propose the corresponding rebalance/rewrite actions as a short list for the user to approve.
