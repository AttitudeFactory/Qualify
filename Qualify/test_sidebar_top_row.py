"""m-24976899 — the sidebar's top row, alternative B «El logo abre y cierra».

Offline: the copy and helpers of `business_vm`, the AuthState vars the row reads, and
the business logo refresh with the provider replaced by a fake (no database, no R2).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from . import business_logo_provider
from . import business_vm as vm
from .auth_state import AuthState, reload_business_logo

BIANKI = "a0000000-0000-4000-8000-00000000000b"
POLETTE = "a0000000-0000-4000-8000-00000000000c"


# -- copy -----------------------------------------------------------------------------------


def test_toggle_labels_and_tooltips_carry_the_shortcut() -> None:
    assert vm.COLLAPSE_LABEL == "Contraer el menú"
    assert vm.EXPAND_LABEL == "Expandir el menú"
    assert vm.CLOSE_DRAWER_LABEL == "Cerrar el menú"
    assert vm.rail_toggle_title(vm.COLLAPSE_LABEL) == "Contraer el menú (⌘ .)"
    assert vm.rail_toggle_title(vm.EXPAND_LABEL) == "Expandir el menú (⌘ .)"


def test_credit_line_conveys_trust() -> None:
    assert vm.CREDIT_LABEL == "Con el respaldo de"
    assert vm.credit_aria().startswith("Con el respaldo de Qualify")
    assert vm.HERE_LABEL == "Aquí estás"


def test_trigger_label_is_the_name_or_opening() -> None:
    assert vm.trigger_label("Bianki") == "Bianki"
    assert vm.trigger_label("Bianki", "Polette") == "Abriendo Polette…"


def test_trigger_aria_names_the_business_and_the_action() -> None:
    assert vm.switch_trigger_aria("Bianki") == "Estás en Bianki. Cambiar de negocio"
    assert vm.switch_trigger_aria("Bianki", "Polette") == "Abriendo Polette…. Cambiar de negocio"


# -- the menu -------------------------------------------------------------------------------


def test_menu_lists_every_business_and_flags_the_open_one() -> None:
    assert vm.business_menu(["Bianki", "Polette"], 1) == [
        {"index": "0", "name": "Bianki", "current": ""},
        {"index": "1", "name": "Polette", "current": "1"},
    ]


def test_menu_never_carries_a_tenant_id() -> None:
    for row in vm.business_menu(["Bianki", "Polette"], 0):
        assert set(row) == {"index", "name", "current"}


def test_single_business_is_not_switchable() -> None:
    state = AuthState()
    state.session_tenant_id = BIANKI
    state.business_name = "Bianki"
    state.business_names = ["Bianki"]
    state.active_business_index = 0
    assert state.can_switch_business is False
    assert state.business_trigger_label == "Bianki"


def test_multi_business_state_vars() -> None:
    state = AuthState()
    state.session_tenant_id = BIANKI
    state.business_name = "Bianki"
    state.business_names = ["Bianki", "Polette"]
    state.active_business_index = 0
    assert state.can_switch_business is True
    assert state.business_trigger_aria == "Estás en Bianki. Cambiar de negocio"
    assert [row["current"] for row in state.business_menu] == ["1", ""]
    state.opening_business = "Polette"
    assert state.business_trigger_label == "Abriendo Polette…"


# -- logo freshness -------------------------------------------------------------------------


def test_logo_is_read_for_a_new_business_or_when_stale() -> None:
    now = 10_000.0
    fresh = now - 60
    old = now - vm.LOGO_FRESH_SECONDS
    kw = {"tenant": BIANKI, "now": now}
    assert vm.logo_needs_refresh(logo_tenant="", fetched_at=0, **kw) is True
    assert vm.logo_needs_refresh(logo_tenant=POLETTE, fetched_at=fresh, **kw) is True
    assert vm.logo_needs_refresh(logo_tenant=BIANKI, fetched_at=0, **kw) is True
    assert vm.logo_needs_refresh(logo_tenant=BIANKI, fetched_at=old, **kw) is True
    assert vm.logo_needs_refresh(logo_tenant=BIANKI, fetched_at=fresh, **kw) is False


def test_no_session_never_reads_a_logo() -> None:
    assert vm.logo_needs_refresh(tenant="", logo_tenant="", fetched_at=0, now=1) is False


@pytest.fixture
def logo_reads(monkeypatch) -> list[UUID]:
    reads: list[UUID] = []

    def fake(tenant_id: UUID) -> str:
        reads.append(tenant_id)
        return f"/r2media/tok-{str(tenant_id)[-1]}"

    monkeypatch.setattr(business_logo_provider, "business_logo_path", fake)
    return reads


async def test_refresh_reads_once_then_reuses(logo_reads) -> None:
    state = AuthState()
    state.session_tenant_id = BIANKI
    await reload_business_logo(state)
    assert state.business_logo_src == "/r2media/tok-b"
    await reload_business_logo(state)  # fresh: nothing read again
    assert logo_reads == [UUID(BIANKI)]
    await reload_business_logo(state, stale=True)  # Tu marca saved
    assert logo_reads == [UUID(BIANKI), UUID(BIANKI)]


async def test_refresh_without_logo_falls_back_to_the_store_icon(monkeypatch) -> None:
    monkeypatch.setattr(business_logo_provider, "business_logo_path", lambda t: "")
    state = AuthState()
    state.session_tenant_id = BIANKI
    state.business_logo_src = "/r2media/old"
    state._logo_tenant = POLETTE
    await reload_business_logo(state)
    assert state.business_logo_src == ""


async def test_refresh_without_session_clears(logo_reads) -> None:
    state = AuthState()
    state.business_logo_src = "/r2media/tok-b"
    await reload_business_logo(state)
    assert state.business_logo_src == ""
    assert logo_reads == []


async def test_refresh_survives_a_database_error(monkeypatch) -> None:
    from sqlalchemy.exc import OperationalError

    def broken(tenant_id: UUID) -> str:
        raise OperationalError("select", {}, Exception("down"))

    monkeypatch.setattr(business_logo_provider, "business_logo_path", broken)
    state = AuthState()
    state.session_tenant_id = BIANKI
    await reload_business_logo(state)
    assert state.business_logo_src == ""


async def test_entering_another_business_drops_the_old_logo() -> None:
    state = AuthState()
    state.session_tenant_id = BIANKI
    state.business_logo_src = "/r2media/tok-b"
    state._logo_fetched_at = 123.0
    await state._enter_business(
        tenant_id=POLETTE,
        business_name="Polette",
        email="dueno@b.co",
        user_id="u",
        kit_complete=True,
    )
    assert state.business_logo_src == ""
    assert state._logo_fetched_at == 0.0
