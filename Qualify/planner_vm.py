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

from qualify_api.planner.recurrence import SERIES_CAP, InvalidRecurrence, weekly_days

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
}
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
GALLERY_LABELS: dict[str, tuple[str, str]] = {
    "draft": ("Borrador", "neutral"),
    "needs_action": ("Por completar", "warn"),
    "schedulable": ("Listo", "ok"),
    "used": ("Usado", "info"),
    "discarded": ("Desechado", "error"),
}
GALLERY_FILTER_ALL = "all"
GALLERY_STATE_FILTERS: tuple[tuple[str, str], ...] = tuple(
    (value, label) for value, (label, _tone) in GALLERY_LABELS.items()
)


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
    kind: str = "feed"
    kind_label: str = "Feed"
    temperature: str = "hot"
    temperature_label: str = "Hot"
    temperature_hint: str = ""


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
                HourCellVM(
                    day_iso=d.isoformat(),
                    hour=key,
                    is_today=d == today,
                    is_past=d < today,
                    cards=ordered(by_cell.get((key, d), [])),
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
) -> PostOptionVM:
    ready = readiness(approval, is_publishable=is_publishable, reason=unpublishable_reason)
    chips = list(outputs)
    g_label, g_tone = GALLERY_LABELS.get(gallery_state, ("", "neutral"))
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
        **_kind_fields(category or "", has_outputs=bool(chips)),
        **_temperature_fields(times_published),
    )


def filter_posts(posts: Iterable[PostOptionVM], *, state: str, category: str) -> list[PostOptionVM]:
    """The gallery's filters: by derived state and by raw category; `GALLERY_FILTER_ALL`
    (or "") means no filter on that axis."""
    return [
        post
        for post in posts
        if (state in ("", GALLERY_FILTER_ALL) or post.gallery_state == state)
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
        if mode == REPEAT_BY_UNTIL:
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
    )


# ---------------------------------------------------------------------------
# QUA-118 v2: format, temperature, goals and the multi-POST plan (pure, tested directly)

# The format a tile announces: (key, word, lucide glyph). The key drives the colour and,
# in the confirm step, the shape of the phone mock (story bars, reel rail, feed header).
_KINDS: dict[str, tuple[str, str, str]] = {
    "reel": ("reel", "Reel", "clapperboard"),
    "tiktok_video": ("reel", "Reel", "clapperboard"),
    "story": ("story", "Historia", "circle-fading-plus"),
    "galeria": ("gallery", "Carrusel", "gallery-horizontal-end"),
    "gallery": ("gallery", "Carrusel", "gallery-horizontal-end"),
    "carousel": ("gallery", "Carrusel", "gallery-horizontal-end"),
}
_FEED_KIND = ("feed", "Feed", "image")
_PACK_KIND = ("pack", "Multiformato", "layers")
# Every format key with its glyph — the page matches over it (`rx.icon` needs a literal).
KIND_ICONS: dict[str, str] = {
    key: icon for key, _word, icon in (*_KINDS.values(), _FEED_KIND, _PACK_KIND)
}
_OUTPUT_KINDS: dict[str, tuple[str, str, str]] = {
    "reel": _KINDS["reel"],
    "story": _KINDS["story"],
    "feed": _FEED_KIND,
}


def post_kind(
    category: str, *, has_outputs: bool = False, output_port: str = ""
) -> tuple[str, str, str]:
    """(key, word, glyph) of what a POST — or one template output of it — publishes as.
    A template package not yet split into one output reads «Multiformato»."""
    if output_port in _OUTPUT_KINDS:
        return _OUTPUT_KINDS[output_port]
    if has_outputs:
        return _PACK_KIND
    return _KINDS.get(category, _FEED_KIND)


def _kind_fields(category: str, *, has_outputs: bool) -> dict[str, str]:
    key, label, _icon = post_kind(category, has_outputs=has_outputs)
    return {"kind": key, "kind_label": label}


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
    repeat_count: str = "4"


@dataclass(frozen=True)
class PlanRowVM:
    """One piece of the plan, ready to render in «Programación» and «Confirmar»."""

    post_id: str
    title: str
    caption_excerpt: str
    thumbnail_url: str
    video_url: str
    kind: str  # reel / story / gallery / feed / pack — the mock's shape and colour
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


def plan_item_error(
    item: PlanItem,
    *,
    post: PostOptionVM | None,
    accounts: list[ConnectionChoiceVM],
    series: SeriesPreviewVM,
    today_iso: str,
    now_hhmm: str,
    reschedule: bool = False,
) -> str:
    """The first thing that keeps `item` from being planned, in the operator's words:
    the output of a package, the date and time, the weekly series, the accounts."""
    if not reschedule and post is not None and post.has_outputs:
        if not item.output_port:
            return PLAN_OUTPUT_REQUIRED
        for chip in post.outputs:
            if chip.port == item.output_port and chip.note:
                return chip.note
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
) -> PlanRowVM:
    """`item` as the page renders it. `post` is None only for a POST no longer listed."""
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
    )
    key, label, _icon = post_kind(
        post.category,
        has_outputs=post.has_outputs and not item.output_port,
        output_port=item.output_port,
    )
    _shape, aspect = frame_shape(post.category, item.output_port)
    hour, minute = split_time(item.time)
    chip = next((c for c in post.outputs if c.port == item.output_port), None)
    output_label = (
        chip.label if chip else (output_long_label(item.output_port) if item.output_port else "")
    )
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
        ),
    )
