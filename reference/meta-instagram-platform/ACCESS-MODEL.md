# The access model, settled against the corpus

Author: `pipeline-r`, 2026-07-24. Answers the sprint's central question — whether customer zero
can publish and read DMs without Meta's 2–4 month App Review / Business Verification clock.
Every claim cites a file in this corpus.

## Verdict: yes, with a precise and testable boundary

**All permissions are available at Standard Access. No App Review. The constraint is not *which*
permission — it is *who* is using the app.**

`docs/graph-api/overview/access-levels.md`, the authoritative Graph API page:

> "Business, Consumer, and Gaming apps are **automatically approved for Standard Access for all
> permissions and features** available to their app type."

> "Permissions with Standard Access can only be requested from app users who have a **role** on
> the requesting app."

Corroborated by `instagram-platform/app-review.md`:

| Development scenario | Access level | App Review |
|---|---|---|
| My app is only for a business I own or manage | Standard | **Not required** |
| I am a Tech Provider and my app serves multiple businesses | Advanced | **Required** |

and `instagram-platform/overview.md:37`: *"If your app only serves your Instagram professional
account or an account you manage, Standard Access is all your app needs."*
`overview.md:107`: Business Verification is required **only** for Advanced Access.

## This retires an earlier hedge

`instagram-platform/overview.md:43` warns that *"because of the limited scope of Standard Access,
some features might not work properly until your app has been granted Advanced Access."* Read
alone, that suggests publishing might silently degrade at Standard Access.

`access-levels.md` resolves it: all permissions **are** auto-approved at Standard Access, and the
"limited scope" is the *audience* limit (role-holders only), not a per-feature capability limit.
The vague warning describes what happens when a non-role-holder uses the app — not a restriction
on `instagram_business_content_publish` or `instagram_business_manage_messages` themselves.

**Consequence:** the founder, as admin of the app *and* administrator of the store's professional
account, is a role-holder. Publishing reels/stories and reading DMs are available to him on day
one with no review, no Business Verification, and therefore no legal-entity dependency in the
critical path.

## The boundary to instrument

Roles are **admin, developer, or tester** (`docs/facebook-login/changelog.md:124`).

The trigger for needing Advanced Access is a single observable event: **the first user without a
role on the app attempts to connect.** That is customer one, not customer zero. It should be a
detectable product event, not a judgement call.

Also from the same line, relevant to any polling design: apps in development mode are
**rate-limited to 200 calls/hour per page-app pair**.

## One claim I could NOT verify — do not propagate it

`.claude/sprint-state-2026-07-23-ig-crm.md` states *"Standard Access covers ~25 test users."*
**No such cap appears anywhere in this corpus.** The number may come from Meta's *test user*
feature (`documentation/facebook-login/guides/test.md`), which is a different mechanism from app
roles — test users are synthetic accounts for automated testing, not real accounts holding roles.

The role-holder limit, if any, is **unverified**. Nothing in the harvested docs states a numeric
cap on app roles. Treat the 25 figure as unsourced until someone confirms it against the App
Dashboard.

## TikTok, for contrast — unchanged and unfavourable

Nothing here applies to TikTok. Per `docs/fase0-zernio-mercado.md` §1.1 an unaudited client
publishes `SELF_ONLY` (private), enforced server-side via `creator_info`. That blocks the founder
**on his own account**, because a private promotional post is worthless. The Meta path is open to
customer zero; the TikTok path is gated by audit regardless of who owns the account. That
asymmetry is real and should drive sequencing.
