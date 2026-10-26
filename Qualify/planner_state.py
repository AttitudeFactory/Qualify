"""State for `/planner` — the Planificador (QUA-108).

Reads the active tenant from `AuthState.session_tenant_id` and runs every blocking call
(`planner_provider`) off the event loop with `asyncio.to_thread`, inside
`background=True` handlers — the same shape as `publishing_state.load_active_connections`.

The page never publishes. "Asignar", "Reprogramar" and "Cancelar" only change planning
state; execution is QUA-111's.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import reflex as rx
from qualify_api.creative.fsm import InvalidTransition as CreativeInvalidTransition
from qualify_api.planner.service import PlannerError

from .auth_state import AuthState
from .campaign_provider import (
    COLOR_LABELS,
    CampaignOptionVM,
    apply_post_choice,
    suggested_color,
)
from .campaign_provider import (
    error_message as campaign_error_message,
)
from .creative_provider import acting_user_id
from .pending_state import PendingState
from .planner_provider import (
    ALL_CONNECTIONS,
    NoPassingVariant,
    PriceBlocked,
    approve_error_message,
    approve_post,
    cancel_event,
    create_tag,
    delete_tag,
    event_detail,
    load_week,
    planner_error_message,
    reject_post,
    remove_rejected_post,
    reschedule_event,
    schedule_post,
    set_event_goals,
    set_event_tags,
)
from .planner_vm import (
    APPROVED_CHECK_TOAST,
    ASSIGN_STEPS,
    AUTO_PUBLISH_UNAVAILABLE,
    CALENDAR_DEFAULT_TZ,
    CAMPAIGN_NEW,
    KIND_ICONS,
    OPENING_HOUR,
    PLAN_GOAL_KEYS,
    PLAN_GOALS,
    REVIEW_EDIT_NOTE,
    STEP_LAST,
    STEP_POST,
    STEP_WHEN,
    SUBMIT_ASSIGN,
    SUBMIT_RESCHEDULE,
    TAG_SUGGESTIONS,
    URL_VIEW,
    URL_WEEK,
    VIEW_CALENDAR,
    VIEW_LIST,
    ConnectionChoiceVM,
    DayColumnVM,
    EventDetailVM,
    HourRowVM,
    PlanItem,
    PlanRowVM,
    PostOptionVM,
    TagSuggestionVM,
    TagVM,
    TzOptionVM,
    approved_toast,
    assign_steps_done,
    build_plan_row,
    campaign_value,
    join_es,
    now_slot,
    parse_view_param,
    parse_week_param,
    scheduled_message,
    split_time,
    timezone_options,
    tz_option,
    waiting_copy,
    week_href,
    week_return_query,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudo cargar Tu semana. Inténtalo de nuevo."
_FORM_INCOMPLETE = "Elige al menos una publicación y completa su fecha, hora y cuenta."
_POST_REQUIRED = "Elige al menos una publicación lista para salir."

MODE_ASSIGN = "assign"
UNSCHEDULED_OPEN = "open"
UNSCHEDULED_CLOSED = "closed"
# How often an open Planificador re-reads its week, so a publication the worker (which
# ticks every 60 s) settled shows on its own.
REFRESH_SECONDS = 30
SCROLL_ID = "q-planner-scroll"

# Opens the calendar at the start of the working day instead of midnight. Runs in the
# browser after the week renders; harmless when the list view is showing (no element).
_SCROLL_TO_OPENING_HOUR = (
    "setTimeout(() => {"
    f"const box = document.getElementById('{SCROLL_ID}');"
    f"const row = document.getElementById('q-hour-{OPENING_HOUR}');"
    "if (box && row) { box.scrollTop += row.getBoundingClientRect().top"
    " - box.getBoundingClientRect().top - 44; }"
    "}, 60)"
)
MODE_RESCHEDULE = "reschedule"
# m-24842985: `/planner?post=<id>&cuando=ahora` opens the drawer on «Ahora».
URL_WHEN = "cuando"
URL_WHEN_NOW = "ahora"

# The event panel's inline confirmations (no dialog on top of the panel).
CONFIRM_CANCEL = "cancel"
CONFIRM_REMOVE = "remove"


MINUTE_STEPS: tuple[str, ...] = tuple(f"{m:02d}" for m in range(0, 60, 5))


def to_24h(hour12: int, meridiem: str) -> int:
    """(12, "am") → 0, (12, "pm") → 12, (3, "pm") → 15."""
    return (hour12 % 12) + (12 if meridiem == "pm" else 0)


_TZ_RESULTS_LIMIT = 60


@lru_cache(maxsize=2)
def _timezones_for(day_iso: str) -> tuple[TzOptionVM, ...]:
    """All zones with that day's offsets, computed once per day (offsets move with DST)."""
    return tuple(timezone_options(datetime.fromisoformat(day_iso + "T12:00:00+00:00")))


def search_timezones(query: str, day_iso: str) -> list[TzOptionVM]:
    """The picker's filter (pure, tested directly): every word of the query must appear
    in the city, the IANA name or the GMT label. Capped so the list stays light."""
    words = query.lower().split()
    options = _timezones_for(day_iso)
    hits = [o for o in options if all(w in o.search for w in words)] if words else options
    return list(hits[:_TZ_RESULTS_LIMIT])


def shift_week(monday_iso: str, weeks: int) -> str:
    """The Monday `weeks` weeks away from `monday_iso` (pure — tested directly)."""
    return (date.fromisoformat(monday_iso) + timedelta(weeks=weeks)).isoformat()


def _weeks(text: str) -> int:
    try:
        return max(int(text.strip() or "0"), 0)
    except ValueError:
        return 0


def _starting_destination(post: PostOptionVM, output_port: str) -> str:
    """Where a piece starts: its output's default for a package, else the POST's."""
    if output_port:
        chip = next((c for c in post.outputs if c.port == output_port), None)
        return chip.default_destination if chip is not None else ""
    return post.default_destination


def rows_for_submit(rows: list[PlanRowVM], tz_name: str, now: datetime) -> list[PlanRowVM]:
    """The plan as «Programar» sends it, in the order it goes out. m-24842985: a piece on
    «Ahora» gets its instant only here, from `now` — the tap — as the next minutes in
    `tz_name` (`now_slot`), so the calendar worker takes it on its next pass and never
    earlier than the owner's tap."""
    day, at = now_slot(tz_name, now)
    return sorted(
        (replace(r, date=day, time=at) if r.now else r for r in rows),
        key=lambda r: (r.date, r.time),
    )


async def schedule_plan_rows(
    tenant_id,
    rows: list[PlanRowVM],
    *,
    mode: str,
    event_id: str,
    view_tz: str,
    goals: tuple[str, ...],
    schedule=None,
    reschedule=None,
    apply_campaign=None,
    resolve_user=None,
) -> tuple[int, list[str], str]:
    """«Confirmar»'s work, piece by piece, off the state (so it is testable without a live
    Reflex context): (publications created, POSTs planned, the failure message or "").

    Each piece is planned on its own (atomic within the piece: its accounts and its
    series, QUA-118 A4); the first refusal stops the loop. QUA-143 AC 21: a piece's
    campaign choice is applied to its POST ONLY AFTER that piece's publications were
    created — a refused schedule breaks out first, so the POST keeps its campaign and no
    campaign typed for it is created. The dependencies default to the real providers.
    """
    schedule = schedule or schedule_post
    reschedule = reschedule or reschedule_event
    apply_campaign = apply_campaign or apply_post_choice
    resolve_user = resolve_user or acting_user_id
    created, planned, failure = 0, [], ""
    user_id = None  # who creates a campaign typed in the drawer (resolved once, lazily)
    for row in rows:
        accounts = tuple(c.id for c in row.accounts)
        try:
            if mode == MODE_RESCHEDULE:
                await asyncio.to_thread(
                    reschedule,
                    tenant_id,
                    event_id,
                    row.date,
                    row.time,
                    accounts[0],
                    view_tz,
                    tuple(row.tag_ids),
                )
                created += 1
            else:
                created += await asyncio.to_thread(
                    schedule,
                    tenant_id,
                    row.post_id,
                    row.date,
                    row.time,
                    accounts[0],
                    view_tz,
                    tuple(row.tag_ids),
                    row.output_port,
                    accounts,
                    "",
                    # A weekly series: its weeks and weekdays (`weekly_days_on`).
                    _weeks(row.repeat_count) if row.series.enabled else 0,
                    row.destination,
                    tuple(row.repeat_days) if row.series.enabled else (),
                    goals,
                )
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner %s failed: %s", mode, type(exc).__name__)
            failure = f"«{row.title}»: {planner_error_message(exc)}"
            break
        planned.append(row.post_id)
        if mode != MODE_RESCHEDULE and row.campaign_changed:
            try:
                if user_id is None:
                    user_id = await asyncio.to_thread(resolve_user, tenant_id)
                await asyncio.to_thread(
                    lambda r=row, u=user_id: apply_campaign(
                        tenant_id,
                        UUID(r.post_id),
                        r.campaign_value,
                        new_name=r.new_campaign_name,
                        new_color=r.new_campaign_color,
                        user_id=u,
                    )
                )
            except Exception as exc:
                logger.error("planner campaign apply failed: %s", type(exc).__name__)
                failure = (
                    f"«{row.title}»: quedó programado, pero no se pudo guardar su campaña. "
                    f"{campaign_error_message(exc)}"
                )
                break
    return created, planned, failure


class PlannerState(rx.State):
    # -- week -----------------------------------------------------------------
    loading: bool = True
    load_error: str = ""
    monday_iso: str = ""
    today_iso: str = ""
    week_label: str = ""
    month_label: str = ""
    tz_name: str = ""
    days: list[DayColumnVM] = []
    rows: list[HourRowVM] = []
    total_events: int = 0
    unscheduled: list[PostOptionVM] = []
    schedulable: list[PostOptionVM] = []
    connections: list[ConnectionChoiceVM] = []
    connection_filter: str = ALL_CONNECTIONS
    # Per-session view preferences (not tenant data; reset on logout like the rest).
    view_mode: str = VIEW_CALENDAR
    # The «Por programar» panel: "" = automatic (m-24842982: open on a wide screen when
    # something is waiting, closed on a phone, where the empty week carries the button),
    # or the owner's own choice, UNSCHEDULED_OPEN / UNSCHEDULED_CLOSED, for every width.
    unscheduled_pref: str = ""
    # The zone the calendar shows and plans in. "" = CALENDAR_DEFAULT_TZ; a pick here
    # is a per-session view choice and is never written back to the tenant.
    view_tz: str = ""
    tenant_tz: str = ""
    now_hhmm: str = ""  # the view zone's wall-clock time when the week was loaded
    auto_publish: str = AUTO_PUBLISH_UNAVAILABLE
    tz_query: str = ""
    # Planning tags (0025): the tenant's labels and the calendar's tag filter.
    tags: list[TagVM] = []
    # QUA-143: the brand's campaigns — the drawer's «Campaña» selector.
    campaigns: list[CampaignOptionVM] = []
    tag_filter: list[str] = []
    tag_query: str = ""
    # m-24842987: «Filtros» (account, tags, zone) in a side panel, off the week's bar.
    filters_open: bool = False

    # -- assign / reschedule drawer ---------------------------------------------
    form_open: bool = False
    form_mode: str = MODE_ASSIGN
    form_event_id: str = ""
    form_tag_query: str = ""
    form_error: str = ""
    saving: bool = False
    # QUA-118 v2: the drawer plans several POSTs at once. `plan_items` is the plan, in
    # the order the POSTs were picked; each piece carries its own date, time, accounts
    # (AC 5: one event per account), tags, output (MP-11) and weekly repetition (A2).
    # A new piece starts on `form_default_date` / `form_default_time` (the clicked cell,
    # or today's next hour). `form_step` is the current step and `form_reached` the
    # furthest one visited. `form_goals` are the plan's goals (`PLAN_GOALS` keys).
    plan_items: list[PlanItem] = []
    form_default_date: str = ""
    form_default_time: str = "09:00"
    form_kind_filter: str = "all"
    form_goals: list[str] = []
    form_step: int = 0
    form_reached: int = 0
    # m-24842985: the pieces whose «Más opciones» is open (POST ids). A piece whose
    # missing data sits there opens it ONCE on its own (`PlanRowVM.needs_more` turning
    # true, `_sync_more_open`); after that the owner opens and closes it.
    more_open: list[str] = []
    # The pieces whose `needs_more` was true at the last sync (to open only on the change).
    more_auto: list[str] = []
    # QUA-118 drag & drop: the POST being dragged from «Sin programar» (the browser
    # drags, this only remembers what), and the `?post=` already turned into an open
    # drawer so a reload or a week change does not reopen it.
    drag_post_id: str = ""
    _url_post_opened: str = ""

    # -- the event panel --------------------------------------------------------
    detail_open: bool = False
    detail_loading: bool = False
    detail: EventDetailVM = EventDetailVM()
    detail_error: str = ""
    detail_confirm: str = ""  # CONFIRM_CANCEL / CONFIRM_REMOVE while the panel asks
    # m-24842984: «Aprobar» / «No la quiero» in flight — both buttons wait (no double tap).
    review_busy: bool = False
    # m-24842984: «Aprobar» refused for the text itself — kept on the panel with a link.
    review_error: str = ""
    # -- delete a tag (confirmed inline, in the filter's own row) ------------------
    delete_tag_id: str = ""
    delete_tag_name: str = ""

    # -- computed -------------------------------------------------------------

    @rx.var
    def is_current_week(self) -> bool:
        return self._week_contains_today()

    def _week_contains_today(self) -> bool:
        if not self.monday_iso or not self.today_iso:
            return False
        monday = date.fromisoformat(self.monday_iso)
        return monday <= date.fromisoformat(self.today_iso) < monday + timedelta(days=7)

    @rx.var
    def is_list_view(self) -> bool:
        return self.view_mode == VIEW_LIST

    @rx.var
    def week_return_query(self) -> str:
        """m-24842987: appended to every ficha opened from here, so the ficha's
        «‹ Tu semana» comes back to this week, in this view."""
        return week_return_query(self.monday_iso, self.view_mode)

    @rx.var
    def filters_active_count(self) -> int:
        """How many of «Filtros» hide publications: account and tags. The zone hides
        nothing, so it is not counted (it is said under the week's dates instead)."""
        return int(self.connection_filter != ALL_CONNECTIONS) + int(bool(self.tag_filter))

    @rx.var
    def unscheduled_count(self) -> int:
        return len(self.unscheduled)

    # -- «Por programar» (m-24842982) -------------------------------------------

    @rx.var
    def waiting_count(self) -> int:
        """Approved publications with no date yet that the drawer can plan."""
        return sum(1 for post in self.unscheduled if post.schedulable)

    @rx.var
    def has_waiting(self) -> bool:
        return self.waiting_count > 0

    @rx.var
    def waiting_body(self) -> str:
        return waiting_copy(self.waiting_count).body

    @rx.var
    def waiting_action(self) -> str:
        return waiting_copy(self.waiting_count).action

    @rx.var
    def unscheduled_auto(self) -> bool:
        return self.unscheduled_pref == ""

    @rx.var
    def unscheduled_open_wide(self) -> bool:
        """Is the panel open on a wide screen (≥ 64em, beside the week)?"""
        if self.unscheduled_pref == "":
            return self.waiting_count > 0
        return self.unscheduled_pref == UNSCHEDULED_OPEN

    @rx.var
    def unscheduled_open_narrow(self) -> bool:
        """Is the panel open below 64em? Never on its own: the week says it."""
        return self.unscheduled_pref == UNSCHEDULED_OPEN

    # -- timezone picker ------------------------------------------------------

    @rx.var
    def tz_city_label(self) -> str:
        return tz_option(self.tz_name, datetime.now(UTC)).city if self.tz_name else ""

    @rx.var
    def form_tz_city(self) -> str:
        """m-24842985: the city of the zone «Programar» plans in (`view_tz or tz_name`,
        the same one `rows_for_submit` uses) — said on «Confirmar» instead of the zone's
        technical name."""
        zone = self.view_tz or self.tz_name
        return tz_option(zone, datetime.now(UTC)).city if zone else ""

    @rx.var
    def tz_results(self) -> list[TzOptionVM]:
        return search_timezones(self.tz_query, datetime.now(UTC).date().isoformat())

    @rx.var
    def tz_suggestions(self) -> list[TzOptionVM]:
        """The calendar's default zone plus the business's own zone, if it differs."""
        names = dict.fromkeys(z for z in (CALENDAR_DEFAULT_TZ, self.tenant_tz) if z)
        return [tz_option(name, datetime.now(UTC)) for name in names]

    # -- tags -----------------------------------------------------------------

    @rx.var
    def tag_results(self) -> list[TagVM]:
        words = self.tag_query.lower().split()
        return [t for t in self.tags if all(w in t.name.lower() for w in words)]

    @rx.var
    def tag_suggestions(self) -> list[TagSuggestionVM]:
        """Recommended tags the tenant does not have yet."""
        existing = {t.name.lower() for t in self.tags}
        return [t for t in TAG_SUGGESTIONS if t.name.lower() not in existing]

    @rx.var
    def detail_available_tags(self) -> list[TagVM]:
        """Tags the open event does not carry yet — the detail's "+ Etiqueta" menu."""
        own = set(self.detail.tag_ids)
        return [t for t in self.tags if t.id not in own]

    @rx.var
    def tag_filter_count(self) -> int:
        return len(self.tag_filter)

    @rx.var
    def can_create_tag(self) -> bool:
        return self._creatable(self.tag_query)

    @rx.var
    def form_can_create_tag(self) -> bool:
        return self._creatable(self.form_tag_query)

    def _creatable(self, query: str) -> bool:
        name = " ".join(query.split())
        return 0 < len(name) <= 40 and all(t.name.lower() != name.lower() for t in self.tags)

    @rx.var
    def has_connections(self) -> bool:
        return len(self.connections) > 0

    @rx.var
    def form_title(self) -> str:
        return (
            "Reprogramar publicación" if self.form_mode == MODE_RESCHEDULE else "Nueva publicación"
        )

    # -- the plan: several POSTs, each with its own date, time, accounts and tags ----

    @rx.var
    def form_is_reschedule(self) -> bool:
        return self.form_mode == MODE_RESCHEDULE

    def _post_for(self, post_id: str) -> PostOptionVM | None:
        """The POST behind a piece of the plan. A reschedule's POST may no longer be in
        the schedulable list (it is already planned), so it is read from the event."""
        if self.form_mode == MODE_RESCHEDULE and post_id == self.detail.post_id:
            return PostOptionVM(
                post_id=self.detail.post_id,
                title=self.detail.title,
                caption_excerpt=self.detail.caption_excerpt,
                thumbnail_url=self.detail.thumbnail_url,
                category_label=self.detail.category_label,
                approval_label=self.detail.approval_label,
                approval_tone=self.detail.approval_tone,
                detail_href=self.detail.detail_href,
                readiness_note=self.detail.publish_note,
                schedulable=True,
                video_url=self.detail.video_url,
                kind=self.detail.kind,
                kind_label=self.detail.kind_label,
            )
        for post in self.schedulable:
            if post.post_id == post_id:
                return post
        return None

    @rx.var
    def form_selected_ids(self) -> list[str]:
        return [item.post_id for item in self.plan_items]

    @rx.var
    def form_count(self) -> int:
        return len(self.plan_items)

    @rx.var
    def form_tiles(self) -> list[PostOptionVM]:
        """The «Contenido» grid: ready POSTs first (they are the ones to pick), then the
        rest, dashed and not selectable — filtered by format."""
        wanted = self.form_kind_filter
        posts = [p for p in self.schedulable if wanted in ("", "all") or p.kind == wanted]
        return sorted(posts, key=lambda p: not p.schedulable)

    @rx.var
    def form_kind_counts(self) -> dict[str, int]:
        counts = {key: 0 for key in KIND_ICONS}
        counts["all"] = len(self.schedulable)
        for post in self.schedulable:
            counts[post.kind] = counts.get(post.kind, 0) + 1
        return counts

    @rx.var
    def form_ready_count(self) -> int:
        return sum(1 for p in self.schedulable if p.schedulable)

    @rx.var
    def plan_rows(self) -> list[PlanRowVM]:
        reschedule = self.form_mode == MODE_RESCHEDULE
        return [
            build_plan_row(
                item,
                post=self._post_for(item.post_id),
                connections=self.connections,
                tags=self.tags,
                today_iso=self.today_iso,
                now_hhmm=self.now_hhmm,
                reschedule=reschedule,
                campaigns=self.campaigns,
            )
            for item in self.plan_items
        ]

    @rx.var
    def plan_rows_by_time(self) -> list[PlanRowVM]:
        """«Confirmar» reads the plan as a day does: in the order it will go out."""
        return sorted(self.plan_rows, key=lambda r: (r.date, r.time))

    @rx.var
    def minute_options(self) -> list[str]:
        """Five-minute steps, plus any piece's own minute when it is not on a step (a
        rescheduled 3:47), so the picker never silently changes it."""
        return sorted({*MINUTE_STEPS, *(f"{split_time(i.time)[1]:02d}" for i in self.plan_items)})

    @rx.var
    def form_post_ok(self) -> bool:
        return bool(self.plan_items)

    @rx.var
    def form_when_ok(self) -> bool:
        rows = self.plan_rows
        return bool(rows) and all(row.error == "" for row in rows)

    @rx.var
    def form_steps_done(self) -> list[bool]:
        return assign_steps_done(
            post_ok=self.form_post_ok, when_ok=self.form_when_ok, reached=self.form_reached
        )

    @rx.var
    def form_step_error(self) -> str:
        """Why the current step cannot be left yet ("" when it can): the one message the
        «Continuar» button is disabled over."""
        if self.form_step == STEP_POST:
            return "" if self.plan_items else _POST_REQUIRED
        if self.form_step == STEP_WHEN:
            pending = [row for row in self.plan_rows if row.error]
            if not pending:
                return ""
            if len(pending) == 1:
                return f"«{pending[0].title}»: {pending[0].error}"
            return f"Revisa {len(pending)} publicaciones: falta completar su programación."
        return ""

    @rx.var
    def form_can_advance(self) -> bool:
        return self.form_step_error == "" and self.form_step < STEP_LAST

    @rx.var
    def form_is_last_step(self) -> bool:
        return self.form_step == STEP_LAST

    @rx.var
    def form_step_title(self) -> str:
        return ASSIGN_STEPS[self.form_step] if 0 <= self.form_step < len(ASSIGN_STEPS) else ""

    @rx.var
    def form_event_count(self) -> int:
        """How many `calendar_events` «Programar» will create: Σ occurrences × accounts."""
        if self.form_mode == MODE_RESCHEDULE:
            return 1
        return sum(row.event_count for row in self.plan_rows)

    @rx.var
    def form_selection_label(self) -> str:
        n = len(self.plan_items)
        if n == 0:
            return "Nada seleccionado"
        return "1 publicación seleccionada" if n == 1 else f"{n} publicaciones seleccionadas"

    @rx.var
    def form_plan_summary(self) -> str:
        """ "3 publicaciones · 4 fechas · lun 12 oct → mié 14 oct" for the confirm head."""
        rows = self.plan_rows_by_time
        if not rows:
            return ""
        pieces = "1 publicación" if len(rows) == 1 else f"{len(rows)} publicaciones"
        n = self.form_event_count
        events = "1 fecha" if n == 1 else f"{n} fechas"
        first, last = rows[0].when_label.split(" · ")[0], rows[-1].when_label.split(" · ")[0]
        span = first if first == last else f"{first} → {last}"
        return f"{pieces} · {events} · {span}"

    @rx.var
    def form_step_counter(self) -> str:
        """N6: «Paso 2 de 3» with the real count — a move has no «Contenido» to pick, so
        it walks «Paso 1 de 2»."""
        total = len(ASSIGN_STEPS)
        number = self.form_step + 1
        if self.form_mode == MODE_RESCHEDULE:
            total, number = total - 1, max(number - 1, 1)
        return f"Paso {number} de {total}"

    @rx.var
    def form_confirm_line(self) -> str:
        """m-24842985 (N13): «Confirmar» says it in one sentence — «Sale el jueves 30 a
        las 7:00 p. m. en Instagram @cuenta» for one piece; for several, the plan's
        summary (each piece carries its own sentence on the timeline)."""
        rows = self.plan_rows_by_time
        if len(rows) == 1 and rows[0].sale_line:
            return rows[0].sale_line
        return self.form_plan_summary

    @rx.var
    def form_submit_label(self) -> str:
        if self.form_mode == MODE_RESCHEDULE:
            return SUBMIT_RESCHEDULE
        n = self.form_event_count
        return SUBMIT_ASSIGN if n <= 1 else f"{SUBMIT_ASSIGN} {n} publicaciones"

    @rx.var
    def form_story_warnings(self) -> int:
        """Pieces whose destination carries a limit we cannot check here (a video story's
        60 s) — «Confirmar» says so once, before the operator confirms."""
        return sum(1 for row in self.plan_rows if row.destination_warning)

    @rx.var
    def form_goal_count(self) -> int:
        return len(self.form_goals)

    # -- loading --------------------------------------------------------------

    async def _tenant(self):
        async with self:
            auth = await self.get_state(AuthState)
            return tenant_uuid(auth.session_tenant_id)

    @rx.event(background=True)
    async def load(self):
        """Load (or reload) the week currently in `monday_iso` ("" → this week)."""
        async for update in self._load_week(quiet=False):
            yield update

    @rx.event(background=True)
    async def refresh_week(self, _tick: str = ""):
        """The calendar's own clock (every `REFRESH_SECONDS` while the page is open):
        reload the week quietly so what the worker published — or failed — shows
        without a manual reload. No spinner, no scroll jump, and never while a panel is
        being filled or saved."""
        async with self:
            busy = self.form_open or self.saving or self.loading
        if busy:
            return
        async for update in self._load_week(quiet=True):
            yield update

    async def _load_week(self, *, quiet: bool):
        async with self:
            if not quiet:
                self.loading = True
            self.load_error = ""
            monday_iso, connection_filter = self.monday_iso, self.connection_filter
            view_tz, tag_filter = self.view_tz, tuple(self.tag_filter)
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.loading = False
                self.load_error = _NO_TENANT
            return
        try:
            data = await asyncio.to_thread(
                load_week, tenant_id, monday_iso, connection_filter, view_tz, tag_filter
            )
        except PlannerError as exc:
            async with self:
                self.loading = False
                self.load_error = planner_error_message(exc)
            return
        except Exception as exc:
            logger.error("planner load_week failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.load_error = _LOAD_FAILED
            return
        async with self:
            self.monday_iso = data.monday_iso
            self.today_iso = data.today_iso
            self.week_label = data.week_label
            self.month_label = data.month_label
            self.tz_name = data.tz_name
            self.days = data.days
            self.rows = data.rows
            self.total_events = data.total_events
            self.unscheduled = data.unscheduled
            self.schedulable = data.schedulable
            self.connections = data.connections
            self.tenant_tz = data.tenant_tz
            self.now_hhmm = data.now_hhmm
            self.auto_publish = data.auto_publish
            self.tags = data.tags
            self.campaigns = data.campaigns
            known = {t.id for t in data.tags}
            self.tag_filter = [t for t in self.tag_filter if t in known]
            self.loading = False
            # `/planner?post=<id>` (the gallery's «Asignar»): the same drawer, opened on
            # that POST once the week — and the POST list — is here. Once per id.
            wanted = self._url_post()
            if wanted and wanted != self._url_post_opened:
                self._url_post_opened = wanted
                self._open_assign(post_id=wanted, now=self._url_now())
        if not quiet:
            yield rx.call_script(_SCROLL_TO_OPENING_HOUR)
            async with self:
                address = self._sync_address()
            yield address

    def _url_param(self, name: str) -> str:
        try:
            return str(self.router.url.query_parameters.get(name, "") or "")
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return ""

    def _url_post(self) -> str:
        return self._url_param("post")

    def _sync_address(self) -> rx.event.EventSpec:
        """m-24842987: the address bar follows the week and the view on screen, so a
        reload — or the browser's back from a ficha — lands on the same week. The
        router's own history entry is kept (only the URL changes)."""
        import json
        from urllib.parse import urlencode

        from .review_links import review_destination

        href = week_href(self.monday_iso, self.view_mode)
        review = review_destination(
            "/planner?"
            + urlencode(
                {
                    key: self._url_param(key)
                    for key in ("revisar", "pieza", "evento", "fallos")
                    if self._url_param(key)
                }
            )
        )
        if review:
            href += ("&" if "?" in href else "?") + review.split("?", 1)[1]
        return rx.call_script(
            "window.history.replaceState(window.history.state, '', " + json.dumps(href) + ")"
        )

    def _url_now(self) -> bool:
        """`/planner?post=<id>&cuando=ahora` (the «Publicar ahora» of the approved card,
        m-24842985): the drawer opens with «Ahora» already chosen."""
        try:
            value = self.router.url.query_parameters.get(URL_WHEN, "") or ""
        except Exception:  # noqa: BLE001 — no router outside a page (tests)
            return False
        return str(value) == URL_WHEN_NOW

    @rx.event
    def load_current_week(self):
        """on_load: open on the week (and view) the address names — `?semana=` and
        `?vista=`, what «‹ Tu semana» sends back (m-24842987) — or on the current week,
        always with no dialog left open.

        State outlives the route: leaving through «Ver POST» with the detail open used to
        bring the same (stale) dialog back on the next visit."""
        self.monday_iso = parse_week_param(self._url_param(URL_WEEK))
        view = parse_view_param(self._url_param(URL_VIEW))
        if view:
            self.view_mode = view
        self.form_open = False
        self.detail_open = False
        self.filters_open = False
        self.detail_confirm = ""
        self.delete_tag_id = ""
        return PlannerState.load

    @rx.event
    def previous_week(self):
        if self.monday_iso:
            self.monday_iso = shift_week(self.monday_iso, -1)
        return PlannerState.load

    @rx.event
    def next_week(self):
        if self.monday_iso:
            self.monday_iso = shift_week(self.monday_iso, 1)
        return PlannerState.load

    @rx.event
    def go_to_today(self):
        self.monday_iso = ""
        return PlannerState.load

    @rx.event
    def set_view_mode(self, value: str | list[str]):
        # The segmented control's on_change is typed `str | list[str]`; it sends a str.
        chosen = value[0] if isinstance(value, list) and value else value
        self.view_mode = chosen if chosen in (VIEW_CALENDAR, VIEW_LIST) else VIEW_CALENDAR
        if self.view_mode == VIEW_CALENDAR:
            return [rx.call_script(_SCROLL_TO_OPENING_HOUR), self._sync_address()]
        return self._sync_address()

    # -- timezone picker ------------------------------------------------------

    @rx.event
    def set_tz_query(self, value: str) -> None:
        self.tz_query = value

    @rx.event
    def choose_tz(self, value: str):
        self.view_tz = "" if value == CALENDAR_DEFAULT_TZ else value
        self.tz_query = ""
        return PlannerState.load

    # -- tag filter -----------------------------------------------------------

    @rx.event
    def set_tag_query(self, value: str) -> None:
        self.tag_query = value

    @rx.event
    def toggle_tag_filter(self, tag_id: str):
        self.tag_filter = (
            [t for t in self.tag_filter if t != tag_id]
            if tag_id in self.tag_filter
            else [*self.tag_filter, tag_id]
        )
        return PlannerState.load

    @rx.event
    def clear_tag_filter(self):
        self.tag_filter = []
        self.tag_query = ""
        return PlannerState.load

    @rx.event(background=True)
    async def create_tag_from_filter(self):
        """The filter popover's "Crear etiqueta" row: create the label from the query."""
        async with self:
            name = self.tag_query
        tag = await self._create_tag(name)
        if tag is None:
            return
        async with self:
            self.tag_query = ""
        yield rx.toast.success("Etiqueta creada: " + tag.name)

    @rx.event(background=True)
    async def add_suggested_tag(self, name: str, color: str, post_id: str):
        """A suggested tag clicked on a piece of the plan: create it (with its colour)
        and put it on that piece."""
        tag = await self._create_tag(name, color)
        if tag is None:
            return
        async with self:
            item = self._item(post_id)
            if item is not None and tag.id not in item.tag_ids:
                self._update_item(post_id, tag_ids=[*item.tag_ids, tag.id])

    async def _create_tag(self, name: str, color: str = "") -> TagVM | None:
        tenant_id = await self._tenant()
        if tenant_id is None:
            return None
        try:
            tag = await asyncio.to_thread(create_tag, tenant_id, name, color)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner create_tag failed: %s", type(exc).__name__)
            async with self:
                self.form_error = planner_error_message(exc)
            return None
        async with self:
            if all(t.id != tag.id for t in self.tags):
                self.tags = sorted([*self.tags, tag], key=lambda t: t.name.lower())
        return tag

    # -- the POST's own review from the dialog ------------------------------------

    @rx.event(background=True)
    async def approve_post_from_detail(self):
        """m-24842984: «Aprobar» on the panel of a publication in review — the gallery's
        approval (creative FSM `generated → approved`), nothing more. It publishes
        nothing (N13): the event keeps the day and hour the owner chose and the calendar
        worker takes it only then. The panel is read again in place (no skeleton, no
        page reload), so its state turns to approved and its line says when it goes out."""
        async with self:
            if self.review_busy:
                return
            event_id = self.detail.event_id
            view_tz = self.view_tz
            self.review_busy = True
            self.review_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            async with self:
                self.review_busy = False
            return
        try:
            await asyncio.to_thread(approve_post, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, (PlannerError, CreativeInvalidTransition)):
                logger.error("planner approve_post failed: %s", type(exc).__name__)
            async with self:
                self.review_busy = False
                if isinstance(exc, (NoPassingVariant, PriceBlocked)):
                    self.review_error = (
                        REVIEW_EDIT_NOTE if isinstance(exc, NoPassingVariant) else exc.detail
                    )
            yield rx.toast.error(approve_error_message(exc))
            return
        try:
            detail = await asyncio.to_thread(event_detail, tenant_id, event_id, view_tz)
        except Exception as exc:  # noqa: BLE001 — the approval stands; `load` re-reads
            logger.warning("planner detail after approve failed: %s", type(exc).__name__)
            detail = None
        async with self:
            self.review_busy = False
            if detail is not None and self.detail.event_id == event_id:
                self.detail = detail
            auto_publish = self.auto_publish
        yield rx.toast.success(
            approved_toast(detail, auto_publish) if detail is not None else APPROVED_CHECK_TOAST
        )
        yield PlannerState.load

    @rx.event(background=True)
    async def reject_post_from_detail(self):
        """Reject the event's POST (creative FSM `generated → rejected`). The event stays
        scheduled; the worker will not publish a rejected POST."""
        async with self:
            if self.review_busy:
                return
            event_id = self.detail.event_id
            self.review_busy = True
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            async with self:
                self.review_busy = False
            return
        try:
            await asyncio.to_thread(reject_post, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, (PlannerError, CreativeInvalidTransition)):
                logger.error("planner reject_post failed: %s", type(exc).__name__)
            async with self:
                self.review_busy = False
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.review_busy = False
        yield rx.toast.success("Publicación rechazada: no saldrá.")
        yield PlannerState.load
        yield PlannerState.open_detail(event_id)

    @rx.event
    def ask_remove_rejected(self) -> None:
        self.detail_confirm = CONFIRM_REMOVE

    @rx.event(background=True)
    async def confirm_remove_rejected(self):
        async with self:
            event_id = self.detail.event_id
            self.detail_confirm = ""
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            removed = await asyncio.to_thread(remove_rejected_post, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner remove_rejected failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail_open = False
        yield rx.toast.success(
            "Publicación quitada de tu semana"
            + (f" ({removed} publicaciones)" if removed > 1 else "")
        )
        yield PlannerState.load

    # -- delete a tag ------------------------------------------------------------

    @rx.event
    def ask_delete_tag(self, tag_id: str, name: str) -> None:
        """The trash icon on a filter row: that row turns into «¿Eliminar?» in place."""
        self.delete_tag_id = tag_id
        self.delete_tag_name = name

    @rx.event
    def cancel_delete_tag(self) -> None:
        self.delete_tag_id = ""
        self.delete_tag_name = ""

    @rx.event(background=True)
    async def confirm_delete_tag(self):
        async with self:
            tag_id, name = self.delete_tag_id, self.delete_tag_name
        tenant_id = await self._tenant()
        if tenant_id is None or not tag_id:
            return
        try:
            await asyncio.to_thread(delete_tag, tenant_id, tag_id)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner delete_tag failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.tags = [t for t in self.tags if t.id != tag_id]
            self.tag_filter = [t for t in self.tag_filter if t != tag_id]
            self.plan_items = [
                replace(item, tag_ids=[t for t in item.tag_ids if t != tag_id])
                for item in self.plan_items
            ]
            self.delete_tag_id = ""
        yield rx.toast.success("Etiqueta eliminada: " + name)
        yield PlannerState.load

    # -- tags in the detail dialog (saved right away) -------------------------

    @rx.event(background=True)
    async def remove_detail_tag(self, tag_id: str):
        async with self:
            event_id = self.detail.event_id
            tag_ids = tuple(t for t in self.detail.tag_ids if t != tag_id)
        async for update in self._save_detail_tags(event_id, tag_ids):
            yield update

    @rx.event(background=True)
    async def add_detail_tag(self, tag_id: str):
        async with self:
            event_id = self.detail.event_id
            tag_ids = (*self.detail.tag_ids, tag_id)
        async for update in self._save_detail_tags(event_id, tag_ids):
            yield update

    async def _save_detail_tags(self, event_id: str, tag_ids: tuple[str, ...]):
        async with self:
            view_tz = self.view_tz
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            await asyncio.to_thread(set_event_tags, tenant_id, event_id, tag_ids)
            detail = await asyncio.to_thread(event_detail, tenant_id, event_id, view_tz)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner set_event_tags failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail = detail
        yield PlannerState.load

    # -- goals of a planned publication (saved right away) -----------------------------

    @rx.event(background=True)
    async def toggle_detail_goal(self, key: str):
        """A goal on or off for the open event (0042) — the same goals as «Nueva
        publicación», editable afterwards for the later analysis."""
        if key not in PLAN_GOAL_KEYS:
            return
        async with self:
            event_id = self.detail.event_id
            current = list(self.detail.goal_keys)
            view_tz = self.view_tz
        goals = tuple(g for g in current if g != key) if key in current else (*current, key)
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            await asyncio.to_thread(set_event_goals, tenant_id, event_id, goals)
            detail = await asyncio.to_thread(event_detail, tenant_id, event_id, view_tz)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner set_event_goals failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail = detail

    # -- tags in the form -----------------------------------------------------

    @rx.event
    def set_form_tag_query(self, value: str) -> None:
        self.form_tag_query = value

    @rx.event(background=True)
    async def create_tag_in_form(self):
        async with self:
            name = self.form_tag_query
        tag = await self._create_tag(name)
        if tag is None:
            return
        async with self:
            self.form_tag_query = ""

    @rx.event
    def toggle_unscheduled(self, was_open: bool) -> None:
        """The toolbar's «Por programar»: the button knows whether the panel is open at
        its width (the automatic default differs between a phone and a wide screen), and
        the owner's choice then holds for every width."""
        self.unscheduled_pref = UNSCHEDULED_CLOSED if was_open else UNSCHEDULED_OPEN

    @rx.event
    def close_unscheduled(self) -> None:
        self.unscheduled_pref = UNSCHEDULED_CLOSED

    @rx.event
    def open_assign_waiting(self) -> None:
        """«Programar mis {n} publicaciones»: the drawer with every waiting approved
        publication already picked, straight to its date and time."""
        self._open_assign()
        added = [self._add_post(post.post_id) for post in self.unscheduled if post.schedulable]
        if any(added):
            self._go_to(STEP_WHEN)

    @rx.event
    def open_filters(self) -> None:
        self.filters_open = True

    @rx.event
    def set_filters_open(self, value: bool) -> None:
        self.filters_open = bool(value)
        if not value:
            self.tz_query = ""
            self.delete_tag_id = ""

    @rx.event
    def set_connection_filter(self, value: str):
        self.connection_filter = value or ALL_CONNECTIONS
        return PlannerState.load

    # -- assign / reschedule --------------------------------------------------

    def _reset_form(self) -> None:
        self.form_error = ""
        self.saving = False
        self.form_event_id = ""
        self.plan_items = []
        self.form_goals = []
        self.form_tag_query = ""
        self.form_kind_filter = "all"
        self.form_default_date = ""
        self.form_default_time = "09:00"
        self.form_step = STEP_POST
        self.form_reached = STEP_POST
        self.more_open = []
        self.more_auto = []

    def _first_account(self) -> list[str]:
        """The first compatible account is preselected: one account is the common case."""
        first = next((c.id for c in self.connections if c.compatible), "")
        return [first] if first else []

    def _new_item(self, post: PostOptionVM) -> PlanItem:
        """A piece just picked: the drawer's default day and time, the first account,
        — for a template package (MP-11) — its next output without a live event, and
        the destination it publishes as today (QUA-118 v2), changeable in the step."""
        return PlanItem(
            post_id=post.post_id,
            date=self.form_default_date,
            time=self.form_default_time,
            connection_ids=self._first_account(),
            output_port=post.next_port,
            destination=_starting_destination(post, post.next_port),
        )

    def _add_post(self, post_id: str) -> bool:
        post = self._post_for(post_id)
        if post is None or not post.schedulable or post_id in self.form_selected_ids:
            return False
        self.plan_items = [*self.plan_items, self._new_item(post)]
        self._sync_more_open()
        return True

    def _update_item(self, post_id: str, **changes) -> None:
        self.plan_items = [
            replace(item, **changes) if item.post_id == post_id else item
            for item in self.plan_items
        ]
        self._sync_more_open()

    def _sync_more_open(self) -> None:
        """m-24842985: open «Más opciones» on its own when what a piece is missing sits
        in there — once, when that becomes true; closing it afterwards stays closed."""
        needing = [row.post_id for row in self.plan_rows if row.needs_more]
        fresh = [p for p in needing if p not in self.more_auto]
        if fresh:
            self.more_open = [*self.more_open, *(p for p in fresh if p not in self.more_open)]
        self.more_auto = needing

    def _item(self, post_id: str) -> PlanItem | None:
        return next((item for item in self.plan_items if item.post_id == post_id), None)

    def _open_assign(
        self, post_id: str = "", day_iso: str = "", hour: int | None = None, now: bool = False
    ) -> None:
        """Open «Nueva publicación», optionally with a POST (the card's «Asignar», a drag)
        and/or a day and hour (a calendar cell) already chosen — or, with `now`, that
        POST on «Ahora» (m-24842985)."""
        self._reset_form()
        self.form_mode = MODE_ASSIGN
        default_day = self.today_iso if self._week_contains_today() else self.monday_iso
        self.form_default_date = day_iso or default_day
        if hour is not None:
            self.form_default_time = f"{int(hour):02d}:00"
        elif self.form_default_date == self.today_iso and self.now_hhmm:
            # Today: the next full hour, never a time already gone (09:00 at 21:00 was a
            # refusal waiting at the last step).
            self.form_default_time = f"{min(split_time(self.now_hhmm)[0] + 1, 23):02d}:00"
        self.form_open = True
        # A POST already chosen skips straight to its programming.
        if post_id and self._add_post(post_id):
            if now:
                self._update_item(post_id, now=True)
            self._go_to(STEP_WHEN)

    @rx.event
    def open_assign_for_post(self, post_id: str) -> None:
        self._open_assign(post_id=post_id)

    @rx.event
    def open_assign_for_day(self, day_iso: str) -> None:
        self._open_assign(day_iso=day_iso)

    @rx.event
    def open_assign_for_slot(self, day_iso: str, hour: int) -> None:
        """A click on an empty calendar cell: that day, that hour. A past day does
        nothing — there is nothing to plan there."""
        if self.today_iso and day_iso < self.today_iso:
            return
        self._open_assign(day_iso=day_iso, hour=int(hour))

    @rx.event
    def open_assign_blank(self) -> None:
        self._open_assign()

    # -- drag & drop from «Sin programar» to a day × hour cell --------------------

    @rx.var
    def dragging(self) -> bool:
        return self.drag_post_id != ""

    @rx.event
    def start_drag(self, post_id: str) -> None:
        self.drag_post_id = post_id

    @rx.event
    def end_drag(self) -> None:
        self.drag_post_id = ""

    @rx.event
    def drop_on_slot(self, day_iso: str, hour: int) -> None:
        """A card dropped on a cell: the drawer opens prefilled with that POST, day and
        hour — exactly what a click on the cell does, with the POST already chosen.
        Nothing is created here; only «Programar» creates. A past day takes nothing."""
        post_id, self.drag_post_id = self.drag_post_id, ""
        if not post_id or (self.today_iso and day_iso < self.today_iso):
            return
        self._open_assign(post_id=post_id, day_iso=day_iso, hour=int(hour))

    @rx.event
    def close_form(self) -> None:
        self.form_open = False
        self.form_error = ""

    @rx.event
    def set_form_open(self, value: bool) -> None:
        self.form_open = value
        if not value:
            self.form_error = ""

    # «Contenido»

    @rx.event
    def toggle_plan_post(self, post_id: str) -> None:
        """A tile clicked: in the plan or out of it. Only a ready POST (D1) gets in; a
        reschedule's piece is fixed."""
        if self.form_mode == MODE_RESCHEDULE:
            return
        if post_id in self.form_selected_ids:
            self.plan_items = [i for i in self.plan_items if i.post_id != post_id]
        else:
            self._add_post(post_id)

    @rx.event
    def set_form_kind_filter(self, value: str | list[str]) -> None:
        chosen = value[0] if isinstance(value, list) and value else value
        self.form_kind_filter = chosen if isinstance(chosen, str) and chosen else "all"

    # «Programación» — every handler names the piece by its POST id

    @rx.event
    def set_item_now(self, post_id: str, value: bool) -> None:
        """m-24842985: «Ahora» or «Elegir día y hora». «Ahora» plans nothing yet: the
        instant is taken when «Programar» is tapped (`submit_form`)."""
        self._update_item(post_id, now=bool(value))

    @rx.event
    def set_item_more(self, post_id: str, value: str | list[str]) -> None:
        """«Más opciones» of a piece opened («more») or closed («»)."""
        chosen = value[0] if isinstance(value, list) and value else value
        others = [p for p in self.more_open if p != post_id]
        self.more_open = [*others, post_id] if chosen else others

    @rx.event
    def set_item_date(self, post_id: str, value: str) -> None:
        self._update_item(post_id, date=value)

    @rx.event
    def set_item_time(self, post_id: str, value: str) -> None:
        self._update_item(post_id, time=value)

    @rx.event
    def set_item_hour12(self, post_id: str, value: str) -> None:
        item = self._item(post_id)
        if item is None:
            return
        hour, minute = split_time(item.time)
        meridiem = "am" if hour < 12 else "pm"
        self._update_item(post_id, time=f"{to_24h(int(value), meridiem):02d}:{minute:02d}")

    @rx.event
    def set_item_minute(self, post_id: str, value: str) -> None:
        item = self._item(post_id)
        if item is None:
            return
        hour, _ = split_time(item.time)
        self._update_item(post_id, time=f"{hour:02d}:{int(value):02d}")

    @rx.event
    def set_item_meridiem(self, post_id: str, value: str) -> None:
        item = self._item(post_id)
        if item is None:
            return
        hour, minute = split_time(item.time)
        new_hour = to_24h(hour % 12 or 12, "pm" if value == "pm" else "am")
        self._update_item(post_id, time=f"{new_hour:02d}:{minute:02d}")

    @rx.event
    def set_item_output(self, post_id: str, value: str | list[str]) -> None:
        """Another output of a package: its file decides where it may go, so the
        destination starts again on that output's own."""
        chosen = value[0] if isinstance(value, list) and value else value
        port = chosen if isinstance(chosen, str) else ""
        post = self._post_for(post_id)
        destination = _starting_destination(post, port) if post is not None else ""
        self._update_item(post_id, output_port=port, destination=destination)

    @rx.event
    def set_item_destination(self, post_id: str, destination: str) -> None:
        """«¿Dónde quieres publicarlo?»: only an available destination is taken — a
        disabled button never changes the piece. A move keeps its destination."""
        if self.form_mode == MODE_RESCHEDULE:
            return
        row = next((r for r in self.plan_rows if r.post_id == post_id), None)
        if row is None or not any(d.key == destination and d.available for d in row.destinations):
            return
        self._update_item(post_id, destination=destination)

    @rx.event
    def toggle_item_connection(self, post_id: str, connection_id: str) -> None:
        """An account chip: an incompatible account can never be chosen (the service
        would refuse it anyway). A reschedule moves one event, so there the choice
        replaces instead of accumulating."""
        item = self._item(post_id)
        if item is None or not any(
            c.id == connection_id and c.compatible for c in self.connections
        ):
            return
        if self.form_mode == MODE_RESCHEDULE:
            ids = [connection_id]
        elif connection_id in item.connection_ids:
            ids = [c for c in item.connection_ids if c != connection_id]
        else:
            ids = [*item.connection_ids, connection_id]
        self._update_item(post_id, connection_ids=ids)

    @rx.event
    def toggle_item_tag(self, post_id: str, tag_id: str) -> None:
        item = self._item(post_id)
        if item is None:
            return
        ids = (
            [t for t in item.tag_ids if t != tag_id]
            if tag_id in item.tag_ids
            else [*item.tag_ids, tag_id]
        )
        self._update_item(post_id, tag_ids=ids)

    @rx.event
    def set_item_repeat(self, post_id: str, value: bool) -> None:
        """Turning the weekly series on starts on the date's own weekday; the operator
        then adds or removes days (`toggle_item_repeat_day`)."""
        item = self._item(post_id)
        if item is None:
            return
        days = list(item.repeat_days)
        if value and not days:
            try:
                days = [date.fromisoformat(item.date).weekday()]
            except ValueError:
                days = []
        self._update_item(post_id, repeat=bool(value), repeat_days=days)

    @rx.event
    def toggle_item_repeat_day(self, post_id: str, day: int) -> None:
        """A weekday of the series on or off — never the last one (a series needs a day)."""
        item = self._item(post_id)
        if item is None or not 0 <= int(day) <= 6:
            return
        day = int(day)
        days = list(item.repeat_days)
        if day in days:
            if len(days) == 1:
                return
            days.remove(day)
        else:
            days.append(day)
        self._update_item(post_id, repeat_days=sorted(days))

    @rx.event
    def set_item_repeat_count(self, post_id: str, value: str) -> None:
        self._update_item(post_id, repeat_count=value)

    @rx.event
    def apply_to_all(self, post_id: str) -> None:
        """«Usar en todas»: this piece's accounts, tags and campaign (QUA-143) on every
        piece of the plan — the common case is one brand account and one campaign for the
        whole day. The campaign copied is the one the piece SHOWS (its pick, or its POST's
        own), so every other POST is put in it on «Confirmar»."""
        source = self._item(post_id)
        if source is None:
            return
        chosen = campaign_value(source, self._post_for(post_id))
        self.plan_items = [
            replace(
                item,
                connection_ids=list(source.connection_ids),
                tag_ids=list(source.tag_ids),
                campaign=chosen,
                new_campaign_name=source.new_campaign_name,
                new_campaign_color=source.new_campaign_color,
            )
            for item in self.plan_items
        ]
        self._sync_more_open()

    # QUA-143 — the piece's campaign: the POST's, applied only on «Confirmar».

    @rx.event
    def set_item_campaign(self, post_id: str, value: str) -> None:
        """The selector: a campaign id, «Sin campaña» or «Nueva campaña» (which opens the
        name and the four colours, the suggested one preselected)."""
        item = self._item(post_id)
        if item is None:
            return
        if value == CAMPAIGN_NEW:
            self._update_item(
                post_id,
                campaign=CAMPAIGN_NEW,
                new_campaign_color=item.new_campaign_color or suggested_color(self.campaigns),
            )
        else:
            self._update_item(post_id, campaign=value)

    @rx.event
    def set_item_new_campaign_name(self, post_id: str, value: str) -> None:
        self._update_item(post_id, new_campaign_name=value)

    @rx.event
    def set_item_new_campaign_color(self, post_id: str, color: str) -> None:
        if color in COLOR_LABELS:  # the closed list of four, never a state colour
            self._update_item(post_id, new_campaign_color=color)

    # «Confirmar»

    @rx.event
    def edit_plan_item(self, post_id: str) -> None:
        """✎ on a preview: back to «Programación», where that piece is edited."""
        if self._item(post_id) is not None:
            self._go_to(STEP_WHEN)

    @rx.event
    def remove_plan_item(self, post_id: str) -> None:
        """🗑 on a preview: the piece leaves the plan (nothing was created yet). With the
        plan empty, back to «Contenido» to pick something."""
        if self.form_mode == MODE_RESCHEDULE:
            return
        self.plan_items = [i for i in self.plan_items if i.post_id != post_id]
        if not self.plan_items:
            self.form_reached = STEP_POST
            self._go_to(STEP_POST)

    @rx.event
    def toggle_goal(self, key: str) -> None:
        if key not in PLAN_GOAL_KEYS:
            return
        self.form_goals = (
            [g for g in self.form_goals if g != key]
            if key in self.form_goals
            else [*self.form_goals, key]
        )

    def _go_to(self, step: int) -> None:
        self.form_step = max(STEP_POST, min(step, STEP_LAST))
        self.form_reached = max(self.form_reached, self.form_step)
        self.form_error = ""

    @rx.event
    def next_step(self) -> None:
        """«Continuar»: only past a valid step — the step's own message says otherwise."""
        if self.form_can_advance:
            self._go_to(self.form_step + 1)

    @rx.event
    def prev_step(self) -> None:
        if self.form_mode == MODE_RESCHEDULE and self.form_step <= STEP_WHEN:
            return  # a move's piece is fixed: there is no «Contenido» to go back to
        self._go_to(self.form_step - 1)

    @rx.event
    def go_to_step(self, step: int) -> None:
        """The stepper: back to any step (to fix something); forward only while every
        step before the target is completed — at most one past the current step, since a
        step counts as done only once reached (`assign_steps_done`)."""
        if self.form_mode == MODE_RESCHEDULE and step == STEP_POST:
            return
        if step <= self.form_step or all(self.form_steps_done[:step]):
            self._go_to(step)

    @rx.event(background=True)
    async def submit_form(self):
        """«Programar» / «Guardar cambios» from «Confirmar». Everything the steps
        validated is re-validated by the service. Each piece is planned on its own
        (atomic within the piece: its accounts and its series, QUA-118 A4); if one is
        refused, the pieces already planned leave the drawer — so a retry never plans
        them twice — and the refused one stays, with the service's reason."""
        async with self:
            if self.saving:
                return
            mode, event_id = self.form_mode, self.form_event_id
            view_tz = self.view_tz
            # m-24842985: «Ahora» becomes an instant only here, on the owner's tap — the
            # next minutes in the zone the week plans in; the worker takes it next pass.
            rows = rows_for_submit(self.plan_rows, view_tz or self.tz_name, datetime.now(UTC))
            all_now = bool(rows) and all(r.now for r in rows)
            plan_goals = tuple(self.form_goals)
            if not rows:
                self.form_error = _FORM_INCOMPLETE
                return
            pending = next((row for row in rows if row.error), None)
            if pending is not None:
                self.form_error = f"«{pending.title}»: {pending.error}"
                return
            self.saving = True
            self.form_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.saving = False
                self.form_error = _NO_TENANT
            return
        created, planned, failure = await schedule_plan_rows(
            tenant_id, rows, mode=mode, event_id=event_id, view_tz=view_tz, goals=plan_goals
        )
        if failure:
            async with self:
                self.saving = False
                self.plan_items = [i for i in self.plan_items if i.post_id not in planned]
                self.form_error = failure + (
                    " Las publicaciones anteriores ya quedaron programadas." if planned else ""
                )
            if planned:
                yield PlannerState.load
            return
        async with self:
            self.saving = False
            self.form_open = False
            self.detail_open = False
            goals = [g.label for g in PLAN_GOALS if g.key in self.form_goals]
            # Jump to the week the first piece lands in, so the operator sees it appear.
            self.monday_iso = rows[0].date
        message = scheduled_message(
            created=created,
            day_iso=rows[0].date,
            at=rows[0].time,
            reschedule=mode == MODE_RESCHEDULE,
            now=all_now,
        )
        if goals:
            message += (
                ("" if message.endswith(".") else ".")
                + " Buscas: "
                + join_es([g.lower() for g in goals])
                + "."
            )
        yield rx.toast.success(message)
        yield PlannerState.load
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now

    # -- detail (a side panel, never a modal) -------------------------------------

    @rx.event(background=True)
    async def open_detail(self, event_id: str):
        """Open the event's panel."""
        await self._load_detail(event_id, "")

    @rx.event(background=True)
    async def open_detail_asking(self, event_id: str, confirm: str):
        """Open the event's panel with an inline confirmation already armed («cancel»
        from a card's ⋯ menu) — the panel asks, no dialog on top of it."""
        await self._load_detail(event_id, confirm)

    async def _load_detail(self, event_id: str, confirm: str) -> None:
        async with self:
            self.detail_open = True
            self.detail_loading = True
            self.detail_error = ""
            self.review_error = ""
            self.detail_confirm = confirm if confirm in (CONFIRM_CANCEL, CONFIRM_REMOVE) else ""
            self.detail = EventDetailVM()
            view_tz = self.view_tz
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.detail_loading = False
                self.detail_error = _NO_TENANT
            return
        try:
            detail = await asyncio.to_thread(event_detail, tenant_id, event_id, view_tz)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner event_detail failed: %s", type(exc).__name__)
            async with self:
                self.detail_loading = False
                self.detail_error = planner_error_message(exc)
            return
        async with self:
            self.detail = detail
            self.detail_loading = False
            if detail.final_review and not confirm:
                self.detail_open = False
        if detail.final_review and not confirm:
            from .final_review_state import FinalReviewState

            review = await self.get_state(FinalReviewState)
            await review._read(UUID(detail.post_id))

    @rx.event
    def set_detail_open(self, value: bool) -> None:
        self.detail_open = value
        if not value:
            self.detail_confirm = ""

    @rx.var
    def detail_post(self) -> PostOptionVM:
        """The open event's POST as the gallery knows it (its format and Cold/Hot), or an
        empty option when it is not listed."""
        for post in self.schedulable:
            if post.post_id == self.detail.post_id:
                return post
        return PostOptionVM(
            post_id="",
            title="",
            caption_excerpt="",
            thumbnail_url="",
            category_label="",
            approval_label="",
            approval_tone="neutral",
            detail_href="",
            temperature="",
        )

    @rx.event
    def reschedule_from_detail(self) -> None:
        self._reset_form()
        self.form_mode = MODE_RESCHEDULE
        self.form_event_id = self.detail.event_id
        self.plan_items = [
            PlanItem(
                post_id=self.detail.post_id,
                date=self.detail.local_date,
                time=self.detail.local_time,
                connection_ids=[self.detail.connection_id] if self.detail.connection_id else [],
                tag_ids=list(self.detail.tag_ids),
                output_port=self.detail.output_port,  # shown, never changed by a move
                destination=self.detail.destination,  # likewise: a move keeps it
            )
        ]
        self.detail_open = False
        self.detail_confirm = ""
        self.form_open = True
        self._go_to(STEP_WHEN)  # the POST is fixed: a move starts at its programming

    @rx.event(background=True)
    async def open_reschedule(self, event_id: str):
        """From a card's ⋯ menu: load the event, then open the reschedule form."""
        async with self:
            view_tz = self.view_tz
        tenant_id = await self._tenant()
        if tenant_id is None:
            return
        try:
            detail = await asyncio.to_thread(event_detail, tenant_id, event_id, view_tz)
        except Exception as exc:
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail = detail
        yield PlannerState.reschedule_from_detail

    # -- cancel (confirmed inside the panel) ------------------------------------------

    @rx.event
    def ask_cancel(self, event_id: str):
        """A card's ⋯ «Cancelar publicación»: the event's panel opens asking."""
        return PlannerState.open_detail_asking(event_id, CONFIRM_CANCEL)

    @rx.event
    def ask_cancel_from_detail(self) -> None:
        self.detail_confirm = CONFIRM_CANCEL

    @rx.event
    def dismiss_confirm(self) -> None:
        self.detail_confirm = ""

    @rx.event(background=True)
    async def confirm_cancel(self):
        async with self:
            event_id = self.detail.event_id
            self.detail_confirm = ""
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            await asyncio.to_thread(cancel_event, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner cancel failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail_open = False
        yield rx.toast.success("Publicación cancelada: salió del calendario")
        yield PlannerState.load
        yield PendingState.refresh_now  # m-24842963: the menu's count drops now
