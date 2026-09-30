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

VIEW_CALENDAR = "calendar"
VIEW_LIST = "list"

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

# (long label, short label for the compact calendar card, tone)
_APPROVAL_LABEL: dict[str, tuple[str, str, str]] = {
    "approved": ("Aprobado", "Aprobado", "ok"),
    "pending": ("Pendiente de aprobación", "Pendiente", "warn"),
    "rejected": ("Rechazado", "Rechazado", "error"),
    "not_ready": ("En producción", "En producción", "neutral"),
}
_MISSING_POST = ("POST no disponible", "No disponible", "error")

_STATUS_LABEL: dict[str, tuple[str, str]] = {
    "scheduled": ("Programado", "info"),
    "cancelled": ("Cancelado", "neutral"),
    "publishing": ("Publicando", "info"),
    "published": ("Publicado", "ok"),
    "failed": ("Falló", "error"),
}
OVERDUE_LABEL = ("Venció sin aprobación", "warn")

# The POST category vocabulary is QUA-109's. These labels cover what the temporary
# adapter returns plus the categories QUA-109 is expected to introduce.
_CATEGORY_LABEL: dict[str, str] = {
    "feed": "Publicación",
    "gallery": "Galería",
    "carousel": "Galería",
    "story": "Story",
    "reel": "Reel",
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


def status_label(status: str, *, overdue: bool) -> tuple[str, str]:
    if overdue:
        return OVERDUE_LABEL
    return _STATUS_LABEL.get(status, (status, "neutral"))


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
    """An account the operator can plan onto (active connections only)."""

    id: str
    label: str  # "@cuenta"
    platform: str


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
    can_delete: bool = False  # cancelled → removable from the calendar
    detail_href: str = ""
    publish_note: str = ""  # why this POST cannot be published yet, if so
    # Pre-filled values for the reschedule form.
    local_date: str = ""
    local_time: str = ""
    connection_id: str = ""
    tags: list[TagVM] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)


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


def build_card(
    item: CardInput, *, zone: ZoneInfo, connections: Mapping[str, tuple[str, str]]
) -> EventCardVM:
    local = item.scheduled_at.astimezone(zone)
    platform, account = connections.get(item.connection_id, ("", "Cuenta desconocida"))
    approval = item.approval if item.post_title is not None else None
    a_label, a_tone = approval_label(approval)
    s_label, s_tone = status_label(item.status, overdue=item.overdue)
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
        approval_label=a_label,
        approval_short=approval_short(approval),
        approval_tone=a_tone,
        status_label=s_label,
        status_tone=s_tone,
        overdue=item.overdue,
        can_modify=item.status == "scheduled",
        muted=item.status == "cancelled",
        detail_href=item.detail_href,
        date_label=date_label(local.date()),
        tags=list(item.tags),
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
) -> PostOptionVM:
    a_label, a_tone = approval_label(approval)
    return PostOptionVM(
        post_id=post_id,
        title=title,
        caption_excerpt=caption_excerpt,
        thumbnail_url=thumbnail_url or "",
        category_label=category_label(category),
        approval_label=a_label,
        approval_tone=a_tone,
        detail_href=detail_href,
    )
