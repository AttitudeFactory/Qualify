# Sprint 2 — pipeline-engineer working state (QUA-19 / QUA-20)

Owner: `pipeline` agent. Started 2026-07-29. Flushed incrementally per `durable-findings`.
Binding criteria live in Linear (`QUA-19`, `QUA-20`) — this file is working state, not a spec.

## Status ledger

| Section | State |
|---|---|
| 1. Context read (issues + comments + ADR 25 O1-O7 + ADR 28) | DONE |
| 2. Codebase recon | DONE |
| 3. Login-fork blocker found, routed to architect | DONE |
| 4. Plan sent to team-lead | SENT — awaiting approval |
| 5. Architect ruling received; §3 resolved, 2 of my claims corrected | DONE |
| 6. Implementation | BLOCKED on team-lead plan approval — no code written yet |

---

## 1. Context read — binding constraints extracted

### QUA-19 (publish video: reel / video story / carousel video)
- Path: `POST /<IG_USER_ID>/media?upload_type=resumable&media_type=REELS|STORIES|VIDEO`
  -> `{id, uri}` -> `POST` to that uri (`rupload.facebook.com/ig-api-upload/<API_VERSION>/<IG_CONTAINER_ID>`)
  with headers `offset`, `file_size`, binary body streamed from R2 -> `media_publish`.
- Container status polling cadence is PINNED by Meta docs: `GET /<IG_CONTAINER_ID>?fields=status_code`
  once per minute, max 5 minutes (`content-publishing.md:324`). States `FINISHED` / `IN_PROGRESS`.
- Write-ahead: `publish_attempts` row BEFORE the attempt, with `idempotency_key`, `creation_id`,
  `tenant_id`, `connection_id`, `adapter_version`, raw response.
- Blind retry FORBIDDEN (ADR 22e): reconcile against API by `creation_id`. Use `debug_info.retriable`
  from `rupload` failures (`content-publishing.md:187-194`).
- Stories confirmed by `media_product_type`, NOT `media_type` (`content-publishing.md:230,262`).
- Scheduling survives restarts (Postgres), tenant timezone, token valid at publish time,
  `degraded` connection -> do not publish + notify.
- Objects gate `packages/shared/src/qualify_shared/objects/`: ONLY `put_media` + `open_object`.
  NO `presign_get`, NO TTL, NO token, NO public HTTP route (all deferred to QUA-68).
- Tenant-prefix enforcement on object key + static test forbidding boto3/S3 client outside the module.
- `R2Settings` frozen dataclass w/ `from_env()`, mirrors `MetaOAuthSettings`. s3v4 / region auto.
- `put_media`: single PUT, no multipart, explicit reject > 300 MB.
- Reel cover via `thumb_offset`, NEVER `cover_url`.
- OUT: image, public route, token, TTL, presign, ClickHouse, Celery, `packages/pipeline`,
  `ingestion.*` DDL, bucket lifecycle, multipart, `raw_payload_key()`.

### QUA-20 (DM + comment intake, poll-first, Instagram only)
- Poll-first is the PRODUCTION path, not a fallback. Webhooks cannot fire for customer zero
  (need Live + Advanced Access + Business Verification, `webhooks.md:60-73`).
- Ingest mechanism must be a swappable seam; webhook endpoint NOT built now.
- Rate limit floor: 200 calls/hour per page-app pair in development mode.
- Dedup: `UNIQUE(connection_id, external_message_id)` in Postgres + idempotent upsert. NOT Redis SETNX.
- `threads` / `messages` in Postgres, never `ingestion.*` (ADR 22d). Columns include `tenant_id`,
  `connection_id`, channel, state, window.
- `threads.assigned_agent_id` nullable from day one.
- Messaging window computed and shown; sending outside the window is blocked BY THE SYSTEM.
- Known gap to write down (not resolve): "Requests" folder conversations go invisible after
  30 days of inactivity.

### Login-fork blocker (QUA-19 comment 2026-07-28) — ALREADY RULED, no code change
`docs/arquitectura.md` §6 amendment O1-O7 (2026-07-29) closes it: the live app is on
"API con inicio de sesión de empresa de Instagram" (wrong branch); ADR 25 requires
"Configuración de la API con inicio de sesión de Facebook". O6 states the fix is a dashboard +
env + reseed operation with **zero code changes** — C-04 is already written for the target branch.
Consequence for me: I code against the Facebook Login branch (`graph.facebook.com`), which is what
`qualify_api/config.py` already does. Nothing in my scope should be redesigned for this.

---

## 2. Codebase recon — what exists that I build on

- `packages/api/src/qualify_api/config.py` — `MetaOAuthSettings` frozen dataclass + `from_env()`;
  this is the exact pattern QUA-19 asks me to copy for `R2Settings`. Also `redis_url()`.
- `packages/api/src/qualify_api/connections/resolver.py` — **the seam workers must use**:
  `CredentialResolver.client_for(connection_id) -> AuthenticatedClient`. Workers ask for an
  already-authenticated client, NEVER a token. Publisher and poller both go through this.
  Note: `AuthenticatedClient` Protocol currently exposes only `get`/`post` — enough for both
  stories (resumable upload is a POST with binary body).
- `packages/api/src/qualify_api/connections/meta_oauth.py` — the Protocol + Http impl + fake
  split, and the `_parse_*` `[V]` convention (one parse function per endpoint, marked `[V]`,
  the only place live reality lands). I replicate this shape for the publish + poll clients.
- `packages/shared/tests/test_session_sanctity.py` — the AST static-guard pattern. The
  boto3/S3 static test QUA-19 demands is the same file with a different `_FORBIDDEN` set.
  `_SRC_ROOTS` there already covers api/shared/scraper.
- `migrations/postgres/versions/0002_connections.py` — `_enable_tenant_rls()` helper (NULLIF
  is load-bearing, R7), composite FK `(x_id, tenant_id) -> social_connections(id, tenant_id)`
  (R2), column-level grants (R3). New tables must follow all three.
- `tenants.timezone` (Text, NOT NULL) already exists in `0001` — QUA-19's "tenant timezone"
  criterion has a column to read; I do not need new DDL for it.
- Head revision is `0002`. My migrations are `0003` (publishing) and `0004` (inbox).

---

## 3. BLOCKING FINDING — QUA-19 and QUA-20 were verified on OPPOSITE sides of the ADR 25 login fork

**Status: verified against the primary corpus by `pipeline`, 2026-07-29. Routed to `architect`.
Do not start QUA-20's transport layer until this is ruled.**

The login fork is exclusive, app-level and one-way (ADR 25 / amendment O1). Both stories run
against the SAME app, so they must both work on the SAME branch. They do not, as specced:

**QUA-19 forces Facebook Login for Business.** `content-publishing/resumable-uploads.md:5` —
resumable byte upload is *"available only for apps that have implemented Facebook Login for
Business"*. Without it, video falls back to public `video_url`, and ADR 28's entire
"zero public HTTP surface" argument collapses.

**QUA-20's access-level verification was done against the Instagram Login corpus.** Its cited
source is `instagram-platform/instagram-api-with-instagram-login/conversations-api.md`, which
states its own branch explicitly:
- `conversations-api.md:28` — *"All endpoints can be accessed via the `graph.instagram.com` host."*
- `conversations-api.md:40` — permissions `instagram_business_basic` (the `instagram_business_*`
  family, i.e. the Instagram Login vocabulary that ADR 25 explicitly says is NOT ours).
- The Standard-Access line the issue quotes (`:19-20`) is from that document.

**Under Facebook Login there is no `conversations` edge on `ig-user`.** Verified by listing
`instagram-platform/instagram-graph-api/reference/ig-user/` — the edges are media,
media_publish, mentions, stories, tags, etc. No conversations. The documented path is the
**Page** node instead, and it carries two extra gates:

- `docs/graph-api/reference/page/conversations.md:22-26` — for Instagram Messaging conversations
  the app needs a Page access token from someone with the `MESSAGING` task, the permissions
  `instagram_basic` + `instagram_manage_messages` + `pages_manage_metadata`, and — literal —
  **"Your app must be owned by a verified business"**.
- ~~`documentation/business-messaging/instagram-messaging/features/moderate-conversations.md:20`~~
  **— CITATION WITHDRAWN, see §5. I over-extended it: that sentence is scoped to "this API",
  meaning the moderation API (block/restrict), not the read path.** The architect supplied the
  citation that does close the read path:
  `documentation/business-messaging/instagram-messaging/overview.md:122` — *"Apps with Standard
  Access can only interact with people who have a role on the app."* A real customer sending a
  DM has no role, by definition. Conclusion unchanged; the evidence for it is now correct.

**Consequence, stated precisely:** on the branch ADR 25 signed and QUA-19 requires, DM intake
for customer zero is plausibly gated behind Business Verification + Advanced Access — the exact
administrative clock QUA-20's poll-first design was built to sidestep. The gate is **not** an
artifact of poll-vs-webhook; it sits on the read endpoint itself.

**COMMENTS ARE NOT AFFECTED — verified, and this is what makes a partial slice possible.**
`instagram-platform/comment-moderation.md:20,25-26` has a Facebook Login column
(`instagram_basic`, `instagram_manage_comments`, `pages_read_engagement`) and scopes access by
ACCOUNT OWNERSHIP, not by the counterparty's role: *"Standard Access if your app serves
Instagram professional accounts you own or manage and have added to your app in the App
Dashboard."* Same wording in `ig-media/comments.md:18`. So comment intake works under
Facebook Login with Standard Access.

~~**What I did NOT verify:** whether the verified-business line on `page/conversations.md` is
currently enforced, or is stale corpus. It appears identically in the `v2.10` copy of the same
page, which is weak evidence of age.~~ **WRONG READ, INVERTED BY THE ARCHITECT — see §5.** The
`v2.10` copy is byte-identical, but the page header declares **Graph API v25.0**: identical
means the harvester saved the *current* page under both paths, not that the text dates from
2017. I read "appears in an old-version path" as evidence of age when it was evidence of
harvesting. **The gate is current. No live call needed to settle it.**

**My proposed handling (architect decides, not me):** split QUA-20 along this seam. Build the
whole thing — tables, upsert dedup, seam, poller, window — but land the **comment** source
first as the working vertical slice, and keep the **DM** source behind the same
`ConversationSource` Protocol with its transport unimplemented until the branch question is
ruled. The seam QUA-20 already demands ("changing mechanism does not rewrite the rest of the
flow") is the same seam that absorbs this. Nothing gets thrown away either way.

---

## 4. Plan sent to team-lead 2026-07-29 (awaiting approval)

### Reused conventions found, not invented
- Tenant object-key prefix is ALREADY established: `raw_payload_key()`
  (`packages/scraper/src/qualify_scraper/shared.py:247-264`) emits `t/{tenant_id}/fp/...` for
  first-party payloads, deliberately disjoint from `scrape/...`. So the objects gate enforces
  prefix **`t/{tenant_id}/`** — same namespace, no second convention. Proposed media sub-path
  `t/{tenant_id}/media/{connection_id}/{media_id}`; the SUB-path is a proposal for the architect,
  the PREFIX invariant is already ADR 22/R5 and not mine to re-decide.
- `packages/api` deps do not include `uvicorn` (confirmed by reading its `pyproject.toml`).

### Constants pinned to corpus, not invented
| Constant | Value | Source |
|---|---|---|
| container status poll interval / ceiling | 60 s / 5 min | `content-publishing.md:324` |
| reel max size | 300 MB | `ig-user/media.md:86` |
| video story max size | 100 MB | `ig-user/media.md:127` |
| dev-mode rate limit | 200 calls/h per page-app pair | `ACCESS-MODEL.md` via `facebook-login/changelog.md:124` |
| conversation message readability | only 20 most recent | `conversation.md` Limitations; `conversations-api.md:154` |
| comments per query | max 50, top-level only, reverse chronological | `ig-media/comments.md` Limitations |

### Slice order (each ends green under `uv run --no-sync pytest -m "not integration"`)
QUA-19: A1 objects gate + R2Settings + static guard -> A2 migration 0003 -> A3 publish client
seam -> A4 publish service (write-ahead + poll + reconcile) -> A5 scheduler.
QUA-20: B1 shape contract -> B2 migration 0004 -> B3 ingest seam + comment source
-> B4 poller + idempotent upsert -> B5 messaging window + send block.

A2 and B2 are DDL and are BLOCKED on architect sign-off by my own role rules. A1 and B1 need
no sign-off and are where I start.

### uvicorn debt — my recommendation
Declare `uvicorn[standard]` as a real dependency of `packages/api` (it ships `create_app()` and
HTTP routes; how the artifact is run should be reproducible from `pyproject.toml`, not from a
remembered `--with` flag), plus a `just serve` recipe carrying `--factory`. BUT schedule it as
the LAST change of my sprint work, not the first: it mutates `uv.lock` and forces a sync, and
sync is the documented venv-corrupting operation here. None of my tests need it (all in-process
`httpx.AsyncClient`), so nothing is blocked by deferring it.

---

## 5. Architect ruling received 2026-07-29 — §3 resolved, two of my claims corrected

Recorded by the architect in the Linear comment on QUA-20 and in `docs/arquitectura.md` §6 as
ADR 25 amendment point **(O8)**. My §3 conclusion stands; two supporting claims did not, and
both are struck through in place above rather than quietly deleted.

**Corrections to my own work, kept because the failure modes are reusable:**
1. **Over-extended citation.** I cited `moderate-conversations.md:20` as gating the read path.
   Its "Advanced Access" sentence is scoped to *"this API"* — the moderation API (block/restrict).
   The citation that actually closes the read path is
   `documentation/business-messaging/instagram-messaging/overview.md:122` — *"Apps with Standard
   Access can only interact with people who have a role on the app."* Lesson: a permission
   sentence inside a feature doc is scoped to that feature until proven otherwise.
2. **Inverted staleness read.** I treated the byte-identical `v2.10` copy of
   `page/conversations.md` as weak evidence the text was old. The architect diffed it: the page
   header declares **Graph API v25.0**, so identical copies mean the harvester wrote the
   *current* page under both paths. Lesson: in this corpus, a versioned path is a harvest
   artifact, not a date stamp — the opposite of the `changelog.md` trap caught on QUA-19, where
   the text really was from 2019.

**Rulings that change my code (all three are now settled inputs, not open questions):**
- **(1) DM half: NOT buildable-and-testable on the signed branch. Build behind an unimplemented
  transport.** The fork does NOT reopen: returning to Instagram Login would trade the DM gate for
  losing mentions/tags (ADR 25's reason) *and* resumable byte upload (ADR 28's reason) — more
  cost, less product. (O8) records this as a **known, priced cost of the signed branch**; ADR 25
  priced the fork on the mentions axis and never on the DM axis.
- **(2) My split is confirmed as the right seam**, with one binding condition: **the
  unimplemented DM transport must fail naming the gate** — verified business / Advanced Access —
  **never a bare `NotImplementedError`.** Rationale to preserve: in six weeks nobody remembers
  why that branch is empty, and the error message is where that memory lives. Same discipline as
  the connection with no `instagram_account_id`.
- **(3) Messaging window: 24 h, CITED — no `[V]`.** `instagram-platform/overview.md:178`
  (*"respond within 24 hours... human agent tag to send a response within 7 days"*), with `:176`
  confirming the page covers the Facebook Login branch. **The 7 days is NOT a longer window** —
  it is an extension existing only under the `human_agent` tag, so it is modelled as an explicit
  separate capability and **never a default**. The value stays injected (it is policy, and this
  ticket forbids hardcoded platform numbers) but is injected **with** the cited 24 h rather than
  with no default.

**Bonus cross-check from the architect, relevant to the open `/me/accounts` risk the lead
flagged:** `business-messaging/instagram-messaging/get-started.md` requires the `MODERATE` task
on the Page and describes `/me/accounts` as returning Pages the user can perform
`MANAGE`/`CREATE_CONTENT`/`MODERATE`/`ADVERTISE` tasks on — independent confirmation that the
edge filters by **task, not ownership**. That is the live `{"data": []}` hypothesis (a) the lead
routed to the architect, now with corpus support.

**QUA-19 unaffected. Plan otherwise unchanged.**

---

## 6. Inbound from `datasci` (QUA-67 corpus work) 2026-07-29 — one of these narrows my split

Their citations are on disk at `packages/models/NOTES_ig_shapes_contract.md` §1/§3. Recorded here
because item 1 changes MY design, not just my reading.

**1. `instagram_manage_comments` gates the WHOLE comments edge, not just the `username` field.**
`ig-media/comments.md:70-73` requires `instagram_basic` + `instagram_manage_comments` to *read*
`/{ig-media-id}/comments`. That scope is **not granted today** (live grants: `instagram_basic`,
`instagram_content_publish`, `pages_show_list`, `pages_read_engagement`).

**Effect on §3/§5: my "comments as the working vertical slice" is ALSO gated today — but by a
DIFFERENT KIND of gate, and the distinction is the whole point of keeping the split.**
- DMs: **verified business + Advanced Access** — an administrative clock measured in weeks,
  outside the team's control.
- Comments: **a missing scope** — fixed by re-resolving `QUALIFY_META_SCOPES` (ADR 25 O5, which
  already forbids hardcoding a spelling from docs) and re-consenting. Hours, in the team's control.

So the split survives and comments remain the right vertical slice; what changes is that I must
**not** treat an empty comment poll as "no comments". Also per that section: if the Page role came
via Business Manager, `ads_management` OR `ads_read` is additionally required.

**2. Confirms my §3 independently, and adds the endpoint I would have got wrong.** Our DM path is
`GET graph.facebook.com/{page-id}/conversations?platform=instagram` with a **Page access token**,
not a user token (`business-messaging/instagram-messaging/get-started.md:133`). Its Messenger
Platform reference page is **not harvested** — manifest marks it `skipped_out_of_scope`, zero
files. Relevant to me: even once the gate lifts, I have **no corpus** for that endpoint's response
shape, so the DM parser will be `[V]` against nothing. Another reason the transport stays
unimplemented rather than guessed.

**3. Human precondition for DMs that is NOT a scope.** `get-started.md:129` — the account owner
must manually enable *Instagram Settings > Messages and story replies > Message controls >
Connected Tools > Allow Access to Messages*. No permission set substitutes for it.

**Design consequence I am adopting for BOTH sources (from datasci's framing):** an empty poll is
**ambiguous** — "nothing new" vs "scope missing" vs "toggle off". The poller must be able to tell
these apart rather than collapsing them to zero. Concretely: check granted scopes against the
source's declared requirement BEFORE polling, and surface a distinct state for
"cannot-observe" vs "observed-nothing". A silent zero is the failure mode that looks like
working software.

**4. Do not propagate:** `ig-comment/replies.md:36,76` spell it `page_read_engagement` (singular).
Meta typo; every other corpus occurrence is `pages_read_engagement`.

## 7. team-lead rulings 2026-07-29

- **QUA-67 is MINE** (`owner: pipeline-engineer` in the issue); the lead had misassigned it and
  corrected. The typed shapes module is mine end to end.
- **I must NOT regenerate `synthetic_ig_comments.json`.** It lives in
  `packages/models/tests/fixtures/`, which is `datasci`'s property, and they are working in this
  workspace now. I build the contract, hand off, datasci regenerates consuming it.
- **Where the shapes module lives is an architect layout call**, not mine — it must be importable
  by both `qualify_api` (threads/messages columns) and `qualify_models` (fixture + sentiment).
  `packages/shared/` is the obvious candidate. Ask it in the same message as the A2/B2 DDL.
- Plan APPROVED. Start at A1.
- `uvicorn`: agreed, and deferring to the end is agreed. **Must ping the lead before running the
  sync** so datasci is not mid-test.
- Live-verified: OAuth code exchange works with the current `.env`; do not doubt the credentials.
  `/me/accounts` returning `{"data": []}` is still open with the architect — if my work reaches
  IG-account-resolution через the Page, STOP and ask.

---

## 8. A1 — objects gate (IN PROGRESS)

**Dependency decision made here, deliberately:** `boto3` is **not** added to
`packages/shared/pyproject.toml` in this slice. Adding it mutates `uv.lock` and forces the sync
that corrupts this venv, and the lead has asked to coordinate any sync. Instead the S3 client is
built behind a **lazy import inside the factory**, so `boto3` is imported only when the real R2
store is constructed. Tests drive an in-memory `ObjectStore` double and never import it. The
declaration gets batched with the `uvicorn` change at the end of the sprint, under coordination.
This is why A1 can land fully tested today with zero dependency churn.

### A1 DONE — verified 2026-07-29

**Files on disk** (`ls` confirmed, not asserted from memory):
- `packages/shared/src/qualify_shared/objects/__init__.py` — surface; deliberately does NOT
  re-export `R2ObjectStore`, so the import that reaches a real client stays visible at call sites.
- `.../objects/keys.py` — `tenant_prefix`, `media_key`, `require_tenant_prefix`,
  `TenantPrefixViolation`.
- `.../objects/config.py` — `R2Settings` frozen + `from_env()`, no dev fallback, redacting repr.
- `.../objects/gate.py` — `ObjectStore` Protocol, `ObjectGate.put_media` / `.open_object`,
  `MAX_MEDIA_BYTES = 300 MiB`, `ObjectSizeExceeded`, `UnsizedStream`.
- `.../objects/s3.py` — `R2ObjectStore`, the ONLY sanctioned S3 client site.
- `packages/shared/tests/test_objects_gate.py`, `test_objects_config.py`,
  `test_object_store_sanctity.py`.

**Verified, not believed:** `uv run --no-sync pytest -m "not integration"` → **204 passed**,
zero failures. The three new files contribute **29** of those. `ruff check` and
`ruff format --check` both clean over `packages/shared/`.

**Decisions taken inside A1 worth not re-litigating:**
- `put_media` measures the stream **from its current position** (SEEK_CUR, not absolute length)
  and restores it. Measuring absolute length would over-count a stream handed over mid-read AND
  store only the remainder while judging the whole. Both behaviours have tests.
- The size boundary is **inclusive** — exactly 300 MB is legal, since that is Meta's stated reel
  ceiling, not one byte below it.
- An **unseekable** stream is refused (`UnsizedStream`) rather than uploaded unmeasured: the
  ceiling must not silently stop applying for precisely the inputs most likely to be large.
- `put_object`, never `upload_fileobj` — the latter silently switches to multipart above a
  threshold, which is the exact behaviour the ceiling exists to forbid.
- The prefix is re-checked on **read** as well as write: a key read back from a DB row is still
  input, and the check costs a string comparison.
- Violation messages never echo the offending key (it can carry another tenant's id) — asserted
  by a test, since exception text reaches logs.
- `test_gate_exposes_no_presign_method` asserts the gate's public surface is exactly
  `{put_media, open_object}`. ADR 28c's "no public HTTP surface" is thereby enforced by a test
  rather than by review vigilance.
- The static guard includes **two self-tests** (a known-bad file must trip it; an innocent
  `client("redis")` must not). A static guard that silently matches nothing reads as protection
  while providing none — that failure mode is why they are there.

### A2 — BLOCKED, DDL proposal sent to architect 2026-07-29
Also asked in the same message: where the QUA-67 typed-shapes module lives (layout call, per the
lead's ruling in §7).

---

## 9. R9(f) DONE — `link_required` split + the two counters. Verified 2026-07-29.

Done BEFORE the rest of the plan at the lead's request, and I agreed: it is small, and without
it step 1 of R9(e)'s empirical test cannot be run at all. A1 was already finished when the
request arrived, so nothing was preempted.

**What changed** (`packages/api/src/qualify_api/connections/service.py`,
`packages/api/src/qualify_api/http/connections_routes.py`):
- New outcome `ConnectOutcome.PAGE_ACCESS_REQUIRED` — `/me/accounts` returned NOTHING.
  `LINK_REQUIRED` now means only the genuine R4 case: Pages came back, none carries an IG
  account. The two need OPPOSITE operator instructions, which is why they are separate members
  and not one member with a detail field somebody might not read.
- `_no_connection_outcome()` decides between them in one place.
- `ConnectResult` gained `page_count` and `linked_page_count`; both are also returned on the
  HTTP callback response, not only logged. The operator running step 1 is looking at a browser,
  not at a log tail — and counts carry no ids, names or token, so exposing them costs nothing.
- A `WARNING` log on every dead end carrying `outcome`, `pages`, `pages_with_ig`. First real run
  now produces the evidence instead of prompting a second run to go get it.
- The route now blanks `external_username` based on `connection_id is None` rather than on an
  enum comparison against a list of dead-end outcomes. R9(f) just added one such outcome; an
  enum check would have to be remembered every time another is added.

**R4's invariant is untouched and still asserted:** both dead ends persist zero connection, zero
credential, and still spend the jti.

**Verified, not believed:** `uv run --no-sync pytest -m "not integration"` → **209 passed**
(was 204 before this change). 9 tests cover this ruling, including
`test_dead_end_log_carries_counts_but_no_identifiers`, which asserts the log contains
`pages=1 pages_with_ig=0` and does NOT contain the token, page id or page name — all three are
in scope at that point in the flow. `ruff check` + `ruff format` clean.

**Checked for collateral damage:** `grep -rn "link_required" Qualify/` finds nothing, so no UI
consumer depended on the old single outcome.

**NOT done, deliberately (R9 forbids it):** the `/me/accounts` edge itself is untouched. R9(a)
closed the `[V]` — it IS the correct endpoint — and R9(e) forbids touching edge code before
step 1 runs.

---

## 10. Architect DDL sign-off 2026-07-29 — approved with THREE binding corrections

Recorded by the architect in `docs/arquitectura.md` §6 (ruling **R10** is new, see §11).

1. **`publish_attempts`: row-per-attempt with UPDATE — approved**, and the append-only precedent
   explicitly does NOT transfer. `connection_events` IS a log (its purpose is history);
   `oauth_credentials` is append-only for CUSTODY (never overwrite a secret in place). Neither
   reason applies to a table holding the state of ONE logical operation identified by
   `(connection_id, idempotency_key)`.
   **Condition I must implement: transitions are MONOTONIC.** `settled_at`,
   `published_media_id` and the terminal state are **write-once**, enforced as
   `UPDATE ... WHERE settled_at IS NULL` (or an equivalent CHECK) — *not* by trusting the
   caller. Without it a late reconciliation can overwrite an already-settled outcome with stale
   information, which is the exact failure ADR 22(e) exists to prevent. If transition history is
   wanted later, emit it to `connection_events`; the two shapes answer different questions.
2. **`scheduled_posts` gains `scheduled_tz TEXT NOT NULL`** (IANA name used at compose time).
   `scheduled_for TIMESTAMPTZ` stays and is what the scheduler fires on. Reason: `tenants.timezone`
   is MUTABLE and means "the tenant's zone now", not "the zone this post was composed under" —
   correcting a misconfigured zone would silently shift every scheduled post. Instant + zone
   reconstructs the wall clock the user typed, so do NOT also add a local-time column.
3. **`messages` UNIQUE is `(connection_id, external_message_id)`, WITHOUT `tenant_id`** — and not
   merely because it is narrower. Adding `tenant_id` would state a WEAKER invariant, implying the
   same `external_message_id` could coexist under the same connection in another tenant, which
   the composite FK already makes impossible. **The `tenant_id` denormalization exists for RLS,
   not for uniqueness.** `tenant_id NOT NULL` + composite FK stay as proposed.
4. **`window_expires_at`: derive, don't materialize — agreed, BUT my proposed base was a BUG.**
   The 24 h window is opened by the **inbound** message, not by any message:
   `overview.md:178` — *"An Instagram user **sends a message** ... Your app can use the API to
   respond within 24 hours."* **Replying does NOT extend the window.** Deriving from
   `last_message_at` (which includes outbound) would reopen a window Meta considers closed, and
   the system would permit sends the platform rejects — or accepts and counts as a policy
   violation. **Add `last_inbound_at TIMESTAMPTZ NULL` and derive from that.** Keep
   `last_message_at` for inbox ordering only. `NULL` in `last_inbound_at` means *no window ever
   opened*, which is NOT *window expired* — must not be collapsed (see R10).
5. **QUA-67 module layout: `packages/shared`, as `qualify_shared.social.ig_shapes`** — approved.
   A new package is rejected by ADR 26 reasoning (4); `qualify_models` is rejected by dependency
   DIRECTION (the API must not depend on the models package for a payload contract) and by the
   heavy `ml` group deps. **Condition:** the module is STRICTLY a contract — payload parsing and
   validation only. No DB access, no HTTP, no business logic. The moment it imports a session or
   a client it stops being shareable and becomes a second API.

## 11. R10 — the silent-zero invariant (architect generalized my §6 note)

Written to `docs/arquitectura.md` §6. The project's provenance rule covered what IS observed and
left uncovered what is NOT observed. A zero can mean four things and on this platform all four
occur: nothing happened; scope missing (comments, today); administrative gate (DM, O8); or
**silent platform exclusion** — media from private accounts never arrives, with no error, which
also affects mentions/tags.

Binding beyond the poller: **no coverage or recall metric may be computed over an interval where
observation was impeded** — mark a gap, do not average it down — and the gap must stay
identifiable so it can be backfilled when capability returns.

R10 also keeps the two lookalike gates separate: comments = **missing scope**, hours, under our
control; DM = **administrative clock**, weeks, outside it. That both currently return zero is
exactly why zero cannot be the datum.

## 12. B1 CANCELLED — the contract already exists, built by datasci

Lead verified the working tree; I verified it too (§13). `packages/models/src/qualify_models/social/ig_shapes.py`
(748 lines) + `packages/models/tests/test_ig_shapes.py` (420) + a regenerated
`synthetic_ig_comments.json`. It has everything B1 would have produced, including the
citations-resolve test.

**I write nothing for B1 and must not edit those files** (datasci territory). I CONSUME the
contract in B2: import the type and derive the columns from it rather than fixing shapes myself,
and use `parse_meta_timestamp` in ingestion rather than writing a parallel parser.

**OPEN CONFLICT I must not resolve unilaterally, routed to the lead:** the architect ruled the
module belongs in `packages/shared` as `qualify_shared.social.ig_shapes` (§10.5), but it was
BUILT in `packages/models/`. Someone must move it, and the file is datasci's. Moving it myself
would edit another agent's file, which the durable-findings rules forbid. Flagged; not acted on.

---

## 13. A2 + B2 DONE — migrations 0003/0004 applied, reversed, re-applied. Verified 2026-07-29.

**Files:** `migrations/postgres/versions/0003_publishing.py`,
`migrations/postgres/versions/0004_inbox.py`,
`packages/api/tests/test_publishing_inbox_schema.py` (8 `db`-marked tests).

**All three architect conditions implemented:**
1. **Write-once settle.** Implemented as a **BEFORE UPDATE trigger**
   (`publish_attempts_settle_once`), not as `UPDATE ... WHERE settled_at IS NULL` in the
   repository. Reason: a CHECK cannot see the previous row (the invariant is about the
   TRANSITION), and the architect's instruction was explicitly "not trusting the caller" — a
   repository convention is bypassable by a backfill script, a psql session or a future worker,
   a trigger is not. Plus a CHECK that `settled_at IS NULL` iff status is non-terminal, so the
   timestamp and the status cannot disagree about the same fact.
2. **`scheduled_tz TEXT NOT NULL`** added; `scheduled_for TIMESTAMPTZ` unchanged; NO local-time
   column (instant + zone already reconstructs the wall clock, a third column could disagree).
3. **`last_inbound_at`** added and documented as the window's only base; `last_message_at`
   demoted to inbox ordering with an explicit "NEVER the basis of the window" comment.
   `window_expires_at` is NOT a column.

**Contract-derived nullability (this is what reading QUA-67 first bought):**
`messages.posted_at` is **NULLABLE** because the contract marks comment `timestamp` as
`Presence.IF_REQUESTED`; `author_external_id`/`author_username` are NULLABLE because
`from`/`username` are `Presence.REQUIRES_PERMISSION`. Added `ingested_at NOT NULL DEFAULT now()`
so ordering never has to invent a timestamp. Had I written this DDL before reading the contract
I would have made all three NOT NULL and rejected payloads Meta legitimately sends.

**Verified against the live database, not asserted:**
- `alembic upgrade head` → 0002→0003→0004 clean.
- `alembic downgrade 0002` → clean, then `upgrade head` again → clean. **Reversibility gate met.**
  I downgraded only MY two revisions rather than to `base`, deliberately: the lead needs the
  seeded stack intact right now for the R9 step-1 test.
- Post-migration probe: all four tables exist, `relforcerowsecurity = True` on all four,
  tenants still seeded.
- `pytest -m db` → **36 passed**. `pytest -m "not integration"` → **217 passed**. ruff clean.

**A test I nearly shipped green-for-the-wrong-reason, recorded because the near-miss is the
lesson:** `_insert_attempt(settled=True)` originally bound the STRING `"now()"` as a parameter.
It passed — Postgres coerces it — so the trigger test was green. I checked the stored value
rather than trusting the green, confirmed a real timestamp, then rewrote the helper to
interpolate `now()` as SQL anyway. A test whose setup relies on an obscure coercion is a test
whose green cannot be read at a glance.

**Still OPEN and NOT mine to close:** the QUA-67 module is in `packages/models/` but the
architect ruled it belongs in `packages/shared` as `qualify_shared.social.ig_shapes` (§10.5).
Migration 0004's docstring currently cites `qualify_models.social.ig_shapes`; that reference
must be updated when the move happens. Routed to the lead; I am not moving another agent's file.

---

## 14. QUA-67 contract delivered by datasci — what it changes for my remaining slices

Module: `packages/models/src/qualify_models/social/ig_shapes.py` (43 offline tests green,
including one that re-verifies all 31 corpus citations still resolve). **I import it; I do not
re-derive anything from the corpus, and I do not edit it.**

**1. It VALIDATES the dedup design already in migration 0004 — this is the important one.**
`COMMENT_LIMITS` records that the comments edge is **not filterable by timestamp**, and
`INCREMENTAL_POLLING_NOTE` spells out the consequence: **an incremental poll cannot use a
since-cursor; dedup must be by comment id.** That is exactly what
`UNIQUE(connection_id, external_message_id)` + an `ON CONFLICT` upsert implements. Had the edge
supported a cursor, a cheaper design would have existed and the constraint would have been
belt-and-braces; it does not, so the constraint is load-bearing. **B4 must not be written
around a `since` parameter — there isn't one.**

**2. `user` XOR `username` — a modelling trap that my DDL happens to avoid, recorded so it is
not "fixed" into existence later.** `user` arrives ONLY when the app user wrote the comment;
otherwise `username` arrives. They are mutually exclusive and the model rejects both together.
My `messages` table has ONE identity column (`author_external_id`, the IGSID) and ONE display
column (`author_username`) — not two author columns racing each other. **The ingestion layer in
B4 resolves the XOR into those two columns; it must not add a second author column.**

**3. `replies=None` means "I did not request it", NOT "this comment has no replies."** They are
indistinguishable in the payload. A textbook R10 instance — an absent value with several
distinct causes that must not be collapsed.

**4. IGSID is not portable identity**, typed separately with `IGSID_IS_PORTABLE_IDENTITY = False`:
the same person messaging two businesses presents two different IGSIDs. `author_external_id`
**cannot be joined** across tenants, apps, or against any external source. Migration 0004 already
carries this as a column comment; it is now enforced by the type as well.

**5. DM half formally out**, encoded as `UNCOVERED_SURFACES["direct_messages"]` citing
`business-messaging/instagram-messaging/overview.md:122` — the same citation the architect gave
me. Three independent parties now agree on that gate.

**Useful API I will call rather than reimplement:**
`IGComment.policy_for(field)` → `FieldPolicy`; `IGComment.fields_requiring_permission(
"instagram_manage_comments")` → `{"username", "from_"}` — that set is exactly what B3's
"cannot-observe vs observed-nothing" check should consult instead of a hardcoded list;
`parse_meta_timestamp(value)` handles ISO-8601 and epoch.

---

## 15. STATE AT HANDOFF — what is done, what is next, what NOT to redo

**DONE, green, on disk (verified by running, not by memory):**
- **A1** objects gate — `packages/shared/src/qualify_shared/objects/` (5 modules) + 3 test files.
- **R9(f)** `link_required` split + the two counters — `connections/service.py`,
  `http/connections_routes.py`, `tests/test_oauth_callback.py`.
- **A2/B2** migrations `0003_publishing` + `0004_inbox`, applied AND reversed AND re-applied,
  plus `packages/api/tests/test_publishing_inbox_schema.py` (8 db tests).
- Suite state at handoff: **217 offline / 36 db, ruff clean.**

**NEXT, in order (approved plan, nothing blocked except where noted):**
- **A3** publish client seam — Protocol + Http impl + one `_parse_*` per endpoint marked `[V]`,
  mirroring `meta_oauth.py`. Endpoints: create container (`upload_type=resumable`), `rupload`
  byte upload, `GET ?fields=status_code`, `media_publish`, and reconcile-by-`creation_id`.
  Constants already pinned in §4. Nothing blocks this.
- **A4** publish service — write-ahead, 60 s/5 min polling, `debug_info.retriable`, no blind
  retry, `media_product_type` to confirm stories.
- **A5** scheduler — tenant timezone via `scheduled_tz`, `degraded` connection guard.
- **B3/B4/B5** ingest seam + comment source + poller + window (24 h from `last_inbound_at`).
  **DM transport stays unimplemented and MUST fail naming the gate** (verified business /
  Advanced Access), never a bare `NotImplementedError` — binding architect condition.
- **LAST, and only with the lead's go-ahead:** declare `boto3` (+ `uvicorn`) and run the sync.
  Coordinate first — sync is the venv-corrupting operation here.

**DO NOT REDO:**
- Do not rebuild the QUA-67 contract (§14) or edit anything in `packages/models/`.
- Do not touch the `/me/accounts` edge (R9(a)/R9(e) forbid it before the lead's step 1).
- Do not add `presign_get`, a public route, a token or a TTL (QUA-68 owns those).
- Do not re-derive corpus constants — §4 has them with citations.

**OPEN, not mine to close:** the shapes module sits in `packages/models/` but the architect
ruled it belongs in `packages/shared` as `qualify_shared.social.ig_shapes`. Migration 0004's
docstring cites the current path and needs updating after any move. Routed to the lead twice.

---

## 16. ig_shapes move — ALREADY DONE when I got the task. I verified it instead of redoing it.

**The lead's brief said the module was still in `packages/models`, intact, nothing half-moved.
That was stale by the time I read it.** Disk state when I checked:
`packages/shared/src/qualify_shared/social/{__init__.py,ig_shapes.py}` present,
`packages/shared/tests/test_ig_shapes.py` present, and `ig_shapes.py` GONE from
`packages/models/src/qualify_models/social/` (only a stale `__pycache__` entry left).
So `datasci` completed the move after reporting the permission denial.

This is the durable-findings Rule 4 case exactly: a report about disk is a belief, disk is the
fact. Had I followed the brief literally I would have tried to `git mv` a file that was no
longer there.

**What I did instead — verification of someone else's move, plus the parts that are mine:**

1. **Test-count reconciliation, because 40 ≠ 43.** The moved suite collects **40**; datasci
   reported **43**. A move that silently drops tests is the classic failure, so I did not accept
   the gap. I diffed test names in the stale `.pyc` at the OLD location against the new source.
   Result: **nothing lost.** Three fixture-instance tests were deliberately relocated to
   `packages/models/tests/test_ig_fixture_shape.py` (verified present, **3 passed**), next to
   the fixture they read. **40 + 3 = 43.**
2. **The citations test survived** — `test_every_citation_resolves_against_the_corpus` is
   present and green from the new location, so the corpus-relative paths still resolve. That was
   the specific silent-breakage risk the lead flagged.
3. **The architect's "strictly contract" condition still holds after the move** — verified by
   listing the module's imports: stdlib + pydantic only, no DB, no HTTP. The new
   `social/__init__.py` documents the condition, so the next person to add to it is warned.
4. **MY files, updated:** `migrations/postgres/versions/0004_inbox.py` lines 21 and 119 now cite
   `qualify_shared.social.ig_shapes`.
5. **datasci's NOTES, minimally updated** (lead explicitly instructed the path fix): mechanical
   path citations updated; the "the move did not happen" paragraph **preserved and marked
   SUPERSEDED** rather than rewritten — the record of the permission denial is the useful part,
   and rewriting another agent's account of their own session is not a path fix.

**Verified:** root suite **258 passed** (was 217 before the move), ruff clean.

**The lead's predicted side effect is CONFIRMED:** the contract's 40 tests now run in the default
gate. `packages/shared/tests` is in root `testpaths`; `packages/models/tests` is not.

**NEW GAP I FOUND, and it is the same trap in a new place — routed to the lead.** The three
relocated fixture tests live in `packages/models/tests/`, which is **NOT** in root `testpaths`
(verified: `--collect-only | grep -c test_ig_fixture_shape` → **0**). They pass when run
explicitly but do **not** run in the default gate. So the assertions that the synthetic fixture
still validates against the contract, and still carries its shape version, are exactly the ones
that will NOT fire if the contract drifts. The move improved gate coverage for the contract and
left its fixture-conformance tests outside — a smaller version of the same problem it fixed.
Not mine to fix: adding `packages/models/tests` to `testpaths` pulls in the heavy `ml` suite,
which is a root-`pyproject.toml` decision.

## 17. Post-move reconciliation + a lockfile divergence that changes my final sync step

**Count reconciled, nothing lost.** datasci reported 41 contract tests; I had measured 40. Both
were right at different moments — they added `test_the_contract_stays_strictly_a_contract`
(line 412) between my measurement and theirs. Verified now: the file collects **41**, and
`--collect-only | grep -c "test_ig_shapes.py::"` inside the root gate is also **41**, contained
within a total of **258**. The arithmetic closes; no test disappeared in the move.

That guard is a genuine improvement over what I did: I verified the architect's "strictly
contract" condition **once, by inspection**. datasci turned it into a **permanent test** that
fails if the module ever imports sqlalchemy, psycopg, httpx, requests, fastapi, `qualify_api`,
`qualify_models` or `qualify_shared.db`. An inspection protects the moment; a test protects the
condition.

**NEW — `uv.lock` has diverged from a manifest, and it lands on my final sync step.**
Verified two ways:
- `packages/models/pyproject.toml` now declares `qualify-shared` under `[project].dependencies`
  (datasci, to make `test_ig_fixture_shape.py` import the moved contract).
- `uv.lock` is **unmodified** (`git status --short uv.lock` → empty), and parsing it confirms
  `qualify-shared` is **NOT** listed under the `qualify-models` package block.

They deliberately did not run `uv sync` — correct, given the trap. But the consequence is that
**the one coordinated sync at the end of the sprint is no longer "add boto3 + uvicorn".** It now
also reconciles a third, already-pending change from another agent. Concretely, that sync must
resolve:
1. `boto3`/`botocore` → `packages/shared` (mine, for `objects/s3.py`'s lazy import).
2. `uvicorn` → `packages/api` (mine, the HTTP-artifact debt).
3. `qualify-shared` → `packages/models` (datasci's, already written, unsynced).

Nothing is broken meanwhile: `packages/models/pyproject.toml` also carries
`pythonpath = ["src", "../shared/src"]`, the same belt-and-suspenders the root config uses, so
the import works today without the sync. But a `uv sync` run expecting to touch only my two
packages will silently also act on models, and whoever runs it should know that BEFORE seeing
the resolver output rather than after.

**Ownership note:** `packages/models/pyproject.toml` is de-facto mine per the file map; datasci
flagged the edit rather than making it silently, which is the right call and is why I found it
by reading their message instead of by a mystery lock conflict later. I am NOT reverting it —
the change is correct.

---

## 18. R11(d) DONE — testpaths audited. Verified 2026-07-29.

Lead gave explicit authorization to touch the root `pyproject.toml` for this, which is the
approval I had reserved.

**What I built:**
- Root `pyproject.toml`: new `[[tool.qualify.test-gate.excluded]]` entries — one per excluded
  directory, each carrying a REASON, sited next to `testpaths` so both halves of the decision
  are read together. Two entries: `packages/models/tests` (R11(b): collecting it drags torch
  and the `ml` group into the gate, i.e. trades a silent gap for an unstable gate) and
  `packages/docs-harvester/tests` (the third instance R11 found; never a deliberate decision
  until now, and flagged to move into the gate if it ever asserts against a shared contract).
- `packages/shared/tests/test_gate_coverage.py` — 5 tests. It discovers `packages/*/tests`
  **from the filesystem**, not from any list (a list cannot notice a directory nobody added to
  it), and fails on any directory that is neither collected nor explicitly excluded.

Beyond the ruling's letter, it also fails on: an exclusion whose reason is too thin to
evaluate (an unjustified exclusion is a silent gap with extra syntax — that is how a deny-list
degrades back into the allow-list it replaced); a **stale** exclusion naming a directory that
no longer exists (it implies a considered decision about something gone, and hides that the
real directory may have moved somewhere unaudited); and a path declared both collected and
excluded (pytest resolves that silently, so the reader is told one thing while the gate does
another).

It lives in `packages/shared/tests` because that directory is itself inside the gate — an
auditor outside the thing it audits would be the same bug it audits for.

**Verified by actually breaking it, not by reading it:** created a real `packages/ghostpkg/tests`
directory, re-ran, and the audit FAILED naming `packages/ghostpkg/tests`; then removed it and
confirmed the directory is gone. Plus an in-suite self-test so a future refactor of the set
comparison cannot leave the assertions vacuously true.

**Suite: 263 passed** (was 258; +5, all from this new file — the lead's condition was that the
count must not drop, and I confirmed the delta is exactly the new tests, nothing else entered).
ruff clean.

**R11(a) NOT DONE — deliberately, and it is the remaining half of the ruling.** (a) requires
moving `synthetic_ig_comments.json` AND `test_ig_fixture_shape.py` into `packages/shared/tests/`,
with the sentiment tests staying in models reading the fixture from shared. Rationale in the
ruling: `qualify_models` depends on `qualify_shared`, so `shared` must never reach into
`models`; moving only the tests would invert the dependency direction. **The fixture is
datasci's file and I was explicitly told not to touch it**, and the lead's task named (b)/(c)/(d)
only. Routed to the lead. Until (a) lands, the `packages/models/tests` deny-list entry is
covering a directory that still holds a shared-contract conformance test — which R11's positive
invariant says should not be there. The deny-list is honest about the current state; it is not
an endorsement of it.

## 19. R11(a) DONE — fixture + conformance tests moved to shared. Verified 2026-07-29.

Lead extended the R11 task to include (a) with an explicit, scoped ownership exception over
`packages/models/tests/` (move only; no content edits beyond what relocation forces).

**Moved:**
- `packages/models/tests/fixtures/synthetic_ig_comments.json` → `packages/shared/tests/fixtures/`
  (`git mv`, history preserved).
- `packages/models/tests/test_ig_fixture_shape.py` → `packages/shared/tests/`
  (**plain `mv`** — the file was UNTRACKED, so `git mv` fails with "not under version control".
  Worth knowing before the next move in this repo, where most of the tree is uncommitted.)
- `packages/models/tests/fixtures/` keeps ONLY the media files; untouched.

**Dependency direction, which is the whole reason for (a):** `test_ig_comments.py` (sentiment)
STAYS in models and now reaches toward `packages/shared/tests/fixtures/`. The consumer reaches
the contract; never the reverse. Moving only the tests would have forced `shared` to look inside
`models` — same hop count, forbidden direction.

**Content edited only where relocation forced it:** the moved file's docstring described its own
location ("Lives here rather than beside the contract") and would have been a lie. Rewrote it to
state both reasons for the new home. No test logic touched.

**Verified against every condition the lead set:**
- Conformance tests collected by the DEFAULT gate: **3**, confirmed with `--collect-only` and by
  name, not inferred from the total.
- Root suite **266 passed** — was 263 after R11(d), 258 before. Delta **+3 = exactly the moved
  tests**; nothing else entered.
- Corpus-citations test **green from the new location** (the silent-breakage risk of any move).
- Sentiment tests in models: **11 green**, fixture found at its new path.
- Gate audit itself still green; ruff clean.

**Recorded in `.claude/sprint-state-2026-07-29-sprint2-arranque.md` §9** per the new convention
(executor annotates the move; §9 only — I edited nothing else in that file).

**R11 is now complete: (a) moved, (b) not done deliberately, (c) not done deliberately, (d) built
and audited.** The tension I flagged in §18 is RESOLVED — `packages/models/tests` no longer hosts
a shared-contract conformance test, so its deny-list entry is now honest AND correct rather than
merely honest.

## 20. SELF-CORRECTION — I over-claimed to the lead, and the claim was about disk

When I delivered R11(d) I told the lead the deny-list tension was written *"into the entry's own
reason text so nobody reads the deny-list as 'resolved'"*. **That was false.** I had written it in
this state file (§18) and in the message, but the `reason` string in the root `pyproject.toml`
contained only the `ml`/torch justification. I found it by re-reading the file when the lead asked
me to update that reason — not by remembering.

This is the exact failure the durable-findings Rule 4 names, committed by me while I was busy
applying Rule 4 to everyone else's reports: **"I wrote X" is a belief about my own past tool
calls; the filesystem is the fact.** The near-miss is instructive — the claim was plausible
because I *had* written that sentence, just not where I said. Writing something in three places
and mis-remembering which one received it is not an exotic failure mode; it is the normal one.

**Corrected:** the `packages/models/tests` reason now states that the exclusion is legitimate
only because what remains is package-local model work, records that this became true on
2026-07-29 with R11(a), and instructs that a future shared-contract assertion landing there be
MOVED OUT rather than have this reason widened.

**Re-verified on disk rather than recalled:** `packages/shared/tests/fixtures/synthetic_ig_comments.json`
and `packages/shared/tests/test_ig_fixture_shape.py` both present;
`packages/models/tests/test_ig_fixture_shape.py` absent. Gate audit 5 green, root suite
**266 passed**.

---

## 21. A3 FINDING — two Authorization schemes, and the existing resolver seam only speaks one

Verified against the corpus before writing any client code.

**Meta uses a different `Authorization` scheme per host:**
- `graph.facebook.com` → `Authorization: Bearer <token>`
  (`content-publishing.md:84,212,272,305`; `resumable-uploads.md:41`)
- `rupload.facebook.com` → `Authorization: OAuth <token>`
  (`content-publishing.md:164,174`; `resumable-uploads.md:92,102`)

**This collides with C-03's seam.** `InjectingCredentialResolver.client_for()` returns a
`_BearerClient` that hardcodes `headers={"Authorization": f"Bearer {token}"}`
(`packages/api/src/qualify_api/connections/resolver.py:58-63`). The byte upload to `rupload`
therefore CANNOT go through the existing authenticated-client seam unchanged. That seam is
deliberately narrow — the whole point is that workers receive a client and never a token — so
widening it is not mine to do unilaterally.

**AND the corpus contradicts itself on `media_publish`,** which is a `graph.facebook.com` call:
shown with `Bearer` at `content-publishing.md:305` and with `OAuth` at
`resumable-uploads.md:137`. So "scheme follows host" is ALMOST right but not textually clean.

This is the same class as ADR 25's four scope spellings: **the documentation disagrees with
itself, so no single spelling may be hardcoded from reading.** Applying that precedent, the
scheme becomes a per-host value with a corpus-cited default, not a literal buried in a client.
It is also not resolvable offline — settling it needs one live call, which lands with the
lead's account work, not with me.

**Design consequence for A3 (mine to decide, and I am taking the reversible option):** the
publish client takes the auth scheme as data per host, defaulting to the corpus reading
(`Bearer` for graph, `OAuth` for rupload). If a live call later shows Meta accepts one scheme
everywhere, deleting a parameter is cheap; discovering a hardcoded literal is wrong at 3am is
not.

**ROUTED:** the `_BearerClient` limitation is a C-03 seam question. Raised with the architect —
either the resolver grows a scheme parameter, or the publish client gets a narrow sanctioned
exception. **I have not modified `resolver.py`.**

## 22. A3 DONE — publish client seam. Verified 2026-07-29.

**Files:** `packages/api/src/qualify_api/publishing/{__init__.py,client.py}`,
`packages/api/tests/test_publishing_client.py` (30 tests).

Mirrors `meta_oauth.py`: `PublishClient` Protocol + `HttpPublishClient` + one `_parse_*` per
endpoint marked `[V]`. Tests drive the REAL client through `httpx.MockTransport`, so URL
construction and headers are exercised — testing the parse functions alone would leave the
part most likely to be wrong (which header goes to which host) unexercised. That choice paid
off immediately; see the bug below.

**Corpus-pinned, not invented:** five `ContainerStatus` values (`content-publishing.md:318-322`),
60 s/5 min poll cadence (`:324`), `REELS|STORIES|VIDEO` (`resumable-uploads.md:32`), the two
auth schemes, `debug_info.retriable` (`:187-194`).

**REAL BUG the tests caught, which would have reached production:** passing the `IO[bytes]`
from `qualify_shared.objects.open_object()` straight to `httpx.AsyncClient(content=...)`
raises `RuntimeError: Attempted to send an sync request with an AsyncClient instance`. boto3's
`get_object()["Body"]` is a SYNC stream; the async client requires an async iterable. The
obvious fix — `content=fileobj.read()` — would hold a whole 300 MB reel in memory, silently
converting a streaming upload into a buffered one. Fixed with `_achunks()`, an async generator
yielding 8 MiB chunks, so memory stays flat regardless of file size. **Two tests now assert
the streaming property itself** (that `read(size)` is called repeatedly, never once unbounded;
and that every byte including the tail arrives) — otherwise "it streams" would be an
unverified docstring claim.

**Design decisions worth not re-litigating:**
- `ContainerStatus` is five states, not a ready/not-ready bool. `ERROR`/`EXPIRED` are terminal
  failures that must never be retried into, and `PUBLISHED` is how reconciliation learns that
  an ambiguous publish actually succeeded. `FINISHED` is deliberately NOT terminal — it means
  "ready to publish", so work continues.
- An **unknown** `status_code` raises rather than being coerced. Reading a sixth value as
  IN_PROGRESS would make the poller wait out its ceiling; as ERROR would abandon a live publish.
- `retriable` absent ⇒ `None`, never `False` (R10 applied to a flag): "Meta said nothing" is not
  "Meta said no", and collapsing them turns a recoverable failure into an abandoned one.
- `media_publish` returning no id **raises**, because that is the documented ambiguous case
  (`content-publishing.md:316`) the service must answer by reconciling on `creation_id`, not by
  retrying.
- `IMAGE` is refused locally before any request — it is a scope error (QUA-68), not a bad
  request, and the client has no `cover_url` path at all (asserted on the wire).
- Auth scheme is a per-host parameter with the corpus default, per §21.

**Verified:** `pytest packages/api/tests/test_publishing_client.py` → **30 passed**. Full
offline suite **296 passed** (was 266). ruff clean.

**NEXT: A4** (publish service: write-ahead → poll at pinned cadence → reconcile, no blind
retry) then A5 (scheduler). The client is the seam A4 consumes; A4 is where
`publish_attempts` and the settle-once trigger get exercised together.

## 23. A3 REWORKED per R12 — scaffolding deleted, wired onto the credential seam

The architect approved option (a) and **rejected (b)**, my own transport, as a second door past
the credential gate. Correct call, and the corollary was explicit: the scaffolding must not
land. It has been deleted, not merged.

**Also: the architect found the contradiction is WORSE than I reported, which strengthens the
case.** It is not only across documents — `resumable-uploads.md` shows `Bearer` for the
container on `graph.facebook.com` (:41) and `OAuth` for `media_publish` on that SAME host
(:137), while `content-publishing.md` uses `Bearer` throughout its graph examples. So "scheme
follows host" is not *almost* a rule; **it is not a documented rule at all.** The only corpus
invariant is that `rupload` is never shown with `Bearer`.
(Their correction to my citation: `:305` is `/media` with branded content, not `media_publish`;
the `Bearer` `media_publish` is `:212`. Substance unchanged.)

**What changed:**
1. `MetaOAuthSettings` gains `graph_auth_scheme` / `rupload_auth_scheme`, env-overridable
   (`QUALIFY_META_GRAPH_AUTH_SCHEME`, `QUALIFY_META_RUPLOAD_AUTH_SCHEME`), with the corpus
   citation in the docstring. **The literal lives in exactly one place** — passing `"OAuth"`
   from the publisher would only have moved the hardcode.
2. `CredentialResolver.client_for(connection_id, *, scheme)` — **no default.** A `Bearer`
   default makes the safe case invisible and the dangerous one opt-in: forget the argument and
   you get `Bearer` against `rupload`, discovered in production.
3. `_BearerClient` → `_InjectedAuthClient`. The old name became a lie the moment two schemes
   existed, and it sits on the credential door, which gets audited.
4. `HttpPublishClient` now takes **two `AuthenticatedClient`s**, one per host, and builds no
   transport. **There is no token in that file at all.**
5. `verifier.py` names `settings.graph_auth_scheme` explicitly at its one call site.

**The resolver did NOT learn what `rupload` is** — that would be the mirror-image coupling.

**New tests worth naming:** the schemes are env-overridable without a code change (so one live
call settles R12 by configuration, not redeploy); the publish client holds no token attribute;
and the existing upload test now proves that per-request `offset`/`file_size` headers MERGE
with the injected `Authorization` rather than replacing it — if httpx ever changed that, the
upload would go out unauthenticated and look like a Meta fault.

**Verified:** full offline suite **298 passed** (was 296), ruff clean. Grep confirms no
`_BearerClient` and no self-built transport remain in the publishing path.

**`DISCREPANCIES.md` §4 written** (architect said go ahead, no permission needed) with the
per-file table showing one document contradicting itself.

**Noted, not mine:** `DISCREPANCIES.md`, `ACCESS-MODEL.md` and `LOGIN-FORK-AND-MENTIONS.md` are
hand-written analysis living inside a harvested tree — a re-harvest could overwrite them.

---

## 24. CLEAN STOP — state at end of turn, 2026-07-29

Stopping here deliberately: the lead was explicit that the sprint does not have to close today
and that a clean stopping point beats a forced half-slice. **A4 is NOT started** — no partial
module on disk, nothing half-wired.

**Verified at this instant, by running:**
- `uv run --no-sync pytest -m "not integration"` → **298 passed**
- `uv run --no-sync pytest -m db` → **36 passed**
- `ruff check` + `ruff format --check` over `packages/api packages/shared packages/scraper
  migrations` → **clean, 89 files formatted**

**Minor finding, not mine and not urgent:** repo-wide `ruff check .` reports **12 errors** and
37 files needing format — **all of them in `.claude/skills` (10) and `.agents/skills` (2)**,
i.e. skill helper scripts, zero in any package. Worth knowing because anyone running the
bare repo-wide command sees red that belongs to nobody's package and may assume the tree is
dirty.

### Delivered this turn (all green, all on disk)
| Slice | What |
|---|---|
| **A1** | objects gate — `qualify_shared/objects/` (5 modules) + 3 test files |
| **R9(f)** | `link_required` split + the two counters — **validated in production on its first real run** |
| **A2/B2** | migrations `0003_publishing` + `0004_inbox`, applied/reversed/re-applied + 8 db tests |
| **R11(a)+(d)** | fixture move + `testpaths` deny-list with audit (5 tests) |
| **A3** | publish client seam + R12 rework — 32 tests |
| **R12** | scheme as settings, `client_for(..., scheme=)` no default, `_InjectedAuthClient` rename |
| **docs** | `DISCREPANCIES.md` §4; arranque §9 annotated (move + rename) |

### NEXT — A4, not started. Everything it needs already exists.
Write-ahead BEFORE the attempt (`idempotency_key`, `creation_id`, `tenant_id`, `connection_id`,
`adapter_version`, raw response) → poll at the pinned 60 s / 5 min → **no blind retry**,
reconcile by `creation_id` using `debug_info.retriable` → confirm story via
`media_product_type`, never `media_type`.

Underneath it, ready: `ObjectGate.open_object()` (A1), `publish_attempts` + the settle-once
trigger (A2), `PublishClient` (A3), `CredentialResolver.client_for(..., scheme=...)` (R12).
**Suggested first slice:** the write-ahead + reconcile decision logic against a fake
`PublishClient`, with no DB — then wire the repository. Each half ends green alone.

### Still open, none blocking A4
- **R12 `[V]`** — one live call settles which auth scheme Meta actually wants. Config, not code.
- **`uv.lock` divergence** — the final sync now reconciles THREE changes (`boto3` → shared,
  `uvicorn` → api, `qualify-shared` → models). **Lead owns scheduling it; do not run it solo.**
- **DM transport** stays unimplemented and must fail NAMING the gate (verified business /
  Advanced Access), never a bare `NotImplementedError`.
