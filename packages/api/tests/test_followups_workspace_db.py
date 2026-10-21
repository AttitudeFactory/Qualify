"""The reads behind «Consultas desde comentarios» against Postgres (m-24789646, PR 3): one
query returns a page of origins with their post (caption, link, surface) and the author's
existing DM thread with its last inbound; the commercial reader returns exactly the
recent, commercial, not-yet-followed comments under the given version — under RLS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.followups import (
    FollowupTrigger,
    OriginKind,
    PostgresFollowupRepository,
    PostgresOriginReader,
    new_followup,
)
from qualify_api.followups.origins import PostgresCommercialIntentReader
from qualify_api.inbox.models import MonitoredMedia
from qualify_api.sentiment.repository import AnalysisVersion

from .test_followups_schema_db import NOW, seed_world

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000b1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000b2")
VERSION = AnalysisVersion("d", "p", "m", None)


@pytest.fixture
def seeded() -> dict[str, UUID]:
    world = seed_world(TENANT, OTHER)
    with tenant_session(TENANT) as session:
        media_id = session.execute(
            text(
                "SELECT t.external_thread_id FROM messages m JOIN threads t "
                "ON t.id = m.thread_id WHERE m.id = :id"
            ),
            {"id": world["comment"]},
        ).scalar_one()
        session.add(
            MonitoredMedia(
                tenant_id=TENANT,
                connection_id=world["connection"],
                external_media_id=media_id,
                is_monitored=True,
                caption="Llegó la colección de otoño",
                permalink="https://instagram.com/reel/x",
                media_product_type="REELS",
            )
        )
        session.execute(
            text("UPDATE threads SET last_inbound_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(hours=1), "id": world["dm_thread"]},
        )
    return world


def test_one_query_reads_the_origin_its_post_and_the_authors_dm_window(
    seeded: dict[str, UUID],
) -> None:
    origins = PostgresOriginReader().get_many(
        tenant_id=TENANT, message_ids=[seeded["comment"], seeded["story_reply"], uuid4()]
    )
    comment = origins[seeded["comment"]]
    assert comment.channel == "comment"
    assert comment.media_caption == "Llegó la colección de otoño"
    assert comment.media_permalink == "https://instagram.com/reel/x"
    assert comment.media_product_type == "REELS"
    assert comment.dm_thread_id == seeded["dm_thread"]
    assert comment.dm_last_inbound_at == NOW - timedelta(hours=1)
    dm = origins[seeded["story_reply"]]
    assert dm.channel == "dm"
    assert dm.dm_thread_id == seeded["dm_thread"]  # a DM is its own thread
    assert dm.media_caption is None
    assert len(origins) == 2
    assert PostgresOriginReader().get_many(tenant_id=OTHER, message_ids=[seeded["comment"]]) == {}
    assert PostgresOriginReader().get_many(tenant_id=TENANT, message_ids=[]) == {}


def test_the_commercial_reader_returns_recent_unfollowed_comments(
    seeded: dict[str, UUID],
) -> None:
    reader = PostgresCommercialIntentReader()

    def unfollowed(**overrides: object) -> list[UUID]:
        args: dict[str, object] = dict(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            version=VERSION,
            posted_since=NOW - timedelta(days=7),
            limit=20,
        )
        args.update(overrides)
        return [c.message_id for c in reader.unfollowed(**args)]  # type: ignore[arg-type]

    assert unfollowed() == [seeded["comment"]]
    [flag] = reader.unfollowed(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        version=VERSION,
        posted_since=NOW - timedelta(days=7),
        limit=20,
    )
    assert flag.intent_result_id == seeded["intent"]
    # Another version, an older comment window, another tenant: nothing.
    assert unfollowed(version=AnalysisVersion("d2", "p", "m", None)) == []
    assert unfollowed(posted_since=NOW + timedelta(minutes=1)) == []
    assert unfollowed(tenant_id=OTHER) == []
    # Once it has a followup, it is no longer offered.
    PostgresFollowupRepository().open(
        new_followup(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            origin_kind=OriginKind.COMMENT,
            origin_message_id=seeded["comment"],
            trigger=FollowupTrigger.INTENT,
            intent_result_id=seeded["intent"],
            now=datetime.now(UTC),
        )
    )
    assert unfollowed() == []
