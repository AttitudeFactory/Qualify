# OAuth/CRM path: which cascade stages transfer, and a Fase 1 defect found on the way

**Owner:** datasci (FDE) · **Date:** 2026-07-23/24 · **Session:** /team-dev sprint (IG Business/Creator CRM integration)
**Scope:** Tasks D3 (#11), D2 (#10), D4 (#12). D1 (#9) blocked on the harvested Meta reference.

**Precedent:** follows `NOTES_pain_signal_feasibility.md` (2026-07-18), `NOTES_fase0_agentive_layer.md` (2026-07-21) and `NOTES_manychat_activation_layer.md` (2026-07-23). Same rules: every checkpoint claim verified live against the HF Hub; no rate is invented; synthetic fixtures are labelled synthetic.

**Framing note.** This sprint is about integrating client Business/Creator Instagram accounts into Qualify's own CRM. It is **not** the "sell a publishing API to developers" pivot that `docs/fase0-zernio-mercado.md` §6.1 ruled NO-GO, and nothing here re-litigates that.

---

## 0. Headline findings

1. **A Fase 1 correctness defect, found while assessing stage transfer: `run_filter` returns `passed=False` for every input, so `run_vision` is unreachable through `run_cascade`.** The cascade's premise — a cheap filter that discards non-candidates so VLM spend lands only on pre-qualified content — is, as implemented, a filter that discards 100% of candidates. Root cause established quantitatively in §2. Filed as task #13, deliberately not fixed.
2. **Sentiment is the only stage that transfers unchanged into the day-one increment. It is also the only model in the stack with no declared licence.** The licence gap is pre-existing and documented; the **concentration** is new. §4.
3. **The discard gate survives on `mentioned_media` and `tags`, but siglip2 is the wrong instrument to fill it.** The architectural slot is real — third-party volume is unbounded and an @-mention proves only that the brand was *named*. The predicate that matters there is metadata and text, not pixels. §3.2.
4. **`vision` and `transcription` transfer *unchanged* to third-party media** — the one place the Fase 1 cascade is reused verbatim rather than repurposed. This is a sharper result than `NOTES_fase0_agentive_layer.md` §3.1 reached, because that analysis considered only owned media. §3.3.
5. **Competitor and unaffiliated-creator content remain structurally unreachable**, and this is now machine-readable rather than implied. §3.4.

---

## 1. Deliverables on disk

| Artifact | Purpose |
|---|---|
| `src/qualify_models/oauth_scope.py` | The (stage × surface) applicability matrix as typed data, consumed by the cost model |
| `tests/test_oauth_scope.py` | Offline tests pinning the matrix judgements |
| `tests/test_filter_calibration.py` | Pins the #13 filter defect: offline arithmetic tests + 1 integration test |
| `src/qualify_models/providers.py` | New `SentimentProvider` Protocol + `LocalRobertuitoSentimentProvider` |
| `src/qualify_models/sentiment.py` | Provider injection; records `model_id` on the result |
| `src/qualify_models/social/ig_comments.py` | IG owned-media comments → attributed polarity roll-up |
| `tests/fixtures/synthetic_ig_comments.json` | **SYNTHETIC** comment payload (see §6.2) |
| `tests/test_ig_comments.py` | Offline end-to-end tests + 1 integration test on real robertuito |

**Suite state: 76 offline tests pass against a cold HF cache, up from 25.** Before this sprint the suite reported 27 passing but only 25 of those were genuinely hermetic (§5). Verified with `HF_HOME` pointed at an empty directory, not merely a warm one.

---

## 2. The filter defect (task #13)

### 2.1 Symptom

`run_filter` returns `passed=False` for every input tried, across every label set tried. Measured 2026-07-23 on `tests/fixtures/sample_frame.jpg`, the repo's only real fixture:

| Label set | max score | threshold | passed |
|---|---|---|---|
| `DEFAULT_LABELS` (the shipped 5) | 0.0000323 | 0.22 | **False** |
| generic 3-label | 0.0003790 | 0.22 | **False** |
| binary | 0.0000879 | 0.22 | **False** |

`cascade.py` gates vision on `filter_result.passed`, so **`run_vision` is unreachable through `run_cascade`**.

Why it survived: `tests/test_filter.py` asserts only that scores lie in `[0.0, 1.0]` — a constant-`False` filter satisfies that perfectly — and the golden set has **1 item** with no filter label. This is exactly the defect class the golden-set evaluation exists to catch, and that mandate remains unfunded.

### 2.2 Two hypotheses, one survivor

The lead proposed an alternative root cause worth taking seriously: loading the model emits
`bos_token_id ... got 49406` / `eos_token_id ... got 49407`, which are **CLIP's** special-token ids. If the text tower were being fed mis-tokenized input, every score would be garbage regardless of threshold, and threshold recalibration would burn golden-set labelling effort and still fail.

**Ruled out.** Probing the pipeline the filter actually instantiates:

| Probe | Value |
|---|---|
| Tokenizer class | `GemmaTokenizer` |
| Tokenizer `vocab_size` | 256000 |
| `config.text_config.vocab_size` | 256000 (matches) |
| Tokenizer's real `bos`/`eos`/`pad` | 2 / 1 / 0 |
| `config.text_config.bos`/`eos` | 49406 / 49407 (**unused**) |
| `"brand logo"` → `input_ids` | `[15524, 6302, 1]` |
| Max token id emitted | 235250 (< 256000) |

The tokenizer emits its own Gemma ids and terminates with its own EOS (`1`). The CLIP ids sit vestigially in `text_config` and are never read. The transformers warning is additionally wrong on its own terms — it claims the vocab is "between 0 and 31999" when the model declares 256000.

The supporting observation offered for the tokenizer hypothesis — "scores barely move across label sets" — conflated *across* label sets with *within* one. Within a set the model discriminates strongly. Positive control on the same frame, nine labels:

```
   0.0059338  cos=0.1034  text overlay on a video
   0.0003448  cos=0.0781  a woman
   0.0002499  cos=0.0752  a person
   0.0002069  cos=0.0736  a woman speaking to the camera indoors
   0.0001083  cos=0.0678  a selfie video of a woman talking
   0.0000323  cos=0.0571  product close-up
   0.0000295  cos=0.0563  brand logo
   0.0000093  cos=0.0460  generic scenery
   0.0000013  cos=0.0284  a landscape
```

Top-to-bottom spread ~**4,500×**, with a semantically correct ordering on a TikTok frame that does carry on-screen text. A broken text encoder cannot produce that ranking. **The text tower is healthy; only the decision rule is broken.**

### 2.3 The real mechanism

SigLIP computes `logits = cos_sim · logit_scale + logit_bias`, then `sigmoid`. This checkpoint's trained constants, read off `SiglipModel`:

- `logit_scale.exp()` = **112.67**
- `logit_bias` = **−16.77**

The large negative bias is deliberate: SigLIP trains with a pairwise sigmoid loss in which nearly every in-batch pair is a negative, so the bias encodes a very low prior of match. At `cos_sim = 0` the score is **5.2e-8**. Small absolute scores are *correct behaviour*, not a bug — which is why this defect is invisible to casual inspection.

Inverting the threshold is the punchline:

> **`threshold = 0.22` demands `cos_sim ≥ 0.1376`.** The best hand-tuned label on this frame reached **0.1034**. Even a caption written to match the frame does not clear the bar.

The `0.22` constant sits just above `1/5 = 0.20`, the uniform baseline for a **softmax** over five candidate labels. That is almost certainly how it was chosen. SigLIP has no softmax head; its scores are independent per-label sigmoids that do not sum to 1 (measured sum ≈ 0.0001).

### 2.4 Why this is flagged, not fixed

Recalibrating without labelled positives and negatives replaces a wrong constant with an **unvalidated** one — the same defect wearing better optics. The honest options are (a) threshold in cosine space, (b) top-k ranking instead of thresholding, or (c) a threshold fit to labelled data. Choosing among them is a golden-set question, which is precisely the standing mandate that has never been funded. Filed as **#13**.

Note the ordering consequence for this sprint: proposing siglip2 as the enrichment gate for `mentioned_media`/`tags` (§3.2) would have meant reusing a component that **has never worked in this repo**.

---

## 3. D3 (#11) — stage-by-stage transfer

Implemented as data in `oauth_scope.py` rather than prose, so `eval/fase0_cost.py` reads the same matrix a human argues with. A cost curve that disagrees with the applicability matrix is a bug in one of them; keeping both in one place makes that detectable.

Verdicts are four-valued, not boolean. `APPLIES_UNCHANGED` (run the Fase 1 stage as-is) and `APPLIES_REPURPOSED` (the slot survives, but prompt/output schema/instrument change) have very different build costs, and a boolean collapses them.

### 3.1 Surfaces

Five OAuth-reachable surfaces (`docs/fase0-zernio-mercado.md` §4.1/§4.3), plus two modelled-as-unreachable. Graph API edge names are **provisional** pending #9's grounding in the harvested Meta reference.

| Surface | Third-party authored? | Modality | Volume bounded by |
|---|---|---|---|
| `owned_media` | No | video+image+text | the client's own publishing rate |
| `owned_media_comments` | **Yes** | text only | audience size × engagement — UNMEASURED |
| `mentioned_media` | **Yes** | video+image+text | third-party behaviour — effectively unbounded |
| `mentioned_comment` | **Yes** | text only | third-party behaviour — effectively unbounded |
| `tags` | **Yes** | video+image+text | unbounded, and cheaper to trigger than a mention |
| `competitor_content` | — | — | **not reachable** |
| `unaffiliated_creator_content` | — | — | **not reachable** |

### 3.2 Filter — dies on owned media, survives as a *slot* on third-party media

- **`owned_media`: does not apply, bluntly.** The filter answers "is this content about the brand". On a connected account the OAuth grant answers that a priori — the client owns the media. Nothing is discarded, so none of the cascade's discard economics exist here.
- **`mentioned_media` / `tags`: the gate survives, the instrument does not.** Third-party volume is unbounded, and an @-mention proves the brand was **named**, not that the media merits a VLM pass. So the cheap-gate-before-expensive-stage shape transfers intact. But the predicate changes from *visual brand-relevance* to *enrichment-worthiness* — author reach, spam/giveaway density, substantive vs drive-by — which lives in payload metadata and caption text, not in pixels. The cheapest effective gate is free numeric predicates from the payload, then a cheap text classifier, and only then the VLM. Routing that decision through a zero-shot **image** classifier is both more expensive and less informative.
- **`tags` needs the gate harder than `mentioned_media`.** Tagging costs the tagger less effort than composing an @-mention, so bulk-tag, giveaway and spam density is higher and signal-to-volume is worse. This is the surface most able to run up a VLM bill on worthless content.

This corrects my own initial position. I first claimed the filter stage does not carry over at all; the lead pushed back on `mentioned_media`/`tags` and was right. The formulation that survives is **"the architectural slot survives, the incumbent instrument does not"** — and per §2, the incumbent instrument does not currently work at all.

### 3.3 Vision and transcription — unchanged on third-party media, repurposed on owned

- **`mentioned_media` / `tags`: `APPLIES_UNCHANGED`.** Genuine earned media authored by a third party. Describing what someone else showed about the brand, and transcribing what they said about it out loud, is the Fase 1 visual-listening use case verbatim — prompt and output schema included. **This is the one place the cascade is reused wholesale.**
- **`owned_media`: `APPLIES_REPURPOSED`.** Description is worth ~nothing (the client authored the video and knows what is in it). The value is structured creative-feature extraction for cross-post comparison — a different prompt and output schema behind the same Provider seam. This restates `NOTES_fase0_agentive_layer.md` §3.1 and does not redo it.

**This is a genuine extension of the prior notes, not a repetition.** That analysis concluded reuse was "thinner than it looks" — correct for owned media, which is all it examined. Once `mentioned_media` and `tags` are on the table, vision and ASR transfer *unchanged* to a real earned-media surface reachable **without scraping**. That is a narrow bridge, but it is wider than the previous session found, and it is the only part of the multimodal thesis that OAuth can serve.

### 3.4 Sentiment, and the structural negatives

- **`owned_media_comments` / `mentioned_comment`: `APPLIES_UNCHANGED`.** robertuito is trained on Spanish social-media text and IG comments are in-distribution. Third-party audience voice, no scraping, no ClickHouse, no VLM, no GPU. This is the composition point of `docs/fase0-zernio-mercado.md` §4.3.
- **`mentioned_media` / `tags` captions: `APPLIES_REPURPOSED`.** Captions run longer than the tweet-length distribution robertuito was trained on. Treat polarity there as weaker evidence than on comments until measured.
- **`owned_media`: does not apply.** Polarity of a caption the client wrote themselves is an authored property, not a measurement.
- **`competitor_content` / `unaffiliated_creator_content`: `UNREACHABLE` for all four stages.** No OAuth grant can exist — a client cannot authorize access to an account it does not control. These are modelled rather than omitted precisely because the negative result is the load-bearing strategic finding (`docs/fase0-zernio-mercado.md` §4.2), and a matrix that simply lacked the rows would read as an oversight instead of a verdict.

---

## 4. The robertuito risk concentration

**The licence gap is not new and must not be reported as new.** `docs/modelos-multimodal-fase1.md:91` already records it: *"Caveat de licencia (heredado, no nuevo): el Hub no declara licencia para los repos `pysentimiento/robertuito-*`"*, with the ADR 13 non-commercial guardrail cited. Re-verified live 2026-07-23: still no `license` field, 271.8M downloads, last updated 2024-07-08.

**What is new is the blast radius.** In Fase 1, robertuito was one stage of four in a cascade over scraped content; an unresolved commercial-use question was a contained problem with obvious substitutes. On the OAuth/CRM path, per §3, it is **the only model in the day-one increment** — the increment that runs on comments alone, with no VLM, no GPU and no scraping. Same unresolved licence, radically different exposure.

**Precision matters here, so state it exactly.** Sentiment is *not* the only stage transferring unchanged overall — vision and transcription also transfer unchanged to `mentioned_media` and `tags` (§3.3). The accurate claim is narrower and stronger for planning purposes:

> On the **day-one increment** — comments only, no VLM, no GPU, no scraping — robertuito is the sole model in the loop, and it is the one model in the stack with no declared licence.

Resolution (chasing the original repo/paper terms; deciding whether the MIT-licensed `MoritzLaurer/bge-m3-zeroshot-v2.0` becomes the default) is a `docs/` change and therefore the architect's call. Routed, not fixed here.

---

## 5. Test-hygiene finding: the suite was not as offline as it claimed

`pyproject.toml` declares `markers = ["integration: hits the network ..."]` with `addopts = "-m 'not integration'"`, and four test files use the marker correctly. **Two did not**, and they were the only unmarked network tests in the package:

- `tests/test_filter.py::test_run_filter_against_sample_frame`
- `tests/test_sentiment.py::test_run_sentiment_on_spanish_text`

Evidence: with a warm HF cache the suite reports **27 passed**; with `HF_HOME` pointed at an empty directory it reports **2 failed, 25 passed**, both failing with `OSError: We couldn't connect to 'https://huggingface.co'`. They pass on a developer machine and fail on a clean checkout.

**Correction to this package's own record:** `NOTES_fase0_agentive_layer.md` §1.1 states "27 unit tests pass ... with zero network". That is true only on a warm cache. Correcting my predecessor session's overstatement rather than inheriting it.

Reproduction:

```bash
cd packages/models && HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run pytest -q
```

**Follow-up deferred by decision, not oversight:** no `FilterProvider` seam is being built this sprint. Given §3.2 — the filter's slot survives on only two surfaces, filled by a different instrument — building its provider seam now would be speculative work on a stage this product may not run in its current form.

---

## 6. D2 (#10) — sentiment over owned-content comments, proven end-to-end

### 6.1 What was actually blocking it

Not modelling — plumbing. `run_sentiment` constructed a `transformers.pipeline` inline, so the stage could not be exercised without weights, and every test of it was a network test in disguise (§5). `vision` and `transcription` already had Provider seams; `filter` and `sentiment` did not.

Closed by adding `SentimentProvider` to `providers.py` (same Protocol shape as the other two) plus `LocalRobertuitoSentimentProvider` as the default. `run_sentiment` now takes an optional `provider` and is otherwise backwards compatible. `SentimentResult` gained an optional `model_id`, so a polarity result records the checkpoint that produced it — the provenance rule the other two stages already satisfied and this one did not.

Worth noting for the ledger: a previous session of this role improvised an *injectable-runner* pattern to work around exactly this gap. This closes it at the abstraction rather than routing around it again.

### 6.2 Fixture honesty

`tests/fixtures/synthetic_ig_comments.json` carries `"_fixture_kind": "SYNTHETIC"` and a `_warning` stating in full that no Graph API response was captured, no real account was connected, and no real user's comment or username appears. `test_fixture_is_labelled_synthetic` asserts those markers, so replacing the file with real captured payloads requires consciously deleting the marker — which is the right moment to ask whether real users' comments belong in a git repo.

The field shapes follow `docs/fase0-zernio-mercado.md` §4.1 and are marked **provisional**: grounding them in the harvested Meta reference is D1's job (#9), and this module deliberately does not pre-empt it. Nothing in it names a CRM table, column or entity — that is the architect's call under A2.

### 6.3 Result

`analyze_comments` takes a parsed payload and returns a `CommentSentimentSummary`: per-comment `SentimentResult` rows attributed to the real IG comment id, plus label counts, `net_sentiment` and `negative_share`.

Real robertuito on the synthetic fixture (integration test, weights loaded from cache):

| Label | Score | Comment |
|---|---|---|
| POS | 0.970 | *Me encanta este producto, la calidad superó mis expectativas* |
| NEG | 0.927 | *Llevo tres semanas esperando mi pedido y nadie responde* |
| NEU | 0.906 | *Alguien sabe si hacen envíos a Colombia?* |
| NEU | 0.855 | *Sí, envían a toda Latinoamérica* |
| NEG | 0.938 | *Pésima atención al cliente, no vuelvo a comprar* |

`counts={'POS': 1, 'NEG': 2, 'NEU': 2}`, `net_sentiment=-0.2`, `negative_share=0.4`, `analyzed=5`, `skipped_empty=2`, `total=7`.

**The §4.3 claim is confirmed: this runs today.** No scraping, no ClickHouse, no VLM, no GPU — a comments payload and a 109M-param CPU model.

### 6.4 Three deliberate restraints

- **Empty and whitespace-only comments are skipped, not classified.** An image-only or emoji-stripped comment gives the model nothing to read; classifying it manufactures a label from nothing. They are counted in `skipped_empty` so totals still reconcile.
- **No alerting threshold is proposed.** `negative_share` is returned as a plain ratio. Picking a crisis-alert cutoff without labelled data would repeat exactly the mistake behind the #13 filter defect: an unvalidated constant that looks like a decision.
- **The integration test asserts label *vocabulary* and provenance, never label *correctness*.** Accuracy is a golden-set question and the golden set has one item.

One honest detail from building it: the stub provider used in the offline tests labels *"Sí, envían a toda Latinoamérica"* POS, while real robertuito calls it NEU (0.855) — arguably the better answer, since it is a factual statement. The stub is a keyword matcher, not a sentiment model, and its docstring says so. It exists to prove the pipeline around the model, not the model.

---

## 7. D4 (#12) — cost model for the OAuth/CRM path

`estimate_crm_account` in `eval/fase0_cost.py`, a sibling of `estimate_account` rather than a replacement. Tests in `tests/test_crm_cost.py`.

### 7.1 Why the unit changes again

`cost.py` prices the Fase 1 cascade at $/video. `fase0_cost.estimate_account` prices a publishing product driven by how much the client **publishes**. The CRM path is driven by how much their audience and third parties **say** — inbound volume, which is a behaviour of *other people*. That distinction is the whole model: the client controls their posting rate, and nobody controls their mention rate.

The model reads the §3 applicability matrix rather than restating it (`comment_sentiment_applies()`, `requires_enrichment_gate()`), and raises if the matrix stops supporting its premise. A cost curve that silently disagrees with the stage assessment is the failure this is built to prevent.

### 7.2 The two increments

- **Day-one** (`analyze_mentions=False`): comment polarity only. One operation, no VLM, no ASR, no gate.
- **Earned-media** (`analyze_mentions=True`): adds the enrichment gate, mention vision and mention transcription over `mentioned_media` + `tags`.

### 7.3 The headline number

Only the VLM stage is priceable from published rates (Anthropic list prices on a token-shaped operation). At 4 frames/mention, against a **$6/month account** and the 20% tripwire:

| Model | $/mention | Enriched mentions affordable before AI spend passes 20% of revenue |
|---|---|---|
| `claude-haiku-4-5` | $0.00890 | **~135/month** |
| `claude-sonnet-5` | $0.02670 | ~45/month |
| `claude-opus-4-8` | $0.04450 | ~27/month |

**Even on the cheapest model a $6 account affords only ~135 enriched mentions a month.** I found this by writing a test that assumed Haiku would be safe at 250 enriched mentions; it failed, and the failure was right. That is a small budget for any brand with real mention volume, and it reproduces the structural problem `NOTES_fase0_agentive_layer.md` §3.3 identified for competitor analysis: **the billing unit (connected accounts) and the cost driver (third-party mention volume) come apart.** Mentions are not correlated with connected accounts, so they cannot be bundled into a flat per-account subscription. The earned-media increment needs a hard per-tenant quota, metered/credit pricing, or an aggressive gate — and realistically all three.

These figures are **VLM-only lower bounds**: ASR and the gate are unpriced, so real totals are higher by an unknown amount.

### 7.4 The gate is the dominant lever, and it does not exist

`mention_gate_pass_rate` multiplies every downstream per-mention cost linearly — a gate passing 20% instead of 100% cuts VLM+ASR spend fivefold, and it is the difference between the earned-media increment being viable and being underwater at a busy brand.

**It prices a component that has not been built.** Per §2, `filter.py` is a constant-`False` function; per §3.2 the surviving gate is metadata/text predicates rather than siglip2. The parameter is exposed and its `note` field says so explicitly, tested by `test_gate_note_flags_that_no_gate_exists_yet`.

### 7.5 What stays `None`, and why

All of these are behaviours of other people that nobody in this project has measured. Each is a **required caller input with no default**, and leaving any one `None` nulls the whole total (`test_one_missing_rate_nulls_the_whole_total`):

| Input | Why it has no value |
|---|---|
| `comments_per_month` | No connected-account comment-volume data exists in this repo |
| `mentions_per_month` | Same, and it is set by third parties — unbounded in principle |
| `mention_gate_pass_rate` | No enrichment gate has ever been calibrated |
| `sentiment_usd_per_comment` | robertuito CPU cost was never profiled here; no hosted per-call rate sourced |
| `gate_usd_per_mention` | The gate does not exist |
| `asr_usd_per_mention` | The same unsourced hosted-ASR rate open since Fase 1 (`eval/README.md`) |

Passing `0.0` to model self-hosting is a modelling choice the **caller** makes explicitly. The function will not make it for them — that is the difference between a documented assumption and a fabricated rate.

**Note on self-hosted classification cost, raised by PO:** at two-tenant volume the marginal dollar cost of a self-hosted classifier is effectively zero, because the cost is the already-provisioned worker rather than the call. But dollars are the wrong constraint there. Zero-shot NLI runs **one forward pass per (text, candidate-label) pair**, so compute scales with `messages × labels`, not messages. **The throughput lever is the label taxonomy, not the tenant count** — a design constraint on the intent list, not a budget line. No throughput figure is given because none has been measured.

### 7.6 Field rename

`OperationCost.usd_per_call` → **`usd_total`**. The old name was a misnomer at every construction site: it holds a *period total*, not a unit price.

Renamed period-**neutrally** rather than to `usd_per_month` as originally approved, because grepping consumers first (as required) turned up a second one: `eval/conversation_cost.py` shares `OperationCost` and populates it with **per-conversation** totals. `usd_per_month` would have been wrong there. Both modules updated; full suite green.

---

## Provenance

- **Checkpoint facts verified live via `hub_repo_details`, check-date 2026-07-23:** `pysentimiento/robertuito-sentiment-analysis` (no declared licence, 108.8M params), `MoritzLaurer/bge-m3-zeroshot-v2.0` (MIT, 567.8M params, hf-inference live).
- **Runtime facts measured this session** (`packages/models`, macOS, `uv run`, offline): siglip2 score distributions across four label sets on `tests/fixtures/sample_frame.jpg`; `GemmaTokenizer` identity and vocab; `logit_scale`/`logit_bias` read off `SiglipModel`; warm-vs-cold-cache suite behaviour.
- **Code inspected:** `filter.py`, `sentiment.py`, `cascade.py`, `providers.py`, `schemas.py`, `eval/cost.py`, `eval/fase0_cost.py`, `pyproject.toml`, `tests/test_filter.py`, `tests/test_sentiment.py`, `tests/test_fase0_cost.py`.
- **Docs referenced (not edited — owned by architect):** `docs/fase0-zernio-mercado.md` §4.1/§4.2/§4.3/§6.1; `docs/modelos-multimodal-fase1.md` (incl. line 91); `CLAUDE.md`.
- **Prior notes built on, not redone:** `NOTES_fase0_agentive_layer.md` §1.1/§3.1; `NOTES_manychat_activation_layer.md` §2.1/§2.2/§2.3; `NOTES_pain_signal_feasibility.md`.
- **Routed to the architect via the lead** (I do not own `docs/`): the #13 filter defect versus the cascade discard economics described in `docs/modelos-multimodal-fase1.md` and `docs/arquitectura.md` §3.4; the robertuito concentration in §4.
