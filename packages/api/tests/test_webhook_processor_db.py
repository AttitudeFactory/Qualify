"""Webhook delivery -> intake log -> processor -> `mentions`, against real Postgres
(QUA-147). Real receiver (`qualify_webhook`), real queue and resolution
(`qualify_webhook_worker`), real `ingest_mention` (tenant_session); only the Meta
content client is faked (`_content_client_for`), as in `test_mentions_composition.py`.

The processor claims with the real clock, so it may also pick up live `pending` rows
other tests left behind; every assertion is about this test's own account and rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import MentionedMedia
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions import composition
from qualify_api.mentions.resolve import PLATFORM_INSTAGRAM, resolve_external_account
from qualify_api.tenancy.models import Tenant, User
from qualify_api.webhooks.processor import Processor, mentions_handler
from qualify_api.webhooks.receiver import record_delivery
from qualify_api.webhooks.repository import WebhookQueue

pytestmark = pytest.mark.db

TENANT = UUID("a1470000-0000-4000-8000-000000000147")


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_connection(external_account_id: str) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="qua147-webhooks",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(TENANT) as session:
        conn = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform=PLATFORM_INSTAGRAM,
            account_type="business",
            external_account_id=external_account_id,
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


class FakeContentClient:
    def __init__(self) -> None:
        self.media_calls: list[str] = []

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia:
        self.media_calls.append(media_id)
        return MentionedMedia(
            id=media_id,
            caption="hola @marca",
            media_type="IMAGE",
            like_count=3,
            timestamp=datetime(2026, 10, 1, tzinfo=UTC),
            username="fan",
        )

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None:
        return None


@pytest.fixture
def fake_meta(monkeypatch: pytest.MonkeyPatch) -> FakeContentClient:
    client = FakeContentClient()

    async def fake_content_client_for(*, tenant_id: UUID, connection_id: UUID):
        return client, "ig-own-user"

    monkeypatch.setattr(composition, "_content_client_for", fake_content_client_for)
    return client


def _processor() -> Processor:
    return Processor(
        queue=WebhookQueue(),
        handlers={
            "mentions": mentions_handler(
                resolve=resolve_external_account, ingest=composition.ingest_mention
            )
        },
        worker_id=f"test-{uuid4()}",
    )


def _body(account: str, field: str, value: dict) -> bytes:
    return json.dumps(
        {
            "object": "instagram",
            "entry": [{"id": account, "changes": [{"field": field, "value": value}]}],
        }
    ).encode()


def _event_status(owner: Engine, account: str, field: str) -> list[tuple[str, str | None]]:
    with owner.connect() as conn:
        return [
            (r.status, r.last_error)
            for r in conn.execute(
                text(
                    "SELECT status, last_error FROM meta_webhook_events "
                    "WHERE entry_id = :e AND field = :f"
                ),
                {"e": account, "f": field},
            )
        ]


def _mentions(owner: Engine, connection_id: UUID, media_id: str) -> list:
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT * FROM mentions WHERE connection_id = :c AND media_id = :m"),
            {"c": connection_id, "m": media_id},
        ).all()


async def test_a_recorded_mention_is_processed_into_the_tenants_mentions(owner, fake_meta) -> None:
    account = f"ig-{uuid4()}"
    connection_id = _seed_connection(account)
    media_id = f"media-{uuid4()}"
    record_delivery(body=_body(account, "mentions", {"media_id": media_id}), signature_header="s")

    await _processor().run_once(limit=1000)

    assert _event_status(owner, account, "mentions") == [("processed", None)]
    [mention] = _mentions(owner, connection_id, media_id)
    assert (mention.tenant_id, mention.caption, mention.enrichment_status) == (
        TENANT,
        "hola @marca",
        "ENRICHED",
    )
    assert fake_meta.media_calls == [media_id]


async def test_replaying_a_processed_change_never_duplicates_the_mention(owner, fake_meta) -> None:
    """Crash-after-write: the change is reclaimed and handled again. The mention's own
    natural key makes the replay a no-op."""
    account = f"ig-{uuid4()}"
    connection_id = _seed_connection(account)
    media_id = f"media-{uuid4()}"
    record_delivery(body=_body(account, "mentions", {"media_id": media_id}), signature_header="s")
    await _processor().run_once(limit=1000)

    with owner.begin() as conn:  # simulate the lost settlement
        conn.execute(
            text(
                "UPDATE meta_webhook_events SET status = 'pending', processed_at = NULL "
                "WHERE entry_id = :e"
            ),
            {"e": account},
        )
    await _processor().run_once(limit=1000)

    assert _event_status(owner, account, "mentions") == [("processed", None)]
    assert len(_mentions(owner, connection_id, media_id)) == 1


async def test_an_unknown_account_is_orphan_and_writes_no_mention(owner, fake_meta) -> None:
    account = f"ig-unknown-{uuid4()}"
    media_id = f"media-{uuid4()}"
    record_delivery(body=_body(account, "mentions", {"media_id": media_id}), signature_header="s")

    await _processor().run_once(limit=1000)

    assert _event_status(owner, account, "mentions") == [("orphan", None)]
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM mentions WHERE media_id = :m"), {"m": media_id}
            ).scalar()
            == 0
        )
    assert fake_meta.media_calls == []


async def test_a_comments_change_is_kept_as_unsupported(owner, fake_meta) -> None:
    account = f"ig-{uuid4()}"
    _seed_connection(account)
    record_delivery(
        body=_body(account, "comments", {"id": f"c-{uuid4()}", "text": "precio?"}),
        signature_header="s",
    )

    await _processor().run_once(limit=1000)

    assert _event_status(owner, account, "comments") == [("unsupported", None)]
    assert fake_meta.media_calls == []
