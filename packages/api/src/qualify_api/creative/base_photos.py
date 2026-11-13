"""The stored base photographs of a piece (m-25017279, ADR 49 §2 item 1, migration 0164).

A base is the raw Seedream photograph a still was composed over. It lives in
`image_assets` as its own row — `role='base'`, the same version and position as the still
it made — so `piece_layers.base_asset_id` can point at it (ADR 49 §2.1) and the version
cascade and the retention purge (its object is under the piece's R2 folder) treat it like
any other file of the piece.

A base is never a piece's output: never its cover, never a carousel child, never what the
Planificador publishes or exports. That is not left to every reader remembering a filter:
the table's row-level policy (0164) hides `role='base'` rows from every query that has not
asked for them with `app.base_photos = 'on'`, for the transaction only
(`base_photos_visible`). `qualify_admin` bypasses RLS; its readers of `image_assets` (the
retention purge and its warning mail) either want every file of the folder or read only
`https://` URLs, which a base never has.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import text

from qualify_api.creative import models as orm
from qualify_api.creative.media import MediaWrite

OUTPUT_ROLE = "output"
BASE_ROLE = "base"
#: The transaction-local setting the 0164 policy reads.
BASE_PHOTOS_SETTING = "app.base_photos"


@contextmanager
def base_photos_visible(session: Any) -> Iterator[None]:
    """Let THIS transaction read and write `role='base'` rows, then hide them again."""
    session.execute(text("SELECT set_config(:name, 'on', true)"), {"name": BASE_PHOTOS_SETTING})
    # not in a `finally`: after an error the transaction is rolled back, and a
    # transaction-local setting goes with it (a statement there would only fail again)
    yield
    session.execute(text("SELECT set_config(:name, '', true)"), {"name": BASE_PHOTOS_SETTING})


def add_base_photos(
    session: Any,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> int:
    """One `role='base'` row per still that carries a kept base, at the still's position.
    Written once per version (a completed version is immutable, and
    `uq_image_assets_base_position` refuses a second base at one position)."""
    rows = [
        orm.ImageAsset(
            tenant_id=tenant_id,
            draft_id=draft_id,
            version_id=version_id,
            role=BASE_ROLE,
            media_url=item.base.key,
            object_key=item.base.key,
            content_type=item.base.content_type,
            model_id=item.base.model_id,
            provider=item.base.provider,
            rendered_prompt=item.base.rendered_prompt,
            media_type="image",
            position=item.position,
            aspect_ratio=item.aspect_ratio,
            params={
                "sha256": item.base.sha256,
                "prompt_compiler_version": item.base.prompt_compiler_version,
                # Seedream images are synchronous: no vendor task to resume or re-send
                "vendor_task_id": None,
            },
        )
        for item in media
        if item.base is not None
    ]
    if not rows:
        return 0
    with base_photos_visible(session):
        session.add_all(rows)
        session.flush()
    return len(rows)
