"""m-24976896 — «{Temporada} está cerca: crea tus stickers y videos» in «Tu semana»:
the production provider maps the backend's `SeasonNotice` (one read per week load), a
failed read only hides it, and «Ahora no» hides it at once and tells the backend."""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID

import pytest
from qualify_api.whatsapp import seasons
from qualify_api.whatsapp.seasons import SeasonNotice

from . import planner_provider
from .planner_state import PlannerState
from .planner_vm import EMPTY_SEASON_NOTICE, SeasonNoticeVM

TENANT = UUID("a0000000-0000-4000-8000-000000976898")
BRAND = UUID("c0000000-0000-4000-8000-000000976898")

NOTICE = SeasonNotice(
    season_key="navidad-2026",
    season_label="Navidad 2026",
    text="Navidad está cerca: crea tus stickers y videos.",
    action_label="Crear para Navidad",
    action_href="/brand/kit?crear=temporada&temporada=navidad-2026",
    dismiss_label="Ahora no",
    days_until=12,
)


class FakeCalendar:
    def __init__(self, found: Any = NOTICE, fail: bool = False) -> None:
        self.found, self.fail = found, fail
        self.calls: list[tuple[Any, ...]] = []

    def notice(self, tenant_id: UUID, brand_id: UUID) -> Any:
        self.calls.append(("notice", tenant_id, brand_id))
        if self.fail:
            raise RuntimeError("db down")
        return self.found

    def dismiss(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> None:
        self.calls.append(("dismiss", tenant_id, brand_id, season_key))


def test_the_production_provider_maps_the_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCalendar()
    monkeypatch.setattr(seasons, "production_season_calendar", lambda: fake)
    vm = planner_provider.season_notice(TENANT, BRAND)
    assert vm == SeasonNoticeVM(
        season_key="navidad-2026",
        text="Navidad está cerca: crea tus stickers y videos.",
        action_label="Crear para Navidad",
        action_href="/brand/kit?crear=temporada&temporada=navidad-2026",
        dismiss_label="Ahora no",
    )
    fake.found = None
    assert planner_provider.season_notice(TENANT, BRAND) == EMPTY_SEASON_NOTICE
    fake.fail = True
    assert planner_provider.season_notice(TENANT, BRAND) == EMPTY_SEASON_NOTICE  # hidden


def test_one_read_per_week_load() -> None:
    body = inspect.getsource(planner_provider.load_week)
    assert body.count("season_notice(tenant_id, brand_id)") == 1


async def test_ahora_no_hides_it_and_tells_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCalendar()
    monkeypatch.setattr(seasons, "production_season_calendar", lambda: fake)
    monkeypatch.setattr(planner_provider, "_require_brand", lambda _t: BRAND)

    async def tenant(self: PlannerState) -> UUID:
        return TENANT

    monkeypatch.setattr(PlannerState, "_tenant", tenant)
    state = PlannerState()
    state.season_notice = planner_provider.season_notice(TENANT, BRAND)
    await PlannerState.dismiss_season_notice.fn(state)
    assert state.season_notice == EMPTY_SEASON_NOTICE
    assert fake.calls[-1] == ("dismiss", TENANT, BRAND, "navidad-2026")


def test_the_week_draws_it() -> None:
    from .planner_page import _season_notice

    rendered = str(_season_notice())
    assert "dismiss_season_notice" in rendered and "action_href" in rendered
