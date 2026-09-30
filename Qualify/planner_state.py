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
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import reflex as rx
from qualify_api.creative.fsm import InvalidTransition as CreativeInvalidTransition
from qualify_api.planner.service import PlannerError

from .auth_state import AuthState
from .planner_provider import (
    ALL_CONNECTIONS,
    cancel_event,
    create_tag,
    delete_event,
    delete_tag,
    event_detail,
    load_week,
    planner_error_message,
    reject_post,
    remove_rejected_post,
    reschedule_event,
    schedule_post,
    set_event_tags,
)
from .planner_vm import (
    AUTO_PUBLISH_UNAVAILABLE,
    CALENDAR_DEFAULT_TZ,
    OPENING_HOUR,
    TAG_SUGGESTIONS,
    VIEW_CALENDAR,
    VIEW_LIST,
    ConnectionChoiceVM,
    DayColumnVM,
    EventDetailVM,
    HourRowVM,
    PostOptionVM,
    TagSuggestionVM,
    TagVM,
    TzOptionVM,
    timezone_options,
    tz_option,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudo cargar el Planificador. Inténtalo de nuevo."
_FORM_INCOMPLETE = "Completa el POST, la fecha, la hora y la cuenta."

MODE_ASSIGN = "assign"
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


MINUTE_STEPS: tuple[str, ...] = tuple(f"{m:02d}" for m in range(0, 60, 5))


def split_time(value: str) -> tuple[int, int]:
    """ "15:50" → (15, 50); anything unparsable → 09:00 (pure — tested directly)."""
    try:
        hour_text, minute_text = value.split(":")[:2]
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        return 9, 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return 9, 0
    return hour, minute


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
    show_unscheduled: bool = False
    # The zone the calendar shows and plans in. "" = CALENDAR_DEFAULT_TZ; a pick here
    # is a per-session view choice and is never written back to the tenant.
    view_tz: str = ""
    tenant_tz: str = ""
    auto_publish: str = AUTO_PUBLISH_UNAVAILABLE
    tz_query: str = ""
    # Planning tags (0025): the tenant's labels and the calendar's tag filter.
    tags: list[TagVM] = []
    tag_filter: list[str] = []
    tag_query: str = ""

    # -- assign / reschedule dialog --------------------------------------------
    form_open: bool = False
    form_mode: str = MODE_ASSIGN
    form_event_id: str = ""
    form_post_id: str = ""
    form_post_title: str = ""
    form_date: str = ""
    form_time: str = "09:00"
    form_connection_id: str = ""
    form_tag_ids: list[str] = []
    form_tag_query: str = ""
    form_error: str = ""
    saving: bool = False

    # -- detail / cancel ------------------------------------------------------
    detail_open: bool = False
    detail_loading: bool = False
    detail: EventDetailVM = EventDetailVM()
    detail_error: str = ""
    cancel_open: bool = False
    cancel_event_id: str = ""
    # -- delete a tag (confirmation) ------------------------------------------
    delete_event_open: bool = False
    remove_rejected_open: bool = False  # confirm "Quitar del calendario" (rejected POST)
    delete_event_id: str = ""
    delete_tag_open: bool = False
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
    def unscheduled_count(self) -> int:
        return len(self.unscheduled)

    # -- timezone picker ------------------------------------------------------

    @rx.var
    def tz_city_label(self) -> str:
        return tz_option(self.tz_name, datetime.now(UTC)).city if self.tz_name else ""

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

    # -- 12-hour time picker over `form_time` ("HH:MM", 24 h) ------------------

    @rx.var
    def form_hour12(self) -> str:
        return str(split_time(self.form_time)[0] % 12 or 12)

    @rx.var
    def form_minute(self) -> str:
        return f"{split_time(self.form_time)[1]:02d}"

    @rx.var
    def form_meridiem(self) -> str:
        return "am" if split_time(self.form_time)[0] < 12 else "pm"

    @rx.var
    def minute_options(self) -> list[str]:
        """Five-minute steps, plus the event's own minute when rescheduling one that is
        not on a step (e.g. 3:47), so the picker never silently changes it."""
        current = f"{split_time(self.form_time)[1]:02d}"
        return sorted({*MINUTE_STEPS, current})

    def _set_time(self, hour: int, minute: int) -> None:
        self.form_time = f"{hour:02d}:{minute:02d}"

    @rx.event
    def set_form_hour12(self, value: str) -> None:
        _, minute = split_time(self.form_time)
        self._set_time(to_24h(int(value), self.form_meridiem), minute)

    @rx.event
    def set_form_minute(self, value: str) -> None:
        hour, _ = split_time(self.form_time)
        self._set_time(hour, int(value))

    @rx.event
    def set_form_meridiem(self, value: str | list[str]) -> None:
        chosen = value[0] if isinstance(value, list) and value else value
        hour, minute = split_time(self.form_time)
        self._set_time(to_24h(hour % 12 or 12, "pm" if chosen == "pm" else "am"), minute)

    @rx.var
    def form_is_reschedule(self) -> bool:
        return self.form_mode == MODE_RESCHEDULE

    @rx.var
    def form_post_note(self) -> str:
        """Why the POST being scheduled will not publish yet — the same `readiness_note` the
        card and the detail dialog show (`planner_vm.readiness`), "" when it is ready."""
        if self.form_mode == MODE_RESCHEDULE:
            return self.detail.publish_note
        for post in self.schedulable:
            if post.post_id == self.form_post_id:
                return post.readiness_note
        return ""

    # -- loading --------------------------------------------------------------

    async def _tenant(self):
        async with self:
            auth = await self.get_state(AuthState)
            return tenant_uuid(auth.session_tenant_id)

    @rx.event(background=True)
    async def load(self):
        """Load (or reload) the week currently in `monday_iso` ("" → this week)."""
        async with self:
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
            self.auto_publish = data.auto_publish
            self.tags = data.tags
            known = {t.id for t in data.tags}
            self.tag_filter = [t for t in self.tag_filter if t in known]
            self.loading = False
        yield rx.call_script(_SCROLL_TO_OPENING_HOUR)

    @rx.event
    def load_current_week(self):
        """on_load: always open on the current week, with no dialog left open.

        State outlives the route: leaving through «Ver POST» with the detail open used to
        bring the same (stale) dialog back on the next visit."""
        self.monday_iso = ""
        self.form_open = False
        self.detail_open = False
        self.cancel_open = False
        self.delete_event_open = False
        self.delete_tag_open = False
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
            return rx.call_script(_SCROLL_TO_OPENING_HOUR)
        return None

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
    async def add_suggested_tag(self, name: str, color: str):
        """A suggested tag clicked in the form: create it (with its colour) and select it
        for the publication being planned."""
        tag = await self._create_tag(name, color)
        if tag is None:
            return
        async with self:
            if tag.id not in self.form_tag_ids:
                self.form_tag_ids = [*self.form_tag_ids, tag.id]

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

    # -- delete a cancelled event ---------------------------------------------

    @rx.event
    def ask_delete_event(self, event_id: str) -> None:
        self.delete_event_id = event_id
        self.delete_event_open = True

    @rx.event
    def ask_delete_event_from_detail(self) -> None:
        self.delete_event_id = self.detail.event_id
        self.delete_event_open = True

    @rx.event
    def set_delete_event_open(self, value: bool) -> None:
        self.delete_event_open = value

    @rx.event(background=True)
    async def confirm_delete_event(self):
        async with self:
            event_id = self.delete_event_id
            self.delete_event_open = False
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            await asyncio.to_thread(delete_event, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, PlannerError):
                logger.error("planner delete_event failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        async with self:
            self.detail_open = False
            self.delete_event_id = ""
        yield rx.toast.success("Publicación eliminada del calendario")
        yield PlannerState.load

    # -- the POST's own review from the dialog ------------------------------------

    @rx.event(background=True)
    async def reject_post_from_detail(self):
        """Reject the event's POST (creative FSM `generated → rejected`). The event stays
        scheduled; the worker will not publish a rejected POST."""
        async with self:
            event_id = self.detail.event_id
        tenant_id = await self._tenant()
        if tenant_id is None or not event_id:
            return
        try:
            await asyncio.to_thread(reject_post, tenant_id, event_id)
        except Exception as exc:
            if not isinstance(exc, (PlannerError, CreativeInvalidTransition)):
                logger.error("planner reject_post failed: %s", type(exc).__name__)
            yield rx.toast.error(planner_error_message(exc))
            return
        yield rx.toast.success("POST rechazado: no se publicará")
        yield PlannerState.load
        yield PlannerState.open_detail(event_id)

    @rx.event
    def ask_remove_rejected(self) -> None:
        self.remove_rejected_open = True

    @rx.event
    def set_remove_rejected_open(self, value: bool) -> None:
        self.remove_rejected_open = value

    @rx.event(background=True)
    async def confirm_remove_rejected(self):
        async with self:
            event_id = self.detail.event_id
            self.remove_rejected_open = False
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
            "POST quitado del calendario" + (f" ({removed} publicaciones)" if removed > 1 else "")
        )
        yield PlannerState.load

    # -- delete a tag ------------------------------------------------------------

    @rx.event
    def ask_delete_tag(self, tag_id: str, name: str) -> None:
        self.delete_tag_id = tag_id
        self.delete_tag_name = name
        self.delete_tag_open = True

    @rx.event
    def set_delete_tag_open(self, value: bool) -> None:
        self.delete_tag_open = value

    @rx.event(background=True)
    async def confirm_delete_tag(self):
        async with self:
            tag_id, name = self.delete_tag_id, self.delete_tag_name
            self.delete_tag_open = False
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
            self.form_tag_ids = [t for t in self.form_tag_ids if t != tag_id]
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

    # -- tags in the form -----------------------------------------------------

    @rx.event
    def toggle_form_tag(self, tag_id: str) -> None:
        self.form_tag_ids = (
            [t for t in self.form_tag_ids if t != tag_id]
            if tag_id in self.form_tag_ids
            else [*self.form_tag_ids, tag_id]
        )

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
            if tag.id not in self.form_tag_ids:
                self.form_tag_ids = [*self.form_tag_ids, tag.id]

    @rx.event
    def toggle_unscheduled(self) -> None:
        self.show_unscheduled = not self.show_unscheduled

    @rx.event
    def set_connection_filter(self, value: str):
        self.connection_filter = value or ALL_CONNECTIONS
        return PlannerState.load

    # -- assign / reschedule --------------------------------------------------

    def _reset_form(self) -> None:
        self.form_error = ""
        self.saving = False
        self.form_event_id = ""
        self.form_post_id = ""
        self.form_post_title = ""
        self.form_time = "09:00"
        self.form_date = ""
        self.form_connection_id = self.connections[0].id if self.connections else ""
        self.form_tag_ids = []
        self.form_tag_query = ""

    def _open_assign(self, post_id: str = "", day_iso: str = "") -> None:
        """Open the assign dialog, optionally with a POST (from the Sin programar panel)
        and/or a day (from a day column's "+") already chosen."""
        self._reset_form()
        self.form_mode = MODE_ASSIGN
        self.form_post_id = post_id
        default_day = self.today_iso if self._week_contains_today() else self.monday_iso
        self.form_date = day_iso or default_day
        self.form_open = True

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
        self._open_assign(day_iso=day_iso)
        self._set_time(int(hour), 0)

    @rx.event
    def open_assign_blank(self) -> None:
        self._open_assign()

    @rx.event
    def close_form(self) -> None:
        self.form_open = False
        self.form_error = ""

    @rx.event
    def set_form_open(self, value: bool) -> None:
        self.form_open = value
        if not value:
            self.form_error = ""

    @rx.event
    def set_form_post_id(self, value: str) -> None:
        self.form_post_id = value

    @rx.event
    def set_form_date(self, value: str) -> None:
        self.form_date = value

    @rx.event
    def set_form_time(self, value: str) -> None:
        self.form_time = value

    @rx.event
    def set_form_connection_id(self, value: str) -> None:
        self.form_connection_id = value

    @rx.event(background=True)
    async def submit_form(self):
        async with self:
            if self.saving:
                return
            mode = self.form_mode
            event_id, post_id = self.form_event_id, self.form_post_id
            day, at, connection_id = self.form_date, self.form_time, self.form_connection_id
            view_tz, tag_ids = self.view_tz, tuple(self.form_tag_ids)
            if (mode == MODE_ASSIGN and not post_id) or not day or not at or not connection_id:
                self.form_error = _FORM_INCOMPLETE
                return
            self.saving = True
            self.form_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.saving = False
                self.form_error = _NO_TENANT
            return
        try:
            if mode == MODE_RESCHEDULE:
                await asyncio.to_thread(
                    reschedule_event, tenant_id, event_id, day, at, connection_id, view_tz, tag_ids
                )
            else:
                await asyncio.to_thread(
                    schedule_post, tenant_id, post_id, day, at, connection_id, view_tz, tag_ids
                )
        except PlannerError as exc:
            async with self:
                self.saving = False
                self.form_error = planner_error_message(exc)
            return
        except Exception as exc:
            logger.error("planner %s failed: %s", mode, type(exc).__name__)
            async with self:
                self.saving = False
                self.form_error = planner_error_message(exc)
            return
        async with self:
            self.saving = False
            self.form_open = False
            self.detail_open = False
            # Jump to the week the event landed in, so the operator sees it appear.
            self.monday_iso = day
        yield rx.toast.success(
            "Publicación reprogramada" if mode == MODE_RESCHEDULE else "POST programado"
        )
        yield PlannerState.load

    # -- detail -----------------------------------------------------------------

    @rx.event(background=True)
    async def open_detail(self, event_id: str):
        async with self:
            self.detail_open = True
            self.detail_loading = True
            self.detail_error = ""
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

    @rx.event
    def set_detail_open(self, value: bool) -> None:
        self.detail_open = value

    @rx.event
    def reschedule_from_detail(self) -> None:
        self._reset_form()
        self.form_mode = MODE_RESCHEDULE
        self.form_event_id = self.detail.event_id
        self.form_post_id = self.detail.post_id
        self.form_post_title = self.detail.title
        self.form_date = self.detail.local_date
        self.form_time = self.detail.local_time
        self.form_connection_id = self.detail.connection_id
        self.form_tag_ids = list(self.detail.tag_ids)
        self.detail_open = False
        self.form_open = True

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

    # -- cancel -----------------------------------------------------------------

    def _ask_cancel(self, event_id: str) -> None:
        self.cancel_event_id = event_id
        self.cancel_open = True

    @rx.event
    def ask_cancel(self, event_id: str) -> None:
        self._ask_cancel(event_id)

    @rx.event
    def ask_cancel_from_detail(self) -> None:
        self._ask_cancel(self.detail.event_id)

    @rx.event
    def set_cancel_open(self, value: bool) -> None:
        self.cancel_open = value

    @rx.event(background=True)
    async def confirm_cancel(self):
        async with self:
            event_id = self.cancel_event_id
            self.cancel_open = False
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
            self.cancel_event_id = ""
        yield rx.toast.success("Publicación cancelada")
        yield PlannerState.load
