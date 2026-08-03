# Contradictions inside Meta's own documentation

Found while verifying `docs/backlog-crm-workflows.md` against the harvested corpus.
Author: `pipeline-r`, 2026-07-24. Every line cited is in this corpus — check them, do not
take my word for it. These are **landmines**: in each case Meta states two different things,
so "I read it in the docs" is not sufficient grounding for either value.

---

## 1. The content-publish scope name has two spellings. Meta disagrees with itself.

| Source | Spelling |
|---|---|
| `instagram-platform/instagram-api-with-instagram-login/business-login.md:10` | `instagram_business_content_publish` |
| `instagram-platform/app-review.md:49` | `instagram_business_content_publishing` |
| `instagram-platform/app-review.md:62` (migration table) | `instagram_business_content_publishing` |

The other three scopes are spelled identically in both places — `instagram_business_basic`,
`instagram_business_manage_messages`, `instagram_business_manage_comments`. **Only
content-publish/publishing differs.**

Context that makes this worse: `business-login.md:14` explains these *new* values replace the
older `business_basic` / `business_content_publish` / `business_manage_comments` /
`business_manage_messages`, deprecated **2025-01-27**. So there are three candidate spellings in
circulation and the current one is genuinely ambiguous in the source.

**Do not hardcode either spelling from documentation alone.** A wrong `scope` value fails the
OAuth authorization call. Resolve empirically against the live authorization endpoint before any
connection code ships, and record the answer as the authority.

This corrects a claim I made to the lead earlier, where I asserted
`instagram_business_content_publishing` was simply correct. It is not simply correct — it is one
of two documented spellings.

## 2. The publishing rate limit has two values, and the interaction with carousels is misread

| Source | Claim |
|---|---|
| `instagram-platform/content-publishing.md:61` | "Instagram accounts are limited to **100** API-published posts within a 24-hour moving period. **Carousels count as a single post.**" |
| `instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit.md:47` | `quota_total` — max **IG Containers** publishable per `quota_duration`, "currently **`50`**" |
| same file, `:65` | `"quota_total": 50` in the example response |

These are **not the same quantity**, which is why both can be true:

- **100** counts *published posts*, and a carousel is one post regardless of item count.
- **50** counts *containers*, and a carousel needs one container per item **plus** one carousel
  container.

So a 10-image carousel is **1** post against the 100 limit but **11** containers against the 50
limit. Carousels are *more* expensive under the binding constraint, not less.

**`docs/backlog-crm-workflows.md:348` states "100 posts por API en ventana móvil de 24 h (50 si
son carruseles)".** That reconciles the two numbers by inventing a carousel-specific 100→50
halving which appears nowhere in Meta's docs and inverts the actual direction of the cost. The
100 and the 50 are different counters, not two cases of one counter.

**Practical rule:** never hardcode either number. Read `GET /<IG_ID>/content_publishing_limit`
at runtime — it is the only value Meta commits to, it returns `quota_total`, `quota_duration`
and `quota_usage`, and both prose figures are flagged "currently", i.e. subject to change.

For the founder's actual volume (a single store, 1–3 posts/day) neither limit binds, so this
does not gate customer zero. It gates any future scheduling or multi-account feature.

## 3. `create-an-instagram-app` is a stub, and the real content is out of scope

`instagram-platform/create-an-instagram-app.md` is **314 bytes** and consists of a pointer:

> "The following content is from the Meta App Development documentation. Please refer to the
> Development documentation to learn more about the Meta App Development process."

The actual app-creation walkthrough lives under `/documentation/development`, which is outside
the founder-approved harvest scope. Anything relying on app-creation steps is **not** grounded
by this corpus. Flagged rather than silently scope-crept.

## 4. The `Authorization` scheme has two values, and the split is NOT "one per host"

Recorded by `pipeline` 2026-07-29 while building the resumable upload path (QUA-19). Ruled as
**R12** in `docs/arquitectura.md` §6.

Meta's examples use two different `Authorization` schemes, and the obvious rule — "`Bearer` on
`graph.facebook.com`, `OAuth` on `rupload.facebook.com`" — **is not what the corpus says.** The
contradiction is not only between documents; it is *inside one file*:

| Where | Host | Scheme shown |
|---|---|---|
| `content-publishing/resumable-uploads.md:41` | `graph.facebook.com` (create container) | `Bearer` |
| `content-publishing/resumable-uploads.md:137` | `graph.facebook.com` (`media_publish`) | **`OAuth`** |
| `content-publishing/resumable-uploads.md:92,102` | `rupload.facebook.com` | `OAuth` |
| `content-publishing.md:84,212,272` | `graph.facebook.com` | `Bearer` |
| `content-publishing.md:164,174` | `rupload.facebook.com` | `OAuth` |

So `resumable-uploads.md` shows the SAME host with BOTH schemes, while `content-publishing.md`
shows that host with only `Bearer`. Reading either file alone yields a confident and different
rule.

**The single invariant across the whole corpus:** `rupload.facebook.com` is **never** shown
with `Bearer`.

**Consequence, same as §1:** neither value may be hardcoded from documentation. The scheme is
configuration — `MetaOAuthSettings.graph_auth_scheme` / `.rupload_auth_scheme`, overridable via
`QUALIFY_META_GRAPH_AUTH_SCHEME` / `QUALIFY_META_RUPLOAD_AUTH_SCHEME` — with defaults placed
where the corpus is unanimous. `CredentialResolver.client_for` takes `scheme` with **no
default**, so a caller cannot get one by forgetting.

**Not resolvable by reading.** One live call against a connected account settles it. Until
then, treat both values as `[V]`.
