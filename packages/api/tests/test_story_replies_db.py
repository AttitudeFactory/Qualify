"""Replies to stories against Postgres (m-24789646, PR 5): migration 0075's columns and
CHECKs, the insert that adds a story to a message stored without it (and never
overwrites one), the origin reader, the commercial reader and the intent reader — each
taking story replies only when asked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import CheckViolation
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.conversations.contracts import RemoteMessage
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.followups import PostgresOriginReader
from qualify_api.followups.origins import PostgresCommercialIntentReader
from qualify_api.inbox.models import Message
from qualify_api.intent.models import CommentIntentResult
from qualify_api.intent.repository import PostgresIntentRepository
from qualify_api.sentiment.repository import AnalysisVersion

from .test_followups_schema_db import seed_world

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000c1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000c2")
VERSION = AnalysisVersion(
    detector_version=f"story-test-{uuid4().hex[:6]}",
    pipeline_version="p",
    model_id="m",
    model_revision=None,
)


@pytest.fixture
def seeded() -> dict[str, UUID]:
    return seed_world(TENANT, OTHER)


def _remote(mid: str, **kw: object) -> RemoteMessage:
    values: dict[str, object] = dict(
        external_message_id=mid,
        direction="inbound",
        text="¿Cuánto cuesta ese vestido?",
        posted_at=datetime.now(UTC) - timedelta(hours=1),
        shape_version=SHAPE_VERSION_IG_DM,
        author_external_id="igsid-x",
    )
    values.update(kw)
    return RemoteMessage(**values)  # type: ignore[arg-type]


def _insert(seeded: dict[str, UUID], message: RemoteMessage) -> bool:
    return PostgresConversationRepository().insert_message(
        tenant_id=TENANT,
        thread_id=seeded["dm_thread"],
        connection_id=seeded["connection"],
        message=message,
    )


def _stored(seeded: dict[str, UUID], mid: str):
    rows = PostgresConversationRepository().list_messages(
        tenant_id=TENANT, thread_id=seeded["dm_thread"], limit=500
    )
    [row] = [r for r in rows if r.external_message_id == mid]
    return row


def _story_reply(seeded: dict[str, UUID], *, hours_ago: float = 1) -> UUID:
    mid = f"mid-{uuid4().hex[:10]}"
    _insert(
        seeded,
        _remote(
            mid,
            posted_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            story_reply_id=f"179{uuid4().int % 10**12}",
            story_reply_url="https://cdn/story",
        ),
    )
    return _stored(seeded, mid).id


# --- 0075 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"story_reply_url": "https://cdn/x"},  # a URL without the story id
        {"story_reply_id": "1790", "direction": "outbound"},  # only inbound replies
    ],
)
def test_story_reply_checks(seeded: dict[str, UUID], overrides: dict[str, object]) -> None:
    values: dict[str, object] = dict(
        tenant_id=TENANT,
        thread_id=seeded["dm_thread"],
        connection_id=seeded["connection"],
        external_message_id=f"mid-{uuid4().hex[:10]}",
        direction="inbound",
        text="hola",
        shape_version="test",
    )
    values.update(overrides)
    with pytest.raises(IntegrityError) as exc, tenant_session(TENANT) as session:
        session.add(Message(**values))
        session.flush()
    assert isinstance(exc.value.orig, CheckViolation)


# --- the insert ------------------------------------------------------------------------------


def test_the_insert_keeps_the_story_and_a_later_reading_fills_it_once(seeded) -> None:
    mid = f"mid-{uuid4().hex[:10]}"
    assert _insert(seeded, _remote(mid)) is True
    assert _stored(seeded, mid).story_reply_id is None
    assert _insert(seeded, _remote(mid, story_reply_id="s1", story_reply_url="u1")) is False
    assert _insert(seeded, _remote(mid, story_reply_id="s2", story_reply_url="u2")) is False
    assert _insert(seeded, _remote(mid)) is False  # a replay without it changes nothing
    stored = _stored(seeded, mid)
    assert (stored.story_reply_id, stored.story_reply_url) == ("s1", "u1")
    with tenant_session(TENANT) as session:
        count = session.execute(
            text("SELECT count(*) FROM messages WHERE external_message_id = :m"), {"m": mid}
        ).scalar_one()
    assert count == 1


def test_a_new_story_reply_is_stored_with_its_story(seeded) -> None:
    mid = f"mid-{uuid4().hex[:10]}"
    assert _insert(seeded, _remote(mid, story_reply_id="s9", story_reply_url="u9")) is True
    assert _stored(seeded, mid).story_reply_id == "s9"


# --- readers ---------------------------------------------------------------------------------


def test_the_origin_reader_marks_a_story_reply(seeded) -> None:
    message_id = _story_reply(seeded)
    origin = PostgresOriginReader().get(tenant_id=TENANT, message_id=message_id)
    assert origin is not None and origin.is_story_reply
    assert origin.channel == "dm" and origin.story_reply_url == "https://cdn/story"
    plain = PostgresOriginReader().get(tenant_id=TENANT, message_id=seeded["story_reply"])
    assert plain is not None and plain.is_story_reply is False  # a DM without a story
    assert PostgresOriginReader().get(tenant_id=OTHER, message_id=message_id) is None


def _flag(seeded: dict[str, UUID], message_id: UUID) -> UUID:
    with tenant_session(TENANT) as session:
        row = CommentIntentResult(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            message_id=message_id,
            source_id="mid",
            detector_version=VERSION.detector_version,
            pipeline_version=VERSION.pipeline_version,
            model_id=VERSION.model_id,
            confidences={"price": 0.9},
            commercial_intent=True,
        )
        session.add(row)
        session.flush()
        return row.id


def test_the_commercial_reader_takes_story_replies_only_when_asked(seeded) -> None:
    recent = _story_reply(seeded, hours_ago=1)
    old = _story_reply(seeded, hours_ago=30)
    flags = {_flag(seeded, recent), _flag(seeded, old)}
    reader = PostgresCommercialIntentReader()
    now = datetime.now(UTC)

    def found(story_since: datetime | None) -> set[UUID]:
        rows = reader.unfollowed(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            version=VERSION,
            posted_since=now - timedelta(days=7),
            limit=100,
            story_replies_since=story_since,
        )
        return {r.message_id for r in rows if r.intent_result_id in flags}

    assert found(None) == set()
    assert found(now - timedelta(hours=24)) == {recent}


def test_the_intent_reader_lists_story_replies_only_when_asked(seeded) -> None:
    message_id = _story_reply(seeded)
    repo = PostgresIntentRepository()

    def pending(include: bool) -> set[UUID]:
        return {
            p.message_id
            for p in repo.list_pending_for_intent(
                tenant_id=TENANT,
                connection_id=seeded["connection"],
                version=VERSION,
                include_story_replies=include,
            )
        }

    assert message_id not in pending(False)
    with_stories = pending(True)
    assert message_id in with_stories
    assert seeded["comment"] in with_stories  # comments are still there
    assert seeded["story_reply"] not in with_stories  # a DM without a story is not
