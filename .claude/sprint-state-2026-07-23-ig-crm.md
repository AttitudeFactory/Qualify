# Sprint state — IG Business/Creator → CRM integration (2026-07-23)

**Status:** all three teammates died simultaneously to a session limit at ~02:08 (resets 03:30 America/Montevideo). Written by dev-lead to survive the lead session too. Verified against disk, not against agent claims.

Sprint goal (founder, verbatim): harvest Meta's Instagram Platform docs into the repo + load into graphify, so the dev team has full reference for **integrating client Business and Creator accounts into Qualify's own CRM SaaS**. Explicitly NOT the Zernio dev-facing publishing-API pivot.

Founder-approved decisions: harvest scope = full `instagram-platform` tree + graph-api base (Graph API core, App Review, Business Verification, token handling). Landing path = `reference/meta-instagram-platform/`.

---

## What is on disk (verified 02:1x)

| Artifact | State |
|---|---|
| `docs/integracion-cuentas-conectadas-meta.md` | **316 lines, landed.** architect A1 (§0–§1) |
| `packages/models/src/qualify_models/oauth_scope.py` | **19KB, landed.** 28 rows = 7 surfaces × 4 stages, total coverage verified, imports cleanly offline |
| `reference/` | **ABSENT.** pipeline correctly wrote nothing — was awaiting plan approval + layout ruling |

## ⚠️ THE "WHAT WAS LOST" LIST BELOW IS STALE — corrected 2026-07-24

Verified against the filesystem: **`packages/models/tests/test_oauth_scope.py` EXISTS and passes offline** (15 test functions, 20 parametrised cases), and **`tests/test_filter_calibration.py` exists** (the #13 pinning test). Both landed from a resumed or parallel session after this file was written. The list below is a snapshot of a moment, not current state.

**Lesson, and the lead violated it first:** this file is a handoff artifact, not an authority. The lead repeated its "no tests" claim back to `datasci` as fact without re-checking disk — the exact failure this project keeps hitting. **Re-verify against the filesystem before citing anything here.**

Also corrected: `oauth_scope.py` contains **zero** permission-scope strings (grepped). It encodes content surfaces and Graph API edges, not OAuth scopes. A lead claim that it "may encode deprecated scope names" was false and is retracted.

## What was lost (in flight when the limits hit — SEE STALENESS WARNING ABOVE)

- **No test file for `oauth_scope.py`.** datasci's own plan called for tests pinning matrix totality and the load-bearing negatives. Currently untested.
- **`NOTES_fase0_oauth_crm.md` never written.** This is the expensive loss — it was to hold the filter-defect write-up, the robertuito risk-concentration reframe, and the per-surface gate reasoning.
- **No `SentimentProvider` seam** (`sentiment.py` and `providers.py` untouched, verified: zero occurrences).
- **No `@pytest.mark.integration` markers** on the two network tests.
- **No failing test for the filter defect** (task #13) — it survives only as the task description.

## Unexplained

`packages/models/NOTES_manychat_activation_layer.md` (1.3KB, 23:01) appeared during this session. Not assigned to any teammate this sprint and predates architect's 23:08 write. Likely from a prior or parallel session. **Do not assume it is sprint output.**

---

## VERIFIED Fase 1 defect — task #13 (highest-value finding of the sprint)

`run_filter` returns `passed=False` for every input. `cascade.py` gates `run_vision` on it, so **the vision stage is unreachable through `run_cascade`**. Found by datasci, independently reproduced by the lead on `tests/fixtures/sample_frame.jpg`:

```
DEFAULT(5)   max=0.0000323  sum=0.0001060  passed=False
generic(3)   max=0.0000822  sum=0.0000865  passed=False
binary       max=0.0000991  sum=0.0001234  passed=False
```

Threshold is `0.22`. Scores are 3–4 orders of magnitude below it; sums are ~1e-4, not 1.0.

**Two competing root causes — UNRESOLVED. Do not fix until settled.**
1. *Units mismatch.* SigLIP emits independent per-label **sigmoid** scores, not a softmax. `0.22` looks calibrated as if softmax (sits just above the 0.20 uniform baseline for 5 labels).
2. *Broken text tower.* Model load emits `bos_token_id ... got 49406` / `eos_token_id ... got 49407` — CLIP-range ids on a ~32k-vocab model. Supporting evidence: scores barely discriminate across semantically unrelated label sets, which hypothesis 1 does not explain.

These imply different fixes. Recalibrating a threshold on a broken text tower would burn golden-set labeling effort and still fail.

Why it survived: `tests/test_filter.py` asserts structure (`0.0 <= s <= 1.0`), never discrimination — a constant-`False` filter passes it trivially. Golden set holds 1 item with no filter label.

Ruling already given to datasci: **option (b)** — flag + failing test pinning observed behavior. Do NOT recalibrate; correct threshold is empirical and needs the golden set. Architect notified: `docs/modelos-multimodal-fase1.md` and `docs/arquitectura.md` §3.4 both describe discard economics the code does not deliver (sign is inverted — filter discards 100%).

## Second verified defect — no-network gate

`uv run pytest` in `packages/models`: **27 passed warm cache, 2 failed / 25 passed cold cache.** `tests/test_filter.py::test_run_filter_against_sample_frame` and `tests/test_sentiment.py::test_run_sentiment_on_spanish_text` download weights and carry no `integration` marker. Repro:

```
cd packages/models && HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run pytest -q
```

The package already declares the marker and `addopts = "-m 'not integration'"`, and four tests use it correctly. These two are the only holes. Approved: mark them, offline replacement lands in the same change, coverage relocates and never drops. `NOTES_fase0_agentive_layer.md` §1.1's "27 tests pass, no network" is true only on a warm cache — datasci was to correct his own role's record.

## Third finding — robertuito risk concentration

`pysentimiento/robertuito-sentiment-analysis` declares **no license** on the Hub (lead-verified via Hub API). This is NOT new — already documented at `docs/modelos-multimodal-fase1.md:91` as an inherited caveat.

**What IS new and unwritten:** in Fase 1 robertuito was one stage of four. On the OAuth/CRM path, if sentiment is the only stage transferring unchanged, robertuito becomes the **entire day-one AI value proposition**. Same unresolved commercial-use question, radically larger blast radius. Awaiting founder decision on whether to route resolution to architect now.

---

## pipeline's recon findings — PRESERVED HERE, existed nowhere else

These were delivered by message only; no code landed. All curl-verified by pipeline. **They materially change task #1's stated assumptions and re-deriving them costs real time.**

1. **`/docs/graph-api/**` serves `text/html`, not markdown** (~1MB/page, genuinely server-rendered, ~10.7KB real text). The Graph API half of the approved scope needs an HTML→markdown path the Instagram half does not. Rest of the base set is clean markdown: `/docs/app-review` (2.5KB), `/docs/development/release/business-verification` (3.7KB), `/docs/facebook-login/guides/access-tokens` (14.7KB).

2. **`/docs/` and `/documentation/` are NOT interchangeable — would have silently corrupted the harvest.** `/documentation/graph-api/overview` returns **HTTP 200 with a "page not found" body** (soft-404: 137KB chrome, 58 chars visible text, in Spanish). The instagram-platform tree resolves under both forms, which is where the lead's "they're the same" pre-flight impression came from; it does not hold site-wide. Fix: canonicalize to `/docs/` + explicit soft-404 detection. **On this host, HTTP 200 is not proof of a real page.**

3. **The site geo-localizes to Spanish by default.** `/docs/graph-api/overview` returned Spanish with no language header. Pin `Accept-Language: en-US` on every request.

4. **Better seed than task #1 specifies:** `/docs/instagram-platform` (tree root) links directly to the four surfaces this sprint actually needs — Instagram API with Instagram Login, Instagram API with Facebook Login for Business, Messaging via Messenger API, Sharing to Stories/Feed — each explicitly scoped to Business/Creator accounts. `content-publishing` is one leaf below. Seed from root, keep content-publishing in the frontier.

**pipeline's approved-in-spirit design** (plan was sound; lead had not yet sent formal approval when the limit hit): pure `urls.py` (canonicalize / is_in_scope / url_to_local_path / extract_links, no I/O) · `fetch.py` with a `Fetcher` Protocol + `HttpFetcher` (≥1.1s interval, 3 retries, backoff) and a `FixtureFetcher` for tests — making the no-network gate structural rather than promised · `soft404.py` · `htmlmd.py` · `manifest.py` as **append-only JSONL journal flushed per page** (crash-safe; doubles as resume frontier; aggregate `manifest.json` regenerated from it) · `crawl.py` BFS with depth tracking. Explicit path-prefix allowlist + max-depth/max-page caps; out-of-scope URLs recorded as skipped-with-reason, never silently dropped. Recon fixtures (markdown page, HTML graph-api page, soft-404 body) were captured during recon.

---

## OPEN DECISIONS blocking the respawn

**For the founder:**
- **(F2) RESOLVED 2026-07-23 — subagent dispatch AUTHORIZED** for graphify's semantic-extraction step. Verified no `GEMINI_API_KEY`/`GOOGLE_API_KEY` in env and no `.env`; the skill (SKILL.md:154-161) is explicit that graphify needs no key and that on a subagent-dispatching host the host agent itself is the LLM. `pipeline` asked rather than inferring authorization — correct, and it is now granted. Costs real tokens; proceed anyway.
- **(F3) RESOLVED 2026-07-23 — graph is built over the `instagram-platform` subtree ONLY.** `graph-api` base set is still harvested to `reference/` as consultable corpus but stays OUT of the graph, to keep communities dense rather than diluted by Meta's cross-cutting App Review / Business Verification material.
- **(F1) STILL OPEN** Robertuito license — route resolution to architect now, or accept-and-annotate as a known risk?
- **(F4) architect ruled this is **Fase 1 Parte 4**, and that Parte 3 (R2, `packages/shared`, Celery, `ingestion.*` DDL) is now **critical path** — anything that materializes content is hard-blocked on it. Connection layer (OAuth, token custody, refresh, health FSM, Postgres) is NOT blocked. Confirm this sequencing.
- **(F5)** architect: ADR 19 stays PROPUESTO; goes to **RETIRADA** only if the founder confirms he is dropping the dev-facing publishing API. Founder signs that, not the architect.
- **(F6)** architect's item zero, a founder task not an engineering one: **no legal entity with matching NIF/address/active website ⇒ that is the block before the block.** The 2–4 month App Review / Business Verification clock consumes zero engineering capacity and should start week 0.

**For the lead to route on respawn:**
- Layout ruling for the harvester (`packages/docs-harvester/` as its own uv project — pipeline's recommendation — vs `scripts/meta_docs_harvester/`). architect never answered; pipeline correctly wrote nothing pending it.
- architect flagged a **`payload_schema_version=2`** envelope change in `packages/scraper/src/qualify_scraper/shared.py`: add `source_class`, generalize the vendor-named `zyte_request_meta`, and **invert ADR 18's brand-agnostic keying to tenant-scoped** — first-party responses are never shareable across tenants and getting it wrong is a **cross-tenant leak**. architect owns the decision, pipeline owns the code. Neither has started.
- architect will **not** lock any ClickHouse `ORDER BY` this sprint (requires the `clickhouse-architecture-advisor` gate; `ORDER BY` is immutable once shipped). Candidates to be presented PROPUESTO-no-lockeado.

---

## FOUNDER CONTEXT REVEALED 2026-07-23 ~02:30 — changes the sprint's premise

Founder disclosed the actual commercial situation. Recorded verbatim in substance:

- He is forming the legal entity **in Cúcuta, Colombia**, with **PuntoServis**, to open a PuntoServis store.
- **Customer zero is himself:** he needs this product to do marketing/advertising for that store.
- **Customer one is a friend, a real-estate advisor**, whose **human sales agents** would use the tool to *"atender todos sus canales"*.

### What this FIXES

1. **The CAC/WTP problem, which was the second of three NO-GO grounds.** `fase0-zernio-mercado.md` §5.3 ruled solo-founder software sales to SMBs inviable (100–250 customers needed for €3.000/mes). He is not selling cold — customer 0 is himself, customer 1 is a warm relationship with a team. This is §6.3's "sell the service before building the tool" validation path, already half-executed.
2. **The earned-media precision wall, which killed the most attractive feature.** `NOTES_manychat_activation_layer.md` §2.2 ruled auto-reply statistically unshippable at earned-media base rates (π≈0.5% → 7.9% precision, 11.6 false positives per true positive). **Both disclosed customers operate on OWNED media** — their own store account, the realtor's own agent accounts. That is the π≈10% → **65% precision** row of the same table. The verdict does not transfer because the premise does not: the feature is unshippable for Qualify's original earned-media thesis and shippable for his actual first two customers.

### What this BREAKS

1. **The architect's A1 ruling, made ~1h earlier:** *"Read-first, write-later: reading is what makes this Qualify; publishing is what would make it a Zernio clone"*, with smart replies explicitly out of scope. But *"atender todos sus canales"* is **write-side inbound conversation management** — DM/comment reply across channels. Both disclosed customers need the write side first. **Architect must re-rule with this context.**
2. **The phase map.** Unified social inbox is **Fase 6** in `CLAUDE.md`. Multi-agent seat management (the realtor's human agents) has no phase at all. His near-term need sits at the far end of the roadmap while Parte 3/Parte 4 sit at the near end.
3. **The entire Spanish-market WTP analysis** (`fase0-zernio-mercado.md` §5): Metricool €16–29, community-manager €250–700/mes, "Metricool Free covers the PYME". **Colombia is a different market with different absolute price points.** None of §5 is known to transfer.
4. **Entity assumptions.** §1.2 costed entity formation and Meta Business Verification against Spanish **NIF/CIF/VAT**. Colombia is **NIT + Cámara de Comercio**. Meta accepts Colombian entities but the document set and timeline are unverified. PuntoServis involvement may mean he operates under an existing entity — materially changes the "block before the block".
5. **Channel priority.** Colombian real estate runs on **WhatsApp**, not Instagram. `fase0-zernio-mercado.md` marks WhatsApp Business as **"no verificado en esta pasada — pendiente"** — an unresearched gap that may now be the single most important channel. ManyChat's WhatsApp support needs Cloud API + approved templates + tiered messaging limits.

### What this ELEVATES

`docs/ingenieria-inversa-manychat.md` (185 lines, gtm, 2026-07-23) and `packages/models/NOTES_manychat_activation_layer.md` (datasci, same day, **D3/D4/D5 sections still `(pending)`** — that session also appears to have died) are now **the most directly relevant documents in the repo**. They were written to *refute* "we can steal ManyChat's features", screening against owned-vs-earned. The founder's real customers are owned-media — so the screen mostly passes instead of failing. Finish D3/D4/D5 before designing anything.

Also relevant from that teardown: ManyChat's whole trigger surface is an **NLI zero-shot classifier, not an LLM** (§1.1), which strengthens the `bge-m3-zeroshot-v2.0` proposal and gives it a second role (activation trigger, not just signal detector). And ManyChat auto-generates replies **only for positive comments** — risk management disguised as a feature.

### CORRECTION + PRIORITY STATEMENT from founder, 2026-07-24 (supersedes parts of the above)

Corrections to the 02:30 record:

- **PuntoServis provides marketing training courses and its own marketing tools.** The founder understands franchisees **manage their own social accounts**. He is a *franchisee*, not a vendor to PuntoServis.
- **The real-estate customer is in URUGUAY, not Colombia.** (Colombia is only where the legal entity is being formed, in Cúcuta.) Their complaint is against **Gallito** and **MercadoLibre** — Uruguayan classifieds portals — which *"no les permite hacer muchas cosas"*. That is a portal-syndication / lead-management problem on a **completely different integration surface** than Meta's APIs. **Do not scope it this sprint.** It is customer one, not customer zero.
- **IP boundary, stated explicitly:** *"yo no les voy a pedir o regalar mi inteligencia de negocio"*. The tool must stay separable from, and run in parallel to, the marketing tooling PuntoServis already supplies. Nothing here is built *for* PuntoServis or shared with them. This is an architectural constraint, not a preference.

**FOUNDER'S STATED PRIORITY — this is now the sprint's north star, verbatim in substance:** have the tool ready for integrations with the PuntoServis store's social accounts *that he himself will administer*, to publish **reels, stories, promotions**, to **move toward TikTok**, and to have **all DM channels attended**, running in parallel to PuntoServis's existing marketing tools.

### THE ASYMMETRY THAT NOW DRIVES EVERYTHING — architect must verify and rule

The founder is **customer zero, publishing to accounts he administers himself.** That is a different legal posture from publishing on behalf of third-party clients, and the existing research costed only the third-party case. Lead's reading, **to be verified, not assumed**:

- **Meta (IG/FB):** an app in Development Mode is usable by people holding a Role on the app (admin/developer/tester); Standard Access covers ~25 test users. If the founder administers the accounts, **he may be able to publish reels/stories/promotions without App Review or Business Verification at all.** If true, the 2–4 month clock **does not block customer zero** — it only blocks selling to third parties later.
- **TikTok:** the gate is different in kind. Per `fase0-zernio-mercado.md` §1.1, an unaudited client publishes everything **`SELF_ONLY` (private)**, enforced server-side via `creator_info`. That blocks him **even on his own account**, because a private promotional post is worthless. His stated intent to "move toward TikTok" therefore hits a real wall the Meta path does not.

**If this asymmetry holds it reorders the whole build:** Meta publishing + DMs is buildable and shippable now, for real use, by customer zero; TikTok publishing is gated behind an audit regardless. That is a concrete, testable claim and it must be settled before any sequencing is committed.

### Consequence for sequencing

This is a **research question before it is a dev question**. Recommend a `/team-research` pass (Colombia entity + WhatsApp Business access path + Colombian SMB/real-estate WTP + finish ManyChat D3/D4/D5) rather than continuing to spend dev capacity on the Meta docs harvest alone. The harvest stays valid and useful either way — it is now *more* useful, since Messaging API is in-scope.

---

## FOUNDER DECISIONS 2026-07-24 (captured post-mortem, one at a time) — apply when limit is raised

1. **Business Portfolio ownership (B0-3 / A5-2): RESOLVED — the FOUNDER owns it, under his own entity.** The store's IG account lives under the founder's own Meta Business Portfolio, not PuntoServis's. Consequence: token custody is designed WITHOUT vendor/partner captivity; the IP boundary with PuntoServis stays clean. C-03 no longer needs the "build with key_id to keep the door open" hedge for ownership reasons (key_id rotation still good practice, but not forced by uncertainty).

2. **"Promociones" scope (B0-2 / W3-Q1): RESOLVED — BOTH, organic first.** Organic promotional posts are day-one (Content Publishing API, covered). Paid advertising (Marketing API, `ads_management`, needs payment method + Business Manager, ZERO repo research) goes to the parking lot as a future item WITH its own research pass. Does not block Sprint 1.

3. **Client-priority steer: PARALLEL, optimize for the SHARED CORE.** Founder's words: *"me quiero enfocar en las features que pueden reusar ambos emprendimientos."* This VALIDATES the existing Tramo 1 shape — multi-tenant foundation, connection layer, organic publishing, poll-first inbox all serve both the store (customer zero) and the realtor (customer one). Store is the test-bed for the shared core, not a detour. Realtor-specific (WhatsApp, multi-agent seats) and TikTok (blocked) stay deferred. Build the common denominator first.

4. **Phase reclassification (B0-6 / A5-3): SIGNED.** Founder approved moving multi-tenant + single-channel inbox out of Fase 6 to Parte 4-A/4-B. **PENDING ACTION (architect-owned, blocked on monthly limit): update CLAUDE.md phase map, and flip ADRs 21/22/24 from PROPUESTO to APROBADO in arquitectura.md.** Lead did NOT edit CLAUDE.md itself — it is the architect's file and this is a doc-section change, not a one-line fix. Founder separately intends to invoke /team-po to reorganize/clean the roadmap — BLOCKED until the monthly spend limit is raised (a fresh /team-po hits the same cap that just killed all five agents).

5. **robertuito licence (B0-4): FOUNDER STEER — research a newer alternative model.** Founder's reasoning: robertuito is old (~2021, roberta-base), so look for a more current model as the alternative rather than just accepting/annotating the licence gap. This is a RESEARCH TASK for the next session (datasci + Hub search), NOT a decision closable now, and it is scoped tighter than "find a newer model" because of what datasci already found: **newer ≠ licensed.** The high-download modern candidates (`cardiffnlp/twitter-xlm-roberta-base-sentiment` and its multilingual variant) ALSO declare no licence; `tabularisai/multilingual-sentiment-analysis` is cc-by-nc-4.0 (the class ADR 13 rejected). So the research brief must require ALL THREE: (a) more current than robertuito, (b) a clean commercial licence (Apache-2.0/MIT), (c) 3-class Spanish social-media sentiment. Meanwhile build the `SentimentProvider` seam anyway (the architect's ruling stands — it converts an unbounded-tail risk into swapping one implementation, and the newer-model search is exactly what the seam exists to absorb). Note the concentration also MOVES to `MoritzLaurer/bge-m3-zeroshot-v2.0` per architect §3.4(b) — that checkpoint needs the same licence test.

**R6 RESOLVED 2026-07-24 by datasci-rm, lead-verified against the live Hub — the three-way constraint IS satisfiable, overturning the prior "no clean swap exists" finding.** The `clapAI` family meets all three (newer + clean licence + 3-class ES-covering): **`clapAI/modernBERT-base-multilingual-sentiment`** (apache-2.0, ModernBERT Jan-2025, 3-class neg/neu/pos, hf-inference live, 87.6K dl) and **`clapAI/mmBERT-small-multilingual-sentiment`** (MIT, Sep-2025, 3-class). Both are label-compatible drop-ins for robertuito → zero SentimentProvider contract change. `bge-m3-zeroshot-v2.0` verified **MIT** (concentration target passes ADR 13). **Load-bearing caveat that must not be buried:** every clean-licensed candidate is multilingual mixed/review-domain, NOT Spanish-social-specific like robertuito (TASS tweets). The swap trades domain-match for licence-clean. Whether that costs accuracy on Uruguayan/Colombian social text is a **golden-set question (~100 labeled comments)** — that measurement is the deliverable, not the model pick. Consequence for B0-4: robertuito's licence stops being an unbounded GA risk (a clean replacement exists and swaps cheaply); it becomes a measurement task, not a procurement dead-end.

## FINAL STATE 2026-07-24 03:47 — full team died to MONTHLY spend limit (not hourly)

All five teammates (`po`, `datasci`, `datasci-2`, `pipeline`, `pipeline-r`, `architect-r`) hit the **monthly** spend limit within ~2 minutes. This is NOT the hourly session-limit outage from earlier — a monthly cap does not reset on the hour. **Respawn is futile until the founder raises the limit** at claude.ai/settings/usage. Lead did not attempt respawn.

**What is DONE and verified on disk:**
- Backlog `docs/backlog-crm-workflows.md` — **979 lines**, all four challenge streams integrated. Both required QG corrections landed: the carousel fabrication is fixed AND documented as an error (§ line 360, 370), poll-first is in (14 refs), B0-4 robertuito swap evidence present. **95 tests pass offline (cold cache), up from 25 at sprint start.**
- All four architect tasks (A1-A4) + A5 asymmetry + login-fork ruling. Login fork = **Facebook Login for Business** (integracion doc §7, 901 lines) — decided because `mentioned_media`/`mentioned_comment` are Facebook-Login-EXCLUSIVE, and losing them would delete the multimodal cascade from the connected-account path.
- Harvest: **84/84 instagram-platform pages, 218 files / 2.6MB across the union, 0 fetch failures.** Notes on disk: `ACCESS-MODEL.md`, `DISCREPANCIES.md`, `LOGIN-FORK-AND-MENTIONS.md`.
- Naming resolved: `tenant_id` canonical (ADR 24a), rename executed across arquitectura.md — docs agree.
- Filter defect (#13) root cause RESOLVED (see task #13): threshold in probability space vs logit_bias-scaled distribution; pinning test landed.

**What is UNFINISHED (blocked by the mass death, not by design):**
1. **QG (#19) — the lead must finish it.** The two corrections landed; final sign-off is lead judgment and needs no teammate. DONE-ABLE NOW.
2. **ADR 25 (login fork) row never landed in `docs/arquitectura.md`.** The architect died before flushing it; the full reasoning IS on disk (integracion §7) but the formal ADR row is missing. Needs architect on respawn, OR founder accepts the §7 reasoning as-is.
3. **Corpus merge NOT executed.** Both trees still coexist: `instagram-platform/` (84, clean) and `documentation/instagram-platform/` (68, 84 files still escaped). **P4/graphify MUST NOT run** — would graph duplicates + mangled `&lt;IG_ID&gt;`. Merge plan is in pipeline-r's messages + LOGIN-FORK notes; needs a pipeline agent. NOTHING LOST — both trees intact.
4. **#9 (D1)** never startable this session (needed the harvest); now unblocked for next.
5. **`oauth_scope.py` scope vocabulary is now wrong** — encodes `instagram_business_*`, but ADR 25 puts us on the Facebook Login `instagram_*` family. datasci task, next session.
6. **App-creation expansion** (`create-an-instagram-app.md` stub) never fetched.

## Respawn order (dependency-correct) — ONLY after monthly limit is raised

1. **pipeline** — unblocked the moment layout is ruled; has the most lost ground to recover and owns the founder's literal ask.
2. **architect** — A2 in flight, plus owes the layout ruling and the schema-v2 decision.
3. **datasci** — #11 code landed; needs tests + `NOTES_fase0_oauth_crm.md` + the #13 failing test. Must still rule out the broken-text-tower hypothesis before any root-cause claim is written down.
