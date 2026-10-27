"""Persisted publication versions; previewing and restoring never generate media."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from qualify_api.creative import models as orm
from qualify_api.creative.fsm import DraftTrigger, apply_transition


def snapshot_current(
    session: Session, draft: orm.ContentDraft, *, revision: int | None = None
) -> None:
    """Attach legacy content before another generation can replace its rows."""
    copies = list(
        session.scalars(
            select(orm.CopyVariant).where(
                orm.CopyVariant.draft_id == draft.id, orm.CopyVariant.version_id.is_(None)
            )
        )
    )
    media = list(
        session.scalars(
            select(orm.ImageAsset).where(
                orm.ImageAsset.draft_id == draft.id, orm.ImageAsset.version_id.is_(None)
            )
        )
    )
    if not copies and not media:
        return
    if draft.active_version_id is not None:
        for row in (*copies, *media):
            row.version_id = draft.active_version_id
        session.flush()
        return
    number = (
        revision
        if revision is not None
        else (
            max(1, draft.revision - 1) if draft.status in {"drafting", "failed"} else draft.revision
        )
    )
    version = session.scalar(
        select(orm.PieceVersion).where(
            orm.PieceVersion.draft_id == draft.id, orm.PieceVersion.revision == number
        )
    )
    if version is None:
        first = copies[0] if copies else media[0]
        version = orm.PieceVersion(
            id=uuid4(),
            tenant_id=draft.tenant_id,
            brand_id=draft.brand_id,
            draft_id=draft.id,
            revision=number,
            status="active",
            model_id=first.model_id or "",
            model_revision=(
                getattr(first, "model_revision", None)
                or (getattr(first, "params", None) or {}).get("model_revision")
            ),
            pipeline_version=draft.pipeline_version,
            requires_ai_disclosure=draft.requires_ai_disclosure,
            spent_usd=session.scalar(
                select(func.coalesce(func.sum(orm.CreativeUsageEvent.cost_usd), 0)).where(
                    orm.CreativeUsageEvent.draft_id == draft.id,
                    orm.CreativeUsageEvent.created_at == first.created_at,
                )
            )
            or Decimal(0),
            created_at=first.created_at,
        )
        session.add(version)
        session.flush()
    for row in (*copies, *media):
        row.version_id = version.id
    draft.active_version_id = version.id
    session.flush()


def visible_version(model: type[Any]) -> ColumnElement[bool]:
    """Restrict operational reads to the selected version, with a legacy fallback."""
    selected = (
        select(orm.ContentDraft.active_version_id)
        .where(orm.ContentDraft.id == model.draft_id)
        .correlate(model)
        .scalar_subquery()
    )
    return (model.version_id == selected) | model.version_id.is_(None)


def version_row(session: Session, draft_id: UUID, version_id: UUID) -> orm.PieceVersion:
    row = session.scalar(
        select(orm.PieceVersion).where(
            orm.PieceVersion.id == version_id, orm.PieceVersion.draft_id == draft_id
        )
    )
    if row is None or row.status != "active":
        raise ValueError("Esta versi\u00f3n no est\u00e1 disponible.")
    return row


def restore(session: Session, draft_id: UUID, version_id: UUID) -> None:
    from qualify_api.planner.models import CalendarEvent

    # Same lock order as regeneration/calendar publication.
    events = session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.post_id == draft_id)
        .order_by(CalendarEvent.id)
        .with_for_update()
    ).all()
    draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
    if draft is None:
        raise ValueError("La publicaci\u00f3n ya no est\u00e1 disponible.")
    if draft.media_purged_at is not None:
        raise ValueError("Los archivos de esta publicaci\u00f3n ya no est\u00e1n disponibles.")
    if any(event.status in {"scheduled", "publishing"} for event in events):
        raise ValueError("Cancela la programaci\u00f3n antes de cambiar la versi\u00f3n.")
    if draft.status not in {"generated", "rejected", "failed", "approved"}:
        raise ValueError("Espera a que termine la generaci\u00f3n antes de usar otra versi\u00f3n.")
    version = version_row(session, draft_id, version_id)
    if draft.active_version_id == version.id and draft.status == "generated":
        return
    draft.status = apply_transition(draft.status, DraftTrigger.RESTORE_VERSION)
    draft.active_version_id = version.id
    draft.revision += 1
    draft.selected_variant_id = None
    draft.approved_revision = None
    draft.approved_by = None
    draft.approved_at = None
    draft.failure_reason = None
    draft.failure_detail = None
    draft.requires_ai_disclosure = version.requires_ai_disclosure
    draft.pipeline_version = version.pipeline_version
    media = session.scalars(
        select(orm.ImageAsset)
        .where(orm.ImageAsset.draft_id == draft.id, orm.ImageAsset.version_id == version.id)
        .order_by(orm.ImageAsset.position)
    ).all()
    draft.preview_key = next((item.object_key for item in media if item.object_key), None)
