# QUA-23 — Closing the SigLIP filter defect: measured baseline

Author: `datasci`, 2026-07-29. All commands run with `uv run --no-sync` (no `uv sync`,
per the venv trap in `CLAUDE.md`). No network, no weight downloads.

**Status: deliverables A-D BUILT. The decision rule is deliberately NOT chosen, and QUA-23
stays OPEN — honestly blocked, not abandoned.** That is the correct outcome, not a failure:
the issue's own criterion forbids replacing the constant without labelled data, and the
labelled data does not exist. §5 is the specification for what would unblock it. §7 lists what
landed.

This file is the durable record so the measurement does not have to be redone.

---

## 1. What the acceptance criteria claim vs. what is actually on disk

QUA-23 lists four criteria. **Two of them are already satisfied, and one is vacuous as
written.** Verified against the filesystem 2026-07-29, not inferred.

### 1.1 "Los dos tests que descargan pesos reciben marca `integration`" — ALREADY DONE

Both weight-downloading filter tests already carry the mark:

| Test | Mark |
|---|---|
| `tests/test_filter.py::test_run_filter_against_sample_frame` | `@pytest.mark.integration` |
| `tests/test_filter_calibration.py::test_filter_discards_the_only_real_fixture` | `@pytest.mark.integration` |

So does every other weight-touching test in the package (`test_sentiment.py`,
`test_vision.py`, `test_transcription.py`, `test_cascade.py`). Nothing to do here.

The *offline substitute* half is partially done: `test_filter.py`'s docstring records a
deliberate decision **not** to build a `FilterProvider` seam, with offline coverage relocated
to `test_filter_calibration.py` (6 offline tests). That is the "cobertura reubicada" the AC
asks for, already landed.

### 1.2 The offline gate command is VACUOUS as literally written

The AC gate is:

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run pytest -q
```

Run verbatim (with `--no-sync`): **175 passed**. Green.

**But it collects zero filter tests.** The root `pyproject.toml:52-57` sets
`testpaths = ["packages/api/tests", "packages/shared/tests", "packages/scraper/tests", "Qualify"]`
— `packages/models/tests` is deliberately excluded (comment at `pyproject.toml:48-49`:
the models suite runs under its own `ml` group). So a bare `uv run pytest -q` proves nothing
about the filter.

**The gate must name the path explicitly** to mean anything:
`uv run --no-sync pytest packages/models/tests -q`.

### 1.3 That explicit run is RED today — for an unrelated, pre-existing reason

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --no-sync pytest packages/models/tests -q
→ 7 deselected, 7 errors in 3.39s
   ModuleNotFoundError: No module named 'jiwer'
```

Seven collection errors: `test_conversation_cost`, `test_crm_cost`, `test_eval_harness`,
`test_eval_integration`, `test_eval_metrics`, `test_eval_schema`, `test_fase0_cost` — all via
`qualify_models/eval/metrics.py:5: import jiwer`.

**This is a venv gap, not a code defect.** `jiwer>=4.0.0` *is* declared
(`packages/models/pyproject.toml:32-33`, group `eval`, which is in `default-groups` at
line 37), but it is **not installed** in the shared `.venv`, while `torch 2.13.0`,
`torchvision 0.28.0` and `transformers 5.14.1` are. Classic partial-sync state — consistent
with the documented `uv sync` ↔ `uv sync --group ml` corruption trap.

**I did not fix this**: the fix is a sync, which is forbidden while other agents share the
workspace. It is pre-existing and unrelated to QUA-23's substance.

**RESOLVED 2026-07-29 — ephemeral dependency, no sync needed.** `uv run --with` injects a
package for one invocation without touching the shared `.venv`:

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --no-sync --with jiwer pytest packages/models/tests -q
→ 152 passed, 8 deselected in 5.43s
```

So the package-level gate **can** be certified without a sync and without coordinating with
other agents. The partial-sync gap remains logged above as pre-existing debt (`jiwer>=4.0.0`
declared in the `eval` group, which is in `default-groups`, yet absent from the `.venv` while
torch/transformers are present) — it should be repaired by whoever next has the workspace to
themselves, but it no longer blocks verification.

### The corrected gate

QUA-23's acceptance criterion should read (explicit path, ephemeral dep):

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --no-sync --with jiwer pytest packages/models/tests -q
```

A command that collects nothing is not a gate.

### 1.4 The filter-relevant subset IS green offline, cold cache

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --no-sync pytest \
  packages/models/tests/test_filter.py \
  packages/models/tests/test_filter_calibration.py \
  packages/models/tests/test_schemas.py -q
→ 6 passed, 2 deselected in 2.26s
```

---

## 2. The root cause is settled; only the operating point is open

Confirmed from `tests/test_filter_calibration.py` (which already pins the arithmetic offline,
no weights needed) and `filter.py`:

- SigLIP2 scores each label independently as `sigmoid(cos·112.66890716552734 − 16.771724700927734)`.
- The trained `logit_bias` of −16.77 is why absolute scores are tiny. **Correct behaviour**
  for a pairwise-sigmoid-loss model; not a bug, and not a broken text tower.
- `filter.py:36` hardcodes `threshold: float = 0.22`, which inverts to a required
  **cos ≥ 0.1376**. Best measured cosine on the real fixture across a hand-tuned label sweep:
  **0.1034**. Nothing clears the bar.
- 0.22 is almost certainly a softmax intuition — `1/5` uniform baseline over the five
  `DEFAULT_LABELS`, nudged up. SigLIP has **no softmax head**; scores do not sum to 1.

Nothing in §2 needs re-deriving. The open question is exclusively: **which decision rule, at
which operating point.**

---

## 3. THE BLOCKER, QUANTIFIED — the golden set cannot support any choice

`packages/models/eval_data/golden_set_v1.jsonl` holds **exactly one item**
(`tiktok_7663622615168306462`), and its label is **`filter_relevant: true`**.

So the labeled set is: **1 positive, 0 negatives.**

This is not "a small sample". It is structurally unable to answer the question, for two
independent reasons:

1. **Precision is undefined and unmeasurable.** Precision = TP/(TP+FP). With zero negative
   items in the set, a false positive **cannot be observed at any threshold**. Every rule that
   passes the single item scores precision 1.0; every rule that rejects it scores 0.0 (the
   `filter_metrics` implementation returns 0.0 for the empty denominator, which is a
   convention, not a measurement). A sweep over thresholds would produce a curve that looks
   like evidence and contains none.
2. **Recall is a single Bernoulli trial.** n=1. The 95% Wilson interval for 1/1 is roughly
   [0.21, 1.00]. Any recall estimate is compatible with a rule that is right 21% of the time.

Additionally, that one item's own `source_notes` flag its `reference_transcript` as an empty
**placeholder** and its `sentiment_label` as a **provisional** human read — so even the single
item is not fully adjudicated ground truth.

**Conclusion: the acceptance criterion "la elección se justifica contra datos etiquetados"
cannot be met with the data that exists.** Per the AC's own instruction, substituting a new
constant would be the same defect with better optics. The honest deliverable is the machinery
plus the labeling spec, not a number.

---

## 4. A rule that can be eliminated on structural grounds, without labels

Not everything needs data. **Top-k as literally stated (option b) cannot implement a filter.**

The cascade's purpose (`cascade.py`, gating vision on `filter_result.passed`) is to *discard
posts* so VLM spend lands only on pre-qualified candidates. Top-k over a fixed candidate-label
list selects k labels **for every image** — it ranks labels *within* an image and never
rejects an image. Discard rate would be 0%, and the cascade's cost model collapses.

There is, however, a viable **threshold-free** variant worth keeping on the table, which I
think the ticket's "top-k" was reaching for:

> **Argmax-over-partitioned-labels:** split the candidate labels into *relevant* and
> *distractor* sets, and pass the post iff the top-scoring label falls in the relevant set.

Note `DEFAULT_LABELS` already contains what looks like an intended distractor —
`"generic scenery"` — alongside four brand-relevant ones. This rule needs **no threshold
constant at all**, which makes it attractive: it cannot be mis-tuned the way 0.22 was. It
still needs labeled data to *validate*, but it has no free parameter to fit, so it needs
strictly less data than a fitted threshold.

This is the one substantive analytical result available without new labels, and it narrows
the choice from three options to two.

---

## 4b. Minor: `filter.py` has pre-existing format drift

`uv run --no-sync ruff format --check packages/models/src packages/models/tests` reports
**1 file would be reformatted**: `src/qualify_models/filter.py`. It is unmodified in
`git status`, so this predates Sprint 2 and is nobody's regression. Left alone deliberately —
reformatting it during QUA-67 would have put an unrelated diff in a contract change. Fold it
into the QUA-23 change, where `filter.py` is being edited anyway.

---

## 5. DELIVERABLE D — the labelling specification

**This is QUA-23's final deliverable.** The issue does not close. It stays open, honestly
blocked, because its own acceptance criterion says the choice must be justified against
labelled data and that data does not exist. What follows is exactly what would unblock it,
priced.

Every number below is computed by `required_n_for_proportion()` in
`src/qualify_models/eval/metrics.py` and pinned by tests — not estimated by hand.

### 5.1 How many items, and why

Sample sizes for a 95% Wilson interval, **per estimand**:

| True rate | ±15pp | ±10pp | ±5pp |
|---|---|---|---|
| 90% | 15 | **34** | 141 |
| 80% | 26 | 60 | 245 |
| 50% (worst case) | 39 | 93 | 381 |

**Precision and recall need separate budgets.** Recall is estimated over *actual positives*;
precision over *predicted positives*. One number cannot size both — a 100-item set split 90/10
sizes recall comfortably and starves precision. This is why `check_sufficiency()` counts the
two classes separately rather than checking a total.

**Recommendation: ~50 relevant + ~50 non-relevant ≈ 100 items.**

- 50 actual positives comfortably clears the 34 needed for recall at ±10pp.
- 50 non-relevant items ensure the predicted-positive denominator also clears 34 even if the
  rule over-fires somewhat.
- 50 per class buys ±8.5pp at an observed 90% — slightly better than the ±10pp target, which
  is the right side to err on.
- Going to ±5pp would cost ~141 **per class** (~280 items). That precision is not needed to
  choose between three rules whose differences, if real, will be much larger than 10pp.

> **This independently validates `docs/arquitectura.md` §7.** That doc already specified ~100
> labelled videos. It reads like a round number picked by feel; it is not — a power analysis
> from first principles lands in the same place. **The doc should be strengthened with this
> derivation, not corrected.**

### 5.2 What today's set actually is

`eval_data/golden_set_v1.jsonl`: **1 item.** `filter_relevant: true`. So 1 positive, 0
negatives → Wilson 95% on recall is **[0.21, 1.00]**, and precision is unmeasurable at any
operating point.

**And that single item is not usable as-is even for the one thing it covers.** Its own
`source_notes` record that:
- `reference_transcript` is an **empty placeholder** "pending a human listen" — so it
  contributes nothing to WER, and the metric skips it;
- `sentiment_label: POS` is a **provisional human read** of the caption's tone;
- both are explicitly "flagged for re-labeling".

So the honest count is **zero adjudicated items**, not one. Whoever funds the labelling round
should budget to re-label this item too, not treat it as one already banked.

### 5.3 What each item must carry

The schema already exists (`GoldenItem`, `src/qualify_models/eval/schema.py`) and needs no
change. Per item:

| Field | Who provides it | Notes |
|---|---|---|
| `post_id`, `platform` | scrape | idempotency key component |
| `image_path` | ffmpeg keyframe | the frame the filter actually scores |
| `audio_path` | ffmpeg | only needed for the ASR stage |
| `filter_relevant` | **human labeller** | the ground truth this issue needs |
| `reference_transcript` | **human transcription** | the expensive one; see 5.5 |
| `sentiment_label` | **human labeller** | POS/NEU/NEG |
| `labeler`, `labeled_at` | process | label provenance |
| `source_notes` | labeller | rationale, and any provisional flag |

### 5.4 Stratification

Do **not** sample 100 posts at random and hope the split lands near 50/50. Draw the two
classes deliberately:

1. **Relevance (the binding stratum): ~50 relevant, ~50 non-relevant.** Non-relevant is the
   class that does not exist today and the one precision depends on entirely.
2. **Platform:** roughly balanced TikTok / Instagram Reels. The filter runs on frames from
   both and there is no evidence they behave alike.
3. **Within non-relevant, include hard negatives**, not only obvious ones. A set whose
   negatives are all landscapes will make any rule look excellent. Include: generic indoor
   scenes, people with no product, text-only cards, other brands' content. Hard negatives are
   where a filter earns its keep, and where the ±10pp interval is worth having.

Avoid drawing many frames from a single video to inflate the count: frames from one video are
not independent samples, and the interval maths above assumes independence. One frame per
post.

### 5.5 Cost

The dominant cost is **human labelling time**, not compute.

- `filter_relevant` is a fast binary judgement from one frame: realistically **10-20 seconds
  per item** → ~30 minutes for 100 items.
- `sentiment_label` from the caption: similar, another ~30 minutes.
- `reference_transcript` is the expensive field — **real-time or worse**, several minutes per
  video. **Do not bundle it into this ask.**

**Recommendation: fund the filter labels first and separately.** `filter_relevant` for 100
items is roughly **one focused hour** and unblocks QUA-23 completely. Transcription labels
serve a different stage (ASR/WER) and can be funded later against their own question. Bundling
them turns a one-hour ask into a multi-day one and is the most likely reason this stays
unfunded for another sprint.

Compute cost is negligible: scoring 100 frames with SigLIP2-base on CPU is minutes, and the
sweep afterwards is pure arithmetic over stored scores — `ScoredItem` takes scores as input
precisely so re-evaluating a rule never re-runs the model.

### 5.6 What happens the moment the data lands

No new code. The machinery is already built and tested:

```python
report = recommend(
    [UNCALIBRATED_LEGACY_RULE, CosineThresholdRule(min_cosine=...), ArgmaxRelevantLabelRule(...)],
    scored_items,
)
```

`check_sufficiency()` will pass, `recommend()` will return an operating point with confidence
intervals and a discard rate, and closing QUA-23 becomes **changing one binding** —
`UNCALIBRATED_LEGACY_RULE` in `filter_decision.py` — plus inverting the defect-pin test in
`test_filter_calibration.py`, which its own docstring already instructs ("this test must be
inverted, not deleted").

---

## 7. What was built (2026-07-29)

### A — `src/qualify_models/filter_decision.py`

The decision rule as a named, swappable object instead of an anonymous constant.

- `FilterDecisionRule` protocol; `FilterDecision` carries `rule_id`, `rule_params` and
  `calibrated` so a stored decision can answer *which rule, at which operating point, and had
  it been validated?*
- Three rules, **all `calibrated=False`** because none has been validated:
  `ProbabilityThresholdRule` (the defect, kept and named), `CosineThresholdRule` (a monotone
  reparameterisation — same boundaries, but in the space where values are legible),
  `ArgmaxRelevantLabelRule` (**no free numeric parameter**; consults only ranking, so the
  sigmoid-scale defect cannot touch it).
- `SIGLIP2_LOGIT_SCALE` / `_BIAS` / `BEST_MEASURED_COS_SIM` moved here from the test file —
  they are properties of the checkpoint, not of a test, and two copies would drift.
  `test_filter_calibration.py` now imports them, so the defect pin is unchanged but no longer
  duplicated.
- `REJECTED_RULE_FORMS` — top-k recorded **as data** with its reasoning, so the option cannot
  be quietly re-proposed.

**The default is unchanged.** `run_filter` gains an optional `rule=` parameter; omitting it
reproduces previous behaviour exactly via `UNCALIBRATED_LEGACY_RULE`. Closing QUA-23 is a
one-line change of that binding, on the day data justifies it.

### B — `src/qualify_models/eval/calibration.py`

- `ScoredItem` takes scores as **input**, so re-evaluating a rule never re-runs the model;
  re-scoring is needed only when the checkpoint or the candidate labels change.
- `check_sufficiency()` counts positives and negatives **separately**, because precision and
  recall have different denominators and one total can size one while starving the other.
- `recommend()` returns `CalibrationReport` with `recommendation=None` when the data cannot
  support a choice. **The refusal is a first-class outcome, not an exception**, and it still
  reports the sweep — labelled as insufficient rather than presented as a finding.
- Degenerate rules (0% or 100% discard) are excluded from recommendation regardless of F1,
  which is what catches both the current defect and top-k.

### C — Wilson intervals in `src/qualify_models/eval/metrics.py`

`wilson_interval()` and `required_n_for_proportion()`; `FilterMetrics` now ships
`precision_ci` / `recall_ci`. Wilson rather than the normal approximation because the normal
interval reports **[1.0, 1.0] — certainty — from a single observation**, which is precisely
the misreading this project must not make. `None` for an empty denominator: undefined, not
wide. `required_n_for_proportion` is solved by search against the same interval function, so
the sample-size answer agrees with the interval actually reported.

### D — §5 above.

### Verification

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --no-sync --with jiwer pytest packages/models/tests -q
→ 203 passed, 8 deselected
```

New tests: `test_filter_decision.py` (28), `test_calibration.py` (23). All offline. Every
labelled set in `test_calibration.py` is synthetic **and legitimately so** — those tests
exercise the estimator (sweep, intervals, guard), never the model. No test in this change
asserts that any rule is correct, because no rule is calibrated.

---

## 6. Cross-references

- `packages/models/tests/test_filter_calibration.py` — the offline arithmetic pin. Its
  module docstring already states the "do not substitute an unvalidated constant" discipline.
- `packages/models/src/qualify_models/eval/metrics.py:39` — `filter_metrics()` already
  computes precision/recall/F1. **It returns point estimates with no confidence interval**,
  which at n=1 is actively misleading. Adding intervals is a real gap.
- `packages/models/src/qualify_models/eval/README.md` — golden-set schema and the "grows
  toward ~100" note.
- `docs/arquitectura.md` §7 — the golden-set gate this feeds.
