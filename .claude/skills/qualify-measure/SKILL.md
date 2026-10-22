---
name: qualify-measure
description: How Qualify measures an LLM classifier, prompt or generation model before it ships — golden set from real client data, dev/test split, per-class reliability, cost per client per month, Langfuse evals (`just eval-*`), and documenting every model or vendor test the same turn in docs/modelos-generativos/. Use when changing a prompt, adding or swapping a model or vendor, or building an eval.
---

# Qualify — measure before it ships

Reference implementation: `docs/intencion-comercial-medicion.md` (408 real comments, dev/test,
labeling rules, per-class reliability, classes below the bar shown as «no fiable»).

## Procedure

1. **Golden set from real data** of real tenants — anonymize anything that leaves the database.
   Spanish of CO/VE/UY. Write the labeling rules down before labeling.
2. **Split dev/test** and never tune on test.
3. **Baseline first:** measure the current prompt/model before the change, with the same set.
4. **Per-class metrics**, not just an average. Classes that miss the bar are marked unreliable in
   the product, not hidden.
5. **Cost next to quality:** USD per item and per client per month for a realistic client, from
   the versioned pricing table (`qualify_creative/pricing_data/`) and live vendor prices.
6. **Run it reproducibly:** an eval folder under `packages/api/evals/<name>/` with a `just eval-*`
   recipe; traces and scores in Langfuse (`just langfuse-up`). Live vendor calls only in evals or
   `integration`-marked tests.
7. **Provenance:** every stored output and metric records model id, revision/version and prompt
   version.
8. **Data terms:** check the vendor's license and whether it keeps or trains on client data
   (BytePlus authorized presets cede data — client data never goes there).

## Document the same turn

Every model or vendor test — passes and failures — goes into `docs/modelos-generativos/<model>.md`
(model id, date, settings, inputs, outcome, cost). If results contradict a documented choice, say
so with the numbers and propose the doc/code change: the golden set outranks the plan.

Methodology help: `eval-driven-dev`, `model-evaluation`, `claude-api`.
