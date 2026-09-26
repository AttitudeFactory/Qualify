"""The seam between the Planificador screen and `qualify_api.planner` (QUA-108).

Same split as `publishing_provider.py`: plain synchronous functions over ids that the
state runs off the event loop (`asyncio.to_thread`). It reuses, unchanged:
- `connections_provider.connections_for` for the tenant's accounts;
- `creative_provider.default_brand_id` for the tenant's brand (1 tenant = 1 brand);
- `connections_provider.acting_user_id` for `created_by` (AuthState holds no user id).

It never publishes: the planner service it calls has no publish path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.planner.composition import production_planner_service, tenant_timezone
from qualify_api.planner.post_reader import PostSummary
from qualify_api.planner.service import (
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    InvalidSchedule,
    InvalidTag,
    PlannedEvent,
    PlannerError,
    PostNotSchedulable,
    UnknownEvent,
    UnknownPost,
    UnknownTag,
    compose_instant,
    resolve_zone,
    week_start,
)

from .connections_provider import acting_user_id, connections_for
from .creative_provider import default_brand_id
from .planner_vm import (
    CardInput,
    ConnectionChoiceVM,
    DayColumnVM,
    EventDetailVM,
    HourRowVM,
    PostOptionVM,
    TagVM,
    approval_label,
    build_post_option,
    build_week,
    category_label,
    content_type_label,
    date_label,
    month_label,
    status_label,
    time_label_12h,
    week_label,
)

ALL_CONNECTIONS = "all"


class NoBrand(PlannerError):
    """The tenant has no brand row yet — nothing to plan for."""


@dataclass(frozen=True)
class WeekData:
    monday_iso: str
    week_label: str
    month_label: str
    tz_name: str
    today_iso: str
    days: list[DayColumnVM] = field(default_factory=list)
    rows: list[HourRowVM] = field(default_factory=list)
    unscheduled: list[PostOptionVM] = field(default_factory=list)
    schedulable: list[PostOptionVM] = field(default_factory=list)
    connections: list[ConnectionChoiceVM] = field(default_factory=list)
    total_events: int = 0
    tenant_tz: str = ""  # the business's own zone — the picker's suggestion
    tags: list[TagVM] = field(default_factory=list)


def planner_error_message(exc: Exception) -> str:
    """Operator-facing Spanish for every refusal — what happened and what to do."""
    messages: list[tuple[type[Exception], str]] = [
        (NoBrand, "Este negocio todavía no tiene una marca configurada."),
        (UnknownPost, "Ese POST ya no está disponible. Actualiza la página."),
        (
            PostNotSchedulable,
            "Ese POST no se puede planificar: está en producción, falló o fue rechazado.",
        ),
        (
            InactiveConnection,
            "La cuenta elegida no está activa. Revísala en Conexiones o elige otra.",
        ),
        (InvalidSchedule, "La fecha y hora deben ser futuras y válidas en tu zona horaria."),
        (UnknownEvent, "Ese evento ya no existe. Actualiza la página."),
        (InvalidTag, "La etiqueta debe tener entre 1 y 40 caracteres."),
        (UnknownTag, "Esa etiqueta ya no existe. Actualiza la página."),
        (EventNotModifiable, "Ese evento ya no se puede modificar (no está programado)."),
        (
            EventConflict,
            "Alguien más modificó este evento al mismo tiempo. Actualiza y vuelve a intentarlo.",
        ),
    ]
    for kind, message in messages:
        if isinstance(exc, kind):
            return message
    return "No se pudo completar la acción. Inténtalo de nuevo."


def _require_brand(tenant_id: UUID) -> UUID:
    brand_id = default_brand_id(tenant_id)
    if brand_id is None:
        raise NoBrand(str(tenant_id))
    return brand_id


def _connection_index(
    tenant_id: UUID,
) -> tuple[dict[str, tuple[str, str]], list[ConnectionChoiceVM]]:
    """All the tenant's accounts (for labelling cards, whatever their status) and the
    active ones (the only ones an event may be planned onto)."""
    index: dict[str, tuple[str, str]] = {}
    active: list[ConnectionChoiceVM] = []
    for connection in connections_for(tenant_id):
        label = f"@{connection.external_username}" if connection.external_username else "Cuenta"
        index[connection.id] = (connection.platform, label)
        if connection.status == "active":
            active.append(
                ConnectionChoiceVM(id=connection.id, label=label, platform=connection.platform)
            )
    return index, active


def _post_option(post: PostSummary) -> PostOptionVM:
    return build_post_option(
        post_id=str(post.post_id),
        title=post.title,
        caption_excerpt=post.caption_excerpt,
        thumbnail_url=post.thumbnail_url,
        category=post.category,
        approval=post.approval.value,
        detail_href=post.detail_href,
    )


def _tag_vm(tag) -> TagVM:
    return TagVM(id=str(tag.id), name=tag.name, color=tag.color)


def view_zone(tenant_id: UUID, tz_override: str) -> str:
    """The zone the calendar shows and plans in: the operator's pick for this session if
    valid, else the business's own zone. Never written back to the tenant."""
    if tz_override:
        try:
            resolve_zone(tz_override)
            return tz_override
        except InvalidSchedule:
            pass
    return tenant_timezone(tenant_id)


def _card_input(planned: PlannedEvent) -> CardInput:
    event, post = planned.event, planned.post
    return CardInput(
        event_id=str(event.id),
        post_id=str(event.post_id),
        scheduled_at=event.scheduled_at,
        status=event.status,
        overdue=planned.overdue_unapproved,
        connection_id=str(event.connection_id),
        post_title=post.title if post is not None else None,
        caption_excerpt=post.caption_excerpt if post is not None else "",
        thumbnail_url=post.thumbnail_url if post is not None else None,
        category=post.category if post is not None else None,
        content_type=post.content_type if post is not None else None,
        approval=post.approval.value if post is not None else None,
        detail_href=post.detail_href if post is not None else "",
        tags=tuple(_tag_vm(t) for t in planned.tags),
    )


def load_week(
    tenant_id: UUID,
    monday_iso: str,
    connection_filter: str,
    tz_override: str = "",
    tag_filter: tuple[str, ...] = (),
) -> WeekData:
    """Everything the page renders for one week. `monday_iso == ""` means this week.

    Blocking (DB) — run off the event loop.
    """
    brand_id = _require_brand(tenant_id)
    tenant_tz = tenant_timezone(tenant_id)
    tz_name = view_zone(tenant_id, tz_override)
    zone = ZoneInfo(tz_name)
    today = datetime.now(UTC).astimezone(zone).date()
    monday = week_start(date.fromisoformat(monday_iso) if monday_iso else today)

    index, active = _connection_index(tenant_id)
    connection_id = (
        UUID(connection_filter)
        if connection_filter and connection_filter != ALL_CONNECTIONS
        else None
    )
    service = production_planner_service()
    planned = service.list_week(
        tenant_id=tenant_id,
        brand_id=brand_id,
        monday=monday,
        tz_name=tz_name,
        connection_id=connection_id,
        tag_ids=frozenset(UUID(t) for t in tag_filter if _is_uuid(t)),
    )
    schedulable = service.list_schedulable(tenant_id=tenant_id, brand_id=brand_id)
    unscheduled = service.list_unscheduled(tenant_id=tenant_id, brand_id=brand_id)
    grid = build_week(
        monday=monday,
        today=today,
        zone=zone,
        items=[_card_input(p) for p in planned],
        connections=index,
    )
    return WeekData(
        monday_iso=monday.isoformat(),
        week_label=week_label(monday),
        month_label=month_label(monday),
        tz_name=tz_name,
        today_iso=today.isoformat(),
        days=grid.days,
        rows=grid.rows,
        unscheduled=[_post_option(p) for p in unscheduled],
        schedulable=[_post_option(p) for p in schedulable],
        connections=active,
        total_events=len(planned),
        tenant_tz=tenant_tz,
        tags=[_tag_vm(t) for t in service.list_tags(tenant_id=tenant_id)],
    )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _parse_instant(day: str, at: str, tz_name: str) -> datetime:
    try:
        parsed_day = date.fromisoformat(day)
        parsed_time = time.fromisoformat(at)
    except ValueError as exc:
        raise InvalidSchedule(f"bad date/time {day!r} {at!r}") from exc
    return compose_instant(parsed_day, parsed_time, tz_name)


def _uuid(value: str, error: type[PlannerError]) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise error(value) from exc


def schedule_post(
    tenant_id: UUID,
    post_id: str,
    day: str,
    at: str,
    connection_id: str,
    tz_override: str = "",
    tag_ids: tuple[str, ...] = (),
) -> None:
    brand_id = _require_brand(tenant_id)
    tz_name = view_zone(tenant_id, tz_override)
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoBrand(str(tenant_id))
    service = production_planner_service()
    event = service.schedule(
        tenant_id=tenant_id,
        brand_id=brand_id,
        post_id=_uuid(post_id, UnknownPost),
        connection_id=_uuid(connection_id, InactiveConnection),
        scheduled_at=_parse_instant(day, at, tz_name),
        scheduled_tz=tz_name,
        user_id=user_id,
    )
    if tag_ids:
        service.set_event_tags(
            tenant_id=tenant_id,
            event_id=event.id,
            tag_ids=[_uuid(t, UnknownTag) for t in tag_ids],
        )


def reschedule_event(
    tenant_id: UUID,
    event_id: str,
    day: str,
    at: str,
    connection_id: str,
    tz_override: str = "",
    tag_ids: tuple[str, ...] = (),
) -> None:
    tz_name = view_zone(tenant_id, tz_override)
    service = production_planner_service()
    event = service.reschedule(
        tenant_id=tenant_id,
        event_id=_uuid(event_id, UnknownEvent),
        scheduled_at=_parse_instant(day, at, tz_name),
        scheduled_tz=tz_name,
        connection_id=_uuid(connection_id, InactiveConnection) if connection_id else None,
    )
    service.set_event_tags(
        tenant_id=tenant_id,
        event_id=event.id,
        tag_ids=[_uuid(t, UnknownTag) for t in tag_ids],
    )


def create_tag(tenant_id: UUID, name: str, color: str = "") -> TagVM:
    return _tag_vm(
        production_planner_service().create_tag(tenant_id=tenant_id, name=name, color=color)
    )


def delete_tag(tenant_id: UUID, tag_id: str) -> None:
    production_planner_service().delete_tag(tenant_id=tenant_id, tag_id=_uuid(tag_id, UnknownTag))


def set_event_tags(tenant_id: UUID, event_id: str, tag_ids: tuple[str, ...]) -> None:
    """Change only an event's labels (the detail dialog) — works for any event status,
    since labels do not change what or when anything is published."""
    production_planner_service().set_event_tags(
        tenant_id=tenant_id,
        event_id=_uuid(event_id, UnknownEvent),
        tag_ids=[_uuid(t, UnknownTag) for t in tag_ids],
    )


def delete_event(tenant_id: UUID, event_id: str) -> None:
    production_planner_service().delete(tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent))


def cancel_event(tenant_id: UUID, event_id: str) -> None:
    production_planner_service().cancel(tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent))


def event_detail(tenant_id: UUID, event_id: str, tz_override: str = "") -> EventDetailVM:
    planned = production_planner_service().get(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent)
    )
    event, post = planned.event, planned.post
    tz_name = view_zone(tenant_id, tz_override)
    local = event.scheduled_at.astimezone(ZoneInfo(tz_name))
    index, _ = _connection_index(tenant_id)
    platform, account = index.get(str(event.connection_id), ("", "Cuenta desconocida"))
    a_label, a_tone = approval_label(post.approval.value if post is not None else None)
    s_label, s_tone = status_label(event.status, overdue=planned.overdue_unapproved)
    return EventDetailVM(
        event_id=str(event.id),
        post_id=str(event.post_id),
        title=post.title if post is not None else "POST no disponible",
        caption_excerpt=post.caption_excerpt if post is not None else "",
        thumbnail_url=(post.thumbnail_url or "") if post is not None else "",
        category_label=category_label(post.category if post is not None else None),
        content_type_label=content_type_label(post.content_type if post is not None else None),
        approval_label=a_label,
        approval_tone=a_tone,
        status_label=s_label,
        status_tone=s_tone,
        when_label=f"{date_label(local.date())} · {time_label_12h(local)} ({tz_name})",
        platform=platform,
        account_label=account,
        revision=event.revision,
        can_modify=event.status == "scheduled",
        can_delete=event.status == "cancelled",
        detail_href=post.detail_href if post is not None else "",
        publish_note=(
            post.unpublishable_reason if post is not None and not post.is_publishable else ""
        ),
        local_date=local.date().isoformat(),
        local_time=local.strftime("%H:%M"),
        connection_id=str(event.connection_id),
        tags=[_tag_vm(t) for t in planned.tags],
        tag_ids=[str(t.id) for t in planned.tags],
    )
