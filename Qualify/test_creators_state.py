"""Creadores' states (m-24946129, m-24946132) — `creators_state.py`.

No DB and no vendor: the backend facade (`qualify_api.creators.service`, design §10) is
replaced by an in-memory twin through `creators_provider._service`, and the session
lookup by `_session_ids`. Background handlers are driven through `.fn(state)` (the way
`test_catalog_state.py` does).

Pins:
1. Opening a screen never pays: the list, the sheet and Comparar read; only a button
   («Ver cómo le va», «Actualizar», «Intentar de nuevo») calls `refresh_creator`.
2. «Ver cómo le va»: save (free) then read (paid) once; success closes the drawer into
   the sheet (N3); a typo or a private account is taken back off the list and the
   drawer says what to do, keeping what was typed.
3. A creator already in the list is not read again: «Ya revisaste a @x hace N días».
4. «Elige de 2 a 4»: a fifth is refused in words; only creators with a read can be
   picked; «Comparar» goes to `/creadores/comparar?ids=…`.
5. Comparar refuses fewer than 2 (or more than 4) and sends the owner back to the list.
6. The switch off → nothing is listed (the page shows «Pronto»).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creators.metrics import (
    CompareEntry,
    MetricValue,
    ReelRead,
    SnapshotFacts,
    build_sheet,
    compare,
)

from . import creators_provider, creators_state
from .creators_state import CreatorsCompareState, CreatorSheetState, CreatorsState
from .creators_vm import COMPARE_INVALID, INVALID_HANDLE, PICK_LIMIT, compare_url

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
BRAND = UUID("b0000000-0000-4000-8000-000000000001")
USER = UUID("c0000000-0000-4000-8000-000000000001")
NOW = datetime.now(UTC)


class CreatorsDisabled(Exception):
    pass


class InvalidHandle(ValueError):
    pass


class UnsupportedNetwork(ValueError):
    pass


class TooManyToCompare(ValueError):
    pass


class CreatorNotFound(LookupError):
    pass


@dataclass
class Tracked:
    id: UUID
    handle: str
    refresh_state: str = "never"
    refresh_error: str | None = None
    last_snapshot_id: UUID | None = None
    status: str = "active"
    created_at: datetime = NOW


def _reels(base: int) -> list[ReelRead]:
    return [
        ReelRead(
            reel_id=f"r{i}",
            url=f"https://www.instagram.com/reel/r{i}/",
            taken_at=NOW - timedelta(days=4 + 3 * i),
            duration_s=20.0,
            views=base + i * 10,
            likes=40,
            comments=2,
            counts_hidden=False,
            is_paid_partnership=False,
            coauthors=(),
            sound_id="s",
            sound_title="Audio original",
            sound_is_original=True,
        )
        for i in range(10)
    ]


@dataclass
class FakeService:
    """The §10.2 facade, in memory. `outcome` is what the next refresh answers."""

    enabled: bool = True
    outcome: str = "read"
    tracked: dict[UUID, Tracked] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    refreshed: list[UUID] = field(default_factory=list)
    archived: list[UUID] = field(default_factory=list)
    stale: set[str] = field(default_factory=set)

    CreatorsDisabled = CreatorsDisabled
    InvalidHandle = InvalidHandle
    UnsupportedNetwork = UnsupportedNetwork
    TooManyToCompare = TooManyToCompare
    CreatorNotFound = CreatorNotFound

    def _require(self) -> None:
        if not self.enabled:
            raise CreatorsDisabled()

    def creators_enabled(self, tenant_id: UUID) -> bool:
        return self.enabled

    def refresh_stuck(self, tracked: Tracked, now: datetime) -> bool:
        return tracked.refresh_state == "reading" and tracked.handle.startswith("stuck")

    def seed(self, handle: str, *, read: bool = True) -> Tracked:
        tracked = Tracked(
            id=uuid4(),
            handle=handle,
            refresh_state="ok" if read else "never",
            last_snapshot_id=uuid4() if read else None,
        )
        self.tracked[tracked.id] = tracked
        return tracked

    def _snapshot(self, t: Tracked) -> SnapshotFacts:
        return SnapshotFacts(
            snapshot_id=t.last_snapshot_id or uuid4(),
            network="instagram",
            handle=t.handle,
            read_at=NOW - timedelta(days=20 if t.handle in self.stale else 1),
            status="ok",
            followers=5000,
            full_name=t.handle.title(),
            reels_read=10,
        )

    def add_creator(self, tenant_id, brand_id, handle, *, user_id, **_kw) -> Tracked:
        self._require()
        self.calls.append("add")
        clean = handle.strip().lstrip("@").lower()
        if not clean or " " in clean:
            raise InvalidHandle()
        for t in self.tracked.values():
            if t.handle == clean:
                t.status = "active"
                return t
        return self.seed(clean, read=False)

    def list_creators(self, tenant_id, brand_id, *, now=None, **_kw):
        self._require()
        self.calls.append("list")
        out = []
        for t in self.tracked.values():
            if t.status != "active":
                continue
            read = t.last_snapshot_id is not None
            out.append(
                SimpleNamespace(
                    tracked=t,
                    full_name=t.handle.title() if read else "",
                    avatar_url="",
                    followers=5000 if read else None,
                    median_views=MetricValue(
                        "median_views", 1000 if read else None, "ok" if read else "unknown", 10
                    ),
                    engagement_rate=MetricValue("engagement_rate", 0.04, "ok", 10),
                    read_at=NOW - timedelta(days=1) if read else None,
                    stale=False,
                )
            )
        return out

    def archive_creator(self, tenant_id, brand_id, tracked_id) -> None:
        self._require()
        self.archived.append(tracked_id)
        self.tracked[tracked_id].status = "archived"

    def refresh_creator(self, tenant_id, brand_id, tracked_id, **_kw):
        self._require()
        self.refreshed.append(tracked_id)
        t = self.tracked[tracked_id]
        if self.outcome in ("read", "fresh"):
            t.last_snapshot_id = uuid4()
            t.refresh_state = "ok"
        else:
            t.refresh_state, t.refresh_error = "failed", self.outcome
        return SimpleNamespace(
            status=self.outcome, snapshot_id=t.last_snapshot_id, credits=5, partial=False
        )

    def creator_sheet(self, tenant_id, brand_id, tracked_id, *, now=None):
        self._require()
        self.calls.append("sheet")
        t = self.tracked.get(tracked_id)
        if t is None:
            raise CreatorNotFound()
        if t.last_snapshot_id is None:
            return None
        return build_sheet(t.id, self._snapshot(t), _reels(1000), now=NOW)

    def compare_creators(self, tenant_id, brand_id, tracked_ids, *, now=None):
        self._require()
        self.calls.append("compare")
        ids = list(dict.fromkeys(tracked_ids))
        if not 2 <= len(ids) <= 4:
            raise TooManyToCompare()
        entries = [
            CompareEntry(i, self._snapshot(self.tracked[i]), _reels(1000 * (n + 1)))
            for n, i in enumerate(ids)
        ]
        return compare(entries, now=NOW)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    fake = FakeService()
    monkeypatch.setattr(creators_provider, "_service", lambda: fake)
    monkeypatch.setattr(creators_provider, "business_zone", lambda _t: UTC)
    monkeypatch.setattr(creators_provider, "acting_user", lambda _t, _e: USER)

    async def _ids(_state: Any) -> tuple[UUID, UUID, str]:
        return TENANT, BRAND, "duena@example.com"

    async def _access(_state: Any, _tenant: UUID) -> bool:
        return fake.enabled

    told: list[str] = []

    async def _tell(_state: Any, message: str) -> None:
        told.append(message)

    async def _off(_state: Any) -> None:
        told.append("off")

    monkeypatch.setattr(creators_state, "_session_ids", _ids)
    monkeypatch.setattr(creators_state, "_ensure_access", _access)
    monkeypatch.setattr(creators_state, "_tell_list", _tell)
    monkeypatch.setattr(creators_state, "_access_off", _off)
    monkeypatch.setattr(creators_state, "STAGE_SECONDS", 0.01)
    fake.told = told  # type: ignore[attr-defined]
    return fake


async def _drain(events: Any) -> list[Any]:
    if events is None:
        return []
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


async def _loaded_list(service: FakeService) -> CreatorsState:
    state = CreatorsState()
    await _drain(CreatorsState.reload.fn(state))
    return state


# --- 1. opening never pays ----------------------------------------------------------


async def test_opening_the_three_screens_never_pays(service: FakeService, monkeypatch) -> None:
    a, b = service.seed("maria"), service.seed("ruta")
    await _loaded_list(service)

    sheet = CreatorSheetState()
    monkeypatch.setattr(CreatorSheetState, "_route_id", lambda self: a.id)
    await _drain(CreatorSheetState.load.fn(sheet))
    assert sheet.has_read and sheet.sheet.handle == "@maria"

    comp = CreatorsCompareState()
    monkeypatch.setattr(CreatorsCompareState, "_requested", lambda self: [str(a.id), str(b.id)])
    await _drain(CreatorsCompareState.load.fn(comp))
    assert comp.has_comparison and len(comp.comparison.columns) == 2

    assert service.refreshed == []


async def test_the_list_shows_the_last_read_first(service: FakeService) -> None:
    """Last read first; a creator just added (no read yet) is the newest of all."""
    service.seed("maria")
    service.seed("nuevo", read=False)
    state = await _loaded_list(service)
    assert [c.handle for c in state.cards] == ["@nuevo", "@maria"]
    assert state.cards[0].state == "pending"
    assert not state.loading and state.load_error == ""


# --- 2. «Ver cómo le va» --------------------------------------------------------------


async def test_review_saves_reads_once_and_opens_the_sheet(service: FakeService) -> None:
    state = await _loaded_list(service)
    state.drawer_open = True
    state.handle_input = "https://www.instagram.com/comeconmaria/?igsh=x"
    events = await _drain(CreatorsState.submit.fn(state))
    assert len(service.refreshed) == 1
    tracked_id = service.refreshed[0]
    assert not state.drawer_open and not state.adding
    assert state.working == []
    assert any(f"/creadores/{tracked_id}" in str(e) for e in events)


async def test_a_typo_is_taken_off_the_list_and_the_text_stays(service: FakeService) -> None:
    service.outcome = "missing"
    state = await _loaded_list(service)
    state.drawer_open = True
    state.handle_input = "comeconmria"
    await _drain(CreatorsState.submit.fn(state))
    assert service.archived == service.refreshed
    assert state.add_message.startswith("No encontramos a @comeconmria en Instagram.")
    assert state.handle_input == "comeconmria"
    assert state.drawer_open
    assert all(c.handle != "@comeconmria" for c in state.cards)


async def test_a_private_account_offers_another_one(service: FakeService) -> None:
    service.outcome = "private"
    state = await _loaded_list(service)
    state.drawer_open = True
    state.handle_input = "secreta"
    await _drain(CreatorsState.submit.fn(state))
    assert "privada" in state.add_message
    assert state.add_tone == "warn"
    assert state.action_label == "Revisar otra cuenta"
    CreatorsState.on_action.fn(state)
    assert state.handle_input == "" and state.add_message == ""


async def test_an_invalid_handle_is_said_before_any_read(service: FakeService) -> None:
    state = await _loaded_list(service)
    state.drawer_open = True
    state.handle_input = "dos palabras"
    await _drain(CreatorsState.submit.fn(state))
    assert state.add_message == INVALID_HANDLE
    assert service.refreshed == []


async def test_an_empty_field_does_nothing(service: FakeService) -> None:
    state = await _loaded_list(service)
    state.handle_input = "   "
    assert state.submit_disabled
    await _drain(CreatorsState.submit.fn(state))
    assert "add" not in service.calls


async def test_closing_the_drawer_leaves_a_notice_when_the_read_ends(
    service: FakeService,
) -> None:
    state = await _loaded_list(service)
    state.drawer_open = False  # the owner closed it while waiting
    state.handle_input = "maria"
    events = await _drain(CreatorsState.submit.fn(state))
    assert state.notice == "Listo: ya puedes ver cómo le va a @maria."
    assert state.notice_href.startswith("/creadores/")
    assert events == []


# --- 3. already in the list -------------------------------------------------------------


async def test_a_creator_already_in_the_list_is_not_read_again(service: FakeService) -> None:
    maria = service.seed("maria")
    state = await _loaded_list(service)
    state.drawer_open = True
    state.handle_input = "@maria"
    await _drain(CreatorsState.submit.fn(state))
    assert service.refreshed == []
    assert state.add_message == "Ya revisaste a @maria ayer."
    assert state.existing_href == f"/creadores/{maria.id}"
    assert state.action_label == "Actualizar"
    await _drain(CreatorsState.refresh_existing.fn(state))
    assert service.refreshed == [maria.id]


# --- 4. «Elige de 2 a 4» -------------------------------------------------------------------


async def test_picking_two_to_four(service: FakeService) -> None:
    ids = [str(service.seed(f"c{i}").id) for i in range(5)]
    pending = str(service.seed("sinleer", read=False).id)
    state = await _loaded_list(service)
    CreatorsState.start_pick.fn(state)
    CreatorsState.toggle_pick.fn(state, pending)
    assert state.picked == []
    CreatorsState.toggle_pick.fn(state, ids[0])
    assert state.pick_hint == "Elige al menos uno más"
    assert not state.pick_ready
    for i in ids[1:4]:
        CreatorsState.toggle_pick.fn(state, i)
    CreatorsState.toggle_pick.fn(state, ids[4])
    assert state.pick_error == PICK_LIMIT
    assert len(state.picked) == 4
    assert state.pick_label == "Comparar 4 creadores"
    event = CreatorsState.go_compare.fn(state)
    assert compare_url(ids[:4]).replace(",", "%2C") in str(event)


# --- 5. Comparar refuses 1 or 5 ------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 5])
async def test_comparar_refuses_outside_two_to_four(
    service: FakeService, monkeypatch, count: int
) -> None:
    ids = [str(service.seed(f"c{i}").id) for i in range(count)]
    comp = CreatorsCompareState()
    monkeypatch.setattr(CreatorsCompareState, "_requested", lambda self: ids)
    events = await _drain(CreatorsCompareState.load.fn(comp))
    assert service.told == [COMPARE_INVALID]  # type: ignore[attr-defined]
    assert any("/creadores" in str(e) for e in events)
    assert "compare" not in service.calls


async def test_updating_a_stale_creator_reads_only_that_one(
    service: FakeService, monkeypatch
) -> None:
    a, b = service.seed("maria"), service.seed("ruta")
    service.stale.add("ruta")
    comp = CreatorsCompareState()
    monkeypatch.setattr(CreatorsCompareState, "_requested", lambda self: [str(a.id), str(b.id)])
    await _drain(CreatorsCompareState.load.fn(comp))
    assert comp.comparison.stale_ids == [str(b.id)]
    assert comp.comparison.stale_button == "Actualizar @ruta"
    await _drain(CreatorsCompareState.update_stale.fn(comp))
    assert service.refreshed == [b.id]
    assert comp.updating == []


# --- the sheet ---------------------------------------------------------------------------


async def test_actualizar_keeps_the_sheet_and_words_the_cap(
    service: FakeService, monkeypatch
) -> None:
    maria = service.seed("maria")
    sheet = CreatorSheetState()
    monkeypatch.setattr(CreatorSheetState, "_route_id", lambda self: maria.id)
    await _drain(CreatorSheetState.load.fn(sheet))
    service.outcome = "cap_reached"
    await _drain(CreatorSheetState.refresh.fn(sheet))
    assert sheet.has_read
    assert service.refreshed == [maria.id]
    assert sheet.refresh_message == (
        "Llegaste al límite de revisiones por ahora. Vuelve a intentarlo más tarde."
    )
    for word in ("crédito", "credito", "dinero"):
        assert word not in sheet.refresh_message.lower()


async def test_quitar_archives_and_tells_the_list(service: FakeService, monkeypatch) -> None:
    maria = service.seed("maria")
    sheet = CreatorSheetState()
    monkeypatch.setattr(CreatorSheetState, "_route_id", lambda self: maria.id)
    await _drain(CreatorSheetState.load.fn(sheet))
    events = await _drain(CreatorSheetState.confirm_archive.fn(sheet))
    assert service.archived == [maria.id]
    assert service.told == ["Quitaste a @maria de tu lista."]  # type: ignore[attr-defined]
    assert any("/creadores" in str(e) for e in events)


async def test_a_sheet_of_another_business_is_gone(service: FakeService, monkeypatch) -> None:
    sheet = CreatorSheetState()
    monkeypatch.setattr(CreatorSheetState, "_route_id", lambda self: uuid4())
    await _drain(CreatorSheetState.load.fn(sheet))
    assert sheet.load_error == "Este creador ya no está en tu lista."
    assert not sheet.has_read


# --- 6. the switch -------------------------------------------------------------------------


async def test_switch_off_lists_nothing(service: FakeService) -> None:
    service.seed("maria")
    service.enabled = False
    state = CreatorsState()
    await _drain(CreatorsState.load.fn(state))
    assert state.cards == []
    assert "list" not in service.calls


def test_the_menu_entry_follows_the_switch() -> None:
    """§11: «Creadores» stays «Pronto» in the static menu map (a business off the switch)
    and is swapped for the working entry by the switch's Var."""
    from .ui.layout import NAV_GATES, NAV_RESULTS, _gated_nav_item

    entry = next(item for item in NAV_RESULTS if item[0] == "Creadores")
    assert entry[3] is False
    assert "Creadores" in NAV_GATES
    rendered = str(_gated_nav_item(entry).render())
    assert "Pronto" in rendered


async def test_with_exactly_two_compare_opens_directly(service: FakeService) -> None:
    a, b = service.seed("maria"), service.seed("ruta")
    state = await _loaded_list(service)
    event = CreatorsState.start_pick.fn(state)
    assert not state.picking
    assert str(a.id) in str(event) and str(b.id) in str(event)


async def test_leaving_the_list_drops_pick_mode_and_the_notice(service: FakeService) -> None:
    for name in ("a", "b", "c"):
        service.seed(name)
    state = await _loaded_list(service)
    CreatorsState.start_pick.fn(state)
    state.notice = "Listo: ya puedes ver cómo le va a @a."
    CreatorsState.leave_flow.fn(state)
    assert not state.picking and state.picked == []
    assert state.notice == "" and state.notice_href == ""


async def test_a_plain_visit_is_not_in_pick_mode(service: FakeService) -> None:
    for name in ("a", "b", "c"):
        service.seed(name)
    state = await _loaded_list(service)
    state.picking = True
    await _drain(CreatorsState.load.fn(state))
    assert not state.picking


async def test_a_stuck_read_in_the_list_offers_a_retry(service: FakeService) -> None:
    service.seed("stuck.one", read=False).refresh_state = "reading"
    service.seed("alive", read=False).refresh_state = "reading"
    state = await _loaded_list(service)
    by_handle = {c.handle: c.state for c in state.cards}
    assert by_handle == {"@stuck.one": "failed", "@alive": "working"}
