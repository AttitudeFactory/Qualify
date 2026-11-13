"""Galería › the products in the WhatsApp catalog (m-25017357), offline.

No database, no Meta: the provider functions the state calls are replaced with
stand-ins, `_session_ids` / `_current_tenant` / `get_state` are monkeypatched on the
CLASS (as in `test_catalog_gallery_state.py`), background handlers run via `.fn`.

Pins:
1. Every state and every reason (eligibility and the item's error codes) has its badge,
   tone, help and action; unknown codes get the spec's generic sentence.
2. A card carries at most one WhatsApp badge, none for «not in WhatsApp», and no second
   «missing photo».
3. The bulk callout and its button by situation (first time, pending, up to date,
   nothing ready); the dialog shows only the counts above zero and states removals.
4. No catalog / lost permission: no product states; the team is reached through a
   support ticket.
5. One product: upload, «Guardar y subir» saves first, refusals in the owner's words.
6. Every product: the plan, the confirmation, `PlanChanged` → the confirmation again.
7. Polling starts while something is in flight and stops when nothing is.
8. Copy: no technical words; logout resets the state.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from . import catalog_whatsapp_page as page_module
from . import catalog_whatsapp_state as module
from . import catalog_whatsapp_vm as vm
from .auth_state import AuthState
from .catalog_state import CatalogState
from .catalog_vm import ProductVM
from .catalog_whatsapp_provider import (
    CatalogNotConnected,
    CatalogPermissionMissing,
    PlanChanged,
    PlanVM,
    ProductNotEligible,
    RunVM,
    SentVM,
    SyncViewVM,
)
from .catalog_whatsapp_state import CatalogWhatsAppState, refusal_text

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("b0000000-0000-4000-8000-000000000001")
_USER = UUID("c0000000-0000-4000-8000-000000000001")
_A = "d0000000-0000-4000-8000-00000000000a"
_B = "d0000000-0000-4000-8000-00000000000b"
_C = "d0000000-0000-4000-8000-00000000000c"
_GONE = "d0000000-0000-4000-8000-0000000000ff"


def _product(pid: str, name: str, photos: int = 1) -> ProductVM:
    return ProductVM(
        product_id=pid,
        name=name,
        slug=name.lower(),
        description="",
        price_label="$5",
        price_amount="5",
        price_currency="USD",
        category="",
        primary_photo_key="k" if photos else "",
        photo_count=photos,
        video_count=0,
        counts_label="1 foto",
    )


# -- 1. per product -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "reason", "badge", "tone", "action"),
    [
        ("not_uploaded", None, vm.NOT_UPLOADED_BADGE, "neutral", vm.ACTION_UPLOAD),
        ("queued", None, vm.IN_FLIGHT_BADGE, "info", vm.ACTION_BUSY),
        ("uploading", None, vm.IN_FLIGHT_BADGE, "info", vm.ACTION_BUSY),
        ("synced", None, vm.SYNCED_BADGE, "ok", vm.ACTION_NONE),
        ("out_of_date", None, vm.OUT_OF_DATE_BADGE, "warn", vm.ACTION_UPDATE),
        ("error", "meta_rejected", vm.ERROR_BADGE, "error", vm.ACTION_RETRY),
        ("error", "meta_unconfirmed", vm.ERROR_BADGE, "error", vm.ACTION_RETRY),
        ("error", "send_failed", vm.ERROR_BADGE, "error", vm.ACTION_RETRY),
        ("error", "no_permission", vm.ERROR_BADGE, "error", vm.ACTION_NONE),
        ("error", "something_new", vm.ERROR_BADGE, "error", vm.ACTION_RETRY),
        ("not_eligible", "no_price", "Le falta el precio", "warn", vm.ACTION_NONE),
        ("not_eligible", "no_currency", "Le falta la moneda", "warn", vm.ACTION_NONE),
        ("not_eligible", "no_photo", "Le falta la foto", "warn", vm.ACTION_NONE),
        ("not_eligible", "photo_too_small", "Foto muy pequeña", "warn", vm.ACTION_NONE),
        ("not_eligible", "photo_format", "Foto en otro formato", "warn", vm.ACTION_NONE),
    ],
)
def test_every_state_and_reason_has_its_words(state, reason, badge, tone, action) -> None:
    view = vm.editor_view(state, reason)
    assert (view.badge, view.tone, view.action) == (badge, tone, action)
    assert view.help and view.help[-1] in ".»"


def test_every_backend_code_is_mapped() -> None:
    from qualify_api.whatsapp.catalog_sync.mapping import INELIGIBLE_REASONS
    from qualify_api.whatsapp.models import CATALOG_ITEM_ERRORS

    assert set(CATALOG_ITEM_ERRORS) <= set(vm.ITEM_ERRORS)
    assert set(INELIGIBLE_REASONS) - {"inactive"} <= set(vm.NOT_ELIGIBLE)
    assert vm.editor_view("error", "zzz").help == vm.ITEM_ERROR_FALLBACK[0]
    assert "500 × 500" in vm.NOT_ELIGIBLE["photo_too_small"][1]
    assert "JPG o PNG" in vm.NOT_ELIGIBLE["photo_format"][1]


def test_rejected_says_what_to_check_and_that_the_team_helps() -> None:
    text = vm.ITEM_ERRORS["meta_rejected"][0]
    assert all(w in text for w in ("nombre", "precio", "foto", "escríbenos"))


def test_the_button_saves_first_when_the_editor_has_changes() -> None:
    assert vm.action_label(vm.ACTION_UPLOAD, dirty=False) == "Subir a WhatsApp"
    assert vm.action_label(vm.ACTION_UPLOAD, dirty=True) == "Guardar y subir a WhatsApp"
    assert vm.action_label(vm.ACTION_UPDATE, dirty=True) == "Actualizar en WhatsApp"
    assert vm.action_label(vm.ACTION_NONE, dirty=False) == ""


# -- 2. the card ----------------------------------------------------------------------------


def test_a_card_carries_at_most_one_badge_and_none_when_not_there() -> None:
    assert vm.card_badge("not_uploaded", None, photo_count=1) == ("", "")
    assert vm.card_badge("synced", None, photo_count=1) == (vm.CARD_SYNCED, "En WhatsApp")
    assert vm.card_badge("queued", None, photo_count=1)[0] == vm.CARD_UPLOADING
    assert vm.card_badge("out_of_date", None, photo_count=1)[1] == "Por actualizar"
    assert vm.card_badge("error", "send_failed", photo_count=1)[1] == "No se subió"
    # «Falta la foto» is already on the card: not repeated
    assert vm.card_badge("not_eligible", "no_photo", photo_count=0) == ("", "")
    assert vm.card_badge("not_eligible", "no_price", photo_count=1) == (
        vm.CARD_MISSING,
        "Le falta el precio",
    )


# -- 3. the bulk block and the dialog -------------------------------------------------------


def _states(**by_id: tuple[str, str | None]) -> dict[str, tuple[str, str | None]]:
    return dict(by_id)


def test_first_time_offers_to_upload_everything() -> None:
    states = {
        _A: ("not_uploaded", None),
        _B: ("not_uploaded", None),
        _C: ("not_eligible", "no_price"),
    }
    screen = vm.screen_view("connected", states, {_A: 1, _B: 1, _C: 1})
    assert screen.bulk == vm.Bulk(
        "Tus clientes pueden ver tus 2 productos con su precio dentro de WhatsApp.",
        "info",
        "Subir mis productos a WhatsApp",
    )
    assert screen.problem_ids == (_C,)


def test_pending_changes_name_only_the_parts_above_zero() -> None:
    states = {
        _A: ("not_uploaded", None),
        _B: ("out_of_date", None),
        _C: ("synced", None),
        _GONE: ("out_of_date", None),  # deleted here, still in WhatsApp
    }
    bulk = vm.screen_view("connected", states, {_A: 1, _B: 1, _C: 1}).bulk
    assert bulk.tone == "warn" and bulk.button == "Actualizar mi catálogo de WhatsApp"
    assert bulk.text == (
        "1 nuevo y 1 con cambios todavía no están en WhatsApp. "
        "1 que borraste aquí todavía se ve en WhatsApp."
    )
    only_new = vm.bulk_view(vm.Counts(total=4, new=3, synced=1, ever_sent=True))
    assert only_new.text == "3 nuevos todavía no están en WhatsApp."


def test_up_to_date_and_nothing_ready() -> None:
    done = vm.screen_view("connected", {_A: ("synced", None), _B: ("synced", None)}, {_A: 1, _B: 1})
    assert done.bulk == vm.Bulk("Tus 2 productos están en WhatsApp con su precio de hoy.", "ok")
    nothing = vm.screen_view("connected", {_A: ("not_eligible", "no_price")}, {_A: 1})
    assert nothing.bulk.button == "" and "precio y foto" in nothing.bulk.text


def test_the_dialog_shows_only_counts_above_zero_and_states_removals() -> None:
    dialog = vm.dialog_view(
        new=3,
        changed=0,
        deletes=1,
        not_eligible={"no_photo": 2, "no_price": 1, "inactive": 4},
        first_time=False,
        removal_names=["Combo viejo"],
    )
    assert dialog.title == "¿Actualizar tu catálogo de WhatsApp?"
    assert dialog.lines == (
        "Se suben 3 productos nuevos.",
        "3 no se pueden subir todavía: les falta la foto o el precio. Los verás después "
        "para corregirlos.",
    )
    assert dialog.removal == (
        "Se quita de WhatsApp 1 que borraste aquí: «Combo viejo». Tus clientes ya no lo verán."
    )
    assert dialog.confirm == "Sí, actualizar"
    first = vm.dialog_view(new=1, changed=2, deletes=0, not_eligible={}, first_time=True)
    assert first.title == "¿Subir tus productos a WhatsApp?" and first.confirm == "Sí, subir"
    assert first.lines == ("Se sube 1 producto nuevo.", "Se actualizan 2 que cambiaste.")
    assert first.removal == ""


def test_summary_and_progress() -> None:
    ok = vm.run_summary(status="finished", new=3, changed=2, deletes=1, failed=0)
    assert ok == vm.Summary("Listo: 3 subidos, 2 actualizados y 1 quitado.", "ok", 0)
    partial = vm.run_summary(status="partial", new=3, changed=2, deletes=0, failed=2)
    assert partial.tone == "warn" and partial.problems == 2
    assert partial.text == "Listo: 3 productos ya están en WhatsApp. 2 con problemas."
    lost = vm.run_summary(
        status="failed", new=1, changed=0, deletes=0, failed=0, error_code="missing_permission"
    )
    assert lost.tone == "error" and lost.text == vm.LOST_ACCESS_TEXT
    assert vm.progress_title(2, 5) == "Subiendo a WhatsApp: 2 de 5"
    assert vm.progress_value(2, 5) == 40 and vm.progress_value(0, 0) == 0
    assert vm.problems_label(1, active=False) == "Ver el que tiene problemas"
    assert vm.problems_label(4, active=False) == "Ver los 4 con problemas"


# -- 4. no catalog / lost permission --------------------------------------------------------


def test_no_catalog_shows_no_product_states() -> None:
    screen = vm.screen_view("none", {_A: ("not_uploaded", None)}, {_A: 1})
    assert screen.card_kind == {} and screen.editor == {} and screen.bulk == vm.Bulk()


def test_lost_permission_keeps_the_states_but_offers_no_bulk_action() -> None:
    screen = vm.screen_view("missing_permission", {_A: ("synced", None)}, {_A: 1})
    assert screen.card_kind == {_A: vm.CARD_SYNCED} and screen.bulk.button == ""


# -- the state ------------------------------------------------------------------------------


class _Fake:
    def __init__(self) -> None:
        self.view = SyncViewVM(connection="connected", states={_A: ("not_uploaded", None)})
        self.plans: list[PlanVM] = []
        self.sent: list[tuple[str, Any]] = []
        self.refuse: Exception | None = None
        self.team: list[dict[str, Any]] = []

    def load_view(self, tenant_id: UUID, brand_id: UUID) -> SyncViewVM:
        assert (tenant_id, brand_id) == (_TENANT, _BRAND)
        return self.view

    def plan_all(self, tenant_id: UUID, brand_id: UUID) -> PlanVM:
        return self.plans.pop(0)

    def send_all(self, tenant_id, brand_id, user_id, plan_key) -> SentVM:
        self.sent.append(("all", plan_key))
        if self.refuse is not None:
            refuse, self.refuse = self.refuse, None
            raise refuse
        return SentVM(("r1",), 2, 0, 0, 0)

    def upload_one(self, tenant_id, brand_id, user_id, product_id) -> SentVM:
        self.sent.append(("upload", str(product_id)))
        if self.refuse is not None:
            raise self.refuse
        return SentVM(("r2",), 1, 0, 0, 0)

    def update_one(self, tenant_id, brand_id, user_id, product_id) -> SentVM:
        self.sent.append(("update", str(product_id)))
        return SentVM((), 0, 0, 1, 0)

    def request_team(self, tenant_id, **kw: Any) -> Any:
        self.team.append(kw)
        return type("T", (), {"reference": "#ABC123", "notified": True})()


@pytest.fixture
def fake(monkeypatch) -> _Fake:
    fake = _Fake()
    for name in ("load_view", "plan_all", "send_all", "upload_one", "update_one", "request_team"):
        monkeypatch.setattr(module, name, getattr(fake, name))
    monkeypatch.setattr(module, "product_names", lambda t, ids: {})
    monkeypatch.setattr(module, "acting_user_id", lambda t: _USER)
    return fake


@pytest.fixture
def world(monkeypatch, fake) -> tuple[CatalogWhatsAppState, CatalogState]:
    catalog = CatalogState()
    catalog.products = [_product(_A, "Shawarma mixto"), _product(_B, "Wrap", photos=0)]
    auth = AuthState()
    auth.user_email = "dueno@example.com"
    states: dict[type, Any] = {CatalogState: catalog, AuthState: auth}

    async def get_state(self: Any, cls: type) -> Any:
        return states[cls]

    async def ids(self: Any) -> tuple[UUID, UUID]:
        return (_TENANT, _BRAND)

    async def tenant(self: Any) -> UUID:
        return _TENANT

    monkeypatch.setattr(CatalogWhatsAppState, "get_state", get_state)
    monkeypatch.setattr(CatalogWhatsAppState, "_session_ids", ids)
    monkeypatch.setattr(CatalogWhatsAppState, "_current_tenant", tenant)
    wa = CatalogWhatsAppState()
    states[CatalogWhatsAppState] = wa
    return wa, catalog


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


def _names(events: list[Any]) -> str:
    return " ".join(str(e) for e in events)


async def test_load_paints_badges_and_the_problems_filter(world, fake) -> None:
    wa, catalog = world
    fake.view = SyncViewVM(
        connection="connected",
        states={_A: ("synced", None), _B: ("not_eligible", "no_photo")},
    )
    events = await _drain(CatalogWhatsAppState.load.fn(wa))
    assert wa.connected and wa.card_kind == {_A: vm.CARD_SYNCED}
    assert wa.ed_action == {_A: vm.ACTION_NONE, _B: vm.ACTION_NONE}
    assert wa.live_ids == [_A] and wa.problem_count == 1
    assert catalog.wa_ready and catalog.wa_problem_ids == [_B]
    # the only product without a photo is a problem: «sin foto» steps aside
    assert catalog.wa_hides_photo_filter and not catalog.show_missing_filter
    catalog.only_wa_problems = True
    assert [p.product_id for p in catalog.visible_products] == [_B]
    assert "watch" not in _names(events)  # nothing in flight: no polling


async def test_polling_starts_while_in_flight_and_stops_after(world, fake, monkeypatch) -> None:
    wa, _ = world
    fake.view = SyncViewVM(connection="connected", states={_A: ("uploading", None)})
    events = await _drain(CatalogWhatsAppState.load.fn(wa))
    assert "watch" in _names(events)

    async def no_wait(_s: float) -> None:
        fake.view = SyncViewVM(connection="connected", states={_A: ("synced", None)})

    monkeypatch.setattr(module.asyncio, "sleep", no_wait)
    wa._on_page = True
    wa.sent_verbs = {_A: vm.ACTION_UPLOAD}
    events = await _drain(CatalogWhatsAppState.watch.fn(wa))
    assert "«Shawarma mixto» ya está en WhatsApp" in _names(events)
    assert wa._watching is False and wa.sent_verbs == {}


async def test_polling_stops_when_the_owner_leaves(world, fake, monkeypatch) -> None:
    wa, _ = world
    reads: list[int] = []

    async def no_wait(_s: float) -> None:
        reads.append(1)

    monkeypatch.setattr(module.asyncio, "sleep", no_wait)
    wa._on_page = False
    await _drain(CatalogWhatsAppState.watch.fn(wa))
    assert reads == [1] and wa._watching is False


async def test_upload_one_queues_it_and_watches(world, fake) -> None:
    wa, _ = world
    await _drain(CatalogWhatsAppState.load.fn(wa))
    fake.view = SyncViewVM(connection="connected", states={_A: ("queued", None)})
    events = await _drain(CatalogWhatsAppState.send_one.fn(wa, _A))
    assert fake.sent == [("upload", _A)]
    assert wa.sent_verbs == {_A: vm.ACTION_UPLOAD} and wa.acting == ""
    assert wa.card_kind[_A] == vm.CARD_UPLOADING and "watch" in _names(events)


async def test_save_and_upload_saves_first(world, fake) -> None:
    wa, catalog = world
    await _drain(CatalogWhatsAppState.load.fn(wa))
    catalog.selected_id = _A
    catalog.edit_name = "Shawarma grande"  # unsaved
    catalog.edit_price, catalog.edit_currency = "5", "USD"
    event = await wa.act(_A)
    assert "save_product" in str(event) and catalog._wa_after_save == _A
    assert fake.sent == []  # nothing goes to WhatsApp before the save lands


async def test_refusals_are_said_in_the_owners_words(world, fake) -> None:
    wa, _ = world
    await _drain(CatalogWhatsAppState.load.fn(wa))
    fake.refuse = ProductNotEligible("no_price")
    events = await _drain(CatalogWhatsAppState.send_one.fn(wa, _A))
    assert wa.ed_error == vm.NOT_ELIGIBLE["no_price"][1] and wa.ed_error_for == _A
    assert "error" in _names(events)
    assert refusal_text(CatalogNotConnected()) == vm.NOT_CONNECTED_ERROR
    assert refusal_text(CatalogPermissionMissing("auth_error")) == vm.LOST_ACCESS_TEXT
    assert refusal_text(RuntimeError("x")) == vm.DB_ERROR


async def test_unchanged_product_says_it_was_already_up_to_date(world, fake) -> None:
    wa, _ = world
    fake.view = SyncViewVM(connection="connected", states={_A: ("out_of_date", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    events = await _drain(CatalogWhatsAppState.send_one.fn(wa, _A))
    assert fake.sent == [("update", _A)] and vm.ALREADY_UP_TO_DATE in _names(events)


def _plan(new: int = 2, key: str = "k1") -> PlanVM:
    return PlanVM(new, 0, 0, 0, 0, {"no_photo": 1}, key)


async def test_bulk_plan_confirm_and_summary(world, fake, monkeypatch) -> None:
    wa, _ = world
    await _drain(CatalogWhatsAppState.load.fn(wa))
    fake.plans = [_plan()]
    await _drain(CatalogWhatsAppState.open_dialog.fn(wa))
    assert wa.dialog_open and wa.dialog_title == "¿Subir tus productos a WhatsApp?"
    assert wa.dialog_lines[0] == "Se suben 2 productos nuevos."
    assert fake.sent == []  # the plan writes nothing
    fake.view = SyncViewVM(
        connection="connected",
        states={_A: ("queued", None), _B: ("not_eligible", "no_photo")},
        last_run=RunVM("r1", "sync_all", "pending", 2, 0, 0, ""),
    )
    events = await _drain(CatalogWhatsAppState.confirm_all.fn(wa))
    assert fake.sent == [("all", "k1")] and not wa.dialog_open
    assert wa.running and wa.progress_total == 2 and wa.progress_done == 1
    assert wa.progress_title == "Subiendo a WhatsApp: 1 de 2"
    assert "watch" in _names(events)

    fake.view = SyncViewVM(
        connection="connected",
        states={_A: ("synced", None), _B: ("not_eligible", "no_photo")},
        last_run=RunVM("r1", "sync_all", "finished", 2, 0, 0, ""),
    )

    async def no_wait(_s: float) -> None:
        return None

    monkeypatch.setattr(module.asyncio, "sleep", no_wait)
    wa._on_page = True
    events = await _drain(CatalogWhatsAppState.watch.fn(wa))
    assert not wa.running and wa.summary_text == "Listo: 2 subidos." and wa.summary_tone == "ok"
    assert vm.UP_TO_DATE_TOAST in _names(events)


async def test_plan_changed_shows_the_confirmation_again(world, fake) -> None:
    wa, _ = world
    await _drain(CatalogWhatsAppState.load.fn(wa))
    fake.plans = [_plan(2, "k1"), _plan(3, "k2")]
    await _drain(CatalogWhatsAppState.open_dialog.fn(wa))
    fake.refuse = PlanChanged()
    await _drain(CatalogWhatsAppState.confirm_all.fn(wa))
    assert wa.dialog_open and wa.dialog_notice == vm.PLAN_CHANGED
    assert wa.dialog_lines[0] == "Se suben 3 productos nuevos." and wa._plan_key == "k2"
    assert not wa.running


async def test_no_catalog_asks_the_team_once(world, fake) -> None:
    wa, catalog = world
    fake.view = SyncViewVM(connection="none", states={_A: ("not_uploaded", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    assert wa.not_connected and not wa.shows_products and wa.card_kind == {}
    assert catalog.wa_problem_ids == []
    await CatalogWhatsAppState.ask_team.fn(wa)
    await CatalogWhatsAppState.ask_team.fn(wa)  # a second tap files nothing
    assert len(fake.team) == 1 and fake.team[0]["screen"] == vm.ASK_CATALOG_SCREEN
    assert wa.team_sent and "#ABC123" in wa.team_notice


async def test_lost_permission_asks_to_reconnect(world, fake) -> None:
    wa, _ = world
    fake.view = SyncViewVM(connection="auth_error", states={_A: ("synced", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    assert wa.lost_access and wa.shows_products and wa.bulk_button == ""
    await CatalogWhatsAppState.ask_team.fn(wa)
    assert fake.team[0]["screen"] == vm.ASK_RECONNECT_SCREEN


def test_logout_resets_the_whatsapp_layer() -> None:
    from .auth_state import business_state_classes

    assert CatalogWhatsAppState in business_state_classes()


# -- 8. copy --------------------------------------------------------------------------------

_FORBIDDEN = re.compile(
    r"sincroniz|\bAPI\b|\bpost\b|\bfeed\b|\bSKU\b|Meta Commerce|en cola|\bupload\b|retailer",
    re.IGNORECASE,
)


def _visible_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    skip: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"debug", "info", "warning", "error", "exception"}:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "logger":
                    skip.update(id(n) for n in ast.walk(node))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in skip
        and " " in n.value.strip()
    ]


@pytest.mark.parametrize("mod", [vm, module, page_module])
def test_no_technical_words_reach_the_owner(mod) -> None:
    for text in _visible_strings(Path(inspect.getfile(mod))):
        assert not _FORBIDDEN.search(text), text


async def test_the_last_summary_goes_once_there_is_something_new(world, fake) -> None:
    wa, _ = world
    fake.view = SyncViewVM(connection="connected", states={_A: ("synced", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    wa.summary_text, wa.summary_tone = "Listo: 1 subido.", "ok"
    fake.view = SyncViewVM(connection="connected", states={_A: ("out_of_date", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    assert wa.summary_text == "" and wa.bulk_button == vm.UPDATE_ALL


async def test_a_new_situation_offers_its_own_team_request(world, fake) -> None:
    wa, _ = world
    fake.view = SyncViewVM(connection="none")
    await _drain(CatalogWhatsAppState.load.fn(wa))
    await CatalogWhatsAppState.ask_team.fn(wa)
    assert wa.team_sent
    fake.view = SyncViewVM(connection="missing_permission", states={_A: ("synced", None)})
    await _drain(CatalogWhatsAppState.load.fn(wa))
    assert not wa.team_sent and wa.team_notice == ""


def test_a_refused_save_does_not_upload_afterwards() -> None:
    catalog = CatalogState()
    catalog._wa_after_save = _A
    catalog.edit_error = "El producto necesita un nombre."
    catalog._stay_after_refusal()
    assert catalog._wa_after_save == ""


def test_the_save_chains_the_upload_only_for_the_saved_product() -> None:
    source = inspect.getsource(CatalogState.save_product.fn)
    assert "send, self._wa_after_save = self._wa_after_save" in source
    assert "CatalogWhatsAppState.send_one(send)" in source
