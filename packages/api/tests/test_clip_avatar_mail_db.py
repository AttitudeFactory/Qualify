"""m-25120319 on Postgres: the failure email is staged in the Clip's own write, once per
`failed_at` (migration 0186's UNIQUE), sent once through a recording mailer (never Resend),
and invisible to another business (RLS)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import clip_avatar_mail as cm
from qualify_api.mail import OutgoingMail

from .test_clip_avatar_db import _create_b, _fail_block, _first_create, _pass

pytestmark = pytest.mark.db

AUTH_USER = uuid4()


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> str | None:
        self.sent.append(mail)
        return f"resend-{len(self.sent)}"


def _member(tenant: UUID, user: UUID) -> str:
    with admin_session() as session:
        session.execute(
            text("UPDATE users SET auth_user_id = :a WHERE id = :u"), {"a": AUTH_USER, "u": user}
        )
        session.execute(
            text("""
            INSERT INTO tenant_members (tenant_id, user_id, role) VALUES (:t, :u, 'owner')
            ON CONFLICT DO NOTHING
        """),
            {"t": tenant, "u": user},
        )
        return str(session.scalar(text("SELECT email FROM users WHERE id = :u"), {"u": user}))


def _rows(tenant: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("""
                SELECT kind, slots, block_ids, failed_at, failure_codes, sent_at,
                       closed_reason, provider_id,
                       source_version, idempotency_key
                FROM clip_avatar_failure_mails ORDER BY created_at, failed_at
            """)
            )
        )


def test_one_email_per_failure_on_postgres_and_rls(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _first_create(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    email = _member(tenant, world["user"])
    t0 = datetime.now(UTC).replace(microsecond=0)
    content._clip_avatar_clock = lambda: t0
    made = _create_b(world)
    block = made.block_ids[0]
    _fail_block(tenant, block)
    _pass(world, made.clip_id)  # the failure is seen: stamp + row, one transaction
    _pass(world, made.clip_id)  # read again: nothing new
    (row,) = _rows(tenant)
    assert (row.kind, row.slots, row.failed_at) == ("block_failed", [1], t0)
    assert row.block_ids == [block] and row.failure_codes == ["provider_error"]
    assert row.source_version == "clip-avatar-failed-v1"
    assert row.idempotency_key == cm.failure_key(tenant, made.clip_id, "block_failed", t0)

    outbox, mailer = cm.PostgresAvatarFailureOutbox(), RecordingMailer()
    assert tenant in outbox.pending_tenants()
    send = {
        "now": t0 + timedelta(minutes=1),
        "mailer": mailer,
        "base_url": "https://app.qualify.test",
        "verify": lambda auth, address: address if auth == AUTH_USER else None,
    }
    assert cm.send_pending(outbox, tenant, **send) == 1
    assert cm.send_pending(outbox, tenant, **send) == 0
    (mail,) = mailer.sent
    assert mail.to == email and f"/drafts/{made.clip_id}" in mail.text
    assert "content-service-brand" in mail.subject  # the business's name
    (row,) = _rows(tenant)
    assert row.sent_at is not None and row.provider_id == "resend-1"

    # «Intentar de nuevo», and it fails again: a new failure, one more email
    t1 = t0 + timedelta(hours=2)
    content._clip_avatar_clock = lambda: t1
    args = {"tenant_id": tenant, "user_id": world["user"], "clip_id": made.clip_id}
    world["service"].retry_block(block_id=block, **args)
    _fail_block(tenant, block)
    _pass(world, made.clip_id)
    _pass(world, made.clip_id)
    assert [r.failed_at for r in _rows(tenant)] == [t0, t1]
    assert cm.send_pending(outbox, tenant, **{**send, "now": t1 + timedelta(minutes=1)}) == 1
    assert len(mailer.sent) == 2

    # another business sees none of it
    other = uuid4()
    with admin_session() as session:
        session.execute(
            text("""
            INSERT INTO tenants (id, name, country, timezone, currency)
            VALUES (:t, 'other', 'CO', 'America/Bogota', 'COP')
        """),
            {"t": other},
        )
    with tenant_session(other) as session:
        count = session.scalar(text("SELECT count(*) FROM clip_avatar_failure_mails"))
    assert count == 0


def _send(tenant: UUID, mailer: RecordingMailer, at: datetime) -> int:
    return cm.send_pending(
        cm.PostgresAvatarFailureOutbox(),
        tenant,
        now=at,
        mailer=mailer,
        base_url="https://app.qualify.test",
        verify=lambda auth, address: address if auth == AUTH_USER else None,
    )


def test_two_avatars_failing_in_one_pass_are_one_row_and_one_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import clip_avatar as ca

    from .test_clip_avatar_db import _clip, _request

    world = _first_create(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    _member(tenant, world["user"])
    t0 = datetime.now(UTC).replace(microsecond=0)
    content._clip_avatar_clock = lambda: t0
    made = world["service"].create_clip_with_blocks(
        tenant_id=tenant,
        brand_id=world["brand"],
        user_id=world["user"],
        brief=_clip(world["brand"], tenant),
        blocks=[
            ca.ClipAvatarPlacement(block=_request(), at=0),
            ca.ClipAvatarPlacement(block=_request(), at=1),
        ],
    )
    for block in made.block_ids:
        _fail_block(tenant, block)
    _pass(world, made.clip_id)
    _pass(world, made.clip_id)
    (row,) = _rows(tenant)  # the arrays went through their casts
    assert (row.kind, row.slots, row.failed_at) == ("block_failed", [1, 2], t0)
    assert row.block_ids == list(made.block_ids)
    assert row.failure_codes == ["provider_error", "provider_error"]
    mailer = RecordingMailer()
    assert _send(tenant, mailer, t0 + timedelta(minutes=1)) == 1
    assert _send(tenant, mailer, t0 + timedelta(minutes=2)) == 0
    (mail,) = mailer.sent
    assert "algunos de tus avatares no se pudieron crear" in mail.subject


def test_a_too_long_avatar_is_one_row_and_one_email_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_creative.schemas import SourceSegment

    from qualify_api.creative import clip_avatar as ca
    from qualify_api.creative import models as orm

    from .test_clip_avatar_db import _clip, _request

    world = _first_create(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    _member(tenant, world["user"])
    t0 = datetime.now(UTC).replace(microsecond=0)
    content._clip_avatar_clock = lambda: t0
    brief = _clip(world["brand"], tenant)
    own = SourceSegment(key=f"uploads/{tenant}/a.mp4", start_s=0, end_s=30, speed=1)
    brief = brief.model_copy(update={"media": brief.media.model_copy(update={"segments": (own,)})})
    made = world["service"].create_clip_with_blocks(
        tenant_id=tenant,
        brand_id=world["brand"],
        user_id=world["user"],
        brief=brief,
        blocks=[ca.ClipAvatarPlacement(block=_request(), at=1)],  # after the 30 s: it passes 60
    )
    block = made.block_ids[0]
    key = f"t/{tenant}/generated/{block}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :b"), {"b": block}
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=block,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="omnihuman",
                model_id="omnihuman-1.5",
                params={"duration_seconds": 30.9},  # with the 30 s of the Clip: over 60
            )
        )
    _pass(world, made.clip_id)
    _pass(world, made.clip_id)
    wait = world["service"].clip_wait(tenant_id=tenant, clip_id=made.clip_id)
    assert wait is not None, "no wait"
    assert [b.failure_code for b in wait.blocks] == ["clip_too_long"], (wait.state, wait.blocks)
    (row,) = _rows(tenant)
    assert (row.kind, row.slots, row.block_ids) == ("clip_too_long", [1], [block])
    assert row.failure_codes == ["clip_too_long"]
    mailer = RecordingMailer()
    assert _send(tenant, mailer, t0 + timedelta(minutes=1)) == 1
    assert _send(tenant, mailer, t0 + timedelta(minutes=2)) == 0
    (mail,) = mailer.sent
    assert "quedó muy largo" in mail.subject and "dura más de 60 segundos" in mail.text
