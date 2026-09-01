"""`MemoryMentionsRepository` (QUA-49) — fully offline. Proves the idempotency and
sentiment-decoration invariants `repository.py`'s module docstring documents, without a
database; `test_mentions_repository_db.py` proves the same natural-key idempotency holds
under the REAL Postgres constraint (`uq_mention_natural_key`), which is the one thing an
in-memory dict cannot stand in for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MemoryMentionsRepository,
    NewMention,
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
