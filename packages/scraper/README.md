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
