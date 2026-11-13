"""The stored base photographs of a piece (m-25017279, ADR 49 §2 item 1, migration 0164).

A base is the raw Seedream photograph a still was composed over. It is described in its
own table, `piece_base_photos` — one row per version and position, `stored` (its R2 key,
SHA-256, type, size) or `missing` (paid for, but R2 did not keep it) — never in
`image_assets`, so no reader of a piece's outputs (cover, media list, carousel children,
Planificador, export) can see one: there is nothing for them to filter.
`piece_layers.base_asset_id` points here (ADR 49 §2.1).

A `missing` base is never silent: the row says so (a re-compose will offer only «Crear
otra» for that slide) and `report_missing_base` tells the team through the same channel as
the plan and vendor alerts (`plans.notify`, Lark).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from qualify_api.creative import models as orm
from qualify_api.creative.media import MediaWrite

logger = logging.getLogger(__name__)

STORED = "stored"
MISSING = "missing"
#: The pipeline that writes base rows (provenance; ADR 49 §2.3, stage `base`).
BASE_PIPELINE_VERSION = "image-pipeline-base-v1"


def _team_notifier() -> object:
    from qualify_api.plans.notify import production_team_notifier  # noqa: PLC0415

    return production_team_notifier()


#: Swappable in tests (`RecordingTeamNotifier`); production reads the team webhook.
notifier_factory: Callable[[], object] = _team_notifier


def report_missing_base(tenant_id: UUID, draft_id: UUID, name: str) -> None:
    """An operational alert: a paid base photo was not kept. Never raises — an alert that
    cannot be sent is logged, the piece goes on. Ids only: no client data."""
    text = (
        f"Foto base no guardada (m-25017279): negocio {tenant_id}, pieza {draft_id}, "
        f"{name}. R2 no la aceptó; la pieza sigue sin ella y no se podrá recomponer."
    )
    logger.error(
        "base photo not kept: tenant=%s draft=%s name=%s",
        tenant_id,
        draft_id,
        name,
        extra={"metric": "creative.base_photo.missing"},
    )
    try:
        notifier = notifier_factory()
        notify = getattr(notifier, "notify", None)
        if callable(notify):
            notify(text)
    except Exception:  # noqa: BLE001 - an alert never breaks a paid piece
        logger.warning("base photo alert not sent for draft %s", draft_id, exc_info=True)


def add_base_photos(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> int:
    """One `piece_base_photos` row per still that carries a base, at the still's position.
    Written once per version: a completed version is immutable, and
    `uq_piece_base_photos_position` refuses a second base at one position."""
    rows = [
        orm.PieceBasePhoto(
            tenant_id=tenant_id,
            brand_id=brand_id,
            draft_id=draft_id,
            version_id=version_id,
            position=item.position,
            state=STORED if item.base.key is not None else MISSING,
            object_key=item.base.key,
            # what was paid for, also when R2 did not keep it
            sha256=item.base.sha256,
            content_type=item.base.content_type,
            width=item.base.width,
            height=item.base.height,
            rendered_prompt=item.base.rendered_prompt,
            model_id=item.base.model_id,
            provider=item.base.provider,
            prompt_compiler_version=item.base.prompt_compiler_version,
            pipeline_version=BASE_PIPELINE_VERSION,
            missing_reason=item.base.missing_reason if item.base.key is None else None,
        )
        for item in media
        if item.base is not None
    ]
    session.add_all(rows)
    if rows:
        session.flush()
    return len(rows)
