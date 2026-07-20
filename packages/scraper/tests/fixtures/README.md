# Hydration fixtures

Saved hydration-JSON payloads the parsers are tested against. No network is
touched by any test — `FixtureScrapingClient` reads these files from disk.

**All fixtures in this directory are SYNTHETIC.** This sprint has no live
scraping and no vendor account, so no real captured payloads were available.
Each file is hand-built to be *structurally faithful* to the real embedded
page data:

- `tiktok/*.json` mirror TikTok's `__UNIVERSAL_DATA_FOR_REHYDRATION__` →
  `__DEFAULT_SCOPE__["webapp.video-detail"].itemInfo.itemStruct` shape.
- `instagram/*.json` mirror Instagram's `graphql.shortcode_media` shape.
- `html/*.html` embed those JSON payloads in the real page script shapes
  (`<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` for TikTok,
  `window._sharedData = {...}` for Instagram) so the `extract.py` HTML→hydration
  path is exercised end-to-end without a live fetch.

Format-detection caveat: `tiktok/story.json`, `tiktok/text.json`, and
`instagram/story.json` carry an explicit hint field (`contentTypeHint` /
`product_type == "story"`) because those formats have no stable public
discriminator in the video-detail / shortcode page data. That hint is a
synthetic stand-in and must be re-validated against a real captured payload
before the story/text detection paths are trusted in production.

Once real payloads can be captured (task 4 vendor client, blocked on the
architect's ingestion ADR), replace these with real samples — the parsers and
schemas should not need to change if the synthetic shapes were faithful.
