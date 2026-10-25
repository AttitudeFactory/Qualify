"""`db`-marked tests for `comment_intent_results` (migration 0069) and
`PostgresIntentRepository` (m-24789644, B3/B7): pending selection, idempotency per
version, tenant isolation, and the CHECKs that keep a row consistent with the
`IntentSignal` contract even when written by raw SQL.

Seeds its own disposable tenants/connections/comments, like
`test_sentiment_repository.py`. No cleanup: the table is append-only for every role
(0069 grants only SELECT/INSERT), and each test uses a fresh analysis version so tests
never consume each other's pending comments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.intent import IntentClass, IntentSignal, PostgresIntentRepository
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_I = UUID("e0000000-0000-4000-8000-0000000000a2")
TENANT_I2 = UUID("e0000000-0000-4000-8000-0000000000a3")


def _fresh_version(model_revision: str | None = None) -> AnalysisVersion:
    return AnalysisVersion(
        detector_version=f"intent-test-v1-{uuid4().hex[:8]}",
        pipeline_version="intent-test-pipeline-v1",
        model_id="test/intent-stub",
        model_revision=model_revision,
    )


def _signal(
    message_id: UUID,
    source_id: str,
    version: AnalysisVersion,
    classes: dict[str, float] | None = None,
) -> IntentSignal:
    return IntentSignal(
        comment_id=message_id,
        source_id=source_id,
        classes=classes or {"price": 0.9, "availability": 0.6},
        detector_version=version.detector_version,
        pipeline_version=version.pipeline_version,
        model_id=version.model_id,
        model_revision=version.model_revision,
    )


def _seed_connection(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"t-{tenant_id}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@i.co", display_name="U")
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
        return conn.id


def _seed_comment(
    tenant_id: UUID, connection_id: UUID, *, text_: str | None = "¿cuánto cuesta?"
) -> tuple[UUID, str]:
    """(message_id, source_id) of a new inbound comment on a new comment-channel thread."""
    now = datetime.now(UTC)
    source_id = f"comment-{uuid4()}"
    with tenant_session(tenant_id) as session:
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
            last_message_at=now,
        )
        session.add(thread)
        session.flush()
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            text=text_,
            posted_at=now,
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        return message.id, source_id


def _soft_delete(tenant_id: UUID, message_id: UUID) -> None:
    with tenant_session(tenant_id) as session:
        message = session.get(Message, message_id)
        assert message is not None
        message.deleted_at = datetime.now(UTC)
        session.flush()


def _pending_ids(connection_id: UUID, version: AnalysisVersion) -> set[UUID]:
    pending = PostgresIntentRepository().list_pending_for_intent(
        tenant_id=TENANT_I, connection_id=connection_id, version=version
    )
    return {p.message_id for p in pending}


def test_pending_lists_analyzable_comments_only() -> None:
    connection_id = _seed_connection(TENANT_I)
    analyzable, _ = _seed_comment(TENANT_I, connection_id)
    without_text, _ = _seed_comment(TENANT_I, connection_id, text_=None)
    deleted, _ = _seed_comment(TENANT_I, connection_id)
    _soft_delete(TENANT_I, deleted)

    assert _pending_ids(connection_id, _fresh_version()) == {analyzable}


def test_recorded_signal_round_trips_and_leaves_pending() -> None:
    connection_id = _seed_connection(TENANT_I)
    message_id, source_id = _seed_comment(TENANT_I, connection_id)
    version = _fresh_version()
    signal = _signal(message_id, source_id, version)
    repo = PostgresIntentRepository()

    assert repo.record_intent_result(tenant_id=TENANT_I, connection_id=connection_id, signal=signal)
    assert _pending_ids(connection_id, version) == set()
    assert repo.get_signals(tenant_id=TENANT_I, message_ids=[message_id], version=version) == {
        message_id: signal
    }


@pytest.mark.parametrize("model_revision", [None, "rev-1"])
def test_recording_the_same_version_twice_is_idempotent(model_revision: str | None) -> None:
    connection_id = _seed_connection(TENANT_I)
    message_id, source_id = _seed_comment(TENANT_I, connection_id)
    version = _fresh_version(model_revision)
    signal = _signal(message_id, source_id, version)
    repo = PostgresIntentRepository()

    assert repo.record_intent_result(tenant_id=TENANT_I, connection_id=connection_id, signal=signal)
    assert not repo.record_intent_result(
        tenant_id=TENANT_I, connection_id=connection_id, signal=signal
    )
    with tenant_session(TENANT_I) as session:
        count = session.execute(
            text("SELECT count(*) FROM comment_intent_results WHERE message_id = :m"),
            {"m": message_id},
        ).scalar_one()
    assert count == 1


def test_a_new_version_adds_a_row_and_keeps_the_old_one() -> None:
    connection_id = _seed_connection(TENANT_I)
    message_id, source_id = _seed_comment(TENANT_I, connection_id)
    v1, v2 = _fresh_version(), _fresh_version("rev-2")
    repo = PostgresIntentRepository()
    repo.record_intent_result(
        tenant_id=TENANT_I, connection_id=connection_id, signal=_signal(message_id, source_id, v1)
    )

    assert _pending_ids(connection_id, v2) == {message_id}
    repo.record_intent_result(
        tenant_id=TENANT_I, connection_id=connection_id, signal=_signal(message_id, source_id, v2)
    )
    assert message_id in repo.get_signals(tenant_id=TENANT_I, message_ids=[message_id], version=v1)
    assert message_id in repo.get_signals(tenant_id=TENANT_I, message_ids=[message_id], version=v2)


def test_every_intent_class_is_accepted_by_the_table() -> None:
    """Guards the class list frozen in 0069 against drifting from `IntentClass`."""
    connection_id = _seed_connection(TENANT_I)
    version = _fresh_version()
    repo = PostgresIntentRepository()
    for intent_class in IntentClass:
        message_id, source_id = _seed_comment(TENANT_I, connection_id)
        signal = _signal(message_id, source_id, version, classes={intent_class.value: 0.8})
        assert repo.record_intent_result(
            tenant_id=TENANT_I, connection_id=connection_id, signal=signal
        )


def test_tenant_isolation_another_tenant_cannot_read_a_signal() -> None:
    connection_a = _seed_connection(TENANT_I)
    message_a, source_a = _seed_comment(TENANT_I, connection_a)
    version = _fresh_version()
    repo = PostgresIntentRepository()
    repo.record_intent_result(
        tenant_id=TENANT_I, connection_id=connection_a, signal=_signal(message_a, source_a, version)
    )
    _seed_connection(TENANT_I2)

    assert repo.get_signals(tenant_id=TENANT_I2, message_ids=[message_a], version=version) == {}
    with tenant_session(TENANT_I2) as session:
        visible = session.execute(
            text("SELECT count(*) FROM comment_intent_results WHERE message_id = :m"),
            {"m": message_a},
        ).scalar_one()
    assert visible == 0


def test_a_tenant_cannot_record_a_signal_on_another_tenants_comment() -> None:
    connection_a = _seed_connection(TENANT_I)
    message_a, source_a = _seed_comment(TENANT_I, connection_a)
    connection_b = _seed_connection(TENANT_I2)

    # The composite FK (message_id, tenant_id) has no matching message for TENANT_I2.
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_I2) as session:
            session.execute(
                text(
                    "INSERT INTO comment_intent_results (tenant_id, connection_id, message_id,"
                    " source_id, detector_version, pipeline_version, model_id, confidences,"
                    " commercial_intent) VALUES (:t, :c, :m, :s, 'd', 'p', 'm',"
                    " '{\"price\": 0.9}', true)"
                ),
                {"t": TENANT_I2, "c": connection_b, "m": message_a, "s": source_a},
            )


@pytest.mark.parametrize(
    ("confidences", "commercial_intent"),
    [
        ("{}", False),  # no class at all
        ('{"discount": 0.9}', True),  # unknown class
        ('{"general": 0.6, "price": 0.5}', True),  # general combined with a commercial one
        ('{"price": 0.9}', False),  # flag disagrees with the classes
        ('{"general": 0.9}', True),  # flag disagrees with the classes
    ],
)
def test_checks_reject_rows_that_contradict_the_contract(
    confidences: str, commercial_intent: bool
) -> None:
    connection_id = _seed_connection(TENANT_I)
    message_id, source_id = _seed_comment(TENANT_I, connection_id)

    with pytest.raises(IntegrityError, match="ck_comment_intent_"):
        with tenant_session(TENANT_I) as session:
            session.execute(
                text(
                    "INSERT INTO comment_intent_results (tenant_id, connection_id, message_id,"
                    " source_id, detector_version, pipeline_version, model_id, confidences,"
                    " commercial_intent) VALUES (:t, :c, :m, :s, 'd', 'p', 'm',"
                    " CAST(:conf AS jsonb), :ci)"
                ),
                {
                    "t": TENANT_I,
                    "c": connection_id,
                    "m": message_id,
                    "s": source_id,
                    "conf": confidences,
                    "ci": commercial_intent,
                },
            )


def test_rows_cannot_be_updated_or_deleted_by_the_app_role() -> None:
    connection_id = _seed_connection(TENANT_I)
    message_id, source_id = _seed_comment(TENANT_I, connection_id)
    PostgresIntentRepository().record_intent_result(
        tenant_id=TENANT_I,
        connection_id=connection_id,
        signal=_signal(message_id, source_id, _fresh_version()),
    )

    for statement in (
        "UPDATE comment_intent_results SET model_id = 'x' WHERE message_id = :m",
        "DELETE FROM comment_intent_results WHERE message_id = :m",
    ):
        with pytest.raises(Exception, match="permission denied"):
            with tenant_session(TENANT_I) as session:
                session.execute(text(statement), {"m": message_id})


def test_a_bounded_pending_read_takes_the_newest_comments_first() -> None:
    """m-24852204: the automatic pass takes `limit` comments per connection; the newest
    go first so a backlog never delays what just arrived."""
    connection_id = _seed_connection(TENANT_I)
    seeded = [_seed_comment(TENANT_I, connection_id)[0] for _ in range(3)]
    version = _fresh_version()
    pending = PostgresIntentRepository().list_pending_for_intent(
        tenant_id=TENANT_I, connection_id=connection_id, version=version, limit=2
    )
    assert [p.message_id for p in pending] == [seeded[2], seeded[1]]
