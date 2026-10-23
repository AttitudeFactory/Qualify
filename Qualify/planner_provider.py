"""The seam between the Planificador screen and `qualify_api.planner` (QUA-108).

Same split as `publishing_provider.py`: plain synchronous functions over ids that the
state runs off the event loop (`asyncio.to_thread`). It reuses, unchanged:
- `connections_provider.connections_for` for the tenant's accounts;
- `creative_provider.default_brand_id` for the tenant's brand (1 tenant = 1 brand);
- `connections_provider.acting_user_id` for `created_by` (AuthState holds no user id).

It never publishes: the planner service it calls has no publish path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.creative.fsm import InvalidTransition as CreativeInvalidTransition
from qualify_api.planner.composition import production_planner_service, tenant_timezone
from qualify_api.planner.embedded import calendar_worker
from qualify_api.planner.gallery import gallery_state
from qualify_api.planner.heartbeat import production_heartbeat_store, worker_covers
from qualify_api.planner.post_reader import PostSummary, UnpublishableReason
from qualify_api.planner.publishable import (
    REASON_TEXT,
    SCHEDULABLE_PLATFORMS,
    destination_for_product_type,
)
from qualify_api.planner.repository import EventRecord
from qualify_api.planner.service import (
    DuplicateEvent,
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    IncompatibleConnection,
    InvalidSchedule,
    InvalidSeries,
    InvalidTag,
    OutputRequired,
    PlannedEvent,
    PlannerError,
    PostNotRejected,
    PostNotSchedulable,
    UnknownEvent,
    UnknownGoal,
    UnknownOutput,
    UnknownPost,
    UnknownTag,
    UnsupportedDestination,
    compose_instant,
    resolve_zone,
    week_start,
)

from .campaign_provider import CampaignOptionVM, brand_campaign_options
from .connections_provider import acting_user_id, connections_for
from .creative_provider import default_brand_id
from .planner_vm import (
    AUTO_PUBLISH_UNAVAILABLE,
    CALENDAR_DEFAULT_TZ,
    DESTINATION_LABELS,
    SERIES_MESSAGES,
    SERIES_UNKNOWN_MESSAGE,
    CardInput,
    CategoryOptionVM,
    ConnectionChoiceVM,
    DayColumnVM,
    EventDetailVM,
    HourRowVM,
    PostOptionVM,
    TagVM,
    auto_publish_state,
    build_output_chip,
    build_post_option,
    build_week,
    category_label,
    category_options,
    content_type_label,
    date_label,
    event_actions,
    event_readiness,
    goal_labels,
    is_pending,
    month_label,
    output_label,
    post_kind,
    status_label,
    time_label_12h,
    week_label,
)
from .r2_media import is_r2_key, issue_view_path

logger = logging.getLogger(__name__)

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
    now_hhmm: str = ""  # the current wall-clock time in the view zone ("HH:MM")
    tags: list[TagVM] = field(default_factory=list)
    # QUA-143: the brand's campaigns — the drawer's «Campaña» selector.
    campaigns: list[CampaignOptionVM] = field(default_factory=list)
    # One of planner_vm.AUTO_PUBLISH_* — worker running here + an active account (QUA-111).
    auto_publish: str = AUTO_PUBLISH_UNAVAILABLE


def planner_error_message(exc: Exception) -> str:
    """Operator-facing Spanish for every refusal — what happened and what to do."""
    if isinstance(exc, PostNotSchedulable) and exc.reason:
        # QUA-118 D1: the evaluator's exact reason, the same text the card shows.
        return f"Ese POST no se puede planificar: {exc.reason}"
    if isinstance(exc, InvalidSeries):
        return SERIES_MESSAGES.get(exc.code, SERIES_UNKNOWN_MESSAGE)
    if isinstance(exc, UnsupportedDestination):
        # QUA-118 v2: the selector's own sentence for why that destination is off.
        return exc.reason or "Instagram no publica este contenido en el destino elegido."
    messages: list[tuple[type[Exception], str]] = [
        (NoBrand, "Este negocio todavía no tiene una marca configurada."),
        (UnknownPost, "Ese POST ya no está disponible. Actualiza la página."),
        (
            PostNotSchedulable,
            "Ese POST no se puede planificar: no está aprobado o no está listo para publicar.",
        ),
        (
            InactiveConnection,
            "La cuenta elegida no está activa. Revísala en Tus redes o elige otra.",
        ),
        (InvalidSchedule, "La fecha y hora deben ser futuras y válidas en tu zona horaria."),
        (UnknownEvent, "Ese evento ya no existe. Actualiza la página."),
        (InvalidTag, "La etiqueta debe tener entre 1 y 40 caracteres."),
        (UnknownTag, "Esa etiqueta ya no existe. Actualiza la página."),
        (EventNotModifiable, "Ese evento ya no se puede modificar (no está programado)."),
        (
            PostNotRejected,
            "Ese POST ya no está rechazado (quizá se aprobó de nuevo): no se quitó nada.",
        ),
        (
            CreativeInvalidTransition,
            "Ese POST ya no está en revisión, así que no se puede rechazar. Actualiza la página.",
        ),
        (
            EventConflict,
            "Alguien más modificó este evento al mismo tiempo. Actualiza y vuelve a intentarlo.",
        ),
        (
            OutputRequired,
            "Este POST tiene varias salidas (Reel, feed, historia): elige cuál programar.",
        ),
        (UnknownOutput, "Ese POST no tiene esa salida. Actualiza la página."),
        (UnknownGoal, "Una de las metas elegidas no es válida. Actualiza la página."),
        (
            DuplicateEvent,
            "Esa publicación ya está programada en esa cuenta a esa misma hora.",
        ),
        (
            IncompatibleConnection,
            "Esa cuenta no admite publicaciones programadas desde Qualify. Elige otra.",
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
            compatible = connection.platform in SCHEDULABLE_PLATFORMS
            active.append(
                ConnectionChoiceVM(
                    id=connection.id,
                    label=label,
                    platform=connection.platform,
                    compatible=compatible,
                    note=""
                    if compatible
                    else REASON_TEXT[UnpublishableReason.CHANNEL_NOT_SUPPORTED],
                )
            )
    return index, active


def _thumbnail_url(tenant_id: UUID, url: str | None) -> str | None:
    """A POST's thumbnail as the page can load it: a generated piece lives in R2 only
    since 2026-10-06, so its key becomes a short-lived `/r2media/<token>` path; an
    `http(s)` URL or a local upload key is kept as it is. A token that cannot be minted
    costs only the thumbnail (the card shows its placeholder)."""
    if not url or not is_r2_key(url):
        return url
    try:
        return issue_view_path(tenant_id, url, "image") or None
    except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth failing the week
        logger.warning("planner thumbnail token not issued: %s", type(exc).__name__)
        return None


def _post_option(
    post: PostSummary,
    occupied: dict[str | None, EventRecord] | None = None,
    *,
    zone: ZoneInfo | None = None,
    connections: dict[str, tuple[str, str]] | None = None,
    thumbnails: dict[str, str | None] | None = None,
    video_url: str = "",
) -> PostOptionVM:
    """`occupied` is the POST's live event per output (`PlannerService.occupied_outputs`),
    so each chip can say when and where that output goes out. `video_url` is the
    short-lived path of an R2-only video, for the drawer's preview frame."""
    chips = []
    for output in post.outputs:
        event = (occupied or {}).get(output.port)
        when, account = "", ""
        if event is not None and zone is not None:
            local = event.scheduled_at.astimezone(zone)
            when = f"{_WEEKDAY_SHORT[local.weekday()]} {local.day} · {time_label_12h(local)}"
            account = (connections or {}).get(str(event.connection_id), ("", ""))[1]
        chips.append(
            build_output_chip(
                port=output.port,
                is_publishable=output.is_publishable,
                unpublishable_reason=output.unpublishable_reason,
                event_status=event.status if event is not None else None,
                when_label=when,
                account_label=account,
                media_types=output.media_types,
                image_size=output.image_size,
                preferred_destination=destination_for_product_type(output.media_product_type),
            )
        )
    return build_post_option(
        post_id=str(post.post_id),
        title=post.title,
        caption_excerpt=post.caption_excerpt,
        thumbnail_url=(thumbnails or {}).get(str(post.post_id), post.thumbnail_url),
        category=post.category,
        approval=post.approval.value,
        detail_href=post.detail_href,
        is_publishable=post.is_publishable,
        unpublishable_reason=post.unpublishable_reason,
        outputs=chips,
        video_url=video_url,
        gallery_state=gallery_state(post).value,
        times_published=post.times_published,
        has_live_event=post.has_live_event,
        media_types=post.media_types,
        image_size=post.image_size,
        preferred_destination=destination_for_product_type(post.media_product_type),
        lifecycle_status=post.lifecycle_status,
        **_campaign_fields(post),
        campaign_id=str(post.campaign.id) if post.campaign is not None else "",
        event_count=post.event_count,
        retention_state=post.retention_state,
        purge_days_left=post.purge_days_left,
    )


def event_destination(event: EventRecord, post: PostSummary | None) -> str:
    """Where the event goes out: its own (0041), or — for an event the backfill could not
    derive — what its POST publishes as, the rule the executor falls back to."""
    if event.destination:
        return event.destination
    if post is None:
        return ""
    if event.output_port:
        output = next((o for o in post.outputs if o.port == event.output_port), None)
        return destination_for_product_type(output.media_product_type if output else None) or ""
    return destination_for_product_type(post.media_product_type) or ""


@dataclass(frozen=True)
class GalleryData:
    posts: list[PostOptionVM] = field(default_factory=list)
    categories: list[CategoryOptionVM] = field(default_factory=list)


def load_gallery(tenant_id: UUID) -> GalleryData:
    """Every POST of the brand as a card (QUA-118 gallery), with the same view-model and
    the same per-output chips as the «Sin programar» panel. Blocking (DB) — run off
    the event loop."""
    brand_id = _require_brand(tenant_id)
    tz_name = view_zone(tenant_id, "")
    zone = ZoneInfo(tz_name)
    index, _active = _connection_index(tenant_id)
    service = production_planner_service()
    posts = service.list_posts(tenant_id=tenant_id, brand_id=brand_id)
    occupied = service.occupied_outputs(tenant_id=tenant_id, brand_id=brand_id)
    videos = {
        str(p.post_id): url
        for p in posts
        if p.video_object_key and (url := _video_url(tenant_id, p.video_object_key))
    }
    options = [
        _post_option(
            p,
            occupied.get(p.post_id),
            zone=zone,
            connections=index,
            thumbnails={str(p.post_id): _thumbnail_url(tenant_id, p.thumbnail_url)},
            video_url=videos.get(str(p.post_id), ""),
        )
        for p in posts
    ]
    return GalleryData(posts=options, categories=category_options(options))


_WEEKDAY_SHORT = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _tag_vm(tag) -> TagVM:
    return TagVM(id=str(tag.id), name=tag.name, color=tag.color)


def view_zone(tenant_id: UUID, tz_override: str) -> str:
    """The zone the calendar shows and plans in: the operator's pick for this session if
    valid, else `CALENDAR_DEFAULT_TZ` — not the tenant's zone. Never written back to the
    tenant."""
    if tz_override:
        try:
            resolve_zone(tz_override)
            return tz_override
        except InvalidSchedule:
            pass
    return CALENDAR_DEFAULT_TZ


def _campaign_fields(post: PostSummary | None) -> dict[str, str]:
    """QUA-143: the POST's campaign as the view-models carry it — every event of the POST
    reads it here, from the POST; nothing about it lives on the event."""
    campaign = post.campaign if post is not None else None
    if campaign is None:
        return {}
    return {"campaign_name": campaign.name, "campaign_color": campaign.color}


def _card_input(
    planned: PlannedEvent,
    video_urls: dict[str, str] | None = None,
    thumbnails: dict[str, str | None] | None = None,
) -> CardInput:
    event, post = planned.event, planned.post
    return CardInput(
        event_id=str(event.id),
        post_id=str(event.post_id),
        scheduled_at=event.scheduled_at,
        status=event.status,
        overdue=planned.overdue_unapproved,
        expired=planned.expired,
        connection_id=str(event.connection_id),
        post_title=post.title if post is not None else None,
        caption_excerpt=post.caption_excerpt if post is not None else "",
        thumbnail_url=(
            (thumbnails or {}).get(str(post.post_id), post.thumbnail_url)
            if post is not None
            else None
        ),
        category=post.category if post is not None else None,
        content_type=post.content_type if post is not None else None,
        approval=post.approval.value if post is not None else None,
        detail_href=post.detail_href if post is not None else "",
        tags=tuple(_tag_vm(t) for t in planned.tags),
        is_publishable=post.is_publishable if post is not None else False,
        unpublishable_reason=post.unpublishable_reason if post is not None else "",
        video_url=(video_urls or {}).get(str(event.post_id), ""),
        output_port=event.output_port,
        destination=event_destination(event, post),
        times_published=post.times_published if post is not None else None,
        **_campaign_fields(post),
    )


def _week_video_urls(tenant_id: UUID, planned: list[PlannedEvent]) -> dict[str, str]:
    """One short-lived URL per POST with an R2-only video (not one per event): the cards
    show its first frame, fetched with HTTP Range (`r2_media`), never the whole reel."""
    keys = {
        str(p.post.post_id): p.post.video_object_key
        for p in planned
        if p.post is not None and p.post.video_object_key
    }
    return {post_id: url for post_id, key in keys.items() if (url := _video_url(tenant_id, key))}


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
    now_local = datetime.now(UTC).astimezone(zone)
    today = now_local.date()
    monday = week_start(date.fromisoformat(monday_iso) if monday_iso else today)

    index, active = _connection_index(tenant_id)
    connection_id = (
        UUID(connection_filter)
        if connection_filter and connection_filter != ALL_CONNECTIONS
        else None
    )
    service = production_planner_service()
    planned = [
        p
        for p in service.list_week(
            tenant_id=tenant_id,
            brand_id=brand_id,
            monday=monday,
            tz_name=tz_name,
            connection_id=connection_id,
            tag_ids=frozenset(UUID(t) for t in tag_filter if _is_uuid(t)),
        )
        # QUA-118 A1: a cancelled event is none of the five visible states. The cancel
        # flow removes the row (`cancel_event`); a row cancelled by another path (the
        # repository, a test) stays invisible all the same.
        if p.event.status != "cancelled"
    ]
    schedulable = service.list_schedulable(tenant_id=tenant_id, brand_id=brand_id)
    unscheduled = service.list_unscheduled(tenant_id=tenant_id, brand_id=brand_id)
    occupied = service.occupied_outputs(tenant_id=tenant_id, brand_id=brand_id)
    video_urls = _week_video_urls(tenant_id, planned)
    # one viewable thumbnail per POST on the page (R2 keys → `/r2media`, § 2026-10-06)
    posts = {
        str(p.post_id): p
        for p in (
            *(item.post for item in planned if item.post is not None),
            *schedulable,
            *unscheduled,
        )
    }
    thumbnails = {pid: _thumbnail_url(tenant_id, p.thumbnail_url) for pid, p in posts.items()}
    # The drawer previews the chosen POST: one short-lived URL per schedulable R2 video.
    option_videos = {
        str(p.post_id): url
        for p in schedulable
        if p.video_object_key and (url := _video_url(tenant_id, p.video_object_key))
    }
    grid = build_week(
        monday=monday,
        today=today,
        zone=zone,
        items=[_card_input(p, video_urls, thumbnails) for p in planned],
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
        # The panel's cards show the same first frame the gallery and the drawer do.
        unscheduled=[
            _post_option(
                p,
                occupied.get(p.post_id),
                zone=zone,
                connections=index,
                thumbnails=thumbnails,
                video_url=option_videos.get(str(p.post_id), ""),
            )
            for p in unscheduled
        ],
        schedulable=[
            _post_option(
                p,
                occupied.get(p.post_id),
                zone=zone,
                connections=index,
                thumbnails=thumbnails,
                video_url=option_videos.get(str(p.post_id), ""),
            )
            for p in schedulable
        ],
        connections=active,
        total_events=len(planned),
        tenant_tz=tenant_tz,
        now_hhmm=now_local.strftime("%H:%M"),
        tags=[_tag_vm(t) for t in service.list_tags(tenant_id=tenant_id)],
        campaigns=brand_campaign_options(tenant_id, brand_id),
        auto_publish=auto_publish_state(
            worker_covers_tenant=calendar_worker().status().covers(tenant_id)
            or worker_covers(production_heartbeat_store(), tenant_id),
            has_active_connection=bool(active),
        ),
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


def _parse_day_time(day: str, at: str) -> tuple[date, time]:
    try:
        return date.fromisoformat(day), time.fromisoformat(at)
    except ValueError as exc:
        raise InvalidSchedule(f"bad date/time {day!r} {at!r}") from exc


def schedule_post(
    tenant_id: UUID,
    post_id: str,
    day: str,
    at: str,
    connection_id: str,
    tz_override: str = "",
    tag_ids: tuple[str, ...] = (),
    output_port: str = "",
    connection_ids: tuple[str, ...] = (),
    repeat_until: str = "",
    repeat_count: int = 0,
    destination: str = "",
    repeat_weekdays: tuple[int, ...] = (),
    goals: tuple[str, ...] = (),
) -> int:
    """Plan one POST (or one template output of it, `output_port` — MP-11) on one or
    more accounts, once or weekly. Returns how many events were created.

    - `connection_ids` (QUA-118 AC 5) are the accounts; when empty, `connection_id` alone.
    - `repeat_until` (ISO date) OR `repeat_count` (> 0) make it a weekly series (QUA-118
      A2/A4): the same weekday and time, at most `SERIES_CAP` occurrences, one
      `calendar_event` per occurrence and account, created all-or-nothing.
    - `tag_ids` are attached to every event created.
    """
    brand_id = _require_brand(tenant_id)
    tz_name = view_zone(tenant_id, tz_override)
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoBrand(str(tenant_id))
    service = production_planner_service()
    accounts = [_uuid(c, InactiveConnection) for c in (connection_ids or (connection_id,)) if c]
    common = {
        "tenant_id": tenant_id,
        "brand_id": brand_id,
        "post_id": _uuid(post_id, UnknownPost),
        "connection_ids": accounts,
        "scheduled_tz": tz_name,
        "user_id": user_id,
        "output_port": output_port or None,
        # QUA-118 v2: where the events go out; "" → what the POST publishes as today.
        "destination": destination or None,
        # QUA-118 v2 (0042): the plan's goals, kept on every event for later analysis.
        "goals": list(goals),
    }
    if repeat_weekdays and repeat_count:
        # QUA-118 v2: several weekdays, `repeat_count` weeks each, at the same time.
        start, at_time = _parse_day_time(day, at)
        events = service.schedule_weekly(
            start=start,
            weekdays=list(repeat_weekdays),
            weeks=repeat_count,
            at=at_time,
            **common,  # type: ignore[arg-type]
        )
    elif repeat_until or repeat_count:
        first_day, at_time = _parse_day_time(day, at)
        until = _parse_day_time(repeat_until, "00:00")[0] if repeat_until else None
        events = service.schedule_series(
            first_day=first_day,
            at=at_time,
            until=until,
            count=repeat_count or None,
            **common,  # type: ignore[arg-type]
        )
    else:
        events = service.schedule_many(
            scheduled_at=_parse_instant(day, at, tz_name),
            **common,  # type: ignore[arg-type]
        )
    if tag_ids:
        tags = [_uuid(t, UnknownTag) for t in tag_ids]
        for event in events:
            service.set_event_tags(tenant_id=tenant_id, event_id=event.id, tag_ids=tags)
    return len(events)


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


def set_event_goals(tenant_id: UUID, event_id: str, goals: tuple[str, ...]) -> None:
    """QUA-118 v2: the goals of one planned publication, edited from its panel."""
    production_planner_service().set_event_goals(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent), goals=list(goals)
    )


def reject_post(tenant_id: UUID, event_id: str) -> None:
    """Reject the event's POST from the Planificador — the creative FSM's `reject` edge
    (legal only for a POST in review; anything else raises `InvalidTransition`). The event
    stays scheduled and the worker will not publish it (the POST is not approved)."""
    from .creative_provider import reject_draft  # noqa: PLC0415 — avoids an import cycle

    planned = production_planner_service().get(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent)
    )
    user_id = acting_user_id(tenant_id)
    if user_id is None:
        raise NoBrand(str(tenant_id))
    reject_draft(
        tenant_id,
        planned.event.post_id,
        user_id,
        reason="Rechazado desde Tu semana",
        regenerate=False,
    )


def remove_rejected_post(tenant_id: UUID, event_id: str) -> int:
    """ "Quitar del calendario" for a rejected POST (`PlannerService.remove_rejected_post`)."""
    return production_planner_service().remove_rejected_post(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent)
    )


def delete_event(tenant_id: UUID, event_id: str) -> None:
    production_planner_service().delete(tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent))


def cancel_event(tenant_id: UUID, event_id: str) -> None:
    """«Cancelar publicación»: the event leaves the calendar (QUA-118 A1 — `cancelled` is
    not a visible state), through the FSM, never by a bare delete."""
    production_planner_service().cancel_and_delete(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent)
    )


def _video_url(tenant_id: UUID, key: str | None) -> str:
    """The dialog's video preview: a short-lived `/r2media/<token>` for the tenant's own
    R2 video (`r2_media.issue_view_path` re-checks the prefix). A token that cannot be
    minted only costs the preview, never the dialog."""
    if not key:
        return ""
    try:
        return issue_view_path(tenant_id, key, "video")
    except Exception as exc:  # noqa: BLE001 — a preview is not worth failing the dialog
        logger.warning("planner video token not issued: %s", type(exc).__name__)
        return ""


def event_detail(tenant_id: UUID, event_id: str, tz_override: str = "") -> EventDetailVM:
    planned = production_planner_service().get(
        tenant_id=tenant_id, event_id=_uuid(event_id, UnknownEvent)
    )
    event, post = planned.event, planned.post
    tz_name = view_zone(tenant_id, tz_override)
    local = event.scheduled_at.astimezone(ZoneInfo(tz_name))
    index, _ = _connection_index(tenant_id)
    platform, account = index.get(str(event.connection_id), ("", "Cuenta desconocida"))
    # Same function the calendar card uses (`planner_vm.event_readiness`), over the same
    # `PostSummary` verdict — card and dialog cannot disagree.
    ready = event_readiness(
        status=event.status,
        approval=post.approval.value if post is not None else None,
        is_publishable=post.is_publishable if post is not None else False,
        reason=post.unpublishable_reason if post is not None else "",
    )
    s_label, s_tone = status_label(
        event.status,
        pending=is_pending(event.status, post.approval.value if post is not None else None),
        expired=planned.expired,
    )
    actions = event_actions(
        status=event.status,
        approval=post.approval.value if post is not None else None,
        lifecycle=post.lifecycle_status if post is not None else None,
    )
    return EventDetailVM(
        event_id=str(event.id),
        post_id=str(event.post_id),
        title=post.title if post is not None else "POST no disponible",
        caption_excerpt=post.caption_excerpt if post is not None else "",
        thumbnail_url=(
            (_thumbnail_url(tenant_id, post.thumbnail_url) or "") if post is not None else ""
        ),
        category_label=category_label(post.category if post is not None else None),
        content_type_label=content_type_label(post.content_type if post is not None else None),
        approval_label=ready.label,
        approval_tone=ready.tone,
        status_label=s_label,
        status_tone=s_tone,
        when_label=f"{date_label(local.date())} · {time_label_12h(local)} ({tz_name})",
        platform=platform,
        account_label=account,
        revision=event.revision,
        can_modify=actions.can_modify,
        can_reject_post=actions.can_reject_post,
        can_remove_rejected=actions.can_remove_rejected,
        detail_href=post.detail_href if post is not None else "",
        publish_note=ready.note,
        expired=planned.expired,
        video_url=_video_url(tenant_id, post.video_object_key if post is not None else None),
        local_date=local.date().isoformat(),
        local_time=local.strftime("%H:%M"),
        connection_id=str(event.connection_id),
        tags=[_tag_vm(t) for t in planned.tags],
        tag_ids=[str(t.id) for t in planned.tags],
        output_port=event.output_port or "",
        output_label=output_label(event.output_port),
        destination=(dest := event_destination(event, post)),
        destination_label=DESTINATION_LABELS.get(dest, ""),
        goals=goal_labels(event.goals),
        goal_keys=list(event.goals),
        **_detail_kind(post, event.output_port),
        **_campaign_fields(post),
    )


def _detail_kind(post: PostSummary | None, output_port: str | None) -> dict[str, str]:
    """What the event's content IS (Imagen / Video / Carrusel) for the panel's chip."""
    if post is None:
        return {}
    types = post.media_types
    if output_port:
        output = next((o for o in post.outputs if o.port == output_port), None)
        types = output.media_types if output is not None else ()
    key, label, _icon = post_kind(types, category=post.category or "")
    return {"kind": key, "kind_label": label}
