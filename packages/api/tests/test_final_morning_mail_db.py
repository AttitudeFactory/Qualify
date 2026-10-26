from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.models import ImageAsset
from qualify_api.mail import FakeMailer
from qualify_api.mail.final_summary import mark_delivery, preference, send_pending, stage_batch
from qualify_api.mail.routes import router
from qualify_api.tenancy.models import TenantMember, User

from .test_creative_regenerate_db import _brand, _drafting_draft

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 26, 11, tzinfo=UTC)
BASE = "https://app.example.invalid"


class UniqueFakeMailer(FakeMailer):
    def send(self, mail):
        super().send(mail)
        return str(uuid4())


def fixture():
    tenant = uuid4()
    brand = _brand(tenant)
    users = []
    with admin_session() as session:
        for role in ("owner", "admin", "agent"):
            user = User(tenant_id=tenant, email=f"{uuid4()}@example.invalid", display_name=role)
            session.add(user)
            session.flush()
            session.add(TenantMember(tenant_id=tenant, user_id=user.id, role=role))
            users.append(user.id)
    draft = _drafting_draft(tenant, brand)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status='approved',title='Mi video' WHERE id=:id"),
            {"id": draft},
        )
        session.add(
            ImageAsset(
                tenant_id=tenant,
                draft_id=draft,
                media_url="",
                media_type="video",
                params={
                    "draft": {
                        "status": "final_ready",
                        "final_origin": "approval",
                        "final_nightly": True,
                    }
                },
                position=0,
            )
        )
        session.execute(
            text("""
            INSERT INTO creative_jobs(tenant_id,draft_id,kind,revision,vendor_model,lane,status,
                                      finished_at,position)
            VALUES(:tenant,:draft,'final',1,'byteplus:seedance-2-5','nightly','succeeded',:at,0)
        """),
            {"tenant": tenant, "draft": draft, "at": NOW - timedelta(hours=1)},
        )
    return tenant, tuple(users), draft


def stage(tenant):
    return stage_batch(tenant, now=NOW, base_url=BASE, thumbnail=lambda *args: "")


def test_two_approvers_one_agent_one_frozen_batch_per_day():
    tenant, users, draft = fixture()
    assert stage(tenant) == 2
    assert stage(tenant) == 0
    fake = UniqueFakeMailer()
    assert send_pending(tenant, now=NOW, mailer=fake) == 2
    assert send_pending(tenant, now=NOW, mailer=fake) == 0
    assert len(fake.sent) == 2 and all(m.sender_name == "Qualify" for m in fake.sent)
    assert str(draft) in fake.sent[0].text
    assert stage_batch(tenant, now=NOW + timedelta(days=1), base_url=BASE) == 0
    with pytest.raises(LookupError):
        preference(tenant, users[2])


def test_individual_optout_token_get_safe_post_then_next_batch_respects_person():
    tenant, users, _ = fixture()
    _, token = preference(tenant, users[0])
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    url = f"/api/mail/finals/preferences/{tenant}/{users[0]}/{token}"
    assert client.get(url).status_code == 200
    assert preference(tenant, users[0])[0]
    assert client.post(url, content="List-Unsubscribe=One-Click").status_code == 200
    assert not preference(tenant, users[0])[0]
    assert stage(tenant) == 1
    assert client.post(url, content="enabled=true").status_code == 200
    assert preference(tenant, users[0])[0]
    assert stage(tenant) == 1
    assert client.get(url.replace(str(users[0]), str(users[1]))).status_code == 404


def test_rls_cannot_read_or_change_other_member_preferences():
    tenant, users, _ = fixture()
    other, other_users, _ = fixture()
    _, token = preference(tenant, users[0])
    preference(other, other_users[0])
    with tenant_session(other) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM final_mail_preferences WHERE user_id=:u"),
                {"u": users[0]},
            )
            == 0
        )
    with pytest.raises(LookupError):
        preference(other, users[0], token=token, enabled=False)
    assert preference(tenant, users[0])[0]


def test_unknown_send_retries_identical_payload_and_key_without_duplicate_then_expires():
    tenant, _, draft = fixture()
    stage(tenant)

    class CrashMailer:
        def __init__(self):
            self.calls = []
            self.accepted = {}
            self.crash = True

        def send(self, mail):
            self.calls.append(mail)
            identity = self.accepted.setdefault(mail.idempotency_key, str(uuid4()))
            if self.crash:
                self.crash = False
                raise TimeoutError("accepted but response lost")
            return identity

    mailer = CrashMailer()
    assert send_pending(tenant, now=NOW, mailer=mailer) == 0
    with tenant_session(tenant) as session:
        session.execute(text("UPDATE content_drafts SET title='Changed' WHERE id=:d"), {"d": draft})
    assert send_pending(tenant, now=NOW + timedelta(minutes=3), mailer=mailer) == 2
    assert mailer.calls[0] == mailer.calls[1]
    assert len(mailer.accepted) == 2
    # A separate unknown attempt older than provider's dedupe window is quarantined.
    second, _, _ = fixture()
    stage(second)
    with tenant_session(second) as session:
        session.execute(
            text("UPDATE final_mail_batches SET first_attempt_at=:at"),
            {"at": NOW - timedelta(hours=23)},
        )
    before = len(mailer.calls)
    assert send_pending(second, now=NOW, mailer=mailer) == 0
    assert len(mailer.calls) == before


def test_no_email_for_confirmed_or_immediate_final_and_delivery_webhook_matches():
    tenant, _, draft = fixture()
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets SET params=jsonb_set(params,'{draft,final_nightly}','false')
            WHERE draft_id=:d
        """),
            {"d": draft},
        )
    assert stage(tenant) == 0
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets SET params=jsonb_set(params,'{draft,final_nightly}','true')
            WHERE draft_id=:d
        """),
            {"d": draft},
        )
    assert stage(tenant) == 2
    send_pending(tenant, now=NOW, mailer=UniqueFakeMailer())
    with tenant_session(tenant) as session:
        provider = session.scalar(text("SELECT provider_id FROM final_mail_batches LIMIT 1"))
    assert mark_delivery(provider, kind="delivered", at=NOW)
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("""
            SELECT delivery_status FROM final_mail_batches WHERE provider_id=:provider
        """),
                {"provider": provider},
            )
            == "delivered"
        )


def test_confirmed_between_stage_and_first_send_is_not_emailed():
    tenant, _, draft = fixture()
    stage(tenant)
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets SET params=jsonb_set(params,'{draft,status}','"final"')
            WHERE draft_id=:d
        """),
            {"d": draft},
        )
    fake = UniqueFakeMailer()
    assert send_pending(tenant, now=NOW, mailer=fake) == 0
    assert not fake.sent
    with tenant_session(tenant) as session:
        assert session.scalar(text("SELECT count(*) FROM final_mail_batches WHERE discarded")) == 2


def test_composite_fk_rejects_other_business_user_even_with_own_tenant():
    from sqlalchemy.exc import IntegrityError

    tenant, _, _ = fixture()
    _, others, _ = fixture()
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text("""
            INSERT INTO final_mail_preferences(tenant_id,user_id) VALUES(:t,:u)
        """),
            {"t": tenant, "u": others[0]},
        )


def test_piece_waits_for_all_finals_and_mixed_terminal_failure_is_reported_as_failure():
    tenant, _, draft = fixture()
    with tenant_session(tenant) as session:
        session.add(
            ImageAsset(
                tenant_id=tenant,
                draft_id=draft,
                media_url="",
                media_type="video",
                position=1,
                params={
                    "draft": {
                        "status": "rendering",
                        "final_origin": "approval",
                        "final_nightly": True,
                    }
                },
            )
        )
        session.execute(
            text("""
            INSERT INTO creative_jobs(tenant_id,draft_id,kind,revision,vendor_model,lane,position)
            VALUES(:t,:d,'final',1,'byteplus:seedance-2-5','nightly',1)
        """),
            {"t": tenant, "d": draft},
        )
    assert stage(tenant) == 0
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets SET params=jsonb_set(params,'{draft,status}','"failed"')
            WHERE draft_id=:d AND position=1
        """),
            {"d": draft},
        )
        session.execute(
            text("""
            UPDATE creative_jobs SET status='failed',finished_at=:at
            WHERE draft_id=:d AND position=1
        """),
            {"d": draft, "at": NOW - timedelta(minutes=10)},
        )
    assert stage(tenant) == 2
    fake = UniqueFakeMailer()
    assert send_pending(tenant, now=NOW, mailer=fake) == 2
    assert all("no pudimos preparar 1 video" in mail.subject for mail in fake.sent)
