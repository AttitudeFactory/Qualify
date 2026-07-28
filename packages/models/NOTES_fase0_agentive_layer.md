# Fase 0 (publishing API): what `packages/models` is worth, and where AI actually differentiates

**Owner:** datasci (FDE) · **Date:** 2026-07-21 · **Session:** /team-research (respawn)
**Scope:** Assess `packages/models` under the proposed Fase 0 pivot (ADR 19, PROPUESTO): what survives a Fase 1 pause, what actually rots, where ML genuinely differentiates a social publishing/scheduling API, whether the multimodal cascade composes with owned-content analysis, and how to evaluate generative output with no ground truth.

**Precedent:** follows `NOTES_pain_signal_feasibility.md` (2026-07-18). Same rules: every checkpoint claim verified live against the HF Hub; no rate is invented.

**Headline findings, up front:**

1. **The architect's "`packages/models` does not rot" claim is half right and the half that is wrong is the load-bearing half.** Weights and golden sets are stable — true. But rot in this package was never going to come from the weights: it comes from the *runtime surface* (transformers version, Inference Provider roster, provider account entitlements), and **two of those three drift vectors have already broken this package during its three-day active life**, both documented in `providers.py` docstrings. The architect's *conclusion* (pausing `models` is cheaper than pausing `scraper`) survives; its *premise* does not. Mitigation is cheap and half-built — see §1.
2. **`moondream/moondream3-preview`, the doc-committed vision checkpoint, is not what the docs think it is.** Verified live 2026-07-21: it is **BSL 1.1, not open-weight**; **9.27B params** (~18.5 GB), not a small model; has **no HF Inference Provider**, so the "buy hosted first" path does not exist for it; and it has **never been downloaded or run in this repo** (16 KB cached = refs only). This is a Fase 1 problem that the pause would freeze in place, not solve.
3. **Fase 0 is a plumbing and OAuth product.** On the write side, every AI feature is a thin wrapper. The only genuine ML surface is comment/DM triage — i.e. the *reading* half, which is the half that resembles Qualify's actual thesis. Saying so is the finding; see §2.
4. **"Why did this post work" cannot be answered for a single account, and shipping it would be worse than shipping nothing.** n≈20–200 posts, heavy-tailed engagement, no control, dozens of candidate features. The descriptive version is honest and cheap ($1.78 to backfill a 200-video library). The causal version is a confident-sounding random number generator. See §3.
5. **The competitor half of "creative intelligence" does not compose with Fase 0 at all** — competitor content is unreachable through connected-account APIs, so it requires `packages/scraper`, the exact package ADR 19 proposes to pause. ADR 19 misses this coupling. It also breaks the unit economics independently (45–135% of a $6 seat). See §3.

---

## 1. Sunk-cost and thaw assessment

### 1.1 Live checkpoint verification (2026-07-21)

All rows verified this session via `hf_hub_repo_details` / `hf_fs` against the live Hub. Deltas from `docs/modelos-multimodal-fase1.md` are flagged.

| Checkpoint | Params | License (verified) | Inference Provider (live) | Last updated | Delta vs docs |
|---|---|---|---|---|---|
| `google/siglip2-base-patch16-224` | 375.2M | **apache-2.0** | none listed (`endpoints_compatible`) | 2025-02-21 | none |
| `moondream/moondream3-preview` | **9268.6M** | **`other` → BSL 1.1** | **none** | 2026-04-09 | **three deltas, see §1.2** |
| `Qwen/Qwen3-VL-4B-Instruct` | 4437.8M | apache-2.0 | featherless-ai only | 2025-10-15 | single-provider risk |
| `openai/whisper-large-v3-turbo` | 808.9M | **mit** | **hf-inference + deepinfra** | 2024-10-04 | none |
| `pysentimiento/robertuito-sentiment-analysis` | 108.8M | **none declared** | none listed | 2024-07-08 | license still unresolved |
| `vikhyatk/moondream2` (fallback) | 1927.2M | apache-2.0 | none listed | 2025-09-23 | none |

**Live runtime checks run this session** (`packages/models`, `uv run pytest`):

- 27 unit tests pass, `ruff check` clean, in 13 s with zero network.
- `tests/test_transcription.py -m integration` **passes** — the hosted whisper path via HF Inference Providers still works as of 2026-07-21.
- `tests/test_eval_integration.py -m integration` **passes** — Hub revision resolution still works.
- `tests/test_vision.py -m integration` **passes** — local Qwen3-VL-4B path works (from cache).
- Locked deps: `transformers 5.14.1`, `huggingface-hub 1.24.0`, `torch 2.13.0`, all pinned exactly in `uv.lock`.

### 1.2 `moondream3-preview` is mis-specified in the docs

Three separate problems, all verified live, none of which are rot — they are pre-existing defects a pause would preserve:

- **License is BSL 1.1 (Business Source License), licensor M87 Labs.** The Hub metadata says `license: other`; the actual `LICENSE.md` is BSL with an Additional Use Grant that permits production use *except* "offering the Licensed Work to third parties on a hosted or embedded basis in order to compete with M87 Labs's paid version(s)". Change Date: two years post-release, then Apache-2.0. A social-listening CRM plausibly does not "significantly overlap" with a VLM API, so Qualify's use is *probably* permitted — but this is a legal read, not an engineering one, and **`CLAUDE.md` and `docs/modelos-multimodal-fase1.md` both describe this stack as "open-weight", which BSL is not.** ADR 13 already rejected CC-BY-NC embedding models on commercial grounds; BSL deserves the same explicit test rather than an implicit pass.
- **9.27B params, ~18.5 GB of safetensors.** The plan positions the vision stage as serverless-GPU-or-hosted. At 9B with no Inference Provider, "buy it hosted to start" is not available — it must be self-hosted on a real GPU from day one, which inverts the buy-first sequencing in `docs/alternativas-fase1.md`.
- **Never run.** `~/.cache/huggingface/hub/models--moondream--moondream3-preview` contains 16 KB: a `refs/main` pointer and one blob. No weights were ever fetched. The committed primary vision checkpoint has produced zero outputs in this repo; `Qwen/Qwen3-VL-4B-Instruct` (the documented *fallback*) is the only vision path that has ever worked.

**Recommendation to architect** (I do not own `docs/`): `docs/modelos-multimodal-fase1.md`'s vision row needs three corrections — license class (BSL, not open-weight), parameter count/hosting implication (9.27B, no hosted provider), and status (unvalidated). The honest current state is that **Qwen3-VL-4B-Instruct is the de-facto vision checkpoint** and moondream3 is an aspiration.

### 1.3 Per-component reuse and thaw cost

"Thaw" = work to get the component running and trustworthy again after a 6–12 month pause, assuming `uv.lock` is untouched.

| Component | Reusable in Fase 0? | Rot vector | Rot risk | Thaw cost |
|---|---|---|---|---|
| **`filter.py` / siglip2** | **No.** Fase 0 has no relevance gate — you do not filter your own posts for whether they mention your brand. | apache-2.0 weights, native transformers class, no `trust_remote_code`, CPU-only | **Low** | **~0.** `uv sync` + `pytest`. Nothing to re-decide. |
| **`vision.py` / moondream3 + Qwen3-VL** | **Partially** — only for owned-content feature extraction (§3), and then likely repriced onto a hosted frontier VLM instead. | moondream3: `custom_code` (the exact failure class that already broke moondream2), BSL preview artifact, no provider. Qwen3-VL: **single** provider (featherless-ai), which already rejects this account. | **High** | **Days, and it is a re-decision not a re-run.** moondream3 was never validated; the provider path is already broken. Thaw = choose the vision checkpoint properly, which is unfinished Fase 1 work regardless of the pause. |
| **`transcription.py` / whisper-large-v3-turbo** | **Marginal** — only if Fase 0 ingests owned video audio. | MIT, two live providers, 102M downloads | **Low** | **~0.** Most robust component in the package; verified live today. |
| **`sentiment.py` / robertuito** | **Yes, immediately** — if Fase 0 reads comments/DMs from connected accounts. Confirms architect's exception (b). | Weights stable; but **license still undeclared** on the Hub (re-verified 2026-07-21), and it pulls the `pysentimiento` library, not plain transformers | **Low technically, unresolved legally** | **~0 to run; unbounded to clear legally.** The license question is the blocker, and it is the one component Fase 0 would actually ship. Resolve it before, not after. |
| **`eval/` harness** | **Yes, wholesale.** Confirms architect's exception (a). | Pure Python + pydantic + jiwer. Zero model coupling — `runner` and `revision_resolver` are injected. | **Near zero** | **~0 to thaw; ~1 day to extend** to generative eval (§5). |
| **Golden set (`eval_data/`)** | Methodology yes, content no. | 1 item, placeholder transcript, provisional sentiment label | **None (nothing to rot)** | n/a — but see the honest note below. |

### 1.4 Engaging the architect's "models does not rot" claim

**Verdict: refuted as stated, conclusion upheld on different grounds.**

The claim is that checkpoints and golden sets are stable artifacts, so pausing `models` costs little, unlike `scraper` whose hydration-JSON parsers decay silently. The asymmetry is real. The stated reason is wrong, and the error matters because it would lead you to skip a cheap mitigation.

**What actually rots here is the runtime surface between the code and the weights.** Three vectors, and the empirical record in this very package:

1. **Library version drift — ALREADY REALIZED.** `LocalMoondreamVisionProvider` is broken under `transformers >= 5.14.1`: moondream2's `trust_remote_code` class predates an internal API change (expects `all_tied_weights_keys`). Documented in `providers.py:29-35`. This happened during *active development*, not during a pause.
2. **Inference Provider roster and routing drift — ALREADY REALIZED, twice.** `HFInferenceVisionProvider` must name `provider="featherless-ai"` explicitly because `provider="auto"` returns `400 model_not_supported` for this model/account (`providers.py:104-112`); and no `hf-inference` chat-VLM is available to this account at all. Provider rosters are commercial arrangements that change without notice — today's live verification shows Qwen3-VL served by exactly **one** provider.
3. **Checkpoint availability and licensing drift — LATENT, and moondream3 is the exposure.** It is a **preview** artifact under a license with a **Change Date**. Preview checkpoints get replaced, renamed, gated, or withdrawn. This is the one vector that genuinely bites weights, and it bites precisely the checkpoint the docs commit to.

Two of three vectors are already realized. The base rate of drift in this package over roughly three days of active life is **two breakages**. Extrapolating that over a 6–12 month pause: the hosted paths are where the damage lands.

**But the mitigation is cheap, and half of it already exists** — which is why the architect's conclusion survives:

- `uv.lock` pins exact versions, so `uv sync` reproduces the environment bit-for-bit. **Frozen dependencies do not drift; rot only bites on upgrade.** (Note the `pyproject.toml` specifiers are open lower bounds — `transformers>=5.14.1` — so the lockfile is the entire protection. Do not run `uv lock --upgrade` casually during a pause.)
- The `Provider` Protocol confines provider drift to one file. A provider break is a one-file swap, not a pipeline rewrite. This is exactly the value the architect credits the abstraction with, and it is the reason thaw cost stays low.
- The 4 `@pytest.mark.integration` tests are the only drift detectors, they are already marked and isolated, and they cost seconds and pennies to run (verified this session: 29 s for the two hosted ones).

**The corrected claim, and the recommendation:**

> `packages/models` does not rot in its weights or its logic. Its **hosted-provider paths** are the drift surface, and its **4 integration tests are the only thing that will tell you they broke**. Under a pause, run those 4 tests on a monthly CI cron and nothing else. That converts silent rot into a dated signal for roughly $0/month and turns an unbounded thaw into a bounded one.

**The real asymmetry with `scraper`, stated correctly.** `scraper` decays because the *upstream data format* changes and nobody controls it — repair requires re-deriving parsing logic from freshly scraped live pages, which is expensive and cannot be done offline. `models` decays because the *upstream runtime* changes — repair is a version pin or a provider swap behind a stable Protocol, which is cheap and can largely be done offline. So: **pausing `models` is cheap because repair is cheap, not because breakage is unlikely.**

### 1.5 The debt a pause freezes but does not create

Distinct from rot, and worth naming because it will be mistaken for rot on thaw:

- **The cascade has never been validated.** The golden set has **1 item**, with a placeholder (empty) reference transcript and a provisional sentiment label. `eval/README.md` is candid about this: the run proves harness mechanics, not label accuracy. The central product claim — that the cascade works well enough to build on — is untested.
- **The vision stage has never run on its committed checkpoint** (§1.2).
- **No absolute $/video exists for the VLM or ASR stages.** `eval/cost.py` correctly refuses to invent them; the open question is flagged in `eval/README.md` and remains open.

None of this grows during a pause. None of it shrinks either. The honest framing for the founder: **pausing Fase 1 does not defer a validated asset, it defers an unvalidated one** — which cuts both ways. It lowers the cost of pausing (there is less realized value to strand than the LOC suggests) and it raises the cost of the eventual thaw (the validation bill is still unpaid, and it is the expensive part: ~100 human-labeled videos, with transcript references at minutes per item).

---

## 2. Where AI actually differentiates a publishing API

**Bottom line first, because it is the finding: there is very little real ML value on the write side of this product. Fase 0 is an OAuth, queueing, idempotency, and rate-limit product.** The hard problems ADR 19 lists (platform app review, exactly-once publishing under ambiguous failure, multi-tenant OAuth custody, shared per-app rate ceilings, adapter drift) are all distributed-systems and compliance problems. None of them is an ML problem. Any AI in Fase 0 is a feature on top of that plumbing, and the plumbing — not the AI — is the barrier to entry.

Costs below are computed with `eval/fase0_cost.py` at its documented token-shape assumptions (§4), against a $6/month-per-connected-account price point.

### 2.1 Ranked

| # | Feature | Genuinely useful? | Cost/op (Haiku 4.5) | Defensible? | Verdict |
|---|---|---|---|---|---|
| 1 | **Comment/DM triage + suggested reply** | Yes — real, recurring, unpleasant work | robertuito self-hosted ≈ marginal; reply drafting $0.0015 | **Moderate** | **The only genuine ML surface.** Build it. |
| 2 | **Cross-platform format adaptation** | Yes, materially | ~$0 (mostly not ML) | Low as ML, **moderate as data** | **Not AI — a maintained constraints table.** Label it honestly. |
| 3 | **Caption/hook generation per platform** | Yes, but table stakes | $0.0015/caption | **None** | **Thin wrapper.** Ship it, price it at zero, never market it as the differentiator. |
| 4 | **Ad-creative variants** | Marginal | Not priced here — image/video generation is a different, much costlier model class | **None** | **Thin wrapper**, and out of stack. Defer. |
| 5 | **Best-time-to-post prediction** | Later, yes. At MVP, no. | ~$0 (statistics, not tokens) | **High at scale, zero at MVP** | **Honest-later, fake-now.** See §2.3. |
| 6 | **Performance prediction (pre-publish)** | No | ~$0 | Zero at MVP | **Do not ship.** Strictly worse than #5. |

### 2.2 The one worth building

**Comment/DM triage** is the only feature where existing `packages/models` code plugs in directly, and it is defensible for a non-obvious reason: **it sits on the *reading* side.** Everything else in Fase 0 is write-side plumbing that any competitor with OAuth credentials can replicate. Triage requires ingesting, classifying, and prioritizing an inbound stream — which is structurally the same problem Qualify was built to solve, and where the existing `sentiment.py` plus the proposed zero-shot classifier (`MoritzLaurer/bge-m3-zeroshot-v2.0`, MIT, hf-inference live, verified 2026-07-18 in `NOTES_pain_signal_feasibility.md` §2) apply unchanged.

This confirms the architect's exception (b) and sharpens it: the composition point is not "Fase 0 happens to read comments" — it is that **the inbound half of Fase 0 is the only half where Qualify's thesis has any purchase at all.** If Fase 0 ships, the inbound features are where the differentiated work should concentrate.

Caveat that must clear first: robertuito's license is still undeclared on the Hub (§1.1). This is the component Fase 0 would ship on day one. Resolve the license before building on it.

### 2.3 Why best-time-to-post is fake at MVP scale

It is not a thin wrapper — it is a genuine statistical problem — which makes it more dangerous, because it *sounds* rigorous.

To personalize posting time you need per-account history of (posted_at × engagement). A new customer has none: **cold start is the default state of every account on day one.** What you can serve instead is a population prior — "Tuesdays at 6pm" — dressed as a personalized prediction. That is a defensible product only if you say plainly that it is a population baseline.

Even with history, the effect is hard to detect: with n≈20–50 posts per account, engagement variance driven by *content* dwarfs variance driven by *timing*, and the two are confounded (people post their best content at their favorite times). You cannot separate them without randomization, and you cannot randomize a customer's publishing schedule without their consent.

Where it becomes real: **pooled cross-account data with account-level fixed effects**, where each account is its own control and timing effects are estimated across thousands of accounts. That is a genuine data moat — a publishing API accumulates exactly this dataset and a pure-plumbing competitor does not. But it is a Year-2 asset. Ordering: **ingest and store the analytics time-series from day one so the dataset accrues; do not ship the inference until the accounts exist.** This is the single most valuable thing Fase 0 can do for its own future ML story, and it costs nothing but a schema decision now.

### 2.4 What "thin wrapper" means here, precisely

Caption generation costs **$0.03/month** for a 20-post account — 0.5% of a $6 seat. That is the tell. **When a feature's marginal cost rounds to zero, cost is not a barrier, and when cost is not a barrier the feature is not a moat.** Any competitor ships it in a weekend at the same price. Include it because customers expect it; do not build a positioning claim on it.

---

## 3. Reusing the cascade on owned content

This was flagged as the highest-value question: does the Fase 1 differentiated core compose with Fase 0, or is the reuse story wishful? **Answer: the composition is real but much narrower than it looks, and the most attractive half of it does not compose at all.**

Three sub-questions with three different verdicts.

### 3.1 Own library — composes cleanly, cheap, modest value

Owned content arrives through **connected-account APIs**. No scraping, no proxies, no Zyte. This is the clean part.

Costs computed with `fase0_cost.py` (Haiku 4.5, 4 frames/video, VLM only, ASR excluded):

| Scenario | Monthly AI cost | Share of a $6 seat |
|---|---|---|
| Captions only, 20 posts/mo | $0.030 | 0.5% |
| + own library, 20 videos/mo | $0.208 | 3.5% |
| One-time backfill, 200-video library | **$1.78 one-time** | — |
| One-time backfill, 1000-video library | $8.90 one-time | — |

**It fits comfortably.** Analyzing a client's entire back catalogue costs less than two dollars.

But cost was never the objection — **value** is. ADR 19's *ortogonalidad* point is correct on the descriptive layer: the cascade's native output is a description of a video, and the client already knows what is in their own video. **Descriptions of owned content are worth approximately nothing.**

The value, if there is any, is not description — it is **structured feature extraction for cross-post comparison**: turning a library into a table of `(post_id → hook type, on-screen text density, face presence, cut rate, colour palette, spoken-word topics, …)` joinable against platform analytics. That is a different prompt and a different output schema from the Fase 1 cascade, though the same stage and the same Provider seam. **Reuse is at the level of infrastructure and method, not at the level of the existing prompts or outputs.**

### 3.2 "Why did this post work" — the honest statistical verdict

**This cannot be answered for a single account, and shipping a version that claims to would be worse than shipping nothing.** Reasons, in order of severity:

1. **It is a causal question asked of observational data with no control and no randomization.** There is no counterfactual: you never observe the same post published without the feature you are crediting.
2. **Sample size is tiny relative to the hypothesis space.** A typical library is 20–200 posts. A creative-feature table has dozens of columns. At α=0.05 with 30 candidate features you expect ~1.5 spuriously "significant" findings by chance alone — and the product will report them with a straight face.
3. **Engagement is heavy-tailed.** One viral post routinely carries the entire distribution. Means and regressions are dominated by outliers, so the *effective* sample size is far below the nominal n. Confidence intervals computed as if the data were normal will be badly overconfident.
4. **Confounding is severe and mostly unobserved:** follower count grows monotonically over the library's lifetime (later posts get more reach for reasons unrelated to creative), algorithm behaviour changes under you, topic and seasonality shift, and content quality correlates with the very features being measured.

**What is defensible now:** a purely **descriptive**, explicitly non-causal segmentation. *"Your top-decile posts by engagement share these attributes; your bottom decile share these."* No prescription, no "do X to get more views". This is honest, still genuinely useful to a marketer, and costs $1.78 per library. Frame it as a lens on what already happened.

**What becomes defensible at scale:** pooled cross-account modelling with account fixed effects — the same asset described in §2.3. This is the real long-run differentiator and it is unavailable to a plumbing-only competitor, because it requires (a) many accounts, (b) their analytics time-series, (c) cascade-extracted creative features. **Build (c) and start accumulating (b) now; ship the inference later.**

**The gate before any performance claim ships** — this is the eval design, and it is non-negotiable: fit on posts before date T, predict rank-order of engagement for posts after T, report **Spearman ρ with a bootstrap CI**, and beat **two** baselines: (i) predict-the-mean, and (ii) **follower-count-at-time-of-post alone**. Baseline (ii) is the one that kills projects, because reach tracks audience size far more than creative. My prior, stated in advance so it is falsifiable: **single-account models will not beat baseline (ii).** If a backtest shows otherwise, that is a real result and I will take the update.

### 3.3 Competitor content — does not compose, and ADR 19 misses the coupling

The most commercially attractive version of this feature is competitive creative intelligence: *"here is what is working for your competitors."* Two independent blockers.

**Blocker 1 — it requires the paused package.** Competitors' public content is **not reachable through connected-account APIs**; a client cannot OAuth into a competitor's account. Acquiring it requires scraping — i.e. `packages/scraper`, precisely the package ADR 19 identifies as perishable and proposes to pause. So competitor creative intelligence is not a Fase 0 feature that rescues stranded `models` work; **it is a feature that un-pauses `scraper`.** If the founder wants it in Fase 0, the pause decision must be reopened and the scraper's rot cost comes back onto the table. **This coupling is absent from ADR 19's reuse analysis and should be added.**

**Blocker 2 — the unit economics break independently of blocker 1:**

| Scenario | Haiku 4.5 | Sonnet 5 |
|---|---|---|
| Own 20 + 3 competitors × 30 videos/mo | $1.01 (16.8% of seat) | $3.03 (**50.5%**) |
| Competitor-heavy, 300 videos/mo | $2.70 (**45.0%**) | $8.10 (**135% — underwater**) |

Competitor analysis **cannot be bundled into a per-connected-account subscription.** Its cost scales with competitors monitored, which is uncorrelated with connected accounts — the billing unit and the cost driver come apart. It needs separate metered or credit-based pricing (the `billing.usage_events` model already designed for Phase 5), plus a hard per-tenant quota. Note also that these figures are **VLM-only**: ASR is excluded because no hosted per-minute rate is sourced (§4), so the true totals are higher.

### 3.4 Net verdict

**Do not sell Fase 0 on "it reuses our differentiated core." The reuse is thinner than it looks, and the claim will not survive contact with the build.**

- The half that composes (own-library structured feature extraction, descriptive only) is cheap, honest, and modest.
- The half carrying the big claim ("why did this post work") is statistically unsupportable at MVP scale and should ship only in descriptive form.
- The half that would genuinely differentiate (competitor creative intelligence) requires reactivating `scraper` and a separate pricing model.

The defensible strategic framing: **Fase 0's real contribution to Qualify's ML future is the dataset it accumulates** (cross-account creative features × analytics time-series), not the cascade it reuses. That is worth optimizing for now, cheaply, via schema decisions — and it is a genuinely different argument from the one ADR 19 currently makes.

---

## 4. `eval/fase0_cost.py` — the model, its levers, its assumptions

Written by the predecessor datasci session; 8 tests in `tests/test_fase0_cost.py`, all passing. This section is the missing writeup.

### 4.1 What it models and why the unit changed

`eval/cost.py` models the **Fase 1 cascade at $/video**: the question there is "what does processing one scraped video cost", because the cascade exists to keep expensive stages off non-candidates.

`fase0_cost.py` is its sibling for a product sold **per connected account per month**. The unit of analysis changes accordingly: not "what does one video cost" but **"does the AI spend on one account fit inside that account's subscription revenue"**. That reframing is the whole point — a per-video cost is meaningless when the billing unit is an account whose video volume is a customer behaviour, not a system parameter.

### 4.2 API

- `token_cost_usd(model_id, tokens_in, tokens_out) -> float` — single call at list rates. Raises `KeyError` on an unknown model rather than defaulting, so a typo cannot silently price at zero.
- `caption_generation_usd(model_id) -> float` — one platform-adapted caption.
- `video_analysis_usd(model_id, frames=4) -> float` — one VLM pass over N sampled frames. **VLM only; excludes ASR.**
- `estimate_account(...) -> AccountEconomics` — the monthly roll-up under a usage profile.
- `AccountEconomics.margin_safe -> bool | None` — tripwire, see §4.5.

### 4.3 Levers, in descending order of impact

Computed values at the defaults, for calibration:

| Model | Caption | Video (4 frames) | Video (8 frames) |
|---|---|---|---|
| `claude-opus-4-8` | $0.00750 | $0.04450 | $0.07650 |
| `claude-sonnet-5` | $0.00450 | $0.02670 | $0.04590 |
| `claude-haiku-4-5` | $0.00150 | $0.00890 | $0.01530 |

1. **`own_videos_analyzed_per_month` / `competitor_videos_analyzed_per_month`** — dominant. Video analysis is ~6x a caption per call (pinned as a regression test), and it is the only lever that can exceed revenue on its own.
2. **`model_id`** — Opus 4.8 is 5x Haiku 4.5 at identical token shapes. Model choice alone moves a workload from 16% to 84% of revenue.
3. **`revenue_usd_per_month`** — the denominator moves 6x across the tiers of a per-account product ($6 → $1). **An operation affordable for a small customer is underwater for a large one**, which is counterintuitive and is the failure mode `test_cheapest_tier_breaks_under_frontier_model` pins.
4. **`frames_per_video`** — linear, second-order at 4–8 frames.
5. **`posts_per_month` / `captions_per_post`** — real but negligible (§2.4).

### 4.4 Assumptions — the part to distrust

**The token shapes are engineering guesses, not measurements.** No real prompt was ever traced. Specifically:

- `CAPTION_TOKENS_IN = 500`, `CAPTION_TOKENS_OUT = 200`. A production caption prompt carrying brand-voice guidelines, few-shot examples, and per-platform constraints plausibly runs **1500–3000 input tokens — 3–6x the assumption**. Direction of error: **understates**.
- `VIDEO_TOKENS_PER_FRAME = 1600` — the standard-resolution image cost on the Anthropic API. High-resolution frames cost up to **~3x** more. Direction: **understates** if frames are sent at native resolution.
- **Excluded: prompt caching.** A caption prompt's brand-voice preamble is identical across calls and is the ideal caching candidate; caching would cut steady-state input cost substantially. Direction: **overstates**.
- **Excluded: batch discount (50% off).** Scheduled publishing is inherently batchable — this is a large, realistic, unclaimed saving. Direction: **overstates**.

The two error directions **partly cancel**, which is a reason not to over-trust either the total or the `margin_safe` verdict in either direction. What the model is genuinely good for is **ratios and rankings** — video-vs-caption, Haiku-vs-Opus, which lever dominates — all of which are robust to a uniform scaling error in the token shapes. Treat absolute dollars as order-of-magnitude only.

**Anthropic list prices are cached from the `claude-api` skill table, 2026-06-24.** Re-verify before quoting externally.

### 4.5 The 20% tripwire

`margin_safe` returns `True` when AI spend is under 20% of the account's revenue. **This is a working threshold, not a sourced industry benchmark**, and the docstring says so. The reasoning: inside a per-account price of $1–6 there must still be room for infra, payment processing, and support. Treat it as a tripwire that prompts a conversation, not a target to optimize toward and not a number to put in a business plan.

### 4.6 Rates that remain `None`, and why

Both are **required caller inputs with no default**, and `estimate_account` returns `total_ai_usd_per_month = None` when either is missing rather than silently reporting a partial total (pinned by `test_unpriced_stages_yield_no_total`):

- **`asr_usd_per_video`** — no hosted per-minute ASR rate is sourced anywhere in this repo. This is the *same* open question already flagged for Fase 1 in `eval/README.md`; it was not closed and has not been invented here. Closing it needs a quoted HF Inference / Groq / Deepinfra rate or a measured self-hosted figure.
- **`comment_triage_usd_per_month`** — depends on per-account comment volume, which is entirely unmeasured. No connected-account or scraped comment-volume data exists in the project.

**Every scenario table in §2 and §3 of this document passes `0.0` for both**, and is therefore a **VLM-and-caption-only lower bound**. Real totals are higher by an unknown amount. Stated explicitly so no figure here is mistaken for a full cost.

### 4.7 One code defect worth fixing

`OperationCost.usd_per_call` is a **misnomer inside `estimate_account`**: the field is populated with a *monthly total* (`caption_unit * posts_per_month * captions_per_post`), not a per-call cost. The name is inherited from the per-call helpers where it is accurate. Harmless internally, actively misleading if this model is ever serialized into a pricing deck. **Recommend renaming to `usd_per_month` on the `estimate_account` path** before the model is quoted externally.

---

## 5. Agent Skills as a product surface, and evaluating generative output

### 5.1 What makes a published Skill sellable rather than embarrassing

A Skill is **a behavioural contract, not documentation**. The test of whether it is worth publishing is falsifiable and worth applying honestly:

> If a competent agent holding only the OpenAPI spec would behave identically without the Skill, the Skill has zero value.

Most published Skills fail that test — they are the REST docs restated in Markdown. What passes:

1. **It encodes the non-obvious** — the platform constraint matrix (aspect ratios, durations, codecs, character limits, hashtag conventions per platform), error-code semantics (which 4xx are retryable and which are permanent), the two-phase container-then-publish patterns, chunked-upload rules. This is knowledge the model does not have and cannot guess, and it is exactly the "commodity plumbing" tax from ADR 19 turned into an asset.
2. **It says when *not* to act.** The highest-value line in a publishing Skill is the one that says: *on an ambiguous publish timeout, do not retry — reconcile against recent-posts, and if unavailable, fail closed and escalate.* That directly encodes ADR 19's hard problem #2. An agent that double-posts to a client's real audience is a visible, trust-destroying failure; a Skill that prevents it earns its place.
3. **It is versioned against the API it wraps**, and states that version, so drift is detectable rather than silent.
4. **It is small and composable** — one job, not a manual.
5. **It has an eval suite behind it** (§5.2), so "we improved the Skill" is a measurement, not a vibe.

**Honest business framing:** a Skill is **a distribution channel, not a product**. It lowers integration friction for the developer segment and puts Qualify in the path of agent-built workflows. Nobody pays for the Skill. Do not model revenue on it.

### 5.2 Evaluating generative output with no ground truth

There is no WER and no precision@k for "is this caption good". The honest methodology has four layers, in this order.

**Layer 1 — Refuse the framing first. Most real failures are deterministic.** Generative output has a hard shell that is pass/fail measurable, free to compute, and catches the majority of production defects:

- character limit per platform, hashtag count, mention validity
- banned-term / competitor-name list
- **required disclosure present when the post is sponsored** (regulatory, not stylistic)
- no fabricated URLs or @handles
- correct language, correct platform-native format

Report as a **compliance rate**. A caption that exceeds a platform's character limit is broken no matter how well it reads. **Build this layer before touching LLM-as-judge** — it is cheap, objective, and it is what will actually break in production.

**Layer 2 — Pairwise preference, never absolute scoring.** Both humans and model judges are unreliable at "rate this 1–5" and substantially more reliable at "A or B". Build the eval as **A/B against a baseline** (the current prompt, or a human-written caption) and report **win-rate with a binomial confidence interval**. This gives a natural regression gate: a new prompt ships only if it beats the incumbent at p<0.05.

**Layer 3 — A small human-labeled anchor set, non-negotiable.** ~100–200 pairs labeled by someone who actually knows the brand voice. Without it you cannot know whether your judge measures anything at all. Report **judge-vs-human agreement (Cohen's κ)** on this set and re-report it whenever the judge model changes. A judge with unmeasured agreement is decoration.

**Layer 4 — LLM-as-judge, scoped to what it can actually do.**

*Where it is trustworthy:*
- **Rubric-checkable, near-objective properties**: "does this reply answer the question asked", "does it assert a fact absent from the source", "is the tone consistent with these three exemplar posts". Judge-human agreement on these is usually high enough to gate on.
- **Relative comparisons** far more than absolute scores.
- **As a screen, not a verdict** — triage 1000 outputs down to the 50 a human reviews. This is its highest-value use and the one most often skipped.

*Where it is not trustworthy — the part that gets glossed over:*
- **Self-preference / same-family bias.** A judge from the same model family as the generator systematically prefers its own outputs. Generating with Haiku and judging with Sonnet is *inside one family*. Mitigate by judging with a different family, or accept the number supports only within-arm comparisons.
- **Position bias.** Judges favour the first (or last) option presented. **Mandatory mitigation: run both orders, keep only order-consistent verdicts, and report the flip rate.** A high flip rate means the judge is not discriminating and the win-rate is noise wearing a percentage sign. Reporting the flip rate is the cheapest honesty check in the whole design.
- **Length and fluency bias.** Judges reward longer, more polished text. For social captions this is *actively inverted* — short usually wins on-platform. A judge will confidently steer caption generation in the wrong direction.
- **Anything needing ground truth the judge lacks**: will this caption perform well, is this claim about the client's product true, is this reply appropriate given a customer history the judge cannot see. **A judge cannot evaluate business outcomes. Never let a win-rate stand in for engagement.**
- **Brand voice specifically:** a judge can check consistency *against supplied exemplars*; it cannot know a brand's voice a priori. This makes exemplar collection a **product onboarding requirement**, not an eval implementation detail — a design consequence worth surfacing early.

**Layer 5 — the metric that actually matters, and it is a product decision.** For captions and replies, the real ground truth is **human accept / edit / reject inside the product**. Ship generative features as **drafts the user approves**, log the three-way outcome plus the edit diff, and you get a continuously growing, real, unfakeable eval set at **zero labeling cost** — and the edit diffs are a direct signal of *what* was wrong, not just that something was. This is the single highest-leverage eval decision available in Fase 0, it must be designed in from day one, and it is a product-design choice rather than an ML one.

### 5.3 What the existing harness gives you for free

Confirming the architect's exception (a), with specifics. `eval/harness.py` is model-agnostic by construction — `runner` and `revision_resolver` are injected, and `EvalReport` already pins `harness_version`, `pipeline_version`, manifest identity + SHA256, and per-stage checkpoint + revision. That provenance discipline is **exactly** what generative eval needs and is the part teams usually get wrong: without pinning the generator model, the judge model, and the prompt version, two win-rates are not comparable.

What changes to support §5.2:

- `metrics.py` — add compliance rate, pairwise win-rate with binomial CI, judge-human κ, judge flip-rate.
- `schema.py` — `GoldenItem` gains reference outputs / preference pairs.
- `providers.py` — a `JudgeProvider` Protocol alongside `VisionProvider` / `TranscriptionProvider`; the judge is a swappable model, and §5.2 requires swapping it to test family bias.
- `EvalReport` — pin generator model, **judge model**, and prompt version, exactly as it pins checkpoints today.

**Estimated effort: ~1 day.** The methodology transfers; the harness does not need rebuilding. This is the strongest concrete support for the claim that `packages/models`' eval work is not stranded.

---

## Provenance

- **Checkpoint facts verified live via `hf_hub_repo_details` and `hf_fs`, check-date 2026-07-21:** `google/siglip2-base-patch16-224`, `moondream/moondream3-preview` (incl. full `LICENSE.md` retrieval → BSL 1.1, M87 Labs), `openai/whisper-large-v3-turbo`, `pysentimiento/robertuito-sentiment-analysis`, `Qwen/Qwen3-VL-4B-Instruct`, `vikhyatk/moondream2`.
- **Runtime facts measured this session** (`packages/models`, macOS, `uv run`): 27 unit tests pass + `ruff check` clean; `tests/test_transcription.py`, `tests/test_eval_integration.py`, `tests/test_vision.py` pass under `-m integration`; locked versions `transformers 5.14.1` / `huggingface-hub 1.24.0` / `torch 2.13.0`; `moondream3-preview` local cache = 16 KB (refs only, weights never fetched).
- **All cost figures** computed by `eval/fase0_cost.py` at its documented token-shape assumptions, with `asr_usd_per_video=0.0` and `comment_triage_usd_per_month=0.0` → **VLM-and-caption-only lower bounds** (§4.6).
- **Code inspected:** `eval/{harness,cost,fase0_cost,metrics,provenance,schema,cli}.py`, `providers.py`, `eval/README.md`, `tests/test_fase0_cost.py`, `pyproject.toml`, `uv.lock`.
- **Docs referenced (not edited — owned by architect/gtm-r):** `docs/arquitectura.md` §7 + "Nota de soporte de ADR 19"; `docs/modelos-multimodal-fase1.md`; `CLAUDE.md`; `NOTES_pain_signal_feasibility.md`.
- **Recommended doc updates flagged to architect** (I do not own `docs/`): moondream3 license class / size / hosting implication / unvalidated status (§1.2); the ADR 19 rot premise (§1.4); the scraper coupling in competitor creative intelligence (§3.3).


