# Copy experiment — which model writes the generator's copy

`run_experiment.py` runs the generator's copy over `cases.json` — 24 briefs of three
FICTIONAL brands (an ice-cream shop in Cúcuta, a smash-burger place in Bogotá, a
real-estate advisor in Medellín) across every kind and format — once per config, as a
Langfuse dataset run. Each variant is rendered with `render_prompt` exactly as
`ContentService` renders it and scored by the deterministic gates of
`qualify_api.evals.copy_quality` (docs/plan-observabilidad-langfuse.md §6.2): schema,
brand rules, printed lengths, «must mention / must avoid», plus diversity, cost and
latency. There is no gold copy; voice quality is a human judgement the gates do not
measure (plan §8).

It spends real money and needs the Langfuse server, so it is run by hand, never in CI:

```bash
just langfuse-up
just eval-copy                          # all configs, 2 variants per brief
just eval-copy --limit 3                # a pilot (its own dataset, copy-generador-piloto-3)
just eval-copy --configs opus-5.5@low
```

Results land in Langfuse under Datasets → `copy-generador` (one run per config, the
traces in the `sdk-experiment` environment, which the SDK sets) and here under `results/`.

## Result — lengths enforced, 2026-10-13 (`results/20261013-195325.json`) — CURRENT

Same day, after the copy adapter started HOLDING the limits (one repair turn on the
fields over their limit, then a word-boundary cut; the service passes the printed limits
of flyers, templates and carousels). The two candidates only; production was already at
1.000.

| config | gates | diversity | $/piece | p95 s |
|---|---|---|---|---|
| `claude-opus-5-5` @ medium (production, earlier run) | 1.000 | **0.890** | 0.0632 | 17.7 |
| `claude-opus-5-5` @ low | 1.000 | 0.768 | 0.0427 | 10.7 |
| `claude-sonnet-5-5` @ medium | 1.000 | 0.819 | **0.0201** | **9.3** |

One CTA (33 characters for a 32 limit) was still over after the repair and was cut; the
repairs are rare enough that the cost per piece barely moved (Sonnet 0.0199 → 0.0201).

Reading: with lengths held in code, both candidates pass every deterministic gate, so the
plan's rule no longer rules them out. **Sonnet 5.5 @ medium is the candidate to replace
Opus 5.5 @ medium**: a third of the cost, half the latency, slightly less varied hooks.
What the gates cannot say is whether it sounds like the brand — that is the human score
(`aprobado`, `edicion`) the Borradores now records. Before switching the default: a second
run, and a week of approvals compared by model in Langfuse.

## Result — 2026-10-13 (`results/20261013-184953.json`, `results/20261013-191138.json`)

24 briefs × 2 variants per config. `opus-5.5@low` is the clean rerun: its first run lost
9 calls to a three-minute network outage (APITimeoutError at ~17 s each, all between
23:03 and 23:06 UTC), which depressed its gate rate to 0.812 although every variant that
answered passed.

| config | gates | rules | lengths | constraints | diversity | $/piece | p95 s |
|---|---|---|---|---|---|---|---|
| `claude-opus-5-5` @ medium (production) | **1.000** | 1.000 | 1.000 | 1.000 | **0.890** | 0.0632 | 17.7 |
| `claude-opus-5-5` @ low | 0.979 | 1.000 | 0.979 | 1.000 | 0.777 | 0.0413 | 10.9 |
| `claude-sonnet-5-5` @ medium | 0.958 | 0.979 | 0.958 | 0.979 | 0.854 | **0.0199** | **8.3** |

Every failure is a LENGTH overrun, none a brand rule:

- Sonnet 5.5, avatar testimonial (`hel-08`): a 61-character hook against the schema's 60
  — `CopyPayload` rejects it, so in production that variant would fail validation.
- Sonnet 5.5, real-estate countdown (`inm-04`): a 33-character printed CTA against 32.
- Opus 5.5 @ low: one printed hook or CTA over its limit.

Reading, under the plan's rule (§6.3): a candidate may replace production if its gate
rate drops no more than 2 points. Opus @ low drops 2.1 and Sonnet 5.5 4.2, so **production
stays Opus 5.5 @ medium**. But the gap is entirely lengths, which code can enforce:
structured outputs cannot carry `maxLength` (`strict_schema` moves it into the
description), so a model is only asked, never held, to the limit. Enforcing the limits
(re-ask or trim before validation) and rerunning is the next step; if the gaps close,
Sonnet 5.5 writes this copy at a third of the cost and half the latency, and Opus @ low
at two thirds of the cost. One run each; the plan asks for a repeat before a default
changes.

Spend for the whole day's runs (pilot, full run, rerun): about $4.10 at the table's
conservative prices (cache tokens billed at the full input rate).
