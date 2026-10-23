"""View-models for the Planificador (QUA-108) — pure, no Reflex, no database.

Everything here is serialized to the browser, so it is a whitelist of display fields: ids
as strings, labels pre-formatted server-side, tones by name. The week-building logic
(hour rows, today, list grouping, labels) lives here as plain functions so it is
unit-testable without the Reflex runtime.

## Two views of the same week (concept reviewed against Buffer, Later and TRYHOLO.ai —
## concept only, no code or design copied)

- **Calendario**: seven day columns crossed with a real time axis, one row per hour of
  the day (24, 12-hour labels "9 a. m." / "3 p. m."), opened scrolled to the start of
  the working day. A compact chip sits in the row of its hour; several chips in the
  same hour stack in that cell, in time order. No absolute positioning by minute:
  Reflex has no primitive for it and a business plans a handful of posts a week, so
  hour granularity is what the operator reads anyway.
- **Lista**: the same events grouped by day ("Hoy, 25 de septiembre"), time on the left,
  wide cards — the view for reading the plan rather than seeing its shape.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from qualify_api.planner.publishable import destination_options
from qualify_api.planner.recurrence import (
    SERIES_CAP,
    InvalidRecurrence,
    weekly_days,
    weekly_days_on,
)

from .creative_vm import OUTPUT_WORDS, PORT_LABELS

VIEW_CALENDAR = "calendar"
VIEW_LIST = "list"

# QUA-118 v2 (founder review, 2026-10-06): the assign flow plans SEVERAL POSTs at once —
# a story at 2 a. m., a carousel at 10 a. m. and a reel at 11 a. m. are one plan. Three
# steps, each named by an icon and a word, never a number: pick the content from a grid,
# set each piece's date, time, accounts and tags, then confirm over a phone-shaped
# preview of every piece (edit or drop any of them there) with the plan's goals. The
# reschedule flow walks the same steps with one piece, already chosen.
ASSIGN_STEPS: tuple[str, ...] = ("Contenido", "Programación", "Confirmar")
ASSIGN_STEP_ICONS: tuple[str, ...] = ("layout-grid", "calendar-clock", "circle-check")
STEP_POST, STEP_WHEN, STEP_PREVIEW = range(3)
STEP_LAST = STEP_PREVIEW

REPEAT_BY_COUNT = "count"
REPEAT_BY_UNTIL = "until"

# The recurrence refusals, in the operator's words (`recurrence.InvalidRecurrence.code`).
SERIES_MESSAGES: dict[str, str] = {
    "end_required": (
        "Indica cuándo termina la serie: una fecha de fin o un número de ocurrencias "
        "(solo una de las dos)."
    ),
    "count_too_small": "La serie necesita al menos una ocurrencia.",
    "too_many": f"Una serie admite como máximo {SERIES_CAP} ocurrencias.",
    "until_before_first": "La fecha de fin de la serie es anterior a la primera publicación.",
    "days_required": "Elige al menos un día de la semana.",
}
# The weekday picker of a weekly series, Monday first (`date.weekday()` order).
WEEKDAY_INITIALS: tuple[str, ...] = ("L", "M", "X", "J", "V", "S", "D")
WEEKDAY_NAMES: tuple[str, ...] = (
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
)
SERIES_UNKNOWN_MESSAGE = "La serie no es válida. Revisa cómo termina."

# Hour rows of the calendar view: one per hour of the day, 00 → 23. The calendar opens
# scrolled to OPENING_HOUR so the working day is what the operator sees first.
HOUR_ROW_KEYS: tuple[int, ...] = tuple(range(24))
OPENING_HOUR = 7

_WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
_WEEKDAYS_LONG = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_MONTHS_LONG = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# MP-11: what a template output's chip says about its planning state, by event status.
OUTPUT_UNSCHEDULED = "sin programar"
OUTPUT_NOT_PUBLISHABLE = "no publicable"
_OUTPUT_STATE: dict[str, tuple[str, str]] = {
    "publishing": ("publicando", "info"),
    "published": ("publicada", "ok"),
}


def output_label(port: str | None) -> str:
    """The word a card or chip prints for a template output ("Reel" / "Feed" /
    "Historia"); "" for a whole-POST event."""
    if not port:
        return ""
    return OUTPUT_WORDS.get(port, port.title())


def output_long_label(port: str) -> str:
    """The output's full name for the «Salida» control ("Reel 9:16")."""
    return PORT_LABELS.get(port, port.title())


# (long label, short label for the compact calendar card, tone). This is the POST's
# approval — a different axis from the event's state below, so it never reuses one of
# the five state words ("pending" reads «En revisión», not «Pendiente»).
_APPROVAL_LABEL: dict[str, tuple[str, str, str]] = {
    "approved": ("Aprobado", "Aprobado", "ok"),
    "pending": ("En revisión", "En revisión", "warn"),
    "rejected": ("Rechazado", "Rechazado", "error"),
    "not_ready": ("En producción", "En producción", "neutral"),
}
_MISSING_POST = ("POST no disponible", "No disponible", "error")

# QUA-118 A1 — the five visible states of a calendar event, and the only five words the
# UI ever prints for one: Programado · Pendiente · Publicado · Vencido · Fallido. They are
# derived from what already exists (`EventStatus`, `rules.is_expired_scheduled`, the
# POST's approval); nothing new is persisted. Two persisted statuses have no word of
# their own on purpose: `publishing` is a transient of seconds and reads «Programado»
# while the attempt runs; `cancelled` never reaches a screen — «Cancelar publicación»
# removes the event from the calendar (`PlannerService.cancel_and_delete`).
_STATUS_LABEL: dict[str, tuple[str, str]] = {
    "scheduled": ("Programado", "info"),
    "publishing": ("Programado", "info"),
    "published": ("Publicado", "ok"),
    "failed": ("Fallido", "error"),
}
# A scheduled event whose POST is no longer approved (edited after approval — the only
# way there since D1): it must go through review again before the worker will take it.
PENDING_LABEL = ("Pendiente", "warn")
# QUA-115: a scheduled event past its 24 h execution window, approved or not. The worker
# will not touch it; only "Reprogramar" brings it back. Takes precedence over PENDING.
EXPIRED_LABEL = ("Vencido", "warn")
EXPIRED_NOTE = "Pasaron más de 24 h de la hora programada. Reprográmalo para volver a publicarlo."

# The POST category vocabulary is QUA-109's. These labels cover what the temporary
# adapter returns plus the categories QUA-109 is expected to introduce.
_CATEGORY_LABEL: dict[str, str] = {
    "feed": "Publicación",
    "gallery": "Galería",
    "galeria": "Galería",  # `PostCategory.GALERIA` (QUA-109)
    "carousel": "Galería",
    "story": "Story",
    "reel": "Reel",
    "tiktok_video": "Video TikTok",
}


def hour_row_for(hour: int) -> int:
    """The calendar row an event at local `hour` sits in."""
    return hour


def _meridiem(hour: int) -> tuple[int, str]:
    return (hour % 12 or 12), ("a. m." if hour < 12 else "p. m.")


def hour_row_label(hour: int) -> str:
    """12-hour label for a calendar row: "12 a. m.", "9 a. m.", "12 p. m.", "3 p. m."."""
    h, suffix = _meridiem(hour)
    return f"{h} {suffix}"


def time_label_12h(moment: datetime) -> str:
    """12-hour clock time for a card: "9:20 a. m.", "3:50 p. m."."""
    h, suffix = _meridiem(moment.hour)
    return f"{h}:{moment.minute:02d} {suffix}"


def approval_label(approval: str | None) -> tuple[str, str]:
    long_label, _short, tone = _approval(approval)
    return long_label, tone


def approval_short(approval: str | None) -> str:
    return _approval(approval)[1]


def _approval(approval: str | None) -> tuple[str, str, str]:
    if approval is None:
        return _MISSING_POST
    return _APPROVAL_LABEL.get(approval, ("Aprobación desconocida", "Desconocida", "neutral"))


# "Approved" is a human decision; "ready" is `publishable.evaluate` (via
# `PostSummary.is_publishable`) — the same verdict QUA-111's executor applies. An approved
# POST shows which of the two it is, so "Aprobado + Programado" never promises a publish
# the worker will refuse.
READY_TO_PUBLISH = ("Listo para publicar", "Listo", "ok")
APPROVED_NOT_READY = ("Aprobado, pero no listo para publicar", "No listo", "warn")


@dataclass(frozen=True)
class Readiness:
    label: str
    short: str
    tone: str
    note: str  # the evaluator's reason when the POST cannot be published; "" otherwise


def readiness(approval: str | None, *, is_publishable: bool, reason: str) -> Readiness:
    """What the calendar says about a POST's approval AND publishability. Only reads the
    verdict the reader already computed — it decides nothing itself."""
    if approval == "approved":
        label, short, tone = READY_TO_PUBLISH if is_publishable else APPROVED_NOT_READY
    else:
        label, short, tone = _approval(approval)
    note = "" if is_publishable or approval is None else reason
    return Readiness(label, short, tone, note)


@dataclass(frozen=True)
class EventActions:
    """What the event dialog (and the card menu) may offer — one rule for both.

    The POST's own state decides with the event's: rejecting is the creative FSM's
    `generated → rejected` edge, so it is offered only for a POST in review; a REJECTED
    POST has nothing to move or cancel, only "Quitar del calendario" (its unpublished
    events are removed; the service re-checks the rejection). Every action is enforced
    again server-side — this only decides what is shown."""

    can_modify: bool  # Reprogramar / Cancelar publicación
    can_reject_post: bool  # "Rechazar POST"
    can_remove_rejected: bool  # "Quitar del calendario" for a rejected POST


def event_actions(*, status: str, approval: str | None, lifecycle: str | None) -> EventActions:
    rejected = approval == "rejected"
    return EventActions(
        can_modify=status == "scheduled" and not rejected,
        can_reject_post=status == "scheduled" and lifecycle == "generated",
        can_remove_rejected=rejected and status in ("scheduled", "cancelled"),
    )


def status_label(status: str, *, pending: bool = False, expired: bool = False) -> tuple[str, str]:
    """One of the five visible states (QUA-118 A1). `pending` = a scheduled event whose
    POST is not approved; `expired` = past the execution window (QUA-115) — expiry wins,
    whatever the POST says, because rescheduling is the only way forward."""
    if expired:
        return EXPIRED_LABEL
    if pending:
        return PENDING_LABEL
    return _STATUS_LABEL.get(status, (status, "neutral"))


def is_pending(status: str, approval: str | None) -> bool:
    """The «Pendiente» rule, shared by the card and the detail dialog: a `scheduled` event
    of a POST that exists and is not approved."""
    return status == "scheduled" and approval is not None and approval != "approved"


def category_label(category: str | None) -> str:
    if not category:
        return "Sin categoría"
    return _CATEGORY_LABEL.get(category, category.replace("_", " ").capitalize())


def content_type_label(content_type: str | None) -> str:
    return content_type.replace("_", " ").capitalize() if content_type else ""


def week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"{monday.day} – {sunday.day} {_MONTHS[sunday.month - 1]} {sunday.year}"
    if monday.year == sunday.year:
        return (
            f"{monday.day} {_MONTHS[monday.month - 1]} – "
            f"{sunday.day} {_MONTHS[sunday.month - 1]} {sunday.year}"
        )
    return (
        f"{monday.day} {_MONTHS[monday.month - 1]} {monday.year} – "
        f"{sunday.day} {_MONTHS[sunday.month - 1]} {sunday.year}"
    )


def month_label(monday: date) -> str:
    """The toolbar's heading for a week: "Septiembre de 2026", or "Septiembre – octubre
    de 2026" / "Diciembre de 2026 – enero de 2027" when the week spans two months."""
    sunday = monday + timedelta(days=6)
    first = _MONTHS_LONG[monday.month - 1]
    last = _MONTHS_LONG[sunday.month - 1]
    if monday.month == sunday.month:
        return f"{first.capitalize()} de {sunday.year}"
    if monday.year == sunday.year:
        return f"{first.capitalize()} – {last} de {sunday.year}"
    return f"{first.capitalize()} de {monday.year} – {last} de {sunday.year}"


def date_label(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def day_title(day: date, today: date) -> str:
    """The list view's day heading: "Hoy, 25 de septiembre", "Mañana, …", "Sábado 27 de …"."""
    rest = f"{day.day} de {_MONTHS_LONG[day.month - 1]}"
    if day == today:
        return f"Hoy, {rest}"
    if day == today + timedelta(days=1):
        return f"Mañana, {rest}"
    if day == today - timedelta(days=1):
        return f"Ayer, {rest}"
    return f"{_WEEKDAYS_LONG[day.weekday()]} {rest}"


# ---------------------------------------------------------------------------
# An empty week (m-24842982, audit m4 H2): on a phone the «Por programar» panel is not
# on screen, so the empty week itself says how many approved publications are waiting
# and offers the one button that plans them all.

EMPTY_WEEK_TITLE = "Tu semana está libre"
NO_APPROVED_BODY = "Todavía no tienes publicaciones aprobadas."
CREATE_ACTION = "Crear una publicación"


@dataclass(frozen=True)
class WaitingCopy:
    """What the empty week says for `count` approved publications without a date."""

    body: str
    action: str


def waiting_copy(count: int) -> WaitingCopy:
    """«Tienes 3 publicaciones aprobadas esperando día y hora.» + «Programar mis 3
    publicaciones»; one reads in the singular; none sends to «Crear una publicación»."""
    if count <= 0:
        return WaitingCopy(body=NO_APPROVED_BODY, action=CREATE_ACTION)
    if count == 1:
        return WaitingCopy(
            body="Tienes 1 publicación aprobada esperando día y hora.",
            action="Programar mi publicación",
        )
    return WaitingCopy(
        body=f"Tienes {count} publicaciones aprobadas esperando día y hora.",
        action=f"Programar mis {count} publicaciones",
    )


# ---------------------------------------------------------------------------
# Timezones — the Planificador's view zone picker


# Palette keys a planning tag may use (migration 0025). They are Radix scale names.
TAG_COLORS: tuple[str, ...] = ("teal", "blue", "violet", "pink", "amber", "green", "orange", "gray")

_TZ_REGIONS = (
    "Africa/",
    "America/",
    "Antarctica/",
    "Asia/",
    "Atlantic/",
    "Australia/",
    "Europe/",
    "Indian/",
    "Pacific/",
)
# Spanish names for the zones this product's customers actually use; everything else
# shows the IANA city with underscores as spaces.
_TZ_CITY_ES: dict[str, str] = {
    "America/Bogota": "Bogotá",
    "America/Caracas": "Caracas",
    "America/Mexico_City": "Ciudad de México",
    "America/Lima": "Lima",
    "America/Guayaquil": "Guayaquil",
    "America/Panama": "Panamá",
    "America/Santiago": "Santiago de Chile",
    "America/Argentina/Buenos_Aires": "Buenos Aires",
    "America/Sao_Paulo": "São Paulo",
    "America/Santo_Domingo": "Santo Domingo",
    "America/Havana": "La Habana",
    "America/New_York": "Nueva York",
    "America/Los_Angeles": "Los Ángeles",
    "Europe/Madrid": "Madrid",
    "Europe/London": "Londres",
    "UTC": "UTC",
}


# Spanish country names for the markets this product serves; any other country keeps the
# English name from the tz database's own iso3166.tab.
_COUNTRY_ES: dict[str, str] = {
    "AR": "Argentina",
    "BO": "Bolivia",
    "BR": "Brasil",
    "CA": "Canadá",
    "CL": "Chile",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "DE": "Alemania",
    "DO": "República Dominicana",
    "EC": "Ecuador",
    "ES": "España",
    "FR": "Francia",
    "GB": "Reino Unido",
    "GT": "Guatemala",
    "HN": "Honduras",
    "IT": "Italia",
    "MX": "México",
    "NI": "Nicaragua",
    "PA": "Panamá",
    "PE": "Perú",
    "PR": "Puerto Rico",
    "PT": "Portugal",
    "PY": "Paraguay",
    "SV": "El Salvador",
    "US": "Estados Unidos",
    "UY": "Uruguay",
    "VE": "Venezuela",
}


def _tz_table(name: str) -> str:
    """Read a table shipped with the tz database: the `tzdata` package (always present on
    Windows, where zoneinfo needs it), else the system database. "" if neither has it."""
    try:
        return resources.files("tzdata.zoneinfo").joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError):
        system = Path("/usr/share/zoneinfo") / name
        return system.read_text(encoding="utf-8") if system.exists() else ""


@lru_cache(maxsize=1)
def zone_countries() -> dict[str, str]:
    """IANA zone → country name (Spanish where we have it), from zone.tab + iso3166.tab."""
    names: dict[str, str] = {}
    for line in _tz_table("iso3166.tab").splitlines():
        if line and not line.startswith("#"):
            code, _, country = line.partition("\t")
            names[code] = _COUNTRY_ES.get(code, country.strip())
    zones: dict[str, str] = {}
    for line in _tz_table("zone.tab").splitlines():
        if line and not line.startswith("#"):
            parts = line.split("\t")
            if len(parts) >= 3:
                zones[parts[2].strip()] = names.get(parts[0], parts[0])
    return zones


# What the Planificador tells the operator about automatic publication (QUA-111).
AUTO_PUBLISH_ACTIVE = "active"  # the worker runs for this tenant and it has an account
AUTO_PUBLISH_NO_CONNECTION = "no_connection"  # worker fine; the tenant has no active account
AUTO_PUBLISH_UNAVAILABLE = "unavailable"  # the worker is not running (or excludes the tenant)


def auto_publish_state(*, worker_covers_tenant: bool, has_active_connection: bool) -> str:
    """The service's availability comes first: with no worker, connecting an account
    would not help, so that is not what the operator is told to do."""
    if not worker_covers_tenant:
        return AUTO_PUBLISH_UNAVAILABLE
    return AUTO_PUBLISH_ACTIVE if has_active_connection else AUTO_PUBLISH_NO_CONNECTION


# The zone every calendar opens in, whatever the tenant's own zone is: the operators
# plan from Caracas. The picker still overrides it per session.
CALENDAR_DEFAULT_TZ = "America/Caracas"


def tz_city(name: str) -> str:
    return _TZ_CITY_ES.get(name, name.rsplit("/", 1)[-1].replace("_", " "))


def tz_offset(name: str, at: datetime) -> int:
    """UTC offset of zone `name` at instant `at`, in minutes."""
    offset = at.astimezone(ZoneInfo(name)).utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def tz_offset_label(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+"
    hours, mins = divmod(abs(minutes), 60)
    return f"GMT{sign}{hours}:{mins:02d}"


@dataclass(frozen=True)
class TzOptionVM:
    value: str  # IANA name
    city: str
    country: str  # "" for UTC and a few oceanic zones
    offset_label: str  # "GMT-5:00"
    search: str  # lowercase haystack for the picker's filter


def tz_option(name: str, at: datetime) -> TzOptionVM:
    city = tz_city(name)
    country = zone_countries().get(name, "")
    label = tz_offset_label(tz_offset(name, at))
    return TzOptionVM(
        value=name,
        city=city,
        country=country,
        offset_label=label,
        search=f"{city} {country} {name} {label}".lower(),
    )


def timezone_options(at: datetime) -> list[TzOptionVM]:
    """Every regional IANA zone plus UTC, west to east, then by city."""
    names = [n for n in available_timezones() if n.startswith(_TZ_REGIONS)] + ["UTC"]
    return sorted(
        (tz_option(n, at) for n in set(names)),
        key=lambda o: (tz_offset(o.value, at), o.city),
    )


# ---------------------------------------------------------------------------
# VMs


@dataclass(frozen=True)
class TagSuggestionVM:
    """A recommended planning tag, offered until the tenant creates it."""

    name: str
    color: str
    hint: str


# The recommended set. Each colour means one thing so the calendar reads at a glance:
# amber = money on the table, violet = something new, pink = a date, blue = teaching,
# teal = the brand itself, green = the community, orange = practical notices.
TAG_SUGGESTIONS: tuple[TagSuggestionVM, ...] = (
    TagSuggestionVM("Promoción", "amber", "Ofertas, descuentos, combos"),
    TagSuggestionVM("Lanzamiento", "violet", "Producto o servicio nuevo"),
    TagSuggestionVM("Fecha especial", "pink", "Temporada, festivos, aniversarios"),
    TagSuggestionVM("Educativo", "blue", "Tips, tutoriales, preguntas frecuentes"),
    TagSuggestionVM("Marca", "teal", "Detrás de cámaras, equipo, historia"),
    TagSuggestionVM("Comunidad", "green", "Testimonios, clientes, colaboraciones"),
    TagSuggestionVM("Aviso", "orange", "Horarios, cierres, recordatorios"),
)


@dataclass(frozen=True)
class TagVM:
    """A planning tag (migration 0025) as the UI shows it."""

    id: str
    name: str
    color: str  # one of TAG_COLORS


@dataclass(frozen=True)
class ConnectionChoiceVM:
    """An account the operator can plan onto (active connections only). QUA-118 AC 6:
    `compatible` says whether the Planificador can publish to its channel; an
    incompatible one is listed disabled with `note` and never gets an event."""

    id: str
    label: str  # "@cuenta"
    platform: str
    compatible: bool = True
    note: str = ""


# QUA-118: the POST's five gallery states (`planner.gallery.GalleryState`) as the card
# prints them — a different entity from the five event states, deliberately other words.
# m-24842981 (CREAR-3): the owner's words. «needs_action» covers two different jobs for
# the owner — a publication waiting for their review («Por revisar», `CARD_STATES`) and
# an approved one that cannot go out yet («Le falta algo») — so the card splits it.
GALLERY_LABELS: dict[str, tuple[str, str]] = {
    "draft": ("Creándose", "neutral"),
    "needs_action": ("Le falta algo", "warn"),
    "schedulable": ("Lista para programar", "ok"),
    "used": ("Ya salió", "info"),
    "discarded": ("Descartada", "error"),
}
GALLERY_FILTER_ALL = "all"


@dataclass(frozen=True)
class CardStateVM:
    """What a «Por aprobar» card says about a publication (m-24842981): its state in
    words and tone, and its ONE main button — what the owner has to do with it."""

    key: str
    label: str
    tone: str
    action: str  # CARD_ACTION_*: what the main button does
    action_label: str


CARD_ACTION_REVIEW = "review"  # opens the publication's page
CARD_ACTION_SCHEDULE = "schedule"  # hands it to Tu semana to choose day and time
CARD_ACTION_VIEW = "view"  # opens the publication's page, nothing to do
CARD_ACTION_PLANNER = "planner"  # opens Tu semana on it: it is already on the calendar

#: The ready card's button keeps the name CREAR-1 (m-24842978) gave this same step —
#: it opens Tu semana, where «Programar» is the final, confirming verb (navigation map
#: §3); the ticket's table said «Programar», flagged to the founder in the PR.
SCHEDULE_ACTION_LABEL = "Elegir día y hora"

# In the order the filters show them: what needs the owner first, history last.
CARD_STATES: dict[str, CardStateVM] = {
    s.key: s
    for s in (
        CardStateVM("review", "Por revisar", "warn", CARD_ACTION_REVIEW, "Revisar"),
        CardStateVM("missing", "Le falta algo", "warn", CARD_ACTION_REVIEW, "Ver qué falta"),
        CardStateVM(
            "ready", "Lista para programar", "ok", CARD_ACTION_SCHEDULE, SCHEDULE_ACTION_LABEL
        ),
        CardStateVM("scheduled", "Programada", "info", CARD_ACTION_PLANNER, "Ver en Tu semana"),
        CardStateVM("used", "Ya salió", "info", CARD_ACTION_VIEW, "Ver"),
        CardStateVM("discarded", "Descartada", "error", CARD_ACTION_VIEW, "Ver"),
        CardStateVM("drafting", "Creándose", "neutral", CARD_ACTION_VIEW, "Ver"),
    )
}
_CARD_STATE_BY_GALLERY: dict[str, str] = {
    "draft": "drafting",
    "needs_action": "missing",
    "schedulable": "ready",
    "used": "used",
    "discarded": "discarded",
}
GALLERY_STATE_FILTERS: tuple[tuple[str, str], ...] = tuple(
    (key, state.label) for key, state in CARD_STATES.items()
)


def card_state(
    gallery_state: str, *, waiting_review: bool, times_published: int = 0
) -> CardStateVM | None:
    """The card's state (m-24842981): a publication generated and waiting for the
    owner is «Por revisar» whatever else it lacks — reviewing comes first. A «used» one
    that has never gone out is only on the calendar: «Programada», not «Ya salió»."""
    key = _CARD_STATE_BY_GALLERY.get(gallery_state)
    if key is None:
        return None
    if gallery_state == "needs_action" and waiting_review:
        key = "review"
    if gallery_state == "used" and times_published <= 0:
        key = "scheduled"
    return CARD_STATES[key]


#: The card states where «Ya probada» / «Por probar» helps a decision — whether to
#: repeat it. Everywhere else the line is noise on a phone (UX review, m-24842981).
HISTORY_CARD_STATES: frozenset[str] = frozenset({"ready", "used"})


def history_help(times_published: int) -> str:
    """The visible help under «Ya probada» / «Por probar» (m-24842981): how many times
    the publication already went out — on the card and on its own page, never only in
    a tooltip (N12). The threshold is the temperature's (`COLD_MIN_USES`)."""
    n = max(times_published, 0)
    if n >= COLD_MIN_USES:
        return f"Ya salió {n} veces en tus redes: se puede repetir sin problema."
    if n == 1:
        return "Salió 1 vez en tus redes: todavía no sabemos si funciona."
    return "Todavía no ha salido en tus redes."


def history_word(times_published: int) -> str:
    """«Ya probada» / «Por probar» (m-24842981, the words approved in wave 1)."""
    return "Ya probada" if max(times_published, 0) >= COLD_MIN_USES else "Por probar"


@dataclass(frozen=True)
class CategoryOptionVM:
    """One category the gallery can filter by: the raw value and its label."""

    value: str
    label: str


@dataclass(frozen=True)
class SeriesPreviewVM:
    """What the «Fecha y hora» step says about the recurrence being set up: how many
    occurrences, on which days, or why the series cannot be built. `count == 1` with
    `enabled=False` is a single publication."""

    enabled: bool = False
    count: int = 1
    dates: list[str] = field(default_factory=list)  # "lun 12 oct", in order
    summary: str = ""  # "Semanal · 4 veces · del 12 oct al 2 nov"
    error: str = ""  # "" when valid


@dataclass(frozen=True)
class OutputChipVM:
    """One template output of a POST as the Sin programar card and the «Salida»
    control show it (MP-11): «Feed · lun 12:00 @bianki», «Historia · sin programar»."""

    port: str  # "reel" / "feed" / "story"
    label: str  # "Reel 9:16" — the «Salida» control
    word: str  # "Reel" — the chip
    state_label: str  # "sin programar" / "lun 12:00 · @bianki" / "publicada" / "no publicable"
    tone: str  # neutral / ok / info / warn
    scheduled: bool  # has a live event (scheduled / publishing / published)
    note: str = ""  # why this output cannot be published yet ("" when it can)
    # QUA-118 v2: where this output may go out, what it is, and where it starts.
    destinations: list[DestinationChoiceVM] = field(default_factory=list)
    default_destination: str = ""
    kind: str = "image"
    kind_label: str = "Imagen"


@dataclass(frozen=True)
class EventCardVM:
    event_id: str
    post_id: str
    time_label: str  # "3:30 p. m.", local to the tenant zone
    title: str
    caption_excerpt: str
    thumbnail_url: str  # "" when there is none (or it expired)
    platform: str
    account_label: str
    category_label: str
    content_type_label: str
    approval_label: str
    approval_short: str
    approval_tone: str
    status_label: str
    status_tone: str
    overdue: bool
    can_modify: bool  # only a scheduled event can be moved or cancelled
    muted: bool  # cancelled: stays visible (history) but visually recedes
    detail_href: str
    date_label: str
    tags: list[TagVM] = field(default_factory=list)
    readiness_note: str = ""  # why the POST cannot be published yet ("" when it can)
    # The POST's R2-only video: the card shows its first frame instead of a placeholder.
    video_url: str = ""
    # MP-11: "Reel" / "Feed" / "Historia" when the event publishes one template output;
    # "" for a whole-POST event. The same POST shows up to three times in a week.
    output_label: str = ""
    # QUA-118 v2: where the event goes out — `post` / `reel` / `story` and its word, on
    # every card so it reads without opening the event ("" only when unknown).
    destination: str = ""
    destination_label: str = ""
    # QUA-118 v2: the POST's temperature (`temperature`) — Cold (proven, evergreen) or
    # Hot (new) — so the calendar shows it on the chip, with its frost or fire.
    temperature: str = ""
    temperature_label: str = ""
    temperature_hint: str = ""
    # QUA-143: the POST's campaign — name and palette key ("" for an independent POST).
    # Identity, never state: drawn with the tag palette, never on the status edge.
    campaign_name: str = ""
    campaign_color: str = ""


@dataclass(frozen=True)
class DayColumnVM:
    """One day: the calendar's column header and the list view's group."""

    iso: str
    weekday: str
    day_number: str
    title: str  # "Hoy, 25 de septiembre"
    is_today: bool
    is_past: bool
    count: int
    cards: list[EventCardVM] = field(default_factory=list)


@dataclass(frozen=True)
class HourCellVM:
    day_iso: str
    hour: int  # 0-23 — a click on an empty cell plans a publication at this hour
    is_today: bool
    is_past: bool
    cards: list[EventCardVM] = field(default_factory=list)
    # Up to `CELL_VISIBLE` chips show in the cell (the hour row grows to fit them); from
    # the next one on, a «+N más» pill opens, beside it, the ones that did not fit.
    visible: list[EventCardVM] = field(default_factory=list)
    more: list[EventCardVM] = field(default_factory=list)
    more_count: int = 0
    heading: str = ""  # «Mar 6 · 6 p. m.» — the subtitle of that list


@dataclass(frozen=True)
class HourRowVM:
    """One row of the calendar grid: a time label and seven cells (Monday → Sunday)."""

    key: int
    label: str
    cells: list[HourCellVM] = field(default_factory=list)


@dataclass(frozen=True)
class WeekGrid:
    days: list[DayColumnVM]
    rows: list[HourRowVM]


@dataclass(frozen=True)
class PostOptionVM:
    """A POST as the Sin programar panel and the assign dialog show it."""

    post_id: str
    title: str
    caption_excerpt: str
    thumbnail_url: str
    category_label: str
    approval_label: str
    approval_tone: str
    detail_href: str
    approval_short: str = ""
    readiness_note: str = ""  # why the POST cannot be published yet ("" when it can)
    # MP-11: the POST's template outputs with their planning state; empty for a POST
    # planned whole. `next_port` is the first output without a live event — what the
    # «Salida» control preselects.
    outputs: list[OutputChipVM] = field(default_factory=list)
    has_outputs: bool = False
    next_port: str = ""
    # QUA-118: the raw category (the preview frame's shape) and whether the POST may be
    # planned at all (D1: approved and publishable — `readiness_note` says why not).
    category: str = ""
    schedulable: bool = False
    video_url: str = ""
    # QUA-118 gallery: the derived state (`GALLERY_LABELS` key), its word and tone, and
    # the POST's history (D2) — «Usado ×N» and «En calendario» are badges, never the
    # state itself, so a `recurrente` POST reads Listo + Usado ×3.
    gallery_state: str = ""
    gallery_label: str = ""
    gallery_tone: str = "neutral"
    used_count: int = 0
    in_calendar: bool = False
    media_label: str = ""  # "Video · Reel 9:16"
    # QUA-118 v2: the format the grid tile shows («Reel», «Historia», «Carrusel», «Feed»,
    # «Multiformato», key in `KIND_ICONS`), and the POST's temperature (`temperature`).
    kind: str = "image"
    kind_label: str = "Imagen"
    # QUA-118 v2: where it may go out and what the selector starts on.
    destinations: list[DestinationChoiceVM] = field(default_factory=list)
    default_destination: str = ""
    # The POST waits for the human's decision (creative status `generated`): the gallery
    # card offers «Aprobar» / «Rechazar» right there, without opening the POST.
    can_review: bool = False
    temperature: str = "hot"
    temperature_label: str = "Hot"
    temperature_hint: str = ""
    # QUA-143: the POST's campaign ("" when independent) — the gallery card's badge and
    # the drawer's piece header — and how many publications the POST already has (the
    # drawer warns that a campaign change reaches all of them).
    campaign_name: str = ""
    campaign_color: str = ""
    campaign_id: str = ""
    event_count: int = 0
    # m-24828907: the card's retention badge — «Se elimina en N días» (warn) inside the
    # 15-day window, «Contenido eliminado» (neutral) once the files are gone; "" otherwise.
    retention_label: str = ""
    retention_tone: str = "neutral"
    # m-24842981 (CREAR-3): the «Por aprobar» card — its state in words (`CARD_STATES`),
    # its one main button, and the visible help under «Ya probada» / «Por probar».
    card_state: str = ""
    card_label: str = ""
    card_tone: str = "neutral"
    card_action: str = CARD_ACTION_VIEW
    card_action_label: str = "Ver"
    history_word: str = ""
    history_help: str = ""


def retention_badge(state: str, days_left: int | None) -> tuple[str, str]:
    """(label, tone) of a gallery card's retention badge (m-24828907)."""
    if state == "purged":
        return "Contenido eliminado", "neutral"
    if state != "warning" or days_left is None:
        return "", "neutral"
    if days_left <= 0:
        return "Se elimina hoy", "warn"
    if days_left == 1:
        return "Se elimina mañana", "warn"
    return f"Se elimina en {days_left} días", "warn"


@dataclass(frozen=True)
class EventDetailVM:
    event_id: str = ""
    post_id: str = ""
    title: str = ""
    caption_excerpt: str = ""
    thumbnail_url: str = ""
    category_label: str = ""
    content_type_label: str = ""
    approval_label: str = ""
    approval_tone: str = "neutral"
    status_label: str = ""
    status_tone: str = "neutral"
    when_label: str = ""  # "Lun 28 sep · 15:00 (America/Caracas)"
    platform: str = ""
    account_label: str = ""
    revision: int = 0
    can_modify: bool = False
    can_reject_post: bool = False  # the POST is in review → "Rechazar POST"
    can_remove_rejected: bool = False  # the POST is rejected → "Quitar del calendario"
    detail_href: str = ""
    publish_note: str = ""  # why this POST cannot be published yet, if so
    # QUA-115: past the execution window. The dialog then shows EXPIRED_NOTE instead of
    # the "publishes in the next minute it is ready" wording, which is false until the
    # event is rescheduled. `publish_note` keeps the POST's own reason for the form.
    expired: bool = False
    # Backend path (`r2_media`) of the POST's R2-only video, "" when there is none.
    video_url: str = ""
    # Pre-filled values for the reschedule form.
    local_date: str = ""
    local_time: str = ""
    connection_id: str = ""
    tags: list[TagVM] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)
    # MP-11: the output this event publishes ("" for the whole POST), and its word.
    output_port: str = ""
    output_label: str = ""
    # QUA-118 v2: where it goes out — fixed for the event, shown on the panel.
    destination: str = ""
    destination_label: str = ""
    kind: str = "image"  # what the content IS — the panel's chip
    kind_label: str = "Imagen"
    goals: list[str] = field(default_factory=list)  # the plan's goals, as labels (0042)
    goal_keys: list[str] = field(default_factory=list)  # the same goals, as keys
    # QUA-143: the POST's campaign ("" when independent), read through the POST.
    campaign_name: str = ""
    campaign_color: str = ""
    # N13 (m-24842959): «Aprobada por ti: sale el lunes 28 de septiembre a las 3:00 p. m.»
    # — derived from local_date/local_time, so every builder gets it without passing it.
    approved_line: str = field(init=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "approved_line", approved_line(self.local_date, self.local_time))


# ---------------------------------------------------------------------------
# Builders — take plain values (not ORM rows, not service types) so the page state and
# the tests can call them the same way.


@dataclass(frozen=True)
class CardInput:
    """What one planned event contributes to the week — decoupled from the service's
    dataclasses so this module does not import the backend."""

    event_id: str
    post_id: str
    scheduled_at: datetime  # aware
    status: str
    overdue: bool
    connection_id: str
    post_title: str | None  # None → the POST could not be read
    caption_excerpt: str = ""
    thumbnail_url: str | None = None
    category: str | None = None
    content_type: str | None = None
    approval: str | None = None
    detail_href: str = ""
    tags: tuple[TagVM, ...] = ()
    is_publishable: bool = False  # `PostSummary.is_publishable`
    unpublishable_reason: str = ""  # `PostSummary.unpublishable_reason`
    video_url: str = ""  # backend path of the POST's R2-only video (`r2_media`), or ""
    expired: bool = False  # QUA-115: `PlannedEvent.expired` — past the execution window
    output_port: str | None = None  # MP-11: `EventRecord.output_port`
    destination: str | None = None  # QUA-118 v2: `EventRecord.destination`
    times_published: int | None = None  # the POST's history (D2) — None: POST unreadable
    campaign_name: str = ""  # QUA-143: `PostSummary.campaign.name`, "" when independent
    campaign_color: str = ""


def event_readiness(
    *, status: str, approval: str | None, is_publishable: bool, reason: str
) -> Readiness:
    """A scheduled event shows readiness (it is what decides whether it will publish);
    one that already ran, or was cancelled, keeps the plain approval wording."""
    if status == "scheduled":
        return readiness(approval, is_publishable=is_publishable, reason=reason)
    long_label, short, tone = _approval(approval)
    return Readiness(long_label, short, tone, "")


def build_card(
    item: CardInput, *, zone: ZoneInfo, connections: Mapping[str, tuple[str, str]]
) -> EventCardVM:
    local = item.scheduled_at.astimezone(zone)
    platform, account = connections.get(item.connection_id, ("", "Cuenta desconocida"))
    approval = item.approval if item.post_title is not None else None
    ready = event_readiness(
        status=item.status,
        approval=approval,
        is_publishable=item.is_publishable,
        reason=item.unpublishable_reason,
    )
    pending = is_pending(item.status, approval)
    s_label, s_tone = status_label(item.status, pending=pending, expired=item.expired)
    return EventCardVM(
        event_id=item.event_id,
        post_id=item.post_id,
        time_label=time_label_12h(local),
        title=item.post_title if item.post_title is not None else "POST no disponible",
        caption_excerpt=item.caption_excerpt,
        thumbnail_url=item.thumbnail_url or "",
        platform=platform,
        account_label=account,
        category_label=category_label(item.category),
        content_type_label=content_type_label(item.content_type),
        approval_label=ready.label,
        approval_short=ready.short,
        approval_tone=ready.tone,
        status_label=s_label,
        status_tone=s_tone,
        # `overdue` is the card's "needs attention" flag (amber edge + warning icon): a
        # Pendiente or Vencido event will not publish as is.
        overdue=pending or item.expired,
        can_modify=event_actions(status=item.status, approval=approval, lifecycle=None).can_modify,
        muted=item.status == "cancelled",
        detail_href=item.detail_href,
        date_label=date_label(local.date()),
        tags=list(item.tags),
        # The POST's own reason stays here (list view, reschedule form); the expiry note
        # is the detail dialog's (`EXPIRED_NOTE` via `EventDetailVM.expired`).
        readiness_note=ready.note,
        video_url=item.video_url,
        output_label=output_label(item.output_port),
        destination=item.destination or "",
        destination_label=DESTINATION_LABELS.get(item.destination or "", ""),
        campaign_name=item.campaign_name,
        campaign_color=item.campaign_color,
        **(_temperature_fields(item.times_published) if item.times_published is not None else {}),
    )


CELL_VISIBLE = 5


def _cell(
    *, day_iso: str, hour: int, is_today: bool, is_past: bool, cards, heading: str = ""
) -> HourCellVM:
    """A calendar cell: all its cards (in time order), and the split the grid draws —
    the first `CELL_VISIBLE`, then the rest behind «+N más»."""
    cards = list(cards)
    return HourCellVM(
        day_iso=day_iso,
        hour=hour,
        is_today=is_today,
        is_past=is_past,
        cards=cards,
        visible=cards[:CELL_VISIBLE],
        more=cards[CELL_VISIBLE:],
        more_count=max(len(cards) - CELL_VISIBLE, 0),
        heading=heading,
    )


def build_week(
    *,
    monday: date,
    today: date,
    zone: ZoneInfo,
    items: Iterable[CardInput],
    connections: Mapping[str, tuple[str, str]],
) -> WeekGrid:
    """The week as seven day groups (list view, headers) and as hour rows × seven cells
    (calendar view). Cards are chronological everywhere. An event outside the week is
    ignored (the service already filters)."""
    week_days = [monday + timedelta(days=i) for i in range(7)]
    by_day: dict[date, list[tuple[datetime, EventCardVM]]] = {d: [] for d in week_days}
    by_cell: dict[tuple[int, date], list[tuple[datetime, EventCardVM]]] = {}
    for item in items:
        local = item.scheduled_at.astimezone(zone)
        if local.date() not in by_day:
            continue
        card = build_card(item, zone=zone, connections=connections)
        by_day[local.date()].append((item.scheduled_at, card))
        by_cell.setdefault((hour_row_for(local.hour), local.date()), []).append(
            (item.scheduled_at, card)
        )

    def ordered(pairs: list[tuple[datetime, EventCardVM]]) -> list[EventCardVM]:
        return [card for _, card in sorted(pairs, key=lambda pair: pair[0])]

    days = [
        DayColumnVM(
            iso=d.isoformat(),
            weekday=_WEEKDAYS[d.weekday()],
            day_number=str(d.day),
            title=day_title(d, today),
            is_today=d == today,
            is_past=d < today,
            count=len(by_day[d]),
            cards=ordered(by_day[d]),
        )
        for d in week_days
    ]
    rows = [
        HourRowVM(
            key=key,
            label=hour_row_label(key),
            cells=[
                _cell(
                    day_iso=d.isoformat(),
                    hour=key,
                    is_today=d == today,
                    is_past=d < today,
                    cards=ordered(by_cell.get((key, d), [])),
                    heading=f"{_WEEKDAYS[d.weekday()]} {d.day} · {hour_row_label(key)}",
                )
                for d in week_days
            ],
        )
        for key in HOUR_ROW_KEYS
    ]
    return WeekGrid(days=days, rows=rows)


def build_post_option(
    *,
    post_id: str,
    title: str,
    caption_excerpt: str,
    thumbnail_url: str | None,
    category: str | None,
    approval: str,
    detail_href: str,
    is_publishable: bool,
    unpublishable_reason: str,
    outputs: Iterable[OutputChipVM] = (),
    video_url: str = "",
    gallery_state: str = "",
    times_published: int = 0,
    has_live_event: bool = False,
    media_types: tuple[str, ...] = (),
    image_size: tuple[int, int] | None = None,
    preferred_destination: str | None = None,
    lifecycle_status: str = "",
    campaign_name: str = "",
    campaign_color: str = "",
    campaign_id: str = "",
    event_count: int = 0,
    retention_state: str = "",
    purge_days_left: int | None = None,
) -> PostOptionVM:
    ready = readiness(approval, is_publishable=is_publishable, reason=unpublishable_reason)
    r_label, r_tone = retention_badge(retention_state, purge_days_left)
    chips = list(outputs)
    g_label, g_tone = GALLERY_LABELS.get(gallery_state, ("", "neutral"))
    card = card_state(
        gallery_state,
        waiting_review=lifecycle_status == "generated",
        times_published=times_published,
    )
    shows_history = card is not None and card.key in HISTORY_CARD_STATES
    if card is not None:  # the same words on every surface that prints the state
        g_label, g_tone = card.label, card.tone
    kind, aspect = frame_shape(category or "", "")
    ratio = aspect.replace(" / ", ":")
    medium = "Video" if video_url else "Imagen"
    return PostOptionVM(
        post_id=post_id,
        title=title,
        caption_excerpt=caption_excerpt,
        thumbnail_url=thumbnail_url or "",
        category_label=category_label(category),
        approval_label=ready.label,
        approval_tone=ready.tone,
        detail_href=detail_href,
        approval_short=ready.short,
        readiness_note=ready.note,
        outputs=chips,
        has_outputs=bool(chips),
        next_port=next((chip.port for chip in chips if not chip.scheduled), ""),
        category=category or "",
        schedulable=approval == "approved" and is_publishable,
        video_url=video_url,
        gallery_state=gallery_state,
        gallery_label=g_label,
        gallery_tone=g_tone,
        used_count=times_published,
        in_calendar=has_live_event,
        media_label=f"{medium} · {kind}" + ("" if ratio in kind else f" {ratio}"),
        **_kind_fields(media_types, category or "", has_outputs=bool(chips)),
        **_temperature_fields(times_published),
        destinations=(choices := destinations_for(media_types, image_size)),
        default_destination=default_destination(
            choices, preferred_destination or _CATEGORY_DESTINATION.get(category or "")
        ),
        can_review=lifecycle_status == "generated",
        campaign_name=campaign_name,
        campaign_color=campaign_color,
        campaign_id=campaign_id,
        event_count=event_count,
        retention_label=r_label,
        retention_tone=r_tone,
        card_state=card.key if card is not None else "",
        card_label=card.label if card is not None else "",
        card_tone=card.tone if card is not None else "neutral",
        card_action=card.action if card is not None else CARD_ACTION_VIEW,
        card_action_label=card.action_label if card is not None else "Ver",
        history_word=history_word(times_published) if shows_history else "",
        history_help=history_help(times_published) if shows_history else "",
    )


def filter_posts(posts: Iterable[PostOptionVM], *, state: str, category: str) -> list[PostOptionVM]:
    """The gallery's filters: by the card's state (`CARD_STATES`, m-24842981) and by raw
    category; `GALLERY_FILTER_ALL` (or "") means no filter on that axis."""
    return [
        post
        for post in posts
        if (state in ("", GALLERY_FILTER_ALL) or post.card_state == state)
        and (category in ("", GALLERY_FILTER_ALL) or post.category == category)
    ]


def category_options(posts: Iterable[PostOptionVM]) -> list[CategoryOptionVM]:
    """The categories present among `posts`, each once, in first-seen order."""
    seen: dict[str, str] = {}
    for post in posts:
        if post.category and post.category not in seen:
            seen[post.category] = post.category_label
    return [CategoryOptionVM(value=value, label=label) for value, label in seen.items()]


# ---------------------------------------------------------------------------
# QUA-118: the assign drawer's pure pieces (tested without Reflex)


def _short_day(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()].lower()} {day.day} {_MONTHS[day.month - 1]}"


def series_preview(
    first_day_iso: str,
    *,
    repeat: bool,
    mode: str,
    count_text: str,
    until_iso: str,
    weekdays: list[int] | None = None,
) -> SeriesPreviewVM:
    """The «Fecha y hora» step's reading of the recurrence controls — the same rule the
    service applies (`recurrence.weekly_days`), so the step never promises a series
    the backend will refuse. Not repeating → one occurrence, no summary."""
    if not repeat:
        return SeriesPreviewVM()
    try:
        first_day = date.fromisoformat(first_day_iso)
    except ValueError:
        return SeriesPreviewVM(enabled=True, count=0, error="Elige primero la fecha.")
    try:
        if weekdays is not None:
            # QUA-118 v2: several weekdays, `count_text` weeks each
            # (`recurrence.weekly_days_on`); no weekday chosen → the start date's own.
            try:
                weeks = int(count_text.strip() or "0")
            except ValueError:
                weeks = 0
            days = weekly_days_on(first_day, weekdays or [first_day.weekday()], weeks)
        elif mode == REPEAT_BY_UNTIL:
            if not until_iso:
                return SeriesPreviewVM(enabled=True, count=0, error="Elige la fecha de fin.")
            days = weekly_days(first_day, until=date.fromisoformat(until_iso))
        else:
            try:
                count = int(count_text.strip() or "0")
            except ValueError:
                count = 0
            days = weekly_days(first_day, count=count)
    except ValueError as exc:  # InvalidRecurrence is a ValueError; a bad until_iso too
        code = exc.code if isinstance(exc, InvalidRecurrence) else ""
        return SeriesPreviewVM(
            enabled=True, count=0, error=SERIES_MESSAGES.get(code, SERIES_UNKNOWN_MESSAGE)
        )
    n = len(days)
    times = "1 vez" if n == 1 else f"{n} veces"
    span = (
        f"el {_short_day(days[0])}"
        if n == 1
        else f"del {_short_day(days[0])} al {_short_day(days[-1])}"
    )
    return SeriesPreviewVM(
        enabled=True,
        count=n,
        dates=[_short_day(d) for d in days],
        summary=f"Semanal · {times} · {span}",
    )


def assign_steps_done(*, post_ok: bool, when_ok: bool, reached: int) -> list[bool]:
    """Which steps count as completed: the two input steps by their own validity AND
    only once reached (a defaulted date or a preselected account is not a step the
    operator completed); never the last one — confirming is the act, not a state. A
    later step is never done while an earlier one is not, so the stepper cannot show a
    gap. `reached` is the furthest step visited."""
    return [post_ok, post_ok and when_ok and reached >= STEP_WHEN, False]


def frame_shape(category: str, output_port: str) -> tuple[str, str]:
    """(kind label, CSS aspect ratio) for a preview frame: the template output when the
    event publishes one, else the POST's category."""
    if output_port == "reel":
        return "Reel", "9 / 16"
    if output_port == "story":
        return "Historia", "9 / 16"
    if output_port == "feed":
        return "Feed 4:5", "4 / 5"
    if category in ("reel", "tiktok_video"):
        return "Reel", "9 / 16"
    if category == "story":
        return "Historia", "9 / 16"
    if category == "galeria":
        return "Galería", "1 / 1"
    return "Publicación", "4 / 5"


def media_label(post: PostOptionVM | None, output_port: str) -> str:
    """ "Video · Reel 9:16" — the POST's media as the summary card prints it."""
    if post is None:
        return ""
    kind, aspect = frame_shape(post.category, output_port)
    medium = "Video" if post.video_url else "Imagen"
    ratio = aspect.replace(" / ", ":")
    return f"{medium} · {kind}" + ("" if ratio in kind else f" {ratio}")


def build_output_chip(
    *,
    port: str,
    is_publishable: bool,
    unpublishable_reason: str,
    event_status: str | None,
    when_label: str = "",
    account_label: str = "",
    media_types: tuple[str, ...] = (),
    image_size: tuple[int, int] | None = None,
    preferred_destination: str | None = None,
) -> OutputChipVM:
    """One output's chip (MP-11). `event_status` is the live event's, or None when the
    output has none. A scheduled output reads «lun 12:00 · @bianki»; an unscheduled one
    that cannot be published yet reads «no publicable» with the reason as its note."""
    if event_status is None:
        if is_publishable:
            state, tone, note = OUTPUT_UNSCHEDULED, "neutral", ""
        else:
            state, tone, note = OUTPUT_NOT_PUBLISHABLE, "warn", unpublishable_reason
    elif event_status in _OUTPUT_STATE:
        (state, tone), note = _OUTPUT_STATE[event_status], ""
    else:
        state = " · ".join(part for part in (when_label, account_label) if part) or "programada"
        tone, note = "ok", ""
    return OutputChipVM(
        port=port,
        label=output_long_label(port),
        word=output_label(port),
        state_label=state,
        tone=tone,
        scheduled=event_status is not None,
        note=note,
        destinations=(choices := destinations_for(media_types, image_size)),
        default_destination=default_destination(
            choices, preferred_destination or _PORT_DESTINATION.get(port)
        ),
        **_kind_fields(media_types, "", has_outputs=False),
    )


# ---------------------------------------------------------------------------
# QUA-118 v2: format, temperature, goals and the multi-POST plan (pure, tested directly)

# What the content IS (QUA-118 v2): read from its media, never from where it goes out.
# The key drives the tile's colour (`q-kind-*`); the destination has its own (`q-dest-*`).
_IMAGE_KIND = ("image", "Imagen", "image")
_VIDEO_KIND = ("video", "Video", "film")
_CAROUSEL_KIND = ("carousel", "Galería", "gallery-horizontal-end")
_PACK_KIND = ("pack", "Multiformato", "layers")
# Every content key with its glyph — the page matches over it (`rx.icon` needs a literal).
KIND_ICONS: dict[str, str] = {
    key: icon for key, _word, icon in (_IMAGE_KIND, _VIDEO_KIND, _CAROUSEL_KIND, _PACK_KIND)
}
# Only when the media is unknown (a POST read without assets): the category's usual shape.
_CATEGORY_KIND: dict[str, tuple[str, str, str]] = {
    "reel": _VIDEO_KIND,
    "tiktok_video": _VIDEO_KIND,
    "story": _IMAGE_KIND,
    "galeria": _CAROUSEL_KIND,
}


def post_kind(
    media_types: tuple[str, ...] | list[str] = (),
    *,
    category: str = "",
    has_outputs: bool = False,
) -> tuple[str, str, str]:
    """(key, word, glyph) of what the content is: one image, one video, a carousel, or a
    template package not yet split into one output («Multiformato»). `media_types` is
    the publisher's vocabulary (IMAGE / VIDEO), in order."""
    if has_outputs:
        return _PACK_KIND
    types = tuple(media_types)
    if len(types) == 1:
        return _VIDEO_KIND if types[0] == "VIDEO" else _IMAGE_KIND
    if len(types) >= 2:
        return _CAROUSEL_KIND
    return _CATEGORY_KIND.get(category, _IMAGE_KIND)


def _kind_fields(
    media_types: tuple[str, ...], category: str, *, has_outputs: bool
) -> dict[str, str]:
    key, label, _icon = post_kind(media_types, category=category, has_outputs=has_outputs)
    return {"kind": key, "kind_label": label}


# Where an event goes out (QUA-118 v2, `publishable.DESTINATIONS`): the word the operator
# reads everywhere — never «Feed» — and its glyph.
DESTINATION_LABELS: dict[str, str] = {"post": "Publicación", "reel": "Reel", "story": "Historia"}
DESTINATION_ICONS: dict[str, str] = {
    "post": "grid-3x3",
    "reel": "clapperboard",
    "story": "circle-fading-plus",
}
DESTINATION_REQUIRED = "Elige dónde quieres publicarlo."


@dataclass(frozen=True)
class DestinationChoiceVM:
    """One button of «¿Dónde quieres publicarlo?» (`publishable.DestinationOption`)."""

    key: str  # post / reel / story
    label: str
    available: bool
    reason: str = ""  # why it is off, printed under the selector
    warning: str = ""  # what Meta may still refuse that cannot be checked here


def destination_choices(options) -> list[DestinationChoiceVM]:
    """The offered options of `publishable.destination_options`, as the selector shows
    them; a destination that is not offered (a video's «Publicación») is left out."""
    return [
        DestinationChoiceVM(
            key=o.destination,
            label=DESTINATION_LABELS[o.destination],
            available=o.available,
            reason=o.reason,
            warning=o.warning,
        )
        for o in options
        if o.offered
    ]


_CATEGORY_DESTINATION: dict[str, str] = {"reel": "reel", "story": "story", "galeria": "post"}
_PORT_DESTINATION: dict[str, str] = {"reel": "reel", "story": "story", "feed": "post"}


def destinations_for(
    media_types: tuple[str, ...], image_size: tuple[int, int] | None
) -> list[DestinationChoiceVM]:
    """The selector's buttons for content of this shape (`publishable.destination_options`
    — the same rule the service and the executor apply)."""
    return destination_choices(destination_options(tuple(media_types), image_size))


def default_destination(choices: list[DestinationChoiceVM], preferred: str | None) -> str:
    """What the selector starts on: what the POST publishes as today (its category or
    output), when that is available; else the first available one; else ""."""
    available = [c.key for c in choices if c.available]
    if preferred in available:
        return preferred or ""
    return available[0] if available else ""


# Cold / Hot (founder's brief, 2026-10-06). The words are the boss's, the idea is the
# market's: «cold» is EVERGREEN content — it has worked every time it went out and can be
# repeated safely (brands recycle their top performers every 60–90 days); «hot» is content
# just made, still to prove itself on the channels. Until per-post performance metrics
# land, "worked" is read from the POST's own publishing history (D2): reused from the
# Planificador at least `COLD_MIN_USES` times means the team keeps choosing it.
TEMPERATURE_COLD = "cold"
TEMPERATURE_HOT = "hot"
COLD_MIN_USES = 2


def temperature(times_published: int) -> tuple[str, str, str]:
    """(key, word, hint) for a POST published `times_published` times."""
    n = max(times_published, 0)
    if n >= COLD_MIN_USES:
        return (
            TEMPERATURE_COLD,
            "Cold",
            f"Cold · probado: salió {n} veces. Contenido evergreen, seguro para repetir.",
        )
    if n == 1:
        return TEMPERATURE_HOT, "Hot", "Hot · en prueba: salió 1 vez, aún sin historial."
    return TEMPERATURE_HOT, "Hot", "Hot · nuevo: todavía no ha salido en tus redes."


def _temperature_fields(times_published: int) -> dict[str, str]:
    key, label, hint = temperature(times_published)
    return {"temperature": key, "temperature_label": label, "temperature_hint": hint}


@dataclass(frozen=True)
class PlanGoalVM:
    """One goal the operator can set for a plan (the confirm step's checks)."""

    key: str
    label: str
    icon: str
    color: str  # a Radix scale — identity, like a tag colour, never a state
    hint: str


PLAN_GOALS: tuple[PlanGoalVM, ...] = (
    PlanGoalVM("likes", "Likes", "heart", "pink", "Que guste: reacciones"),
    PlanGoalVM("views", "Vistas", "eye", "blue", "Alcance: que lo vea más gente"),
    PlanGoalVM("comments", "Comentarios", "message-circle", "violet", "Abrir conversación"),
    PlanGoalVM("ads", "Ads", "megaphone", "amber", "Candidato a pauta pagada"),
    PlanGoalVM("followers", "Seguidores", "user-plus", "green", "Crecer la comunidad"),
    PlanGoalVM("engagement", "Interacción", "sparkles", "teal", "Guardados y compartidos"),
)
PLAN_GOAL_KEYS: frozenset[str] = frozenset(g.key for g in PLAN_GOALS)


def goal_labels(keys) -> list[str]:
    """The stored goal keys (0042) as the panel prints them, in `PLAN_GOALS` order."""
    chosen = set(keys or ())
    return [g.label for g in PLAN_GOALS if g.key in chosen]


PLAN_OUTPUT_REQUIRED = "Elige qué salida programar (Reel, feed o historia)."
PLAN_ACCOUNT_REQUIRED = "Elige al menos una cuenta compatible."
PLAN_DATE_REQUIRED = "Elige la fecha y la hora."
PLAN_DATE_PAST = "Esa fecha ya pasó. Elige una de hoy en adelante."
PLAN_TIME_PAST = "Esa hora ya pasó. Elige una posterior."


def split_time(value: str) -> tuple[int, int]:
    """ "15:50" → (15, 50); anything unparsable → 09:00."""
    try:
        hour_text, minute_text = value.split(":")[:2]
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        return 9, 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return 9, 0
    return hour, minute


def time_label(at: str) -> str:
    """ "10:00 a. m." """
    hour, minute = split_time(at)
    return f"{hour % 12 or 12}:{minute:02d} {'a. m.' if hour < 12 else 'p. m.'}"


def when_label(day_iso: str, at: str) -> str:
    """ "lun 12 oct · 10:00 a. m." — "" without a valid date."""
    try:
        day = date.fromisoformat(day_iso)
    except ValueError:
        return ""
    return f"{_short_day(day)} · {time_label(at)}"


@dataclass(frozen=True)
class PlanItem:
    """One piece of a plan as the operator edits it: which POST (and output), when,
    where, with which tags, and whether it repeats weekly. Raw values only; the row the
    page renders is `build_plan_row`'s."""

    post_id: str
    date: str = ""
    time: str = "09:00"
    connection_ids: list[str] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)
    output_port: str = ""
    repeat: bool = False
    repeat_count: str = "4"  # weeks
    destination: str = ""  # post / reel / story — where this piece goes out
    # The weekdays of a weekly series (0 = Monday); empty → the date's own weekday.
    repeat_days: list[int] = field(default_factory=list)
    # QUA-143: the campaign chosen for the piece's POST — a campaign id, `CAMPAIGN_NONE` or
    # `CAMPAIGN_NEW` (then `new_campaign_name`/`_color`). "" = keep the POST's own. It is
    # the POST's campaign: applied to the POST on «Confirmar», never to the publication.
    campaign: str = ""
    new_campaign_name: str = ""
    new_campaign_color: str = ""

    # A plan kept in a session from before a field existed (Reflex keeps dev state across
    # reloads) reads the field's default instead of failing.
    _LATER_DEFAULTS = {
        "destination": "",
        "repeat_days": (),
        "campaign": "",
        "new_campaign_name": "",
        "new_campaign_color": "",
    }

    def __getattr__(self, name: str):
        if name in PlanItem._LATER_DEFAULTS:
            return list(PlanItem._LATER_DEFAULTS[name]) if name == "repeat_days" else ""
        raise AttributeError(name)


@dataclass(frozen=True)
class PlanRowVM:
    """One piece of the plan, ready to render in «Programación» and «Confirmar»."""

    post_id: str
    title: str
    caption_excerpt: str
    thumbnail_url: str
    video_url: str
    kind: str  # image / video / carousel / pack — what the content IS
    kind_label: str
    aspect: str  # CSS aspect-ratio of the frame
    media_label: str
    temperature: str
    temperature_label: str
    temperature_hint: str
    date: str
    time: str
    hour12: str
    minute: str
    meridiem: str
    when_label: str
    day_label: str  # "lun 12 oct"
    time_label: str
    connection_ids: list[str]
    tag_ids: list[str]
    accounts: list[ConnectionChoiceVM]
    tags: list[TagVM]
    first_account: str
    output_port: str
    output_label: str
    outputs: list[OutputChipVM]
    has_outputs: bool
    repeat: bool
    repeat_count: str
    series: SeriesPreviewVM
    event_count: int
    note: str  # it will be scheduled but not published yet: why ("" when ready)
    error: str  # why this piece cannot be planned as set ("" when it can)
    # QUA-118 v2: where it goes out, the selector's buttons, and what to say about it.
    destination: str = ""
    destination_label: str = ""
    destinations: list[DestinationChoiceVM] = field(default_factory=list)
    destination_warning: str = ""  # e.g. a video story longer than 60 s
    mock: str = "post"  # the phone mock: post / carousel / reel / story
    repeat_days: list[int] = field(default_factory=list)  # chosen weekdays (0 = Monday)
    # QUA-143 — the POST's campaign: the one it HAS (the header badge) and the one chosen
    # here (the selector, `campaign_value`), whether that is a change, what the change
    # reaches («sus otras N publicaciones») and the new campaign being typed.
    current_campaign_name: str = ""
    current_campaign_color: str = ""
    campaign_value: str = ""
    chosen_campaign_name: str = ""
    chosen_campaign_color: str = ""
    campaign_changed: bool = False
    campaign_warning: str = ""
    creating_campaign: bool = False
    new_campaign_name: str = ""
    new_campaign_color: str = ""


CAMPAIGN_NONE = "none"  # the selector's «Sin campaña» (same value as the POST detail)
CAMPAIGN_NEW = "new"  # the selector's «Nueva campaña»
CAMPAIGN_NAME_REQUIRED = "Escribe el nombre de la nueva campaña."


def campaign_value(item: PlanItem, post: PostOptionVM | None) -> str:
    """What the piece's selector shows: the operator's pick, else the POST's own."""
    if item.campaign:
        return item.campaign
    return (post.campaign_id if post is not None and post.campaign_id else "") or CAMPAIGN_NONE


def campaign_warning(existing: int) -> str:
    """QUA-143 AC 19: a campaign change reaches every publication the POST already has."""
    if existing <= 0:
        return ""
    if existing == 1:
        return "La campaña pertenece al POST y también se aplicará a su otra publicación."
    return (
        f"La campaña pertenece al POST y también se aplicará a sus otras {existing} publicaciones."
    )


def plan_item_error(
    item: PlanItem,
    *,
    post: PostOptionVM | None,
    accounts: list[ConnectionChoiceVM],
    series: SeriesPreviewVM,
    today_iso: str,
    now_hhmm: str,
    reschedule: bool = False,
    destinations: list[DestinationChoiceVM] | None = None,
) -> str:
    """The first thing that keeps `item` from being planned, in the operator's words:
    the output of a package, where it goes out, the date and time, the weekly series,
    the accounts — and a new campaign without a name (QUA-143)."""
    if not reschedule and item.campaign == CAMPAIGN_NEW and not item.new_campaign_name.strip():
        return CAMPAIGN_NAME_REQUIRED
    if not reschedule and post is not None and post.has_outputs:
        if not item.output_port:
            return PLAN_OUTPUT_REQUIRED
        for chip in post.outputs:
            if chip.port == item.output_port and chip.note:
                return chip.note
    if not reschedule and destinations is not None:
        chosen = next((d for d in destinations if d.key == item.destination), None)
        if chosen is None:
            return DESTINATION_REQUIRED
        if not chosen.available:
            return chosen.reason
    if not item.date or not item.time:
        return PLAN_DATE_REQUIRED
    if today_iso and item.date < today_iso:
        return PLAN_DATE_PAST
    if today_iso and now_hhmm and item.date == today_iso and item.time <= now_hhmm:
        return PLAN_TIME_PAST
    if series.error:
        return series.error
    if not accounts:
        return PLAN_ACCOUNT_REQUIRED
    return ""


def build_plan_row(
    item: PlanItem,
    *,
    post: PostOptionVM | None,
    connections: Iterable[ConnectionChoiceVM],
    tags: Iterable[TagVM] = (),
    today_iso: str = "",
    now_hhmm: str = "",
    reschedule: bool = False,
    campaigns: Iterable = (),
) -> PlanRowVM:
    """`item` as the page renders it. `post` is None only for a POST no longer listed.
    `campaigns` are the brand's (anything with `id`, `name`, `color`)."""
    if post is None:
        post = PostOptionVM(
            post_id=item.post_id,
            title="POST no disponible",
            caption_excerpt="",
            thumbnail_url="",
            category_label="",
            approval_label="",
            approval_tone="neutral",
            detail_href="",
        )
    chosen = set(item.connection_ids)
    accounts = [c for c in connections if c.id in chosen and c.compatible]
    tag_set = set(item.tag_ids)
    series = series_preview(
        item.date,
        repeat=item.repeat and not reschedule,
        mode=REPEAT_BY_COUNT,
        count_text=item.repeat_count,
        until_iso="",
        weekdays=list(item.repeat_days),
    )
    chip = next((c for c in post.outputs if c.port == item.output_port), None)
    if chip is not None:
        key, label = chip.kind, chip.kind_label
        destinations = chip.destinations
    elif post.has_outputs and not item.output_port:
        key, label, _icon = post_kind(has_outputs=True)
        destinations = []
    else:
        key, label = post.kind, post.kind_label
        destinations = post.destinations
    dest = item.destination
    chosen = next((d for d in destinations if d.key == dest), None)
    mock = {"reel": "reel", "story": "story"}.get(dest, "carousel" if key == "carousel" else "post")
    aspect = {"reel": "9 / 16", "story": "9 / 16", "carousel": "1 / 1"}.get(mock, "4 / 5")
    hour, minute = split_time(item.time)
    output_label = (
        chip.label if chip else (output_long_label(item.output_port) if item.output_port else "")
    )
    value = campaign_value(item, post)
    current = post.campaign_id or CAMPAIGN_NONE
    known = {c.id: c for c in campaigns}
    if value == CAMPAIGN_NEW:
        chosen_name, chosen_color = item.new_campaign_name.strip(), item.new_campaign_color
    elif value in known:
        chosen_name, chosen_color = known[value].name, known[value].color
    else:
        chosen_name, chosen_color = "", ""
    changed = not reschedule and value != current
    campaign_fields = {
        "current_campaign_name": post.campaign_name,
        "current_campaign_color": post.campaign_color,
        "campaign_value": value,
        "chosen_campaign_name": chosen_name,
        "chosen_campaign_color": chosen_color,
        "campaign_changed": changed,
        "campaign_warning": campaign_warning(post.event_count) if changed else "",
        "creating_campaign": value == CAMPAIGN_NEW and not reschedule,
        "new_campaign_name": item.new_campaign_name,
        "new_campaign_color": item.new_campaign_color,
    }
    return PlanRowVM(
        post_id=item.post_id,
        title=post.title,
        caption_excerpt=post.caption_excerpt,
        thumbnail_url=post.thumbnail_url,
        video_url=post.video_url,
        kind=key,
        kind_label=label,
        aspect=aspect,
        media_label=media_label(post, item.output_port),
        temperature=post.temperature,
        temperature_label=post.temperature_label,
        temperature_hint=post.temperature_hint,
        date=item.date,
        time=item.time,
        hour12=str(hour % 12 or 12),
        minute=f"{minute:02d}",
        meridiem="am" if hour < 12 else "pm",
        when_label=when_label(item.date, item.time),
        day_label=when_label(item.date, item.time).split(" · ")[0],
        time_label=time_label(item.time),
        connection_ids=list(item.connection_ids),
        tag_ids=list(item.tag_ids),
        accounts=accounts,
        tags=[t for t in tags if t.id in tag_set],
        first_account=accounts[0].label if accounts else "tu_cuenta",
        output_port=item.output_port,
        output_label=output_label,
        outputs=[] if reschedule else list(post.outputs),
        has_outputs=post.has_outputs and not reschedule,
        repeat=item.repeat and not reschedule,
        repeat_count=item.repeat_count,
        series=series,
        event_count=max(series.count, 1) * len(accounts),
        note=chip.note if chip else post.readiness_note,
        error=plan_item_error(
            item,
            post=post,
            accounts=accounts,
            series=series,
            today_iso=today_iso,
            now_hhmm=now_hhmm,
            reschedule=reschedule,
            destinations=None if reschedule else destinations,
        ),
        destination=dest,
        destination_label=DESTINATION_LABELS.get(dest, ""),
        destinations=[] if reschedule else list(destinations),
        destination_warning=chosen.warning if chosen is not None else "",
        mock=mock,
        repeat_days=list(item.repeat_days),
        **campaign_fields,
    )


def approved_line(day_iso: str, at: str) -> str:
    """N13 (m-24842959): what the event panel says of an approved, scheduled publication —
    «Aprobada por ti: sale el lunes 28 de septiembre a las 3:00 p. m.» («a la 1:…»).
    "" without a valid date; no final period, «p. m.» already ends the sentence. The
    owner approved it; Qualify never publishes on its own."""
    try:
        day = date.fromisoformat(day_iso)
    except ValueError:
        return ""
    hour, _minute = split_time(at)
    article = "a la" if hour % 12 == 1 else "a las"
    weekday = _WEEKDAYS_LONG[day.weekday()].lower()
    month = _MONTHS_LONG[day.month - 1]
    return f"Aprobada por ti: sale el {weekday} {day.day} de {month} {article} {time_label(at)}"
