# qualify-scraper

Fase 1 Parte 2 of Qualify's social pipeline: scrape TikTok / Instagram post
pages and convert the embedded hydration JSON into typed Pydantic `Post`
objects. Per ADR 17, ingestion is **built in-house over Zyte** (buy the proxy /
anti-block, write the parser); EnsembleData/Data365 stay a documented fallback
for formats where in-house parsing is blocked (notably stories).

This sprint delivers the parsers, schemas, hydration extractors, and the real
Zyte client — all testable offline against saved fixtures with **no live
scraping, no Zyte account, and no network**. ClickHouse materialization, Celery,
and the R2-backed payload store are Parte 3.

Standalone `uv` project mirroring `packages/models`. Python >= 3.12; runtime deps
`pydantic` + `httpx` (httpx only exercised on the live scrape path); `ruff`
(lint + format) and `pytest` in the dev group.

## Formats in scope

Wide across formats from the start (deliberate expansion vs. the plan doc's
"video-only TikTok first" MVP note):

| Platform  | Formats (`ContentType`)                                            |
|-----------|-------------------------------------------------------------------|
| TikTok    | `tiktok_video`, `tiktok_photo`, `tiktok_story`, `tiktok_text`      |
| Instagram | `instagram_reel`, `instagram_post`, `instagram_carousel`, `instagram_story` |

Multi-image galleries/carousels and text-only posts fit one model via the
`content_type` discriminator plus a `media: list[MediaItem]` (empty for text,
one item for single video/image, many for galleries/carousels).

## Layout

```
src/qualify_scraper/
├── shared.py             # -> packages/shared at Parte 3: Platform, natural key,
│                         #    ScrapeProvenance, RawHydration, RawPayloadStore seam
├── schemas.py            # Post, MediaItem, PostMetrics, ContentType/MediaKind enums
├── extract.py            # HTML -> hydration dict (in-house parse seam per ADR 17)
├── client.py             # ScrapingClient Protocol, ZyteTransport/ZyteApiTransport,
│                         #    ZyteScrapingClient, FixtureScrapingClient
└── parsers/
    ├── tiktok.py         # parse_tiktok(raw, brand_id, pipeline_version) -> Post
    └── instagram.py      # parse_instagram(raw, brand_id, pipeline_version) -> Post
tests/
├── conftest.py           # fixtures_dir / brand_id / pipeline_version fixtures
├── fixtures/{tiktok,instagram}/*.json   # saved hydration payloads
├── fixtures/html/*.html                 # pages embedding those payloads
└── test_*.py
```

## Runtime scrape path (production)

```
ZyteApiTransport.fetch_html(url)      # live Zyte API (browserHtml) — the only network call
  -> extract_{tiktok,instagram}_hydration(html)   # pull embedded hydration JSON
  -> RawPayloadStore.persist(...)      # store raw payload as canonical artifact FIRST
  -> parse_{tiktok,instagram}(raw, ...)            # typed Post
```

`ZyteScrapingClient` wires these together and persists the raw payload **before**
parsing, so any post can be re-parsed without re-scraping. The store is a
`RawPayloadStore` Protocol: `LocalDiskRawPayloadStore` now, an R2 impl drops in
at Parte 3 behind the same seam with no parser changes.

## Running the tests

```bash
cd packages/scraper
uv sync
uv run pytest        # 24 tests, zero network access
```

**No test touches the network.** Parser/schema tests read saved hydration JSON
through `FixtureScrapingClient`; the `ZyteScrapingClient` wiring test injects a
`FakeTransport` returning saved HTML, never `ZyteApiTransport`. The live
transport (`httpx` → Zyte) is import-safe but never invoked under test.

## Fixtures

All fixtures are **synthetic** but structurally faithful to the real embedded
page data (TikTok `__UNIVERSAL_DATA_FOR_REHYDRATION__` → `itemStruct`; IG
`graphql.shortcode_media`). This sprint has no scraping to capture real payloads.
The story/text detection paths rely on a synthetic hint field and must be
re-validated against a real payload before production use. See
`tests/fixtures/README.md` for details.

## Idempotency

The natural key is `(brand_id, platform, post_id)`, exposed as `Post.natural_key`
so dedup is checkable from the schema alone — independent of storage. It maps
directly onto the eventual `ingestion.posts` `ReplacingMergeTree` key (plan-
ingesta-social.md §3.2). Re-parsing the same raw payload yields the same natural
key, so re-runs are safe.

## Provenance

`ScrapeProvenance` fields are **mandatory** (non-optional) on every `Post`:

- `hydration_json_r2_key` — reference to the raw payload in R2, so a post can be
  re-parsed without re-scraping (scraping costs money per request).
- `source_url` — the scraped post URL.
- `scraped_at` — when the raw payload was fetched (immutable across re-parses).
- `parser_version` — which parser produced the row (e.g. `tiktok-parser-0.1.0`),
  set by the parser module itself.
- `pipeline_version` — the whole-pipeline config the row ran under.

`parser_version` is deliberately distinct from `pipeline_version`: re-parsing the
same persisted hydration JSON with an improved parser changes the output while
`scraped_at` / `hydration_json_r2_key` stay fixed, so the row must record *which
parser* produced it for the re-parse to be auditable. A `Post` cannot be
constructed without these, so provenance can never be dropped on the parse path.
A `content_type`↔`platform` prefix validator also runs at construction, catching
a parser that mislabels a post. `detector_version` (model-side) is added
downstream by `packages/models`, not here.

## Status of decisions

- **Vendor** — LOCKED: build in-house over Zyte (ADR 17). EnsembleData/Data365
  are a targeted fallback for blocked formats (stories).
- **Layout** — LOCKED: standalone `uv` project (no workspace this sprint). The
  workspace conversion is a Parte 3 concern, when `packages/shared` lands; the
  `shared.py` module here is written to lift into it cleanly.
- **Schema shape** — provisional until architect sign-off; it constrains the
  eventual `ingestion.posts` ClickHouse DDL. Open deltas vs. §3.2: nested
  `metrics`/`media` submodels, the new `content_type` discriminator, and whether
  multi-media posts stay one row + a child media table.

## Known issues (measured 2026-08-06, not yet fixed)

Three defects found while checking whether the corpus runner could reuse the
production path. All were verified against the live web on 2026-08-06 from a
residential IP; none is fixed here, and each needs its own task.

1. **`MediaItem.url` is not fetchable, on any platform.** `parsers/tiktok.py`
   puts `video.playAddr` into `MediaItem.url`. That URL returns **HTTP 403** to a
   plain `GET` and also to a `GET` carrying a real browser `User-Agent` plus the
   correct `Referer`. TikTok gates its CDN behind a JS anti-bot challenge whose
   solution becomes a cookie, so no header combination opens it. Nothing in the
   suite ever exercised the field, which is why this went unnoticed. Treat
   `MediaItem.url` as an identifier, **not** as something you can download —
   anything needing the bytes must go through `qualify_scraper.research.harvest`.

2. **`extract_instagram_hydration` targets a payload Instagram no longer ships.**
   It regexes `window._sharedData` (`extract.py`). A live logged-out
   `instagram.com` page fetched on 2026-08-06 returned HTTP 200 with ~610 KB of
   HTML containing **zero** occurrences of `_sharedData` — and zero occurrences of
   `og:title`, `"username"`, `"video_versions"` or `edge_owner_to_timeline_media`.
   Meta serves anonymous visitors a `PolarisLoggedOut` shell with no content at
   all. Against any real 2026 page this extractor raises
   `HydrationExtractionError`; it passes its test only because the fixture encodes
   the dead format. Anonymous Instagram ingestion is not currently possible —
   fixing the regex is not enough, the data is not in the response.

3. **The HTML fixtures are synthetic, so neither extractor has met a real page.**
   `tests/fixtures/html/instagram_reel.html` is **815 bytes** and
   `tiktok_video.html` is **687 bytes**; real hydration pages are hundreds of KB.
   "The extractors are tested" currently means "tested against hand-written
   minimal HTML". Capturing one real page per platform as a fixture would convert
   both extractor tests from shape-checks into evidence — and would have caught
   issue 2 when it first broke.

## Research corpus runner (`qualify_scraper.research`)

`research/harvest.py` downloads a corpus of videos + engagement metrics for the
hook-pattern spike. It is **not** part of the production ingestion path and
nothing under `client.py` / `parsers/` / `extract.py` may import it.

**Running it needs no sync.** `yt-dlp` is invoked as a *binary* via subprocess,
never imported, so it does not have to be in the workspace venv:

```bash
uv run --no-sync pytest packages/scraper/tests   # tests need no yt-dlp at all
```

**Do not run `uv sync --group corpus`.** `CLAUDE.md` records a measured trap:
alternating `uv sync` between dependency groups corrupts the shared workspace
`.venv` editable installs (seen twice in one day with a single agent; only
`rm -rf .venv && uv sync --group ml` recovered it). A third group in that
rotation is the same hazard and would break the venv for other agents working in
the repo. The `corpus` group declares intent and pins a floor — it is not an
install step. If the `yt-dlp` binary is missing, install it isolated with
`uv tool install yt-dlp`.

The 16 runner tests drive `harvest_corpus` through a `FixtureFetcher` implementing
the `VideoFetcher` Protocol, so they touch neither the network nor `yt-dlp`.

### Reading the pilot's output

**A null result may mean "we could not see it", not "it is not there."** Two
measured reasons, both reported by `HarvestReport`:

- **Three accounts, zero margin.** A hook type must appear in ≥3 accounts to
  count as a pattern rather than one advertiser's house style, and this niche
  yields exactly three usable TikTok accounts — so a type must appear in *all
  three*, and one account not using it erases it from the study.
- **Achieved span can be far narrower than requested.** Measured: a run asking
  for 365 days returned 98. `span_coverage` reports it. The effect is
  **asymmetric** — a *positive* finding survives low coverage, a *negative* one
  does not, since a hook type used only in the unsampled months reads as "this
  account does not vary".

The pilot exists to falsify "this niche never varies", so an uninterpretable
negative is its worst outcome: it looks decisive and is not. Check
`span_coverage` and the account count before reading any null as a verdict.

### A guard needs a test that makes it fire

Four defects landed on 2026-08-06 across this package and `packages/models`,
**every one under a green suite**: a metric-missing guard that made the blank
impossible to emit; a variety sampler that could only see one ~3-month window; a
`separation > 0.5` threshold where 0.5 is the *maximum* attainable; and a
Spearman check that reads ~0 against exactly the drift it was built to detect.

The shared shape is **a guard aimed at the right hazard, positioned where it can
never fire** — and a test that merely passes with the guard present cannot see
it. Write the test that makes the guard *trip*: feed it the input that should
trigger it and assert it did. If you cannot construct that input, that is the
finding.
