"""«Formas de pago» (m-24955648, first PR): the state with a fake provider, and the views.

No DB: the provider functions the state calls are stand-ins with the backend's rules
(`PaymentMethodService` semantics, its Spanish messages), and `_session_ids` is patched
on the CLASS. Background handlers run through `.fn(state)`.
"""

from __future__ import annotations

import io
import json
from typing import Any
from uuid import UUID

import pytest
from qualify_api.whatsapp.payments import (
    PaymentMethodIncomplete,
    PaymentTooManyActive,
)
from sqlalchemy.exc import OperationalError

from . import whatsapp_payments_state as module
from . import whatsapp_tab_payments
from .whatsapp_page import tab_body
from .whatsapp_payments_state import WhatsAppPaymentsState
from .whatsapp_payments_vm import (
    ADD,
    BUTTONS_OR_LIST,
    CLOSING_BEFORE,
    CLOSING_ON_DELIVERY,
    EMPTY_TEXT,
    EMPTY_TITLE,
    INCOMPLETE,
    NAME_TOO_LONG,
    OFFER_NOW,
    OFFERED,
    PLACEHOLDER_LEFT,
    QR_TOO_LARGE,
    QR_WRONG_TYPE,
    SAVE_FAILED,
    STEP_TITLES,
    currency_words,
    updated_label,
)
from .whatsapp_vm import NUMBER_SUBS, TAB_PAYMENTS, resolve_panel

_T = UUID("a0000000-0000-4000-8000-000000000001")
_B = UUID("b0000000-0000-4000-8000-000000000001")
_U = UUID("c0000000-0000-4000-8000-000000000001")


class _Fake:
    """The service's rules, in memory."""

    def __init__(self) -> None:
        self.methods: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.fail: BaseException | None = None
        self.n = 0

    def _get(self, method_id: str) -> dict[str, Any]:
        return next(m for m in self.methods if m["method_id"] == method_id)

    def _check(self, name: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append(name)

    def list_methods(self, t: UUID, b: UUID) -> list[dict[str, Any]]:
        return [dict(m) for m in self.methods]

    def create(self, t: UUID, b: UUID, u: UUID | None, **form: Any) -> str:
        self._check("create")
        self.n += 1
        method_id = f"m{self.n}"
        self.methods.append(
            {
                "method_id": method_id,
                "name": form["name"],
                "currency": form["currency"],
                "instructions": form["instructions"],
                "pay_on_delivery": form["pay_on_delivery"],
                "has_qr": False,
                "thumb_url": "",
                "active": False,
                "updated_at": "2026-11-05T12:00:00+00:00",
            }
        )
        return method_id

    def update(self, t: UUID, b: UUID, u: UUID | None, method_id: str, **form: Any) -> None:
        self._check("update")
        self._get(method_id).update(form)

    def set_active(self, t: UUID, b: UUID, u: UUID | None, method_id: str, active: bool) -> None:
        self._check(f"active:{active}")
        m = self._get(method_id)
        if active:
            if not (m["pay_on_delivery"] or m["instructions"] or m["has_qr"]):
                raise PaymentMethodIncomplete()
            if sum(1 for x in self.methods if x["active"] and x is not m) >= 10:
                raise PaymentTooManyActive()
        m["active"] = active

    def reorder(self, t: UUID, b: UUID, u: UUID | None, ids: list[str]) -> None:
        self._check("reorder")
        self.methods = [self._get(i) for i in ids]

    def delete(self, t: UUID, b: UUID, method_id: str) -> None:
        self._check("delete")
        self.methods = [m for m in self.methods if m["method_id"] != method_id]

    def set_qr(self, t: UUID, b: UUID, u: UUID | None, method_id: str, **kw: Any) -> None:
        self._check("qr")
        assert kw["content"] and kw["content_type"] == "image/png"
        self._get(method_id)["has_qr"] = True

    def remove_qr(self, t: UUID, b: UUID, u: UUID | None, method_id: str) -> None:
        self._check("remove_qr")
        self._get(method_id)["has_qr"] = False


async def _ids(self: WhatsAppPaymentsState) -> tuple[UUID, UUID, UUID]:
    return (_T, _B, _U)


@pytest.fixture
def fake(monkeypatch) -> _Fake:
    f = _Fake()
    monkeypatch.setattr(WhatsAppPaymentsState, "_session_ids", _ids)
    for name, fn in {
        "list_methods": f.list_methods,
        "create_method": f.create,
        "update_method": f.update,
        "set_active": f.set_active,
        "reorder_methods": f.reorder,
        "delete_method": f.delete,
        "set_qr": f.set_qr,
        "remove_qr": f.remove_qr,
        "business_currency": lambda t: "VES",
    }.items():
        monkeypatch.setattr(module, name, fn)
    return f


async def _drain(events: Any) -> list[Any]:
    return [e async for e in events]


def _state(fake: _Fake) -> WhatsAppPaymentsState:
    state = WhatsAppPaymentsState()
    state._methods = fake.list_methods(_T, _B)
    state._business_currency = "VES"
    state.loaded_for = "conn"
    return state


async def _refresh(state: WhatsAppPaymentsState, fake: _Fake) -> None:
    state._methods = fake.list_methods(_T, _B)


def _seed(fake: _Fake, *names: str, active: bool = True) -> None:
    for name in names:
        fake.create(
            _T, _B, _U, name=name, currency="VES", instructions="Datos", pay_on_delivery=False
        )
        fake.methods[-1]["active"] = active
    fake.calls.clear()


# ---------------------------------------------------------------------------
# the add / edit flow


async def test_create_then_activation_needs_instructions_then_works(fake) -> None:
    state = _state(fake)
    state.open_new()
    assert state.flow_open and state.step == 1 and state.f_currency == "VES"
    state.pick_shortcut("otra")
    state.set_f_name("Zelle")
    state.next_step()
    assert state.step == 2
    state.set_f_instructions("")
    state.next_step()
    state.skip_qr()
    assert state.step == 4 and state.f_active
    await _drain(WhatsAppPaymentsState.save_flow.fn(state))
    assert state.f_error == INCOMPLETE and fake.calls == []  # refused before any write
    state.set_f_active(False)
    events = await _drain(WhatsAppPaymentsState.save_flow.fn(state))
    assert fake.calls == ["create"] and not state.flow_open
    assert "Guardada. Enciéndela cuando quieras." in json.dumps(str(events), ensure_ascii=False)
    await _refresh(state, fake)
    method_id = state.rows[0].method_id
    # «La ofreces» with nothing to send: refused here, with its [Editar]
    assert state.toggle_active(method_id, True) is None
    assert state.error == INCOMPLETE and state.incomplete_id == method_id
    state.open_edit(method_id)
    assert state.step == 4 and state.editing
    state.go_step(2)
    state.set_f_instructions("Zelle a pagos@ejemplo.com")
    state.next_step()
    state.next_step()
    state.set_f_active(True)
    events = await _drain(WhatsAppPaymentsState.save_flow.fn(state))
    assert fake.calls[-2:] == ["update", "active:True"]
    assert "Listo: tus clientes ya pueden elegir «Zelle»." in json.dumps(
        str(events), ensure_ascii=False
    )


async def test_a_shortcut_fills_the_example_and_its_placeholder_must_go(fake) -> None:
    state = _state(fake)
    state.open_new()
    state.pick_shortcut("binance")
    assert (state.f_name, state.f_currency) == ("Binance", "USDT")
    assert state.f_instructions.startswith("Binance Pay ID: [número]")
    state.next_step()
    state.next_step()
    assert state.step == 2 and state.f_error == PLACEHOLDER_LEFT
    state.set_f_instructions("Binance Pay ID: 123456 · Solo USDT")
    state.next_step()
    assert state.step == 3 and state.f_error == ""
    # «Otra» does not wipe what the owner already wrote
    state.pick_shortcut("otra")
    assert state.f_instructions == "Binance Pay ID: 123456 · Solo USDT"


def test_the_name_is_checked_at_20(fake) -> None:
    state = _state(fake)
    state.open_new()
    state.set_f_name("Transferencia Banco de Venezuela")
    state.next_step()
    assert state.step == 1 and state.f_error == NAME_TOO_LONG
    assert state.name_count == "32/20"


async def test_pay_on_delivery_needs_nothing_and_its_preview_says_so(fake) -> None:
    state = _state(fake)
    state.open_new()
    state.pick_shortcut("efectivo")
    assert state.f_on_delivery
    state.set_f_instructions("")
    state.next_step()
    state.next_step()
    state.skip_qr()
    assert state.preview_text[-1] == CLOSING_ON_DELIVERY
    await _drain(WhatsAppPaymentsState.save_flow.fn(state))
    assert fake.calls == ["create", "active:True"]


def test_the_preview_adds_the_sample_total_and_the_currency_line(fake) -> None:
    state = _state(fake)
    state.open_new()
    state.pick_shortcut("bre-b")  # COP in a business that sells in VES
    state.set_f_instructions("Llave Bre-B: 300 · A nombre de: Bianki")
    assert state.preview_text == [
        "Llave Bre-B: 300 · A nombre de: Bianki",
        "Total: $18 (ejemplo)",
        "Te confirmamos el monto en pesos.",
        CLOSING_BEFORE,
    ]


async def test_a_refusal_after_create_deletes_it_again(fake) -> None:
    state = _state(fake)
    _seed(fake, *[f"Forma {i}" for i in range(10)])
    state.open_new()
    state.set_f_name("La 11")
    state.next_step()
    state.set_f_instructions("Datos")
    state.next_step()
    state.skip_qr()
    await _drain(WhatsAppPaymentsState.save_flow.fn(state))
    assert state.f_error == PaymentTooManyActive().message  # the backend's words
    assert fake.calls == ["create", "active:True", "delete"] and len(fake.methods) == 10
    assert state.flow_open  # everything typed is still there


async def test_the_qr_is_checked_parked_and_sent_on_save(fake, tmp_path) -> None:
    from PIL import Image

    class Upload:
        def __init__(self, data: bytes, content_type: str, size: int | None = None) -> None:
            self._data, self.content_type = data, content_type
            self.size = len(data) if size is None else size
            self.name = "qr.png"

        async def read(self, n: int = -1) -> bytes:
            return self._data[:n] if n >= 0 else self._data

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    state = _state(fake)
    state.open_new()
    await state.handle_qr([Upload(b"%PDF", "application/pdf")])
    assert state.f_qr_error == QR_WRONG_TYPE
    await state.handle_qr([Upload(b"x", "image/png", size=16 * 1024 * 1024)])
    assert state.f_qr_error == QR_TOO_LARGE
    await state.handle_qr([Upload(buf.getvalue(), "image/png")])
    assert state.f_qr_error == "" and state.f_qr_preview.startswith("data:image/jpeg;base64,")
    assert state._f_qr_path and state.f_qr_name == "qr.png"  # the file, not the state
    parked = state._f_qr_path
    state.set_f_name("Pago móvil")
    state.set_f_instructions("")
    state.step = 4
    await _drain(WhatsAppPaymentsState.save_flow.fn(state))  # a QR is enough to offer it
    assert fake.calls == ["create", "qr", "active:True"]
    from pathlib import Path

    assert not Path(parked).exists()  # the temp file goes with the form


# ---------------------------------------------------------------------------
# the list


async def test_reorder_is_optimistic_saved_and_undoable(fake) -> None:
    _seed(fake, "Efectivo", "Bre-B", "Pago móvil")
    state = _state(fake)
    assert state.place("m3", 0) is not None
    assert [r.name for r in state.rows] == ["Pago móvil", "Efectivo", "Bre-B"]
    events = await _drain(WhatsAppPaymentsState.store_order.fn(state))
    assert fake.calls == ["reorder"] and [m["name"] for m in fake.methods][0] == "Pago móvil"
    assert "Listo: «Pago móvil» va primero." in json.dumps(str(events), ensure_ascii=False)
    assert state.undo_order() is not None
    await _drain(WhatsAppPaymentsState.store_undo.fn(state))
    assert [m["name"] for m in fake.methods] == ["Efectivo", "Bre-B", "Pago móvil"]


async def test_the_handle_lifts_moves_and_drops_with_one_write(fake) -> None:
    _seed(fake, "A", "B", "C")
    state = _state(fake)
    state.handle_key("m3", " ")
    state.handle_key("m3", "ArrowUp")
    state.handle_key("m3", "ArrowUp")
    assert [r.name for r in state.rows] == ["C", "A", "B"] and fake.calls == []
    assert state.handle_key("m3", " ") is not None
    await _drain(WhatsAppPaymentsState.store_order.fn(state))
    assert fake.calls == ["reorder"]
    state.handle_key("m1", " ")
    state.handle_key("m1", "ArrowDown")
    state.handle_key("m1", "Escape")
    assert [r.name for r in state.rows] == ["C", "A", "B"]


async def test_a_failed_write_puts_the_list_back(fake) -> None:
    _seed(fake, "A", "B")
    state = _state(fake)
    fake.fail = OperationalError("x", {}, Exception("down"))
    state.place("m2", 0)
    await _drain(WhatsAppPaymentsState.store_order.fn(state))
    assert [r.name for r in state.rows] == ["A", "B"] and state.error == SAVE_FAILED
    assert state.busy is False


async def test_an_eleventh_active_is_refused_with_the_backends_words(fake) -> None:
    _seed(fake, *[f"F{i}" for i in range(10)])
    _seed(fake, "Once", active=False)
    state = _state(fake)
    state.toggle_active("m11", True)
    assert state.rows[-1].active  # optimistic
    await WhatsAppPaymentsState.store_active.fn(state, "m11", True)
    assert not state.rows[-1].active and state.error == PaymentTooManyActive().message


async def test_a_failing_session_lookup_rolls_back_too(fake, monkeypatch) -> None:
    _seed(fake, "A", "B")
    state = _state(fake)

    async def boom(self: WhatsAppPaymentsState) -> None:
        raise OperationalError("x", {}, Exception("down"))

    monkeypatch.setattr(WhatsAppPaymentsState, "_session_ids", boom)
    state.ask_delete("m1")
    assert state.delete_open and state.delete_title_text == "¿Borrar «A»?"
    state.confirm_delete()
    assert [r.name for r in state.rows] == ["B"]
    await WhatsAppPaymentsState.store_delete.fn(state, "m1")
    assert [r.name for r in state.rows] == ["A", "B"] and state.error == SAVE_FAILED
    assert not state.busy


def test_row_labels_in_words() -> None:
    assert currency_words("VES") == "En bolívares" and currency_words("") == ""
    assert updated_label("2026-11-05T12:00:00+00:00") == "Actualizado el 5 nov."


# ---------------------------------------------------------------------------
# the views


def test_the_tab_sits_between_perfil_and_qr_with_its_own_address() -> None:
    labels = [label for _slug, label in NUMBER_SUBS]
    assert labels.index("Formas de pago") == labels.index("Perfil") + 1
    assert labels.index("Códigos QR") == labels.index("Formas de pago") + 1
    assert resolve_panel("numero", "pagos") == TAB_PAYMENTS
    assert "payments_tab" in str(tab_body()) or OFFERED in str(tab_body())


def test_the_panel_carries_the_list_the_empty_state_and_each_step() -> None:
    rendered = str(whatsapp_tab_payments.payments_tab())
    for words in (
        ADD,
        EMPTY_TITLE,
        EMPTY_TEXT,
        OFFERED,
        BUTTONS_OR_LIST,
        OFFER_NOW,
        *STEP_TITLES,
        "Primero",
        "Subir uno",
        "Bajar uno",
        "Último",
        "Borrar",
        "data-rank-handle",
        "q-pay-instr-count",
        "Pago móvil",
        "Efectivo al recibir",
    ):
        assert json.dumps(words)[1:-1] in rendered, words
