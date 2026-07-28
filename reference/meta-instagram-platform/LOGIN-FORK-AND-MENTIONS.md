# The login fork, and what it costs you on the mentions surface

Author: `pipeline-r`, 2026-07-24. Answers two questions at once, because the corpus shows they
are the same question: the `datasci` / `datasci-2` dispute about whether `mentioned_media` and
`/tags` are documented, and the login-fork ruling `architect-r` is holding.

All claims cite `instagram-platform/instagram-graph-api/reference/ig-user/*.md` in this corpus.

## The fork is real and one-way

`instagram-platform/app-review.md`:

> **"Your app can either use Facebook Login or Instagram Login but not both."**

The two paths have different permission vocabularies:

| Facebook Login | Instagram Login |
|---|---|
| `instagram_basic` | `instagram_business_basic` |
| `instagram_content_publishing` | `instagram_business_content_publish`/`…publishing` (see [DISCREPANCIES.md](DISCREPANCIES.md) §1) |
| `instagram_manage_comments` | `instagram_business_manage_comments` |
| `instagram_manage_messages` | `instagram_business_manage_messages` |
| `pages_read_engagement`, `pages_show_list`, `ads_management`, … | *(no equivalent)* |

## The decisive asymmetry: the mention/tag surface is Facebook-Login-only

Four dedicated reference pages exist — this settles the "undocumented" claim, they are all here:

| Page | Bytes | Shape |
|---|---|---|
| `ig-user/mentioned_media.md` | 5 785 | lookup by known media-id |
| `ig-user/mentioned_comment.md` | 6 504 | lookup by known comment-id |
| `ig-user/mentions.md` | 4 812 | — |
| `ig-user/tags.md` | 3 779 | **listing** endpoint |

**Every one of them lists its permissions as `instagram_basic` + `instagram_manage_comments` +
`pages_read_engagement`** — the Facebook Login vocabulary. Grepping all four for
`instagram_business_*` returns **zero occurrences.**

**Consequence: choosing Instagram Login appears to forfeit the entire earned-media mention/tag
surface.** That is not a minor trade — it is the surface Qualify's original listening thesis is
built on. Conversely, Instagram Login is the simpler onboarding flow (no Facebook Page linkage).
This must be an explicit, recorded decision, not a side effect of whichever guide gets
implemented first.

Caveat, stated honestly: absence of the Instagram-Login vocabulary on these pages is strong
evidence but not an explicit statement that the endpoints are unavailable under Instagram Login.
Meta does not say "not available with Instagram Login" in so many words. Confirm against the
live Graph API before treating the forfeiture as final.

## Who was right about `mentioned_media`

**Both, partly.**

`datasci` is right that the pages exist and that **vision/transcription can run on this content**:
`mentioned_media.md` returns `media_url` and `media_type` with values `IMAGE`, `VIDEO`,
`CAROUSEL_ALBUM`. Real media, fetchable, so the Fase 1 cascade does transfer.

`datasci-2` is right that **discovery is webhook-driven, not enumerable** — for `mentioned_media`.
The read syntax is:

```http
GET /{ig-user-id}?fields=mentioned_media.media_id({media-id})
```

You must already hold the `{media-id}`, and the doc states it *"is included in the Webhook
notification payload."* There is no "list my mentions" call. So a poll-based ingestion design
does not work for mentions; a webhook subscription is mandatory.

**But `datasci-2` is wrong that mentions are "solely a webhook field, comment-shaped".**
`/tags` **is** a true listing endpoint:

> `GET /<IG_USER_ID>/tags` — "Returns a **list** of IG Media objects in which an IG User has been
> tagged by another Instagram user."

So tagged media *is* enumerable and pollable. The mention surface splits: **`/tags` is pull,
`mentioned_media` is push.** Any ingestion design needs both paths, not one.

## Documented limitations that constrain the design

From `mentioned_media.md`:
- **"Mentions on Stories are not supported."**
- **"Commenting on photos in which you were tagged is not supported."**
- **"Webhooks will not be sent if the Media upon which the comment or @mention appears was
  created by an account that is set to private."**

From `tags.md`:
- **"Private IG Media objects will not be returned."**

The private-account exclusions apply to both paths and are silent — no error, the content simply
never arrives. Any coverage or recall metric built on this surface must account for it, or it
will overstate reach.
