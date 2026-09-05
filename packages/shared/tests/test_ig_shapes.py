"""Tests for the Instagram comment field-shape contract (QUA-67).

Fully offline: no network, no weights, no connected account. The only external
thing these tests touch is the harvested corpus already on disk.

The most load-bearing test here is `test_every_citation_resolves_against_the_corpus`.
The contract's claims are only worth anything if they still match the corpus they
were derived from; that test makes a stale contract **fail** rather than quietly
lie after a re-harvest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from qualify_shared.social.ig_shapes import (
    COMMENT_LIMITS,
    COMMENTS_EDGE_PERMISSIONS,
    COMMENTS_EDGE_PERMISSIONS_CITATION,
    CORPUS_ROOT,
    IGSID_CITATION,
    IGSID_IS_PORTABLE_IDENTITY,
    LOGIN_FORK_CITATION,
    MENTIONED_COMMENT_FIELDS_CITATION,
    MENTIONED_MEDIA_FIELDS_CITATION,
    MENTIONED_MEDIA_NO_VIEWS_CITATION,
    MENTIONS_COMMENT_ID_CITATION,
    MENTIONS_ENTRY_ID_CITATION,
    MENTIONS_FIELD_CITATION,
    MENTIONS_MEDIA_ID_CITATION,
    REPLY_CREATION_CITATION,
    SIGNED_LOGIN_FORK,
    TIMESTAMP_CITATION_ISO,
    UNCOVERED_SURFACES,
    UNSUPPORTED_FIELDS,
    Citation,
    IGComment,
    LoginFork,
    MentionedComment,
    MentionedMedia,
    MentionEvent,
    Presence,
    parse_comments_page,
    parse_mentioned_comment,
    parse_mentioned_media,
    parse_mentions_notification,
    parse_meta_timestamp,
)


def _repo_root() -> Path:
    """Walk up until the harvested corpus is found."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / CORPUS_ROOT).is_dir():
            return candidate
    raise RuntimeError(f"could not locate {CORPUS_ROOT} above {__file__}")


def _all_citations() -> list[Citation]:
    """Every Citation the contract makes, from wherever it is attached."""
    found: list[Citation] = [
        IGSID_CITATION,
        TIMESTAMP_CITATION_ISO,
        LOGIN_FORK_CITATION,
        REPLY_CREATION_CITATION,
        COMMENTS_EDGE_PERMISSIONS_CITATION,
        MENTIONS_FIELD_CITATION,
        MENTIONS_MEDIA_ID_CITATION,
        MENTIONS_COMMENT_ID_CITATION,
        MENTIONS_ENTRY_ID_CITATION,
        MENTIONED_MEDIA_FIELDS_CITATION,
        MENTIONED_MEDIA_NO_VIEWS_CITATION,
        MENTIONED_COMMENT_FIELDS_CITATION,
        *COMMENT_LIMITS.citations,
        *UNSUPPORTED_FIELDS.values(),
        *(surface.citation for surface in UNCOVERED_SURFACES),
    ]
    for name in IGComment.model_fields:
        try:
            found.append(IGComment.policy_for(name).citation)
        except KeyError:  # pragma: no cover - every field carries a policy today
            pass
    return found


# ---------------------------------------------------------------------------
# The contract is falsifiable against its own evidence
# ---------------------------------------------------------------------------


def test_every_citation_resolves_against_the_corpus() -> None:
    """Each Citation must point at a real line containing the quoted text.

    This is what separates a contract from documentation. If Meta changes a doc
    and the corpus is re-harvested, this fails loudly and names the field whose
    grounding evaporated, instead of leaving a confidently-typed lie in place.
    """
    root = _repo_root()
    failures: list[str] = []

    for citation in _all_citations():
        path = root / CORPUS_ROOT / citation.path
        if not path.is_file():
            failures.append(f"missing file: {citation.path}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if citation.line > len(lines):
            failures.append(
                f"{citation.path}:{citation.line} out of range (file has {len(lines)} lines)"
            )
            continue
        actual = lines[citation.line - 1]
        if citation.quote not in actual:
            failures.append(
                f"{citation.path}:{citation.line} no longer contains {citation.quote!r}\n"
                f"    actual: {actual[:160]!r}"
            )

    assert not failures, "corpus citations went stale:\n" + "\n".join(failures)


def test_the_contract_actually_makes_citations() -> None:
    """Guards the test above against passing vacuously on an empty list."""
    assert len(_all_citations()) >= 20


def test_every_field_carries_a_presence_policy() -> None:
    """No field may be added without declaring why it might be absent."""
    for name in IGComment.model_fields:
        policy = IGComment.policy_for(name)
        assert isinstance(policy.presence, Presence)


# ---------------------------------------------------------------------------
# Timestamps: the corpus contradicts itself, so both forms must parse
# ---------------------------------------------------------------------------


def test_parses_iso_8601_with_meta_offset() -> None:
    """The form the comment surface actually emits (`ig-comment.md:80`)."""
    parsed = parse_meta_timestamp("2017-05-19T23:27:28+0000")
    assert parsed == datetime(2017, 5, 19, 23, 27, 28, tzinfo=UTC)
    assert parsed.tzinfo is not None


def test_parses_unix_epoch_integer() -> None:
    """The form the conversations docs declare, despite their own ISO example."""
    parsed = parse_meta_timestamp(1_495_236_448)
    assert parsed.tzinfo is not None
    assert parsed == datetime(2017, 5, 19, 23, 27, 28, tzinfo=UTC)


def test_parses_unix_epoch_as_numeric_string() -> None:
    """JSON numbers survive as strings often enough to be worth accepting."""
    assert parse_meta_timestamp("1495236448") == parse_meta_timestamp(1_495_236_448)


def test_both_documented_forms_agree_on_the_same_instant() -> None:
    """The whole point of parsing both: they must normalize to one instant."""
    assert parse_meta_timestamp("2017-05-19T23:27:28+0000") == parse_meta_timestamp(1_495_236_448)


def test_naive_iso_is_treated_as_utc() -> None:
    assert parse_meta_timestamp("2017-05-19T23:27:28") == datetime(
        2017, 5, 19, 23, 27, 28, tzinfo=UTC
    )


def test_non_utc_offset_is_normalized_to_utc() -> None:
    parsed = parse_meta_timestamp("2017-05-20T01:27:28+0200")
    assert parsed == datetime(2017, 5, 19, 23, 27, 28, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", "   ", "not-a-timestamp", "2017-13-45T99:99:99+0000"])
def test_unparseable_timestamps_raise(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_meta_timestamp(bad)


def test_bool_is_rejected_rather_than_read_as_epoch() -> None:
    """bool subclasses int; True would silently parse as 1970-01-01T00:00:01Z."""
    with pytest.raises(TypeError):
        parse_meta_timestamp(True)


# ---------------------------------------------------------------------------
# Author fields: mutually exclusive, permission-gated
# ---------------------------------------------------------------------------


def test_user_and_username_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        IGComment.model_validate({"id": "1", "user": "17841400000000000", "username": "someone"})


def test_either_author_field_alone_is_accepted() -> None:
    assert IGComment.model_validate({"id": "1", "username": "someone"}).username == "someone"
    assert IGComment.model_validate({"id": "1", "user": "17841400000000000"}).user is not None


def test_both_author_fields_absent_is_legal() -> None:
    """The common case: neither requested, or the permission is missing."""
    comment = IGComment.model_validate({"id": "1", "text": "hola"})
    assert comment.user is None
    assert comment.username is None


def test_the_two_author_fields_declare_each_other_exclusive() -> None:
    assert IGComment.policy_for("username").mutually_exclusive_with == "user"
    assert IGComment.policy_for("user").mutually_exclusive_with == "username"


def test_username_is_permission_gated_not_merely_optional() -> None:
    policy = IGComment.policy_for("username")
    assert policy.presence is Presence.REQUIRES_PERMISSION
    assert policy.permission == "instagram_manage_comments"


def test_user_is_ownership_gated() -> None:
    assert IGComment.policy_for("user").presence is Presence.IF_OWNED_BY_APP_USER


def test_fields_lost_without_the_comments_permission() -> None:
    """Consumers can ask the type what a missing grant costs them."""
    lost = IGComment.fields_requiring_permission("instagram_manage_comments")
    assert lost == {"username", "from_"}


# ---------------------------------------------------------------------------
# The `from` object and IGSID identity semantics
# ---------------------------------------------------------------------------


def test_wire_field_from_is_aliased_onto_from_() -> None:
    """`from` is a Python keyword; the wire name must still parse."""
    comment = IGComment.model_validate(
        {"id": "1", "from": {"id": "IGSID_123", "username": "someone"}}
    )
    assert comment.from_ is not None
    assert comment.from_.id == "IGSID_123"
    assert comment.from_.username == "someone"


def test_igsid_is_documented_as_non_portable() -> None:
    """Pins the decision that an author column keyed on IGSID cannot be joined."""
    assert IGSID_IS_PORTABLE_IDENTITY is False


def test_from_object_tolerates_a_missing_username() -> None:
    """`from.id` can arrive without `from.username` under a partial field request."""
    comment = IGComment.model_validate({"id": "1", "from": {"id": "IGSID_123"}})
    assert comment.from_ is not None
    assert comment.from_.username is None


# ---------------------------------------------------------------------------
# Fields Meta documents as unsupported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", sorted(UNSUPPORTED_FIELDS))
def test_unsupported_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="not supported"):
        IGComment.model_validate({"id": "1", field: "anything"})


def test_unknown_but_permitted_extra_fields_are_ignored() -> None:
    """Real payloads carry more than we model; that must not be an error."""
    comment = IGComment.model_validate({"id": "1", "some_future_meta_field": 42})
    assert comment.id == "1"


# ---------------------------------------------------------------------------
# Collection limits
# ---------------------------------------------------------------------------


def test_comment_collection_limits_match_the_corpus() -> None:
    assert COMMENT_LIMITS.max_per_query == 50
    assert COMMENT_LIMITS.returns_top_level_only is True
    assert COMMENT_LIMITS.filterable_by_timestamp is False
    assert COMMENT_LIMITS.reverse_chronological_since_api_version == "3.2"


def test_replies_are_expansion_only_so_absence_is_not_emptiness() -> None:
    """The trap worth encoding: `replies=None` != "this comment has no replies"."""
    assert IGComment.policy_for("replies").presence is Presence.EXPANSION_ONLY
    comment = IGComment.model_validate({"id": "1", "text": "hola"})
    assert comment.replies is None


def test_replies_parse_recursively_when_expanded() -> None:
    """`replies` is an EDGE (`{"data": [...]}`), like every other Graph API edge in
    this contract — not a bare list. Corrected 2026-09-05 against a real Meta
    response during QUA-22 manual testing; the bare-list shape this test used to
    assert had never been exercised against a comment with an actual reply."""
    comment = IGComment.model_validate(
        {
            "id": "1",
            "text": "parent",
            "replies": {"data": [{"id": "2", "text": "child", "parent_id": "1"}]},
        }
    )
    assert comment.replies is not None
    assert comment.replies.data[0].parent_id == "1"


# ---------------------------------------------------------------------------
# Permissions and the login fork
# ---------------------------------------------------------------------------


def test_the_whole_edge_needs_the_manage_comments_permission() -> None:
    """Not just `username` — without this the poll returns nothing at all."""
    assert "instagram_manage_comments" in COMMENTS_EDGE_PERMISSIONS
    assert "instagram_basic" in COMMENTS_EDGE_PERMISSIONS


def test_permissions_are_spelled_for_the_signed_fork() -> None:
    """Facebook-fork vocabulary; the `instagram_business_*` spellings must not leak."""
    assert SIGNED_LOGIN_FORK is LoginFork.FACEBOOK
    assert not any(p.startswith("instagram_business_") for p in COMMENTS_EDGE_PERMISSIONS)


def test_no_permission_uses_the_meta_typo_spelling() -> None:
    """`ig-comment/replies.md:36,76` writes `page_read_engagement` (singular). Meta typo."""
    assert not any(p.startswith("page_") for p in COMMENTS_EDGE_PERMISSIONS)


# ---------------------------------------------------------------------------
# Uncovered surfaces, as data
# ---------------------------------------------------------------------------


def test_uncovered_surfaces_are_queryable_by_name() -> None:
    names = {surface.name for surface in UNCOVERED_SURFACES}
    assert "direct_messages" in names
    assert "non_organic_comments" in names
    assert "webhook_payloads" in names
    assert "live_video_comments" in names


def test_dm_exclusion_records_what_would_unblock_it() -> None:
    dm = next(s for s in UNCOVERED_SURFACES if s.name == "direct_messages")
    assert dm.unblocked_by is not None
    assert "Advanced Access" in dm.unblocked_by


def test_the_human_toggle_ambiguity_is_recorded() -> None:
    """An empty DM poll is ambiguous between 'no messages' and 'toggle off'.

    A product requirement, not a footnote: an inbox that renders silence as zero
    would be reporting a permissions gap as customer disinterest.
    """
    toggle = next(s for s in UNCOVERED_SURFACES if s.name == "direct_messages_human_toggle")
    assert "AMBIGUOUS" in toggle.reason
    assert toggle.unblocked_by is not None
    assert "programmatically" in toggle.unblocked_by


def test_every_uncovered_surface_explains_itself() -> None:
    for surface in UNCOVERED_SURFACES:
        assert surface.reason.strip()
        assert surface.citation.quote.strip()


# ---------------------------------------------------------------------------
# Envelope parsing
# ---------------------------------------------------------------------------


def test_parse_comments_page_reads_the_data_envelope() -> None:
    page = parse_comments_page(
        {
            "data": [
                {"id": "1", "text": "primero", "timestamp": "2017-08-31T19:16:02+0000"},
                {"id": "2", "text": "segundo", "timestamp": "2017-08-31T18:10:30+0000"},
            ]
        }
    )
    assert [c.id for c in page.data] == ["1", "2"]
    assert page.data[0].timestamp == datetime(2017, 8, 31, 19, 16, 2, tzinfo=UTC)


def test_parse_comments_page_rejects_a_non_list_data() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        parse_comments_page({"data": {"id": "1"}})


def test_the_corpus_worked_example_parses() -> None:
    """The sample response at `ig-media/comments.md:89-104`, verbatim."""
    page = parse_comments_page(
        {
            "data": [
                {
                    "timestamp": "2017-08-31T19:16:02+0000",
                    "text": "This is awesome!",
                    "id": "17870913679156914",
                },
                {
                    "timestamp": "2017-08-31T18:10:30+0000",
                    "text": "*Sniff*",
                    "id": "17873440459141021",
                },
            ]
        }
    )
    assert len(page.data) == 2
    # No `from`/`username` in Meta's own example — absence is the normal case.
    assert all(c.from_ is None and c.username is None for c in page.data)


# The fixture-instance tests live in `packages/models/tests/test_ig_fixture_shape.py`,
# next to the fixture they read and to the sentiment path that consumes it.


# ---------------------------------------------------------------------------
# Mentions webhook envelope (QUA-49)
# ---------------------------------------------------------------------------


def test_parses_a_caption_mention_with_no_comment_id() -> None:
    """`webhooks-for-instagram.md`'s caption-mention sample: `media_id` only."""
    events = parse_mentions_notification(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841405726653026",
                    "time": 1520622968,
                    "changes": [{"field": "mentions", "value": {"media_id": "17918195224117851"}}],
                }
            ],
        }
    )
    assert events == (
        MentionEvent(ig_user_id="17841405726653026", media_id="17918195224117851", comment_id=None),
    )


def test_parses_a_comment_mention_with_both_ids() -> None:
    """`webhooks-for-instagram.md`'s comment-mention sample: `media_id` + `comment_id`."""
    events = parse_mentions_notification(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841405726653026",
                    "changes": [
                        {
                            "field": "mentions",
                            "value": {
                                "comment_id": "17894227972186120",
                                "media_id": "17918195224117851",
                            },
                        }
                    ],
                }
            ],
        }
    )
    assert events == (
        MentionEvent(
            ig_user_id="17841405726653026",
            media_id="17918195224117851",
            comment_id="17894227972186120",
        ),
    )


def test_parses_a_batch_of_multiple_updates() -> None:
    """Meta batches up to 1000 updates per delivery; multiple entries must all parse."""
    events = parse_mentions_notification(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "111",
                    "changes": [{"field": "mentions", "value": {"media_id": "aaa"}}],
                },
                {
                    "id": "222",
                    "changes": [{"field": "mentions", "value": {"media_id": "bbb"}}],
                },
            ],
        }
    )
    assert {e.ig_user_id for e in events} == {"111", "222"}


def test_skips_changes_for_fields_other_than_mentions() -> None:
    """A subscribed app receives notifications for every field it is subscribed to
    (`webhooks-for-instagram.md`'s Limitations), so a real batch may carry an
    unrelated field once this app subscribes to more than `mentions`."""
    events = parse_mentions_notification(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "111",
                    "changes": [
                        {"field": "comments", "value": {"text": "hola"}},
                        {"field": "mentions", "value": {"media_id": "aaa"}},
                    ],
                }
            ],
        }
    )
    assert len(events) == 1
    assert events[0].media_id == "aaa"


def test_entry_with_no_changes_yields_no_events() -> None:
    events = parse_mentions_notification({"object": "instagram", "entry": [{"id": "111"}]})
    assert events == ()


def test_malformed_mentions_value_raises() -> None:
    """A `mentions` change missing the documented-required `media_id` is a real
    contract violation, unlike an unrelated field — that must fail loudly."""
    with pytest.raises(ValidationError):
        parse_mentions_notification(
            {
                "object": "instagram",
                "entry": [{"id": "111", "changes": [{"field": "mentions", "value": {}}]}],
            }
        )


def test_mentions_entry_id_is_the_mentioned_account_not_the_mentioner() -> None:
    """Pins the semantics `MENTIONS_ENTRY_ID_CITATION` documents, so a future reader
    cannot accidentally treat `ig_user_id` as the third party who wrote the mention."""
    assert "app user's Instagram professional account" in MENTIONS_ENTRY_ID_CITATION.quote


# ---------------------------------------------------------------------------
# The architect's condition on this module's home, enforced rather than trusted
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS = (
    "sqlalchemy",
    "psycopg",
    "httpx",
    "requests",
    "fastapi",
    "qualify_api",
    "qualify_models",
    "qualify_shared.db",
)


def test_the_contract_stays_strictly_a_contract() -> None:
    """Parsing and validation only — no DB, no HTTP, no business logic.

    The architect's binding condition for letting this module live in
    `qualify_shared`: the moment it imports a session or a client it stops being
    shareable, and the dependency direction that motivated the move
    (`qualify_api` must not depend on `qualify_models` for a payload contract)
    would be quietly re-broken.

    Being in `shared` actively invites additions, so this is a standing test
    rather than a one-time inspection — the same discipline as
    `test_session_sanctity.py` in this package.
    """
    source = (
        Path(__file__).resolve().parents[1] / "src" / "qualify_shared" / "social" / "ig_shapes.py"
    ).read_text(encoding="utf-8")

    offenders = [
        name for name in FORBIDDEN_IMPORTS if f"import {name}" in source or f"from {name}" in source
    ]
    assert not offenders, (
        f"ig_shapes.py must stay a pure contract but imports: {offenders}. "
        "Move whatever needs these into the consumer package."
    )


# ---------------------------------------------------------------------------
# mentioned_media / mentioned_comment (QUA-49)
# ---------------------------------------------------------------------------


def test_parse_mentioned_media_reads_the_documented_sample() -> None:
    """`mentioned_media.md:71-79`'s own Sample Response, minus the fields this
    contract does not model (`media_url`, `owner`, `comments*`)."""
    inner = {
        "caption": "@bluebottle There can be only one!",
        "media_type": "IMAGE",
        "like_count": 12,
        "timestamp": "2018-03-20T00:05:29+0000",
        "username": "someoneelse",
        "id": "17918195224117851",
    }

    media = parse_mentioned_media(inner)

    assert media == MentionedMedia(
        id="17918195224117851",
        caption="@bluebottle There can be only one!",
        media_type="IMAGE",
        like_count=12,
        timestamp=datetime(2018, 3, 20, 0, 5, 29, tzinfo=UTC),
        username="someoneelse",
    )


def test_parse_mentioned_media_tolerates_missing_display_fields() -> None:
    """Only `id` is required — everything else is a display field Meta may omit
    (no caption set, like counts hidden, etc.), same posture
    `inbox.media_client._parse_media_summary` already takes for its own fields."""
    media = parse_mentioned_media({"id": "17918195224117851"})

    assert media.id == "17918195224117851"
    assert media.caption is None
    assert media.like_count is None
    assert media.timestamp is None


def test_parse_mentioned_media_requires_an_id() -> None:
    with pytest.raises(ValueError, match="no id"):
        parse_mentioned_media({"caption": "no id here"})


def test_mentioned_media_has_no_views_field_in_its_contract() -> None:
    """Structural guard for the product rule: `MentionedMedia` must never grow a
    views/plays field, because Meta's own Fields table for this node never has one
    (`MENTIONED_MEDIA_NO_VIEWS_CITATION`)."""
    assert "views" not in MentionedMedia.__dataclass_fields__
    assert "plays" not in MentionedMedia.__dataclass_fields__
    assert "view_count" not in MentionedMedia.__dataclass_fields__


def test_parse_mentioned_comment_reads_the_documented_sample() -> None:
    """`mentioned_comment.md:64-76`'s own Sample Response."""
    inner = {
        "timestamp": "2017-05-03T16:09:08+0000",
        "like_count": 185,
        "text": "Shout out to @metricsaurus",
        "id": "17873440459141021",
    }

    comment = parse_mentioned_comment(inner)

    assert comment == MentionedComment(
        id="17873440459141021",
        text="Shout out to @metricsaurus",
        like_count=185,
        timestamp=datetime(2017, 5, 3, 16, 9, 8, tzinfo=UTC),
    )


def test_parse_mentioned_comment_requires_an_id() -> None:
    with pytest.raises(ValueError, match="no id"):
        parse_mentioned_comment({"text": "no id here"})


def test_mentioned_comment_has_no_views_field_in_its_contract() -> None:
    assert "views" not in MentionedComment.__dataclass_fields__
    assert "plays" not in MentionedComment.__dataclass_fields__
