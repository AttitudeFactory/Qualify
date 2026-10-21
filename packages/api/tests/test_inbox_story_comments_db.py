"""A story's comment, end to end in Postgres (m-24789644, B6): with `story_comments` on,
a monitored story's comment is stored by the real `PostgresInboxRepository` exactly like a
Reel's — so the sentiment and intent queues pick it up with no change of their own, and
the persisted surface says `STORY` (the UI's «Historia»).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment

from qualify_api.inbox.repository import PostgresInboxRepository
from qualify_api.inbox.service import InboxService
from qualify_api.intent import CURRENT_INTENT_VERSION
from qualify_api.intent.repository import PostgresIntentRepository
from qualify_api.sentiment.repository import PostgresSentimentRepository

from .test_inbox_story_comments import FakeComments, FakeMedia, _summary
from .test_sentiment_repository import VERSION, _seed_connection_only

pytestmark = pytest.mark.db

TENANT = UUID("e0000000-0000-4000-8000-0000000000f7")


async def test_a_story_comment_lands_in_the_sentiment_and_intent_queues() -> None:
    connection_id = _seed_connection_only(TENANT)
    story = _summary("story-1", "STORY", "VIDEO")
    now = story.timestamp + timedelta(hours=1)
    repo = PostgresInboxRepository()
    service = InboxService(
        repository=repo,
        comments_client=FakeComments(
            {"story-1": [IGComment.model_validate({"id": "c-story-1", "text": "¿precio?"})]}
        ),
        media_client=FakeMedia(stories=[story]),
        granted_scopes=frozenset(COMMENTS_EDGE_PERMISSIONS),
        story_comments=True,
    )

    await service.set_media_monitored(
        tenant_id=TENANT,
        connection_id=connection_id,
        external_media_id="story-1",
        monitored=True,
        now=now,
    )
    summary = await service.sync_comments(tenant_id=TENANT, connection_id=connection_id, now=now)

    assert summary.new_comments == 1
    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=connection_id, external_media_id="story-1"
    )
    assert row is not None and row.media_product_type == "STORY"
    sentiment_pending = PostgresSentimentRepository().list_pending_for_analysis(
        tenant_id=TENANT, connection_id=connection_id, version=VERSION
    )
    intent_pending = PostgresIntentRepository().list_pending_for_intent(
        tenant_id=TENANT, connection_id=connection_id, version=CURRENT_INTENT_VERSION
    )
    assert [p.source_id for p in sentiment_pending] == ["c-story-1"]
    assert [p.source_id for p in intent_pending] == ["c-story-1"]
