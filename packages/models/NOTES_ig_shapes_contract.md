# QUA-67 — Instagram comment/DM field-shape contract: corpus findings

Author: `datasci`, 2026-07-29. Scope: offline reading of `reference/meta-instagram-platform/`.
No network, no connected account, no API calls.

**Status: DELIVERED (comments half).** The contract is on disk at
`packages/shared/src/qualify_shared/social/ig_shapes.py`, tested by
`packages/shared/tests/test_ig_shapes.py` (40) + `packages/models/tests/test_ig_fixture_shape.py`
(3) = 43 tests, offline, and `tests/fixtures/synthetic_ig_comments.json` is regenerated as a valid instance
of it. The DM half was **cut** — see §1 resolution. Build summary in §9.

This file remains the durable record of what was read out of the corpus, so the reading does
not have to be redone.

Every claim below cites a file and line in the corpus. Check them; do not take my word.

---

## 0. Corpus hygiene — which tree to read, and which to never parse

The corpus contains **two trees holding the same pages**:

| Tree | Files | State |
|---|---|---|
| `reference/meta-instagram-platform/instagram-platform/` | 84 `.md` | clean text |
| `reference/meta-instagram-platform/documentation/instagram-platform/` | 155 `.md` (whole `documentation/` subtree) | **HTML-entity-escaped** |

The `documentation/` copies are escaped: `<br>` appears as `&lt;br&gt;`, `{` as `&#123;`,
`'` as `&#039;`, `&` as `&amp;`. Compare
`instagram-platform/instagram-graph-api/reference/ig-comment.md:25` against its
`documentation/…` twin — same line count, different bytes.

Confusingly, **`manifest.jsonl` records the escaped copy as the harvested one**
(`local_path: "documentation/instagram-platform/instagram-graph-api/reference/ig-comment.md"`),
and the clean top-level tree is not in the manifest at all. So the manifest points at the
worse copy.

**Rules that follow:**
- **Read** from `instagram-platform/…` when the page exists there. It is what QUA-67's
  Evidencia section cites and what `LOGIN-FORK-AND-MENTIONS.md` cites — the established
  convention.
- **Never programmatically parse** `documentation/…`; an extractor would ingest `&lt;br&gt;`
  as literal field text.
- The `documentation/` tree is nonetheless **larger and not a strict duplicate**: the whole
  `documentation/business-messaging/` subtree (Messenger-Platform-for-Instagram docs) exists
  **only** there. So "read the clean tree" is not sufficient — some pages only exist escaped.

---

## 1. FINDING THAT CHANGES THE TICKET'S PREMISE — the DM half cites the wrong login fork

**This invalidates one acceptance criterion of QUA-67 as written, and constrains QUA-20.**

QUA-67's DM acceptance criterion names
`instagram-platform/instagram-api-with-instagram-login/conversations-api.md` as the source
of truth for conversation/message shapes. **That document describes the Instagram Login
fork, which Qualify structurally cannot use.**

### The fork is exclusive
`instagram-platform/app-review.md`: *"Your app can either use Facebook Login or Instagram
Login but not both."* (already recorded in `reference/meta-instagram-platform/LOGIN-FORK-AND-MENTIONS.md`).

### Qualify is on the Facebook Login fork
- ADR 25 (`docs/arquitectura.md` §6) is signed for **Facebook Login for Business**.
- The scopes actually granted and working against the live account are `instagram_basic`,
  `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` — **all Facebook
  Login vocabulary** (the Instagram Login fork uses `instagram_business_*`).

### What `conversations-api.md` actually documents
`conversations-api.md:28,32,40-41` — host `graph.instagram.com`, endpoint
`/<IG_ID>/conversations`, permissions `instagram_business_basic` +
`instagram_business_manage_messages`. **Instagram Login fork, end to end.**

### What the Facebook Login fork uses instead
`documentation/business-messaging/instagram-messaging/get-started.md:133` —
`GET graph.facebook.com/{page-id}/conversations?platform=instagram`, with a **Page access
token**, not a user token. This is the **Messenger Platform Conversations API**.

### And that reference page is NOT IN THE CORPUS
`manifest.jsonl` records
`https://developers.facebook.com/documentation/business-messaging/messenger-platform/conversations`
as **`skipped_out_of_scope`** ("outside the approved allowlist"). `find . -path
'*messenger-platform*' -name '*.md'` returns **0 files**. Every business-messaging page that
needs it links out to it.

### Consequence
**The DM shape contract cannot be fixed to the same evidentiary standard as the comment
contract, offline, from this corpus.** The only in-corpus sample of the Facebook-Login
conversation list is `get-started.md:140-160`, and it returns **only `{"id": ...}` per
thread — no `updated_time`**, unlike the Instagram-Login sample at `conversations-api.md:65-79`
which does carry `updated_time`.

Options (architect's call, not mine): (a) fix the DM contract as *provisional, Instagram-Login
shaped*, explicitly labelled as the wrong fork; (b) narrow QUA-67 to comments only and split
the DM contract into a new issue blocked on harvesting the Messenger Platform pages;
(c) extend the harvest allowlist to cover `business-messaging/messenger-platform/*` and then
fix the DM contract. **My recommendation is (c) then (b) as fallback** — the harvest is cheap
and the alternative is shipping a typed contract for a fork we cannot call.

### RESOLUTION 2026-07-29 — (b) applied, and for a stronger reason than mine

The architect had already ruled the DM surface **not buildable** on the signed fork, recorded
as ADR 25 point **(O8)**. The decisive citation is one I had not found:

> `documentation/business-messaging/instagram-messaging/overview.md:122` —
> *"Apps with Standard Access can only interact with people who have a role on the app"*

(verified independently, 2026-07-29). A real customer sending a DM holds no role on the app,
**by definition**. So the blocker is not the missing harvest — extending the allowlist (my
option (c)) would have produced an accurately-typed contract for an API that still cannot be
called. The harvest gap I found is real but secondary; this ruling is what closes the path.

**Applied:** QUA-67 narrowed to **comments only**. The DM shape contract moves to a new
Linear issue, blocked on the same Business Verification / Advanced Access gate that blocks the
transport. The exclusion is encoded machine-readably as `UNCOVERED_SURFACES["direct_messages"]`
in `ig_shapes.py`, with this citation, so a consumer asking "is the DM surface promised?" gets
a lookup rather than prose.

### Bonus precondition, non-obvious, relevant to QUA-20
`get-started.md:129` — under the Facebook Login fork the account owner must **manually**
enable *Instagram Settings > Messages and story replies > Message controls > Connected Tools >
Allow Access to Messages*. This is a **human toggle in the Instagram app**, not an OAuth
scope. No amount of correct scope grants will make the DM endpoints work without it. A poll
that returns empty is therefore ambiguous between "no DMs" and "toggle off".

---

## 2. Comments — the half that IS solidly fixable offline

Field shapes for comments are **fork-agnostic**: `ig-comment.md:20-25` and
`ig-media/comments.md:13-18` present both forks side by side and the field list is the same;
only the permission vocabulary, host URL and token type differ. So the comment contract can
be fixed now and only the *permission-conditionality* needs a fork axis.

### Fields (`ig-comment.md:69-82`)

| Field | Shape | Notes |
|---|---|---|
| `id` | str | IG Comment ID |
| `text` | str | comment text |
| `timestamp` | str | **ISO 8601**, example `2017-05-19T23:27:28+0000` (line 80) |
| `from` | object `{id, username}` | `id` is an **IGSID** (line 71) |
| `username` | str | **permission-conditional**, see §3 |
| `user` | str (ID) | **only if the app user created the comment; otherwise `username` is returned instead** (line 81) — mutually exclusive with `username`, not two always-populated columns |
| `parent_id` | str | present when the comment is a reply (line 77) |
| `hidden` | bool | line 72 |
| `like_count` | int | line 74 |
| `media` | object `{id, media_product_type}` | line 76 |
| `replies` | list of IG Comments | edge; **not returned unless field-expanded** |
| `legacy_instagram_comment_id` | str | Marketing-API-era ID, v21.0 and older (line 75) |

Two fields are explicitly **not supported** on this node (`ig-comment.md:13-16`):
`comment_type`, `mentioned_instagram_users`. Worth encoding as forbidden, since a naive
schema author would reach for `comment_type`.

### Nullability reality check
The only fields the corpus's own worked example returns are `hidden`, `media.id`,
`timestamp`, `id` (`ig-comment.md:112-121`) — because `fields=` was set to just those.
**Graph API returns only what you ask for.** So *every* field except `id` is
absent-by-default; nullability in the contract must mean "absent unless requested AND
permitted", which is a different thing from "the API may return null".

The `/comments` edge sample (`ig-media/comments.md:89-104`) returns only
`timestamp`, `text`, `id` — no `from`, no `username`.

---

## 3. Permission-conditional fields — and what today's grants actually allow

`ig-comment.md:82`: from **2024-08-27**, reading `username` of a *commenter* requires
`instagram_manage_comments` (Facebook Login) or `instagram_business_manage_comments`
(Instagram Login).

`ig-media/comments.md:70-78`: reading the comments edge **at all** requires `instagram_basic`
+ `instagram_manage_comments`, and additionally `ads_management` **or** `ads_read` if the
token's Page role was granted via Business Manager.

**Against today's actual grants** (`instagram_basic`, `instagram_content_publish`,
`pages_show_list`, `pages_read_engagement` — `instagram_manage_comments` **NOT granted**):

> **The comments edge is not currently readable at all.** Not "readable without usernames" —
> `instagram_manage_comments` gates the edge itself, per `ig-media/comments.md:70-73`.

This is a harder constraint than the lead's briefing assumed (it framed the missing scopes as
affecting *which fields* arrive). It does not block QUA-67 — the contract is offline — but it
**does** mean QUA-20's comment poll returns nothing until that scope is added, and QUA-21's
real-payload substitution inherits that. Flagged to `team-lead` and to `pipeline`.

**Severity update 2026-07-29 (from `team-lead`) — do NOT over-correct on this.**
`instagram_manage_comments` is **Standard Access, auto-approved** for Business-type apps: it
is not behind App Review or Business Verification, unlike the DM gate in §1. It is simply not
in `QUALIFY_META_SCOPES` yet because the live test used four minimal scopes. Fix = add it to
the consent request and re-consent. **Comments remain the viable vertical slice**; the poll is
temporarily empty, not structurally blocked. The contrast with §1 is the whole point: the DM
surface is blocked by a gate we cannot open on our own timetable, the comment surface by a
scope we simply have not asked for.

### Other conditionality
- `ig-comment.md:39` — comments discovered via the Mentions API are **not readable** unless
  the requester owns the comment; use the Mentioned Comment node instead.
- `ig-comment.md:40-42` — comments on **age-gated media** are not returned; comments by users
  the app user has **restricted** are not returned unless unrestricted and approved.
- `ig-comment.md:42` — comments on **live video** are readable only *while the broadcast is
  live*.

---

## 4. The timestamp contradiction — confirmed, and it is worse than the ticket states

QUA-67 flags that `conversations-api.md` documents epoch while its own example returns ISO.
Verified:

| Location | Documented/returned |
|---|---|
| `conversations-api.md:70` | `"updated_time": "<UNIX_TIMESTAMP>"` |
| `conversations-api.md:131,134,138` | `"created_time": "<UNIX_TIMESTAMP…>"` |
| `conversations-api.md:173` | `"created_time": "2022-07-12T19:11:07+0000"` — **ISO 8601** |
| `ig-comment.md:80` | `timestamp` — ISO 8601, `2017-05-19T23:27:28+0000` |

So: comments are consistently ISO; DM timestamps are **self-contradictory within one page**.
A defensive parser accepting both and normalising to UTC-aware is the only defensible move.

**Additional defect not in the ticket:** the conversation-list sample at
`conversations-api.md:65-79` is **not valid JSON** — `"data":` is followed by `{…},{…}` and
closed with `]`, with the opening `[` missing, and `"<CONVERSATION_ID_1"` is missing its
closing `>`. Line 99-107 has the same missing-`>` defect. These samples therefore **cannot be
lifted into fixtures verbatim**; they must be hand-repaired, and the repair is an assumption,
not evidence.

---

## 5. Collection limits and pagination traps (contract constants, not loose numbers)

### Comments (`ig-media/comments.md:61-66`)
- **Maximum 50 comments per query.**
- **Top-level only** — replies excluded unless `replies` is field-expanded.
- **Cannot be filtered by timestamp.** (So incremental polling cannot use a since-cursor;
  dedupe must be by comment id.)
- **Reverse chronological** on v3.2+; chronological on v3.1 and older.

### DMs (`conversations-api.md:154`)
- The conversation endpoint returns **all** message IDs, but **only the 20 most recent can be
  read**. Querying older ones returns an error saying **the message has been deleted** —
  *which is false*. This is a lying error message and must be encoded in the contract or its
  test, not discovered in production.
- `conversations-api.md:47` — conversations in the **Requests** folder inactive for 30 days
  are not returned at all.
- `conversations-api.md:45` — for a *share*, only the image/video URL is included.

---

## 6. Person identity — IGSID, and it is not portable

`ig-comment.md:71` — `from.id` is an **Instagram-scoped ID (IGSID)**.
`documentation/business-messaging/instagram-messaging/features/user-profile.md:5` — the User
Profile API is keyed on IGSID.
`documentation/business-messaging/instagram-messaging/changelog.md:541` — **IGID was
deprecated** and the Conversation API relies **fully on IGSID** as of 2021-12-14.

Consequence for the schema (architect's call, but the constraint is factual): an IGSID is
scoped to the app/account pair. It is **not** a portable Instagram user identity, so an
author column keyed on it **cannot** be joined across tenants, across apps, or against any
external identity. Two rows with different IGSIDs may be the same human; the same IGSID
means the same human only *within* one app+account scope. If the CRM later wants a person
entity, IGSID is a per-connection alias, not the identity key.

---

## 7. What the contract explicitly does NOT cover

- **Non-organic comments** (comments on ads) are *a different type and are not supported* on
  this edge; they require the Marketing API via the ad's `effective_instagram_media_id`
  (`ig-media/comments.md:7-9`).
- Comments on **age-gated** media and on **live video** (§3).
- **Webhook payloads** — different shape, and unreachable for customer zero (needs Live mode
  + Advanced Access + Business Verification). Out of scope per the ticket.
- **Reply-creation** semantics are read-adjacent but out of scope: note
  `ig-comment/replies.md:25-26` — you can only reply to top-level comments; a reply to a reply
  is silently reparented to the top-level comment; hidden comments cannot be replied to.

### Corpus typo worth not copying
`ig-comment/replies.md:36` **and `:76`** list the permission as **`page_read_engagement`**
(singular `page_`). Everywhere else in the corpus it is `pages_read_engagement`. This is a
Meta typo, repeated twice on the same page; do not propagate it into any scope list.

---

## 8. What was built (2026-07-29)

### `packages/shared/src/qualify_shared/social/ig_shapes.py`

- `IGComment` (+ `IGCommentFrom`, `IGCommentMedia`, `IGCommentsPage`) — all 12 fields the
  ticket named, typed and nullable.
- **Conditionality lives in the type, not in comments.** Each field is
  `Annotated[T, FieldPolicy(...)]` carrying a `Presence` enum
  (`ALWAYS` / `IF_REQUESTED` / `REQUIRES_PERMISSION` / `IF_OWNED_BY_APP_USER` /
  `EXPANSION_ONLY`), the required permission, mutual exclusions, and a `Citation`. Readable
  programmatically via `IGComment.policy_for("username")` and
  `IGComment.fields_requiring_permission("instagram_manage_comments")` → `{"username", "from_"}`.
- `LoginFork` + `SIGNED_LOGIN_FORK` — permissions are meaningless without naming their fork,
  so the type names it.
- `parse_meta_timestamp()` — accepts ISO-8601 `+0000` **and** Unix epoch (int or numeric
  string), normalises to UTC-aware, treats naive input as UTC, and **rejects `bool`** (it is
  an `int` subclass, so `True` would otherwise parse as 1970-01-01T00:00:01Z).
- `IGSID` `NewType` + `IGSID_IS_PORTABLE_IDENTITY = False` — pins that an author column keyed
  on IGSID cannot be joined across tenants, apps, or external identity.
- `COMMENT_LIMITS` — 50/query, top-level-only, not timestamp-filterable, reverse-chronological
  since v3.2, each with its citation. Plus `INCREMENTAL_POLLING_NOTE`: no timestamp filter
  means no since-cursor, so dedupe must be by comment id.
- `UNSUPPORTED_FIELDS` — `comment_type` and `mentioned_instagram_users` are **rejected**, not
  ignored; unknown-but-permitted extras are ignored so Meta adding fields cannot break us.
- `UNCOVERED_SURFACES` — 8 entries as data, each with reason + citation + what would unblock
  it: DMs, the DM human toggle, non-organic/ad comments, age-gated, restricted-user,
  live-video, Mentions-API comments, webhooks.

### `packages/shared/tests/test_ig_shapes.py` — 41 tests, fully offline

The load-bearing one is `test_every_citation_resolves_against_the_corpus`: it walks **every**
`Citation` the contract makes (**31** of them, gathered from field policies, limits,
unsupported fields and uncovered surfaces) and asserts the named file exists, the line is in
range, and
**the quoted text is still on that exact line**.

**Negative control run, 2026-07-29** — the checker was verified to actually catch staleness,
not pass vacuously. All four failure modes detected: off-by-one line, changed wording, deleted
file, line past EOF. A companion test (`test_the_contract_actually_makes_citations`) guards
against the list itself going empty.

> **Suggestion for the lead's question about generalising this repo-wide:** yes, but only
> where a claim is *derived from a file that can change underneath us* — the harvested corpus
> is the clear case. It would be noise on citations to our own source, which the type checker
> and tests already cover.

### `tests/fixtures/synthetic_ig_comments.json` — regenerated

Now a valid instance of `IGComment`, carrying `from`/IGSID, `media`, `hidden`. Preserved
exactly: the 7 comment ids, the reply link (`0004` → `0003`), the empty and whitespace-only
comments, and the POS/NEG/NEU distribution the QUA-21 tests assert. Still marked
`_fixture_kind: SYNTHETIC`; `_provisional_shape` rewritten from "shape is guessed" to
"**shape grounded, data still invented**", and `_shape_version` added.

### Verification

```
HF_HOME=$(mktemp -d) HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --no-sync pytest \
  packages/models/tests/test_ig_shapes.py packages/models/tests/test_ig_comments.py -q
→ 54 passed, 1 deselected
```

Whole models suite (excluding the 8 files blocked by the pre-existing missing `jiwer`):
**96 passed, 7 deselected**. Root suite: **209 passed**, no regressions. `ruff check` and
`ruff format --check` clean. No `uv sync` was run.

### MOVE COMPLETED 2026-07-29 — the contract now lives in `packages/shared`

Per the architect's ruling, authorised by `team-lead` as a scoped exception to file ownership.
Final locations:

| What | Where |
|---|---|
| the contract | `packages/shared/src/qualify_shared/social/ig_shapes.py` |
| contract tests (41) | `packages/shared/tests/test_ig_shapes.py` |
| fixture-instance tests (3) | `packages/models/tests/test_ig_fixture_shape.py` |
| this document | stays here (reasoning, not code) |

**Import path is now `qualify_shared.social.ig_shapes`.** `migrations/postgres/versions/0004_inbox.py`
lines 21 and 119 still cite the old `qualify_models.social.ig_shapes` path — pipeline's file,
routed to them via the lead.

Three things worth knowing about how the move went:

1. **`packages/shared/tests` is in the root `testpaths`, and this was the real prize.** The
   root gate went from **217 → 258 passed**: the 41 contract tests, including the
   citation-verification test, now run in the **default** `uv run pytest`. They never did from
   `packages/models/tests`, which the root config deliberately excludes. This directly
   mitigates the vacuous-gate trap recorded in `NOTES_qua23_filter_decision_rule.md` §1.2.
2. **The move needed a `pythonpath` fix, not a `uv sync`.** `qualify-shared` is declared in
   `packages/models/pyproject.toml` dependencies now, but **`import qualify_shared` fails from
   the shared `.venv`** — the editable install is broken, the documented trap. The root config
   already works around this with an explicit `pythonpath` list; `packages/models`' pytest
   config now does the same via `pythonpath = ["src", "../shared/src"]`. The dependency
   declaration is correct-but-unsynced until someone can safely sync.
3. **The negative control was re-run from the new location**, because relative-path resolution
   is exactly what a move breaks silently. `_repo_root()` still resolves, all 31 citations
   still gather, and all four staleness modes are still detected.

**The architect's binding condition — strictly contract, no DB/HTTP/business logic — is now
enforced by a test**, not just verified once: `test_the_contract_stays_strictly_a_contract`
fails if the module ever imports sqlalchemy, psycopg, httpx, requests, fastapi, `qualify_api`,
`qualify_models` or `qualify_shared.db`. Being in `shared` invites additions, so the condition
needed a standing guard rather than an inspection — same discipline as
`test_session_sanctity.py` in that package. Current imports: stdlib + pydantic only.

### Original blocker (resolved above), kept for the record

The architect ruled the contract's home is **`packages/shared` as
`qualify_shared.social.ig_shapes`**, strictly contract (no DB, no HTTP, no business logic),
and assigned the move to `datasci`. The module already satisfies that constraint: its only
imports are pydantic and the stdlib.

> **SUPERSEDED 2026-07-29 — the move HAS since happened.** Left in place because the record of
> the permission denial is the useful part. Current state, verified on disk by `pipeline`:
> the module is at `packages/shared/src/qualify_shared/social/ig_shapes.py`, its test at
> `packages/shared/tests/test_ig_shapes.py` (40 collected, green), and the three
> fixture-instance tests at `packages/models/tests/test_ig_fixture_shape.py` (3, green) —
> 43 total, nothing lost. `0004_inbox.py` lines 21 and 119 were updated to
> `qualify_shared.social.ig_shapes` by `pipeline`, who owns that file. See §16 of
> `.claude/sprint-state-2026-07-29-sprint2-pipeline.md`.

**The move did not happen** *(at the time of writing)*. `git mv` into `packages/shared/` was
**denied by the permission system**. I did not work around it. State on disk was therefore:

- `ig_shapes.py` was still at `packages/models/src/qualify_models/social/ig_shapes.py`, intact
  and green (203 passed).
- Nothing was half-moved; no `packages/shared/src/qualify_shared/social/` directory existed.
- `migrations/postgres/versions/0004_inbox.py` lines 21 and 119 still cited the
  `qualify_models.social.ig_shapes` path, which was **correct at that moment**.

All three points are superseded by the completed move recorded above.

**Proposed shape of the move, when someone is authorised to do it:**

1. `packages/shared/src/qualify_shared/social/{__init__.py,ig_shapes.py}` — module moves verbatim.
2. Contract tests move to `packages/shared/tests/test_ig_shapes.py`. **Bonus worth having:**
   `packages/shared/tests` *is* in the root `testpaths`, so the contract and its
   citation-verification test would then run in the default `uv run pytest` gate — which
   `packages/models/tests` never does. That directly mitigates the vacuous-gate trap.
3. The three **fixture** tests stay in `packages/models/tests` (the fixture lives there and is
   consumed by the sentiment path), importing from `qualify_shared.social.ig_shapes`.
4. That requires adding `qualify-shared` to `packages/models/pyproject.toml` dependencies.
   Directionally sound and already established — `qualify-api` depends on `qualify-shared`.
   Note the declaration cannot be synced right now (shared workspace, `uv sync` forbidden);
   imports resolve anyway via the workspace editable installs, so the edit is
   correct-but-unsynced until someone syncs.

### Known deviation from plan

The module lives at `qualify_shared.social.ig_shapes` (moved 2026-07-29 per the architect's layout ruling; this section records the reasoning as it stood before that ruling). QUA-20's consumer is `qualify_api`, so
whether `qualify_api` may depend on `qualify_models` — or whether this belongs in
`packages/shared/` — is an **architect layout decision**, deliberately not taken here. The
module has no dependencies beyond pydantic and the stdlib, so moving it is cheap.

---

## 9. What QUA-21 needs to start, now that the contract exists

Written 2026-07-29 at the lead's request as **preparation, not a scope commitment**. QUA-21
("sentiment over own-content comments: from prototype to product") is blocked on QUA-20 for
real payloads. This section records what changed in its favour and what it will still have to
decide, so that day-one is not spent rediscovering it.

### 9.1 What QUA-67 already removed from QUA-21's plate

QUA-21's criterion says *"aquí no se adivinan campos ni se lee el corpus, se importa el tipo"*.
That import now exists:

```python
from qualify_shared.social.ig_shapes import IGComment, parse_comments_page, SHAPE_VERSION
```

So the substitution target is fixed. QUA-21 does **not** need to reopen the corpus.

### 9.2 The three things that will bite on day one

**1. The comments edge may still return nothing.** `instagram_manage_comments` gates the whole
edge, not just `username` (§3). It is Standard Access and auto-approved — it only has to be
*asked for* — but until it is in the consent request and re-consented, a real poll yields zero
comments. **Distinguish "not permitted to observe" from "observed zero" before concluding
anything about the data.** `IGComment.fields_requiring_permission("instagram_manage_comments")`
→ `{"username", "from_"}` is the programmatic form of that check; pipeline is already using it
that way in the intake seam.

**2. Sentiment will run on text that has no author attached.** With today's grants, `from_`
and `username` are both absent. That does not block polarity — `run_sentiment` only needs
`text` and the comment `id` for `source_id` — but it does block anything that wants to group
by author, and it means **provenance will carry `tenant_id`/`connection_id` but no stable
person**. Note also §6: even when the IGSID does arrive it is **not portable**, so an author
column can never be joined outward. Any "top negative commenters" feature is out of reach on
this surface, and that is a permanent property, not a temporary gap.

**3. The fixture marker must be removed *deliberately*, and that is a product decision.**
`_fixture_kind: SYNTHETIC` is asserted by two tests
(`packages/models/tests/test_ig_fixture_shape.py` and `test_ig_comments.py`). They will fail
the moment real payloads land, which is the intended forcing function: **the moment to decide
whether real users' comments belong in a git repo.** Do not "fix" the tests. Escalate the
question. Given that comment text is user-generated content from identifiable accounts, the
likely answer is that real payloads live outside the repo and the committed fixture stays
synthetic — but that is the founder's call, not an engineering one.

### 9.3 What QUA-21 still owes, independent of any of the above

- **Persistence with full provenance**: `source_id` + `detector_version`/`pipeline_version` +
  `model_id`/`revision` + `tenant_id` + `connection_id` (ADR 22c). Today `analyze_comments`
  returns a summary object and persists nothing.
- **Metrics stratified by fragment length.** Worth pre-empting: short comments are where
  Spanish social-media sentiment models degrade most, and a single accuracy number will hide
  it. This is a *measurement* obligation, not a threshold one.
- **The three deliberate restraints must survive**: empty comments skipped and counted; **no
  alert threshold proposed without labelled data**; tests assert vocabulary and provenance,
  never correctness. That last one matters here — the same discipline QUA-23 just applied to
  the filter applies to sentiment, and for the same reason: there is no labelled comment set
  either. `negative_share` is deliberately a bare ratio with no threshold attached.

### 9.4 Honest status

QUA-21 is **not close to done**. The contract removed one blocker (guessed shapes) and QUA-20
will remove another (no real payloads), but the persistence layer, the stratified metrics and
the product decision in 9.2.3 are all untouched. Nothing in this section is committed scope.

---

## 10. Cross-references

- `reference/meta-instagram-platform/DISCREPANCIES.md` — prior art on Meta contradicting
  itself (scope spellings, publishing rate limits). §1 and §4 here extend the same pattern.
- `reference/meta-instagram-platform/LOGIN-FORK-AND-MENTIONS.md` — the fork's cost on the
  mentions surface. §1 here is the messaging-surface counterpart of the same fork.
- `packages/models/src/qualify_models/social/ig_comments.py` — the current provisional
  `InstagramComment`, whose docstring already says it is not grounded in the corpus.
- `packages/models/tests/fixtures/synthetic_ig_comments.json` — `_fixture_kind: SYNTHETIC`,
  `_provisional_shape` marker to be replaced by a contract-derived shape.
