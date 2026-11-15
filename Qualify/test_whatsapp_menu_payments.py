"""m-24955648 §6 in Respuesta automática, offline: the starter's «Formas de pago» answer
composed live from the methods offered (read-only in step 2, never a gap), the gap rule
matching the server's (`definition_gaps(..., payments_offered=…)`), the phone preview
reading the same methods, and the provider's ONE read failing closed."""

from __future__ import annotations

import json
from typing import Any

from qualify_api.whatsapp.menus.engine import Inbound
from qualify_api.whatsapp.menus.starter import PAYMENT_ANSWER_NODE_ID, composed_payment_text
from qualify_api.whatsapp.payments import PaymentOption

from . import whatsapp_menu_provider as provider
from . import whatsapp_tab_menu
from .test_whatsapp_menu_answers import _state
from .whatsapp_menu_vm import PAYMENT_ANSWER_AUTO, PAYMENT_ANSWER_CHANGE

_OPTIONS = (
    PaymentOption(id="m1", name="Pago móvil", currency="VES", instructions="Banco 0102"),
    PaymentOption(
        id="m2", name="Efectivo al recibir", currency="", instructions="", pay_on_delivery=True
    ),
)


def _offering(options: Any) -> Any:
    state = _state()
    state._payment_options = list(options)
    state.payments_offered = len(options)
    state._apply(state._form(), edited=False)
    return state


def _payment_answer(state: Any) -> Any:
    rows = [*state.answers.buttons, *state.answers.rows]
    return next(a for a in rows if a.label == "Formas de pago")


def test_without_methods_the_answer_stays_the_owners_and_its_gap_blocks() -> None:
    state = _offering(())
    answer = _payment_answer(state)
    assert not answer.auto_composed and answer.text_editable and answer.has_gaps
    assert state.gap_count == 4  # Horario, Domicilio, Formas de pago, Reservas


def test_with_methods_it_is_composed_read_only_and_no_longer_a_gap() -> None:
    state = _offering(_OPTIONS)
    answer = _payment_answer(state)
    assert answer.auto_composed and not answer.text_editable and not answer.has_gaps
    assert answer.text == composed_payment_text(_OPTIONS)
    assert answer.status_label != "Falta completar"
    assert state.gap_count == 3  # the server ignores that gap too
    assert "Formas de pago" not in state.publish_gaps.answers_text
    # «Quitar las que faltan y publicar» keeps the live answer
    state.strip_gaps_and_publish()
    state.confirm_strip_and_publish()
    assert any(a.label == "Formas de pago" for a in [*state.answers.buttons, *state.answers.rows])


def test_the_preview_answers_with_the_methods_offered(monkeypatch) -> None:
    from . import whatsapp_menu_state as module

    seen: dict[str, Any] = {}
    real = module.preview_turn

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "preview_turn", spy)
    state = _offering(_OPTIONS)
    state._preview_payload = state._valid_payload
    state._turn(Inbound.text("hola"), "hola")
    assert tuple(seen["payment_methods"]) == _OPTIONS  # the engine reads the same methods


def test_step_2_shows_it_read_only_with_the_way_to_change_the_methods() -> None:
    rendered = str(whatsapp_tab_menu.menu_tab())
    for words in (PAYMENT_ANSWER_AUTO, PAYMENT_ANSWER_CHANGE, "auto_composed"):
        assert json.dumps(words)[1:-1] in rendered, words


def test_the_methods_are_read_once_and_a_failure_fails_closed(monkeypatch) -> None:
    import qualify_api.whatsapp.payments as payments

    reads: list[Any] = []

    def active(tenant_id: Any, brand_id: Any) -> tuple[Any, ...]:
        reads.append(brand_id)
        raise RuntimeError("db")

    monkeypatch.setattr(payments, "active_payment_methods", active)
    from uuid import UUID

    assert provider.payment_options(UUID(int=1), UUID(int=2)) is None
    assert provider.payment_options(UUID(int=1), None) == ()
    assert len(reads) == 1
    assert PAYMENT_ANSWER_NODE_ID == "pagos"


def test_the_owners_own_text_is_shown_as_what_goes_out_without_methods() -> None:
    from qualify_api.whatsapp.menus.starter import PAYMENT_ANSWER_UNSET

    from .whatsapp_menu_vm import (
        PAYMENT_ANSWER_FALLBACK,
        PAYMENT_ANSWER_FALLBACK_FIXED,
        payment_fallback,
    )

    # the starter's text still has its «[…]»: the server's fixed sentence goes instead
    answer = _payment_answer(_offering(_OPTIONS))
    assert answer.fallback_text == PAYMENT_ANSWER_UNSET
    assert answer.fallback_label == PAYMENT_ANSWER_FALLBACK_FIXED
    # the owner completed it: their own text is the fallback
    state = _offering(_OPTIONS)
    index = _payment_answer(state).index
    from .whatsapp_menu_vm import answer_set_text

    state._apply(answer_set_text(state._form(), index, "Aceptamos efectivo y Zelle."))
    done = _payment_answer(state)
    assert done.fallback_text == "Aceptamos efectivo y Zelle."
    assert done.fallback_label == PAYMENT_ANSWER_FALLBACK
    assert payment_fallback("") == PAYMENT_ANSWER_UNSET
    rendered = str(whatsapp_tab_menu.menu_tab())
    assert "fallback_label" in rendered and "fallback_text" in rendered


def test_the_payment_pill_comes_first_in_the_row_and_the_header() -> None:
    """At 375 px a third pill drops to a second line: «Pago por revisar» goes first.
    m-25017844: the row carries ONE pill, chosen in the VM (payment beats the window —
    `test_chat_row.py`); the header keeps its order."""
    import inspect

    from . import whatsapp_tab_chats
    from .chat_row_vm import attention_pill

    assert attention_pill(payment_review=True, reply_within_minutes=5, wants_to_buy=False)[0] == (
        "Pago por revisar"
    )
    source = inspect.getsource(whatsapp_tab_chats)
    # m-25027371: the shared header draws the pills, in this order, before the window line.
    head = source.index("state_pill(S.payment.label, S.payment.tone)")
    assert head < source.index("state_pill(thread.mode_label, thread.mode_tone)")
    from . import chat_thread

    shared = inspect.getsource(chat_thread.thread_header)
    assert shared.index("*pills,") < shared.index("*([window] if window is not None else [])")
