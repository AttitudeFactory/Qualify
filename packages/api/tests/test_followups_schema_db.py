"""Migration 0071 (m-24789646, B7) checked as the REAL roles, then
`PostgresFollowupRepository` against it — same method as `test_conversations_schema_db.py`.

What this file pins:
- grants: `qualify_app` reads/inserts/updates and never deletes; the webhook worker, the
  admin and the credential role have nothing (a Meta delivery cannot open, approve or
  notice anything);
- the CHECKs: kinds/statuses, intent provenance, «approved» complete, a story reply admits
  neither a private reply nor a notice, «posted» carries Meta's id;
- one followup per interaction (UNIQUE `origin_message_id`);
- the composite FKs (a row whose tenant disagrees with its message/thread/outbox fails);
- RLS: another tenant reads nothing and cannot write under the wrong tenant;
- the repository: idempotent opening, approve/discard written back once.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    InsufficientPrivilege,
    UniqueViolation,
)
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import admin_dsn, app_dsn, credential_dsn, webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.models import ConversationOutboxItem
from qualify_api.followups import (
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    NoticeStatus,
    OriginKind,
    PostgresFollowupRepository,
    SendRoute,
    new_followup,
)
from qualify_api.followups.models import InteractionFollowup
from qualify_api.inbox.models import Message, Thread
from qualify_api.intent.models import CommentIntentResult
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000e1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000e2")
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)

_ROLE_DSNS = {
    "app": app_dsn,
    "admin": admin_dsn,
    "worker": webhook_worker_dsn,
    "credential": credential_dsn,
}
_INSERT = (
    "INSERT INTO interaction_followups (tenant_id, connection_id, origin_kind, "
    "origin_message_id, dm_thread_id, trigger, notice_status) SELECT gen_random_uuid(), "
    "gen_random_uuid(), 'comment', gen_random_uuid(), gen_random_uuid(), 'manual', "
    "'not_requested' WHERE false"
)


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, Engine]]:
    built = {name: create_engine(dsn()) for name, dsn in _ROLE_DSNS.items()}
    built["owner"] = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield built
    finally:
        for engine in built.values():
            engine.dispose()


def _attempt(engine: Engine, sql: str) -> str:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql))
            return "ok"
        except DBAPIError as exc:
            if isinstance(exc.orig, InsufficientPrivilege):
                return "denied"
            raise
        finally:
            trans.rollback()


# --- grants, per role ------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM interaction_followups LIMIT 1",
        _INSERT,
        "UPDATE interaction_followups SET status = status WHERE false",
    ],
)
def test_app_can_read_insert_update(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "ok"


def test_app_cannot_delete(engines) -> None:
    assert _attempt(engines["app"], "DELETE FROM interaction_followups WHERE false") == "denied"


@pytest.mark.parametrize("role", ["worker", "admin", "credential"])
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM interaction_followups LIMIT 1",
        _INSERT,
        "UPDATE interaction_followups SET status = status WHERE false",
    ],
)
def test_other_roles_have_nothing(engines, role: str, sql: str) -> None:
    assert _attempt(engines[role], sql) == "denied"


# --- rows --------------------------------------------------------------------------------


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """A comment with its intent analysis, the author's DM thread, a story reply and a
    queued send — everything a followup can point at, in TENANT."""
    with admin_session() as session:
        for tenant_id, name in ((TENANT, "followups"), (OTHER, "followups-other")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@followups.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    igsid = f"igsid-{uuid4().hex[:8]}"
    with tenant_session(TENANT) as session:
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4().hex[:12]}",
            linked_page_id="page-1",
            granted_scopes=["instagram_manage_comments"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        comment_thread = Thread(
            tenant_id=TENANT,
            connection_id=connection.id,
            channel="comment",
            external_thread_id=f"media-{uuid4().hex[:8]}",
            status="open",
        )
        dm_thread = Thread(
            tenant_id=TENANT,
            connection_id=connection.id,
            channel="dm",
            external_thread_id=igsid,
            status="open",
        )
        session.add_all([comment_thread, dm_thread])
        session.flush()
        comment = Message(
            tenant_id=TENANT,
            thread_id=comment_thread.id,
            connection_id=connection.id,
            external_message_id=f"c-{uuid4().hex[:10]}",
            direction="inbound",
            author_external_id=igsid,
            text="¿precio?",
            posted_at=NOW,
            shape_version="test",
        )
        story_reply = Message(
            tenant_id=TENANT,
            thread_id=dm_thread.id,
            connection_id=connection.id,
            external_message_id=f"mid-{uuid4().hex[:10]}",
            direction="inbound",
            author_external_id=igsid,
            text="¿lo tienen en azul?",
            posted_at=NOW,
            shape_version="test",
        )
        session.add_all([comment, story_reply])
        session.flush()
        intent = CommentIntentResult(
            tenant_id=TENANT,
            connection_id=connection.id,
            message_id=comment.id,
            source_id=comment.external_message_id,
            detector_version="d",
            pipeline_version="p",
            model_id="m",
            confidences={"price": 0.9},
            commercial_intent=True,
        )
        outbox = ConversationOutboxItem(
            tenant_id=TENANT,
            connection_id=connection.id,
            thread_id=dm_thread.id,
            channel="dm",
            kind="reply",
            payload={"recipient": {"id": igsid}, "message": {"text": "hola"}},
            approved_by_user_id=user_id,
            approved_at=NOW,
        )
        session.add_all([intent, outbox])
        session.flush()
        return {
            "connection": connection.id,
            "comment": comment.id,
            "story_reply": story_reply.id,
            "dm_thread": dm_thread.id,
            "intent": intent.id,
            "outbox": outbox.id,
            "user": user_id,
        }


def _row(seeded: dict[str, UUID], **overrides) -> InteractionFollowup:
    values = dict(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        origin_kind="comment",
        origin_message_id=seeded["comment"],
        dm_thread_id=seeded["dm_thread"],
        trigger="intent",
        intent_result_id=seeded["intent"],
        notice_status="not_requested",
    )
    values.update(overrides)
    return InteractionFollowup(**values)


def _approved(seeded: dict[str, UUID], **overrides) -> InteractionFollowup:
    values = dict(
        status="approved",
        send_route="private_reply",
        outbox_id=seeded["outbox"],
        decided_by_user_id=seeded["user"],
        decided_at=NOW,
    )
    values.update(overrides)
    return _row(seeded, **values)


def _expect(exc_type, row_factory, tenant_id: UUID = TENANT) -> None:
    with pytest.raises(IntegrityError) as exc, tenant_session(tenant_id) as session:
        session.add(row_factory())
        session.flush()
    assert isinstance(exc.value.orig, exc_type), type(exc.value.orig)


def _add(row: InteractionFollowup) -> None:
    with tenant_session(TENANT) as session:
        session.add(row)
        session.flush()


def test_valid_rows_are_accepted(seeded) -> None:
    _add(_approved(seeded, notice_status="pending", notice_text="Te enviamos la info por DM"))
    _add(
        _row(
            seeded,
            origin_kind="story_reply",
            origin_message_id=seeded["story_reply"],
            trigger="manual",
            intent_result_id=None,
            notice_status="not_applicable",
        )
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin_kind": "mention"},
        {"trigger": "webhook"},
        {"status": "sent"},  # delivery is the outbox's, never stored here
        {"send_route": "email"},
        {"notice_status": "queued"},
        {"notice_attempts": -1},
        # intent provenance: an intent row names its analysis, a manual one none
        {"intent_result_id": None},
        {"trigger": "manual"},
        # a story reply has no public comment for a notice
        {"origin_kind": "story_reply", "origin_message_id": None, "notice_status": "pending"},
        # «posted» ⇔ Meta's id of the public reply
        {"notice_status": "posted"},
        {"notice_external_id": "17890000000000001"},
        # a discarded followup says who discarded it and when
        {"status": "discarded"},
    ],
)
def test_checks(seeded, overrides) -> None:
    if overrides.get("origin_message_id", "") is None:
        overrides = {**overrides, "origin_message_id": seeded["story_reply"]}
    _expect(CheckViolation, lambda: _row(seeded, **overrides))


@pytest.mark.parametrize("missing", ["outbox_id", "send_route", "decided_by_user_id", "decided_at"])
def test_an_approved_row_is_complete(seeded, missing: str) -> None:
    _expect(CheckViolation, lambda: _approved(seeded, **{missing: None}))


def test_open_cannot_carry_a_decision(seeded) -> None:
    _expect(CheckViolation, lambda: _approved(seeded, status="open"))


def test_a_private_reply_answers_a_comment_only(seeded) -> None:
    _expect(
        CheckViolation,
        lambda: _approved(
            seeded,
            origin_kind="story_reply",
            origin_message_id=seeded["story_reply"],
            notice_status="not_applicable",
        ),
    )


def test_one_followup_per_interaction(seeded) -> None:
    _add(_row(seeded))
    _expect(UniqueViolation, lambda: _row(seeded, trigger="manual", intent_result_id=None))


@pytest.mark.parametrize("column", ["origin_message_id", "dm_thread_id", "intent_result_id"])
def test_pointers_must_exist(seeded, column: str) -> None:
    _expect(ForeignKeyViolation, lambda: _row(seeded, **{column: uuid4()}))


def test_outbox_must_exist(seeded) -> None:
    _expect(ForeignKeyViolation, lambda: _approved(seeded, outbox_id=uuid4()))


def test_a_row_under_another_tenant_fails_and_is_invisible(seeded) -> None:
    with pytest.raises(DBAPIError), tenant_session(OTHER) as session:
        session.add(_row(seeded, tenant_id=OTHER))
        session.flush()
    _add(_row(seeded))
    count = "SELECT count(*) FROM interaction_followups WHERE origin_message_id = :m"
    with tenant_session(OTHER) as session:
        assert session.execute(text(count), {"m": seeded["comment"]}).scalar_one() == 0
    with tenant_session(TENANT) as session:
        assert session.execute(text(count), {"m": seeded["comment"]}).scalar_one() == 1


# --- PostgresFollowupRepository --------------------------------------------------------


def _new(seeded: dict[str, UUID], trigger: FollowupTrigger = FollowupTrigger.INTENT):
    return new_followup(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        origin_kind=OriginKind.COMMENT,
        origin_message_id=seeded["comment"],
        dm_thread_id=seeded["dm_thread"],
        trigger=trigger,
        intent_result_id=seeded["intent"] if trigger is FollowupTrigger.INTENT else None,
        now=NOW,
    )


def test_repository_opens_once_per_interaction(seeded) -> None:
    repo = PostgresFollowupRepository()
    first = repo.open(_new(seeded))
    again = repo.open(_new(seeded, FollowupTrigger.MANUAL))
    assert first.created is True and again.created is False
    assert again.followup.id == first.followup.id
    assert again.followup.trigger is FollowupTrigger.INTENT
    assert first.followup.notice_status is NoticeStatus.NOT_REQUESTED
    assert repo.get_for_message(tenant_id=TENANT, origin_message_id=seeded["comment"]) == (
        first.followup
    )
    assert repo.get(tenant_id=OTHER, followup_id=first.followup.id) is None
    assert first.followup.id in {
        f.id for f in repo.list_open(tenant_id=TENANT, connection_id=seeded["connection"])
    }
    assert repo.list_open(tenant_id=OTHER) == []


def test_repository_approves_once_and_round_trips(seeded) -> None:
    repo = PostgresFollowupRepository()
    followup = repo.open(_new(seeded)).followup
    approved = repo.approve(
        tenant_id=TENANT,
        followup_id=followup.id,
        outbox_id=seeded["outbox"],
        send_route=SendRoute.PRIVATE_REPLY,
        decided_by_user_id=seeded["user"],
        now=NOW,
        notice_text="Te enviamos la información por DM 💬",
    )
    stored = repo.get(tenant_id=TENANT, followup_id=followup.id)
    assert stored is not None
    assert stored.status is FollowupStatus.APPROVED
    assert (stored.outbox_id, stored.send_route) == (seeded["outbox"], SendRoute.PRIVATE_REPLY)
    assert stored.notice_status is NoticeStatus.PENDING
    assert stored.notice_text == approved.notice_text
    assert followup.id not in {f.id for f in repo.list_open(tenant_id=TENANT)}
    with pytest.raises(InvalidFollowupTransition):
        repo.discard(
            tenant_id=TENANT, followup_id=followup.id, decided_by_user_id=seeded["user"], now=NOW
        )


def test_repository_discards(seeded) -> None:
    repo = PostgresFollowupRepository()
    followup = repo.open(_new(seeded, FollowupTrigger.MANUAL)).followup
    repo.discard(
        tenant_id=TENANT, followup_id=followup.id, decided_by_user_id=seeded["user"], now=NOW
    )
    stored = repo.get(tenant_id=TENANT, followup_id=followup.id)
    assert stored is not None and stored.status is FollowupStatus.DISCARDED
    assert stored.decided_by_user_id == seeded["user"]
