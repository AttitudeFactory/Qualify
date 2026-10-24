"""m-24852202 against Postgres: the picture's columns (0089) are written once, kept
together by their CHECK, invisible to another tenant, and reach the Reel summaries."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import IGComment
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.inbox.repository import PostgresInboxRepository
from qualify_api.inbox.thumbnails import MemoryThumbnailStore, thumbnail_key

from .test_inbox_thumbnails import NOW, FakeMedia, _media, _service
from .test_sentiment_repository import VERSION, _seed_connection_only

pytestmark = pytest.mark.db


async def _activated(tenant: UUID) -> tuple[UUID, PostgresInboxRepository]:
    connection = _seed_connection_only(tenant)
    repo = PostgresInboxRepository()
    service = _service(repo, FakeMedia({"1801": _media()}), MemoryThumbnailStore())
    await service.set_media_monitored(
        tenant_id=tenant,
        connection_id=connection,
        external_media_id="1801",
        monitored=True,
        now=NOW,
    )
    return connection, repo


async def test_activation_writes_the_picture_once() -> None:
    tenant = uuid4()
    connection, repo = await _activated(tenant)
    row = repo.get_monitored_media(
        tenant_id=tenant, connection_id=connection, external_media_id="1801"
    )
    assert row is not None
    assert row.thumbnail_key == thumbnail_key(tenant, connection, "1801")
    assert row.thumbnail_source == "meta_thumbnail_url"
    assert row.thumbnail_content_type == "image/jpeg"

    again = repo.record_media_thumbnail(
        tenant_id=tenant,
        connection_id=connection,
        external_media_id="1801",
        key=f"t/{tenant}/other",
        content_type="image/png",
        source="meta_media_url",
        stored_at=NOW,
    )
    assert again is False
    assert (
        repo.list_media_missing_thumbnail(tenant_id=tenant, connection_id=connection, limit=10)
        == ()
    )


async def test_another_tenant_can_neither_see_nor_write_the_picture() -> None:
    tenant, intruder = uuid4(), uuid4()
    connection, repo = await _activated(tenant)
    _seed_connection_only(intruder)
    assert (
        repo.get_monitored_media(
            tenant_id=intruder, connection_id=connection, external_media_id="1801"
        )
        is None
    )
    assert (
        repo.record_media_thumbnail(
            tenant_id=intruder,
            connection_id=connection,
            external_media_id="1801",
            key=f"t/{intruder}/x",
            content_type="image/jpeg",
            source="meta_thumbnail_url",
            stored_at=NOW,
        )
        is False
    )


async def test_the_check_keeps_the_columns_together() -> None:
    tenant = uuid4()
    connection, _ = await _activated(tenant)
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE monitored_media SET thumbnail_source = 'somewhere' "
                "WHERE connection_id = :cid"
            ),
            {"cid": str(connection)},
        )
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE monitored_media SET thumbnail_content_type = NULL "
                "WHERE connection_id = :cid"
            ),
            {"cid": str(connection)},
        )


async def test_the_reel_summary_carries_the_stored_picture() -> None:
    from qualify_api.sentiment.repository import PostgresSentimentRepository

    tenant = uuid4()
    connection, repo = await _activated(tenant)
    repo.upsert_comment(
        tenant_id=tenant,
        connection_id=connection,
        external_media_id="1801",
        comment=IGComment.model_validate({"id": f"c-{uuid4()}", "text": "lindo"}),
    )
    summaries = PostgresSentimentRepository().list_reel_summaries(
        tenant_id=tenant, connection_id=connection, version=VERSION, cursor=None
    )
    assert [(s.thumbnail_key, s.thumbnail_content_type) for s in summaries] == [
        (thumbnail_key(tenant, connection, "1801"), "image/jpeg")
    ]
