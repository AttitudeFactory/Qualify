"""`MemoryMentionsRepository` (QUA-49) — fully offline. Proves the idempotency and
sentiment-decoration invariants `repository.py`'s module docstring documents, without a
database; `test_mentions_repository_db.py` proves the same natural-key idempotency holds
under the REAL Postgres constraint (`uq_mention_natural_key`), which is the one thing an
in-memory dict cannot stand in for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MENTIONS_PAGE_SIZE,
    ORIGIN_COMMENT,
    ORIGIN_POST,
    SENTIMENT_NEU,
    SENTIMENT_NO_TEXT,
    SENTIMENT_PENDING,
    SENTIMENT_POS,
    MemoryMentionsRepository,
    MentionCounts,
    MentionPage,
    MentionQuery,
    NewMention,
    sentiment_state_for,
)
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
OTHER_TENANT = UUID("33333333-3333-4333-8333-333333333333")
OTHER_CONNECTION = UUID("44444444-4444-4444-8444-444444444444")

VERSION = AnalysisVersion(
    detector_version="v1",
    pipeline_version="mentions-text-1.0.0",
    model_id="m1",
    model_revision=None,
)


def _new_mention(
    *,
    media_id: str = "media-1",
    comment_id: str | None = None,
    tenant_id: UUID = TENANT,
    connection_id: UUID = CONNECTION,
    text: str | None = None,
    caption: str | None = None,
    enrichment_status: str = ENRICHMENT_OK,
) -> NewMention:
    return NewMention(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_account_id="ig-user-1",
        media_id=media_id,
        comment_id=comment_id,
        caption=caption,
        text=text,
        author_username="someone",
        media_type="IMAGE",
        like_count=3,
        content_posted_at=datetime(2026, 8, 1, tzinfo=UTC),
        enrichment_status=enrichment_status,
    )


def test_upsert_mention_creates_a_row() -> None:
    repo = MemoryMentionsRepository()

    mention_id, created = repo.upsert_mention(_new_mention())

    assert created is True
    records = repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)
    assert len(records) == 1
    assert records[0].id == mention_id
    assert records[0].media_id == "media-1"


def test_upsert_mention_is_idempotent_on_connection_media_comment() -> None:
    repo = MemoryMentionsRepository()
    first_id, first_created = repo.upsert_mention(_new_mention(comment_id="c1"))
    second_id, second_created = repo.upsert_mention(_new_mention(comment_id="c1"))

    assert first_created is True
    assert second_created is False
    assert first_id == second_id
    assert len(repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)) == 1


def test_upsert_mention_treats_two_caption_mentions_on_the_same_media_as_one() -> None:
    """Both events carry `comment_id=None` — the COALESCE-normalized natural key this
    module's docstring documents must still dedupe them, exactly as Postgres'
    `uq_mention_natural_key` does via `COALESCE(comment_id, '')`."""
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(media_id="media-1", comment_id=None))
    _id, created = repo.upsert_mention(_new_mention(media_id="media-1", comment_id=None))

    assert created is False
    assert len(repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)) == 1


def test_upsert_mention_a_caption_and_a_comment_mention_on_the_same_media_are_different_rows() -> (
    None
):
    """The one case a naive `COALESCE(comment_id, '') = COALESCE(comment_id, '')` dedupe
    could get wrong in the other direction: a caption mention (`comment_id=None`) and a
    comment mention (`comment_id='c1'`) on the SAME media are two distinct real events and
    must persist as two rows."""
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(media_id="media-1", comment_id=None))
    repo.upsert_mention(_new_mention(media_id="media-1", comment_id="c1"))

    assert len(repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)) == 2


def test_list_mentions_is_tenant_scoped() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(tenant_id=TENANT, connection_id=CONNECTION))
    repo.upsert_mention(_new_mention(tenant_id=OTHER_TENANT, connection_id=OTHER_CONNECTION))

    records = repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)

    assert len(records) == 1
    assert records[0].external_account_id == "ig-user-1"


def test_list_mentions_filters_by_connection_id() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(media_id="a", connection_id=CONNECTION))
    other_connection = uuid4()
    repo.upsert_mention(_new_mention(media_id="b", connection_id=other_connection))

    records = repo.list_mentions(tenant_id=TENANT, connection_id=CONNECTION, version=VERSION)

    assert [r.media_id for r in records] == ["a"]


def test_enrichment_failure_is_persisted_not_dropped() -> None:
    """`ingest_mention`'s own posture (composition.py's docstring): a mention whose
    Meta enrichment failed is still a real fact and must still be a row, just with
    null content and `enrichment_status=ENRICHMENT_FAILED`."""
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(enrichment_status=ENRICHMENT_FAILED, caption=None, text=None))

    records = repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)

    assert len(records) == 1
    assert records[0].enrichment_status == ENRICHMENT_FAILED
    assert records[0].caption is None
    assert records[0].text is None


def test_pending_analysis_excludes_mentions_with_no_text_or_caption() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(media_id="no-text", text=None, caption=None))
    repo.upsert_mention(_new_mention(media_id="with-caption", caption="hola @qualifymkt.co"))

    pending = repo.list_pending_for_analysis(tenant_id=TENANT, version=VERSION)

    assert [p.text for p in pending] == ["hola @qualifymkt.co"]


def test_record_sentiment_result_is_idempotent_and_excludes_from_pending() -> None:
    repo = MemoryMentionsRepository()
    mention_id, _created = repo.upsert_mention(_new_mention(text="excelente!"))

    first = repo.record_sentiment_result(
        tenant_id=TENANT, mention_id=mention_id, version=VERSION, label="POS", score=0.9
    )
    second = repo.record_sentiment_result(
        tenant_id=TENANT, mention_id=mention_id, version=VERSION, label="POS", score=0.9
    )

    assert first is True
    assert second is False
    assert repo.list_pending_for_analysis(tenant_id=TENANT, version=VERSION) == ()


def test_list_mentions_decorates_current_version_sentiment_label() -> None:
    repo = MemoryMentionsRepository()
    mention_id, _created = repo.upsert_mention(_new_mention(text="pésimo servicio"))
    repo.record_sentiment_result(
        tenant_id=TENANT, mention_id=mention_id, version=VERSION, label="NEG", score=0.8
    )

    records = repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)

    assert records[0].sentiment_label == "NEG"


def test_list_mentions_sentiment_is_none_when_not_analyzed() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_new_mention(text="sin analizar todavía"))

    records = repo.list_mentions(tenant_id=TENANT, connection_id=None, version=VERSION)

    assert records[0].sentiment_label is None


# --------------------------------------------------------------------------------------
# QUA-152 — paginated read over ALL stored mentions, counts over the whole filtered set
# --------------------------------------------------------------------------------------


def _paged_mention(
    index: int,
    *,
    tenant_id: UUID = TENANT,
    connection_id: UUID = CONNECTION,
    comment: bool = False,
    caption: str | None = "una mención",
    text: str | None = None,
    author: str | None = "autora",
    posted_at: datetime | None = datetime(2026, 8, 1, tzinfo=UTC),
) -> NewMention:
    return NewMention(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_account_id="ig-user-1",
        media_id=f"media-{index}",
        comment_id=f"comment-{index}" if comment else None,
        caption=None if comment else caption,
        text=(text if text is not None else "un comentario") if comment else None,
        author_username=None if comment else author,
        media_type="IMAGE",
        like_count=index,
        content_posted_at=posted_at,
        enrichment_status=ENRICHMENT_OK,
    )


def _page(
    repo: MemoryMentionsRepository,
    query: MentionQuery | None = None,
    *,
    tenant_id: UUID = TENANT,
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


def test_paging_walks_every_mention_beyond_the_old_50_cap_exactly_once() -> None:
    """57 mentions with the SAME publication date (a tie on the sort key): every page is
    12 except the last, and walking them yields all 57, none repeated, none skipped."""
    repo = MemoryMentionsRepository()
    created = {repo.upsert_mention(_paged_mention(i))[0] for i in range(57)}

    first = _page(repo)
    seen = [r.id for r in first.rows]
    for page in range(2, first.total_pages + 1):
        seen.extend(r.id for r in _page(repo, page=page, as_of=first.as_of).rows)

    assert first.counts.total == 57
    assert first.total_pages == 5
    assert len(first.rows) == MENTIONS_PAGE_SIZE == 12
    assert len(seen) == 57
    assert set(seen) == created


def test_paging_orders_by_publication_date_falling_back_to_reception() -> None:
    repo = MemoryMentionsRepository()
    old, _ = repo.upsert_mention(_paged_mention(1, posted_at=datetime(2026, 1, 1, tzinfo=UTC)))
    unknown, _ = repo.upsert_mention(_paged_mention(2, posted_at=None))  # received "now"
    mid, _ = repo.upsert_mention(_paged_mention(3, posted_at=datetime(2026, 6, 1, tzinfo=UTC)))

    assert [r.id for r in _page(repo).rows] == [unknown, mid, old]


def test_counts_cover_the_whole_filtered_set_not_the_page() -> None:
    repo = MemoryMentionsRepository()
    ids = [repo.upsert_mention(_paged_mention(i))[0] for i in range(30)]
    for mention_id in ids[:5]:
        repo.record_sentiment_result(
            tenant_id=TENANT, mention_id=mention_id, version=VERSION, label="POS", score=0.9
        )
    for mention_id in ids[5:8]:
        repo.record_sentiment_result(
            tenant_id=TENANT, mention_id=mention_id, version=VERSION, label="NEG", score=0.9
        )
    repo.upsert_mention(_paged_mention(99, caption="   "))  # blank: nothing to analyze

    page = _page(repo, page=3)

    assert len(page.rows) == 7  # 31 rows, page 3 of 3
    assert page.counts == MentionCounts(
        total=31, positive=5, neutral=0, negative=3, pending=22, no_text=1
    )


def test_pending_and_no_text_are_never_counted_as_a_polarity() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_paged_mention(1))
    repo.upsert_mention(_paged_mention(2, caption=None))

    counts = _page(repo).counts

    assert (counts.positive, counts.neutral, counts.negative) == (0, 0, 0)
    assert (counts.pending, counts.no_text) == (1, 1)


def test_filters_by_origin_connection_sentiment_and_search() -> None:
    repo = MemoryMentionsRepository()
    post, _ = repo.upsert_mention(_paged_mention(1, caption="me encanta qualifymkt.co"))
    comment, _ = repo.upsert_mention(_paged_mention(2, comment=True, text="@qualifymkt.co mira"))
    other_conn, _ = repo.upsert_mention(_paged_mention(3, connection_id=OTHER_CONNECTION))
    repo.record_sentiment_result(
        tenant_id=TENANT, mention_id=post, version=VERSION, label="POS", score=0.9
    )

    def ids(query: MentionQuery) -> set[UUID]:
        page = _page(repo, query)
        assert page.counts.total == len(page.rows)
        return {r.id for r in page.rows}

    assert ids(MentionQuery(origin=ORIGIN_POST)) == {post, other_conn}
    assert ids(MentionQuery(origin=ORIGIN_COMMENT)) == {comment}
    assert ids(MentionQuery(connection_id=OTHER_CONNECTION)) == {other_conn}
    assert ids(MentionQuery(sentiment_state=SENTIMENT_POS)) == {post}
    assert ids(MentionQuery(sentiment_state=SENTIMENT_PENDING)) == {comment, other_conn}
    # Meta strips the "@" from third-party captions: both spellings find both rows.
    assert ids(MentionQuery(search="@qualifymkt.co")) == {post, comment}
    assert ids(MentionQuery(search="QUALIFYMKT")) == {post, comment}
    assert ids(MentionQuery(search="autora")) == {post, other_conn}


def test_snapshot_excludes_later_mentions_and_the_notice_counts_them() -> None:
    repo = MemoryMentionsRepository()
    for i in range(13):
        repo.upsert_mention(_paged_mention(i))
    first = _page(repo)

    late, _ = repo.upsert_mention(_paged_mention(100, posted_at=datetime(2030, 1, 1, tzinfo=UTC)))

    again = _page(repo, as_of=first.as_of)
    assert again.counts.total == 13
    assert late not in {r.id for r in again.rows}
    assert [r.id for r in again.rows] == [r.id for r in first.rows]
    assert repo.has_received_after(
        tenant_id=TENANT, version=VERSION, query=MentionQuery(), after=first.as_of
    )


def test_has_received_after_answers_yes_or_no_only() -> None:
    """The tick only needs to know whether anything arrived (QUA-152): no count, no cap."""
    repo = MemoryMentionsRepository()
    for i in range(55):
        repo.upsert_mention(_paged_mention(i))

    def arrived(after: datetime) -> bool:
        return repo.has_received_after(
            tenant_id=TENANT, version=VERSION, query=MentionQuery(), after=after
        )

    assert arrived(datetime(2000, 1, 1, tzinfo=UTC)) is True
    assert arrived(datetime(2999, 1, 1, tzinfo=UTC)) is False
    assert _page(repo).counts.total == 55


def test_a_page_past_the_end_lands_on_the_last_page() -> None:
    repo = MemoryMentionsRepository()
    for i in range(14):
        repo.upsert_mention(_paged_mention(i))

    page = _page(repo, page=9)

    assert page.page == 2
    assert len(page.rows) == 2


def test_empty_listing_is_page_one_of_one() -> None:
    page = _page(MemoryMentionsRepository())

    assert (page.page, page.total_pages, page.rows, page.counts.total) == (1, 1, (), 0)


def test_paging_never_crosses_tenants() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_paged_mention(1))
    repo.upsert_mention(_paged_mention(2, tenant_id=OTHER_TENANT, connection_id=OTHER_CONNECTION))

    page = _page(repo, tenant_id=OTHER_TENANT)

    assert page.counts.total == 1
    assert {r.connection_id for r in page.rows} == {OTHER_CONNECTION}


def test_page_rows_carry_media_type_and_sentiment_state() -> None:
    repo = MemoryMentionsRepository()
    repo.upsert_mention(_paged_mention(1))

    row = _page(repo).rows[0]

    assert row.media_type == "IMAGE"
    assert row.sentiment_state == SENTIMENT_PENDING


def test_sentiment_state_for() -> None:
    assert sentiment_state_for(label="NEU", text=None, caption=None) == SENTIMENT_NEU
    assert sentiment_state_for(label=None, text="hola", caption=None) == SENTIMENT_PENDING
    assert sentiment_state_for(label=None, text=None, caption="hola") == SENTIMENT_PENDING
    assert sentiment_state_for(label=None, text=None, caption=None) == SENTIMENT_NO_TEXT
    assert sentiment_state_for(label=None, text=" \n\t", caption="hola") == SENTIMENT_NO_TEXT


def test_mention_query_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        MentionQuery(origin="story")
    with pytest.raises(ValueError):
        MentionQuery(sentiment_state="positive")


def test_since_window_filters_by_mention_date_and_counts_follow() -> None:
    repo = MemoryMentionsRepository()
    recent, _ = repo.upsert_mention(_paged_mention(1, posted_at=datetime(2026, 10, 10, tzinfo=UTC)))
    repo.upsert_mention(_paged_mention(2, posted_at=datetime(2026, 9, 1, tzinfo=UTC)))
    undated, _ = repo.upsert_mention(_paged_mention(3, posted_at=None))  # received "now"

    page = _page(repo, MentionQuery(since=datetime(2026, 9, 29, tzinfo=UTC)))

    assert {r.id for r in page.rows} == {recent, undated}
    assert page.counts.total == 2
    assert _page(repo).counts.total == 3  # nothing deleted: the window is a view


def test_summarize_ignores_what_the_scope_query_leaves_out() -> None:
    repo = MemoryMentionsRepository()
    post, _ = repo.upsert_mention(_paged_mention(1, caption="me encanta"))
    repo.upsert_mention(_paged_mention(2, comment=True))
    repo.record_sentiment_result(
        tenant_id=TENANT, mention_id=post, version=VERSION, label="POS", score=0.9
    )
    as_of = _page(repo).as_of

    scope = repo.summarize(tenant_id=TENANT, version=VERSION, query=MentionQuery(), as_of=as_of)
    searched = _page(repo, MentionQuery(search="nada coincide"), as_of=as_of)

    assert (scope.total, scope.positive, scope.pending) == (2, 1, 1)
    assert searched.counts.total == 0  # the page narrows; the summary does not


def test_the_sql_blank_class_is_exactly_pythons_whitespace() -> None:
    """The bounded sentiment pass excludes blank texts in SQL; the service skips the ones
    whose `strip()` is empty. Both must agree, or a text counted as blank by one and not by
    the other sits at the head of every batch (QUA-152 review). Python's `re` reads the
    same `\\uXXXX` class syntax Postgres does."""
    import re

    from qualify_api.mentions.repository import _BLANK_CHARS

    blank = re.compile(_BLANK_CHARS)
    mismatches = [
        hex(code)
        for code in range(0x3001)
        if bool(blank.fullmatch(chr(code))) != chr(code).isspace()
    ]
    assert mismatches == []
