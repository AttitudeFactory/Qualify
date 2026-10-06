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
    ASSIGN_STEPS,
    AUTO_PUBLISH_UNAVAILABLE,
    CALENDAR_DEFAULT_TZ,
    OPENING_HOUR,
    REPEAT_BY_COUNT,
    REPEAT_BY_UNTIL,
    STEP_ACCOUNTS,
    STEP_LAST,
    STEP_POST,
    STEP_WHEN,
    TAG_SUGGESTIONS,
    VIEW_CALENDAR,
    VIEW_LIST,
    ConnectionChoiceVM,
    DayColumnVM,
    EventDetailVM,
    HourRowVM,
    OutputChipVM,
    PostOptionVM,
    PreviewFrameVM,
    SeriesPreviewVM,
    TagSuggestionVM,
    TagVM,
    TzOptionVM,
    assign_steps_done,
    media_label,
    preview_frames,
    series_preview,
    timezone_options,
    tz_option,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay una sesión activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudo cargar el Planificador. Inténtalo de nuevo."
_FORM_INCOMPLETE = "Completa el POST, la fecha, la hora y al menos una cuenta."
_OUTPUT_REQUIRED = "Elige qué salida programar (Reel, feed o historia)."
_POST_REQUIRED = "Elige un POST."
_ACCOUNT_REQUIRED = "Elige al menos una cuenta compatible."
_DATE_REQUIRED = "Elige la fecha y la hora."
_DATE_PAST = "Esa fecha ya pasó. Elige una de hoy en adelante."
_TIME_PAST = "Esa hora ya pasó. Elige una posterior."

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
    now_hhmm: str = ""  # the view zone's wall-clock time when the week was loaded
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
    # MP-11: the template output being planned ("reel" / "feed" / "story"); "" for a
    # POST planned whole. Preselected to the first output without a live event.
    form_output_port: str = ""
    # QUA-118: the assign drawer walks four steps (`ASSIGN_STEPS`); `form_step` is the
    # current one and `form_reached` the furthest one visited (the preview counts as
    # done only once seen). Accounts are a set (AC 5: one event per account); the
    # recurrence controls feed `series_preview` (A2/A4: weekly, by count or by date).
    form_step: int = 0
    form_reached: int = 0
    form_connection_ids: list[str] = []
    form_repeat: bool = False
    form_repeat_mode: str = REPEAT_BY_COUNT
    form_repeat_count: str = "4"
    form_repeat_until: str = ""

    # -- detail / cancel ------------------------------------------------------
    detail_open: bool = False
    detail_loading: bool = False
    detail: EventDetailVM = EventDetailVM()
    detail_error: str = ""
    cancel_open: bool = False
    cancel_event_id: str = ""
    # -- delete a tag (confirmation) ------------------------------------------
    remove_rejected_open: bool = False  # confirm "Quitar del calendario" (rejected POST)
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

    def _form_post(self) -> PostOptionVM | None:
        for post in self.schedulable:
            if post.post_id == self.form_post_id:
                return post
        return None

    @rx.var
    def form_outputs(self) -> list[OutputChipVM]:
        """The chosen POST's template outputs — the «Salida» control's options (MP-11).
        Empty for a POST planned whole, so the control is not shown."""
        post = self._form_post()
        return list(post.outputs) if post is not None else []

    @rx.var
    def form_has_outputs(self) -> bool:
        return bool(self.form_outputs)

    @rx.var
    def form_output_label(self) -> str:
        """ "Reel 9:16" for the output being (re)planned, "" for a whole POST."""
        for chip in self.form_outputs:
            if chip.port == self.form_output_port:
                return chip.label
        if self.form_mode == MODE_RESCHEDULE:
            return self.detail.output_label
        return ""

    @rx.var
    def form_post_note(self) -> str:
        """Why the POST being scheduled will not publish yet — the same `readiness_note` the
        card and the detail dialog show (`planner_vm.readiness`), "" when it is ready."""
        if self.form_mode == MODE_RESCHEDULE:
            return self.detail.publish_note
        post = self._form_post()
        if post is None:
            return ""
        # MP-11: with an output chosen, its own reason — the whole POST's readiness says
        # "at least one output is publishable", which is not this output's answer.
        for chip in post.outputs:
            if chip.port == self.form_output_port:
                return chip.note
        return post.readiness_note

    # -- QUA-118: the drawer's steps --------------------------------------------

    @rx.var
    def form_post_blocked(self) -> str:
        """D1: why the chosen POST cannot enter the calendar ("" when it can) — the
        exact evaluator reason, shown as an error in the Post step and blocking it. A
        reschedule never re-blocks on the POST here (the service re-checks it)."""
        if self.form_mode == MODE_RESCHEDULE:
            return ""
        post = self._form_post()
        if post is None:
            return ""
        if self.form_has_outputs:
            if not self.form_output_port:
                return _OUTPUT_REQUIRED
            for chip in post.outputs:
                if chip.port == self.form_output_port:
                    return chip.note
            return ""
        return "" if post.schedulable else (post.readiness_note or "El POST no está aprobado.")

    @rx.var
    def form_post_ok(self) -> bool:
        if self.form_mode == MODE_RESCHEDULE:
            return True
        return bool(self.form_post_id) and self.form_post_blocked == ""

    @rx.var
    def form_series(self) -> SeriesPreviewVM:
        """The recurrence as the «Fecha y hora» step reads it (`series_preview`): the
        occurrences, or why the series cannot be built. A reschedule moves one event,
        so it never repeats."""
        return series_preview(
            self.form_date,
            repeat=self.form_repeat and self.form_mode == MODE_ASSIGN,
            mode=self.form_repeat_mode,
            count_text=self.form_repeat_count,
            until_iso=self.form_repeat_until,
        )

    @rx.var
    def form_date_error(self) -> str:
        """The date step's own refusals: no date, or a day already gone (the time of
        day is the service's call — it knows the zone)."""
        if not self.form_date or not self.form_time:
            return _DATE_REQUIRED
        if self.today_iso and self.form_date < self.today_iso:
            return _DATE_PAST
        if self.today_iso and self.now_hhmm and self.form_date == self.today_iso:
            if self.form_time <= self.now_hhmm:
                return _TIME_PAST
        return ""

    @rx.var
    def form_when_ok(self) -> bool:
        if self.form_date_error:
            return False
        return self.form_series.error == "" and self.form_series.count >= 1

    @rx.var
    def form_selected_accounts(self) -> list[ConnectionChoiceVM]:
        chosen = set(self.form_connection_ids)
        return [c for c in self.connections if c.id in chosen and c.compatible]

    @rx.var
    def form_accounts_ok(self) -> bool:
        return bool(self.form_selected_accounts)

    @rx.var
    def form_steps_done(self) -> list[bool]:
        return assign_steps_done(
            post_ok=self.form_post_ok,
            when_ok=self.form_when_ok,
            accounts_ok=self.form_accounts_ok,
            reached=self.form_reached,
        )

    @rx.var
    def form_step_error(self) -> str:
        """Why the current step cannot be left yet ("" when it can): the one message the
        «Siguiente» button is disabled over, next to the thing to fix."""
        if self.form_step == STEP_POST:
            if not self.form_post_id and self.form_mode == MODE_ASSIGN:
                return _POST_REQUIRED
            return self.form_post_blocked
        if self.form_step == STEP_WHEN:
            return self.form_date_error or self.form_series.error
        if self.form_step == STEP_ACCOUNTS:
            return "" if self.form_accounts_ok else _ACCOUNT_REQUIRED
        return ""

    @rx.var
    def form_step_hint(self) -> str:
        """The step error as the footer prints it — only when the step body does not
        already show it in a callout (a blocked POST, a bad series)."""
        error = self.form_step_error
        if not error or error == self.form_post_blocked or error == self.form_series.error:
            return ""
        return error

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
    def form_step_badge(self) -> str:
        """ "Paso 2 de 4" — the header's pill."""
        return f"Paso {self.form_step + 1} de {len(ASSIGN_STEPS)}"

    @rx.var
    def form_media_label(self) -> str:
        """ "Video · Reel 9:16" — the chosen POST's media for the summary card."""
        return media_label(self._form_post(), self.form_output_port)

    @rx.var
    def form_event_count(self) -> int:
        """How many `calendar_events` «Programar» will create: occurrences × accounts."""
        if self.form_mode == MODE_RESCHEDULE:
            return 1
        return max(self.form_series.count, 1) * len(self.form_selected_accounts)

    @rx.var
    def form_frames(self) -> list[PreviewFrameVM]:
        """One frame per chosen account (AC 7): only what will be published there."""
        return preview_frames(
            post=self._form_post(),
            output_port=self.form_output_port,
            accounts=self.form_selected_accounts,
        )

    @rx.var
    def form_when_label(self) -> str:
        """ "lun 12 oct · 10:00 a. m." for the preview and the confirm step."""
        if not self.form_date:
            return ""
        try:
            day = date.fromisoformat(self.form_date)
        except ValueError:
            return ""
        hour, minute = split_time(self.form_time)
        h12 = hour % 12 or 12
        suffix = "a. m." if hour < 12 else "p. m."
        weekdays = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
        months = (
            "ene",
            "feb",
            "mar",
            "abr",
            "may",
            "jun",
            "jul",
            "ago",
            "sep",
            "oct",
            "nov",
            "dic",
        )
        return (
            f"{weekdays[day.weekday()]} {day.day} {months[day.month - 1]} · "
            f"{h12}:{minute:02d} {suffix}"
        )

    @rx.var
    def form_post_title_or_chosen(self) -> str:
        """The POST's title for the summary: the event's on a reschedule, the chosen
        option's on an assign."""
        if self.form_mode == MODE_RESCHEDULE:
            return self.form_post_title
        post = self._form_post()
        return post.title if post is not None else ""

    @rx.var
    def form_submit_label(self) -> str:
        if self.form_mode == MODE_RESCHEDULE:
            return "Guardar cambios"
        n = self.form_event_count
        return "Programar" if n <= 1 else f"Programar {n} publicaciones"

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
            self.now_hhmm = data.now_hhmm
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
        self.form_output_port = ""
        self.form_step = STEP_POST
        self.form_reached = STEP_POST
        # The first compatible account is preselected: one account is the common case.
        first = next((c.id for c in self.connections if c.compatible), "")
        self.form_connection_ids = [first] if first else []
        self.form_repeat = False
        self.form_repeat_mode = REPEAT_BY_COUNT
        self.form_repeat_count = "4"
        self.form_repeat_until = ""

    def _preselect_output(self) -> None:
        """MP-11: the first output of the chosen POST that has no live event (the next
        one to plan); "" when the POST has no outputs or all are planned."""
        post = self._form_post()
        self.form_output_port = post.next_port if post is not None else ""

    def _open_assign(self, post_id: str = "", day_iso: str = "") -> None:
        """Open the assign dialog, optionally with a POST (from the Sin programar panel)
        and/or a day (from a day column's "+") already chosen."""
        self._reset_form()
        self.form_mode = MODE_ASSIGN
        self.form_post_id = post_id
        self._preselect_output()
        default_day = self.today_iso if self._week_contains_today() else self.monday_iso
        self.form_date = day_iso or default_day
        if self.form_date == self.today_iso and self.now_hhmm:
            # Today: the next full hour, never a time already gone (09:00 at 21:00 was
            # a refusal waiting at the last step).
            hour = min(split_time(self.now_hhmm)[0] + 1, 23)
            self._set_time(hour, 0)
        self.form_open = True
        # A POST already chosen (the card's «Asignar») skips straight to the date.
        if post_id and self.form_post_ok:
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
        self._preselect_output()

    @rx.event
    def set_form_output_port(self, value: str | list[str]) -> None:
        chosen = value[0] if isinstance(value, list) and value else value
        self.form_output_port = chosen if isinstance(chosen, str) else ""

    @rx.event
    def set_form_date(self, value: str) -> None:
        self.form_date = value

    @rx.event
    def set_form_time(self, value: str) -> None:
        self.form_time = value

    @rx.event
    def set_form_connection_id(self, value: str) -> None:
        self.form_connection_id = value

    @rx.event
    def toggle_form_connection(self, connection_id: str) -> None:
        """«Cuentas»: a checkbox per account. An incompatible account cannot be chosen
        (its row is disabled; the service would refuse it anyway). A reschedule moves one
        event, so there the choice replaces instead of accumulating."""
        if not any(c.id == connection_id and c.compatible for c in self.connections):
            return
        if self.form_mode == MODE_RESCHEDULE:
            self.form_connection_ids = [connection_id]
            self.form_connection_id = connection_id
            return
        self.form_connection_ids = (
            [c for c in self.form_connection_ids if c != connection_id]
            if connection_id in self.form_connection_ids
            else [*self.form_connection_ids, connection_id]
        )

    @rx.event
    def set_form_repeat(self, value: bool) -> None:
        self.form_repeat = bool(value)

    @rx.event
    def set_form_repeat_mode(self, value: str | list[str]) -> None:
        chosen = value[0] if isinstance(value, list) and value else value
        self.form_repeat_mode = REPEAT_BY_UNTIL if chosen == REPEAT_BY_UNTIL else REPEAT_BY_COUNT

    @rx.event
    def set_form_repeat_count(self, value: str) -> None:
        self.form_repeat_count = value

    @rx.event
    def set_form_repeat_until(self, value: str) -> None:
        self.form_repeat_until = value

    def _go_to(self, step: int) -> None:
        self.form_step = max(STEP_POST, min(step, STEP_LAST))
        self.form_reached = max(self.form_reached, self.form_step)
        self.form_error = ""

    @rx.event
    def next_step(self) -> None:
        """«Siguiente»: only past a valid step — the step's own message says otherwise."""
        if self.form_can_advance:
            self._go_to(self.form_step + 1)

    @rx.event
    def prev_step(self) -> None:
        self._go_to(self.form_step - 1)

    @rx.event
    def go_to_step(self, step: int) -> None:
        """The stepper: back to any step already reached (to fix something); never
        forward past the steps not completed yet."""
        if step <= self.form_step or (
            step <= self.form_reached and all(self.form_steps_done[:step])
        ):
            self._go_to(step)

    @rx.event(background=True)
    async def submit_form(self):
        """«Programar» / «Guardar cambios» from the Confirmar step. Everything the steps
        validated is re-validated by the service; a refusal comes back as the error of
        this step and nothing is created (the plan is atomic, QUA-118 A4)."""
        async with self:
            if self.saving:
                return
            mode = self.form_mode
            event_id, post_id = self.form_event_id, self.form_post_id
            day, at = self.form_date, self.form_time
            accounts = tuple(c.id for c in self.form_selected_accounts)
            view_tz, tag_ids = self.view_tz, tuple(self.form_tag_ids)
            output_port = self.form_output_port
            series = self.form_series
            if (mode == MODE_ASSIGN and not post_id) or not day or not at or not accounts:
                self.form_error = _FORM_INCOMPLETE
                return
            if mode == MODE_ASSIGN and self.form_post_blocked:
                self.form_error = self.form_post_blocked
                return
            if series.error:
                self.form_error = series.error
                return
            repeat_until = (
                self.form_repeat_until
                if series.enabled and self.form_repeat_mode == REPEAT_BY_UNTIL
                else ""
            )
            repeat_count = (
                series.count if series.enabled and self.form_repeat_mode == REPEAT_BY_COUNT else 0
            )
            self.saving = True
            self.form_error = ""
        tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.saving = False
                self.form_error = _NO_TENANT
            return
        created = 1
        try:
            if mode == MODE_RESCHEDULE:
                await asyncio.to_thread(
                    reschedule_event, tenant_id, event_id, day, at, accounts[0], view_tz, tag_ids
                )
            else:
                created = await asyncio.to_thread(
                    schedule_post,
                    tenant_id,
                    post_id,
                    day,
                    at,
                    accounts[0],
                    view_tz,
                    tag_ids,
                    output_port,
                    accounts,
                    repeat_until,
                    repeat_count,
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
            # Jump to the week the (first) event landed in, so the operator sees it appear.
            self.monday_iso = day
        if mode == MODE_RESCHEDULE:
            message = "Publicación reprogramada"
        elif created == 1:
            message = "POST programado"
        else:
            message = f"{created} publicaciones programadas"
        yield rx.toast.success(message)
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
        self.form_connection_ids = [self.detail.connection_id] if self.detail.connection_id else []
        self.form_tag_ids = list(self.detail.tag_ids)
        self.form_output_port = self.detail.output_port  # shown, never changed by a move
        self.detail_open = False
        self.form_open = True
        self._go_to(STEP_WHEN)  # the POST is fixed: a move starts at the date

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
        yield rx.toast.success("Publicación cancelada: salió del calendario")
        yield PlannerState.load
