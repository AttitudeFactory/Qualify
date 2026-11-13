"""The seasons calendar per country, and the three-week notice in «Tu semana»
(m-24976896). Spec: `docs/ux-stickers-videos.md` §4; list: `docs/temporadas-por-pais.md`.

The calendar is DATA here, not a table: each season is a slug, a Spanish name and a rule
that gives its date in a year (a fixed day, «the 2nd Sunday of May», Carnival from
Easter). A season of a year has the library's key `{slug}-{year}` (`navidad-2026`,
`SEASON_KEY_RE` of `qualify_shared.objects.keys`) and label `{name} {year}` (≤ 24).
«Otra ocasión» (free text) is not here: `SeasonalMediaService.plan_batch` takes any
slug + label, as before.

The business's country is the tenant's (`tenancy.locale.read_business_locale`); an
unknown country falls back to the shared list (`SHARED`).

## The notice (`season_notice`)

At most ONE item: the nearest season of the country inside its own lead
(`notice_days`: 42 for Navidad, 21 for the rest; in the business's own timezone), for
which the business has no batch (no row of that `season_key` in an unarchived season)
and that the owner has not dismissed («Ahora no»).
Its identity is the `season_key`, so it is shown once per season per business; it goes
away by itself when a batch exists or the date passes. It lives only in the app: nothing
here sends a WhatsApp message or an email.

«Ahora no» is stored without a table: the season keys go in ONE reserved key of the
brand's `connect` details document (`brand_kit_details.connect.season_notices_dismissed`,
read and written under ONE lock of the details row, carried across the
wizards' saves by `RESERVED_DETAIL_KEYS`), trimmed to the last `MAX_DISMISSED` keys.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final, Protocol
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_shared.objects.keys import SEASON_KEY_RE

#: How many days before its date a season's notice shows (product call 2026-11-08:
#: Navidad 42, the rest 21) — `SeasonRule.notice_days`.
NOTICE_DAYS: Final = 21
NAVIDAD_NOTICE_DAYS: Final = 42
#: The library's label limit (`seasonal.MAX_LABEL_CHARS`).
MAX_LABEL: Final = 24
MAX_DISMISSED: Final = 24
DISMISSED_DOCUMENT: Final = "connect"
DISMISSED_KEY: Final = "season_notices_dismissed"
#: The «Tu marca» section that holds the library; the flow opens on the chosen season.
BRAND_ROUTE: Final = "/brand/kit"
NOTICE_TEXT: Final = "{name} está cerca: crea tus stickers y videos."
NOTICE_ACTION: Final = "Crear para {name}"
NOTICE_DISMISS: Final = "Ahora no"

_SUN, _SAT = 6, 5


# ======================================================================================
# Date rules
# ======================================================================================


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The `n`-th `weekday` (Monday 0 … Sunday 6) of `month`."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


@dataclass(frozen=True)
class SeasonRule:
    slug: str
    name: str  # Spanish, as the owner reads it
    on: Callable[[int], date]
    rule: str  # the rule in words, for the docs table
    notice_days: int = NOTICE_DAYS


def _fixed(month: int, day: int) -> Callable[[int], date]:
    return lambda year: date(year, month, day)


def _nth(month: int, weekday: int, n: int) -> Callable[[int], date]:
    return lambda year: nth_weekday(year, month, weekday, n)


NAVIDAD = SeasonRule(
    "navidad", "Navidad", _fixed(12, 25), "25 de diciembre", notice_days=NAVIDAD_NOTICE_DAYS
)
ANO_NUEVO = SeasonRule("ano-nuevo", "Año Nuevo", _fixed(1, 1), "1 de enero")
SAN_VALENTIN = SeasonRule("san-valentin", "San Valentín", _fixed(2, 14), "14 de febrero")
AMOR_Y_AMISTAD = SeasonRule(
    "amor-y-amistad", "Amor y Amistad", _nth(9, _SAT, 3), "tercer sábado de septiembre"
)
MADRE = SeasonRule(
    "dia-de-la-madre", "Día de la Madre", _nth(5, _SUN, 2), "segundo domingo de mayo"
)
PADRE_JUNIO = SeasonRule(
    "dia-del-padre", "Día del Padre", _nth(6, _SUN, 3), "tercer domingo de junio"
)
PADRE_JULIO = SeasonRule(
    "dia-del-padre", "Día del Padre", _nth(7, _SUN, 2), "segundo domingo de julio"
)
BRUJAS = SeasonRule("noche-de-brujas", "Noche de brujas", _fixed(10, 31), "31 de octubre")
CARNAVAL = SeasonRule(
    "carnaval",
    "Carnaval",
    lambda year: easter(year) - timedelta(days=48),
    "lunes de Carnaval (48 días antes de Pascua)",
)

#: The list for a country we do not know.
SHARED: Final[tuple[SeasonRule, ...]] = (
    ANO_NUEVO,
    SAN_VALENTIN,
    MADRE,
    PADRE_JUNIO,
    BRUJAS,
    NAVIDAD,
)
CALENDARS: Final[dict[str, tuple[SeasonRule, ...]]] = {
    "CO": (ANO_NUEVO, MADRE, PADRE_JUNIO, AMOR_Y_AMISTAD, BRUJAS, NAVIDAD),
    "VE": (ANO_NUEVO, CARNAVAL, SAN_VALENTIN, MADRE, PADRE_JUNIO, BRUJAS, NAVIDAD),
    "UY": (ANO_NUEVO, CARNAVAL, SAN_VALENTIN, MADRE, PADRE_JULIO, BRUJAS, NAVIDAD),
}


def rules_for(country: str | None) -> tuple[SeasonRule, ...]:
    return CALENDARS.get((country or "").strip().upper(), SHARED)


# ======================================================================================
# Seasons of a year
# ======================================================================================


@dataclass(frozen=True)
class CalendarSeason:
    """One season of one year, keyed like the library (`season_key`, `season_label`)."""

    season_key: str  # «navidad-2026»
    season_label: str  # «Navidad 2026»
    name: str  # «Navidad»
    slug: str
    day: date
    notice_days: int = NOTICE_DAYS


def _season(rule: SeasonRule, year: int) -> CalendarSeason:
    return CalendarSeason(
        season_key=f"{rule.slug}-{year}",
        season_label=f"{rule.name} {year}",
        name=rule.name,
        slug=rule.slug,
        day=rule.on(year),
        notice_days=rule.notice_days,
    )


def seasons_of_year(country: str | None, year: int) -> list[CalendarSeason]:
    return sorted((_season(r, year) for r in rules_for(country)), key=lambda s: s.day)


def next_seasons(country: str | None, today: date, n: int = 3) -> list[CalendarSeason]:
    """The next `n` seasons from `today` (today's included), across the year boundary."""
    upcoming = [
        s
        for year in (today.year, today.year + 1)
        for s in seasons_of_year(country, year)
        if s.day >= today
    ]
    return upcoming[:n]


def season_for_key(key: str, country: str | None = None) -> CalendarSeason | None:
    """The calendar season of a library key (`navidad-2026`), or None (a free-text
    «otra ocasión», another country's season, or not a key)."""
    if not SEASON_KEY_RE.fullmatch(key or ""):
        return None
    slug, _, year = key.rpartition("-")
    if not year.isdigit() or len(year) != 4:
        return None
    for rule in rules_for(country):
        if rule.slug == slug:
            return _season(rule, int(year))
    return None


def days_until(season: CalendarSeason, today: date) -> int:
    return (season.day - today).days


def weeks_until(season: CalendarSeason, today: date) -> int:
    """Whole weeks left, rounded up (21 days → 3, 15 → 3, 1 → 1, the day itself → 0)."""
    return max(0, -(-days_until(season, today) // 7))


# ======================================================================================
# The notice
# ======================================================================================


@dataclass(frozen=True)
class SeasonNotice:
    season_key: str
    season_label: str
    text: str  # «Navidad está cerca: crea tus stickers y videos.»
    action_label: str  # «Crear para Navidad»
    action_href: str  # «/brand/kit?crear=temporada&temporada=navidad-2026»
    dismiss_label: str  # «Ahora no»
    days_until: int
    notice_days: int  # the season's lead: 42 for Navidad, 21 for the rest


def season_notice(
    country: str | None,
    today: date,
    *,
    with_batch: Iterable[str],
    dismissed: Iterable[str],
) -> SeasonNotice | None:
    """Pure: the nearest season inside its own lead (0–`notice_days` days away) without
    a batch and not dismissed, or None."""
    skip = set(with_batch) | set(dismissed)
    for season in _in_window(country, today):
        if season.season_key in skip:
            continue
        days = days_until(season, today)
        return SeasonNotice(
            season_key=season.season_key,
            season_label=season.season_label,
            text=NOTICE_TEXT.format(name=season.name),
            action_label=NOTICE_ACTION.format(name=season.name),
            action_href=f"{BRAND_ROUTE}?"
            + urlencode({"crear": "temporada", "temporada": season.season_key}),
            dismiss_label=NOTICE_DISMISS,
            days_until=days,
            notice_days=season.notice_days,
        )
    return None


def _in_window(country: str | None, today: date) -> list[CalendarSeason]:
    """The upcoming seasons inside their own lead, nearest first."""
    return [
        s
        for s in next_seasons(country, today, n=len(rules_for(country)))
        if days_until(s, today) <= s.notice_days
    ]


class DismissedStore(Protocol):
    def dismissed(self, tenant_id: UUID, brand_id: UUID) -> list[str]: ...

    def dismiss(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> None: ...


class MemoryDismissedStore:
    def __init__(self) -> None:
        self.keys: dict[tuple[UUID, UUID], list[str]] = {}

    def dismissed(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        return list(self.keys.get((tenant_id, brand_id), []))

    def dismiss(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> None:
        self.keys[(tenant_id, brand_id)] = _add_key(
            self.keys.get((tenant_id, brand_id), []), season_key
        )


def _add_key(current: Iterable[str], season_key: str) -> list[str]:
    keys = [k for k in current if isinstance(k, str) and k != season_key]
    return [*keys, season_key][-MAX_DISMISSED:]


class BrandDetailsDismissedStore:
    """`brand_kit_details.connect.season_notices_dismissed` (module docstring)."""

    def dismissed(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        from qualify_api.creative.brand_kit_store import BrandKitStore  # noqa: PLC0415

        connect = BrandKitStore().load_details(tenant_id=tenant_id, brand_id=brand_id).connect
        value = (connect or {}).get(DISMISSED_KEY)
        return [k for k in value if isinstance(k, str)] if isinstance(value, list) else []

    def dismiss(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> None:
        """Read and write the list under ONE row lock: two «Ahora no» at once both stay
        (the same lock `BrandKitStore.save_details` / `set_document_key` take)."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.creative.models import BrandKitDetails as DetailsRow  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.get(DetailsRow, brand_id, with_for_update=True)
            if row is None:
                row = DetailsRow(
                    brand_id=brand_id,
                    tenant_id=tenant_id,
                    logo_brief={},
                    connect={},
                    profile={},
                )
                session.add(row)
            connect = dict(row.connect or {})
            stored = connect.get(DISMISSED_KEY)
            current = stored if isinstance(stored, list) else []
            row.connect = {**connect, DISMISSED_KEY: _add_key(current, season_key)}
            row.updated_at = datetime.now(UTC)
            session.flush()


@dataclass(frozen=True)
class BusinessPlace:
    country: str | None
    timezone: str | None


def _today(place: BusinessPlace, now: datetime) -> date:
    try:
        return now.astimezone(ZoneInfo(place.timezone or "UTC")).date()
    except Exception:  # noqa: BLE001 — an unknown zone reads as UTC
        return now.astimezone(UTC).date()


class SeasonCalendarService:
    """The calendar and the notice for one business.

    - `place(tenant_id)` → its country and timezone (`read_business_locale`);
    - `batch_keys(tenant_id, brand_id)` → the `season_key`s with an unarchived batch
      (`SeasonalMediaService.list_seasons`)."""

    def __init__(
        self,
        place: Callable[[UUID], BusinessPlace],
        batch_keys: Callable[[UUID, UUID], Iterable[str]],
        dismissed: DismissedStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._place = place
        self._batch_keys = batch_keys
        self._dismissed = dismissed
        self._clock = clock

    def today(self, tenant_id: UUID) -> date:
        return _today(self._place(tenant_id), self._clock())

    def upcoming(self, tenant_id: UUID, n: int = 3) -> list[CalendarSeason]:
        """What step 1 «¿Para qué ocasión?» offers: the next `n` dated seasons."""
        place = self._place(tenant_id)
        return next_seasons(place.country, _today(place, self._clock()), n)

    def notice(
        self, tenant_id: UUID, brand_id: UUID, *, today: date | None = None
    ) -> SeasonNotice | None:
        """The «Tu semana» item, or None. `today` overrides the business's day (tests,
        previews); the clock is injectable too. Cheap first: no library read when no
        season is inside its lead."""
        place = self._place(tenant_id)
        today = today or _today(place, self._clock())
        if not _in_window(place.country, today):
            return None
        return season_notice(
            place.country,
            today,
            with_batch=self._batch_keys(tenant_id, brand_id),
            dismissed=self._dismissed.dismissed(tenant_id, brand_id),
        )

    def dismiss(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> None:
        """«Ahora no»: that season's notice does not come back for this business."""
        if not SEASON_KEY_RE.fullmatch(season_key or ""):
            raise ValueError("not a season key")
        self._dismissed.dismiss(tenant_id, brand_id, season_key)


def production_season_calendar() -> SeasonCalendarService:
    from qualify_api.tenancy.locale import read_business_locale  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import production_seasonal_service  # noqa: PLC0415

    library = production_seasonal_service()

    def place(tenant_id: UUID) -> BusinessPlace:
        found = read_business_locale(tenant_id)
        if found is None:
            return BusinessPlace(country=None, timezone=None)
        return BusinessPlace(country=found.country, timezone=found.timezone)

    def batch_keys(tenant_id: UUID, brand_id: UUID) -> list[str]:
        return [s.season_key for s in library.list_seasons(tenant_id, brand_id) if not s.archived]

    return SeasonCalendarService(place, batch_keys, BrandDetailsDismissedStore())


__all__ = [
    "CALENDARS",
    "MAX_LABEL",
    "NAVIDAD_NOTICE_DAYS",
    "NOTICE_DAYS",
    "SHARED",
    "BrandDetailsDismissedStore",
    "BusinessPlace",
    "CalendarSeason",
    "MemoryDismissedStore",
    "SeasonCalendarService",
    "SeasonNotice",
    "SeasonRule",
    "days_until",
    "easter",
    "next_seasons",
    "nth_weekday",
    "production_season_calendar",
    "season_for_key",
    "season_notice",
    "seasons_of_year",
    "weeks_until",
]
