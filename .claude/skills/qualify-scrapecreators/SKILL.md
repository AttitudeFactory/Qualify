---
name: qualify-scrapecreators
description: How Qualify queries and tests ScrapeCreators — always through the official CLI (`scrapecreators`, run as `just sc ...`), never from memory or by guessing a response shape. Use for any discovery, question, ticket, estimate or code change that involves ScrapeCreators (Instagram/TikTok/Facebook/YouTube profiles, reels, posts, comments, transcripts, trending, hashtags, the brand-kit precharge, referentes, earned media), and before quoting what an endpoint returns or costs.
---

# ScrapeCreators — query and test with the CLI

**Rule (founder, 2026-10-24):** every discovery, doubt, question or ticket about ScrapeCreators is
answered by running the official CLI against a real handle/URL. Do not answer from memory, from the
web docs alone, or from `Qualify/scrapecreators_client.py`'s assumptions: run the command, read the
real response, then answer. The command you ran is the evidence — paste it (never the key) in the
ticket, doc or PR.

## Setup

| What | Value |
|---|---|
| Package | `@scrapecreators/cli` (npm, global; Node ≥ 20.3) — installed 2026-10-24, v1.0.87 |
| Install / upgrade | `npm install -g @scrapecreators/cli` |
| Key | `SCRAPECREATORS_API_KEY` — the same variable the app reads from `.env` |
| Run | `just sc <platform> <action> [--params]` — loads the key from `.env` (or your shell) |

`just sc` reads the key from the checkout's `.env`. A worktree has no `.env`: export
`SCRAPECREATORS_API_KEY` in the shell first, or run from the main checkout. Never pass
`--api-key` (it lands in shell history) and never print the key.

Do not run `scrapecreators auth login` (it opens a browser and creates an account flow): ask the
founder first.

## Commands that answer most questions

```bash
just sc list                                  # platforms
just sc list instagram                        # endpoints + required params
just sc instagram profile --help              # params of one endpoint, incl. credit notes
just sc balance                               # credits left — check before any batch

just sc instagram profile --handle <handle> --cache-max-age 7d --pretty
just sc instagram user-posts --handle <handle> --clean --format markdown
just sc instagram post --url "<url>" --pretty
just sc tiktok profile-videos --handle <handle> --sort-by popular --clean
just sc instagram profile --handle <handle> --output "$TMPDIR/sc-<handle>-profile.json"
```

- Handles go without `@`, hashtags without `#`.
- Data on stdout, status on stderr; `--verbose` shows the request URL, timing and status code.
- `--clean` strips noisy fields — use it to read, **not** to decide which fields exist (check the
  raw response for that).

## Credits

- A live call costs credits (1 for most endpoints; `--help` says when it differs). Check
  `just sc balance` before and after anything beyond a handful of calls and report the delta.
- `--cache-max-age <1d|3d|7d|14d|30d>` returns a cached response for **0 credits** when one exists
  (`"cached": true`). Use it for discovery; drop it only when freshness is the question.
- Batches over ~50 calls need the founder's OK with the expected credit cost.

## What to record

- **Field shape answers** (e.g. "does a reel carry `music_info`?"): the command, the JSON path, one
  real example value. Save the raw payload with `--output` outside the repo if it informs a
  parser (raw payloads are kept so data can be re-parsed — house rule).
- **Docs:** the endpoint ↔ field tables live in `docs/descubrir-reels-scrapecreators.md`; vendor
  choice in `docs/adr-34-ingesta-earned-media-vendor.md`. Update them when the CLI shows they drifted.
- **Tickets:** a ScrapeCreators ticket is not ready until its acceptance criteria name the CLI
  command that proves them.
- Do not commit payloads with personal data of real people beyond public profile fields.
