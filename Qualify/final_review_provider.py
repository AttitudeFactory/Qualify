"""Final-review panel's real, tenant-scoped reads and explicit human commands."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.creative.composition import production_content_service
from qualify_api.creative.draft_mode import draft_state, draft_summary
from qualify_api.creative.final_review import FinalIdentity, final_confirmed, review_candidates
from qualify_api.creative.models import ContentDraft, ImageAsset
from qualify_api.planner.composition import tenant_timezone
from qualify_api.planner.models import CalendarEvent
from qualify_api.tenancy.models import TenantMember
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .creative_vm import renewal_day_label
from .final_review_vm import (
    FinalPanelVM,
    FinalVideoVM,
    another_version_use,
    confirmation_note,
    final_state,
    other_version_pending,
)
from .planner_vm import time_label_12h
from .r2_media import issue_view_path
from .review_links import review_href


def candidate_ids(tenant_id: UUID) -> tuple[str, ...]:
    return tuple(str(value) for value in review_candidates(tenant_id=tenant_id))


def event_piece(tenant_id: UUID, event_id: UUID) -> UUID | None:
    with tenant_session(tenant_id) as session:
        return session.scalar(select(CalendarEvent.post_id).where(CalendarEvent.id == event_id))


def load_final_panel(
    tenant_id: UUID, piece_id: UUID, user_id: UUID, *, now: datetime | None = None
) -> tuple[FinalPanelVM, tuple[FinalIdentity, ...]]:
    at = now or datetime.now(UTC)
    service = production_content_service()
    with tenant_session(tenant_id) as session:
        piece = session.get(ContentDraft, piece_id)
        if piece is None:
            raise ValueError("No encontramos esta publicación en tu negocio.")
        title, status, brand_id = piece.title or "Tu publicación", piece.status, piece.brand_id
        assets = list(
            session.scalars(
                select(ImageAsset)
                .where(ImageAsset.draft_id == piece_id)
                .order_by(ImageAsset.position)
            )
        )
        params = [asset.params for asset in assets]
        keys = [asset.object_key for asset in assets if draft_state(asset.params)]
        events = list(
            session.scalars(
                select(CalendarEvent)
                .where(CalendarEvent.post_id == piece_id, CalendarEvent.status == "scheduled")
                .order_by(CalendarEvent.scheduled_at)
            )
        )
        dates = [event.scheduled_at for event in events]
        event_id = str(events[0].id) if events else ""
        member = session.scalar(select(TenantMember).where(TenantMember.user_id == user_id))
        approver = member is not None and member.role in {"owner", "admin"}
        state = draft_summary(params, approved=status == "approved")[0]
        if status in {"drafting", "generated", "rejected"}:
            state = "other_version"
        elif state == "final" and any(
            not final_confirmed(asset.params, object_key=asset.object_key, revision=piece.revision)
            for asset in assets
            if draft_state(asset.params)
        ):
            state = "final_ready"
        nightly = any((draft_state(param) or {}).get("final_nightly") for param in params)
    zone = ZoneInfo(tenant_timezone(tenant_id))
    local = at.astimezone(zone)
    earliest = dates[0].astimezone(zone) if dates else None
    overdue = any(moment <= at < moment + timedelta(hours=24) for moment in dates)
    expired = bool(dates) and all(moment + timedelta(hours=24) <= at for moment in dates)
    day = (
        ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[
            earliest.weekday()
        ]
        + f" {earliest.day}"
        if earliest
        else ""
    )
    hour = time_label_12h(earliest) if earliest else ""
    badge, tone, note = final_state(
        state,
        nightly=nightly,
        during_night=local.hour < 6,
        overdue=overdue,
        expired=expired,
        hour=hour,
    )
    manifest: tuple[FinalIdentity, ...] = ()
    if state in {"final_ready", "final"} and approver:
        manifest = service.review_final(tenant_id=tenant_id, draft_id=piece_id, user_id=user_id)
        keys = [item.object_key for item in manifest]
    videos = tuple(
        FinalVideoVM(issue_view_path(tenant_id, key), f"Video {index + 1}")
        for index, key in enumerate(keys)
        if key and state != "other_version"
    )
    balance = service.creations_balance(tenant_id=tenant_id, brand_id=brand_id)
    left = balance.videos_left if balance is not None else None
    previews = balance.previews_left if balance is not None else None
    can_another = (
        approver
        and state in {"final_ready", "final"}
        and (left is None or left > 0)
        and (previews is None or previews > 0)
    )
    candidates = candidate_ids(tenant_id)
    remaining = [value for value in candidates if value != str(piece_id)]
    pending = other_version_pending(
        day=day,
        hour=hour,
        today=bool(earliest and earliest.date() == local.date()),
        dates=len(dates),
    )
    date_note = f"Sale el {day} a las {hour.rstrip(chr(46))}." if earliest else "Todavía sin fecha"
    return FinalPanelVM(
        piece_id=str(piece_id),
        title=title,
        state=state,
        badge=badge,
        tone=tone,
        note=note,
        videos=videos,
        date_note=date_note,
        can_confirm=bool(manifest) and state == "final_ready" and not expired,
        can_retry=state == "failed"
        and approver
        and not any(
            (draft_state(param) or {}).get("error")
            == "Cancelamos tu video. Te devolvimos la creación."
            for param in params
        ),
        can_another=can_another,
        another_note=(
            another_version_use(
                left, quota=balance.video_quota, renews=renewal_day_label(balance.renews_on)
            )
            if left is not None and balance is not None
            else ""
        ),
        confirm_label="Confirmar y publicar ahora" if overdue else "Confirmar video",
        confirmed_note=confirmation_note(dates=len(dates), day=day, hour=hour),
        reschedule_href=review_href(str(piece_id)),
        event_id=event_id,
        next_count=len(remaining),
        next_label=f"Revisar el siguiente ({len(remaining)} más)" if remaining else "Ver Tu semana",
        other_version_pending=pending if state == "other_version" else "",
    ), manifest


def confirm_review(
    tenant_id: UUID, piece_id: UUID, user_id: UUID, manifest: tuple[FinalIdentity, ...]
) -> None:
    production_content_service().confirm_final(
        tenant_id=tenant_id, draft_id=piece_id, user_id=user_id, expected=manifest
    )


def retry_review(tenant_id: UUID, piece_id: UUID) -> None:
    production_content_service().retry_final(tenant_id=tenant_id, draft_id=piece_id)


def request_another(tenant_id: UUID, piece_id: UUID, user_id: UUID) -> None:
    service = production_content_service()
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, piece_id)
        member = session.scalar(select(TenantMember).where(TenantMember.user_id == user_id))
        if draft is None or member is None or member.role not in {"owner", "admin"}:
            raise PermissionError("Solo los dueños y administradores pueden pedir otra versión.")
        brand_id = draft.brand_id
    balance = service.creations_balance(tenant_id=tenant_id, brand_id=brand_id)
    if balance is not None and (balance.videos_left < 1 or balance.previews_left < 1):
        raise ValueError(another_version_use(balance.videos_left))
    service.reject(
        tenant_id=tenant_id,
        draft_id=piece_id,
        user_id=user_id,
        reason="otra versión del video final",
        regenerate=True,
    )


def failed_candidate_ids(tenant_id: UUID) -> tuple[str, ...]:
    with tenant_session(tenant_id) as session:
        values = session.scalars(
            select(ContentDraft.id)
            .join(ImageAsset, ImageAsset.draft_id == ContentDraft.id)
            .where(
                ContentDraft.status == "approved",
                ImageAsset.params["draft"]["status"].astext == "failed",
            )
            .distinct()
            .order_by(ContentDraft.id)
        )
        return tuple(str(value) for value in values)


def pending_version_note(tenant_id: UUID, piece_id: UUID) -> str:
    with tenant_session(tenant_id) as session:
        dates = list(
            session.scalars(
                select(CalendarEvent.scheduled_at)
                .where(CalendarEvent.post_id == piece_id, CalendarEvent.status == "scheduled")
                .order_by(CalendarEvent.scheduled_at)
            )
        )
    local = datetime.now(UTC).astimezone(ZoneInfo(tenant_timezone(tenant_id)))
    first = dates[0].astimezone(local.tzinfo) if dates else None
    day = (
        ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[first.weekday()]
        + f" {first.day}"
        if first
        else ""
    )
    if first is not None and first <= local < first + timedelta(hours=24):
        return f"No salió a las {time_label_12h(first)} porque falta que confirmes el video."
    return other_version_pending(
        day=day,
        hour=time_label_12h(first) if first else "",
        dates=len(dates),
        today=bool(first and first.date() == local.date()),
    )
