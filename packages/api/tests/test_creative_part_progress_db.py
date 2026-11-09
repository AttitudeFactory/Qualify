"""m-24921082 (UI-7) against Postgres: the result screen of a video by parts is read
under the owning business (RLS) — every part with its state, the parts with a vista
previa, a part waiting in line — and «Intentar de nuevo» / «Hacerla nueva» on a failed
part charge one vista previa in the same transaction as the new revision and its job.

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.part_actions import PART_SAME_PHOTOS_TEXT, PartRecovery
from qualify_api.creative.part_progress import PartAction, PartState, read_part_progress
from qualify_api.creative.parts import PartChangeRefused
from qualify_api.creative.service import PIPELINE_VERSION

from .test_creative_parts_db import _business, _parent, _scalar, _service, _use_previews

pytestmark = pytest.mark.db


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """A business with a video by parts whose text is made (as `test_creative_parts_db`)."""
    tenant, brand, user = _business(monkeypatch)
    service, parts, copy = _service()
    parent = _parent(service, tenant, brand, user)
    return service, parts, copy, tenant, brand, user, parent


def _exec(tenant: UUID, sql: str, **params: object) -> None:
    with tenant_session(tenant) as session:
        session.execute(text(sql), params)


def _fail(tenant: UUID, child: UUID, reason: str) -> None:
    _exec(
        tenant,
        "UPDATE content_drafts SET status='failed', failure_reason=:r, failure_detail=:d "
        "WHERE id=:c",
        r=reason,
        d="detalle",
        c=child,
    )


def test_the_screen_reads_every_part_with_its_state_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    before = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert before is not None and [p.state for p in before.parts] == [PartState.UNMADE] * 4

    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    queued = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert queued is not None and [p.state for p in queued.parts] == [PartState.QUEUED] * 4

    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    # the vendor already answered part 3; its result is still being kept
    _exec(
        tenant,
        "UPDATE creative_jobs SET status='succeeded', finished_at=now() WHERE draft_id=:c",
        c=ids[2],
    )
    _fail(tenant, ids[3], "refused_face")

    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None
    assert [p.state for p in progress.parts] == [
        PartState.TO_REVIEW,
        PartState.TO_REVIEW,
        PartState.CREATING,
        PartState.FAILED,  # a «Nueva» part refused for its photos
    ]
    assert (progress.with_preview, progress.total) == (2, 4)
    last = progress.parts[3]
    assert last.draft_id == ids[3] and last.failure_reason == "refused_face"
    assert last.failure_detail == "detalle"
    assert last.actions == (PartAction.CHANGE, PartAction.REMOVE)
    assert [p.index for p in progress.parts] == [1, 2, 3, 4]


def test_a_purged_video_reads_every_part_expired_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    _exec(tenant, "UPDATE content_drafts SET media_purged_at=now() WHERE id=:p", p=parent)
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None
    assert {p.state for p in progress.parts if p.draft_id is not None} == {PartState.EXPIRED}
    assert all(p.actions == () for p in progress.parts)


def test_another_business_reads_nothing_db(world, monkeypatch) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    other, _other_brand, _other_user = _business(monkeypatch)
    assert read_part_progress(tenant_id=other, parent_id=parent) is None
    assert read_part_progress(tenant_id=tenant, parent_id=uuid4()) is None


def test_a_part_is_not_a_video_by_parts_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert read_part_progress(tenant_id=tenant, parent_id=ids[0]) is None


def test_retry_charges_one_preview_with_its_revision_and_job_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "provider_error")
    previews = _scalar(
        tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand
    )

    PartRecovery(parts).retry_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)

    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == DRAFTING
    assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:c", c=ids[1]) == 2
    assert (
        _scalar(tenant, "SELECT failure_detail FROM content_drafts WHERE id=:c", c=ids[1]) is None
    )
    assert (
        _scalar(tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand)
        == previews + 1
    )
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creative_jobs WHERE draft_id=:c AND revision=2",
            c=ids[1],
        )
        == 1
    )
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None and progress.parts[1].state is PartState.QUEUED


def test_a_retry_the_month_cannot_pay_writes_nothing_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "provider_error")
    _use_previews(tenant, brand, 16)  # 4 parts + 16 = the month's 20
    with pytest.raises(NotEnoughCreations):
        PartRecovery(parts).retry_part(
            tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
        )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == "failed"
    assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:c", c=ids[1]) == 1
    assert _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=:c", c=ids[1]) == 1


def test_another_business_cannot_retry_a_part_db(world, monkeypatch) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "provider_error")
    other, _other_brand, other_user = _business(monkeypatch)
    with pytest.raises(Exception):  # noqa: B017  (UnknownDraft: RLS hides it)
        PartRecovery(parts).retry_part(
            tenant_id=other, parent_id=parent, part_index=2, user_id=other_user
        )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == "failed"


def test_a_purged_video_refuses_a_retry_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "provider_error")
    _exec(tenant, "UPDATE content_drafts SET media_purged_at=now() WHERE id=:p", p=parent)
    with pytest.raises(PartChangeRefused):
        PartRecovery(parts).retry_part(
            tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
        )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == "failed"


def test_a_purged_part_refuses_a_retry_db(world) -> None:  # noqa: ANN001
    """The part's OWN purge mark is read under its lock, not only its video's."""
    _service_, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "provider_error")
    _exec(tenant, "UPDATE content_drafts SET media_purged_at=now() WHERE id=:c", c=ids[1])
    charges = _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE brand_id=:b", b=brand)
    with pytest.raises(PartChangeRefused):
        PartRecovery(parts).retry_part(
            tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
        )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == "failed"
    assert (
        _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE brand_id=:b", b=brand)
        == charges
    )


def test_a_refused_new_part_is_not_retried_with_its_photos_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "refused_face")
    with pytest.raises(PartChangeRefused, match=PART_SAME_PHOTOS_TEXT):
        PartRecovery(parts).retry_part(
            tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
        )
    assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:c", c=ids[1]) == 1


def test_make_new_stamps_the_new_pipeline_version_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    # an «Igual al original» part the original could not be used for
    _exec(
        tenant,
        "UPDATE content_briefs SET media = jsonb_set(jsonb_set(jsonb_set(media, "
        "'{part,mode}', '\"edit\"'), '{part,analysis_id}', to_jsonb(CAST(:a AS text))), "
        "'{clip_reference_mode}', '\"edit\"') "
        "WHERE id = (SELECT brief_id FROM content_drafts WHERE id=:c)",
        a=str(uuid4()),
        c=ids[1],
    )
    _fail(tenant, ids[1], "refused_face")
    _exec(tenant, "UPDATE content_drafts SET pipeline_version='old' WHERE id=:c", c=ids[1])
    previews = _scalar(
        tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand
    )

    PartRecovery(parts).make_part_new(
        tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
    )

    assert (
        _scalar(tenant, "SELECT pipeline_version FROM content_drafts WHERE id=:c", c=ids[1])
        == PIPELINE_VERSION
    )
    assert (
        _scalar(
            tenant,
            "SELECT b.media->'part'->>'mode' FROM content_drafts d "
            "JOIN content_briefs b ON b.id = d.brief_id WHERE d.id=:c",
            c=ids[1],
        )
        == "reference"
    )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == DRAFTING
    assert (
        _scalar(tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand)
        == previews + 1
    )
