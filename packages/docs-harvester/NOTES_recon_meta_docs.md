# Recon: how developers.facebook.com actually serves its docs

Author: `pipeline-r`, 2026-07-24. Every claim below is curl-verified in this session,
not inferred. This supersedes parts of the recon recorded in
`.claude/sprint-state-2026-07-23-ig-crm.md` §"pipeline's recon findings".

---

## CORRECTION (2026-07-24, same session) — READ THIS BEFORE §1-§2

**The single most important variable is the request headers, and §1-§2 below were
measured with browser-like headers, which made me draw the wrong conclusion.**

`developers.facebook.com` **content-negotiates**. For the same URL, with no `.md` suffix:

| Request headers | Response |
|---|---|
| Browser-like (`Accept: text/html...`, Chrome UA, `Sec-Fetch-*`) | 1 MB React HTML app, or a soft-404 |
| Plain bot UA, no `Accept: text/html` | **`content-type: text/markdown`, raw markdown, no wrapper** |

Verified: `GET /documentation/instagram-platform/content-publishing` with
`User-Agent: QualifyDocsHarvester/0.1` and only `Accept-Language: en-US` returns
**HTTP 200, `text/markdown; charset=utf-8`, 19 206 bytes of clean markdown.**

Consequences:

- **§2 is wrong.** `/documentation/<path>` without `.md` is *not* inherently a soft-404.
  It soft-404s only when browser headers make the server serve the HTML app. The `.md`
  suffix is one way to force markdown; **sending a non-browser UA is another, and it is
  the better one** because it needs no URL rewriting.
- **§1's "unwrap the `<pre>` wrapper" is unnecessary** with correct headers. The wrapper
  only appears on the `.md` URL when browser headers are sent. With a bot UA the body is
  already raw markdown and `content-type` is a reliable discriminator.
- The 63x HTML-vs-markdown size ratio in §1 is still true and still the reason to care.
  What was wrong was my inference that `.md` rewriting is the way to get it.

Both routes yield identical content: for `content-publishing`,
`html.unescape(plain_ua_body) == wrapper_unwrapped_body` — verified byte-exact. The
corpus already harvested via the `.md` route is therefore valid, not truncated; it is
merely HTML-entity-unescaped (which is why it measures 17 876 B against 19 206 B raw).

**Design implication:** fetch the canonical URL with a bot UA and branch on
`content-type: text/markdown`. Do not rewrite URLs to add `.md`. §5's canonicalization
table stands; the "Fetch URL: + `.md`" column does not.

---

## 1. Meta serves native markdown. Do not convert HTML.

Every doc page embeds a `markdown_url` in its HTML payload:

```
"markdown_url":"\/documentation\/instagram-platform\/content-publishing.md"
```

Fetching that URL returns a *thin* HTML wrapper around raw markdown:

```html
<html><head><title>Content Publishing</title>...</head><body>
<pre data-testid="developer-docs-markdown-page"># Content Publishing
...
```

Measured on `instagram-platform/content-publishing`:

| Form | Bytes |
|---|---|
| `/docs/instagram-platform/content-publishing` (HTML) | 1 226 243 |
| `/documentation/instagram-platform/content-publishing.md` | 19 487 |

**63x smaller.** The harvester needs no HTML->markdown conversion: it unwraps
`<pre data-testid="developer-docs-markdown-page">` and HTML-unescapes the contents.
No `beautifulsoup4`, no `markdownify`. An `htmlmd.py` conversion module is dead weight.

## 2. `/documentation/<path>` is NOT a soft-404 — it is the markdown route missing its suffix

The earlier recon concluded "`/documentation/` is broken, canonicalize to `/docs/`".
That inference was correct about the symptom and wrong about the cause, and the
correction inverts the canonical form:

- `/documentation/graph-api/overview` -> HTTP 200, ~137 KB of chrome, "page not found" body (soft-404)
- `/documentation/graph-api/overview.md` -> **HTTP 200, real markdown**

`/documentation/X` is the markdown route; without the `.md` suffix it soft-404s.
So: **canonical fetch URL is `/documentation/<path>.md`**, not `/docs/<path>`.
Harvesting via `/docs/` would have pulled 1 MB of React chrome per page for content
that is served clean at 1/63rd the size.

## 3. HTTP 400 "Sorry, something went wrong" is rate limiting, not a real error

Bursting requests yields HTTP 400 with a **1542-byte** generic Facebook error page
(`<title>Error</title>`, "Sorry, something went wrong."). Verified behaviour:

- No cookie jar, ~1 s spacing -> 400 on essentially every request
- Cookie jar (`-c/-b`) + >=3 s spacing -> 200 on every request
- 2 s spacing -> intermittent 400s

Requirements this imposes:
- **Persist cookies across requests.** A fresh cookie jar per request gets throttled.
- **>=3 s between requests** (harvester uses 4 s).
- **Treat 400 as retryable** with backoff, and **never write that body to disk as content**.
  It is 1542 bytes of error page that would otherwise land as a "harvested" doc.
- Browser-ish headers are required: `User-Agent`, `Accept`, `Sec-Fetch-*`,
  `Upgrade-Insecure-Requests`. `Accept-Language: en-US` is still needed — the site
  geo-localizes to Spanish without it (that earlier finding holds).

A real missing page returns a genuine **HTTP 404** (verified:
`/docs/instagram-platform/this-page-does-not-exist-xyz` -> 404). So status codes are
meaningful *except* for the `/documentation/X`-without-`.md` soft-404 case in §2.

## 4. The link graph is server-rendered in the nav, not in the markdown

- Doc **markdown** bodies carry only prose cross-links (`content-publishing.md` has 14
  absolute `https://developers.facebook.com/documentation/...` links). BFS over markdown
  alone would under-cover the tree.
- The **HTML** of any doc page embeds the full sidebar nav. A single fetch of the tree
  root `/docs/instagram-platform` yields **86 distinct `/documentation/instagram-platform/...`
  paths**, including deep leaves (`.../messaging-api/button-template`).

So the crawl is: **one HTML fetch of the tree root to seed the frontier**, then `.md`
for every page, unioning links discovered in both. Link extraction is one regex over
the raw body (handling JSON-escaped `\/`), which works on HTML and markdown alike.

The 86 nav paths already include every surface this sprint is blocked on:
`instagram-api-with-facebook-login/business-login-for-instagram`, `content-publishing`
(+ `audio-api`, `resumable-uploads`), `instagram-api-with-instagram-login/messaging-api`
(+ 8 leaves), `.../conversations-api`, `app-review`, `create-an-instagram-app`.

## 5. Path canonicalization rules that follow

| Input | Canonical | Fetch URL | Local path |
|---|---|---|---|
| `/docs/instagram-platform/content-publishing` | `/documentation/instagram-platform/content-publishing` | + `.md` | `instagram-platform/content-publishing.md` |
| `.../content-publishing#reels` | fragment stripped | | |
| `/documentation/instagram-platform/` | trailing slash stripped | | |
| `/documentation/instagram-platform.md` | `.md` stripped for identity | | |

`/docs/app-review` 301-redirects to `/docs/resp-plat-initiatives/individual-processes/app-review`,
so redirects must be followed and the **final** URL recorded in the manifest, otherwise the
same page is harvested twice under two identities.
