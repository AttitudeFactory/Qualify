# ManyChat's AI layer: what it actually requires, and what survives the owned→earned transfer

**Owner:** datasci (FDE) · **Date:** 2026-07-23 · **Session:** /team-research (ManyChat reverse-engineering)
**Scope (D1–D6):** teardown of ManyChat's AI features at the *model-capability* level; feasibility
against Qualify's committed cascade; eval design for RAG smart replies; a parametric cost model per
conversation; live Hub verification of every checkpoint named.

**Precedents this builds on (reuse, not redo):**
- `NOTES_pain_signal_feasibility.md` (2026-07-18) — 3-class polarity cannot carry topic/intent;
  `MoritzLaurer/bge-m3-zeroshot-v2.0` proposed as the Fase 3 detection primitive.
- `NOTES_fase0_agentive_layer.md` (2026-07-21) — owned-vs-earned reuse limits; generative-eval
  methodology (§5.2); `eval/fase0_cost.py` cost-model discipline (unverified rate → `None`).

---

## 0. Headline findings

1. **ManyChat's entire trigger surface is a classifier, not an LLM.** "Intention Recognition" asks the
   operator to write a hypothesis in the shape *"User is asking about the delivery"* — that is
   verbatim an **NLI hypothesis template**, and the whole feature is zero-shot text classification
   with a natural-language label. This is independent commercial validation that a ~500M-param NLI
   cross-encoder is production-adequate for intent triggering at consumer scale. It **strengthens**
   the P3-0 proposal (`MoritzLaurer/bge-m3-zeroshot-v2.0`) and **widens its scope**: proposed as an
   analytics *signal detector*, the same primitive is also an *activation trigger*. See §1, §2.1.
2. **ManyChat's AI layer is a cost cascade, and it has to be.** Their own FAQ describes the routing:
   deterministic automations first → a cheap "is this an AI scenario" gate → generation only after.
   §4 shows why: at their **published** per-contact economics ($0.0056–0.056 revenue per contact
   per month, verified 2026-07-23), three turns of grounded frontier-model generation is
   **underwater at the top tier**. The cascade is not an optimization, it is what makes the price
   point exist. Direct external validation of Qualify's §3.4 cascade principle.
3. **The classifier transfers to earned media; the actuator does not — and the reason is base rate.**
   The same classifier that is useful on inbound DMs (prior ≈ 10%) yields **~8% precision** on
   public comments (prior ≈ 0.5%). Reaching 50% precision needs a **~12× lower false-positive rate**
   at equal recall. Meanwhile the cost of a false positive **inverts**: private mildly-wrong reply →
   public brand reply to a stranger under a third party's video. **Auto-reply on earned media is
   statistically unshippable.** The same output ranked into a human-triaged queue is shippable,
   because a human actuator collapses the precision requirement. See §2.2 — this kills the most
   attractive feature to copy.
4. **ManyChat auto-generates replies only for *positive* comments.** That is not a product gap, it is
   risk management disguised as a feature: positive is the one polarity class where a wrong
   auto-reply is cheap. A platform that **owns the thread and the account** still restricts
   generation to the safest class. Qualify, with worse priors and public actuation, cannot justify
   being *less* conservative than that.
5. **The one committed Qualify model that maps directly onto a ManyChat AI feature is robertuito** —
   3-class polarity is exactly and sufficiently what "AI Comments" needs. It is also the *only* one.
   Nothing in the committed cascade does intent, slots, retrieval, or generation. Same gap as
   `NOTES_pain_signal_feasibility.md`, now confirmed from a second direction.
6. **ManyChat's RAG grounds on first-party asserted facts; Qualify's would ground on third-party
   observed content.** That is a different eval problem (you cannot warrant a stranger's claim) and
   it changes the golden set — see §3.

---

## 1. D1 — Teardown of ManyChat's AI features by required model capability

All rows from the ManyChat help center, **accessed 2026-07-23**. The question asked of each feature
is not "what does the UI do" but **"what is the smallest model class that produces this behavior"** —
which is what separates a genuine LLM requirement from keyword matching with a nicer UI.

| # | Feature | What it does (per docs) | Smallest sufficient model capability | LLM required? |
|---|---|---|---|---|
| A1 | **Keyword trigger** (baseline) | Literal word/phrase match on an inbound message | String matching | **No** |
| A2 | **Intention Recognition** | Trigger option *"Recognize the intention of the message"* instead of *"detect specific words"*. Operator writes a free-text intent using the prescribed formula **USER + verb + ABOUT + ITEM** (*"User ASKS about the DELIVERY"*) | **Zero-shot text classification against a natural-language hypothesis (NLI)**. One premise (the message) × k hypotheses (the configured intents) → entailment scores → argmax over threshold | **No** — an NLI cross-encoder is sufficient. See §1.1 |
| A3 | **AI Step** | Operator sets a *goal* + *context*; ManyChat generates *tasks*; the step runs a multi-turn exchange and can **save the user's reply into a System or Custom Field** | **Goal-conditioned multi-turn dialogue + slot filling into a typed schema.** State machine over an LLM; the field-write is structured extraction | **Yes** |
| A4 | **AI Replies** | Detects a question in DM/comment, answers from the **Knowledge** library; if it cannot answer, **assigns the conversation to a human** | Four separable capabilities: (a) question detection = binary classification; (b) retrieval over a corpus; (c) grounded generation; (d) **abstention** → handoff | **Yes for (c) only.** (a) and (d) are classifiers |
| A5 | **AI Comments** | Detects a **positive** comment on your post/reel and replies "in your tone". Tone is learned by **analyzing your existing comment replies** and generating five samples for approval | (a) **3-class polarity** — nothing more; (b) short style-conditioned generation. Tone = few-shot exemplar extraction from the operator's own history, **not fine-tuning** | (a) **No.** (b) yes, but tiny |
| A6 | **AI Goals** | After a reply, steers toward one of three fixed objectives: *Share a link*, *Grow followers*, *Capture leads*. Up to 3 simultaneous, drag-ordered by priority | Dialogue **policy over a fixed goal set** + slot filling (Capture leads writes to user fields). *Grow followers* "checks if a user is following you" — that is a **platform API call**, not a model | **Partly** — mostly orchestration over a 3-item action space |
| A7 | **AI Knowledge** | Corpus building: **Link** (scans *the exact page only*, **text only**, one entry per page), **Text** (≤250k chars/entry), File (coming soon) | Ingest → chunk → embed → index. **No crawler, no multimodal, no freshness loop** | **No** |
| A8 | **Flow Builder assistant** | Suggests automation ideas | LLM config/text generation | Yes, thin wrapper |
| A9 | **Text Improver** | Rewrites messages to brand voice | LLM rewriting | Yes, thin wrapper |
| A10 | **Routing layer** (from the FAQ, not a UI feature) | *"the system first checks if any other automation can handle it. If no existing automation responds, the message is passed to the AI… the AI decides whether it is an AI scenario… If it's not any of the live AI scenarios, the default reply works"* | **A cascade with a cheap gate before an expensive stage** | — (architecture) |

Operational facts worth recording, same source and date:

- **Channel gating.** Intention Recognition + AI Step: Instagram, Messenger, WhatsApp, Telegram. The
  newer **AI Replies / AI Comments / AI Goals are Instagram-only and explicitly in beta**.
- **Conversation state has a TTL:** *"the AI will stop waiting for the contact's reply after 10 hours."*
- **AI Comments does not work on Stories or Lives** — Reels and Posts only.
- **Language handling is implicit**: AI auto-detects the contact's language; the docs concede it
  *"might misinterpret the language"* on very short messages or similar languages. Relevant to
  Qualify: comments are *systematically* short, so this is the failure regime, not the edge case.
- **No AI metering.** The pricing page exposes **no AI credits, no per-call AI charge**: AI is a plan
  entitlement (Pro and above). The billing unit is the **Active Contact** — a person per month,
  regardless of message count. This matters for §4 and it means there is **no published per-AI-call
  rate to reverse-engineer** — so none is invented.

### 1.1 The load-bearing observation: Intention Recognition is NLI, and ManyChat says so without saying so

Three independent tells in ManyChat's own guidance, all of which are the known behavior of a
zero-shot NLI classifier rather than of an LLM prompt:

1. **The prompt formula is a hypothesis template.** *USER + verb + ABOUT + ITEM* → *"User is asking
   about shipping options"*. This is exactly the `hypothesis_template` argument of the
   `zero-shot-classification` pipeline. An LLM-based router would not need the operator to phrase the
   label as a declarative sentence about a third person.
2. **"One topic, one keyword. Avoid overlap. Distinct definitions."** Label-space interference is the
   characteristic failure of independent per-label entailment scoring with correlated labels. An LLM
   asked to route among options handles overlap by reasoning; a cross-encoder cannot, so the docs
   push the problem onto the operator.
3. **"The narrower the focus of your intention, the higher the accuracy"**, with the worked example
   of splitting *"store hours"* into per-city labels. That is threshold/separability advice for a
   scored classifier, not prompt advice for a generator.

**Why this is the most valuable line in the teardown:** the feature that fires *every* automation in
ManyChat — the entry point to the whole product — costs a single small-encoder forward pass per
candidate label, not an LLM call. That is what allows the routing cascade in A10 to sit in front of
every inbound message at a price point of roughly one cent per contact per month (§4).

---

## 2. D2 — Feasibility against Qualify's committed models

### 2.1 Direct mapping onto the committed cascade

Committed stack under test (`docs/modelos-multimodal-fase1.md`, as implemented in
`packages/models`): siglip2 filter · Qwen3-VL-4B vision · whisper-large-v3-turbo ASR ·
robertuito 3-class sentiment.

| ManyChat capability | Served by a committed Qualify model? | Verdict |
|---|---|---|
| A5 positive-comment detection | **Yes — `pysentimiento/robertuito-sentiment-analysis`, exactly.** 3-class polarity over Spanish social text is precisely the required capability, no more | **The only clean match in the entire teardown.** Already implemented in `sentiment.py` |
| A2 intent trigger | **No.** Polarity cannot separate *"asking about delivery"* from *"asking about returns"* — both are NEU | Gap → §2.3 |
| A4(a) question detection | **No.** Not a polarity axis at all | Gap → §2.3 |
| A3/A6 slot filling into typed fields | **No.** Nothing in the cascade extracts entities | Gap; needs an LLM |
| A4(b) retrieval | **No.** No embedding model is committed in Fase 1 (`BAAI/bge-m3` is *proposed*, `arquitectura.md` §4/§8.1) | Gap, already-designed shape |
| A4(c)/A5(b)/A9 generation | **No, and correctly so** — generation belongs to the LangGraph orchestrator (`arquitectura.md` §3.5), not the cascade | Not a cascade concern |

This reproduces `NOTES_pain_signal_feasibility.md`'s central finding from an entirely independent
direction: **the committed stack has exactly one text-understanding head, and it is 3-class polarity.**
Two separate investigations, two different feature sets, same single gap.

### 2.2 The owned→earned transfer test, done quantitatively

This is where an attractive feature dies. The attractive feature is obvious: *ManyChat auto-replies
to comments; Qualify sees comments about your brand across all of TikTok/IG, so Qualify should
auto-reply to those.* It does not survive.

**The classifier is the same. The prior is not.** ManyChat classifies messages **a person
deliberately addressed to the brand's own account** — an inbound DM or a comment on the brand's own
post. The prior that such a message carries a business intent is high. Qualify classifies **public
comments on arbitrary third-party videos**, addressed to no one in particular, about anything.

Take a classifier with TPR 0.85 / FPR 0.05 — a reasonable zero-shot NLI operating point — and apply
Bayes to both planes:

| Plane | Prior of the target intent | Precision at TPR 0.85 / FPR 0.05 | False positives per true positive |
|---|---|---|---|
| ManyChat (inbound DM to own account) | ~10% | **65%** | 0.5 |
| ManyChat, pessimistic | ~5% | **47%** | 1.1 |
| Qualify (public comment, earned) | **~0.5%** | **7.9%** | **11.6** |
| Qualify, optimistic | 2% | 25.8% | 2.9 |

(Precision = TPR·π / (TPR·π + FPR·(1−π)); the 0.5% figure is a stated modelling assumption, not a
measurement — most comments on a public video are emoji, tags, and banter. It is the *ratio between
rows*, not the absolute, that carries the argument.)

**To reach 50% precision at π=0.005 you need FPR ≤ 0.0043 — a ~12× reduction in false-positive rate
at unchanged recall.** No threshold move gets you that for free: raising the score cutoff buys
specificity by giving up recall, and at these priors the trade is steep.

**And the cost of a false positive inverts across the two planes.** In ManyChat, a wrong auto-reply
is a private, mildly-off message in a thread the contact opened; the contact rephrases and moves on.
In Qualify, the same error is a **brand replying publicly, to a stranger, under someone else's
video**. That is a reputational event, it is visible to everyone who watches the video, and at volume
it is precisely what platforms classify as spam. The error is not merely more expensive — it is a
different kind of object.

**Verdict — the feature splits in two:**

- **NO-GO: automated public reply/DM to earned-media authors.** Statistically unshippable. The base
  rate makes the required precision unreachable and the failure mode is public and reputational.
  Note this is a *model* verdict and it is independent of platform-API gating (which is gtm's G2 and
  architect's A2 slice) — even with a perfect API it would not ship.
- **GO: the same classifier as a ranked triage queue.** Emit the intent score into `signals.events`
  with provenance and rank a human-reviewed queue. **A human actuator collapses the precision
  requirement**: at 8% precision a reviewer discards 12 rows to find 1 useful lead, which is a
  perfectly ordinary conversion rate for a prospecting queue and vastly better than reading every
  comment. The identical model output is worthless as an actuator and valuable as a prioritizer.
  Phase 3 (`signals.events`, typed signals) → Phase 4/5 (queue → play).

**Precedent applied:** this is the same class of argument as `NOTES_fase0_agentive_layer.md` §3.2
(n=20–200 posts → ~1.5 spurious "significant" findings by chance). There the killer was sample size;
here it is base rate. Both are cases where the model is fine and the **statistics of the deployment
setting** are what make the feature unshippable.

**Corroborating evidence from ManyChat itself:** A5 generates replies **only for positive comments**.
An operator who owns the account, owns the post, and owns the thread still confines auto-generation
to the polarity class where being wrong is cheap. Any Qualify design that auto-generates on earned
media would be taking strictly more risk than the incumbent does with strictly better priors.

### 2.3 Does this strengthen, weaken, or change the `bge-m3-zeroshot-v2.0` proposal (P3-0)?

**Strengthens it, and widens its scope. No change to the checkpoint recommendation.**

- **Strengthens.** The proposal previously rested on an internal argument (polarity cannot carry
  topic). The teardown adds **external evidence from a shipping product at consumer scale**: the
  entry point to ManyChat's whole automation surface is an NLI-shaped zero-shot classifier with
  operator-authored natural-language labels, and ManyChat's own best-practice guidance exhibits the
  characteristic failure modes of that model class (§1.1). The architectural bet — *intent triggering
  does not require an LLM per message* — is being made in production by someone else.
- **Widens the scope.** P3-0 framed the checkpoint as a **signal detector** feeding
  `signals.events` (analytics). The teardown shows the same primitive is also the **trigger** of an
  activation surface (A2). One checkpoint, two roles, no new infra. Worth recording, because it
  changes the ROI of the same spend.
- **Transfers a design constraint for free.** ManyChat's label-authoring rules — one topic per
  intent, no overlapping labels, narrower is more accurate — are exactly the constraints Qualify's
  typed-signal library must impose on its own label set. That is a **product-design requirement
  derived from the model class**, and it should land in P3-1's spec: signal labels are not free-form,
  they are a curated, non-overlapping, narrow-scoped taxonomy, versioned as `detector_version`.
- **Does not weaken.** Nothing in the teardown suggests an LLM is needed for the classification job.
  The LLM requirements in ManyChat sit in generation and slot filling (A3/A4c/A6), which in Qualify's
  architecture already belong to the LangGraph orchestrator (Phase 5), not to the cascade.

**One caveat the teardown adds that P3-0 did not have.** ManyChat concedes language
mis-identification on **very short messages**. Comments are short by construction — median public
comment length is far below a DM. Two consequences for the eval (§3, and the §4 golden-set extension
in `NOTES_pain_signal_feasibility.md`): (a) report intent metrics **stratified by fragment length**,
because a headline F1 will hide a collapse on the shortest bucket, which is also the largest bucket;
(b) length is a candidate **cheap pre-gate** — discarding sub-N-token comments before the classifier
may cost near-zero recall of real signals and remove a large share of the false-positive mass, which
is a direct, measurable attack on the 12× FPR problem in §2.2. Both are testable on the existing
golden set and cost nothing to add.

## 3. D3 — Evaluation design for RAG smart replies

RAG smart replies are a **committed** Qualify feature (`README.md`, Fase 5). This section designs
their evaluation as an **extension of `packages/models/src/qualify_models/eval/`**, not a parallel
harness — the existing `harness.py` already injects `runner` and `revision_resolver` and already pins
manifest identity + SHA256 + per-stage checkpoint/revision on every report, which is exactly the
provenance discipline generative eval needs and the part teams usually get wrong.

### 3.1 What is actually being evaluated: three decisions, not one

The teardown's A4 decomposition is the eval design. A "smart reply" is not one judgement call, it is
a pipeline of three separately-measurable decisions, and **two of the three are classifiers that the
existing metrics code already handles**:

| # | Decision | Question | Metric family | New code? |
|---|---|---|---|---|
| S1 | **Gate** — is this fragment worth replying to at all? | binary classification | precision / recall / F1 | **No** — `metrics.filter_metrics()` verbatim |
| S2 | **Retrieve** — did the right evidence come back? | ranked retrieval | recall@k, MRR | Yes, small |
| S3a | **Abstain** — should we decline (no grounded answer exists)? | binary classification | precision / recall / F1 | **No** — `filter_metrics()` again |
| S3b | **Generate** — is the reply compliant, grounded, and better than baseline? | generation quality | compliance rate, groundedness, pairwise win-rate | Yes |

Framing it this way is the single highest-leverage decision in the design: it converts most of a
"there is no ground truth for generation" problem into **three ordinary supervised problems plus one
residual**. It also means a failure is attributable — a bad reply caused by S2 retrieving the wrong
chunk is a retrieval bug, not a prompt bug, and a headline "reply quality" score would hide that.

### 3.2 Golden-set shape

Extends `eval/schema.py`. `GoldenItem` describes a *video*; a reply item describes a
*fragment + query*, so it is a sibling model in the same module loaded by the same JSONL loader
(same `# manifest_version:` directive, same SHA256 hashing, same portable relative-path resolution):

```
reply_item_id, source_post_id, fragment_id, fragment_type {comment|caption|transcript},
  query_text, language,
  answerable: bool,                    # ground truth for the abstention decision (S3a)
  gold_chunk_ids: list[str],           # ground truth for retrieval (S2)
  reference_reply: str | None,         # optional human-written reply, baseline for S3b
  gate_relevant: bool,                 # ground truth for S1
  labeler, labeled_at, annotator_agreement
```

Four design points, each load-bearing:

- **Unanswerable items are mandatory, and a large minority — propose ≥30%.** ManyChat surfaces this
  exact case in its Playground (*"Once the AI encounters a question not mentioned in any of the
  Knowledge entries, it will suggest you add this information"*, accessed 2026-07-23). Their product
  answer is a UI nudge; the **eval** answer is that abstention is a first-class measured outcome. A
  golden set with only answerable items cannot distinguish a well-grounded system from one that
  never refuses, and never-refusing is precisely the failure that ships hallucinations.
- **Reuse the same source videos as the cascade golden set.** Same argument as
  `NOTES_pain_signal_feasibility.md` §4: one aligned corpus so reply quality can be **conditioned on**
  upstream quality. A reply grounded in a transcript with high WER is wrong for a reason that is not
  the reply model's fault, and the report must be able to say so.
- **The gate set must be stratified, and its precision re-weighted back to the natural prior.**
  This follows directly from §2.2 and it is the number that decides whether the eval is honest. At a
  natural positive rate of ~0.5%, estimating recall to ±0.10 needs ~90 positives, i.e. **~18,000
  naturally-sampled comments to label**. That is not happening. So positives get over-sampled — and
  then **reported precision is inflated by construction** unless it is corrected back to the
  deployment prior. Keep the enriched pool physically separate from a small representative sample,
  report recall from the enriched pool and precision re-weighted to the representative one, and state
  the assumed prior in the report. An uncorrected precision figure here would be the single most
  misleading number the project could produce.
- **Two annotators + Cohen's κ on a subset.** "Is this comment worth replying to" is more subjective
  than "is this frame relevant"; threshold decisions should not rest on unmeasured labels.

### 3.3 Metrics, layered — reusing `NOTES_fase0_agentive_layer.md` §5.2, plus the RAG-specific layer

The predecessor's five-layer methodology transfers wholesale. What is genuinely **new here is Layer 2**
(groundedness/retrieval), because Fase 0 evaluated *free* generation while this evaluates
*retrieval-grounded* generation:

- **Layer 0 — the gate (new, from the teardown).** S1/S3a as binary classification, computed with
  existing code. Cheapest and most decision-relevant layer; run it first.
- **Layer 1 — deterministic compliance.** Pass/fail, free, catches most production defects: platform
  character limits, no fabricated URLs or @handles, banned-term list, required disclosure, correct
  language. Report as a **compliance rate**. Build before touching any judge.
- **Layer 2 — retrieval + groundedness (new, RAG-specific).** Three numbers:
  `recall@k` against `gold_chunk_ids`; **attribution rate** = share of factual claims in the reply
  traceable to a retrieved chunk; **abstention correctness** on the unanswerable subset. The second
  is the anti-hallucination metric and the one that should gate any ship decision.
- **Layer 3 — pairwise preference, never absolute scoring.** A/B against `reference_reply` or the
  incumbent prompt; report **win-rate with a binomial CI**. Mandatory mitigations, both from the
  predecessor's §5.2 and both cheap: **run both presentation orders, keep only order-consistent
  verdicts, and report the flip rate**; judge with a **different model family** than the generator.
  Note the length-bias warning applies with extra force here — chat replies are short, and judges
  reward length, so an unmitigated judge will actively steer the product the wrong way.
- **Layer 4 — human accept / edit / reject inside the product.** The only real ground truth. Ship
  replies as **drafts a human approves**, log the three-way outcome plus the edit diff. This must be
  designed in from day one; it is a product decision, not an ML one. Given §2.2's NO-GO on automated
  public replies, Qualify's smart replies are **draft-first by necessity anyway** — which means the
  best available eval signal is free, and is a direct consequence of the safety constraint.

**Sizing.** To distinguish a 60% win-rate from 50% at 80% power (α=0.05) needs **~200 preference
pairs**. That is the number to plan the annotation budget around; anything much smaller produces a
win-rate whose CI spans the null and cannot gate a release.

### 3.4 Concrete harness extension points

Named against the files as they exist today, so this is a diff and not a memo:

| File | Change |
|---|---|
| `eval/schema.py` | add `ReplyGoldenItem` / `ReplyGoldenSet` + `load_reply_golden_set()`, mirroring `GoldenItem` and reusing the same manifest-version/SHA256 machinery |
| `eval/metrics.py` | add `retrieval_recall_at_k`, `groundedness_rate`, `compliance_rate`, `pairwise_win_rate` (with a binomial CI), `judge_flip_rate`, `cohens_kappa`. **`filter_metrics` is reused unchanged for S1 and S3a** |
| `providers.py` | add a `JudgeProvider` Protocol alongside `VisionProvider` / `TranscriptionProvider`; §3.3 *requires* swapping the judge to test family bias, so it must be a swap point, not a constant |
| `eval/harness.py` | add `evaluate_replies(golden_set, runner, judge, revision_resolver)` following the existing injectable-runner pattern so the suite stays offline by default |
| `EvalReport` | pin **generator model, judge model, prompt version, retrieval index version** exactly as it pins checkpoint + revision today. Two win-rates computed under different judges are not comparable, and nothing else in the report would reveal that |
| `eval/conversation_cost.py` | already written (§4) — attach a `ConversationEconomics` to the report the way `CostEstimate` attaches today |

Effort estimate: **~1–1.5 days**, consistent with the predecessor's ~1 day for generative eval, plus
the retrieval layer. The methodology transfers; the harness does not need rebuilding.

### 3.5 The earned-media hazard that ManyChat does not have

ManyChat's Knowledge library is **first-party asserted fact**: the brand's own page, the brand's own
copy, capped at 250k characters per entry, no crawler. If the AI repeats it and it is wrong, the
brand asserted it.

Qualify's retrieval corpus is `search.content_index` — **third-party observed content**: what
strangers said in comments and what a VLM/ASR pipeline *inferred* from video. Two consequences the
eval must carry and which have no ManyChat analogue:

1. **Groundedness is necessary but no longer sufficient.** A reply can be perfectly attributable to a
   retrieved chunk and still be false, because the chunk is a stranger's claim, or an ASR error, or a
   VLM hallucination. Layer 2's attribution rate must therefore be reported **alongside** upstream
   stage quality (WER, VLM description quality) rather than instead of it — this is the concrete
   reason for the "same corpus" constraint in §3.2.
2. **Attribution provenance must survive into the generated artifact.** The hard rule from
   `arquitectura.md` (every derived signal carries its source ids + `detector_version`) extends here:
   a drafted reply must carry the `source_id`s of the chunks it used, so a human approver in Layer 4
   can check the claim rather than trust it. This is also what makes Layer 4's edit-diff signal
   interpretable.

### 3.6 Falsifiable prior, stated in advance

So it can be wrong in public, in the style of `NOTES_fase0_agentive_layer.md` §3.2:

> **S1/S3a (the gate) will be the binding constraint, not generation quality.** I expect grounded
> reply generation on a *pre-qualified* fragment to reach acceptable compliance and groundedness
> without difficulty, and I expect the gate's precision at the natural prior to be the number that
> decides whether the feature ships. If a first eval run shows the reverse — a clean gate and poor
> generation — that is a real result and the effort should move to prompting/retrieval.

---

## 4. D4 — Parametric cost model per conversation

**Code:** `packages/models/src/qualify_models/eval/conversation_cost.py`
**Tests:** `packages/models/tests/test_conversation_cost.py` — 13 tests; full package run
**40 passed, 4 deselected**, `ruff check` + `ruff format` clean on both files (measured 2026-07-23).

### 4.1 Why the unit is a conversation and the denominator is a contact

Third sibling of `cost.py` ($/video, Fase 1 cascade) and `fase0_cost.py` ($/account/month, Fase 0).
The unit changes because the *billing* unit changes. ManyChat charges per **Active Contact** — "*a
real person you interact with during a monthly billing period… It doesn't matter how many messages
you exchange. One person = one Active Contact for the month*" (pricing FAQ, accessed 2026-07-23).

So the question that decides whether an activation product can exist is not "what does a message
cost" but **"does the AI spend triggered by one contact fit inside the revenue that contact
generates"**.

### 4.2 Verified anchors (the only rates in this model that are not caller inputs)

From https://manychat.com/pricing, **accessed 2026-07-23**, monthly billing. Hard-coded in
`MANYCHAT_PLANS` as a *sourced competitive anchor*, explicitly not as Qualify pricing:

| Plan | $/mo | Included contacts | Overage $/contact | **Revenue per contact** |
|---|---|---|---|---|
| Free | 0 | 25 | n/a | $0 |
| Essential | 14 | 250 | 0.10 | **$0.0560** |
| Pro | 29 | 2,500 | 0.05 | **$0.0116** |
| Business | 69 | 7,500 | 0.025 | **$0.0092** |
| Advanced | 139 | 25,000 | 0.004 | **$0.00556** |

**Note what this table does.** Revenue per contact *falls 10× as the plan gets more expensive*,
because included contacts grow faster than price. The AI budget per conversation is therefore
**tightest on the biggest customers** — the exact inversion `fase0_cost.py` found for per-account
pricing, reproduced here for per-contact pricing and pinned by
`test_revenue_per_contact_falls_as_plan_price_rises`. Any activation feature validated on the entry
tier will be validated in the one place it is cheapest to run.

**Also note what is absent: there is no AI metering.** No credits, no per-call AI charge — AI is a
plan entitlement from Pro up. So no per-AI-call rate can be reverse-engineered from ManyChat, and
none is invented here.

### 4.3 Computed results (generation-only lower bounds)

One conversation = 3 grounded reply turns, 3 retrieved chunks/turn. Token shape ~1,600 in / 120 out
per turn — an **engineering estimate, not a traced measurement**, and the assumption most worth
challenging. Classification and retrieval are excluded because their rates are unsourced (§4.4), so
**every figure below is a lower bound**:

| Plan | Rev/contact | Haiku 4.5: cost | share | Sonnet 5: cost | share | Max % of contacts that may reach the LLM (Haiku, 20% budget) |
|---|---|---|---|---|---|---|
| Essential | $0.05600 | $0.00660 | 11.8% | $0.01980 | 35.4% | **100%** |
| Pro | $0.01160 | $0.00660 | **56.9%** | $0.01980 | 170.7% | **35.2%** |
| Business | $0.00920 | $0.00660 | **71.7%** | $0.01980 | 215.2% | **27.9%** |
| Advanced | $0.00556 | $0.00660 | **118.7%** | $0.01980 | 356.1% | **16.8%** |

Per-turn unit cost: Haiku $0.0022 · Sonnet $0.0066 · Opus $0.0110.

**The headline, pinned as `test_top_tier_underwater_on_generation_alone`:** at the published Advanced
tier, a three-turn grounded conversation on the **cheapest** frontier model already costs **119% of
what the contact earns** — before classification, retrieval, infra, support, or margin. On Sonnet it
is 356%.

**Therefore the cascade is not an optimization, it is the thing that makes the price point exist.**
`breakeven_generation_rate()` states it as a discard threshold in dollars: under the inherited 20%
AI-spend tripwire, **at most ~17% of Advanced-tier contacts may reach the generative stage**
(~35% at Pro; ~7% at Pro on Opus). This is the quantitative explanation of the routing behavior
ManyChat documents in its own FAQ — deterministic automations first, then a cheap "is this an AI
scenario" gate, then generation. **They must gate, or the plan loses money.**

This is direct external validation of Qualify's own §3.4 cascade principle, arriving from an
unrelated product with an unrelated data plane, and it is the strongest architectural evidence in
this teardown.

### 4.4 What stays `None`, and why

Both are required caller inputs with no default; `estimate_conversation` returns
`total_ai_usd_per_conversation = None` when either is missing rather than reporting a partial total
(pinned by `test_unpriced_stages_yield_no_total`):

- **`intent_usd_per_label_call`** — no hosted zero-shot-classification per-call rate is sourced
  anywhere in this repo. `NOTES_pain_signal_feasibility.md` §5 established only *relative* magnitude
  (1–2 orders of magnitude below a VLM pass) and explicitly declined to quote an absolute. Pass `0.0`
  when the classifier is self-hosted on the existing CPU worker — which is the intended steady state.
- **`retrieval_usd_per_query`** — no hosted embedding rate is sourced. Same treatment.

Unchanged open item, inherited and still unclosed across three sessions: **no hosted per-minute ASR
rate exists anywhere in this repo** (`eval/README.md`, `fase0_cost.py` §4.6). Not needed for this
model, but it is the same unpaid bill.

### 4.5 What this means for Qualify's own billing design (Fase 5, P5-1)

**ManyChat's per-contact model works because its cost driver and its billing unit are the same
object.** Cost is incurred when you talk to a person; you are billed per person you talked to. They
move together, so the plan is safe by construction.

**Qualify's earned-media plane breaks that coupling.** Qualify's dominant cost is incurred
*ingesting and classifying content from strangers you will never contact* — scraping, ASR, VLM, and
the §2.2 triage queue that discards ~12 rows per useful one. That volume is driven by how much
conversation exists about a brand, which is **uncorrelated with the number of contacts the customer
ends up engaging**. A per-contact price would therefore be structurally wrong for Qualify: the
billing unit and the cost driver come apart.

This is the *same* failure mode `NOTES_fase0_agentive_layer.md` §3.3 identified for competitor
creative intelligence bundled into a per-account seat, now reaching the same conclusion from a
different direction — and it is an argument **for** the credit/metered model already designed for
Fase 5 (`billing.usage_events`, `docs/backlog-features-gtm.md` P5-1), plus a hard per-tenant quota.
**Recommendation to PO/architect: do not copy ManyChat's per-contact pricing shape. Copy its
cascade.**

## 5. D5 — Live Hub verification + contradiction report

### 5.1 Checkpoints re-verified live, 2026-07-23

Every checkpoint this note relies on, re-checked today via `hub_repo_details` against the live Hub —
not carried over on trust from the 2026-07-18/21 sessions:

| Checkpoint | Params | License (verified) | HF Inference Provider | Downloads | Role here |
|---|---|---|---|---|---|
| `MoritzLaurer/bge-m3-zeroshot-v2.0` | 567.8M (xlm-roberta) | **MIT** | **hf-inference (live)** | 3.5M | Intent trigger + signal detector (§2.3) |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | 278.8M (deberta-v2) | **MIT** | **hf-inference (live)** | 7.3M | Cheaper fallback; ES among 26 declared languages |
| `BAAI/bge-m3` | — (xlm-roberta) | **MIT** | **hf-inference (live)** | 235.4M | Retrieval for the RAG layer (§3) |
| `pysentimiento/robertuito-sentiment-analysis` | 108.8M (roberta) | **none declared** | **none listed** | 271.8M | The one committed model that maps 1:1 onto a ManyChat AI feature (§2.1) |

**No deltas** from the 2026-07-18 and 2026-07-21 verifications. All three MIT models remain live on
`hf-inference`, preserving the buy-first-then-self-host sequencing the rest of the stack uses.

### 5.2 Negative finding: no dedicated intent-classification checkpoint is usable

Searched the Hub for dedicated intent classifiers (2026-07-23, sorted by downloads). **Nothing
viable.** The entire top-15 is small, narrow, and wrong-shaped:

- `qanastek/XLMRoberta-Alexa-Intents-Classification` — the only multilingual entry with any traction
  (313 downloads, CC-BY-4.0). Trained on **MASSIVE**, i.e. a **fixed Alexa smart-assistant taxonomy**
  ("set an alarm", "play music"). Wrong domain, and a fixed label set is exactly the wrong shape when
  the whole point is operator-authored labels.
- The rest are English-only, single-domain (healthcare, Korean, Shona), quantized GGUF hobby
  fine-tunes, or non-commercial (`bespin-global/...` is **CC-BY-NC-4.0**).

**Conclusion:** the practical build is **zero-shot NLI with operator-authored hypotheses**, not a
bespoke or off-the-shelf intent model. This is the same shape of finding as
`NOTES_pain_signal_feasibility.md`'s "no dedicated FTC/ad-disclosure checkpoint exists" — and it is
independently corroborated by ManyChat, whose own UI (§1.1) forces operators to phrase intents as NLI
hypotheses. **`bge-m3-zeroshot-v2.0` stands as the recommendation; nothing on the Hub beats it for
this job.**

### 5.3 Contradiction report — for the architect, via the lead

Nothing here changes the four committed F1/F2/F3/sentiment checkpoints. Three items, in descending
order of urgency:

1. **STILL UNLANDED, and now two sessions old: `moondream/moondream3-preview` is BSL 1.1, not
   open-weight.** Verified 2026-07-21 (`NOTES_fase0_agentive_layer.md` §1.2) with the full
   `LICENSE.md` retrieved: Business Source License 1.1, licensor M87 Labs, 9.27B params (~18.5 GB),
   **no Inference Provider**, and never once run in this repo. Both `CLAUDE.md` and
   `docs/modelos-multimodal-fase1.md` still describe the vision stage as "open-weight" and still name
   moondream3 as the primary recommendation. `docs/modelos-multimodal-fase1.md` was updated on
   2026-07-18 to say the license is `other` — but "other" understates it: BSL carries an explicit
   anti-compete Additional Use Grant and a Change Date, which is a materially different object from
   an unlabelled licence. **The honest current state is that `Qwen/Qwen3-VL-4B-Instruct` is the
   de-facto vision checkpoint.** Re-raising because a correction that survives two sessions unlanded
   is a doc that will mislead whoever reads it next.
2. **`docs/modelos-multimodal-fase1.md`'s zero-shot section is scoped too narrowly.** It records
   `bge-m3-zeroshot-v2.0` as a Fase 3 *signal-detection* primitive. This teardown shows the same
   checkpoint is also the natural *activation trigger* primitive (§2.3) — one checkpoint, two roles
   across two phases. Not a contradiction; a scope widening that improves the ROI case for a
   checkpoint that is currently "propuesto, no lockeado".
3. **The pysentimiento licence question is now load-bearing, not latent.** Re-verified today: the Hub
   still declares **no licence** for `robertuito-sentiment-analysis`. §2.1 shows this is the **only**
   committed Qualify model that maps directly onto a shipping competitor AI feature — i.e. the most
   likely component to reach production first. ADR 13 rejected CC-BY-NC embedding models on
   commercial grounds; the same test has still never been applied to the sentiment model actually in
   the code. Inherited risk, flagged for the third session running, still unresolved.

**Phase mapping of every recommendation in this note** (per session rule 3):

| Finding | Phase | Decision it informs |
|---|---|---|
| Intent trigger = zero-shot NLI, not an LLM (§1.1, §2.3) | **Phase 3** | P3-0 checkpoint commitment; P3-1 signal-label taxonomy design |
| Non-overlapping, narrow, versioned label taxonomy (§2.3) | **Phase 3** | P3-1 spec requirement |
| Length-stratified metrics + short-comment pre-gate (§2.3) | **Phase 3** | Golden-set extension; cascade discard calibration |
| **NO-GO on automated public replies to earned media** (§2.2) | **Phase 5** | Kills a candidate "play"; forces draft-first |
| **GO on intent score → human-triaged ranked queue** (§2.2) | **Phase 3 → 4/5** | `signals.events` consumer; queue UX |
| RAG smart-reply eval design + harness diff (§3) | **Phase 5** | Gate before any smart-reply ships |
| Draft-first ⇒ free accept/edit/reject eval signal (§3.3 Layer 4) | **Phase 5** | Product-design requirement, day one |
| Cascade gate is a pricing necessity (§4.3) | **Phase 1/5** | Validates §3.4 cascade; sets discard-threshold economics |
| Do **not** copy per-contact pricing; use credits (§4.5) | **Phase 5** | P5-1 `billing.usage_events` billing-unit choice |

---

## Provenance

**ManyChat sources — all accessed 2026-07-23**, read via authenticated browser session
(`help.manychat.com` returns HTTP 403 to plain fetches, so page text was extracted in-browser):

- AI Step — https://help.manychat.com/hc/en-us/articles/14281187288860-Manychat-AI-Step
- Manychat AI overview / routing FAQ / Knowledge —
  https://help.manychat.com/hc/en-us/articles/14281227789468-Power-up-your-chat-marketing-with-Manychat-AI
- AI Replies — https://help.manychat.com/hc/en-us/articles/23018283889180-Manychat-AI-Replies
- AI Comments — https://help.manychat.com/hc/en-us/articles/23096278263836-Manychat-AI-Comments
- AI Goals — https://help.manychat.com/hc/en-us/articles/23096273858716-Manychat-AI-Goals
- Intention Recognition —
  https://help.manychat.com/hc/en-us/articles/14281187229468-Manychat-AI-Intention-Recognition
- Section index (feature roster) —
  https://help.manychat.com/hc/en-us/sections/14281203243164-Manychat-AI
- Pricing + Active Contact definition — https://manychat.com/pricing

**Hub facts verified live via `hub_repo_details` / `hub_repo_search`, check-date 2026-07-23:**
`MoritzLaurer/bge-m3-zeroshot-v2.0`, `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`,
`BAAI/bge-m3`, `pysentimiento/robertuito-sentiment-analysis`, plus a downloads-sorted search of
dedicated intent-classification models (§5.2).

**Code written this session:** `src/qualify_models/eval/conversation_cost.py`,
`tests/test_conversation_cost.py`.
**Runtime facts measured this session** (`packages/models`, macOS, `uv run`): full suite
**40 passed, 4 deselected** in 12.4 s with zero network; `ruff check` and `ruff format --check` clean
on both new files. Pre-existing, **not mine and not touched**: `ruff check src tests` reports 4
`UP042` findings in `src/qualify_models/oauth_scope.py` (`str, Enum` → `StrEnum`) — a one-line-each
fix for whoever owns that file next.

**All §4 cost figures** are computed by `conversation_cost.py` with `intent_usd_per_label_call` and
`retrieval_usd_per_query` unset ⇒ **generation-only lower bounds**. Anthropic list prices are
inherited from `fase0_cost.TOKEN_RATES_USD_PER_MTOK`, cached 2026-06-24; re-verify before quoting
externally.

**Repo references (read, not edited — `docs/` belongs to architect/gtm):**
`docs/modelos-multimodal-fase1.md`; `docs/arquitectura.md` §3.4, §3.5, §7 (by citation);
`CLAUDE.md` phase map; `packages/models/NOTES_pain_signal_feasibility.md`;
`packages/models/NOTES_fase0_agentive_layer.md`;
`packages/models/src/qualify_models/{providers.py,eval/*.py}`;
`.claude/research-sessions/2026-07-23-manychat.md`.
