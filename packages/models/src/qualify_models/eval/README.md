# Golden-set evaluation harness

Implements the per-stage golden-set evaluation from `docs/arquitectura.md` §7 for
the multimodal cascade in `packages/models`. It loads a labeled golden set, runs
the cascade (filter → vision → transcription → sentiment) per item, and reports
per-stage metrics with checkpoint provenance. **The golden set outranks the
documented model choices**: when these metrics contradict a doc'd checkpoint, the
metrics win and the doc should be updated.

## Layout

```
src/qualify_models/eval/
  schema.py       GoldenItem / GoldenSet + JSONL loader
  metrics.py      filter precision/recall/F1, sentiment accuracy, WER (via jiwer)
  provenance.py   StageProvenance + best-effort HF Hub revision resolver
  cost.py         parametric per-video cost model
  harness.py      evaluate() -> EvalReport (injectable runner + revision resolver)
  cli.py          `python -m qualify_models.eval`
eval_data/
  golden_set_v1.jsonl   the current golden set (1 item today; grows toward ~100)
```

## Labeling schema (`GoldenItem`)

One JSON object per line in a `.jsonl` manifest. Fields:

| Field | Meaning |
|---|---|
| `post_id` | Stable id of the source post (idempotency key component). |
| `platform` | `tiktok` \| `instagram`. |
| `image_path` | Frame fixture, **relative to the manifest file**. |
| `audio_path` | Audio fixture, relative to the manifest file. |
| `caption` | Post caption (drives the sentiment stage); nullable. |
| `filter_relevant` | **Ground truth**: should the F2 filter pass this as a candidate. |
| `reference_transcript` | **Ground truth**: human reference used as WER denominator. |
| `sentiment_label` | **Ground truth**: `POS` \| `NEU` \| `NEG` (robertuito's label set); nullable. |
| `labeler` | Who produced the labels (label provenance). |
| `labeled_at` | Date the labels were produced (`YYYY-MM-DD`). |
| `source_notes` | Free-text: labeling rationale, provisional-label flags, etc. |

Lines starting with `#` and blank lines are ignored, so a manifest can carry
header comments. Paths are resolved relative to the manifest's directory, so a
manifest is portable regardless of the caller's working directory.

## Provenance

The whole point of the golden-set gate is comparing runs across model swaps
(SigLIP2 vs a fallback, whisper-turbo vs alternatives). For two numbers to be
comparable, a report must pin everything that could move them. Every `EvalReport`
records:

- **Per stage**: the `model_id` that produced it and the HF Hub commit `revision`
  (sha). Revisions are resolved best-effort at run time; on an offline run
  (`--offline`, or an injected stub resolver) they are recorded as `null` —
  **never fabricated**.
- **Manifest identity**: `manifest_id` (file stem), `manifest_version` (the
  declared `# manifest_version:` directive in the manifest), and
  `manifest_sha256` (content hash of the manifest bytes). The declared version is
  the citable label; the hash is tamper-evident — a WER delta can be attributed
  to the model only if the manifest hash is unchanged between runs.
- **Code identity**: `harness_version` (metric/harness computation) and
  `pipeline_version` (the cascade). Both are pinned so a metric change (e.g. a
  WER-normalization tweak) is distinguishable from a model change.

This satisfies the project's hard provenance rule (`CLAUDE.md`: every derived
metric carries the checkpoint id + revision it came from) and mirrors the
first-class-provenance discipline in `docs/arquitectura.md` ADR 13/16.

**Versioning a manifest:** add a `# manifest_version: <n>` comment line to the
`.jsonl` (see `eval_data/golden_set_v1.jsonl`). Bump it whenever labels change so
older reports remain citable against the version they scored.

## Running

```bash
# Offline (no Hub call for revisions); prints JSON to stdout:
uv run python -m qualify_models.eval --manifest eval_data/golden_set_v1.jsonl --offline

# Real run: downloads/serves the models, resolves real Hub revisions,
# writes the report to a file, and plugs measured cost rates into the estimate:
uv run python -m qualify_models.eval \
  --manifest eval_data/golden_set_v1.jsonl \
  --out report.json \
  --vlm-usd-per-video 0.01 --asr-usd-per-video 0.002
```

A real run hits the network (model downloads + hosted ASR + Hub metadata) exactly
like the cascade's own `@pytest.mark.integration` tests.

## Cost model

`cost.py` is deliberately parametric. `docs/modelos-multimodal-fase1.md` and
`NOTES_pain_signal_feasibility.md` §5 establish only *relative* magnitudes — the
VLM (F3) and ASR (F1) stages dominate; the small CPU encoders (filter, sentiment)
are marginal when self-hosted — but **no absolute `$/video` figure for the VLM or
whisper exists in the docs**. So `estimate_cost()` treats those two as required
inputs: pass measured/quoted rates (`--vlm-usd-per-video`, `--asr-usd-per-video`)
to get a real total; otherwise the total is `null` and the missing inputs are
listed in `caveats`. It does not invent cents.

> **Open question for architect/PO (Fase 1 costing):** the absolute `$/video` for
> the hosted VLM and ASR stages is not documented anywhere yet. Closing out Fase 1
> cost sign-off needs a quoted HF Inference / Groq rate (or a measured self-hosted
> figure) for those two stages. Flagging here rather than inventing a number.

## Adding labeled items

1. Extract a frame + audio fixture for the video (same `ffmpeg` recipe as the
   existing `tests/fixtures`), place them somewhere the manifest can reference.
2. Append one JSON line to `eval_data/golden_set_v1.jsonl` with the fields above.
   Provide honest ground truth: `filter_relevant`, a real `reference_transcript`
   (human-typed, not a model's output — that would be circular for WER), and
   `sentiment_label`.
3. Run the offline harness to confirm it loads and the report shape holds.

## Current state and the 1 → ~100 scaling questions

`golden_set_v1.jsonl` has **1 item** today (the existing TikTok "MADONNA — HOUSE
OF CONFESSIONS" fixture). Its `filter_relevant=true` label is confident (the frame
is an unmistakable TikTok-branded event promo). Its `reference_transcript` is a
**placeholder (empty)** — the WER metric skips empty-reference items — and its
`sentiment_label=POS` is a **provisional** human read. Both are flagged in the
item's `source_notes` for re-labeling. So this run proves the harness *mechanics*
(shape, metrics, provenance, cost), not label-accuracy at scale.

Open questions to take to the product owner / architect before scaling to ~100:

- **Who labels?** The eval needs ~100 human-labeled videos. Is this a datasci
  task, a shared team effort, or outsourced annotation? WER references in
  particular are slow (careful transcription of Spanish social audio).
- **Labeling tooling.** Hand-editing JSONL does not scale to 100 items × 4 fields
  (esp. transcripts). Do we want a lightweight labeling UI / spreadsheet-to-JSONL
  export, and who owns it?
- **Effort estimate.** Rough order-of-magnitude: filter + sentiment labels are
  fast (seconds/item); a transcript reference is minutes/item. ~100 items is
  plausibly a day or two of focused labeling — needs confirmation and scheduling.
- **Sampling / class balance.** How do we source the ~100 so the filter
  precision/recall numbers are meaningful (enough true-negatives — irrelevant
  content — not just relevant videos)? This is a sampling-design decision, not a
  purely mechanical one.
- **Fixture storage.** 100 videos' frames+audio is larger than the repo should
  carry inline; decide where golden fixtures live (R2? git-lfs?).

These are decisions for PO/architect, not to be made unilaterally here.
