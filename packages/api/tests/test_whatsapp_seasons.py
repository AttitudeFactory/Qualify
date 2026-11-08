"""m-24976896 — the seasons calendar per country and the «Tu semana» notice, offline:
each country's rules around the year boundary, keys the library accepts, the notice
appearing 21 days before and going away (batch, dismissal, date passed), the business's
own timezone, and «Ahora no» kept across the wizards' saves (reserved key)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from qualify_shared.objects.keys import SEASON_KEY_RE

from qualify_api.creative.brand_kit_store import carry_reserved
from qualify_api.whatsapp.seasonal import (
    MemorySeasonalRepository,
    MemorySourceReads,
    SeasonalMediaService,
)
from qualify_api.whatsapp.seasons import (
    CALENDARS,
    MAX_LABEL,
    SHARED,
    BusinessPlace,
    MemoryDismissedStore,
    SeasonCalendarService,
    easter,
    next_seasons,
    season_for_key,
    season_notice,
    seasons_of_year,
    weeks_until,
)

TENANT = UUID("a0000000-0000-4000-8000-000000976896")
BRAND = UUID("c0000000-0000-4000-8000-000000976896")
USER = UUID("e0000000-0000-4000-8000-000000976896")


def _days(country: str | None, year: int) -> dict[str, date]:
    return {s.slug: s.day for s in seasons_of_year(country, year)}


def test_each_country_has_its_own_dates() -> None:
    co, ve, uy = _days("CO", 2026), _days("VE", 2026), _days("UY", 2026)
    assert co["dia-de-la-madre"] == ve["dia-de-la-madre"] == date(2026, 5, 10)
    assert co["dia-del-padre"] == ve["dia-del-padre"] == date(2026, 6, 21)
    assert uy["dia-del-padre"] == date(2026, 7, 12)
    assert co["amor-y-amistad"] == date(2026, 9, 19) and "san-valentin" not in co
    assert ve["san-valentin"] == uy["san-valentin"] == date(2026, 2, 14)
    assert ve["carnaval"] == uy["carnaval"] == date(2026, 2, 16) and "carnaval" not in co
    assert co["noche-de-brujas"] == date(2026, 10, 31)
    assert _days("AR", 2026).keys() == {r.slug for r in SHARED}


def test_easter_and_carnival_follow_the_moon() -> None:
    assert [easter(y) for y in (2025, 2026, 2027)] == [
        date(2025, 4, 20),
        date(2026, 4, 5),
        date(2027, 3, 28),
    ]
    assert _days("UY", 2027)["carnaval"] == date(2027, 2, 8)


@pytest.mark.parametrize("country", ["CO", "VE", "UY", None])
def test_next_seasons_cross_the_year_boundary(country: str | None) -> None:
    upcoming = next_seasons(country, date(2026, 12, 20), n=3)
    assert [s.season_key for s in upcoming[:2]] == ["navidad-2026", "ano-nuevo-2027"]
    assert upcoming[2].day.year == 2027
    assert next_seasons(country, date(2026, 12, 25), n=1)[0].season_key == "navidad-2026"
    assert next_seasons(country, date(2026, 12, 26), n=1)[0].season_key == "ano-nuevo-2027"


@pytest.mark.parametrize("country", [*CALENDARS, None])
def test_keys_and_labels_fit_the_library(country: str | None) -> None:
    for year in (2026, 2027, 2099):
        for season in seasons_of_year(country, year):
            assert SEASON_KEY_RE.fullmatch(season.season_key)
            assert len(season.season_label) <= MAX_LABEL
            assert "Halloween" not in season.season_label
            assert season_for_key(season.season_key, country) == season


def test_a_free_text_occasion_is_not_a_calendar_season() -> None:
    assert season_for_key("aniversario-del-local") is None
    assert season_for_key("navidad") is None
    assert season_for_key("carnaval-2027", "CO") is None  # not Colombia's
    assert season_for_key("Navidad-2026") is None


def test_weeks_until_rounds_up() -> None:
    navidad = season_for_key("navidad-2026")
    assert navidad is not None
    assert [weeks_until(navidad, date(2026, 12, d)) for d in (4, 10, 24, 25, 26)] == [
        3,
        3,
        1,
        0,
        0,
    ]


# --- the notice ---------------------------------------------------------------------------


def test_the_notice_shows_21_days_before_and_not_22() -> None:
    assert season_notice("CO", date(2026, 12, 3), with_batch=(), dismissed=()) is None
    notice = season_notice("CO", date(2026, 12, 4), with_batch=(), dismissed=())
    assert notice is not None and notice.season_key == "navidad-2026"
    assert notice.text == "Navidad está cerca: crea tus stickers y videos."
    assert notice.action_label == "Crear para Navidad"
    assert notice.action_href == "/brand/kit?crear=temporada&temporada=navidad-2026"
    assert (notice.dismiss_label, notice.days_until) == ("Ahora no", 21)


def test_a_batch_or_a_dismissal_moves_to_the_next_near_season_or_none() -> None:
    today = date(2026, 12, 20)
    assert season_notice("VE", today, with_batch=(), dismissed=()).season_key == "navidad-2026"
    after = season_notice("VE", today, with_batch=["navidad-2026"], dismissed=())
    assert after is not None and after.season_key == "ano-nuevo-2027"
    gone = season_notice("VE", today, with_batch=["navidad-2026"], dismissed=["ano-nuevo-2027"])
    assert gone is None


class World:
    def __init__(self, country: str | None = "CO", tz: str = "America/Bogota") -> None:
        self.now = datetime(2026, 12, 4, 12, 0, tzinfo=UTC)
        self.repo = MemorySeasonalRepository()
        sources = MemorySourceReads()
        sources.logos[(TENANT, BRAND)] = f"t/{TENANT}/brand/{BRAND}/logo.png"
        self.library = SeasonalMediaService(self.repo, sources)
        self.dismissed = MemoryDismissedStore()
        self.reads = 0

        def batch_keys(tenant_id: UUID, brand_id: UUID) -> list[str]:
            self.reads += 1
            return [
                s.season_key
                for s in self.library.list_seasons(tenant_id, brand_id)
                if not s.archived
            ]

        self.service = SeasonCalendarService(
            lambda _t: BusinessPlace(country=country, timezone=tz),
            batch_keys,
            self.dismissed,
            clock=lambda: self.now,
        )


def test_the_service_hides_the_notice_once_a_batch_exists_and_shows_it_if_archived() -> None:
    world = World()
    assert world.service.notice(TENANT, BRAND).season_key == "navidad-2026"
    world.library.plan_batch(TENANT, BRAND, "navidad-2026", "Navidad 2026", "free", USER)
    assert world.service.notice(TENANT, BRAND) is None
    world.library.archive(TENANT, BRAND, "navidad-2026")
    assert world.service.notice(TENANT, BRAND).season_key == "navidad-2026"


def test_ahora_no_is_once_per_season_and_idempotent() -> None:
    world = World()
    world.service.dismiss(TENANT, BRAND, "navidad-2026")
    world.service.dismiss(TENANT, BRAND, "navidad-2026")
    assert world.dismissed.dismissed(TENANT, BRAND) == ["navidad-2026"]
    assert world.service.notice(TENANT, BRAND) is None
    with pytest.raises(ValueError):
        world.service.dismiss(TENANT, BRAND, "Navidad!")


def test_far_from_any_season_the_library_is_not_read() -> None:
    world = World()
    world.now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assert world.service.notice(TENANT, BRAND) is None and world.reads == 0


def test_today_is_the_businesss_day_not_utcs() -> None:
    world = World(tz="America/Bogota")
    world.now = datetime(2026, 12, 4, 3, 0, tzinfo=UTC)  # still Dec 3 in Bogotá
    assert world.service.today(TENANT) == date(2026, 12, 3)
    assert world.service.notice(TENANT, BRAND) is None
    assert [s.season_key for s in world.service.upcoming(TENANT)] == [
        "navidad-2026",
        "ano-nuevo-2027",
        "dia-de-la-madre-2027",
    ]


def test_the_dismissed_list_survives_a_wizard_save() -> None:
    stored = {"city": "Bogotá", "season_notices_dismissed": ["navidad-2026"]}
    written = carry_reserved("connect", stored, {"city": "Cúcuta"})
    assert written["season_notices_dismissed"] == ["navidad-2026"]
