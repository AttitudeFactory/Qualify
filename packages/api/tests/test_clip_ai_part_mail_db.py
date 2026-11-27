"""m-25142979 on Postgres (migration 0192): a waiting Clip's failed AI part stages ONE row
in its own fenced write, never twice for the same (part, revision); a part made again
that fails again is one more; the sender mails it once through a recording mailer (never
Resend), closes it unsent once the Clip failed, and another business never sees it (RLS).
No vendor is called."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy.exc
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import clip_ai_part_actions as act
from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar_mail as cm
from qualify_api.mail import clip_ai_part as template

from .test_clip_ai_part_actions_db import _fail, _status
from .test_clip_ai_parts_db import _create
from .test_clip_ai_parts_db import _world as _parts_world
from .test_clip_avatar_mail_db import AUTH_USER, RecordingMailer, _member

pytestmark = pytest.mark.db

BASE = "https://app.qualify.test"


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    world = _parts_world(monkeypatch)
    content = world["service"]._content  # noqa: SLF001
    world["content"] = content
    world["actions"] = act.ClipAiPartActions(content)
    world["email"] = _member(world["tenant"], world["user"])
    return world


def _see(world: dict[str, Any], clip_id: UUID) -> None:
    """One waiting pass of the Clip: the gate's verdict, and the email it stages."""
    tenant, content = world["tenant"], world["content"]
    store = cap.PostgresAiPartsStore()
    draft = content.repository.get_draft(tenant_id=tenant, draft_id=clip_id)
    brief = content.repository.get_brief(tenant_id=tenant, brief_id=draft.brief_id)
    verdict = cap.ai_parts_gate(tenant_id=tenant, clip_id=clip_id, brief=brief, store=store)
    assert isinstance(verdict, cap.AiPartsWait) and verdict.reason == "part_failed"
    content._stage_ai_part_mail(tenant, draft, verdict.failed)  # noqa: SLF001


def _rows(tenant: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("""
                SELECT kind, slots, block_ids, block_revisions, failure_codes, sent_at,
                       closed_reason, provider_id, source_version, user_id
                FROM clip_avatar_failure_mails ORDER BY created_at, failed_at
            """)
            )
        )


def _send(world: dict[str, Any], mailer: RecordingMailer) -> int:
    return cm.send_pending(
        cm.PostgresAvatarFailureOutbox(),
        world["tenant"],
        now=datetime.now(UTC),
        mailer=mailer,
        base_url=BASE,
        verify=lambda auth, email: email if auth == AUTH_USER else None,
    )


def test_one_row_per_failure_sent_once_and_invisible_to_another_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    made = _create(world)
    part = made.part_ids[0]
    _fail(tenant, part)
    _see(world, made.clip_id)
    _see(world, made.clip_id)  # the next pass reads the same failed part again
    (row,) = _rows(tenant)
    assert row.kind == template.AI_PART_FAILED and list(row.slots) == [1]
    assert [UUID(str(b)) for b in row.block_ids] == [part] and list(row.block_revisions) == [1]
    assert list(row.failure_codes) == ["provider_error"]
    assert row.source_version == template.AI_PART_TEMPLATE_VERSION
    assert row.user_id == world["user"] and row.sent_at is None
    assert _rows(uuid4()) == []  # RLS: another business sees nothing
    mailer = RecordingMailer()
    assert _send(world, mailer) == 1 and _send(world, mailer) == 0
    (mail,) = mailer.sent
    assert mail.to == world["email"]
    assert "La parte con IA 1 de tu video no salió" in mail.text
    assert f"{BASE}/drafts/{made.clip_id}" in mail.text
    (row,) = _rows(tenant)
    assert row.sent_at is not None and row.provider_id == "resend-1"


def test_a_part_made_again_that_fails_again_is_one_more_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    made = _create(world)
    part = made.part_ids[0]
    _fail(tenant, part)
    _see(world, made.clip_id)
    world["actions"].retry_part(tenant_id=tenant, user_id=user, clip_id=made.clip_id, part_id=part)
    assert _status(tenant, part) == ("drafting", 2)
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE content_drafts SET status = 'failed', failure_reason = 'provider_error'
            WHERE id = :p
        """),
            {"p": part},
        )
    _see(world, made.clip_id)
    _see(world, made.clip_id)
    assert [list(r.block_revisions) for r in _rows(tenant)] == [[1], [2]]


def test_a_clip_that_failed_before_the_email_left_is_never_mailed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, content = world["tenant"], world["content"]
    made = _create(world)
    _fail(tenant, made.part_ids[0])
    _see(world, made.clip_id)
    draft = content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    content._fail_waiting_clip(  # noqa: SLF001
        tenant, draft, reason=cap.AI_PART_EXPIRED, detail=cap.AI_PART_EXPIRED_TEXT
    )
    mailer = RecordingMailer()
    assert _send(world, mailer) == 0 and mailer.sent == []
    assert [r.closed_reason for r in _rows(tenant)] == ["resolved"]


def test_an_ai_part_row_needs_its_revisions(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    made = _create(world)
    with pytest.raises(sqlalchemy.exc.IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text("""
            INSERT INTO clip_avatar_failure_mails
                (tenant_id, clip_id, kind, failed_at, slots, block_ids, failure_codes,
                 user_id, idempotency_key, source_version)
            VALUES (:t, :c, 'ai_part_failed', now(), ARRAY[1]::smallint[],
                    ARRAY[:p]::uuid[], ARRAY['x'], :u, :k, 'v')
        """),
            {
                "t": tenant,
                "c": made.clip_id,
                "p": made.part_ids[0],
                "u": world["user"],
                "k": f"k-{uuid4()}",
            },
        )
