# Signal-detection feasibility for creator/podcaster pain points

**Owner:** datasci (FDE) · **Date:** 2026-07-18 · **Session:** /team-research
**Scope:** For each creator/podcaster pain point, can Qualify detect it as a *signal* from content it already ingests (video frame / audio / caption / comments), using the current multimodal cascade? Where not, what live-verified HF Hub checkpoint closes the gap, at what cost, and how does the golden-set eval extend?

**Cascade under evaluation (what exists in `packages/models`):**

| Stage | Checkpoint | Modality | Output |
|---|---|---|---|
| F2 filter | `google/siglip2-base-patch16-224` | image (frame) | zero-shot image label (is-this-relevant gate) |
| F3 vision | `Qwen/Qwen3-VL-4B-Instruct` (local default; moondream3-preview deferred) | image+text | free-text description / structured query |
| F1 ASR | `openai/whisper-large-v3-turbo` | audio | transcript |
| sentiment | `pysentimiento/robertuito-sentiment-analysis` | text (ES) | 3-class polarity POS/NEG/NEU |

**Central finding up front.** The cascade can *transcribe and describe* content well, but for **text semantics it only has 3-class polarity**. It has **no text topic / intent / stance / emotion classifier**. Almost every creator pain point that isn't "generic negativity" is a *topic* signal (payment complaints, brand-deal friction, "open to sponsorship" intent, burnout language) — polarity alone cannot separate "I'm angry at my ex" from "I'm angry the brand hasn't paid me." So the recurring answer below is: *transcription/ingest is already there; the missing piece is a text topic/intent classifier*, which one added zero-shot checkpoint covers for all of them at once.

> Pain-point list below is the working set (brand-deal friction, payment delays, burnout/algorithm anxiety, sponsorship discovery, plus podcaster-specific). It will be reconciled against gtm's final pain-point doc when delivered; the *detectability logic* per row does not depend on the exact wording of the list.

---

## 1. Signal feasibility per pain point

Legend — **Detectable today**: yes / partial / no, against the *current* cascade only.
"Source" = which ingested modality carries the signal. "Gap" = capability missing.

| # | Pain point (creator/podcaster) | Source modality | Detectable today? | Why / what's missing |
|---|---|---|---|---|
| P1 | **Burnout / creator fatigue** (own captions/audio: "taking a break", "burnt out", "exhausted") | caption + transcript | **partial** | robertuito flags NEG polarity, but burnout ≠ generic negativity. Needs emotion (fear/sadness) + a "burnout" topic label. Gap: emotion + zero-shot topic classifier. |
| P2 | **Algorithm anxiety** ("reach is dead", "shadowbanned", "views tanked") | caption + transcript | **partial** | Same as P1: distinctive *topic*, only weakly correlated with polarity. A creator can complain about the algorithm in a upbeat tone. Gap: zero-shot topic classifier. |
| P3 | **Brand-deal friction** (creator venting about a bad sponsorship experience, unclear briefs, creative control) | transcript + caption + comments | **no** | Requires (a) detecting the *topic* is a brand deal and (b) the *stance* is negative/friction. Polarity can't localize the target. Gap: zero-shot topic + stance classifier. |
| P4 | **Payment delays / non-payment** ("brand still hasn't paid me", "chasing an invoice") | transcript + caption + comments | **no** | Specific complaint topic, low base rate, easily missed by polarity. Gap: zero-shot topic/intent classifier. High business value (buying signal for a "creator advocacy"/dispute feature) but rare in public content → recall will be the hard metric. |
| P5 | **Sponsorship discovery / "open to brand deals"** (creator signaling availability: "DM for collabs", "business inquiries →") | caption + transcript + on-frame text (OCR) | **partial** | This is *intent* detection. Caption keywords ("collab", "PR friendly", link-in-bio) are catchable by rules/FTS today; robust detection wants zero-shot intent. On-frame "business inquiries" text is reachable via Qwen3-VL OCR (F3) but not siglip2 (F2 is label-only, no OCR). Gap: zero-shot intent classifier; OCR already covered by F3. |
| P6 | **Ad-disclosure / FTC compliance patterns** (is this post sponsored? "#ad", "paid partnership", "gifted", verbal "thanks to X for sponsoring") | caption + transcript + on-frame text | **partial** | *Presence of a disclosure* is largely rule/keyword-detectable on caption+transcript today (high precision on explicit tags). *Verbal/implicit* sponsorship without a tag needs zero-shot ("is this segment a paid promotion?"). No dedicated FTC checkpoint exists on the Hub (searched); the practical build is rules + zero-shot NLI, not a bespoke model. Gap: zero-shot classifier for the implicit case. |
| P7 | **Audience-sentiment / early crisis on a creator's content** (comment section turning negative) | comments | **yes** | This is exactly robertuito's job: polarity over the comment stream, aggregated + windowed. Already in-cascade. Topic of the backlash (why) needs the topic classifier, but the *that-it's-happening* signal is detectable today. |
| P8 | **Brand/product mention & sentiment in-video** (creator praises/criticizes a brand in audio or on screen) | transcript + frame | **partial** | Brand *recognition* is Qwen3-VL's strength (F3 "recognizes brands/products/landmarks", per modelos doc) and transcript carries spoken mentions. Sentiment toward that brand needs aspect-level sentiment; robertuito is document-level polarity, not aspect-based. Gap: aspect/target-based sentiment (zero-shot stance is a workable proxy). |
| P9 | **Podcaster: topic/segment discovery** (what a podcast episode is actually about, for matching/discovery) | transcript (audio-dominant) | **yes (transcribe) / partial (label)** | Podcasts are audio-first → whisper-large-v3-turbo is the right tool and already in-cascade; transcription is solved. Turning the transcript into *topics/themes* for discovery needs the zero-shot topic classifier (or embeddings + clustering, which is the Phase-4 bge-m3 path). Gap: topic labels over transcript. |
| P10 | **Podcaster: sponsor-read detection & brand-safety** (ad reads inside episodes, unsafe content) | transcript | **partial** | Same machinery as P6 over long-form audio. Detectable-ish with zero-shot; not with the current stack alone. |

**Summary of the gap.** 7 of 10 rows resolve to the *same* missing capability: **zero-shot text topic/intent/stance classification** (P1–P6, P8–P10). One row (P7 crisis-onset) is detectable today. One capability (emotion, P1/P2) is a nice-to-have refinement on top. There is **no** pain point in this set that needs a *new visual or audio model* — the ingest side (whisper, Qwen3-VL OCR, siglip2) already captures the raw signal; what's missing is a text-understanding head richer than 3-class polarity.

---

## 2. Candidate checkpoints (new detection needs)

All rows verified **live** on the HF Hub via `hf-mcp hub_repo_details`, check-date **2026-07-18**. "Provider" = HF Inference Providers availability (the "buy-first, self-host-later" pattern the rest of the stack uses). All are commercial-friendly (MIT) except the pysentimiento license caveat noted.

| Checkpoint (verified live 2026-07-18) | Task | Params | License | HF Inference Provider | Covers pain points | Notes |
|---|---|---|---|---|---|---|
| **`MoritzLaurer/bge-m3-zeroshot-v2.0`** | zero-shot text classification (NLI) | 567.8M (xlm-roberta) | **MIT** | **hf-inference (live)** | P1–P6, P8–P10 | **Primary recommendation.** Multilingual incl. ES; arbitrary candidate labels, no labeled training data needed. `zeroshot-v2.0` line was explicitly trained on commercially-usable data. Shares base with `BAAI/bge-m3`, already proposed for lookalike/RAG embeddings in `docs/arquitectura.md` §4/§8.1 → checkpoint-family synergy. |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | zero-shot text classification (NLI) | 278.8M (deberta-v2) | MIT | hf-inference (live) | same as above | **Cheaper fallback.** ~½ the params, lower cost/latency, slightly lower quality. Multilingual incl. ES. Good default if per-video budget is tight. |
| `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | zero-shot text classification (NLI) | 278.8M | MIT | hf-inference (live) | same | Older baseline (XNLI/MNLI only). Listed for completeness; the `-2mil7` variant supersedes it (trained on 26-lang 2.7M-pair set). |
| **`pysentimiento/robertuito-emotion-analysis`** | emotion classification (ES) | ~109M-class (roberta) | *not declared in Hub metadata* | not listed (run local CPU) | P1, P2 | Same pysentimiento family as the already-committed sentiment model → **zero new infra**, same Provider pattern, same CPU footprint. Ekman-style emotions (joy/sadness/anger/fear/surprise/disgust/others) — captures the fear/sadness/anger axes that proxy anxiety/burnout, but not "burnout" as a named topic → pair with zero-shot, don't use alone. |
| `pysentimiento/robertuito-irony` | irony detection (ES) | roberta | *not declared* | not listed (local) | (refinement) | Optional: sarcasm flips polarity; useful to de-noise P7 comment-sentiment. Not required for v1. |

**License caveat (flag for architect, ADR 13).** The Hub metadata declares **no license** for the pysentimiento repos. This is an **inherited** question — it applies equally to `pysentimiento/robertuito-sentiment-analysis`, which the stack has *already* committed to — not a new risk introduced by the emotion model. Given `docs/arquitectura.md` ADR 13 explicitly rejects non-commercial (CC-BY-NC) embedding models, the pysentimiento terms should be confirmed against the upstream repo/paper before either model is locked for a commercial product. If they turn out non-commercial, the zero-shot MIT models (which can emit emotion-style labels too, e.g. labels `["ansiedad","agotamiento","enojo","alegría"]`) are a clean commercial substitute.

**No dedicated FTC/ad-disclosure checkpoint exists** on the Hub as of this check (searched zero-shot/NLI/spanish and emotion/spanish spaces). Ad-disclosure (P6) is best built as **rules + zero-shot NLI**, not a bespoke model — the explicit-tag case is a high-precision keyword match, the implicit/verbal case is a zero-shot hypothesis ("este contenido es una promoción pagada").

---

## 3. Viabilidad técnica de features competidoras

Technical-feasibility read of the AI-ish features competitor CRMs ship (from `docs/research-features-gtm.md` + gtm's teardown), against Qualify's *actual* planned stack: robertuito/whisper/Qwen3-VL/siglip2 cascade, `sentence-transformers`/bge-m3 embeddings, LangGraph orchestrator, ClickHouse (`search.*`, `crm.creator_centroids`). "Thin layer" = reuses planned infra; "new infra" = needs a component not yet designed.

> Pending gtm's final competitor-feature list; rows below cover the features already documented (Modash/Kuli/Syncly lookalike, Trigify signals, Clay enrichment, plus the common CRM-AI features named in my brief). Will extend on gtm's delivery.

| Competitor feature | Where seen | Feasibility vs Qualify stack | Verdict |
|---|---|---|---|
| **Content-based creator lookalike** (visual+topic) | Modash Lookalikes API, Kuli, Syncly | Directly on the planned `crm.creator_centroids` + bge-m3/SigLIP2 embeddings + ClickHouse `vector_similarity` (ADR 9–12). This is *already designed*, not new. | **Thin layer** on Phase-4 design. |
| **Audio-Intelligence discovery** (match by spoken words) | Syncly, Kuli | whisper-large-v3-turbo (F1) already transcribes; transcript → bge-m3 embedding → same centroid path. Qualify's comment-axis (embedding commenters) is the *net-new* differentiator none of them have (`research-features-gtm.md` §Área1). | **Thin layer**; comment-axis is additive moat. |
| **Auto-reply / smart-reply drafting** | generic CRM-AI, Trigify Jarvis | This is LLM generation in the LangGraph orchestrator (`docs/arquitectura.md` §3.5), RAG over `search.content_index`. No cascade model involved. Needs prompt/graph work, not new ML infra. | **Thin layer** on planned orchestrator (Phase 5). |
| **Lead/creator scoring** | Upfluence Jaice, generic | Score = features already produced (engagement metadata + centroid fit + signal counts). A scoring function over ClickHouse aggregates + a fit metric; no new model. | **Thin layer** (Phase 4). |
| **Crisis / sentiment alerts** | social-listening incumbents | robertuito polarity over comments + windowed materialized view in ClickHouse (`trend_signals`) → `trend.spike` event already in architecture (§3.3). Detectable **today** (P7). Adding *why* (topic of backlash) needs the §2 zero-shot classifier. | **Thin layer** (Phase 2/3); topic-of-crisis needs new checkpoint. |
| **Typed signal library w/ provenance** | Trigify (16+ signal types, LinkedIn/web) | Trigify operates on B2B web/LinkedIn; **nobody does typed signals over TikTok/IG audiovisual** (confirmed `research-features-gtm.md` §3a). Qualify's Phase-3 signals layer needs the §2 zero-shot classifier as the detection primitive + provenance columns (`signals.events`, already designed). | **New primitive** (the §2 checkpoint) on already-designed schema — this is the differentiated build. |
| **Ad-disclosure / brand-safety flags** | Kuli (brand safety) | rules + §2 zero-shot over transcript/caption (P6/P10). New checkpoint, existing pipeline shape. | **New checkpoint**, thin pipeline. |

**Bottom line for architect/PO:** every competitor AI feature is either (a) already covered by planned infra (lookalike, scoring, smart-reply, crisis alerts) or (b) unlocked by the *single* new primitive proposed in §2 (the zero-shot text classifier). No competitor feature in this set forces a new *visual* or *audio* model, new vector store, or new orchestrator. The zero-shot text classifier is the highest-leverage single addition — it turns Phase-3 typed-signals-over-audiovisual (the confirmed-empty competitive axis) from "not buildable with current stack" into "buildable."

---

## 4. Extensión del golden-set

`docs/arquitectura.md` §7 defines the golden set only for cascade quality: ~100 labeled real videos, per-stage metrics (filter precision/recall, ASR WER, VLM description quality, sentiment accuracy), thresholds calibrated against it. Adding a Phase-3 pain-point/topic **signal detector** (the §2 zero-shot classifier) extends it as follows.

**Labeled dataset shape (new).** The current golden set labels *cascade correctness* (is the frame relevant, is the transcript accurate). A signal detector needs a *second* label layer on the same videos — **multi-label** (a video can be burnout + algorithm-anxiety at once), per signal, at the fragment level:

```
video_id, fragment_id, fragment_type {caption|transcript|frame_ocr|comment},
  text, label_set {P1..P10 ∪ none}, annotator, annotator_agreement
```

Key design points, in golden-set style:
- **Reuse the same ~100 videos** — do not source a new corpus. Add the signal labels to the existing fixtures so cascade-quality and signal-quality are measured on one aligned set (provenance + comparability).
- **Class imbalance is the central problem.** Payment-delay (P4) and brand-deal-friction (P3) have very low base rates in public content. 100 videos may yield <5 positives → CI on recall is useless. Mitigation: **stratified/targeted augmentation** — deliberately scrape a *supplementary* labeled pool for the rare high-value signals (search "brand still hasn't paid", "#ad" complaints) so each signal has ≥30–50 positives for a stable metric. Keep this pool *separate* from the representative 100 so precision-in-the-wild isn't inflated.
- **Two annotators + agreement (Cohen's κ)** on a subset — topic/stance labels are more subjective than "is-frame-relevant"; report κ so threshold decisions rest on reliable labels.

**Per-stage metric (new).** Zero-shot is a scored classifier, so per signal:
- **Precision / recall / F1** at the chosen score threshold, **per signal label** (not micro-averaged — P4 and P7 have opposite cost profiles).
- **PR-AUC** per signal (threshold-independent), because thresholds will be tuned per signal.
- For the emotion refinement: accuracy/macro-F1 over the Ekman classes on the burnout/anxiety subset.

**Threshold calibration (new, mirrors cascade-discard calibration).** Each pain signal gets its **own** score cutoff, calibrated on the golden set to the cost profile of *that* signal:
- **P7 crisis / P4 payment-dispute** are high-value, low-base-rate → tune for **recall** (a missed crisis is worse than a false ping; downstream human review filters FPs). Pick the threshold at a target recall (e.g. 0.85) and report the precision you pay for it.
- **P5/P6 sponsorship/ad-disclosure** feed automated GTM actions → tune for **precision** (a false "open to collab" wastes outreach spend and reputation). Threshold at target precision (e.g. 0.90).
- Calibrate as a **cascade discard threshold too**: the zero-shot classifier only runs on fragments that survived F1/F2 (cost model §5), and its own score gates whether a `signals.events` row is emitted — so it's both a detector *and* a discard stage, calibrated the same way §3.4 calibrates F1/F2/F3.
- Record `detector_version` + threshold in the emitted signal (the hard provenance rule, §1.6 / §3.4) so a re-calibration is auditable.

**What does NOT change.** The cascade-stage metrics (filter P/R, WER, VLM quality, polarity accuracy) stay exactly as §7 specifies. The signal detector is an *additional* evaluated stage downstream of ASR/OCR, not a replacement — its input quality is bounded by WER (a bad transcript caps topic recall), so signal metrics should be reported **conditioned on** ASR quality to separate "detector is wrong" from "transcript was wrong."

---

## 5. Cost-per-video impact

Reasoning style mirrors `docs/modelos-multimodal-fase1.md`: the cascade exists to keep expensive stages off non-candidates, so a new stage's cost is judged by (a) how far down the cascade it runs and (b) its per-call cost relative to the VLM.

**Where it runs.** The zero-shot text classifier runs on *text that already exists* — caption (always), transcript (only if F1 produced one), top-N comments — and only on fragments that survived the cheap gates. It never runs on discarded content. So its volume ≈ the F3/VLM candidate volume, i.e. the already-narrowed ~10–20% of ingested posts.

**Per-call cost.** A 278–568M encoder classification pass is **1–2 orders of magnitude cheaper** than a Qwen3-VL / VLM generation and cheaper than a whisper pass. Zero-shot NLI does *k* forward passes for *k* candidate labels, but the labels batch and the input is short (caption ~30 tok, transcript ~300 tok, comments ~200 tok ≈ ~530 tok/video).

| Option | Model | Est. incremental cost / video* | Notes |
|---|---|---|---|
| Buy (HF Inference Providers) | `bge-m3-zeroshot-v2.0` (568M), ~8 labels | **~$0.0003–0.001** | hf-inference live; small-encoder classification is the cheapest tier. Exact rate needs live confirmation (HF pricing changes; not verifiable from the model card alone). |
| Buy, cheaper | `mDeBERTa-...-2mil7` (278M) | **~$0.0002–0.0006** | ~½ params → ~½ cost; slight quality trade. |
| Self-host (Phase 3, own GPU/CPU) | either | **≈ marginal $0** | Runs on the CPU workers alongside robertuito (both are small encoders); no GPU needed. This is the steady-state target. |
| Emotion refinement | `robertuito-emotion-analysis` | **≈ marginal $0** | Local CPU, same box as sentiment; adds one more short forward pass. |

\* Estimate, not a quoted rate. The load-bearing point is **relative magnitude**, not the absolute cents: at ~$0.0002–0.001/video the classifier is **<5% of the cascade's per-video cost**, which is dominated by the VLM (F3) and ASR (F1). Adding pain-point/topic detection does **not** materially move the per-video economics of the cascade. If self-hosted on the existing CPU worker (the eventual state), incremental cost is effectively storage/compute noise.

**Implication.** Cost is not a reason to defer this capability. The decision is purely product-scope (is Phase-3 pain-point signal detection in the roadmap now) and eval-readiness (do we have the labeled golden-set extension from §4), not budget.

---

## 6. Contradiction report (sent to architect)

Items that touch or require updating `docs/modelos-multimodal-fase1.md`'s current choices. **None of these change the four committed F1/F2/F3/sentiment checkpoints** — they are *additions* for a future Phase-3 signals layer.

1. **`modelos-multimodal-fase1.md` frames sentiment as "confirmed, no changes" (robertuito polarity).** True for *sentiment*, but that section implicitly treats "text understanding = 3-class polarity." For creator pain-point detection (P1–P6, P8–P10) polarity is **insufficient** — it cannot separate topics or localize stance. If pain-point/topic signals become in-scope (Phase 3), the doc's model list needs a new **text zero-shot classifier** row (`MoritzLaurer/bge-m3-zeroshot-v2.0`, MIT, hf-inference live). *Not a contradiction of the sentiment choice — a scope gap in the doc's model coverage.*

2. **Latent license question on pysentimiento, relevant to ADR 13.** The Hub declares no license for `pysentimiento/robertuito-*`. ADR 13 (`arquitectura.md`) rejects non-commercial embedding models on commercial-product grounds. The same test should be applied to the already-committed `robertuito-sentiment-analysis` (and the proposed emotion model). Inherited risk, not new — but currently unverified in either doc.

3. **Synergy worth recording, not a contradiction.** The recommended zero-shot classifier (`bge-m3-zeroshot-v2.0`) shares its base model with `BAAI/bge-m3`, already proposed for lookalike/RAG embeddings in `arquitectura.md` §4/§8.1. One model family serves both the Phase-3 signal classifier and the Phase-4 embedding path — a checkpoint-consolidation opportunity for whoever finalizes the model list.

**Sent to architect:** 2026-07-18 (verified-checkpoint list + Phase-3 detector proposal + this contradiction summary) via SendMessage.

---

## Provenance

- Checkpoint facts verified live via `hf-mcp hub_repo_details`, **check-date 2026-07-18**: `MoritzLaurer/bge-m3-zeroshot-v2.0`, `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`, `pysentimiento/robertuito-emotion-analysis`, `pysentimiento/robertuito-sentiment-analysis`, `pysentimiento/robertuito-irony`.
- Architecture references: `docs/arquitectura.md` §3.3, §3.4, §3.5, §4, §6 (ADR 9–13), §7, §8.1; `docs/modelos-multimodal-fase1.md`; `docs/research-features-gtm.md`; `packages/models/src/qualify_models/providers.py`.
- Cascade code inspected: `packages/models/src/qualify_models/providers.py` (Provider protocol, swap points).
</content>
</invoke>
