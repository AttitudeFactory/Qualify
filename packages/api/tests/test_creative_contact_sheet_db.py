"""EF-18 (m-25026598) against Postgres: `DbContactSheets.read` — the sheet of the video a
draft shows, through the tenant door.

- the parent of a video by parts («Tu video completo»): its joined preview's sheet;
- another business reads nothing (RLS);
- a purged piece offers no sheet (`media_purged_at`);
- only the visible version counts (`visible_version`): a part made again shows no sheet
  until its new video has one, and restoring the earlier version brings its sheet back.

The world is `test_creative_part_join_db`'s (real service, worker pass, `DbPartJoins`);
the sheet blocks are stamped on the rows here (the sheet itself is tested offline)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.contact_sheet import DbContactSheets
from qualify_api.creative.parts import PartChanges

from .test_creative_part_join_db import _joins, _scalar, _worker_pass, world  # noqa: F401

pytestmark = pytest.mark.db


def _stamp(tenant: UUID, asset_id: Any, object_key: str) -> None:
    """A sheet block tied to `object_key` on the asset row `asset_id`."""
    block = {
        "version": "contact-sheet-2",
        "source": {"stage": "test", "object_key": object_key},
        "frames": [
            {"key": f"{object_key}-contact-{n}.jpg", "time_s": float(n)} for n in range(1, 7)
        ],
        "sheet": {"key": f"{object_key}-contact-sheet.jpg"},
    }
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE image_assets SET params = params || "
                "jsonb_build_object('contact_sheet', CAST(:block AS jsonb)) WHERE id = :id"
            ),
            {"block": json.dumps(block), "id": asset_id},
        )


def _assets(tenant: UUID, draft: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("SELECT id, object_key FROM image_assets WHERE draft_id = :d"), {"d": draft}
            ).all()
        )


def test_the_parent_shows_its_joined_previews_sheet_to_its_own_business_db(world) -> None:  # noqa: ANN001, F811
    service, _, _, _, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (row,) = _joins(tenant, parent)
    reader = DbContactSheets()
    assert reader.read(tenant_id=tenant, draft_id=parent) is None  # no sheet yet

    _stamp(tenant, row.id, row.object_key)
    view = reader.read(tenant_id=tenant, draft_id=parent)
    assert view is not None and view.video_key == row.object_key
    assert len(view.frames) == 6 and view.sheet_key.endswith("contact-sheet.jpg")

    # another business reads nothing (RLS)
    assert reader.read(tenant_id=uuid4(), draft_id=parent) is None

    # a purged piece offers no sheet
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET media_purged_at = now() WHERE id = :p"), {"p": parent}
        )
    assert reader.read(tenant_id=tenant, draft_id=parent) is None


def test_only_the_visible_versions_sheet_is_offered_db(world) -> None:  # noqa: ANN001, F811
    service, parts, _, _, tenant, user, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (first,) = _assets(tenant, ids[1])
    _stamp(tenant, first.id, first.object_key)
    reader = DbContactSheets()
    view = reader.read(tenant_id=tenant, draft_id=ids[1])
    assert view is not None and view.video_key == first.object_key

    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=user,
    )
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    assert len(_assets(tenant, ids[1])) == 2
    assert reader.read(tenant_id=tenant, draft_id=ids[1]) is None  # the new video has none

    v1 = _scalar(tenant, "SELECT id FROM piece_versions WHERE draft_id=:d AND revision=1", d=ids[1])
    service.restore_version(tenant_id=tenant, draft_id=ids[1], version_id=v1)  # type: ignore[arg-type]
    view = reader.read(tenant_id=tenant, draft_id=ids[1])
    assert view is not None and view.video_key == first.object_key
