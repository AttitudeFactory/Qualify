"""m-24921082 (UI-7) against Postgres: the result screen of a video by parts is read
under the owning business (RLS) — every part with its state, the parts with a vista
previa, a part waiting in line — and «Intentar de nuevo» / «Hacerla nueva» on a failed
part charge one vista previa in the same transaction as the new revision and its job.

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.creative import retention
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.part_actions import (
    PART_BEING_MADE_TEXT,
    PART_CAME_OUT_TEXT,
    PART_LAST_TEXT,
    PART_SAME_PHOTOS_TEXT,
    PartRecovery,
)
from qualify_api.creative.part_join import DbPartJoins
from qualify_api.creative.part_progress import PartAction, PartState, read_part_progress
from qualify_api.creative.parts import PartChangeRefused
from qualify_api.creative.service import PIPELINE_VERSION, UnknownDraft

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


def test_a_part_with_a_preview_reads_its_video_poster_and_length_db(world) -> None:  # noqa: ANN001
    """m-24992894: the row of a part to review carries the active video's key, its
    `thumbnail_key` as poster and its `duration_seconds`; a `preview_key` that is the
    video itself (no thumbnail kept) is never a poster; a part not made carries none."""
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    for child in ids[:2]:
        _exec(
            tenant,
            "UPDATE image_assets SET media_type = 'video', object_key = :v WHERE draft_id = :c",
            v=f"t/{tenant}/generated/{child}/r1/clip.mp4",
            c=child,
        )
    first, second = ids[0], ids[1]
    _exec(
        tenant,
        "UPDATE image_assets SET params = COALESCE(params, '{}'::jsonb) || jsonb_build_object("
        "'thumbnail_key', CAST(:t AS text), 'duration_seconds', '6', "
        "'draft', jsonb_build_object('status', 'draft', 'created_at', "
        "extract(epoch FROM now())::bigint, 'duration_seconds', 6)) WHERE draft_id = :c",
        t=f"t/{tenant}/generated/{first}/r1/first-frame.jpg",
        c=first,
    )
    _exec(
        tenant,
        "UPDATE image_assets SET params = (COALESCE(params, '{}'::jsonb) - 'thumbnail_key' "
        "- 'draft') || jsonb_build_object('duration_seconds', '4.5') WHERE draft_id = :c",
        c=second,
    )
    _exec(
        tenant,
        "UPDATE content_drafts SET preview_key = :k WHERE id = :c",
        k=f"t/{tenant}/generated/{second}/r1/clip.mp4",
        c=second,
    )

    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None
    one, two, three = progress.parts[:3]
    assert one.state is PartState.TO_REVIEW and one.has_preview
    assert one.preview_video_key == f"t/{tenant}/generated/{first}/r1/clip.mp4"
    assert one.preview_poster_key == f"t/{tenant}/generated/{first}/r1/first-frame.jpg"
    assert one.preview_seconds == 6.0
    assert two.has_preview
    assert two.preview_video_key == f"t/{tenant}/generated/{second}/r1/clip.mp4"
    assert two.preview_poster_key == ""  # the mp4 in `preview_key` is not a poster
    assert two.preview_seconds == 4.5
    assert not three.has_preview
    assert (three.preview_video_key, three.preview_poster_key, three.preview_seconds) == (
        "",
        "",
        None,
    )


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


# ---------------------------------------------------------------------------
# «Quitar parte» (m-24985192)


def _counts(tenant: UUID, child: UUID) -> tuple[object, ...]:
    return tuple(
        _scalar(tenant, f"SELECT count(*) FROM {table} WHERE draft_id=:c", c=child)
        for table in ("creation_charges", "creative_jobs", "piece_versions", "image_assets")
    )


def test_remove_marks_the_part_and_the_video_goes_on_without_it_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    for child in (ids[0], ids[2], ids[3]):
        service.run_generation(tenant_id=tenant, draft_id=child)
    _fail(tenant, ids[1], "provider_error")
    kept_rows = _counts(tenant, ids[1])

    assert PartRecovery(parts).remove_part(
        tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
    )

    assert _scalar(tenant, "SELECT part_removed_by FROM content_drafts WHERE id=:c", c=ids[1]) == (
        user
    )
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:c", c=ids[1]) == "failed"
    assert _counts(tenant, ids[1]) == kept_rows  # charges, jobs, versions: all kept
    # the join is asked again, without the part
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creative_pipeline_runs WHERE draft_id=:p AND phase='join'",
            p=parent,
        )
        == 1
    )
    snapshot = DbPartJoins().read(tenant_id=tenant, parent_id=parent)
    assert snapshot is not None and snapshot.removed == frozenset({2})
    assert [p.part_index for p in snapshot.parts] == [1, 3, 4]
    assert snapshot.kept_indexes == (1, 3, 4)
    assert [c.id for c in service.repository.parts_of(tenant_id=tenant, parent_id=parent)] == [
        ids[0],
        ids[2],
        ids[3],
    ]
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None
    assert [(p.index, p.shown, p.total) for p in progress.parts] == [
        (1, 1, 3),
        (3, 2, 3),
        (4, 3, 3),
    ]
    assert [s.label for s in parts.parts(tenant_id=tenant, parent_id=parent)] == [
        "Parte 1 de 3",
        "Parte 2 de 3",
        "Parte 3 de 3",
    ]


def test_remove_is_idempotent_and_refuses_what_it_must_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    recovery = PartRecovery(parts)
    with pytest.raises(PartChangeRefused, match=PART_CAME_OUT_TEXT):
        recovery.remove_part(tenant_id=tenant, parent_id=parent, part_index=1, user_id=user)
    with pytest.raises(PartChangeRefused, match=PART_BEING_MADE_TEXT):
        recovery.remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)
    for child in ids[1:]:
        _fail(tenant, child, "timeout")
    for index in (2, 3):
        assert recovery.remove_part(
            tenant_id=tenant, parent_id=parent, part_index=index, user_id=user
        )
    assert not recovery.remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)
    _fail(tenant, ids[0], "timeout")
    assert recovery.remove_part(tenant_id=tenant, parent_id=parent, part_index=1, user_id=user)
    with pytest.raises(PartChangeRefused, match=PART_LAST_TEXT):
        recovery.remove_part(tenant_id=tenant, parent_id=parent, part_index=4, user_id=user)
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p "
            "AND part_removed_at IS NULL",
            p=parent,
        )
        == 1
    )


def test_another_business_cannot_remove_a_part_db(world, monkeypatch) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "timeout")
    other, _other_brand, _other_user = _business(monkeypatch)
    with pytest.raises(UnknownDraft):
        PartRecovery(parts).remove_part(
            tenant_id=other, parent_id=parent, part_index=2, user_id=user
        )
    assert (
        _scalar(tenant, "SELECT part_removed_at FROM content_drafts WHERE id=:c", c=ids[1]) is None
    )


def test_a_purged_video_refuses_a_removal_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "timeout")
    _exec(tenant, "UPDATE content_drafts SET media_purged_at=now() WHERE id=:p", p=parent)
    with pytest.raises(PartChangeRefused):
        PartRecovery(parts).remove_part(
            tenant_id=tenant, parent_id=parent, part_index=2, user_id=user
        )


def test_an_orphan_extend_becomes_new_with_a_brief_of_its_own_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    # part 3 «Sigue a la anterior» part 2 (set on its stored brief: the plan of the world
    # has none)
    _exec(
        tenant,
        "UPDATE content_briefs SET media = jsonb_set(jsonb_set(media, '{part,mode}', "
        "'\"extend\"'), '{clip_reference_mode}', '\"extend\"') "
        "WHERE id = (SELECT brief_id FROM content_drafts WHERE id=:c)",
        c=ids[2],
    )
    _fail(tenant, ids[1], "timeout")
    _fail(tenant, ids[2], "timeout")
    before = _scalar(tenant, "SELECT brief_id FROM content_drafts WHERE id=:c", c=ids[2])

    PartRecovery(parts).remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)

    after = _scalar(tenant, "SELECT brief_id FROM content_drafts WHERE id=:c", c=ids[2])
    assert after != before
    mode = "SELECT media->'part'->>'mode' FROM content_briefs WHERE id=:b"
    assert _scalar(tenant, mode, b=after) == "reference"
    assert _scalar(tenant, mode, b=before) == "extend"  # the old brief stays


def test_only_a_part_can_carry_the_mark_db(world) -> None:  # noqa: ANN001
    _service_, _parts, _, tenant, _brand, user, parent = world
    with pytest.raises(IntegrityError):
        _exec(
            tenant,
            "UPDATE content_drafts SET part_removed_at=now(), part_removed_by=:u WHERE id=:p",
            u=user,
            p=parent,
        )


def test_retention_dates_the_video_without_its_removed_part_db(world) -> None:  # noqa: ANN001
    _service_, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    _fail(tenant, ids[1], "timeout")
    PartRecovery(parts).remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)
    with tenant_session(tenant) as session:
        families = retention._parts_of(session, [parent])
        purged_with_it = retention._unpurged_parts(session, [parent])
    assert ids[1] not in families[parent]  # its files do not date the video
    assert ids[1] in purged_with_it[parent]  # but the purge takes them with it


def test_a_family_whose_only_files_are_a_removed_parts_still_expires_db(world) -> None:  # noqa: ANN001
    """Review fix: when only the removed part holds files, they date the family — the
    purge finds it and its files never stay in R2 forever."""
    service, parts, _, tenant, _brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _exec(
        tenant,
        "UPDATE image_assets SET object_key = :k, "
        "created_at = now() - interval '200 days' WHERE draft_id = :c",
        k=f"t/{tenant}/generated/{ids[1]}/old.mp4",
        c=ids[1],
    )
    # the video itself has no file (its text only) and the other parts were never made
    assert _scalar(tenant, "SELECT count(*) FROM image_assets WHERE draft_id <> :c", c=ids[1]) == 0
    _fail(tenant, ids[1], "timeout")
    PartRecovery(parts).remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)

    with tenant_session(tenant) as session:
        facts = retention.read_facts(session, tenant, [parent])
        found = retention._candidate_ids(session, tenant, datetime.now(UTC), 50)
    assert facts[parent].generated_at is not None
    assert retention.evaluate(facts[parent], datetime.now(UTC)).state is (
        retention.RetentionState.EXPIRED
    )
    assert parent in found


def test_create_the_missing_parts_skips_a_removed_one_db(world) -> None:  # noqa: ANN001
    """m-24921081 × m-24985192: parts 1-3 created, part 2 removed; «Crear las que
    faltan» makes only part 4 (one vista previa), never part 2 again."""
    from qualify_api.creative.part_request import refusal_of
    from qualify_api.creative.parts import PartRemoved

    _service_, parts, _, tenant, brand, user, parent = world
    first = parts.create_parts(
        tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=(1, 2, 3)
    )
    _fail(tenant, first[1], "timeout")
    PartRecovery(parts).remove_part(tenant_id=tenant, parent_id=parent, part_index=2, user_id=user)
    charges = "SELECT count(*) FROM creation_charges WHERE brand_id=:b"
    before = _scalar(tenant, charges, b=brand)

    with pytest.raises(PartRemoved) as refused:
        parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user, part_indexes=(2,))
    assert refusal_of(refused.value) == ("removed", 2, 0)
    assert _scalar(tenant, charges, b=brand) == before

    made = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert made[:2] == [first[0], first[2]] and len(made) == 3
    assert _scalar(tenant, charges, b=brand) == before + 1  # part 4 only
    rows = "SELECT part_index FROM content_drafts WHERE parent_draft_id=:p ORDER BY part_index"
    with tenant_session(tenant) as session:
        indexes = session.execute(text(rows), {"p": parent}).scalars().all()
    assert indexes == [1, 2, 3, 4]  # the removed part 2 is still the one row
    progress = read_part_progress(tenant_id=tenant, parent_id=parent)
    assert progress is not None and [p.index for p in progress.parts] == [1, 3, 4]
    assert all(PartAction.CREATE not in p.actions for p in progress.parts)
    # asking again is idempotent: nothing more is made or charged
    assert parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user) == made
    assert _scalar(tenant, charges, b=brand) == before + 1
