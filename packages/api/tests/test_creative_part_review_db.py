"""UI-8 (m-24921083) against Postgres: «Me gusta así» is stored in the draft block of the
part's ACTIVE video, idempotent, without any charge nor touching the parent; each
version keeps its own mark through «Crear otra versión» and «Usar esta versión»
(which costs nothing); the versions read «n de m» with their own brief; and another
business reads and writes nothing (RLS).

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.part_progress import PartState, read_part_progress
from qualify_api.creative.part_review import (
    PartNotReviewable,
    part_edit_fields,
    part_versions,
    set_part_liked,
    use_part_version,
)
from qualify_api.creative.parts import PartChanges
from qualify_api.creative.service import UnknownDraft

from .test_creative_parts_db import _business, _parent, _scalar, _service

pytestmark = pytest.mark.db


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    tenant, brand, user = _business(monkeypatch)
    service, parts, copy = _service()
    parent = _parent(service, tenant, brand, user)
    return service, parts, copy, tenant, brand, user, parent


def _as_video(tenant: UUID, child: UUID, *, age_days: float = 0) -> None:
    """The child's active asset as a 480p draft video (what the fake producer skips)."""
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE image_assets a SET media_type = 'video',
                object_key = 't/' || a.tenant_id || '/generated/' || a.draft_id || '/r'
                             || d.revision || '/clip.mp4',
                params = COALESCE(a.params, '{}'::jsonb) || jsonb_build_object('draft',
                    jsonb_build_object('status', 'draft', 'duration_seconds', 4,
                        'created_at', extract(epoch FROM now())::bigint - CAST(:age AS bigint)))
            FROM content_drafts d
            WHERE d.id = a.draft_id AND a.draft_id = :c AND a.version_id = d.active_version_id
            """),
            {"c": child, "age": int(age_days * 86400)},
        )


def _charges(tenant: UUID, brand: UUID) -> tuple[object, object]:
    return (
        _scalar(tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand),
        _scalar(tenant, "SELECT sum(videos) FROM creation_charges WHERE brand_id=:b", b=brand),
    )


def _state(tenant: UUID, parent: UUID, index: int) -> tuple[PartState, bool]:
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None
    row = next(p for p in progress.parts if p.index == index)
    return row.state, row.liked


def test_liking_a_part_reads_ready_once_and_charges_nothing_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    _as_video(tenant, ids[0])
    before = _charges(tenant, brand)
    status = _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:p", p=parent)
    assert _state(tenant, parent, 1) == (PartState.TO_REVIEW, False)

    assert set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=True)
    assert not set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=True)
    assert _state(tenant, parent, 1) == (PartState.READY, True)
    assert _charges(tenant, brand) == before
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:p", p=parent) == status
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[0]) == (
        "generated"
    )

    assert set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=False)
    assert not set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=False)
    assert _state(tenant, parent, 1) == (PartState.TO_REVIEW, False)


def test_a_part_not_to_review_or_expired_is_refused_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    with pytest.raises(PartNotReviewable) as drafting:
        set_part_liked(tenant_id=tenant, parent_id=parent, part_index=2, liked=True)
    assert drafting.value.reason == "not_reviewable"

    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    with pytest.raises(PartNotReviewable) as no_video:  # no draft video kept
        set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=True)
    assert no_video.value.reason == "no_video"

    _as_video(tenant, ids[0], age_days=8)
    with pytest.raises(PartNotReviewable) as expired:
        set_part_liked(tenant_id=tenant, parent_id=parent, part_index=1, liked=True)
    assert expired.value.reason == "expired"
    assert _state(tenant, parent, 1)[0] is PartState.EXPIRED


def test_each_version_keeps_its_own_mark_and_going_back_is_free_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _as_video(tenant, ids[1])
    set_part_liked(tenant_id=tenant, parent_id=parent, part_index=2, liked=True)
    first_text = part_edit_fields(tenant_id=tenant, parent_id=parent, part_index=2).description

    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=user,
    )
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _as_video(tenant, ids[1])
    assert _state(tenant, parent, 2) == (PartState.TO_REVIEW, False)  # a new version: no mark

    old, new = part_versions(tenant_id=tenant, parent_id=parent, part_index=2)
    assert (old.ordinal, old.total, old.current, old.liked) == (1, 2, False, True)
    assert (new.ordinal, new.total, new.current, new.liked) == (2, 2, True, False)
    assert old.description == first_text and new.description == "Papas recién fritas."
    assert old.video_key and new.video_key and old.video_key != new.video_key
    assert not old.expired
    fields = part_edit_fields(tenant_id=tenant, parent_id=parent, part_index=2)
    assert fields.description == "Papas recién fritas." and fields.mode == new.mode
    assert fields.photo_keys == new.photo_keys

    before = _charges(tenant, brand)
    use_part_version(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        version_id=old.version_id,
        user_id=user,
        content=service,
    )
    assert _charges(tenant, brand) == before  # costs 0
    assert _state(tenant, parent, 2) == (PartState.READY, True)  # its own mark is back
    again = part_versions(tenant_id=tenant, parent_id=parent, part_index=2)
    assert [v.current for v in again] == [True, False]
    back = part_edit_fields(tenant_id=tenant, parent_id=parent, part_index=2)
    assert back.description == first_text

    with pytest.raises(PartNotReviewable) as foreign:  # a version of another part
        use_part_version(
            tenant_id=tenant,
            parent_id=parent,
            part_index=1,
            version_id=old.version_id,
            user_id=user,
            content=service,
        )
    assert foreign.value.reason == "unknown_version"


def test_another_business_reads_and_writes_nothing_db(world, monkeypatch) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    _as_video(tenant, ids[0])
    other, _other_brand, other_user = _business(monkeypatch)
    with pytest.raises(UnknownDraft):
        set_part_liked(tenant_id=other, parent_id=parent, part_index=1, liked=True)
    with pytest.raises(UnknownDraft):
        part_versions(tenant_id=other, parent_id=parent, part_index=1)
    with pytest.raises(UnknownDraft):
        part_edit_fields(tenant_id=other, parent_id=parent, part_index=1)
    version = part_versions(tenant_id=tenant, parent_id=parent, part_index=1)[0].version_id
    with pytest.raises(UnknownDraft):
        use_part_version(
            tenant_id=other,
            parent_id=parent,
            part_index=1,
            version_id=version,
            user_id=other_user,
            content=service,
        )
    assert _state(tenant, parent, 1) == (PartState.TO_REVIEW, False)
