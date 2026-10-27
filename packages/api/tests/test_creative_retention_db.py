"""`db` tests for piece retention (m-24828907, migration 0076): the facts read through
RLS, the purge against a recording gate (dry run and real), the purge log's isolation and
append-only grants, and the production tenant discovery.

Provisioning through `admin_session`; everything under test through `tenant_session`.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import models as creative
from qualify_api.creative.models import (
    ContentDraft,
    ContentDraftPurgeWarning,
    ContentDraftWarningBatch,
    ImageAsset,
)
from qualify_api.creative.pieces import DbPieceFiles
from qualify_api.creative.retention import (
    RETENTION,
    RetentionState,
    piece_prefix,
    purge_expired_pieces,
    read_facts,
    retention_of,
    tenants_with_expired_pieces,
)
from qualify_api.creative.retention_job import run_piece_purge
from qualify_api.creative.retention_mail import (
    retry_tenant_warnings,
    send_tenant_warnings,
    warning_review_ids,
)
from qualify_api.mail import FakeMailer, MailError, MailRejected, OutgoingMail, ResendMailer
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.post_reader import NotPublishable, UnpublishableReason
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db

# Distinct from every other schema-test module's tenants.
TENANT_A = UUID("a0000000-0000-4000-8000-000000000907")
TENANT_B = UUID("b0000000-0000-4000-8000-000000000907")
NOW = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)


def _provision(tenant_id: UUID, name: str) -> tuple[UUID, UUID, UUID]:
    """(brand_id, user_id, connection_id), idempotent for the tenant and brand."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        brand = session.scalar(select(Brand).where(Brand.tenant_id == tenant_id))
        if brand is None:
            brand = Brand(tenant_id=tenant_id, name=f"retention-{name}")
            session.add(brand)
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"r-{uuid4()}@a.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        brand_id, app_id, user_id = brand.id, app.id, user.id
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
        return brand_id, user_id, conn.id


def _piece(
    tenant_id: UUID, brand_id: UUID, *, generated_days_ago: float | None, r2: bool = True
) -> UUID:
    """A draft with one image generated `generated_days_ago` days before NOW (no image
    at all with None), in R2 or in the legacy local store."""
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="Retención",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="promotion",
            image_route="template_only",
        )
        session.add(brief)
        session.flush()
        draft = creative.ContentDraft(
            tenant_id=tenant_id,
            brief_id=brief.id,
            brand_id=brand_id,
            status="approved",
            pipeline_version="test",
            category="galeria",
            revision=2,
            approved_revision=2,
        )
        session.add(draft)
        session.flush()
        if generated_days_ago is not None:
            key = (
                f"{piece_prefix(tenant_id, draft.id)}r2/a.jpg"
                if r2
                else f"generated/{tenant_id}/{draft.id}/a.jpg"
            )
            session.add(
                creative.ImageAsset(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    media_url=key,
                    object_key=key,
                    content_type="image/jpeg",
                    created_at=NOW - timedelta(days=generated_days_ago),
                )
            )
        return draft.id


def _event(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    connection_id: UUID,
    post_id: UUID,
    *,
    status: str,
    days_from_now: float,
) -> None:
    with tenant_session(tenant_id) as session:
        session.add(
            CalendarEvent(
                tenant_id=tenant_id,
                brand_id=brand_id,
                post_id=post_id,
                connection_id=connection_id,
                scheduled_at=NOW + timedelta(days=days_from_now),
                scheduled_tz="America/Bogota",
                status=status,
                destination="post",
                created_by_user_id=user_id,
            )
        )


class RecordingGate:
    """Stands in for `ObjectGate.delete_prefix`: a fixed listing per prefix, every call
    recorded, optional failure for one prefix."""

    def __init__(self, sizes: dict[str, list[int]] | None = None, fail: str = "") -> None:
        self.sizes = sizes or {}
        self.fail = fail
        self.calls: list[tuple[UUID, str, bool]] = []

    def delete_prefix(self, tenant_id: UUID, prefix: str, *, execute: bool = False) -> object:
        self.calls.append((tenant_id, prefix, execute))
        if prefix == self.fail:
            raise RuntimeError("R2 down")
        found = self.sizes.get(prefix, [])

        class _Found:
            objects = len(found)
            bytes = sum(found)

        if execute:
            self.sizes[prefix] = []
        return _Found()


def _purged_at(tenant_id: UUID, draft_id: UUID) -> datetime | None:
    with tenant_session(tenant_id) as session:
        return session.get(creative.ContentDraft, draft_id).media_purged_at


def _log(tenant_id: UUID, draft_id: UUID) -> list[creative.ContentDraftPurge]:
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(creative.ContentDraftPurge)
            .where(creative.ContentDraftPurge.draft_id == draft_id)
            .order_by(creative.ContentDraftPurge.purged_at)
        ).all()
        session.expunge_all()
        return list(rows)


# -- facts ---------------------------------------------------------------------------------


def test_facts_read_the_newest_r2_file_and_the_extending_events() -> None:
    brand, user, conn = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=100)
    _event(TENANT_A, brand, user, conn, draft, status="published", days_from_now=-40)
    _event(TENANT_A, brand, user, conn, draft, status="failed", days_from_now=-5)
    _event(TENANT_A, brand, user, conn, draft, status="cancelled", days_from_now=10)
    with tenant_session(TENANT_A) as session:
        facts = read_facts(session, TENANT_A, [draft])[draft]
    assert facts.generated_at == NOW - timedelta(days=100)
    assert facts.last_event_at == NOW - timedelta(days=40)  # failed/cancelled do not count
    assert facts.held is False and facts.purged_at is None


def test_a_scheduled_event_holds_the_piece() -> None:
    brand, user, conn = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=200)
    _event(TENANT_A, brand, user, conn, draft, status="scheduled", days_from_now=-120)
    with tenant_session(TENANT_A) as session:
        verdict = retention_of(session, TENANT_A, [draft], NOW)[draft]
    assert verdict.state is RetentionState.HELD


def test_a_legacy_local_piece_and_a_piece_without_files_are_out_of_scope() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    legacy = _piece(TENANT_A, brand, generated_days_ago=200, r2=False)
    empty = _piece(TENANT_A, brand, generated_days_ago=None)
    with tenant_session(TENANT_A) as session:
        assert retention_of(session, TENANT_A, [legacy, empty], NOW) == {}


def test_another_tenant_reads_no_facts() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    _provision(TENANT_B, "B")
    draft = _piece(TENANT_A, brand, generated_days_ago=100)
    with tenant_session(TENANT_B) as session:
        assert read_facts(session, TENANT_B, [draft]) == {}


# -- the purge -----------------------------------------------------------------------------


def test_a_dry_run_logs_once_and_marks_nothing() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=95)
    prefix = piece_prefix(TENANT_A, draft)
    gate = RecordingGate({prefix: [10, 20]})
    for _ in range(2):
        report = purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=False)
        assert draft in {piece.draft_id for piece in report.purged}
    assert _purged_at(TENANT_A, draft) is None
    log = _log(TENANT_A, draft)
    assert len(log) == 1  # the second dry run did not log the same piece again
    assert (log[0].object_count, log[0].byte_count, log[0].dry_run) == (2, 30, True)
    assert log[0].prefix == prefix
    assert log[0].expired_at == NOW - timedelta(days=95) + RETENTION
    assert all(execute is False for _, _, execute in gate.calls)


def test_a_real_purge_deletes_logs_and_marks_and_is_idempotent() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=91)
    prefix = piece_prefix(TENANT_A, draft)
    gate = RecordingGate({prefix: [5, 5, 5]})
    report = purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    assert (TENANT_A, prefix, True) in gate.calls
    assert report.executed and draft in {piece.draft_id for piece in report.purged}
    assert _purged_at(TENANT_A, draft) == NOW
    assert [(row.object_count, row.dry_run) for row in _log(TENANT_A, draft)] == [(3, False)]
    with tenant_session(TENANT_A) as session:
        assert retention_of(session, TENANT_A, [draft], NOW)[draft].is_purged

    gate.calls.clear()
    again = purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    assert draft not in {piece.draft_id for piece in again.purged}
    assert all(call[1] != prefix for call in gate.calls)


def test_the_purge_spares_recent_held_and_republished_pieces() -> None:
    brand, user, conn = _provision(TENANT_A, "A")
    recent = _piece(TENANT_A, brand, generated_days_ago=60)
    held = _piece(TENANT_A, brand, generated_days_ago=200)
    _event(TENANT_A, brand, user, conn, held, status="publishing", days_from_now=-1)
    republished = _piece(TENANT_A, brand, generated_days_ago=200)
    _event(TENANT_A, brand, user, conn, republished, status="published", days_from_now=-30)
    gate = RecordingGate()
    purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    touched = {prefix for _, prefix, _ in gate.calls}
    for draft in (recent, held, republished):
        assert piece_prefix(TENANT_A, draft) not in touched
        assert _purged_at(TENANT_A, draft) is None


def test_a_failing_piece_is_not_marked_and_does_not_stop_the_others() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    broken = _piece(TENANT_A, brand, generated_days_ago=300)
    fine = _piece(TENANT_A, brand, generated_days_ago=299)
    gate = RecordingGate(fail=piece_prefix(TENANT_A, broken))
    report = purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    assert (broken, "RuntimeError") in report.errors
    assert _purged_at(TENANT_A, broken) is None and _log(TENANT_A, broken) == []
    assert _purged_at(TENANT_A, fine) == NOW


def test_the_purge_never_reaches_another_tenants_piece() -> None:
    brand_b, _, _ = _provision(TENANT_B, "B")
    _provision(TENANT_A, "A")
    foreign = _piece(TENANT_B, brand_b, generated_days_ago=300)
    gate = RecordingGate()
    purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    assert all(tenant == TENANT_A for tenant, _, _ in gate.calls)
    assert piece_prefix(TENANT_B, foreign) not in {prefix for _, prefix, _ in gate.calls}
    assert _purged_at(TENANT_B, foreign) is None


def test_discovery_lists_only_tenants_with_expired_pieces() -> None:
    brand_a, _, _ = _provision(TENANT_A, "A")
    _piece(TENANT_A, brand_a, generated_days_ago=120)
    found = tenants_with_expired_pieces(NOW)
    assert TENANT_A in found
    assert tenants_with_expired_pieces(NOW - timedelta(days=10_000)) == []


def test_the_job_purges_exactly_its_scope() -> None:
    brand_a, _, _ = _provision(TENANT_A, "A")
    brand_b, _, _ = _provision(TENANT_B, "B")
    mine = _piece(TENANT_A, brand_a, generated_days_ago=150)
    theirs = _piece(TENANT_B, brand_b, generated_days_ago=150)
    gate = RecordingGate()
    reports = run_piece_purge([TENANT_A], execute=True, now=NOW, gate=gate)
    assert [report.tenant_id for report in reports] == [TENANT_A]
    assert _purged_at(TENANT_A, mine) == NOW
    assert _purged_at(TENANT_B, theirs) is None


def _approve(tenant_id: UUID, draft_id: UUID) -> None:
    """Give the piece a selected copy variant, so only the purge can block it."""
    with tenant_session(tenant_id) as session:
        variant = creative.CopyVariant(
            tenant_id=tenant_id,
            draft_id=draft_id,
            ordinal=0,
            copy={"hook": "¡Nuevo!", "caption": "Sabor", "cta": "Pide ya"},
            model_id="test",
        )
        session.add(variant)
        session.flush()
        session.get(creative.ContentDraft, draft_id).selected_variant_id = variant.id


def test_a_purged_piece_reads_as_purged_unpublishable_and_without_media() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=95)
    _approve(TENANT_A, draft)
    reader = DraftPostReader(clock=lambda: NOW)

    before = reader.get(tenant_id=TENANT_A, post_id=draft)
    assert before is not None and before.is_publishable
    assert before.retention_state == "expired" and before.thumbnail_url

    purge_expired_pieces(tenant_id=TENANT_A, gate=RecordingGate(), now=NOW, execute=True)

    after = reader.get(tenant_id=TENANT_A, post_id=draft)
    assert after is not None
    assert after.retention_state == "purged"
    assert not after.is_publishable and after.thumbnail_url is None
    verdict = reader.get_publishable(tenant_id=TENANT_A, post_id=draft)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.MEDIA_PURGED


def test_a_warned_piece_carries_its_deadline_and_countdown() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=80)
    summary = DraftPostReader(clock=lambda: NOW).get(tenant_id=TENANT_A, post_id=draft)
    assert summary is not None
    assert summary.retention_state == "warning" and summary.purge_days_left == 10
    assert summary.purge_deadline == (NOW + timedelta(days=10)).isoformat()


def test_the_pieces_picker_no_longer_offers_a_purged_piece() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    draft = _piece(TENANT_A, brand, generated_days_ago=95)
    key = f"{piece_prefix(TENANT_A, draft)}r2/a.jpg"
    files = DbPieceFiles()
    assert files.file(tenant_id=TENANT_A, brand_id=brand, object_key=key) is not None
    purge_expired_pieces(tenant_id=TENANT_A, gate=RecordingGate(), now=NOW, execute=True)
    assert files.file(tenant_id=TENANT_A, brand_id=brand, object_key=key) is None
    listed = files.files(tenant_id=TENANT_A, brand_id=brand, limit=500)
    assert key not in {piece.object_key for piece in listed}


# -- the log's grants and isolation (0076) -------------------------------------------------


def test_the_purge_log_is_append_only_for_the_app_role() -> None:
    for statement in (
        "UPDATE content_draft_purges SET object_count = 0 WHERE false",
        "DELETE FROM content_draft_purges WHERE false",
    ):
        with pytest.raises(DBAPIError) as exc:
            with tenant_session(TENANT_A) as session:
                session.execute(text(statement))
        assert "permission denied" in str(exc.value).lower()


def test_the_purge_log_is_isolated_by_tenant_and_by_the_nullif() -> None:
    brand, _, _ = _provision(TENANT_A, "A")
    _provision(TENANT_B, "B")
    draft = _piece(TENANT_A, brand, generated_days_ago=95)
    purge_expired_pieces(
        tenant_id=TENANT_A,
        gate=RecordingGate({piece_prefix(TENANT_A, draft): [1]}),
        now=NOW,
        execute=False,
    )
    with tenant_session(TENANT_B) as session:
        assert session.scalars(select(creative.ContentDraftPurge)).all() == []
    with tenant_session(TENANT_A) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert session.scalar(text("SELECT count(*) FROM content_draft_purges")) == 0
    with pytest.raises(DBAPIError):
        with tenant_session(TENANT_B) as session:
            session.add(
                creative.ContentDraftPurge(
                    tenant_id=TENANT_A,
                    draft_id=draft,
                    prefix="x/",
                    object_count=0,
                    byte_count=0,
                    dry_run=True,
                    expired_at=NOW,
                )
            )


def test_warning_once_per_deadline_grouped_and_isolated_with_retry() -> None:
    tenant_a, tenant_b = uuid4(), uuid4()
    brand, user, connection = _provision(tenant_a, "warning-A")
    other_brand, _, _ = _provision(tenant_b, "warning-B")
    foreign_piece = _piece(tenant_b, other_brand, generated_days_ago=80)
    auth_id = uuid4()
    with tenant_session(tenant_a) as session:
        session.execute(update(User).where(User.id == user).values(auth_user_id=auth_id))
        session.add(TenantMember(tenant_id=tenant_a, user_id=user, role="owner"))
    first = _piece(tenant_a, brand, generated_days_ago=80)
    second = _piece(tenant_a, brand, generated_days_ago=75)
    held = _piece(tenant_a, brand, generated_days_ago=80)
    _piece(tenant_a, brand, generated_days_ago=50)
    _piece(tenant_a, brand, generated_days_ago=90)
    with tenant_session(tenant_a) as session:
        session.add(
            CalendarEvent(
                tenant_id=tenant_a,
                brand_id=brand,
                scheduled_tz="UTC",
                post_id=held,
                connection_id=connection,
                scheduled_at=NOW - timedelta(days=1),
                status="scheduled",
                created_by_user_id=user,
            )
        )
    mailer = FakeMailer()

    def verify(uid, email):
        return email if uid == auth_id else None

    assert (
        send_tenant_warnings(tenant_a, NOW, mailer=mailer, verify=verify, draft_ids=[foreign_piece])
        == 0
    )
    assert mailer.sent == []
    assert send_tenant_warnings(tenant_a, NOW, mailer=mailer, verify=verify) == 1
    assert "Los archivos de estas 2 piezas" in mailer.sent[0].text
    assert (
        send_tenant_warnings(tenant_a, NOW + timedelta(days=1), mailer=mailer, verify=verify) == 0
    )
    with tenant_session(tenant_a) as session:
        rows = session.scalars(
            select(ContentDraftPurgeWarning).where(
                ContentDraftPurgeWarning.draft_id.in_([first, second])
            )
        ).all()
        assert len(rows) == 2
        warning_id = rows[0].id
    with tenant_session(tenant_b) as session:
        assert session.get(ContentDraftPurgeWarning, warning_id) is None
    with pytest.raises(DBAPIError), tenant_session(tenant_b) as session:
        session.add(
            ContentDraftPurgeWarning(
                tenant_id=tenant_a,
                draft_id=first,
                recipient="forbidden@example.test",
                stage="window_15d",
                deadline=NOW,
                notified_at=NOW,
            )
        )
        session.flush()
    # A second independent warning is sent only during the last 24 hours.
    last_day = NOW + timedelta(days=9, hours=12)
    assert send_tenant_warnings(tenant_a, last_day, mailer=mailer, verify=verify) == 1
    assert "24 horas" in mailer.sent[-1].text
    assert send_tenant_warnings(tenant_a, last_day, mailer=mailer, verify=verify) == 0
    with tenant_session(tenant_a) as session:
        stages = session.scalars(
            select(ContentDraftPurgeWarning.stage).where(ContentDraftPurgeWarning.draft_id == first)
        ).all()
        assert set(stages) == {"window_15d", "last_day"}
    # New generation extends the deadline; first daily pass sees it active, then warns again.
    with tenant_session(tenant_a) as session:
        session.execute(
            update(ImageAsset).where(ImageAsset.draft_id == first).values(created_at=NOW)
        )

    class FailingMailer:
        def send(self, mail):
            raise MailError("offline failure")

    later = NOW + timedelta(days=75)
    assert send_tenant_warnings(tenant_a, later, mailer=FailingMailer(), verify=verify) == 0
    assert send_tenant_warnings(tenant_a, later, mailer=mailer, verify=verify) == 1
    assert send_tenant_warnings(tenant_a, later, mailer=mailer, verify=verify) == 0


class _FailingWarningMailer:
    def send(self, mail: OutgoingMail) -> str | None:
        raise MailError("offline transport failure")


def _warning_account() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    tenant = uuid4()
    brand, user, connection = _provision(tenant, "frozen-warning")
    auth_id = uuid4()
    with tenant_session(tenant) as session:
        session.execute(update(User).where(User.id == user).values(auth_user_id=auth_id))
        session.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    return tenant, brand, user, connection, auth_id


def test_warning_retry_after_unknown_acceptance_keeps_frozen_http_body_and_key(monkeypatch) -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    first = _piece(tenant, brand, generated_days_ago=80)
    with tenant_session(tenant) as session:
        session.execute(
            update(ContentDraft).where(ContentDraft.id == first).values(title="First piece")
        )
    requests = []
    accepted = {}

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    def post(url: str, **kwargs):
        key = kwargs["headers"]["Idempotency-Key"]
        requests.append(deepcopy(kwargs))
        # Another transaction can see the batch before the first HTTP request.
        with tenant_session(tenant) as session:
            staged = session.scalar(
                select(ContentDraftWarningBatch).where(
                    ContentDraftWarningBatch.idempotency_key == key
                )
            )
            assert staged is not None and staged.sent_at is None
            expected_first = NOW if len(requests) <= 2 else NOW + timedelta(days=1)
            assert staged.first_attempt_at == expected_first
            assert staged.payload["mail"]["html"] == kwargs["json"]["html"]
        if len(requests) == 1:
            accepted[key] = kwargs["json"]
            raise httpx.ReadTimeout(
                "provider accepted; response lost", request=httpx.Request("POST", url)
            )
        if key in accepted:
            assert kwargs["json"] == accepted[key]
        else:
            accepted[key] = kwargs["json"]
        return httpx.Response(200, json={"id": "provider-" + key})

    monkeypatch.setattr("qualify_api.mail.httpx.post", post)
    monkeypatch.setenv("QUALIFY_PUBLIC_URL", "https://original.example.test")
    assert (
        send_tenant_warnings(
            tenant, NOW, mailer=ResendMailer("fake", "from@example.test"), verify=verify
        )
        == 0
    )
    second = _piece(tenant, brand, generated_days_ago=75)
    with tenant_session(tenant) as session:
        session.execute(
            update(ContentDraft).where(ContentDraft.id == second).values(title="New piece B")
        )
        session.execute(
            update(ContentDraft).where(ContentDraft.id == first).values(title="Changed title A")
        )
    monkeypatch.setenv("QUALIFY_PUBLIC_URL", "https://changed.example.test")
    # Recreate the client, like a worker restart; only the database retains the retry.
    assert (
        send_tenant_warnings(
            tenant, NOW, mailer=ResendMailer("fake", "from@example.test"), verify=verify
        )
        == 1
    )
    assert requests[0] == requests[1]
    assert "First piece" in requests[1]["json"]["text"]
    assert "New piece B" not in requests[1]["json"]["text"]
    assert len(accepted) == 1
    with tenant_session(tenant) as session:
        ledger = session.scalars(select(ContentDraftPurgeWarning.draft_id)).all()
        assert ledger == [first]
        batch = session.scalar(select(ContentDraftWarningBatch))
        assert batch.sent_at is not None
    assert (
        send_tenant_warnings(
            tenant,
            NOW + timedelta(days=1),
            mailer=ResendMailer("fake", "from@example.test"),
            verify=verify,
        )
        == 1
    )
    assert requests[2]["headers"]["Idempotency-Key"] != requests[1]["headers"]["Idempotency-Key"]
    assert "New piece B" in requests[2]["json"]["text"]
    assert "Changed title A" not in requests[2]["json"]["text"]
    with tenant_session(tenant) as session:
        ledger = session.scalars(select(ContentDraftPurgeWarning.draft_id)).all()
        assert sorted(ledger) == sorted([first, second])


@pytest.mark.parametrize("piece_count", [1, 8])
def test_warning_thumbnail_and_ledger_queries_are_batched_after_dedup(
    monkeypatch, piece_count: int
) -> None:
    from qualify_shared.db.session import _get_engine

    from qualify_api.creative import retention_mail as module

    tenant, brand, _, _, auth_id = _warning_account()
    ids = {_piece(tenant, brand, generated_days_ago=80) for _ in range(piece_count)}
    seen = []
    thumbnail_ids = []
    actual = module._thumbnail_urls

    def thumbnails(session, draft_ids):
        thumbnail_ids.append(set(draft_ids))
        return actual(session, draft_ids)

    monkeypatch.setattr(module, "_thumbnail_urls", thumbnails)

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    def count_thumbnail() -> int:
        return sum(
            sql.lstrip().upper().startswith("SELECT") and "image_assets.media_url" in sql
            for sql in seen
        )

    def count_ledger() -> int:
        return sum(
            sql.lstrip().upper().startswith("SELECT") and "FROM content_draft_purge_warnings" in sql
            for sql in seen
        )

    engine = _get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert send_tenant_warnings(tenant, NOW, mailer=FakeMailer(), verify=verify) == 1
        assert count_thumbnail() == 1 and count_ledger() == 1
        assert thumbnail_ids == [ids]
        seen.clear()
        thumbnail_ids.clear()
        assert send_tenant_warnings(tenant, NOW, mailer=FakeMailer(), verify=verify) == 0
        assert count_thumbnail() == 0 and count_ledger() == 1
        assert thumbnail_ids == []
        new = _piece(tenant, brand, generated_days_ago=80)
        seen.clear()
        assert send_tenant_warnings(tenant, NOW, mailer=FakeMailer(), verify=verify) == 1
        assert count_thumbnail() == 1 and count_ledger() == 1
        assert thumbnail_ids == [{new}]
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("change", ["scheduled", "publishing", "renewed", "expired", "unconfirmed"])
def test_warning_frozen_batch_revalidates_membership_deadline_and_protection(change: str) -> None:
    tenant, brand, user, connection, auth_id = _warning_account()
    piece = _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0
    moment = NOW
    if change in ("scheduled", "publishing"):
        _event(tenant, brand, user, connection, piece, status=change, days_from_now=1)
    if change == "renewed":
        with tenant_session(tenant) as session:
            session.execute(
                update(ImageAsset).where(ImageAsset.draft_id == piece).values(created_at=NOW)
            )
    if change == "expired":
        moment += timedelta(days=10)
    if change == "unconfirmed":

        def verify(uid: UUID, email: str) -> str | None:
            return None

    recording = FakeMailer()
    assert send_tenant_warnings(tenant, moment, mailer=recording, verify=verify) == 0
    assert recording.sent == []
    with tenant_session(tenant) as session:
        old = session.scalar(select(ContentDraftWarningBatch))
        assert old.needs_review_at is not None and old.sent_at is None
        assert old.cancelled_at is None
        assert session.scalars(select(ContentDraftPurgeWarning)).all() == []
    if change == "renewed":
        assert (
            send_tenant_warnings(tenant, NOW + timedelta(days=75), mailer=recording, verify=verify)
            == 1
        )
        with tenant_session(tenant) as session:
            rows = session.scalars(select(ContentDraftWarningBatch)).all()
            assert len(rows) == 2 and len({row.idempotency_key for row in rows}) == 2


def test_warning_identity_provider_outage_does_not_cancel_the_frozen_retry() -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0

    def unavailable(uid: UUID, email: str) -> str | None:
        raise RuntimeError("identity provider unavailable")

    assert send_tenant_warnings(tenant, NOW, mailer=FakeMailer(), verify=unavailable) == 0
    with tenant_session(tenant) as session:
        row = session.scalar(select(ContentDraftWarningBatch))
        assert row.sent_at is None and row.cancelled_at is None
    assert send_tenant_warnings(tenant, NOW, mailer=FakeMailer(), verify=verify) == 1


def test_warning_outbox_is_tenant_isolated_and_payload_is_not_editable() -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    other = uuid4()
    _provision(other, "other-outbox")
    _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0
    with tenant_session(tenant) as session:
        row = session.scalar(select(ContentDraftWarningBatch))
        batch_id = row.id
    with tenant_session(other) as session:
        assert session.get(ContentDraftWarningBatch, batch_id) is None
    with pytest.raises(DBAPIError), tenant_session(other) as session:
        session.add(
            ContentDraftWarningBatch(
                tenant_id=tenant,
                brand_id=brand,
                recipient="test@example.test",
                stage="window_15d",
                idempotency_key=str(uuid4()),
                payload={"mail": {}, "pieces": []},
            )
        )
        session.flush()
    with pytest.raises(DBAPIError), tenant_session(tenant) as session:
        session.execute(
            update(ContentDraftWarningBatch)
            .where(ContentDraftWarningBatch.id == batch_id)
            .values(payload={})
        )


@pytest.mark.parametrize("hours", [22.99, 23.0, 24.0])
def test_warning_unknown_acceptance_retry_stops_before_provider_window(hours: float) -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    first = _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0
    with tenant_session(tenant) as session:
        old = session.scalar(select(ContentDraftWarningBatch))
        batch_id, payload, key = old.id, deepcopy(old.payload), old.idempotency_key
        assert old.first_attempt_at == NOW
    recording = FakeMailer()
    count = retry_tenant_warnings(
        tenant, NOW + timedelta(hours=hours), mailer=recording, verify=verify
    )
    if hours < 23:
        assert count == 1 and recording.sent[0].idempotency_key == key
        assert warning_review_ids(tenant) == []
        return
    assert count == 0 and recording.sent == []
    assert warning_review_ids(tenant) == [batch_id]
    second = _piece(tenant, brand, generated_days_ago=75)
    # Stopped A stays reserved while the next daily pass can send new B.
    assert (
        send_tenant_warnings(tenant, NOW + timedelta(hours=hours), mailer=recording, verify=verify)
        == 1
    )
    assert str(second) in recording.sent[0].text and str(first) not in recording.sent[0].text
    assert (
        send_tenant_warnings(tenant, NOW + timedelta(days=2), mailer=recording, verify=verify) == 0
    )
    with tenant_session(tenant) as session:
        old = session.get(ContentDraftWarningBatch, batch_id)
        assert old.payload == payload and old.idempotency_key == key and old.sent_at is None
        assert old.needs_review_at is not None
        assert session.scalars(select(ContentDraftPurgeWarning.draft_id)).all() == [second]
    # The final-day reminder is an independent stage, not reserved by the earlier one.
    assert (
        send_tenant_warnings(
            tenant, NOW + timedelta(days=9, hours=12), mailer=recording, verify=verify
        )
        == 1
    )
    assert str(first) in recording.sent[-1].text and "24 horas" in recording.sent[-1].text


def test_warning_definitive_rejection_can_retry_next_day_without_unknown_cutoff() -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    class Rejected:
        def send(self, mail: OutgoingMail) -> str | None:
            raise MailRejected("provider explicitly rejected this request")

    assert send_tenant_warnings(tenant, NOW, mailer=Rejected(), verify=verify) == 0
    with tenant_session(tenant) as session:
        batch = session.scalar(select(ContentDraftWarningBatch))
        key = batch.idempotency_key
        assert batch.first_attempt_at is None
    recording = FakeMailer()
    assert (
        retry_tenant_warnings(tenant, NOW + timedelta(days=1), mailer=recording, verify=verify) == 1
    )
    assert recording.sent[0].idempotency_key == key
    assert warning_review_ids(tenant) == []


def test_warning_minute_retry_does_not_discover_new_pieces() -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0
    new = _piece(tenant, brand, generated_days_ago=75)
    recording = FakeMailer()
    assert (
        retry_tenant_warnings(tenant, NOW + timedelta(minutes=1), mailer=recording, verify=verify)
        == 1
    )
    assert str(new) not in recording.sent[0].text
    assert (
        retry_tenant_warnings(tenant, NOW + timedelta(minutes=2), mailer=recording, verify=verify)
        == 0
    )
    assert (
        send_tenant_warnings(tenant, NOW + timedelta(days=1), mailer=recording, verify=verify) == 1
    )
    assert str(new) in recording.sent[-1].text


def test_warning_uncertain_batch_protection_reserves_all_original_piece_identities() -> None:
    tenant, brand, user, connection, auth_id = _warning_account()
    first = _piece(tenant, brand, generated_days_ago=80)
    second = _piece(tenant, brand, generated_days_ago=80)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    assert send_tenant_warnings(tenant, NOW, mailer=_FailingWarningMailer(), verify=verify) == 0
    _event(tenant, brand, user, connection, first, status="scheduled", days_from_now=1)
    new = _piece(tenant, brand, generated_days_ago=80)
    recording = FakeMailer()
    assert send_tenant_warnings(tenant, NOW, mailer=recording, verify=verify) == 1
    assert str(new) in recording.sent[0].text
    assert str(first) not in recording.sent[0].text and str(second) not in recording.sent[0].text
    assert len(warning_review_ids(tenant)) == 1
    assert send_tenant_warnings(tenant, NOW, mailer=recording, verify=verify) == 0


def test_warning_safe_cancel_does_not_miss_a_new_piece_entering_its_final_day() -> None:
    tenant, brand, _, _, auth_id = _warning_account()
    first = _piece(tenant, brand, generated_days_ago=89.5)

    def verify(uid: UUID, email: str) -> str | None:
        return email if uid == auth_id else None

    class Rejected:
        def send(self, mail: OutgoingMail) -> str | None:
            raise MailRejected("definitive rejection before acceptance")

    assert send_tenant_warnings(tenant, NOW, mailer=Rejected(), verify=verify) == 0
    with tenant_session(tenant) as session:
        original = session.scalar(select(ContentDraftWarningBatch))
        batch_id = original.id
        assert original.first_attempt_at is None
    second = _piece(tenant, brand, generated_days_ago=88.5)
    recording = FakeMailer()
    assert (
        send_tenant_warnings(tenant, NOW + timedelta(days=1), mailer=recording, verify=verify) == 1
    )
    assert str(second) in recording.sent[0].text and str(first) not in recording.sent[0].text
    with tenant_session(tenant) as session:
        original = session.get(ContentDraftWarningBatch, batch_id)
        assert original.cancelled_at is not None and original.needs_review_at is None
        assert session.scalars(select(ContentDraftPurgeWarning.draft_id)).all() == [second]
