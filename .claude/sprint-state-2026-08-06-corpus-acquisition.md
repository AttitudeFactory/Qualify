# Corpus acquisition feasibility — video bytes for the hook-pattern corpus

**Agent:** corpus-acquisition-check (pipeline). **Started 2026-08-06.**
**Question:** can we get 50 real-estate short videos (Táchira/Cúcuta) as mp4 on disk,
with metrics + `posted_at`, on TikTok and/or Instagram Reels — and at what real cost?

Status legend: `VERIFIED` = measured on this machine today. `BELIEF` = reasoning/doc-derived, not measured.

---

## Q1 — Are the video bytes reachable?

### TikTok: YES — but NOT by the route `packages/scraper` currently implies. `VERIFIED`

Measured 2026-08-06 on this machine. Egress IP `190.108.25.7` (Tecnowind S.A., Montevideo UY,
`dynamic.dedicado.com.uy`) — a **residential/dedicated** IP, not a datacenter one. This matters:
results below may not reproduce from a cloud worker.

**(a) The raw `playAddr` is NOT fetchable. The team lead's suspicion is confirmed.**
`packages/scraper/src/qualify_scraper/parsers/tiktok.py:65-69` puts `video.playAddr` into
`MediaItem.url`. Against a live, freshly extracted CDN URL
(`https://v19-webapp-prime.tiktok.com/video/tos/alisg/...`):

| probe | result |
|---|---|
| plain `GET`, no headers | **HTTP 403**, 420-byte HTML error body |
| `GET` + real Chrome `User-Agent` + correct `Referer` | **HTTP 403**, same |

So headers alone do not open it. `MediaItem.url` is, today, a **non-actionable** field for
download purposes. Nothing in the repo ever exercised it, which is why this was never caught.

**(b) The missing ingredient is a JS anti-bot challenge, not a header.**
`yt-dlp` succeeds and its own log says why:
```
[TikTok] Solving JS challenge using native Python implementation
[TikTok] 7670219334999969054: Downloading webpage with challenge cookie
```
TikTok gates the CDN behind a JS challenge whose solution becomes a cookie. That is
**a moving target maintained by an upstream project**, not something to hand-roll in
`packages/scraper`. Any in-house `httpx.get(playAddr)` will 403.

**(c) `yt-dlp` (2026.07.04, already installed at `/Users/herwin/.local/bin/yt-dlp`) gets the bytes.**
Full download of a real public TikTok post: **4,347,629 bytes of valid mp4 in ~11 s wall clock,
$0, no account, no vendor.** `ffprobe` confirms `duration=49.53`, container `mov,mp4,m4a`.

**(d) It also returns every metric the corpus needs, in the same call** (`yt-dlp -J`):
`timestamp` (epoch -> `posted_at`), `view_count`, `like_count`, `comment_count`,
`repost_count`, `duration`, `description`, `uploader`, `channel`. No second request.

**(e) Account enumeration is free too.** `yt-dlp --flat-playlist -J https://www.tiktok.com/@<handle>`
returns the account's post list with ids. So "N videos from M accounts" needs no search API.

**(f) Known flakiness — real, and it must be designed around.** Three per-video outcomes seen
in one session against 3 URLs: one clean success, one
`Unable to extract universal data for rehydration`, one
`Your IP address is blocked from accessing this post`. The successful one was a **recent** post
taken from the live account listing; the two failures were older hardcoded ids. Working
hypothesis (`BELIEF`, not measured): freshness and/or per-post gating, not a blanket IP ban —
the account listing and the download both worked from the same IP minutes apart. Practical
consequence: **assume a per-video failure rate and over-enumerate.** Do not build a runner that
assumes 50 URLs in = 50 files out.


### Instagram Reels: NO, not anonymously. Needs a logged-in cookie jar. `VERIFIED`

| probe | result |
|---|---|
| `yt-dlp -J` on two real-looking reel shortcodes | `Instagram sent an empty media response` |
| **control:** same call on an obviously fake shortcode `ZZZZZZZZZZZ` | **byte-identical error** |
| anonymous `GET https://www.instagram.com/instagram/` with a real Chrome UA | HTTP 200, 610 KB |

The control is the load-bearing part: Instagram returns the *same* refusal for a real post and a
nonexistent one, so that error carries **no information about the post** — it is a blanket
logged-out refusal. The 200-OK profile page confirms it from the other side: 610 KB containing
`PolarisLoggedOut` x10, `PolarisProfile` x4, `<title>Instagram</title>`, and **zero** occurrences
of `og:title`, `og:description`, `"username"`, `"video_versions"` or `edge_owner_to_timeline_media`.
It is an empty logged-out shell. Meta serves anonymous visitors no content at all.

**Consequence:** on IG there is no free anonymous path — not to the bytes, not to the metrics, not
even to enumerate an account's posts. Every IG route costs either an authenticated session or a
vendor.

### Q1 verdict

**Build the pilot on TikTok.** TikTok is free, fast, complete and available today; Instagram needs
either a logged-in cookie jar (account-ban risk, manual, fragile) or a paid vendor. If the
handle-sourcing agent reports the niche lives on Instagram, this verdict flips to "paid vendor
required" and the cost/effort picture changes materially — that is the single biggest thing that
could still stop the plan.

## Q2 — Costed acquisition path

### Is a Zyte key configured here? **No.** `VERIFIED`
`ZYTE_API_KEY` appears in exactly one place in the repo — `client.py:48`, `os.environ["ZYTE_API_KEY"]`.
It is **not** in the process env, not in `.env` or `.env.bak` (which carry only `QUALIFY_META_*`),
not in `.claude/settings*.json`, `justfile`, `pyproject.toml` or `docker-compose.yml`. There is no
`~/.config/scrapinghub` either. `ZyteApiTransport` would raise `KeyError` on construction today.
Using Zyte at all requires a signup first.

### What the existing Zyte path gives us toward the corpus
`ZyteScrapingClient` → `extract_tiktok_hydration` → `parse_tiktok` yields a `Post` carrying
**everything except the bytes**: `posted_at` (`createTime`), `views` (`playCount`), `likes`
(`diggCount`), `comments_count`, `shares`, `caption`, `duration_ms`, `creator_handle`. That half is
real and tested. Two gaps make it insufficient on its own:

1. **It cannot produce the mp4.** Its only media output is `MediaItem.url` = `playAddr`, which
   Q1(a) measured at HTTP 403. Zyte gets us metadata, then we still need a byte-fetch route.
   *(Untested option worth naming: re-issuing the CDN URL back through Zyte's own proxy might
   succeed where our direct GET 403s. Nobody has tried it; it costs money to try.)*
2. **There is no account enumeration.** `ScrapingClient` exposes only
   `fetch_hydration(url: str)` — one post at a time. "50 videos from 3 accounts" needs a
   list-an-account's-posts capability that does not exist in `packages/scraper` in any form.

### Cost comparison for a 50-video pilot

| route | money | engineering | gets bytes? |
|---|---|---|---|
| **yt-dlp** | **$0** | ~half a day (thin runner, no auth, no signup) | **yes, measured** |
| Zyte (existing client) | unpriced per-request here; PAYG plan, 50 requests is noise | signup + account-enumeration (absent) + byte-fetch still unsolved | **no** |
| Data365 / Apify | 50 posts = 50 records = **$0.03**; with 50 comments each, 2,550 records = **$1.53** (Data365 @ $0.60/1K) | new client, new auth, new signup, new payload parser — days | **unverified** |

**The team lead's hypothesis is correct and the margin is not close.** The entire vendor delta
across all three routes is **under $2**. Engineering time dominates by two orders of magnitude.

**Correction to `packages/models/src/qualify_models/hooks/corpus.py` (datasci's file, not edited by me):**
its `DATA365_USD_PER_1K_RECORDS` arithmetic prices **metadata records**. It is silently assumed that
paying for a record also yields a downloadable video. Q1 shows the byte-fetch is a *separate,
non-trivial* problem on both platforms, so the `~$6.64` figure is a floor for metadata, not a price
for a corpus. The module's own house rule ("an unsourced rate is `None`, not a guess") argues for
naming byte-acquisition as its own unpriced line rather than leaving it implied.

### Two stale-code findings for whoever owns the scraper roadmap `VERIFIED`

1. **`extract_instagram_hydration` targets a format Meta no longer ships.** It regexes
   `window._sharedData` (`extract.py:19-22`). The live logged-out `instagram.com` page fetched today
   contains **zero** occurrences of `_sharedData`. Against any real 2026 page it raises
   `HydrationExtractionError`. It passes tests only because the fixture encodes the dead format.
2. **The HTML fixtures are synthetic, not captured pages** — `instagram_reel.html` is **815 bytes**
   and `tiktok_video.html` is **687 bytes**. Real hydration pages are hundreds of KB. So
   "the extractors are tested" means "tested against hand-written minimal HTML"; neither has ever
   met a real page. This is the same class of gap as the never-exercised `MediaItem.url`.

## Q3 — Corpus runner design review

datasci's proposal — `packages/scraper/src/qualify_scraper/harvest.py`, output
`corpus/<account>/<post_id>.mp4` + `corpus/metrics.csv` with
`source_id, account_id, posted_at, likes, comments, views` — is **sound in shape**; the CSV columns
do match what `hooks/analysis.py::PostObservation` consumes. Eight changes I would make before it
is written. **Not implemented — Q1 is positive but the platform decision is still open.**

1. **Namespace it away from production, and make yt-dlp an optional dep.** yt-dlp is a research
   tool tracking an adversarial moving target; it must never become importable from the Parte 2
   production path. Put it at `qualify_scraper/research/harvest.py` with `yt-dlp` in an optional
   `[dependency-groups] corpus`, so a default `uv sync` does not pull it — the same isolation
   `packages/models` uses for `ml`.
2. **Keep the repo's Protocol seam.** Define `VideoFetcher` with
   `enumerate_account(handle, limit) -> list[PostRef]` and `fetch(ref, dest) -> FetchedVideo`;
   implement `YtDlpFetcher`; test with a `FixtureFetcher`. Mirrors
   `ScrapingClient`/`FixtureScrapingClient` exactly, keeps the suite offline, and leaves Zyte or
   Data365 swappable in later without touching the runner.
3. **Add `duration_seconds` to `metrics.csv`.** `PostObservation` has the field, and yt-dlp returns
   `duration` for free. Omitting it means re-deriving it from the mp4 later.
4. **`follower_count` needs a separate per-account fetch — it is NOT in the per-video payload.**
   `VERIFIED`: `channel_follower_count` came back `None`. Put it in a second
   `corpus/accounts.csv` (`account_id, handle, follower_count, fetched_at`) rather than
   denormalizing one per-account number onto every post row.
5. **Make it resumable and idempotent.** Skip any post whose mp4 exists and whose row is already in
   `metrics.csv`. Given the per-video failure rate in Q1(f) plus a long download loop on a flaky
   residential connection, a runner that cannot resume will be run from scratch repeatedly — which
   multiplies the ban risk it should be minimizing.
6. **Write `corpus/failures.csv`.** A run that quietly ends with 43 of 50 files, with no record of
   which 7 failed or why, is exactly the silent-partial-success failure this investigation exists to
   prevent. Over-enumerate (~1.3x target) to absorb the loss.
7. **Capture metrics in the same pass as the bytes, and stamp `fetched_at`.** `views`/`likes` drift
   continuously; a download-now/metrics-later design silently mismatches outcome to hook.
8. **Dump yt-dlp's full `-J` JSON to `corpus/<account>/<post_id>.json`.** Same principle as ADR 18's
   raw-payload rule — re-fetching is not free in time or in ban risk — but as a plain file. Do
   **not** drag in `RawPayloadEnvelope`/R2/`brand_id`: that is the production path and pulls Parte 3
   scope into a research script.

Also: `posted_at` must come from yt-dlp's `timestamp` (epoch UTC), **not** `upload_date`, which is
date-only and discards time-of-day.


## Residual risks / what is NOT proven

- **Platform decision is the pivot.** Everything above says "TikTok, free, today". If the
  handle-sourcing agent finds the Táchira/Cúcuta real-estate niche lives on **Instagram**, the free
  path disappears and the plan needs either a logged-in cookie jar (account-ban risk, manual,
  fragile) or a paid vendor whose byte-delivery is itself unverified. **This is the single biggest
  thing that could still stop the corpus.**
- **Enumeration is proven on a mega-account, not on a small regional one.** `@khaby.lame` worked;
  five *guessed* real-estate handles failed — but an obviously-fake control handle produced the
  byte-identical error, so those failures mean "handle does not exist", not "blocked". The
  mechanism (secUid scraped from the profile page) is size-independent, so this is low risk, but it
  is untested on a real target account. Re-test the moment real handles land.
- **IP dependence.** All measurements were taken from a residential Uruguayan IP
  (`190.108.25.7`, Tecnowind S.A.). TikTok treats datacenter ranges far more harshly; none of this
  is evidence that a cloud worker could do the same. For a 50-video research pilot run from the
  founder's own machine, that is fine — as a production claim it is worthless.
- **ToS.** yt-dlp against TikTok is a research-corpus tool. It is not a production ingestion path
  and must not be presented as one, nor left where production code can import it (Q3.1).
- **Not measured:** whether Zyte's proxy can fetch the CDN URL our direct GET 403s on; whether
  Data365/Apify actually deliver downloadable video bytes. Both cost money to settle.

---

# ADDENDUM (same session) — the platform pivot fired. Read this before the sections above.

`docs/corpus-candidatos-inmobiliario-tachira-cucuta.md` landed while this was in flight. It puts
**~11 of ~12 candidate accounts on Instagram**. The "build the pilot on TikTok" verdict in Q1 was
written before that doc existed, and is now conditional. Re-measured against the real niche:

### A1. The one dual-platform account is real, active, and deep. `VERIFIED`

The handles doc lists `@inmobiliarialunaroman` (TikTok side of C4) as **"TikTok no verificable"**
and dates it "publica desde 2022 al menos". **Both of those are now superseded by measurement:**

| measurement | result |
|---|---|
| `yt-dlp --flat-playlist` enumeration | **365 videos** in the catalogue |
| most recent post | **2026-07-26** (11 days old) — the account is **active**, not dormant |
| end-to-end download of a real niche video | **5,700,914 bytes** of valid mp4, 59 s, in ~4 s, $0 |
| metrics returned in the same call | `timestamp`, `view_count`, `like_count`, `comment_count`, `repost_count`, `duration` |
| content | exactly the niche — Cúcuta listings: Guaimaral, Caobos, Prados del Este, Ceiba II, Quinta Vélez |

**So the full acquisition chain is proven end-to-end on a real target account, not just on a test
account.** 365 videos is 7x the 50-video pilot and 1.7x the full 217-video plan, from one handle.

**Method note for the handles agent:** their doc concludes TikTok profiles carry "cero métricas"
because their tool only retrieved the page title (`tiktok.com/@x` is client-rendered). That is true
of an HTML fetch and false of the acquisition path — `yt-dlp --flat-playlist -J` returns the full
post list, and `yt-dlp -J` per post returns follower-independent metrics. **Their R2 criterion
("30+ vídeos") is machine-verifiable for TikTok handles after all, and does not need the ~2 min of
manual browser work per account they budgeted.** Route this to them.

### A2. The blocker is no longer the bytes. It is account count and engagement variance.

Two problems the acquisition path cannot solve, and both are worse than the download question:

1. **One TikTok account is not a corpus.** `plan_corpus(min_accounts=8)` in
   `qualify_models/hooks/corpus.py` exists precisely because *"a hook type appearing in fewer than 3
   accounts is that account's house style, not a pattern."* On TikTok this niche currently yields
   **one** account. 365 videos from a single advertiser measures that advertiser's template, not a
   hook effect — and its captions are visibly templated
   (`🏡✨ CASA EN VENTA – <BARRIO> ✨ 🆔 ÍTEM: <n>`). A 50-video single-account pilot would be
   confounded by construction.
2. **The engagement signal is very thin at this account size.** The downloaded post: **750 views,
   8 likes, 0 comments.** `PostObservation.engagement` ("likes + comments") would be **8**. At that
   magnitude the outcome variable is dominated by integer noise, and `plan_corpus`'s
   `detectable_effect_d=0.8` power calculation assumes a continuous outcome with real variance.
   This should go to datasci before any corpus is collected — it may change the outcome metric
   (e.g. views-per-follower) or the account-size floor for inclusion.

### A3. Revised verdict

- **Q1 (can we get the bytes?) — YES on TikTok, proven on the real niche account, $0.** That
  question is closed and positive.
- **But the corpus as specified (50 videos / 3 accounts, growing to 217 / 8) cannot be built on
  TikTok alone**, because the niche only has one TikTok account. It can be built on Instagram,
  where the accounts are — and Instagram costs either an authenticated cookie jar or a vendor.
- **Recommended next step, and it is cheap:** re-run the A1 enumeration against every remaining
  handle in the candidates doc to check whether any of the IG-listed accounts also has an
  unlisted TikTok presence. That is free, takes minutes, and is the only thing that could still
  make the free path viable. **Not done — needs the handle list confirmed first.**
- **Not attempted, deliberately:** `yt-dlp --cookies-from-browser` for Instagram. It reads the
  founder's personal Chrome cookie jar and puts his own IG account at ban risk. That is his
  decision to make, not mine.

---

# ADDENDUM 2 — the free path survives. Three TikTok accounts, not one. `VERIFIED`

Ran the A3 recommendation (enumerate every candidate handle against TikTok). The candidates doc
classifies accounts by the platform where they were *found*; it does not follow that they are
absent elsewhere. Measured today, `yt-dlp --flat-playlist --print id | wc -l`:

| handle | doc says | **TikTok videos (measured)** |
|---|---|---|
| `@inmobiliarialunaroman` | IG **and** TikTok (TikTok "no verificable") | **365** |
| `@inmobiliariamarelsa` | **IG** | **196** |
| `@inmobiliariatonchala` | **IG** | **150** |
| `@tachirainmuebles` | IG | 5 (too few) |
| `@tu_hogarcucuta`, `@haddad_inmobiliaria`, `@carlosjimenezbienesraices`, `@casa_facil_sc`, `@alquileres.ventastachira` | IG | 0 |

**`@inmobiliariamarelsa` and `@inmobiliariatonchala` are listed as Instagram-only in
`docs/corpus-candidatos-inmobiliario-tachira-cucuta.md` and both have substantial TikTok
catalogues.** That doc needs correcting — the correction belongs to its owner, not to me.

**Three accounts x 150+ videos = 711 available. The 50-video / 3-account pilot is fully covered on
TikTok, free.** Recency confirmed: `@inmobiliariamarelsa`'s latest post is **2026-08-04** (2 days
old), `@inmobiliarialunaroman`'s is 2026-07-26. Both active.

### The two numbers that should drive the next decision

**1. Per-video metadata success rate is ~50%, not ~90%.** `VERIFIED`: of 12 consecutive video ids
enumerated from `@inmobiliarialunaroman`, **6 returned metadata and 6 failed.** Enumeration is
reliable; per-video detail is not. Consequence: **budget ~100 attempts per 50 wanted videos**, and
the runner's resume/failure-log design (Q3.5, Q3.6) moves from "good practice" to **mandatory**.
Cost stays $0; wall clock roughly doubles.

**2. Engagement is thin but not degenerate.** Six-video sample from `@inmobiliarialunaroman`:

| posted | views | likes | comments |
|---|---|---|---|
| 2026-07-26 | 750 | 8 | 0 |
| 2026-07-22 | 426 | 2 | 0 |
| 2026-07-16 | 1084 | 10 | 1 |
| 2026-06-25 | 524 | 10 | 0 |
| 2026-06-25 | 1324 | 14 | 3 |
| 2026-06-25 | 383 | 4 | 0 |

`likes + comments` spans **2 to 17** (distinct values: 2, 4, 8, 10, 11, 17); `views` spans
**383 to 1324**. So there *is* spread — but at n=50 with integer outcomes in a 2-17 band, ties will
dominate and the `d=0.8` power assumption in `plan_corpus` is optimistic.
`analysis.py::_percentiles` handles ties by mid-rank so it degrades gracefully rather than breaking.

**Recommendation for datasci (not my call to make):** consider **views** as the primary outcome
rather than `likes + comments`. Views have ~3.5x range and finer resolution on exactly this corpus;
likes are single/low-double digits where a +/-2 difference is indistinguishable from noise. This is
a measurement offered to the outcome-metric decision, not a decision.

### Final verdict

**Yes — 50 real-estate videos with metrics and `posted_at` can be on disk, on TikTok, for $0 in
vendor spend and roughly half a day of engineering, using `yt-dlp` behind a `VideoFetcher` Protocol
in a research-namespaced runner.** No Zyte key, no Data365, no signup, no Instagram.

The single biggest remaining risk is **not** acquisition. It is that three accounts is the floor of
`plan_corpus(min_accounts=8)`, and that the engagement signal at these account sizes may be too
coarse to carry a hook-pattern effect at all. Both are analysis-design questions, not pipeline ones.

---

# BUILD (same session) — the corpus runner is written, tested, and proven live

Lead gave GO on TikTok. Built, not committed.

**Files** (all under `packages/scraper/`, nothing else touched):
- `src/qualify_scraper/research/__init__.py` — namespace docstring stating the isolation rule
- `src/qualify_scraper/research/harvest.py` — `VideoFetcher` Protocol, `YtDlpFetcher`, `harvest_corpus`
- `tests/test_harvest.py` — 16 offline tests via a `FixtureFetcher` double, no network
- `pyproject.toml` — new optional `[dependency-groups] corpus = ["yt-dlp>=2026.7.4"]`
- `README.md` — new "Known issues" section (the three measured Parte 2 defects)

**Gate:** `ruff check` clean, **77/77** scraper tests pass (`uv run --no-sync pytest packages/scraper/tests`).

### Live proof against real niche accounts

Four runs against `@inmobiliarialunaroman` + `@inmobiliariamarelsa`, never the full pilot:

| run | harvested | failed | skipped | success rate |
|---|---|---|---|---|
| 1 (cold, 1 account, target 4) | 4 | 1 | 0 | 0.80 |
| 2 (+2nd account, target 4 each) | 5 | 4 | 3 | 0.56 |
| 3 (resume) | 1 | 0 | 7 | 1.00 |
| 4 (full resume) | 0 | 0 | 8 | n/a (0 attempts) |

**10 real mp4s on disk, 10 metrics rows, 5 failure rows, 2 account rows.** `ffprobe` confirms every
mp4 is a valid video with the expected duration. Resume verified live: run 4 made **zero** download
attempts. Retry-only-what-failed verified live: run 3's single harvest was run 1's failed video,
succeeding on retry.

### Corrections to my own earlier numbers

1. **The ~50% success rate was measured on the wrong path.** That figure came from metadata-only
   `yt-dlp -J`. The runner's actual path (`--write-info-json` + download, which solves the JS
   challenge) scored **0.80, 0.56 and 1.00** across runs — call it **~60-70%**, not 50%. The
   `attempt_multiplier=2.0` default is therefore conservative rather than barely adequate. Failures
   are transient: the same video that failed in run 1 succeeded in run 3, which is why
   retry-on-rerun matters more than a high first-pass rate.
2. **`follower_count` is unavailable, full stop.** `VERIFIED`: absent from the flat-playlist payload
   *and* from every per-video payload (zero keys matching `follow*`). `playlist_count` is null too.
   The `accounts.csv` column exists and is left **empty** rather than defaulted to 0 — filling it is
   ~30 s of manual browser work per account, 3 accounts for the pilot.

### A bug I introduced and fixed

`accounts.csv` appended blindly, so every re-run added a duplicate account row — 5 rows for 2
accounts after three runs. Any consumer joining on `account_id` would have fanned out. **Caught by
running it live, not by the original 13 tests**, which is the argument for proving on real data
rather than stopping at green. Fixed with an upsert keyed on `handle`; three regression tests added.

### Estimate

Half a day held — roughly 3 h including the live verification. No change.

---

# ADDENDUM 3 — the denominator behind "only three accounts", and its limits

**What "only three" was actually measured over.** The 9 non-rejected candidate handles
published in `docs/corpus-candidatos-inmobiliario-tachira-cucuta.md` as of 04:30 today. That file
is byte-unchanged since (verified). The 4 handles I did **not** probe were the doc's own explicit
geographic rejects — `@sc_inmobiliaria` (San Cristóbal, **Argentina**), `@realestate_octavio`
(Mexico), `@inmobiliaria_habitatrd` (Dominican Republic), `@ruthquirozrealtor` (Bogotá) — correctly
excluded as out-of-region, not overlooked.

So the denominator is **the sourcing agent's published list at one moment**, not the niche.

**And it is a lower bound, for a reason worth knowing.** I probed TikTok using the *Instagram*
spelling of each handle. Handles are not stable across platforms. Re-probing spelling variants
found one account the exact-match pass had missed:

| variant probed | result |
|---|---|
| `@tuhogarcucuta` (IG spells it `@tu_hogarcucuta`) | **4 videos** — a real account the first pass scored 0 |
| `@carlosjimenezbienesraices` + 3 variants | 0 across all — the doc's "ideal candidate by form" genuinely has no TikTok presence |
| `@haddadinmobiliaria`, `@casafacilsc`, `@alquilerventastachira` | 0 |

`@tuhogarcucuta`'s 4 videos are far below any useful threshold, so **the working count of usable
TikTok accounts stays at three** (365 / 196 / 150). But the method caveat stands: **a same-spelling
probe under-counts, so "three" is a floor.** Any new handle should be probed with variants
(underscores removed/added, `_inmobiliaria`/`inmobiliaria_` reordered) before being called absent.

**Consequence to keep in front of datasci:** `plan_corpus(min_accounts=8)` is not merely expensive
in this region on TikTok, it is **unreachable at the currently known denominator** — and its own
rule (a hook type must appear in >=3 accounts to be a pattern rather than house style) has **zero
headroom** above the pilot at n=3. That is a study-design constraint, not a budget one. The
denominator can still move: the sourcing agent has been redirected toward content-style accounts,
and re-probing is free (~30 s/handle).

---

# ADDENDUM 4 — contract fix after datasci made views the primary outcome

`ds-hooks-spike` accepted views as the primary outcome (`Outcome.VIEWS`,
`PostObservation.views`, `engagement_rate` that returns `None` rather than 0 when views are
absent — "an empty denominator is a missing measurement"). That decision exposed a defect in **my**
writer that was harmless before and is not harmless now.

**The bug:** `_post_from_info` did `int(info.get("view_count") or 0)`. That idiom collapses a
*missing* metric into `0`. Since views is now both the primary outcome and the `engagement_rate`
denominator, an unreported view count would have been written as `0` and would have ranked that
post as the worst in its library — exactly the imputation datasci's `None` rule exists to prevent.
Their guard would never have fired, because my CSV never handed them a blank.

**Fixed:** `likes`, `comments`, `views` are now `int | None`; a missing metric is written as an
**empty cell** and a genuine zero is written as `0`. Two tests pin both directions
(`test_missing_views_is_empty_not_zero`, `test_genuine_zero_metric_is_preserved_as_zero`).
`ruff` clean, **79/79** scraper tests pass.

**Worth noting as a pattern:** this is the second defect in this module found by something other
than the test suite — the first was the `accounts.csv` duplicate append (caught by running live),
this one by a downstream consumer changing what a column means. Neither was a coding error at the
time it was written; both became wrong when the surrounding contract moved.

### A framing correction I owe the record

I reported "views span 383-1324, ~3.5x range" as evidence the outcome variable has usable spread.
datasci's pushback is correct and I accept it: **range is resolution, not dispersion.** Six videos
can measure whether the metric has fine enough granularity to break ties; they cannot measure
whether it varies enough to carry an effect. A compressed within-account band is equally consistent
with the platform simply not differentiating those videos. Their `assess_viability()` gate, which
runs before any correlation and can veto it, is the right place for that question — and it is the
pilot's to answer, not mine. Anywhere above where I imply the 3.5x range de-risks the outcome
metric, read it as resolution only.

---

# ADDENDUM 5 — sampling strategy, added after datasci's variety reframe

datasci reframed the binding constraint: **not how many accounts exist, but whether openings vary
*within* an account.** Eight template advertisers fail exactly as three do. That has a direct
consequence for the runner that neither of us had noticed.

**The runner was sampling in the worst possible way for that question.** Enumeration returns
newest-first, so taking the head is a *recency* sample. Measured on `@inmobiliarialunaroman`:

- 365 posts spanning **2022-04-29 to 2026-07-26 = 1,549 days (4.2 years)**
- the 34 most recent cover **67 days = 4.3% of the span**
- the 50 most recent cover **95 days = 6.1%**

A 50-video pilot would have measured one ~3-month window of one advertiser and reported it as that
account's variety. That biases the variety verdict in an unknown direction: it can report no
variety where the account changed style over the years, or report variety that is really two
adjacent campaigns.

**Added `strategy: "spread" | "recent"`, defaulting to `spread`** — evenly spaced across the whole
catalogue, with the over-enumeration backups appended *after* the primary picks so a run that stops
at target has still spanned the full range. (First implementation got this wrong: spreading all
candidates evenly meant stopping at target covered only the newest half. Caught by a test asserting
the oldest post is reached.)

**Verified live.** A `spread` run over the same account returned posts dated
**2022-04-29, 2025-05-28, 2026-03-24, 2026-07-26** — the full 4.2 years, against the recency
sample's one month.

### The tradeoff it exposed, which is itself a finding

**Fetch success is not uniform across a catalogue: old posts fail materially more often.**
Recency-sampled runs scored 0.56-0.80; the spread run reaching back to 2022 scored **0.40** and
exhausted its 10 candidates without reaching a target of 5. So `attempt_multiplier` default is
raised **2.0 -> 3.0**. Practical planning number: a spread pilot of 50 videos should expect
~125 attempts and roughly 45-60 min, not the ~25-30 min I quoted for recency.

`ruff` clean, **84/84** scraper tests.

---

# ADDENDUM 6 — the seam is now verified with REAL data on both sides

datasci built `hooks/join.py`, the consuming half. Both sides were still tested only against their
own fixtures, which is the exact shape of the three bugs already found here. So I ran **their real
loader against my real corpus output**. No code changed; this is verification, not a fix.

**Test 1 — the happy path, real 10-video corpus.**
`join_observations(corpus_smoke/metrics.csv, hook_features.csv, window_seconds=3.0)` with a
hook-features file deliberately missing one id:

- 10 real metrics rows -> **9 observations, `join_rate` 0.9**
- the omitted id correctly reported in `missing_hook_features`, not silently dropped
- `views=750.0`, `engagement=8.0`, `posted_at=2026-07-26` parsed as a `date`

**Test 2 — the blank-cell contract, which no real post has exercised yet.** Every post in the real
corpus reported its views, so the `None` path had never met real data. Injected blanks into a copy:

| injected | result |
|---|---|
| `views` = "" | **`views=None`** — not 0, not a pydantic rejection |
| `comments` = "" | **`engagement=None`** — the composite correctly refuses to sum a missing component |

**Both halves hold.** Worth recording *why* this needed checking: datasci's note that
`PostObservation.views` is `float | None` means an empty cell read by a naive `csv.DictReader`
arrives as `""` and **pydantic would have rejected it**. So between my fix and their loader there
was a window where my corpus was correct and unloadable. Neither side's suite could see that; only
running one against the other could.

**Standing lesson, now with four instances behind it:** every defect found in this module came from
outside it — a live run, a consumer changing a column's meaning, a consumer reframing the question,
and now a cross-package contract. The suite was green through all four. This module's correctness
is mostly held in contracts owned elsewhere, so its own tests structurally cannot certify it. The
cheap countermeasure is the one used here: periodically run the real producer against the real
consumer, with real data.

Accepted from datasci, no action: my "2, 2, 4, 8, 10, 14 collides at n=6" is **illustration, not
evidence** — six draws from 13 values collide about half the time by chance. The pigeonhole
counting bound carries the argument; my sample does not add to it.

---

# ADDENDUM 7 — bounded spread implemented (datasci's call), plus two corrections to their numbers

datasci chose **`spread` bounded to a recency window, 12 months**, on the confounding argument:
full-catalogue spread maximises observed variety *and* the chance hook type is a proxy for date, in
which case regressing out the time trend removes the hook effect with it.

**Implemented:** `max_age_days: int | None = 365` alongside `strategy`. `ruff` clean, **92/92**.

**It costs no extra requests.** TikTok ids are snowflake-style — the high 32 bits are a unix
timestamp — so every post's age is knowable **from enumeration alone**. `_tiktok_posted_at()`
decodes it, so the window filters *before* spending a fetch. 365/365 ids decoded (100%). Posts of
unknown age are **kept**, so a platform without timestamped ids degrades to no filtering rather
than to an empty corpus.

### Correction 1 — the id timestamp is approximate

Decoded 21:24:31 against the payload's own `timestamp` of 21:24:23 — **8 s apart** (id-minting vs
publish time). Irrelevant to a 365-day bound, unacceptable as an analysis timestamp. So
`PostRef.posted_at` is a **filter input only**; `metrics.csv` always carries the exact `timestamp`
from the fetched payload. Test asserts closeness, not equality.

### Correction 2 — the 12-month window is far richer than estimated

datasci projected ~86 posts/year (365 posts / 4.2 years). **Measured: 269 posts within 365 days**,
316 within 730. Posting rate is not uniform — the account has accelerated sharply. So the window
holds ~16x what a 17-per-account pilot needs, not 5x. The bound costs nothing in sample
availability.

### The finding that matters most here: **achieved span != requested span**

A live bounded run (`target=6`, `spread`, `max_age_days=365`) harvested 6/6 but returned posts
spanning **2026-01-13 to 2026-04-21 — 98 days, not 365.** The picks at both ends of the window
failed and only interior backups survived. At a ~50% failure rate this is normal, not a one-off.

**Consequence:** the requested window is an *intent*; only the achieved span describes the corpus.
Anything reasoning about time-confounding — datasci's `hook_temporal_separation()` in particular —
must read the span the corpus actually has. So `HarvestReport` now carries `earliest_posted_at`,
`latest_posted_at` and `achieved_span_days`, and a run that silently narrows is visible instead of
assumed.

### Success rate under the bound

Their prediction (a 12-month bound should raise the 0.40 full-catalogue rate, since failures
concentrate on old posts) is **directionally confirmed but modest**: **0.50** bounded vs 0.40
unbounded vs 0.56-0.80 recency. Target was still met. `attempt_multiplier=3.0` remains right.

---

# ADDENDUM 8 — bound reversed to unbounded; real corpus committed as a shared fixture

**1. `max_age_days` default reverted 365 -> `None` (full catalogue).** datasci reversed their own
12-month call on an argument from the lead: the pilot's job is to *falsify* "this niche never
varies", full-catalogue spread is the most generous test of that, and a negative from the most
generous test is the most informative negative. A bound weakens exactly the test that most needs
power — "no variety" in a narrow window cannot separate *no repertoire* from *window too short*.
The confound is handled by **measuring** temporal separation rather than pre-empting it, and that
measurement then sets the corpus phase's window instead of it being guessed.

**This needed action even though their message said "nothing for you to change".** I had already
shipped the bound *as the default*, so doing nothing would have run the pilot silently bounded to
365 days — the opposite of the decision. The parameter stays (the corpus phase wants it); only the
default moved. Settled shape: **pilot unbounded, corpus bounded by measurement.**

**2. Real corpus committed as a fixture:** `packages/scraper/tests/fixtures/corpus/metrics.csv`
(the real 10 posts from `@inmobiliarialunaroman`, 2026-08-06) and `accounts.csv`. Absolute
scratchpad paths in `video_path` were rewritten repo-relative so the fixture is portable; every
other value is exactly what the runner produced. datasci will commit the same file on their side
and load it in `join`'s suite.

Why this closes a real gap: their fixtures test *their reading* of the format; mine tested *my
writing* of it. Neither tests the format. Two new tests here pin the column tuple and the
`posted_at` encoding against the real file, so a rename or re-encoding fails at the seam rather
than at pilot time.

`ruff` clean, **94/94**.

**3. Noted from datasci, no action:** two bugs in their analysis code (recency-adjustment ranking
floating-point noise into a confident ordering; a Spearman residual check that reads ~0 against a
symmetric U and so would have passed the exact non-monotone drift it was built to catch). Both are
the same shape as my `int(x or 0)` and their `> 0.5` threshold — **a guard aimed at the right
hazard, positioned where it can never fire.** That is now four instances of that specific failure
mode across two packages in one day, which is worth more attention than any individual fix.

**4. Open, deferred by agreement:** age-biased fetch success (0.40 unbounded vs 0.56-0.80 recency)
is to be *measured, not modelled* — compare the requested-date distribution against the achieved
one at the end of the pilot. `HarvestReport.achieved_span_days` plus `failures.csv` already carry
what that needs; no design change now.

---

# ADDENDUM 9 — `requested_span_days` + `span_coverage`, so the gate works on the UNBOUNDED pilot

datasci wired the span-shortfall finding into their gate: `hook_temporal_separation(...,
requested_span_days=N)` now returns `min_span_coverage` and `negative_findings_interpretable`, with
the asymmetry stated — **a positive finding survives low coverage, a negative one does not**, and
since the pilot exists to falsify the pessimistic hypothesis, an uninterpretable negative is its
worst outcome (looks decisive, isn't).

**They asked me to pass `requested_span_days` from `HarvestReport`. I wasn't recording it — and for
the unbounded pilot there was no obvious value to pass at all.** That gap would have left their new
check undefined for exactly the run we are about to do.

Added, with the unbounded case handled honestly:

- **bounded run** -> `requested_span_days = max_age_days`.
- **unbounded run** -> the **age range of the candidate population actually on offer**. An
  unbounded run still requested something: everything available. This is free, because enumeration
  already decoded every post's date via the snowflake id.
- `HarvestReport.span_coverage` = achieved / requested, capped at 1.0, `None` when either is
  unknown. On the measured live case (365 requested, 98 achieved) it reads **0.27**.

`ruff` clean, **98/98**.

### Their correction to my suggestion, which was right

I had said their function "should read the achieved span rather than assume the window". It already
computed achieved span from observed posts and never assumed the window — what was missing was the
**comparison**, because it had no idea what had been *requested* and so could not tell a 98-day
corpus designed as 98 days from one designed as 365. The fix belonged on my side, not theirs.

### Accepted from them

Both my corrections stand: their ~86 posts/year came from a sound division over an unsound
uniform-rate assumption (measured 269 within 365 days), and **the same assumption would have bitten
a corpus plan, not just a window estimate**. And the snowflake timestamp stays a filter input only.

They also named the payoff of the id-decoding trick better than I did: filtering before spending a
fetch makes the corpus window **free**, which is what turns "let the pilot choose the width" into a
cheap plan rather than an expensive one.

### Fixture — already delivered

`packages/scraper/tests/fixtures/corpus/metrics.csv` + `accounts.csv` were committed in Addendum 8;
their request for it crossed with my message. Nothing outstanding.

---

# FINAL — stand-down 2026-08-06. Both requested acknowledgements verified on disk.

Lead ordered a stop: the binding constraint is the founder naming the three accounts, and
until then further refinement is polish on a pipeline that has never met its corpus. No further
changes to `packages/scraper`. Final state: `ruff` clean, **98/98**, **nothing committed**, pilot
never run.

The two things the lead asked to be recorded durably were **checked and both were missing** from
`packages/scraper` — they existed only in this sprint-state file, or (for one) buried in a property
docstring where no reader of the corpus would find it. Both are now in the package, in two places
each (module docstring + README):

1. **The named defect pattern** — "a guard aimed at the right hazard, positioned where it can never
   fire", with all four 2026-08-06 instances listed (my `int(x or 0)` and recency sampling; their
   `> 0.5` threshold and Spearman check), the fact that **all four sat under green suites**, and the
   countermeasure: *write the test that makes the guard trip — feed it the input that should
   trigger it and assert it did; if you cannot construct that input, that is the finding.*
2. **The uninterpretable-negative risk** — under a "Reading the pilot's output" heading in both
   places, so it sits where the corpus is read rather than in a message: three accounts at zero
   margin against the >=3-accounts-per-type rule, plus span shortfall (365 requested -> 98
   achieved), and the asymmetry that a positive finding survives low coverage while a negative one
   does not.

## Resumption instructions for whoever picks this up

- **Pilot config, final:** unbounded (`max_age_days=None`), `strategy="spread"`,
  `attempt_multiplier=3.0`, `uv run --no-sync`, **never a group sync** (see the venv trap in
  the module docstring). Expect ~125 attempts, 45-60 min, $0.
- **Three usable TikTok accounts:** `@inmobiliarialunaroman` (365 videos), `@inmobiliariamarelsa`
  (196), `@inmobiliariatonchala` (150). This is a **floor**, not a count — probe handle variants
  before calling any new handle absent.
- **Do not re-derive:** Instagram is unreachable anonymously (control-tested); `playAddr` 403s;
  Zyte has no key and cannot produce bytes; the vendor delta for 50 videos is under $2.
- **Open and owned elsewhere:** founder must confirm the accounts; datasci owns whether three
  accounts can support any inferential claim.

---

# ADDENDUM 10 — corpus README shipped (lead-approved exception), and a NEW operational finding

**Shipped:** `harvest_corpus` now writes `README.md` into `out_dir` on every run, carrying the
interpretation caveats **with this run's own measured numbers** — harvested/failed counts, account
count, achieved span in days, and `span_coverage` as a percentage. Rewritten (not appended) each
run. Three tests cover the writer. `ruff` clean, **101/101**.

Rationale (lead's, and it is the right one): the caveats in the module docstring and package README
protect readers of the *code*. The person most likely to misread a null result is whoever opens the
corpus directory weeks from now, possibly outside this repo, having read neither. **A caveat must
travel with the data**, and one carrying the run's actual coverage figure is much harder to wave
through than generic prose.

### Two bad assertions I wrote — worth recording, because they invert today's pattern

Both new tests failed initially, and **both failures were in my test, not the code**:

1. Asserted `"% of the span this run asked for"`; the file emits `**0%** of the span ...` — markdown
   bold closes between `%` and ` of`, so the substring could never match.
2. Asserted `"may mean"` against hard-wrapped prose where the text is `may\nmean`.

Today's named pattern is *a guard positioned where it can never fire*. These are its mirror image:
**a test asserting a string the code can never emit** — it fails loudly rather than passing
silently, so it is the benign direction, but the root cause is identical: **the assertion was
written from memory of the intended output rather than checked against the actual output.** The fix
both times was to print the real artifact and match against it.

### NEW OPERATIONAL FINDING — the IP is now rate-limited. `VERIFIED`

The final live verification run failed outright:

```
ERROR: inmobiliarialunaroman: Unable to download JSON metadata:
HTTP Error 429: Too Many Requests
```

This is the **first 429 of the session**, after roughly a dozen enumerations and ~30 video fetches
from one residential IP over ~2 hours. Earlier failures were per-video (`Unable to extract
universal data`); this one is **account-level and blocks enumeration entirely**.

**This matters for the pilot and was not in any earlier estimate:**

- **Do not run the pilot immediately after heavy probing.** Let the IP cool down first.
- `YtDlpFetcher(sleep_between=...)` defaults to **2.0 s**; for a ~125-attempt pilot consider
  raising it. Untested at higher values — I stopped rather than probe further into a 429.
- The 45-60 min estimate assumes requests succeed; a mid-run 429 makes it longer. **The runner
  survives this correctly** — the account is recorded in `failures.csv` at stage `enumerate` and
  the run is fully resumable — but a pilot started into a rate limit will produce an empty corpus.
- **Silver lining, verified accidentally:** the corpus README wrote itself on a 0-harvested run and
  says so plainly ("**0 videos harvested**, 1 failed... not measurable"). A failed corpus announces
  its own failure, which is exactly the behaviour it was built for.

**Recommended before the pilot:** a single cheap enumeration to confirm the 429 has cleared. Free,
one request.

---

# NOTE (no action) — datasci close-out, recorded under the lead's "note it and hold" instruction

No reply sent: the lead's stand-down forbids further design exchange, and datasci confirmed nothing
is outstanding from me. Recorded because two items are evidence about work already on disk here.

**1. The guard rule found a real gap in `packages/models` within ~20 minutes of being named.**
`CorrelationReport.conclusive` was **only ever asserted False** — no test ever made it return True,
so **the entire positive path of the Fase D gate (the only thing that could license reporting a
finding) was unproven**. Same for `separates_from_chance` (zero tests) and `meets_min_posts` (never
asserted true). The guards turned out to be correct, just undemonstrated. This is direct evidence
that the countermeasure recorded in `packages/scraper/README.md` and the `harvest.py` docstring —
*a guard needs a test that makes it fire* — pays for itself; it is no longer only a retrospective
description of four bugs.

**2. The committed real fixture is doing more work than it was committed for.** Loaded 10/10,
`join_rate` 1.0. The values themselves turned out to be the strongest empirical support the design
has:

| account | views | internal range |
|---|---|---|
| `@inmobiliarialunaroman` | 426, 590, 623, 750, **12800** | **30x** |
| `@inmobiliariamarelsa` | 10, 17, 18, 18, 21 | 2.1x |

- **~40x scale gap between accounts**: pooled, every post of the first beats every post of the
  second — the cross-account confound measured rather than argued, now pinned as a test against
  this file.
- The single 12800 outlier against a ~600 baseline is why their interval bootstraps the **median**,
  not the mean.
- **Dispersion is wildly heterogeneous across accounts** (30x vs 2.1x). This sharpens my own
  earlier caution: the question is not whether *the niche* varies, but that **some accounts may
  vary and others not** — a single global viability verdict can hide a live account beside a dead
  one. Theirs to resolve; flagged as pending on their side, correctly not closed on n=5/account.

**Status unchanged: idle.** `ruff` clean, 101/101, nothing committed, pilot never run. Wake
conditions remain (a) handles to variant-probe, (b) founder authorization — and if (b), confirm the
HTTP 429 from Addendum 10 has cleared before starting.
