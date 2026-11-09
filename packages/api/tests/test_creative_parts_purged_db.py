"""m-24921069 against Postgres: no part of a video by parts is made, made again or
restored once the retention purge removed the video's files (`media_purged_at`) — the
founder's refusal `parts.PURGED_PARENT_TEXT`, nothing written or charged — and a part
generation that finishes after its video was purged attaches nothing: its paid work is
recorded and its folder is left to `retention.purge_pending_objects`."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.models import CreativeEngineConfig, CreativeVendorTask
from qualify_api.creative.parts import PURGED_PARENT_TEXT, PartChangeRefused, PartChanges
from qualify_api.creative.service import UsageWrite
from qualify_api.creative.versions import PURGED_FILES_TEXT

from .test_creative_parts_db import _scalar, world  # noqa: F401 — `world` is a fixture

pytestmark = pytest.mark.db


def _purge(tenant: UUID, draft: UUID) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET media_purged_at = now() WHERE id = :p"), {"p": draft}
        )


def _made(service, parts, tenant: UUID, user: UUID, parent: UUID) -> list[UUID]:  # noqa: ANN001
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    return ids


def test_no_part_is_made_under_a_purged_video_db(world) -> None:  # noqa: ANN001, F811
    _, parts, _, tenant, brand, user, parent = world
    _purge(tenant, parent)
    with pytest.raises(PartChangeRefused) as refused:
        parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert str(refused.value) == PURGED_PARENT_TEXT
    count = "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p"
    assert _scalar(tenant, count, p=parent) == 0
    charged = "SELECT count(*) FROM creation_charges WHERE brand_id=:b AND previews>0"
    assert _scalar(tenant, charged, b=brand) == 0


def test_no_part_is_made_again_or_restored_under_a_purged_video_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, tenant, _, user, parent = world
    ids = _made(service, parts, tenant, user, parent)
    version = _scalar(tenant, "SELECT active_version_id FROM content_drafts WHERE id=:d", d=ids[1])
    row = "SELECT brief_id, revision, status, active_version_id FROM content_drafts WHERE id=:d"
    with tenant_session(tenant) as session:
        before = tuple(session.execute(text(row), {"d": ids[1]}).one())
    _purge(tenant, parent)
    with pytest.raises(PartChangeRefused) as refused:
        parts.regenerate_part(
            tenant_id=tenant,
            parent_id=parent,
            part_index=2,
            changes=PartChanges(description="Otra toma."),
            user_id=user,
        )
    assert str(refused.value) == PURGED_PARENT_TEXT
    with pytest.raises(PartChangeRefused) as restored:
        service.restore_version(tenant_id=tenant, draft_id=ids[1], version_id=version)
    assert str(restored.value) == PURGED_PARENT_TEXT
    with tenant_session(tenant) as session:
        assert tuple(session.execute(text(row), {"d": ids[1]}).one()) == before


def test_a_whole_piece_keeps_its_own_purged_text_db(world) -> None:  # noqa: ANN001, F811
    service, _, _, tenant, _, _, parent = world
    version = _scalar(tenant, "SELECT active_version_id FROM content_drafts WHERE id=:d", d=parent)
    _purge(tenant, parent)
    with pytest.raises(ValueError) as refused:
        service.restore_version(tenant_id=tenant, draft_id=parent, version_id=version)
    assert str(refused.value) == PURGED_FILES_TEXT


def test_a_part_finishing_after_its_video_was_purged_attaches_nothing_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, tenant, _, user, parent = world
    ids = _made(service, parts, tenant, user, parent)
    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Otra toma."),
        user_id=user,
    )
    revision = _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=ids[1])
    assets = "SELECT count(*) FROM image_assets WHERE draft_id=:d"
    before = _scalar(tenant, assets, d=ids[1])
    _purge(tenant, parent)  # the purge ran while the worker was making it

    service.run_generation(tenant_id=tenant, draft_id=ids[1])

    assert _scalar(tenant, assets, d=ids[1]) == before
    versions = "SELECT count(*) FROM piece_versions WHERE draft_id=:d AND revision=:r"
    assert _scalar(tenant, f"{versions} AND status='active'", d=ids[1], r=revision) == 0
    marks = "SELECT media_purged_at IS NOT NULL AND media_objects_pending_at IS NOT NULL"
    assert _scalar(tenant, f"{marks} FROM content_drafts WHERE id=:d", d=ids[1]) is True


def test_a_dropped_generation_settles_its_task_and_records_its_spend_once_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, tenant, brand, user, parent = world
    ids = _made(service, parts, tenant, user, parent)
    part = ids[0]
    parts.regenerate_part(  # a new revision, now in the worker's hands
        tenant_id=tenant,
        parent_id=parent,
        part_index=1,
        changes=PartChanges(description="Otra toma."),
        user_id=user,
    )
    revision = _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=part)
    with tenant_session(tenant) as session:
        session.add(
            CreativeVendorTask(
                tenant_id=tenant,
                draft_id=part,
                revision=revision,
                slot="clip:0",
                provider="byteplus",
                model_id="seedance",
                vendor_task_id="task-1",
            )
        )
    usage_rows = "SELECT count(*) FROM creative_usage_events WHERE draft_id=:d"
    budget = "SELECT budget_spent_usd FROM creative_engine_config WHERE brand_id=:b"
    if _scalar(tenant, budget, b=brand) is None:  # `world` makes none: the spend needs one
        with tenant_session(tenant) as session:
            session.add(
                CreativeEngineConfig(
                    tenant_id=tenant,
                    brand_id=brand,
                    monthly_budget_cap_usd=Decimal("100"),
                    budget_spent_usd=Decimal("0"),
                )
            )
    rows_before, spent_before = (
        _scalar(tenant, usage_rows, d=part),
        _scalar(tenant, budget, b=brand),
    )
    assert spent_before is not None
    _purge(tenant, parent)
    usage = UsageWrite(
        provider="byteplus",
        model_id="seedance",
        unit="second",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal("0.50"),
        paid_by="platform",
        pricing_table_version="v1",
        pieces=5,
    )
    for _ in range(2):  # the same outcome delivered twice
        service.repository.finish_generation(
            tenant_id=tenant,
            draft_id=part,
            brand_id=brand,
            new_status=GENERATED,
            failure_reason=None,
            variants=(),
            usage=(usage,),
            spent_usd=Decimal("0.50"),
        )
    assert _scalar(tenant, usage_rows, d=part) == rows_before + 1
    assert _scalar(tenant, budget, b=brand) == spent_before + Decimal("0.50")  # once
    task = "SELECT status, settled_at IS NOT NULL FROM creative_vendor_tasks WHERE draft_id=:d"
    with tenant_session(tenant) as session:
        assert tuple(session.execute(text(task), {"d": part}).one()) == ("failed", True)
    dropped = "SELECT status, failure_reason FROM piece_versions WHERE draft_id=:d AND revision=:r"
    with tenant_session(tenant) as session:
        rows = session.execute(text(dropped), {"d": part, "r": revision}).all()
    assert [tuple(r) for r in rows] == [("failed", "cancelled")]
