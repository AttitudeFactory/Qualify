"""Typed field-shape contract for Instagram **comments** (QUA-67).

This is not documentation. It is the type that QUA-20 (the `threads`/`messages`
intake) and QUA-21 (sentiment over owned-media comments) **import** instead of
re-deriving field shapes from the corpus or guessing them.

Fixed **offline** against the harvested primary corpus in
`reference/meta-instagram-platform/`. No network, no connected account, no API
call was made to produce it. Every field, limit and exclusion below carries a
`Citation` naming the corpus file, line and quoted text it came from, and
`tests/test_ig_shapes.py` **verifies that every citation still resolves** — so a
re-harvest in which Meta changed the docs fails loudly instead of leaving this
contract quietly lying.

SCOPE: comments only.
    The DM/conversations half of the original ticket was cut deliberately. Under
    the signed login fork (Facebook Login for Business, ADR 25) the messaging
    surface is not reachable for customer zero — an app with Standard Access can
    only interact with people who hold a role on the app, and a real customer
    sending a DM by definition does not. Fixing a type for an API we cannot call
    would be a contract in name only. See `UNCOVERED_SURFACES` for the machine-
    readable version of that exclusion, and `NOTES_ig_shapes_contract.md` §1 for
    the full reasoning.

NOT A TABLE SCHEMA.
    Nothing here names a table, column or CRM entity. This contract hands QUA-20
    the *shapes*; how they map onto columns is the architect's call.

WHAT "NULLABLE" MEANS HERE.
    Almost every field is `| None`, but not because Meta returns nulls. The Graph
    API returns **only the fields you ask for in `fields=`**, so absence is the
    default state and presence is the thing that must be earned — by requesting
    the field, holding the permission, and owning the object. `FieldPolicy`
    records which of those three gates applies, per field, in the type itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Final, NewType

from pydantic import BaseModel, ConfigDict, model_validator

# Bumped when a field's name, type, nullability or policy changes in a way that
# makes a consumer's assumptions wrong. Consumers should record it alongside the
# data they parsed, the same way pipeline stages record `detector_version`.
SHAPE_VERSION: Final = "ig-comment-shapes-1.0.0"

# Corpus paths are recorded relative to this directory so the contract stays
# independent of where the repo is checked out. The test resolves it.
CORPUS_ROOT: Final = "reference/meta-instagram-platform"

_IG_COMMENT: Final = "instagram-platform/instagram-graph-api/reference/ig-comment.md"
_IG_MEDIA_COMMENTS: Final = "instagram-platform/instagram-graph-api/reference/ig-media/comments.md"
_IG_COMMENT_REPLIES: Final = (
    "instagram-platform/instagram-graph-api/reference/ig-comment/replies.md"
)
_APP_REVIEW: Final = "instagram-platform/app-review.md"
# NOTE: the `documentation/` subtree is HTML-entity-escaped (`&lt;br&gt;`, `&#123;`).
# Read it, never parse it. It is used here only for pages that exist nowhere else.
_MSG_OVERVIEW: Final = "documentation/business-messaging/instagram-messaging/overview.md"
_MSG_GET_STARTED: Final = "documentation/business-messaging/instagram-messaging/get-started.md"
# QUA-49: the formal per-field webhook reference (payload shape) and the older
# getting-started guide (worked examples, incl. what `entry[].id` identifies).
# Neither lives under `instagram-platform/`, unlike the endpoints above.
_WEBHOOKS_INSTAGRAM_REFERENCE: Final = "docs/graph-api/webhooks/reference/instagram.md"
_WEBHOOKS_GETTING_STARTED: Final = (
    "docs/graph-api/webhooks/getting-started/webhooks-for-instagram.md"
)


@dataclass(frozen=True)
class Citation:
    """A pointer into the harvested corpus, verified by the test suite.

    `quote` must be a substring of `path`'s line number `line`. That exactness is
    the point: it makes the contract falsifiable against its own evidence.
    """

    path: str
    line: int
    quote: str


class LoginFork(StrEnum):
    """Meta's two mutually exclusive login paths.

    `app-review.md:22` — "Your app can either use Facebook Login or Instagram
    Login but not both." The two forks use different permission vocabularies for
    the same underlying fields, so any permission claim must name its fork.
    Qualify is on `FACEBOOK` (ADR 25).
    """

    FACEBOOK = "facebook_login_for_business"
    INSTAGRAM = "business_login_for_instagram"


SIGNED_LOGIN_FORK: Final = LoginFork.FACEBOOK
"""The fork Qualify actually uses. Permission gates below resolve against this."""


class Presence(StrEnum):
    """Why a field might be absent from a real payload."""

    ALWAYS = "always"
    """Returned unconditionally. In practice only `id`."""

    IF_REQUESTED = "if_requested"
    """Returned only when named in `fields=`. The default state of most fields."""

    REQUIRES_PERMISSION = "requires_permission"
    """Additionally gated on a granted OAuth permission. See `FieldPolicy.permission`."""

    IF_OWNED_BY_APP_USER = "if_owned_by_app_user"
    """Returned only when the app user created the object being read."""

    EXPANSION_ONLY = "expansion_only"
    """An edge, absent unless explicitly field-expanded. Never arrives by default."""


@dataclass(frozen=True)
class FieldPolicy:
    """Presence rules for one field, attached to the field's own type.

    Carried in `Annotated[...]` metadata rather than in a docstring or comment so
    a consumer can *read it programmatically* — `IGComment.policy_for("username")`
    — instead of a human having to remember a caveat.
    """

    presence: Presence
    citation: Citation
    permission: str | None = None
    """OAuth permission required, spelled for `SIGNED_LOGIN_FORK`. None if ungated."""

    mutually_exclusive_with: str | None = None
    note: str | None = None


# --------------------------------------------------------------------------
# Person identity
# --------------------------------------------------------------------------

IGSID = NewType("IGSID", str)
"""An Instagram-scoped ID: the identifier of a person **within one app+account pair**.

`ig-comment.md:71` documents `from.id` as an IGSID. This is deliberately a
distinct type from `str` because the difference is expensive to rediscover late:
an IGSID is **not a portable Instagram user identity**. The same human messaging
two different businesses presents two different IGSIDs, and the same IGSID means
"the same human" only within a single app+account scope.

Consequence for anyone modelling a person: an author column keyed on IGSID
**cannot be joined** across tenants, across apps, or against any external
identity source. It is a per-connection alias, not an identity key. Deciding
that by accident — by typing the column `str` and assuming it globally unique —
is precisely the mistake this type exists to block.
"""

IGSID_IS_PORTABLE_IDENTITY: Final = False
"""Machine-readable form of the paragraph above, so a test can assert on it."""

IGSID_CITATION: Final = Citation(
    path=_IG_COMMENT,
    line=71,
    quote="Instagram-scoped ID (IGSID)",
)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

TIMESTAMP_CITATION_ISO: Final = Citation(
    path=_IG_COMMENT,
    line=80,
    quote="ISO 8601 formatted timestamp indicating when IG Comment was created.",
)


def parse_meta_timestamp(value: str | int | float) -> datetime:
    """Parse a Meta timestamp into a UTC-aware `datetime`, defensively.

    Accepts **both** documented forms, because Meta's own corpus contradicts
    itself on which one it emits:

    - ISO 8601 with a `+0000` offset (`ig-comment.md:80`, and the worked example
      at `ig-comment.md:118`), which is what the comment surface uses; and
    - a Unix epoch integer, which the conversations documentation declares for
      `updated_time`/`created_time` even though its own worked example returns
      ISO.

    Comments are consistently ISO today, so the epoch branch is defensive rather
    than currently-exercised. It is kept because the contradiction is in Meta's
    documentation, not in our reading of it: a parser that accepts only the form
    we happen to have seen would fail silently the day the other one arrives.

    Naive ISO inputs (no offset) are treated as UTC — Meta timestamps are always
    UTC-referenced, and guessing local time would be worse than assuming it.
    """
    if isinstance(value, bool):
        # bool is an int subclass; an accidental True would parse as 1970-01-01.
        raise TypeError("timestamp must be a string or a number, not a bool")

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)

    text = value.strip()
    if not text:
        raise ValueError("timestamp is empty")

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Not ISO — the only other documented form is an epoch, possibly as a
        # numeric string. Anything else is genuinely unparseable and should raise.
        try:
            return datetime.fromtimestamp(float(text), tz=UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError(f"unrecognized Meta timestamp: {value!r}") from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# --------------------------------------------------------------------------
# Collection limits — constants of the contract, not loose numbers in a poller
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CommentCollectionLimits:
    """Hard limits of the `GET /{ig-media-id}/comments` edge.

    These belong to the contract rather than to whoever writes the poll loop,
    because every one of them silently changes what "all the comments" means.
    """

    max_per_query: int = 50
    returns_top_level_only: bool = True
    filterable_by_timestamp: bool = False
    reverse_chronological_since_api_version: str = "3.2"

    citations: tuple[Citation, ...] = (
        Citation(
            path=_IG_MEDIA_COMMENTS,
            line=65,
            quote="Returns a maximum of 50 comments per query.",
        ),
        Citation(
            path=_IG_MEDIA_COMMENTS,
            line=64,
            quote="Returns only top-level comments.",
        ),
        Citation(
            path=_IG_MEDIA_COMMENTS,
            line=66,
            quote="Comments cannot be filtered by timestamp.",
        ),
        Citation(
            path=_IG_MEDIA_COMMENTS,
            line=63,
            quote="results returned in chronological order",
        ),
    )


COMMENT_LIMITS: Final = CommentCollectionLimits()

INCREMENTAL_POLLING_NOTE: Final = (
    "Comments cannot be filtered by timestamp, so an incremental poll cannot use a "
    "since-cursor. De-duplication must be by comment id. Combined with the 50-per-query "
    "cap and reverse-chronological ordering, a media object with more than 50 comments "
    "requires cursor pagination to be read completely — and a comment added mid-pagination "
    "shifts the window."
)


# --------------------------------------------------------------------------
# Fields Meta explicitly does not support on this node
# --------------------------------------------------------------------------

UNSUPPORTED_FIELDS: Final[dict[str, Citation]] = {
    "comment_type": Citation(path=_IG_COMMENT, line=15, quote="`comment_type`"),
    "mentioned_instagram_users": Citation(
        path=_IG_COMMENT, line=16, quote="`mentioned_instagram_users`"
    ),
}
"""Named as *not supported* at `ig-comment.md:13-16`.

Rejected rather than ignored: both are names a schema author would plausibly
reach for (`comment_type` especially), and silently dropping them would let a
consumer believe it had asked for something it will never receive.
"""


# --------------------------------------------------------------------------
# The shapes
# --------------------------------------------------------------------------


class IGCommentFrom(BaseModel):
    """The `from` object: who wrote the comment.

    Not readable for comments discovered through the Mentions API unless the
    requester owns the comment (`ig-comment.md:39`).
    """

    model_config = ConfigDict(extra="ignore")

    id: IGSID
    username: str | None = None


class IGCommentMedia(BaseModel):
    """The `media` object: which post the comment was made on."""

    model_config = ConfigDict(extra="ignore")

    id: str
    media_product_type: str | None = None


class IGComment(BaseModel):
    """One Instagram comment, as returned by the Graph API.

    Extra keys are **ignored, not rejected** — real payloads carry more than any
    one consumer needs, and rejecting unknown keys would make this contract brittle
    against Meta adding fields. The two fields Meta documents as *unsupported* are
    the exception and are rejected explicitly.
    """

    model_config = ConfigDict(extra="ignore")

    id: Annotated[
        str,
        FieldPolicy(
            presence=Presence.ALWAYS,
            citation=Citation(path=_IG_COMMENT, line=73, quote="IG Comment ID."),
        ),
    ]

    text: Annotated[
        str | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(path=_IG_COMMENT, line=79, quote="IG Comment text."),
        ),
    ] = None

    timestamp: Annotated[
        datetime | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=TIMESTAMP_CITATION_ISO,
            note="ISO 8601 with a +0000 offset. Normalized to UTC-aware by parse_meta_timestamp.",
        ),
    ] = None

    from_: Annotated[
        IGCommentFrom | None,
        FieldPolicy(
            presence=Presence.REQUIRES_PERMISSION,
            permission="instagram_manage_comments",
            citation=IGSID_CITATION,
            note=(
                "Aliased to `from` on the wire; `from` is a Python keyword. Not readable "
                "for Mentions-API-discovered comments unless the requester owns them."
            ),
        ),
    ] = None

    username: Annotated[
        str | None,
        FieldPolicy(
            presence=Presence.REQUIRES_PERMISSION,
            permission="instagram_manage_comments",
            mutually_exclusive_with="user",
            citation=Citation(
                path=_IG_COMMENT,
                line=82,
                quote="will be required to access the `username` field",
            ),
            note=(
                "Gated since 2024-08-27. Under the Instagram Login fork the equivalent "
                "permission is instagram_business_manage_comments."
            ),
        ),
    ] = None

    user: Annotated[
        str | None,
        FieldPolicy(
            presence=Presence.IF_OWNED_BY_APP_USER,
            mutually_exclusive_with="username",
            citation=Citation(
                path=_IG_COMMENT,
                line=81,
                quote="Only returned if the app user created the IG Comment",
            ),
            note=(
                "Returned INSTEAD OF username when the app user wrote the comment. These "
                "are two spellings of the author under different conditions, not two "
                "columns that are both populated."
            ),
        ),
    ] = None

    parent_id: Annotated[
        str | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(
                path=_IG_COMMENT,
                line=77,
                quote="ID of the parent IG Comment",
            ),
            note="Present when this comment is a reply to another comment.",
        ),
    ] = None

    hidden: Annotated[
        bool | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(
                path=_IG_COMMENT, line=72, quote="Indicates if comment has been hidden"
            ),
        ),
    ] = None

    like_count: Annotated[
        int | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(
                path=_IG_COMMENT, line=74, quote="Number of likes on the IG Comment."
            ),
        ),
    ] = None

    media: Annotated[
        IGCommentMedia | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(
                path=_IG_COMMENT, line=76, quote="Published surface of the [IG Media]"
            ),
        ),
    ] = None

    replies: Annotated[
        IGCommentRepliesEdge | None,
        FieldPolicy(
            presence=Presence.EXPANSION_ONLY,
            citation=Citation(
                path=_IG_MEDIA_COMMENTS,
                line=64,
                quote="unless you use field expansion to request the `replies` field",
            ),
            note=(
                "The edge never arrives by default. Absence therefore means 'not asked "
                "for', NOT 'this comment has no replies' — the two are indistinguishable "
                "in a payload and must not be conflated by a consumer.\n\n"
                "[CORRECTED 2026-09-05, against a REAL live comment with a reply, via "
                "manual QUA-22 smoke testing] Was typed `list[IGComment] | None` — WRONG. "
                "Like every other Graph API edge in this contract (`IGCommentsPage`), "
                '`replies` arrives as `{"data": [...], "paging": {...}}`, never a bare '
                "list. The bare-list guess had never been exercised against a comment "
                "that actually carries a reply until now; it failed with a pydantic "
                "`list_type` error the first time it was (a real 502 on `POST "
                "/api/inbox/sync`, reproduced and root-caused without ever printing "
                "comment text — see the PR/commit this fix ships in)."
            ),
        ),
    ] = None

    legacy_instagram_comment_id: Annotated[
        str | None,
        FieldPolicy(
            presence=Presence.IF_REQUESTED,
            citation=Citation(
                path=_IG_COMMENT,
                line=75,
                quote="The ID for Instagram comment that was created for Marketing API",
            ),
        ),
    ] = None

    @model_validator(mode="before")
    @classmethod
    def _reject_unsupported_and_alias_from(cls, data: Any) -> Any:
        """Reject Meta's documented-unsupported fields; map wire `from` to `from_`."""
        if not isinstance(data, dict):
            return data
        present = [name for name in UNSUPPORTED_FIELDS if name in data]
        if present:
            joined = ", ".join(sorted(present))
            raise ValueError(
                f"field(s) not supported on the IG Comment node: {joined}. "
                f"See {_IG_COMMENT} lines 13-16."
            )
        if "from" in data and "from_" not in data:
            data = {**data, "from_": data["from"]}
            data.pop("from", None)
        return data

    @model_validator(mode="after")
    def _enforce_author_field_exclusivity(self) -> IGComment:
        """`user` and `username` are alternatives, never both.

        `ig-comment.md:81` — `user` is returned *only* if the app user created the
        comment, "otherwise `username` will be returned instead". Both absent is
        legal (neither requested, or the permission is missing); both present is
        not a payload Meta documents, and treating it as normal would let a
        consumer build an author column that is sometimes one and sometimes the
        other without noticing.
        """
        if self.user is not None and self.username is not None:
            raise ValueError(
                "`user` and `username` are mutually exclusive on an IG Comment: "
                "`user` is returned only when the app user authored the comment, "
                "otherwise `username` is returned instead"
            )
        return self

    @classmethod
    def policy_for(cls, field_name: str) -> FieldPolicy:
        """Read a field's presence policy off the type itself.

        Exists so consumers can branch on conditionality programmatically rather
        than by remembering prose.
        """
        try:
            info = cls.model_fields[field_name]
        except KeyError as exc:
            raise KeyError(f"{cls.__name__} has no field {field_name!r}") from exc
        for meta in info.metadata:
            if isinstance(meta, FieldPolicy):
                return meta
        raise KeyError(f"field {field_name!r} carries no FieldPolicy")

    @classmethod
    def fields_requiring_permission(cls, permission: str) -> frozenset[str]:
        """Which fields disappear if `permission` is not granted."""
        return frozenset(
            name
            for name in cls.model_fields
            if _safe_policy(cls, name) is not None
            and _safe_policy(cls, name).permission == permission  # type: ignore[union-attr]
        )


class IGCommentRepliesEdge(BaseModel):
    """The `replies` edge on one `IGComment`, requested via field expansion
    (`?fields=comments{...,replies}`): `{"data": [...], "paging": {...}}` — same
    shape every other Graph API edge in this contract already has (`IGCommentsPage`
    below). NOT a bare `list[IGComment]` — that was this field's original, wrong
    type; see `IGComment.replies`'s own field note for the correction.
    """

    model_config = ConfigDict(extra="ignore")

    data: list[IGComment]
    paging: dict[str, Any] | None = None


def _safe_policy(model: type[IGComment], name: str) -> FieldPolicy | None:
    try:
        return model.policy_for(name)
    except KeyError:
        return None


IGComment.model_rebuild()


class IGCommentsPage(BaseModel):
    """One page of the `GET /{ig-media-id}/comments` edge: `{"data": [...]}`.

    Cursor pagination lives in `paging`, which is left loosely typed on purpose —
    the corpus's comment pages do not document the cursor envelope, and inventing
    a shape for it would be exactly the guessing this contract exists to stop.
    """

    model_config = ConfigDict(extra="ignore")

    data: list[IGComment]
    paging: dict[str, Any] | None = None


def parse_comments_page(payload: dict[str, Any]) -> IGCommentsPage:
    """Parse a Graph-API `{"data": [...]}` comments envelope into typed comments."""
    if not isinstance(payload.get("data"), list):
        raise ValueError("comments payload 'data' must be a list")
    return IGCommentsPage.model_validate(payload)


# --------------------------------------------------------------------------
# What this contract does NOT cover
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UncoveredSurface:
    """A surface deliberately outside this contract, with why and what unblocks it.

    Exposed as data rather than prose so QUA-20/QUA-21 can assert against it —
    "is this surface promised?" should be a lookup, not a reading-comprehension
    exercise over a docstring.
    """

    name: str
    reason: str
    citation: Citation
    unblocked_by: str | None = None


UNCOVERED_SURFACES: Final[tuple[UncoveredSurface, ...]] = (
    UncoveredSurface(
        name="direct_messages",
        reason=(
            "Under the signed Facebook Login fork, an app with Standard Access can only "
            "interact with people holding a role on the app. A real customer sending a DM "
            "holds no such role, so the messaging surface is unreachable for customer "
            "zero. Fixing its shapes now would type an API we cannot call."
        ),
        citation=Citation(
            path=_MSG_OVERVIEW,
            line=122,
            quote="Apps with Standard Access can only interact with people who have a role",
        ),
        unblocked_by="Business Verification + Advanced Access (same gate as the transport)",
    ),
    UncoveredSurface(
        name="direct_messages_human_toggle",
        reason=(
            "Independently of any OAuth scope, the account owner must manually enable "
            "Instagram Settings > Messages and story replies > Message controls > "
            "Connected Tools > Allow Access to Messages. This is a human action inside "
            "the Instagram app, so a DM poll returning empty is AMBIGUOUS between 'no "
            "messages' and 'the owner never enabled access'. Any inbox UI must be able "
            "to distinguish the two rather than rendering silence as zero."
        ),
        citation=Citation(
            path=_MSG_GET_STARTED,
            line=129,
            quote="Connected Tools",
        ),
        unblocked_by="Account-owner action; cannot be granted programmatically",
    ),
    UncoveredSurface(
        name="non_organic_comments",
        reason=(
            "Comments on ads are a different type and are not supported on this edge. "
            "They require the Marketing API via the ad's effective_instagram_media_id."
        ),
        citation=Citation(
            path=_IG_MEDIA_COMMENTS,
            line=9,
            quote="are of a different type and are not supported",
        ),
        unblocked_by="Marketing API access (deferred; out of ADR 21's organic-first scope)",
    ),
    UncoveredSurface(
        name="age_gated_media_comments",
        reason="Comments on age-gated media are not returned at all.",
        citation=Citation(
            path=_IG_COMMENT,
            line=40,
            quote="Comments on age-gated media are not returned.",
        ),
    ),
    UncoveredSurface(
        name="restricted_user_comments",
        reason=(
            "Comments by users the app user has restricted are withheld until the user is "
            "unrestricted and the comments approved. A comment count from this edge is "
            "therefore not the count the account owner sees in the app."
        ),
        citation=Citation(
            path=_IG_COMMENT,
            line=41,
            quote="restricted by the app user will not be returned",
        ),
    ),
    UncoveredSurface(
        name="live_video_comments",
        reason=(
            "Readable only while the broadcast is live, so they are unreachable by any "
            "poll that runs after the fact. A batch pipeline cannot capture them."
        ),
        citation=Citation(
            path=_IG_COMMENT,
            line=42,
            quote="can only be read while the IG Media upon which the comment was created",
        ),
    ),
    UncoveredSurface(
        name="mentions_api_comments",
        reason=(
            "Comments discovered via the Mentions API are not readable unless the "
            "requester owns them; the Mentioned Comment node must be used instead."
        ),
        citation=Citation(
            path=_IG_COMMENT,
            line=39,
            quote="unless the request is made by the comment owner",
        ),
    ),
    UncoveredSurface(
        name="webhook_payloads",
        reason=(
            "Webhook notifications carry their own shape, distinct from the REST node, "
            "and are unreachable for customer zero (Live mode + Advanced Access + "
            "Business Verification)."
        ),
        citation=Citation(
            path=_MSG_OVERVIEW,
            line=122,
            quote="Apps with Standard Access can only interact with people who have a role",
        ),
        unblocked_by="Business Verification + Advanced Access",
    ),
)


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------

COMMENTS_EDGE_PERMISSIONS: Final[tuple[str, ...]] = (
    "instagram_basic",
    "instagram_manage_comments",
)
"""Required to read `GET /{ig-media-id}/comments` **at all**, on the Facebook fork.

`ig-media/comments.md:70-73`. This is the whole edge, not merely the `username`
field: without `instagram_manage_comments` the poll returns nothing, so a
"comments work, usernames don't" reading of the permission is too optimistic.

Spelled for `SIGNED_LOGIN_FORK`. The Instagram Login fork spells the same two
`instagram_business_basic` / `instagram_business_manage_comments`, and the forks
cannot be mixed.
"""

COMMENTS_EDGE_PERMISSIONS_CITATION: Final = Citation(
    path=_IG_MEDIA_COMMENTS,
    line=73,
    quote="instagram_manage_comments",
)

BUSINESS_MANAGER_ROLE_EXTRA_PERMISSIONS: Final[tuple[str, ...]] = (
    "ads_management",
    "ads_read",
)
"""One of these is *additionally* required when the token's Page role was granted
via Business Manager (`ig-media/comments.md:75-78`). Easy to miss, because it
depends on how the human was granted access rather than on anything in the code.
"""

LOGIN_FORK_CITATION: Final = Citation(
    path=_APP_REVIEW,
    line=22,
    quote="Your app can either use Facebook Login or Instagram Login but not both.",
)

REPLY_CREATION_CITATION: Final = Citation(
    path=_IG_COMMENT_REPLIES,
    line=25,
    quote="You can only reply to top-level comments",
)
"""Read-adjacent and out of scope, but worth pinning: a reply to a reply is
silently reparented to the top-level comment. Threading is therefore at most one
level deep, whatever the UI offers.
"""

# --------------------------------------------------------------------------
# Mentions webhook envelope (QUA-49)
# --------------------------------------------------------------------------
#
# SCOPE: the `mentions` field's notification envelope only — NOT the `mentioned_media`/
# `mentioned_comment` read-endpoint response shapes. Those are a separate, still-uncovered
# contract (see `UNCOVERED_SURFACES["webhook_payloads"]` above, which this section narrows
# but does not close: the notification can now be parsed, delivery is still unverified for
# customer zero). Grounded against the formal per-field reference
# (`docs/graph-api/webhooks/reference/instagram.md`), not the getting-started tutorial's
# worked example alone — the tutorial is cited only for what `entry[].id` identifies, which
# the formal reference does not state.

MENTIONS_FIELD_CITATION: Final = Citation(
    path=_WEBHOOKS_INSTAGRAM_REFERENCE,
    line=139,
    quote="@mentions you in a comment or caption on a media object",
)

MENTIONS_MEDIA_ID_CITATION: Final = Citation(
    path=_WEBHOOKS_INSTAGRAM_REFERENCE,
    line=145,
    quote="ID of media containing comment with mention.",
)

MENTIONS_COMMENT_ID_CITATION: Final = Citation(
    path=_WEBHOOKS_INSTAGRAM_REFERENCE,
    line=146,
    quote="ID of comment with mention.",
)

MENTIONS_ENTRY_ID_CITATION: Final = Citation(
    path=_WEBHOOKS_GETTING_STARTED,
    line=141,
    quote="ID of your app user's Instagram professional account",
)
"""`entry[].id` is the MENTIONED account's own IG user id — i.e. our
`external_account_id` — never the id of whoever wrote the mention. The formal
reference (`MENTIONS_FIELD_CITATION`) does not state this; only the
getting-started guide's annotated sample payload does.
"""


class MentionsChangeValue(BaseModel):
    """`entry[].changes[].value` for a `"field": "mentions"` change.

    `media_id` is documented as always present; `comment_id` is present only for a
    mention inside a comment, absent for one in a caption
    (`MENTIONS_MEDIA_ID_CITATION`/`MENTIONS_COMMENT_ID_CITATION`). Both are `str`
    even though Meta calls them numeric strings elsewhere, matching how `IGComment.id`
    is already typed in this module.
    """

    model_config = ConfigDict(extra="ignore")

    media_id: str
    comment_id: str | None = None


class MentionsWebhookEntry(BaseModel):
    """One `entry[]` item: one mentioned account's batch of changes for this delivery.

    `changes` is deliberately left as raw dicts, not a list of a single `changes`
    model: `webhooks-for-instagram.md`'s own Limitations section documents that a
    subscribed app "receives notifications for all fields the app is subscribed
    to", so a real batch can legitimately carry non-`mentions` changes once this
    app subscribes to more fields. Typing `changes` narrowly would make parsing an
    unrelated field's change a hard failure instead of a no-op skip.

    Meta's real envelope also carries `entry[].time` (when the notification was
    sent). Deliberately NOT modeled: nothing downstream consumes it, and
    declaring it as a typed field would only give a payload we don't care about
    ANOTHER way to fail validation. `model_config`'s `extra="ignore"` lets it
    arrive and be silently dropped instead.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    changes: list[dict[str, Any]] = []


class MentionsWebhookNotification(BaseModel):
    """The full `POST` body Meta sends: `{"object": "instagram", "entry": [...]}`."""

    model_config = ConfigDict(extra="ignore")

    object: str
    entry: list[MentionsWebhookEntry]


@dataclass(frozen=True)
class MentionEvent:
    """One resolved `mentions` change, flattened so a caller never re-threads the
    parent `entry` to get at `ig_user_id`. This is the unit `qualify_api.http.
    mentions_routes` (in `qualify_api`, not here — see
    `test_the_contract_stays_strictly_a_contract`) consumes; it is deliberately
    NOT a CRM entity or a persistence row.
    """

    ig_user_id: str
    media_id: str
    comment_id: str | None


def parse_mentions_notification(payload: dict[str, Any]) -> tuple[MentionEvent, ...]:
    """Parse a webhook `POST` body into the `mentions`-field events it carries.

    Silently skips (not an error): an `entry` with no `changes`, and any
    `changes[]` item whose `field` is not `"mentions"` (see
    `MentionsWebhookEntry`'s docstring for why that is expected, not a bug).

    Raises `ValueError`/`pydantic.ValidationError` for the envelope itself, or for
    a `"mentions"` change whose `value` does not match `MentionsChangeValue` — that
    IS a contract violation on the one field this parser claims to understand.
    """
    notification = MentionsWebhookNotification.model_validate(payload)
    events: list[MentionEvent] = []
    for entry in notification.entry:
        for raw_change in entry.changes:
            if raw_change.get("field") != "mentions":
                continue
            value = MentionsChangeValue.model_validate(raw_change.get("value") or {})
            events.append(
                MentionEvent(
                    ig_user_id=entry.id,
                    media_id=value.media_id,
                    comment_id=value.comment_id,
                )
            )
    return tuple(events)


# --------------------------------------------------------------------------
# mentioned_media / mentioned_comment (QUA-49) — the read nodes the `mentions`
# webhook exists to unlock: the only sanctioned way to read the caption/text of
# content the connected account does not own (`ig-comment.md:39` — a comment
# discovered via the Mentions API cannot be read through the ordinary
# `GET /{ig-comment-id}` node "unless the request is made by the comment
# owner"). UNVERIFIED LIVE: no successful call has ever been made against
# either endpoint (Business Verification + Advanced Access still pending —
# same gate `UNCOVERED_SURFACES["webhook_payloads"]` already names). This is
# the same honesty discipline `inbox.client`'s `[V]` marker enforces, applied
# to a still-*un*verified contract: do not read the absence of `[VERIFIED]`
# below as an oversight.
# --------------------------------------------------------------------------

_MENTIONED_MEDIA: Final = (
    "instagram-platform/instagram-graph-api/reference/ig-user/mentioned_media.md"
)
_MENTIONED_COMMENT: Final = (
    "instagram-platform/instagram-graph-api/reference/ig-user/mentioned_comment.md"
)

MENTIONED_MEDIA_FIELDS: Final = "id,caption,media_type,like_count,timestamp,username"
"""A subset of `mentioned_media.md`'s Fields table (`#47-60`) — exactly what the
Dashboard de Menciones (QUA-49) needs. Deliberately excludes `media_url`,
`owner`, `comments`, `comments_count`: nothing downstream consumes them, and
requesting fields nobody reads would make a future schema change look
required instead of opt-in — same discipline `inbox.media_client.MEDIA_FIELDS`
already documents for its own picker fields.
"""

MENTIONED_MEDIA_FIELDS_CITATION: Final = Citation(
    path=_MENTIONED_MEDIA, line=51, quote="The caption text."
)

MENTIONED_MEDIA_NO_VIEWS_CITATION: Final = Citation(
    path=_MENTIONED_MEDIA, line=49, quote="| Field | Description |"
)
"""Pinned deliberately, not merely absent by omission: `mentioned_media.md`'s
entire Fields table (lines 49-60) carries no views/plays/impressions field
under any name. View-count metrics live in Insights, which is scoped to media
the app user OWNS (`instagram-platform/insights.md`) — a mention on a THIRD
PARTY's content structurally cannot carry a view count from this node, for any
future API version, not just today's. `Mention.views` MUST NOT be requested or
derived; `qualify_api.mentions.meta_client` cites this same absence at its own
call site so the two do not drift.
"""


def _optional_str(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def _optional_int(payload: dict[str, Any], field: str) -> int | None:
    """Meta's docs type `like_count` as `*String*` but real payloads have been
    observed elsewhere in this codebase (`inbox`) returning a JSON integer —
    accept either rather than trust the docs' own type label."""
    value = payload.get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


@dataclass(frozen=True)
class MentionedMedia:
    """The `mentioned_media` object nested in
    `GET /{ig-user-id}?fields=mentioned_media.media_id(...)`'s response
    (`mentioned_media.md:71-79`) — the caption of a media object where the
    connected account was @mentioned OUTSIDE a comment (no `comment_id` on the
    triggering `MentionEvent`)."""

    id: str
    caption: str | None
    media_type: str | None
    like_count: int | None
    timestamp: datetime | None
    username: str | None


def parse_mentioned_media(payload: dict[str, Any]) -> MentionedMedia:
    """[UNVERIFIED LIVE — see this section's module comment]. Parses the INNER
    `mentioned_media` object, not the whole response envelope (`{"mentioned_media":
    {...}, "id": "<ig-user-id>"}` — `mentioned_media.md:71-79`'s Sample Response).
    Callers pass `response["mentioned_media"]`.
    """
    media_id = payload.get("id")
    if not isinstance(media_id, str) or not media_id:
        raise ValueError("mentioned_media response carried no id")
    raw_timestamp = payload.get("timestamp")
    return MentionedMedia(
        id=media_id,
        caption=_optional_str(payload, "caption"),
        media_type=_optional_str(payload, "media_type"),
        like_count=_optional_int(payload, "like_count"),
        timestamp=parse_meta_timestamp(raw_timestamp) if isinstance(raw_timestamp, str) else None,
        username=_optional_str(payload, "username"),
    )


MENTIONED_COMMENT_FIELDS: Final = "id,text,like_count,timestamp"
"""A subset of `mentioned_comment.md`'s Fields table (`#47-53`). No `media`
field expansion: the triggering `MentionEvent` already carries `media_id`, so
expanding `media` here would be a redundant call for data already in hand."""

MENTIONED_COMMENT_FIELDS_CITATION: Final = Citation(
    path=_MENTIONED_COMMENT, line=52, quote="Text of the IG Comment."
)


@dataclass(frozen=True)
class MentionedComment:
    """The `mentioned_comment` object nested in
    `GET /{ig-user-id}?fields=mentioned_comment.comment_id(...)`'s response
    (`mentioned_comment.md:66-76`) — the text of a comment where the connected
    account was @mentioned."""

    id: str
    text: str | None
    like_count: int | None
    timestamp: datetime | None


def parse_mentioned_comment(payload: dict[str, Any]) -> MentionedComment:
    """[UNVERIFIED LIVE — see this section's module comment]. Parses the INNER
    `mentioned_comment` object, not the whole response envelope
    (`mentioned_comment.md:66-76`'s Sample Response). Callers pass
    `response["mentioned_comment"]`.
    """
    comment_id = payload.get("id")
    if not isinstance(comment_id, str) or not comment_id:
        raise ValueError("mentioned_comment response carried no id")
    raw_timestamp = payload.get("timestamp")
    return MentionedComment(
        id=comment_id,
        text=_optional_str(payload, "text"),
        like_count=_optional_int(payload, "like_count"),
        timestamp=parse_meta_timestamp(raw_timestamp) if isinstance(raw_timestamp, str) else None,
    )
