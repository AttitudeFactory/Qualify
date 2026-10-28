---
name: durable-findings
description: Make work and findings survive an agent's death. Use when starting any research/build task expected to run longer than a few tool calls, when you discover something that changes another agent's assumptions, when a session is about to hit a spend or context limit, or when a squad lead is preserving state before the team goes down. Covers both flushing your own output to disk incrementally instead of buffering a final report, and writing cross-agent findings to disk rather than delivering them by message only.
---

# Durable findings: nothing survives that only exists in a context window

Agent sessions in this project die routinely — hourly limits, monthly spend limits, connection drops. This is a **standing environment condition, not an anomaly**: it has happened in nearly every multi-agent session on record. The ledger (`.claude/compass-sage/ledger.md`) shows the pattern with unusual clarity:

- 2026-07-20: three teammates crashed in one round. The one that wrote incrementally lost **nothing**. The two that buffered their reports lost **everything**.
- 2026-07-21: same session shape, same split — every agent that flushed per section survived; the analysis loss came only from buffered agents.
- 2026-07-23: three teammates died within 34 seconds. The lead had verified findings that existed **only as messages** in its own context; they would have died with the lead's session.
- 2026-07-24: a specialist's *code* survived while its *prose* died — twice, in the same role. Files written early live; reports composed at the end do not.

The lesson is not "work faster." It is that **the only durable medium is the filesystem.** A verified discovery that never touched disk is exactly as lost as one that was never made.

## Rule 1 — Flush your own output per section, never buffer a final report

Write each section of a deliverable to its file **as you complete it**. Do not compose the whole document in your head (or in your reply) and write it at the end.

- Create the target file with its heading skeleton on your **first** substantive tool call, not your last.
- After each section is reasoned out, write it. A partially-written document is a recoverable asset; an unwritten complete one is nothing.
- This costs a few extra tool calls and buys total loss-resistance. The trade is not close.
- The same applies to code: land a working slice with its test, then the next. Do not stage a large change and commit it to disk only at the end.

**Anti-pattern that keeps recurring:** "I'll gather all the findings and then write the doc." That sentence has destroyed multiple sessions of work in this repo.

## Rule 2 — A finding that changes another agent's assumptions goes to disk, by its discoverer

Rule 1 protects deliverables. It does **not** protect findings that travel between agents, and that gap has been the more expensive one.

If you discover something that invalidates a teammate's plan, contradicts a spec, or changes what someone else should do — **you** write it to disk. Do not rely on messaging the lead. The lead's context window is as mortal as yours, and relaying is not persistence.

Where it goes, in order of preference:

1. **The doc that is now wrong** — correct it at the source, if you own that file.
2. **The session state file** — `.claude/sprint-state-<date>-<topic>.md`, the standing convention for in-flight sprint state.
3. **The ledger** — `.claude/compass-sage/ledger.md`, if it is an outcome or a process failure.
4. **A `NOTES_*.md` next to the code it concerns** — if you do not own the doc that should carry it, and the finding is domain-specific.

Then message the lead **as well**. Message *and* disk, never message *alone*.

**File ownership still binds.** If the finding belongs in a file you do not own, write it to your own notes or the sprint-state file and route the correction to the owner. Never silently edit another agent's file to record a finding — that is how two agents produce conflicting contracts.

## Rule 3 — When you sense the end, spend your last calls on disk

If you are near a limit, or you have just been told the team is going down:

- Stop analyzing. Write.
- Prefer **one honest paragraph on disk** over a polished report you may not finish.
- Record explicitly: what you verified vs. what you only believe; what you were mid-way through; what the next agent should NOT redo. Half-finished work that is silent about being half-finished causes duplicated effort or, worse, false confidence.
- A monthly spend limit is not resumable — write the state file and stop, rather than burning attempts.

## Rule 4 — Claims about disk must be verified against disk

Corollary, from the same ledger: leads repeatedly caught teammates reporting completion for work that was not on disk (and, twice, caught their own fabricated numbers). Before you claim a file exists, a test passes, or a section landed, **check** — `ls`, `grep`, re-run the command. "I wrote X" is a belief about your own past tool calls; the filesystem is the fact.

## Quick helper

To append a timestamped finding to the current sprint-state file without hand-formatting it:

```bash
uv run .agents/skills/durable-findings/scripts/record_finding.py \
  --file .claude/sprint-state-2026-07-26-c04-inflight.md \
  --agent pipeline \
  --title "Meta soft-404 on /documentation/graph-api/*" \
  --body "Returns HTTP 200 with a page-not-found body; a harvester would silently write junk files and report them as successes."
```

The script only appends — it never rewrites existing content — so it is safe to call from any agent regardless of who owns the file's other sections.
