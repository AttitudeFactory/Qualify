"""m-24955785 — the «+» of WhatsApp's chat composer (`ui.orbit_menu`).

The primitive's rules (2–6 options, icon AND text ≤ 16 characters, `data-orbit-key`,
side top / align start / never flipped), the composer's five options in the spec's order
and wording, the menu not drawn outside the 24-hour window, and choosing an option
never sending anything.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest

from .ui import OrbitItem, orbit_menu
from .ui.primitives import ORBIT_FOCUS_SCRIPT
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import (
    EMPTY_THREAD,
    MENU_HELP,
    NOTHING_SENT_UNTIL,
    PAYMENT_REVIEW_HELP,
    PICK_DIRECTIONS,
    PICK_MEDIA,
    PICK_MENU,
    PICK_MENU_LABEL,
    PICK_OFFER,
    PICK_PAYMENTS,
    PICK_PHOTO,
    PICK_PIECES,
    PICK_PRODUCTS,
    PICK_SOURCE_CARDS,
    REVIEW_HELP,
)


def _items(n: int, text: str = "Opción") -> list[OrbitItem]:
    return [OrbitItem(key=f"k{i}", icon="package", text=text, on_select=None) for i in range(n)]


def test_the_primitive_takes_two_to_six_options() -> None:
    for n in (2, 6):
        orbit_menu("Enviar algo", _items(n))
    for n in (1, 7):
        with pytest.raises(ValueError):
            orbit_menu("Enviar algo", _items(n))


def test_an_option_needs_a_text_of_sixteen_characters_at_most() -> None:
    orbit_menu("Enviar algo", _items(2, "x" * 16))
    for bad in ("x" * 17, "   "):
        with pytest.raises(ValueError):
            orbit_menu("Enviar algo", _items(2, bad))


def test_it_opens_above_never_flipped_and_marks_each_option() -> None:
    rendered = str(orbit_menu("Enviar algo al cliente", _items(3)))
    for marker in (
        '"top"',
        '"start"',
        "avoidCollisions:false",
        "data-orbit-key",
        "data-orbit-trigger",
        "q-orbit-pill",
    ):
        assert marker in rendered.replace(" ", ""), marker
    assert "Enviar algo al cliente" in rendered


def test_the_composer_offers_the_six_approved_rows_in_order() -> None:
    """m-24945889 (founder, 2026-11-08): Tus productos · Tu oferta · Tu menú · Formas de
    pago · Cómo llegar · Fotos y videos — six, `orbit_menu`'s maximum."""
    assert [(k, i, t) for k, i, t in PICK_SOURCE_CARDS] == [
        (PICK_PRODUCTS, "package", "Tus productos"),
        (PICK_OFFER, "tag", "Tu oferta"),
        (PICK_MENU, "list", "Tu menú"),
        (PICK_PAYMENTS, "wallet", "Formas de pago"),
        (PICK_DIRECTIONS, "map-pin", "Cómo llegar"),
        (PICK_MEDIA, "images", "Fotos y videos"),
    ]
    assert len(PICK_SOURCE_CARDS) == 6
    assert PICK_PIECES not in {k for k, _i, _t in PICK_SOURCE_CARDS}
    assert PICK_PHOTO not in {k for k, _i, _t in PICK_SOURCE_CARDS}
    assert all(len(text) <= 16 for _k, _i, text in PICK_SOURCE_CARDS)
    assert PICK_MENU_LABEL == "Enviar algo al cliente"
    from . import whatsapp_tab_chats

    rendered = str(whatsapp_tab_chats.chats_tab())
    menu = rendered[rendered.index("data-orbit-trigger") :]
    order = [menu.index(json.dumps(t)[1:-1]) for _k, _i, t in PICK_SOURCE_CARDS]
    assert order == sorted(order)  # top to bottom: show, order, pay
    # each option is wired to open the panel at its step
    assert "open_pick" in rendered and "Foto o menú" not in rendered


def test_the_menu_is_only_drawn_in_the_live_composer() -> None:
    """Outside the 24 h the whole composer is `_expired_composer`: no «+» to disable."""
    from . import whatsapp_tab_chats

    live = inspect.getsource(whatsapp_tab_chats._live_composer)
    expired = inspect.getsource(whatsapp_tab_chats._expired_composer)
    assert "_pick_menu_button()" in live and "_pick_menu_button" not in expired
    assert "_pick_menu_button" not in inspect.getsource(whatsapp_tab_chats._composer).replace(
        "_live_composer", ""
    )


def test_choosing_an_option_opens_never_sends() -> None:
    state = WhatsAppChatsState()
    state.rows = [
        dataclasses.replace(
            EMPTY_THREAD, thread_id="t", window_open=True, window_label="x", window_tone="ok"
        )
    ]
    state.open_thread_id = "t"
    events = state.open_pick(PICK_PRODUCTS)
    assert state.pick_open and state.pick_step == 1 and not state.pick_sending
    assert "send_pick" not in str(events)
    assert state.open_pick("pegar-un-enlace") is None  # an unknown option does nothing
    events = state.close_picker()
    assert ORBIT_FOCUS_SCRIPT.split("(")[0] in str(events) or "data-orbit-trigger" in str(events)


def test_every_review_says_nothing_goes_without_enviar() -> None:
    for help_text in (REVIEW_HELP, PAYMENT_REVIEW_HELP, MENU_HELP):
        assert NOTHING_SENT_UNTIL in help_text


def test_the_stagger_index_compiles_to_a_style_mapping_never_a_string() -> None:
    """React refuses a string `style` (and Radix's Slot spreads it into character keys):
    the index must reach the compiled JSX as a mapping."""
    rendered = str(orbit_menu("Enviar algo", _items(3)))
    compact = rendered.replace(" ", "")
    assert 'style:"' not in compact and "style:'" not in compact
    for n in ("2", "1", "0"):  # nearest to the button first
        assert f'["--q-orbit-i"]:"{n}"' in compact, n
    menu = orbit_menu("Enviar algo", _items(2))
    item = menu.children[1].children[0]  # content → first option
    assert isinstance(item.style, dict) and "--q-orbit-i" in item.style


def test_an_address_from_before_the_plus_is_tidied_not_reopened() -> None:
    from types import SimpleNamespace
    from unittest.mock import PropertyMock, patch

    state = WhatsAppChatsState()
    router = SimpleNamespace(
        url=SimpleNamespace(query_parameters={"flujo": "foto-menu", "paso": "2"})
    )
    with patch.object(WhatsAppChatsState, "router", new_callable=PropertyMock, return_value=router):
        event = state.restore_picker()
    assert "foto-menu" in str(event) and not state.pick_open
