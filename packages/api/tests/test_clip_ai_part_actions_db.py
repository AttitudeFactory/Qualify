"""m-25129407 against Postgres: the owner's actions on a Clip's AI parts write in ONE
transaction under the Clip's fence — the charge first, then the part's new revision, its
queued job, and (on a made Clip) the Clip's next version with its local-build row; a
refusal writes nothing; the same tap twice makes one attempt; the store finds a part's
files and never another business's (RLS). No vendor is called."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import clip_ai_part_actions as act
from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import models as orm
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH

from .test_clip_ai_parts_db import _clip, _count, _create
from .test_clip_ai_parts_db import _world as _parts_world

pytestmark = pytest.mark.db


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    world = _parts_world(monkeypatch)
    content = world["service"]._content  # noqa: SLF001
    world["actions"] = act.ClipAiPartActions(content)
    world["content"] = content
    return world


def _status(tenant: UUID, draft: UUID) -> tuple[str, int]:
    with tenant_session(tenant) as session:
        row = session.execute(
            text("SELECT status, revision FROM content_drafts WHERE id = :d"), {"d": draft}
        ).first()
    assert row is not None
    return str(row.status), int(row.revision)


def _fail(tenant: UUID, part: UUID) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE content_drafts SET status = 'failed', failure_reason = 'provider_error'
            WHERE id = :p
        """),
            {"p": part},
        )
        session.execute(
            text("UPDATE creative_jobs SET status = 'failed' WHERE draft_id = :p"), {"p": part}
        )
    # its generation's own refund at its revision
    from qualify_api.creative.creations import PostgresCreationsLedger

    PostgresCreationsLedger().refund(
        tenant_id=tenant, draft_id=part, revision=1, reason="provider_error"
    )


def _made(tenant: UUID, part: UUID) -> str:
    key = f"t/{tenant}/generated/{part}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :p"), {"p": part}
        )
        session.execute(
            text("UPDATE creative_jobs SET status = 'succeeded' WHERE draft_id = :p"), {"p": part}
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=part,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="seedance",
                model_id="dreamina-seedance-2-0",
                params={"duration_seconds": 5.0, "part": {"seconds": 5, "mode": "reference"}},
            )
        )
    return key


def test_retry_writes_the_part_again_in_one_go_and_a_double_tap_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    made = _create(world)
    part = made.part_ids[0]
    _fail(tenant, part)
    brief_before = (
        world["content"].repository.get_draft(tenant_id=tenant, draft_id=made.clip_id).brief_id
    )
    args = {"tenant_id": tenant, "user_id": user, "clip_id": made.clip_id, "part_id": part}
    assert world["actions"].retry_part(**args) == part
    assert _status(tenant, part) == ("drafting", 2)
    charge = "SELECT count(*) FROM creation_charges WHERE draft_id = :d AND revision = 2"
    assert _count(tenant, charge, d=part) == 1
    queued = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'queued'"
    assert _count(tenant, queued, d=part) == 1
    # the waiting Clip's brief is written again: a pass that read before cannot fail it
    clip = world["content"].repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    assert clip.brief_id != brief_before and clip.status == "drafting"
    # the same tap again: one attempt
    assert world["actions"].retry_part(**args) == part
    assert _status(tenant, part) == ("drafting", 2)
    assert _count(tenant, queued, d=part) == 1
    assert _count(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id = :d", d=part) == 2


def test_a_refused_retry_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    made = _create(world)
    part = made.part_ids[0]
    _fail(tenant, part)
    charges = _count(tenant, "SELECT count(*) FROM creation_charges")
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    with pytest.raises(cap.ClipAiPartsRefused):
        world["actions"].retry_part(
            tenant_id=tenant, user_id=user, clip_id=made.clip_id, part_id=part
        )
    assert _status(tenant, part) == ("failed", 1)
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == charges


def test_redo_on_a_made_clip_writes_the_part_and_the_clips_next_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, user, content = world["tenant"], world["user"], world["content"]
    made = _create(world)
    part = made.part_ids[0]
    key = _made(tenant, part)
    store = cap.PostgresAiPartsStore()
    assert store.played(tenant_id=tenant, clip_id=made.clip_id, keys=[key]) == {key: part}
    assert store.played(tenant_id=uuid4(), clip_id=made.clip_id, keys=[key]) == {}  # RLS
    # the Clip as its first assembly leaves it: the part a stretch of its file, `generated`
    clip = content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    asked = content.repository.get_brief(tenant_id=tenant, brief_id=clip.brief_id)
    video = store.part_video(tenant_id=tenant, part_id=part)
    assert video is not None
    resolved = cap.resolve(asked, {0: video}).brief
    resolved = resolved.model_copy(
        update={"media": resolved.media.model_copy(update={"derived_from_brief_id": clip.brief_id})}
    )
    content.repository.replace_brief(
        tenant_id=tenant, draft_id=made.clip_id, user_id=user, brief=resolved
    )
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :c"),
            {"c": made.clip_id},
        )
        session.execute(
            text("UPDATE creative_jobs SET status = 'succeeded' WHERE draft_id = :c"),
            {"c": made.clip_id},
        )
    world["actions"].redo_part(tenant_id=tenant, user_id=user, clip_id=made.clip_id, part_id=part)
    assert _status(tenant, part) == ("drafting", 2)
    assert _status(tenant, made.clip_id) == ("drafting", 2)
    local = (
        "SELECT count(*) FROM creation_charges WHERE draft_id = :d AND revision = 2 "
        "AND request_kind = 'local_video'"
    )
    assert _count(tenant, local, d=made.clip_id) == 1  # the owner's assembly counts
    queued = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'queued'"
    assert _count(tenant, queued, d=part) == 1
    assert _count(tenant, queued, d=made.clip_id) == 1


def test_remove_marks_the_part_and_writes_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant, user, content = world["tenant"], world["user"], world["content"]
    from qualify_creative.schemas import SourceSegment

    brief = _clip(world["brand"], tenant)
    own = brief.media.segments[0]
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "segments": (
                        *brief.media.segments,
                        SourceSegment(key=own.key, start_s=0, end_s=3, speed=1),
                    )
                }
            )
        }
    )
    made = _create(world, brief=brief)
    part = made.part_ids[0]
    _fail(tenant, part)
    charges = _count(tenant, "SELECT count(*) FROM creation_charges")
    assert world["actions"].remove_part(
        tenant_id=tenant, user_id=user, clip_id=made.clip_id, part_id=part
    )
    removed = "SELECT count(*) FROM content_drafts WHERE id = :p AND part_removed_at IS NOT NULL"
    assert _count(tenant, removed, p=part) == 1
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == charges
    (row,) = cap.PostgresAiPartsStore().parts_of(tenant_id=tenant, clip_id=made.clip_id)
    assert row.removed and row.changed_at is not None and row.mode == "reference"
    assert not world["actions"].remove_part(
        tenant_id=tenant, user_id=user, clip_id=made.clip_id, part_id=part
    )
    assert content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id).status == (
        "drafting"
    )


def test_the_owners_clock_starts_when_the_part_failed_not_at_its_old_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of m-25129407: a failure does not always write `updated_at` (a part that
    waited long, or reaped); its vista previa given back says when it failed."""
    from datetime import UTC, datetime, timedelta

    world = _world(monkeypatch)
    tenant = world["tenant"]
    made = _create(world)
    part = made.part_ids[0]
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at = now() - interval '5 days' WHERE id = :p"),
            {"p": part},
        )
    _fail(tenant, part)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at = now() - interval '5 days' WHERE id = :p"),
            {"p": part},
        )
    (row,) = cap.PostgresAiPartsStore().parts_of(tenant_id=tenant, clip_id=made.clip_id)
    assert row.changed_at is not None
    assert row.changed_at > datetime.now(UTC) - timedelta(hours=1)
