"""`PostgresMentionsRepository.list_mentions_page` (QUA-152)
against real Postgres.

What the in-memory twin cannot prove: that the SQL total order really yields every row
exactly once across OFFSET pages, that the `COUNT(*) FILTER` aggregates agree with a
direct count, that the SQL sentiment-state derivation matches `sentiment_state_for`, that
the ILIKE search escapes `%`/`_`, and that RLS keeps one tenant's pages and counts away
from another's.

Every test uses a FRESH tenant: `qualify_test` is never emptied between runs, so a fixed
tenant would accumulate rows and break the exact counts asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions.models import Mention
from qualify_api.mentions.repository import (
    ENRICHMENT_OK,
    ORIGIN_COMMENT,
    ORIGIN_POST,
    SENTIMENT_NEG,
    SENTIMENT_NO_TEXT,
    SENTIMENT_PENDING,
    SENTIMENT_POS,
    MentionContent,
    MentionCounts,
    MentionPage,
    MentionQuery,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

VERSION = AnalysisVersion(
    detector_version="v1",
    pipeline_version="mentions-text-1.0.0",
    model_id="m1",
    model_revision=None,
)

SAME_DAY = datetime(2026, 8, 1, tzinfo=UTC)


def _fresh_tenant_with_connection() -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"mentions-paging-{tenant_id}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return tenant_id, conn.id


def _add(
    repo: PostgresMentionsRepository,
    tenant_id: UUID,
    connection_id: UUID,
    *,
    comment: bool = False,
    caption: str | None = "una mención",
    text: str = "un comentario",
    author: str | None = "autora",
    posted_at: datetime | None = SAME_DAY,
) -> UUID:
    mention_id, created = repo.upsert_mention(
        NewMention(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_account_id="ig-user-1",
            media_id=f"media-{uuid4()}",
            comment_id=f"comment-{uuid4()}" if comment else None,
            caption=None if comment else caption,
            text=text if comment else None,
            author_username=None if comment else author,
            media_type="IMAGE",
            like_count=1,
            content_posted_at=posted_at,
            enrichment_status=ENRICHMENT_OK,
        )
    )
    assert created
    return mention_id


def _page(
    repo: PostgresMentionsRepository,
    tenant_id: UUID,
    query: MentionQuery | None = None,
    *,
    page: int = 1,
    as_of: datetime | None = None,
) -> MentionPage:
    return repo.list_mentions_page(
        tenant_id=tenant_id,
        version=VERSION,
        query=query or MentionQuery(),
        page=page,
        as_of=as_of,
    )


def test_57_tied_mentions_are_walked_exactly_once_across_offset_pages() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    created = {_add(repo, tenant_id, connection_id) for _ in range(57)}  # all SAME_DAY

    first = _page(repo, tenant_id)
    seen = [r.id for r in first.rows]
    for page in range(2, first.total_pages + 1):
        seen.extend(r.id for r in _page(repo, tenant_id, page=page, as_of=first.as_of).rows)

    assert (first.counts.total, first.total_pages, len(first.rows)) == (57, 5, 12)
    assert len(seen) == 57
    assert set(seen) == created


def test_order_is_publication_date_then_reception_date_newest_first() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    old = _add(repo, tenant_id, connection_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    unknown = _add(repo, tenant_id, connection_id, posted_at=None)  # sorts by received_at
    mid = _add(repo, tenant_id, connection_id, posted_at=datetime(2026, 6, 1, tzinfo=UTC))

    assert [r.id for r in _page(repo, tenant_id).rows] == [unknown, mid, old]


def test_counts_match_direct_counts_over_the_whole_set() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    ids = [_add(repo, tenant_id, connection_id) for _ in range(30)]
    for mention_id in ids[:4]:
        repo.record_sentiment_result(
            tenant_id=tenant_id, mention_id=mention_id, version=VERSION, label="POS", score=0.9
        )
    repo.record_sentiment_result(
        tenant_id=tenant_id, mention_id=ids[4], version=VERSION, label="NEG", score=0.9
    )
    _add(repo, tenant_id, connection_id, caption=" \n\t ")  # blank caption
    _add(repo, tenant_id, connection_id, caption=None)  # no caption at all

    page = _page(repo, tenant_id, page=3)
    with tenant_session(tenant_id) as session:
        direct_total = session.scalar(
            select(func.count()).select_from(Mention).where(Mention.tenant_id == tenant_id)
        )

    assert page.counts.total == direct_total == 32
    assert page.counts == MentionCounts(
        total=32, positive=4, neutral=0, negative=1, pending=25, no_text=2
    )
    assert len(page.rows) == 8


def test_sql_sentiment_state_matches_the_python_definition() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    analyzed = _add(repo, tenant_id, connection_id)
    repo.record_sentiment_result(
        tenant_id=tenant_id, mention_id=analyzed, version=VERSION, label="NEG", score=0.9
    )
    pending = _add(repo, tenant_id, connection_id)
    blank = _add(repo, tenant_id, connection_id, caption="   ")

    states = {r.id: r.sentiment_state for r in _page(repo, tenant_id).rows}

    assert states == {analyzed: SENTIMENT_NEG, pending: SENTIMENT_PENDING, blank: SENTIMENT_NO_TEXT}


def test_filters_narrow_rows_and_counts_together() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    post = _add(repo, tenant_id, connection_id, caption="me encanta qualifymkt.co")
    comment = _add(repo, tenant_id, connection_id, comment=True, text="@qualifymkt.co mira")
    plain = _add(repo, tenant_id, connection_id, caption="otra cosa", author="alguien")
    repo.record_sentiment_result(
        tenant_id=tenant_id, mention_id=post, version=VERSION, label="POS", score=0.9
    )

    def ids(query: MentionQuery) -> set[UUID]:
        page = _page(repo, tenant_id, query)
        assert page.counts.total == len(page.rows)
        return {r.id for r in page.rows}

    assert ids(MentionQuery(origin=ORIGIN_POST)) == {post, plain}
    assert ids(MentionQuery(origin=ORIGIN_COMMENT)) == {comment}
    assert ids(MentionQuery(connection_id=connection_id)) == {post, comment, plain}
    assert ids(MentionQuery(connection_id=uuid4())) == set()
    assert ids(MentionQuery(sentiment_state=SENTIMENT_POS)) == {post}
    assert ids(MentionQuery(search="@QualifyMkt.co")) == {post, comment}
    assert ids(MentionQuery(search="alguien")) == {plain}


def test_search_treats_like_wildcards_literally() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    percent = _add(repo, tenant_id, connection_id, caption="50% de descuento")
    _add(repo, tenant_id, connection_id, caption="500 de descuento")
    underscore = _add(repo, tenant_id, connection_id, caption="usa a_b")
    _add(repo, tenant_id, connection_id, caption="usa axb")

    assert {r.id for r in _page(repo, tenant_id, MentionQuery(search="50%")).rows} == {percent}
    assert {r.id for r in _page(repo, tenant_id, MentionQuery(search="a_b")).rows} == {underscore}


def test_snapshot_is_stable_and_a_new_snapshot_takes_new_mentions_in() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    for _ in range(13):
        _add(repo, tenant_id, connection_id)
    first = _page(repo, tenant_id)
    second_page = _page(repo, tenant_id, page=2, as_of=first.as_of)

    # Arrives after the snapshot, with a publication date that would sort it FIRST.
    late = _add(repo, tenant_id, connection_id, posted_at=datetime(2030, 1, 1, tzinfo=UTC))

    again_first = _page(repo, tenant_id, as_of=first.as_of)
    again_second = _page(repo, tenant_id, page=2, as_of=first.as_of)
    refreshed = _page(repo, tenant_id)

    assert [r.id for r in again_first.rows] == [r.id for r in first.rows]
    assert [r.id for r in again_second.rows] == [r.id for r in second_page.rows]
    assert again_first.counts.total == 13
    assert refreshed.rows[0].id == late
    assert refreshed.counts.total == 14


def test_another_tenant_sees_no_rows_or_counts() -> None:
    repo = PostgresMentionsRepository()
    tenant_a, connection_a = _fresh_tenant_with_connection()
    tenant_b, _connection_b = _fresh_tenant_with_connection()
    for _ in range(5):
        _add(repo, tenant_a, connection_a)

    page_b = _page(repo, tenant_b)

    assert page_b.counts == MentionCounts()
    assert page_b.rows == ()
    assert _page(repo, tenant_a).counts.total == 5


def test_since_window_and_permalink_round_trip() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    old = _add(repo, tenant_id, connection_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    new = _add(repo, tenant_id, connection_id, posted_at=datetime(2026, 10, 10, tzinfo=UTC))
    linked, _ = repo.upsert_mention(
        NewMention(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_account_id="ig-user-1",
            media_id=f"media-{uuid4()}",
            comment_id=None,
            caption="con enlace",
            text=None,
            author_username="autora",
            media_type="IMAGE",
            like_count=1,
            content_posted_at=datetime(2026, 10, 11, tzinfo=UTC),
            enrichment_status=ENRICHMENT_OK,
            permalink="https://www.instagram.com/p/ABC/",
        )
    )

    window = _page(repo, tenant_id, MentionQuery(since=datetime(2026, 10, 1, tzinfo=UTC)))
    links = {r.id: r.permalink for r in window.rows}

    assert set(links) == {new, linked}
    assert old not in links
    assert window.counts.total == 2
    assert links[linked] == "https://www.instagram.com/p/ABC/"
    assert links[new] is None
    assert _page(repo, tenant_id).counts.total == 3


def test_summarize_counts_the_scope_under_the_snapshot() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    first = _add(repo, tenant_id, connection_id)
    repo.record_sentiment_result(
        tenant_id=tenant_id, mention_id=first, version=VERSION, label="NEG", score=0.9
    )
    _add(repo, tenant_id, connection_id, comment=True)
    as_of = _page(repo, tenant_id).as_of
    _add(repo, tenant_id, connection_id)  # after the snapshot

    counts = repo.summarize(tenant_id=tenant_id, version=VERSION, query=MentionQuery(), as_of=as_of)
    comments = repo.summarize(
        tenant_id=tenant_id, version=VERSION, query=MentionQuery(origin=ORIGIN_COMMENT), as_of=as_of
    )

    assert (counts.total, counts.negative, counts.pending) == (2, 1, 1)
    assert comments.total == 1


def test_refresh_content_updates_content_only_and_identity_stays_locked() -> None:
    from sqlalchemy import text as sql
    from sqlalchemy.exc import DBAPIError

    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    mention_id = _add(repo, tenant_id, connection_id)
    other_tenant, _ = _fresh_tenant_with_connection()

    targets = repo.list_refresh_targets(tenant_id=tenant_id, mention_ids=(mention_id,))
    fresh = MentionContent(
        caption="editado",
        text=None,
        author_username="autora",
        media_type="VIDEO",
        like_count=42,
        content_posted_at=SAME_DAY,
        permalink="https://www.instagram.com/p/NEW/",
    )
    assert (
        repo.refresh_content(tenant_id=other_tenant, mention_id=mention_id, content=fresh) is False
    )
    assert repo.refresh_content(tenant_id=tenant_id, mention_id=mention_id, content=fresh) is True

    row = _page(repo, tenant_id).rows[0]
    assert [t.mention_id for t in targets] == [mention_id]
    assert (row.like_count, row.caption, row.permalink) == (
        42,
        "editado",
        "https://www.instagram.com/p/NEW/",
    )
    # The grant is column-level: identity columns stay read-only for the app role.
    with pytest.raises(DBAPIError), tenant_session(tenant_id) as session:
        session.execute(
            sql("UPDATE mentions SET media_id = 'x' WHERE id = :id"), {"id": mention_id}
        )


# --------------------------------------------------------------------------------------
# QUA-152 D1/D2 — the refresh write rules and run planning, in SQL
# --------------------------------------------------------------------------------------


def _content(**given: object) -> MentionContent:
    values: dict = dict.fromkeys(
        (
            "caption",
            "text",
            "author_username",
            "media_type",
            "like_count",
            "content_posted_at",
            "permalink",
        )
    )
    values.update(given)
    return MentionContent(**values)


def test_refresh_stores_an_explicit_zero_and_keeps_omitted_fields() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    mention_id = _add(repo, tenant_id, connection_id, caption="original")

    assert repo.refresh_content(
        tenant_id=tenant_id, mention_id=mention_id, content=_content(like_count=0)
    )

    row = _page(repo, tenant_id).rows[0]
    assert row.like_count == 0  # explicit value written
    assert (row.caption, row.author_username, row.media_type, row.content_posted_at) == (
        "original",
        "autora",
        "IMAGE",
        SAME_DAY,
    )  # omitted fields kept


def test_refresh_stamps_success_and_a_failed_attempt_stamps_only_the_attempt() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    ok_id = _add(repo, tenant_id, connection_id)
    failed_id = _add(repo, tenant_id, connection_id)

    repo.refresh_content(tenant_id=tenant_id, mention_id=ok_id, content=_content(like_count=4))
    repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=failed_id)

    with tenant_session(tenant_id) as session:
        stamps = {
            m.id: (m.content_refreshed_at, m.content_refresh_attempted_at, m.like_count)
            for m in session.scalars(select(Mention).where(Mention.tenant_id == tenant_id))
        }
    assert stamps[ok_id][0] is not None and stamps[ok_id][1] is not None
    assert stamps[failed_id][0] is None and stamps[failed_id][1] is not None
    assert stamps[failed_id][2] == 1  # content untouched


def test_scope_plan_covers_every_page_honours_freshness_and_isolates_tenants() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    other_tenant, other_connection = _fresh_tenant_with_connection()
    ids = [_add(repo, tenant_id, connection_id) for _ in range(30)]
    _add(repo, other_tenant, other_connection)
    _add(repo, tenant_id, connection_id, posted_at=datetime(2020, 1, 1, tzinfo=UTC))
    scope = MentionQuery(since=datetime(2026, 7, 1, tzinfo=UTC))

    plan = repo.plan_scope_refresh(tenant_id=tenant_id, query=scope, fresh_seconds=60, limit=500)
    assert (plan.in_scope, plan.fresh) == (30, 0)
    assert sorted(t.mention_id for t in plan.targets) == sorted(ids)

    for mention_id in ids[:12]:
        repo.refresh_content(tenant_id=tenant_id, mention_id=mention_id, content=_content())
    capped = repo.plan_scope_refresh(tenant_id=tenant_id, query=scope, fresh_seconds=60, limit=10)
    assert (capped.in_scope, capped.fresh, len(capped.targets)) == (30, 12, 10)
    assert not {t.mention_id for t in capped.targets} & set(ids[:12])


def test_scope_plan_takes_never_attempted_first_then_least_recently_attempted() -> None:
    """Outside the freshness window (0 s here), a mention that keeps failing waits behind
    the never-attempted ones and behind those attempted after it."""
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    failed, refreshed_later, never = (_add(repo, tenant_id, connection_id) for _ in range(3))
    repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=failed)
    repo.refresh_content(tenant_id=tenant_id, mention_id=refreshed_later, content=_content())

    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=10
    )

    assert [t.mention_id for t in plan.targets] == [never, failed, refreshed_later]


def test_the_app_role_may_stamp_refreshes_but_not_rewrite_identity() -> None:
    from qualify_shared.db.admin import admin_session as owner_view

    with owner_view() as session:
        grants = {
            column: session.scalar(
                select(func.has_column_privilege("qualify_app", "mentions", column, "UPDATE"))
            )
            for column in (
                "content_refreshed_at",
                "content_refresh_attempted_at",
                "removed_at",
                "like_count",
                "tenant_id",
                "media_id",
                "received_at",
            )
        }
    assert grants == {
        "content_refreshed_at": True,
        "content_refresh_attempted_at": True,
        "removed_at": True,
        "like_count": True,
        "tenant_id": False,
        "media_id": False,
        "received_at": False,
    }


def test_scope_plan_reports_a_moments_ago_failure_without_requesting_it_again() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    failed = _add(repo, tenant_id, connection_id)
    other = _add(repo, tenant_id, connection_id)
    repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=failed)

    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=60, limit=10
    )

    assert [t.mention_id for t in plan.targets] == [other]
    assert (plan.in_scope, plan.fresh, plan.recently_failed) == (2, 0, 1)


def test_a_removed_mention_leaves_every_read_and_a_redelivery_keeps_it_out() -> None:
    """Migration 0062: the app role may stamp `removed_at`; from then on the mention is out
    of the page, the counts, the new-mention count, the refresh plan and the sentiment
    queue — and re-inserting the same natural key (a redelivered webhook) does not
    bring it back."""
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    other_tenant, _ = _fresh_tenant_with_connection()
    kept = _add(repo, tenant_id, connection_id)
    gone = _add(repo, tenant_id, connection_id, comment=True)

    assert repo.mark_removed(tenant_id=other_tenant, mention_id=gone) is False  # RLS
    assert repo.mark_removed(tenant_id=tenant_id, mention_id=gone) is True
    assert repo.mark_removed(tenant_id=tenant_id, mention_id=gone) is True  # idempotent

    page = _page(repo, tenant_id)
    assert [row.id for row in page.rows] == [kept]
    assert page.counts.total == 1
    assert repo.summarize(
        tenant_id=tenant_id, version=VERSION, query=MentionQuery(), as_of=page.as_of
    ) == MentionCounts(total=1, pending=1)
    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=10
    )
    assert (plan.in_scope, [t.mention_id for t in plan.targets]) == (1, [kept])
    assert repo.list_refresh_targets(tenant_id=tenant_id, mention_ids=(gone,)) == ()
    pending = repo.list_pending_for_analysis(tenant_id=tenant_id, version=VERSION)
    assert [p.mention_id for p in pending] == [kept]
    listed = repo.list_mentions(tenant_id=tenant_id, connection_id=None, version=VERSION)
    assert [m.id for m in listed] == [kept]

    with tenant_session(tenant_id) as session:
        row = session.get(Mention, gone)
        assert row is not None and row.removed_at is not None
        media_id, comment_id = row.media_id, row.comment_id
    again, created = repo.upsert_mention(
        NewMention(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_account_id="ig-user-1",
            media_id=media_id,
            comment_id=comment_id,
            caption=None,
            text="un comentario",
            author_username=None,
            media_type=None,
            like_count=None,
            content_posted_at=None,
            enrichment_status=ENRICHMENT_OK,
        )
    )
    assert (again, created) == (gone, False)
    assert [row.id for row in _page(repo, tenant_id).rows] == [kept]


def test_a_successful_read_clears_removed_at() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    mention_id = _add(repo, tenant_id, connection_id)
    repo.mark_removed(tenant_id=tenant_id, mention_id=mention_id)
    assert _page(repo, tenant_id).counts.total == 0

    repo.refresh_content(tenant_id=tenant_id, mention_id=mention_id, content=_content())

    assert [row.id for row in _page(repo, tenant_id).rows] == [mention_id]


def test_a_refresh_target_says_whether_the_mention_was_ever_read() -> None:
    """`ever_read` (the 400/100-without-subcode removal guard) mirrors
    `content_refreshed_at`: only a successful read sets it — a failed attempt never does."""
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    read_id = _add(repo, tenant_id, connection_id, comment=True)
    attempted_id = _add(repo, tenant_id, connection_id, comment=True)
    repo.refresh_content(tenant_id=tenant_id, mention_id=read_id, content=_content())
    repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=attempted_id)

    targets = repo.list_refresh_targets(tenant_id=tenant_id, mention_ids=(read_id, attempted_id))

    assert {t.mention_id: t.ever_read for t in targets} == {read_id: True, attempted_id: False}


def test_a_recent_comment_read_is_proof_for_the_other_comments_of_its_connection() -> None:
    """`comment_read_recently` (QUA-152 review): another COMMENT mention of the same
    connection, re-read successfully within the window on the database clock — never the
    mention itself, a caption mention, a failed attempt or another tenant's row."""
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    candidate = _add(repo, tenant_id, connection_id, comment=True)
    other_comment = _add(repo, tenant_id, connection_id, comment=True)
    caption = _add(repo, tenant_id, connection_id)
    other_tenant, other_connection = _fresh_tenant_with_connection()

    def proof() -> bool:
        return repo.comment_read_recently(
            tenant_id=tenant_id, connection_id=connection_id, besides=candidate, within_seconds=60
        )

    repo.refresh_content(tenant_id=tenant_id, mention_id=candidate, content=_content())
    repo.refresh_content(tenant_id=tenant_id, mention_id=caption, content=_content())
    repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=other_comment)
    foreign = _add(repo, other_tenant, other_connection, comment=True)
    repo.refresh_content(tenant_id=other_tenant, mention_id=foreign, content=_content())
    assert proof() is False

    repo.refresh_content(tenant_id=tenant_id, mention_id=other_comment, content=_content())
    assert proof() is True
    assert (
        repo.comment_read_recently(
            tenant_id=tenant_id, connection_id=connection_id, besides=candidate, within_seconds=0
        )
        is False
    )


def test_scope_plan_rechecks_long_removed_mentions_only_with_spare_capacity() -> None:
    from datetime import timedelta

    from sqlalchemy import update

    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    live = _add(repo, tenant_id, connection_id)
    old_removed = _add(repo, tenant_id, connection_id)
    new_removed = _add(repo, tenant_id, connection_id)
    repo.mark_removed(tenant_id=tenant_id, mention_id=old_removed)
    repo.mark_removed(tenant_id=tenant_id, mention_id=new_removed)
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    with tenant_session(tenant_id) as session:
        session.execute(
            update(Mention)
            .where(Mention.id == old_removed)
            .values(removed_at=two_days_ago, content_refresh_attempted_at=two_days_ago)
        )

    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=10
    )
    assert plan.in_scope == 1
    assert [(t.mention_id, t.removed) for t in plan.targets] == [
        (live, False),
        (old_removed, True),
    ]

    full = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=1
    )
    assert [t.mention_id for t in full.targets] == [live]


def test_mark_removed_never_hides_a_mention_read_after_the_refusing_read_started() -> None:
    from datetime import timedelta

    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    mention_id = _add(repo, tenant_id, connection_id)
    read_started = datetime.now(UTC) - timedelta(seconds=5)
    repo.refresh_content(tenant_id=tenant_id, mention_id=mention_id, content=_content())

    assert (
        repo.mark_removed(
            tenant_id=tenant_id, mention_id=mention_id, unless_read_after=read_started
        )
        is False
    )
    assert [row.id for row in _page(repo, tenant_id).rows] == [mention_id]
    # A read older than the refusing one never shields it.
    assert (
        repo.mark_removed(
            tenant_id=tenant_id,
            mention_id=mention_id,
            unless_read_after=datetime.now(UTC) + timedelta(seconds=5),
        )
        is True
    )


def test_scope_plan_stops_rechecking_after_thirty_days_on_the_database_clock() -> None:
    """Boundaries are set from the database clock (`now()`), the one that stamps
    `removed_at`, so the test is immune to any app/database clock difference."""
    from datetime import timedelta

    from sqlalchemy import text as sql
    from sqlalchemy import update

    from qualify_api.mentions.repository import REMOVED_RECHECK_MAX_AGE_SECONDS

    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    ages = {
        "day-2": timedelta(days=2),
        "just-inside": timedelta(seconds=REMOVED_RECHECK_MAX_AGE_SECONDS) - timedelta(minutes=1),
        "just-outside": timedelta(seconds=REMOVED_RECHECK_MAX_AGE_SECONDS) + timedelta(minutes=1),
    }
    ids = {}
    with tenant_session(tenant_id) as session:
        db_now = session.scalar(sql("select now()"))
    for name, age in ages.items():
        mention_id = _add(repo, tenant_id, connection_id)
        repo.mark_removed(tenant_id=tenant_id, mention_id=mention_id)
        with tenant_session(tenant_id) as session:
            session.execute(
                update(Mention)
                .where(Mention.id == mention_id)
                .values(removed_at=db_now - age, content_refresh_attempted_at=db_now - age)
            )
        ids[mention_id] = name

    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=60, limit=200
    )

    assert sorted(ids[t.mention_id] for t in plan.targets) == ["day-2", "just-inside"]
    assert plan.in_scope == 0


def test_scope_plan_caps_rechecks_and_never_takes_live_capacity() -> None:
    from datetime import timedelta

    from sqlalchemy import update

    from qualify_api.mentions.repository import REMOVED_RECHECK_PER_RUN

    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    live = [_add(repo, tenant_id, connection_id) for _ in range(3)]
    removed = [_add(repo, tenant_id, connection_id) for _ in range(REMOVED_RECHECK_PER_RUN + 10)]
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    with tenant_session(tenant_id) as session:
        session.execute(
            update(Mention)
            .where(Mention.id.in_(removed))
            .values(removed_at=two_days_ago, content_refresh_attempted_at=two_days_ago)
        )

    plan = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=200
    )
    assert [t.mention_id for t in plan.targets if not t.removed] == live
    assert sum(t.removed for t in plan.targets) == REMOVED_RECHECK_PER_RUN

    tight = repo.plan_scope_refresh(
        tenant_id=tenant_id, query=MentionQuery(), fresh_seconds=0, limit=3
    )
    assert [t.mention_id for t in tight.targets] == live
