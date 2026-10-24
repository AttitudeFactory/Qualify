"""Pure tests for the Chats tab's view-models (WA-11, QUA-210): window pill tones, ticks,
the order card, composer validation, the closed-window disable and the filters.

No Reflex, no Postgres: the backend shapes come from `qualify_api.whatsapp.chats` /
`orders` (both pure dataclasses) and every instant is a fixed value.
"""

from __future__ import annotations

import dataclasses
import typing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.whatsapp.chats import MessageRecord, ThreadSummary, WindowView
from qualify_api.whatsapp.menus.engine import format_money as engine_format_money
from qualify_api.whatsapp.orders import read_order

from .whatsapp_chats_vm import (
    FILTER_CLOSED,
    FILTER_OPEN,
    FILTER_UNREAD,
    MEDIA_AUDIO,
    MEDIA_DOCUMENT,
    MEDIA_EXPIRED,
    MEDIA_IMAGE,
    MEDIA_NOT_CAPTURED,
    MEDIA_NOT_CAPTURED_CODE,
    MEDIA_UNAVAILABLE,
    MEDIA_URL_TTL,
    MEDIA_VIDEO,
    NO_MESSAGES_YET,
    WINDOW_CLOSED_NOTICE,
    WINDOW_CLOSED_PILL,
    AgentVM,
    MediaResolution,
    MessageVM,
    OrderCardVM,
    OrderFieldVM,
    OrderLineVM,
    ThreadRowVM,
    UnsentItem,
    build_agent_vm,
    build_conversation,
    build_message_vm,
    build_order_card,
    build_thread_row,
    composer_enabled,
    failure_label,
    filter_counts,
    filter_label,
    filter_threads,
    format_money,
    initials,
    merge_pages,
    message_time,
    outbox_text,
    relative_time,
    resolution_after,
    validate_buttons,
    validate_compose,
    validate_image,
    validate_text,
    window_pill,
)

ZONE = ZoneInfo("America/Bogota")
NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "credential",
    "cipher",
    "secret",
    "key_id",
    "password",
    "plaintext",
)
_VMS = (AgentVM, ThreadRowVM, MessageVM, OrderCardVM, OrderLineVM, OrderFieldVM)


def _thread(**overrides: object) -> ThreadSummary:
    values: dict[str, object] = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "connection_id": uuid4(),
        "wa_id": "573001234567",
        "contact_name": "Laura Gómez",
        "last_message_preview": "¿Tienen domicilio?",
        "last_message_direction": "inbound",
        "last_message_at": NOW - timedelta(minutes=5),
        "last_inbound_at": NOW - timedelta(minutes=5),
        "unread_count": 2,
        "status": "open",
        "assigned_agent_id": None,
        "automation_paused": False,
        "window": WindowView(open=True, closes_at=NOW + timedelta(hours=23, minutes=55)),
    }
    values.update(overrides)
    return ThreadSummary(**values)  # type: ignore[arg-type]


def _message(**overrides: object) -> MessageRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "direction": "inbound",
        "text": "Hola",
        "posted_at": NOW - timedelta(minutes=3),
        "delivery_status": None,
        "delivery_error_code": None,
        "external_message_id": "wamid.x",
        "media_kind": None,
    }
    values.update(overrides)
    return MessageRecord(**values)  # type: ignore[arg-type]


# --- boundary --------------------------------------------------------------------------


def test_whatsapp_chats_vm_has_no_credential_fields() -> None:
    for vm_cls in _VMS:
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, f"{vm_cls.__name__}.{f.name}"


def test_vms_are_frozen_and_carry_no_raw_datetimes() -> None:
    for vm_cls in _VMS:
        assert vm_cls.__dataclass_params__.frozen, vm_cls.__name__  # type: ignore[attr-defined]
        hints = typing.get_type_hints(vm_cls)
        for f in dataclasses.fields(vm_cls):
            assert hints[f.name] is not datetime, f"{vm_cls.__name__}.{f.name}"
            assert "datetime" not in str(hints[f.name]), f"{vm_cls.__name__}.{f.name}"


# --- window pill ---------------------------------------------------------------------


def test_window_pill_open_is_ok_with_the_local_closing_time() -> None:
    label, tone = window_pill(True, NOW + timedelta(hours=5), NOW, ZONE)
    assert (label, tone) == ("Puedes escribirle hasta las 5:00 p. m.", "ok")


def test_window_pill_closing_within_the_hour_is_warn_in_minutes() -> None:
    label, tone = window_pill(True, NOW + timedelta(minutes=41, seconds=10), NOW, ZONE)
    assert (label, tone) == ("Responde en los próximos 42 min", "warn")
    assert window_pill(True, NOW + timedelta(seconds=5), NOW, ZONE) == (
        "Responde en el próximo minuto",
        "warn",
    )


def test_window_pill_closed_is_neutral() -> None:
    assert window_pill(False, None, NOW, ZONE) == ("Solo con mensaje aprobado", "neutral")
    # A stale "open" whose instant already passed reads closed, not negative minutes.
    assert window_pill(True, NOW - timedelta(minutes=1), NOW, ZONE)[1] == "neutral"


def test_window_closed_notice_says_what_happened_and_what_comes_next() -> None:
    """m-24842993 + m-24848535: what happened, and that an approved message still goes."""
    assert WINDOW_CLOSED_NOTICE == (
        "Pasaron más de 24 horas desde su último mensaje. "
        "WhatsApp solo deja escribirle con un mensaje aprobado."
    )


def test_failure_label_never_shows_codes() -> None:
    expected = "No se entregó: pasaron más de 24 horas desde su último mensaje."
    assert failure_label("window_closed") == expected
    assert failure_label("131047") == expected
    assert failure_label("130429") == "No se entregó"
    assert failure_label(None) == "No se entregó"


def test_closed_chat_copy_never_says_ventana_or_plantillas() -> None:
    """With the chat expired, nothing the owner reads names the internal concepts."""
    texts = [
        WINDOW_CLOSED_NOTICE,
        WINDOW_CLOSED_PILL,
        window_pill(False, None, NOW, ZONE)[0],
        failure_label("window_closed"),
        failure_label("131047"),
        build_message_vm(_message(text=None, media_kind="template"), now=NOW, zone=ZONE).text,
    ]
    for text in texts:
        lowered = text.lower()
        assert "ventana" not in lowered, text
        assert "plantilla" not in lowered, text


# --- thread rows ---------------------------------------------------------------------


def test_thread_row_maps_name_number_preview_unread_and_mode() -> None:
    row = build_thread_row(_thread(), now=NOW, zone=ZONE)
    assert row.title == "Laura Gómez"
    assert row.subtitle == "+573001234567"
    assert row.preview == "¿Tienen domicilio?"
    assert row.time_label == "hace 5 min"
    assert (row.unread_label, row.has_unread) == ("2", True)
    assert (row.window_tone, row.window_open) == ("ok", True)
    assert (row.mode_label, row.mode_tone) == ("Responde el menú", "neutral")
    assert row.agent_initials == ""


def test_thread_row_without_name_shows_the_number_and_outbound_prefix() -> None:
    row = build_thread_row(
        _thread(contact_name=None, last_message_direction="outbound", unread_count=0),
        now=NOW,
        zone=ZONE,
    )
    assert row.title == "+573001234567"
    assert row.subtitle == ""
    assert row.preview == "Tú: ¿Tienen domicilio?"
    assert row.unread_label == ""


def test_thread_row_paused_assigned_and_closed() -> None:
    agent_id = uuid4()
    agents = {str(agent_id): build_agent_vm(str(agent_id), "Ana María Pérez", "a@x.co")}
    row = build_thread_row(
        _thread(automation_paused=True, assigned_agent_id=agent_id, status="closed"),
        now=NOW,
        zone=ZONE,
        agents=agents,
    )
    assert (row.mode_label, row.mode_tone) == ("Respondes tú", "info")
    assert (row.agent_initials, row.agent_name) == ("AP", "Ana María Pérez")
    assert row.is_closed


def test_thread_row_closed_window_and_empty_thread() -> None:
    row = build_thread_row(
        _thread(
            window=WindowView(open=False, closes_at=None),
            last_message_preview=None,
            last_message_direction=None,
            last_message_at=None,
        ),
        now=NOW,
        zone=ZONE,
    )
    assert (row.window_label, row.window_tone, row.window_open) == (
        WINDOW_CLOSED_PILL,
        "neutral",
        False,
    )
    assert row.preview == NO_MESSAGES_YET
    assert row.time_label == ""


def test_relative_time_words() -> None:
    assert relative_time(NOW - timedelta(seconds=20), NOW, ZONE) == "ahora"
    assert relative_time(NOW - timedelta(hours=3), NOW, ZONE) == "hace 3 h"
    assert relative_time(NOW - timedelta(days=1), NOW, ZONE) == "ayer"
    assert relative_time(NOW - timedelta(days=3), NOW, ZONE) == "dom"
    assert relative_time(NOW - timedelta(days=30), NOW, ZONE) == "14 sep"
    assert relative_time(NOW - timedelta(days=400), NOW, ZONE) == "9 sep 2025"


def test_initials() -> None:
    assert initials("Ana María Pérez") == "AP"
    assert initials("bianki") == "B"
    assert initials("ana.perez@x.co") == "AP"
    assert initials("  ") == "?"


# --- filters -------------------------------------------------------------------------


def test_filters_split_open_closed_and_unread() -> None:
    rows = [
        build_thread_row(_thread(id=uuid4(), unread_count=1), now=NOW, zone=ZONE),
        build_thread_row(_thread(id=uuid4(), unread_count=0), now=NOW, zone=ZONE),
        build_thread_row(_thread(id=uuid4(), status="closed", unread_count=3), now=NOW, zone=ZONE),
    ]
    assert len(filter_threads(rows, FILTER_OPEN)) == 2
    assert len(filter_threads(rows, FILTER_CLOSED)) == 1
    assert len(filter_threads(rows, FILTER_UNREAD)) == 2
    assert len(filter_threads(rows, "junk")) == 2
    assert filter_counts(rows) == {FILTER_OPEN: 2, FILTER_CLOSED: 1, FILTER_UNREAD: 2}
    assert filter_label(FILTER_UNREAD, 2) == "Sin leer · 2"
    assert filter_label(FILTER_CLOSED, 0) == "Cerrados"


# --- messages and ticks --------------------------------------------------------------


def test_ticks_by_delivery_status() -> None:
    cases = {
        "sent": ("sent", "Enviado"),
        "delivered": ("delivered", "Entregado"),
        "read": ("read", "Leído"),
        None: ("sent", "Enviado"),
    }
    for status, expected in cases.items():
        vm = build_message_vm(
            _message(direction="outbound", delivery_status=status), now=NOW, zone=ZONE
        )
        assert (vm.tick, vm.tick_label) == expected
        assert vm.error_label == ""


def test_failed_tick_explains_without_the_meta_code() -> None:
    vm = build_message_vm(
        _message(direction="outbound", delivery_status="failed", delivery_error_code="131026"),
        now=NOW,
        zone=ZONE,
    )
    assert vm.tick == "failed"
    assert "131026" not in vm.error_label
    assert vm.error_label.startswith("No se entregó: pasaron más de 24 horas")


def test_inbound_has_no_tick_and_uncaptured_media_is_a_placeholder() -> None:
    """A text-less inbound message without `has_media` (stored before 0061) keeps the
    neutral chip; outbound media is worded by the body's type."""
    vm = build_message_vm(_message(text=None, media_kind="image"), now=NOW, zone=ZONE)
    assert vm.tick == ""
    assert vm.is_media_placeholder
    assert vm.text == MEDIA_NOT_CAPTURED
    assert vm.media_control == ""
    out = build_message_vm(
        _message(direction="outbound", text=None, media_kind="image"), now=NOW, zone=ZONE
    )
    assert (out.text, out.is_media_placeholder, out.media_control) == ("[imagen]", False, "")


def test_non_file_kinds_are_worded_by_kind() -> None:
    vm = build_message_vm(_message(text=None, media_kind="location"), now=NOW, zone=ZONE)
    assert (vm.text, vm.is_media_placeholder) == ("[ubicación]", True)


# --- inbound media (0061) -----------------------------------------------------------


def _media(kind: str, mime: str | None = None, **overrides: object) -> MessageRecord:
    values: dict[str, object] = {"text": None, "has_media": True, "media_mime": mime}
    values.update(overrides)
    return _message(media_kind=kind, **values)


@pytest.mark.parametrize(
    ("kind", "mime", "control", "action"),
    [
        ("image", "image/jpeg", MEDIA_IMAGE, "Ver imagen"),
        ("sticker", "image/webp", MEDIA_IMAGE, "Ver imagen"),
        ("audio", "audio/ogg; codecs=opus", MEDIA_AUDIO, "Escuchar audio"),
        ("video", "video/mp4", MEDIA_VIDEO, "Ver video"),
        ("document", "application/pdf", MEDIA_DOCUMENT, "Descargar PDF"),
        (
            "document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            MEDIA_DOCUMENT,
            "Descargar Excel",
        ),
        ("document", "application/x-unknown", MEDIA_DOCUMENT, "Descargar archivo"),
        ("document", None, MEDIA_DOCUMENT, "Descargar archivo"),
    ],
)
def test_media_controls_by_kind_before_any_request(
    kind: str, mime: str | None, control: str, action: str
) -> None:
    vm = build_message_vm(_media(kind, mime), now=NOW, zone=ZONE)
    assert (vm.media_control, vm.media_action) == (control, action)
    assert vm.media_can_request and not vm.media_loading
    assert vm.media_src == "" and vm.media_notice == ""
    assert not vm.is_media_placeholder and vm.text == ""


def test_a_caption_stays_under_the_media_control() -> None:
    vm = build_message_vm(_media("image", "image/jpeg", text="Mi pedido"), now=NOW, zone=ZONE)
    assert (vm.media_control, vm.text, vm.is_media_placeholder) == (MEDIA_IMAGE, "Mi pedido", False)


def test_loading_marks_only_that_message() -> None:
    record = _media("image", "image/jpeg")
    vm = build_message_vm(record, now=NOW, zone=ZONE, loading=[str(record.id)])
    other = build_message_vm(_media("image"), now=NOW, zone=ZONE, loading=[str(record.id)])
    assert vm.media_loading and not other.media_loading


def test_a_fresh_url_is_shown_and_an_expired_one_is_asked_again() -> None:
    record = _media("audio", "audio/ogg")
    key = str(record.id)
    fresh = {key: resolution_after("https://app.example/public/media/t1", NOW)}
    vm = build_message_vm(record, now=NOW, zone=ZONE, media=fresh)
    assert vm.media_src == "https://app.example/public/media/t1"
    assert not vm.media_can_request
    later = NOW + MEDIA_URL_TTL + timedelta(seconds=1)
    stale = build_message_vm(record, now=later, zone=ZONE, media=fresh)
    assert stale.media_src == "" and stale.media_can_request
    # The token lives 15 min; the cache must give it up before that.
    assert timedelta(minutes=15) > MEDIA_URL_TTL


def test_media_expired_is_neutral_and_final() -> None:
    record = _media("image", "image/jpeg")
    outcome = {str(record.id): MediaResolution(error=MEDIA_EXPIRED)}
    vm = build_message_vm(record, now=NOW, zone=ZONE, media=outcome)
    assert (vm.media_notice, vm.media_notice_tone) == (
        "El archivo ya no está disponible en WhatsApp",
        "neutral",
    )
    assert not vm.media_can_request


def test_media_unavailable_is_warn_with_a_retry() -> None:
    record = _media("video", "video/mp4")
    outcome = {str(record.id): MediaResolution(error=MEDIA_UNAVAILABLE)}
    vm = build_message_vm(record, now=NOW, zone=ZONE, media=outcome)
    assert (vm.media_notice, vm.media_notice_tone) == (
        "No se pudo traer el archivo; reintentar",
        "warn",
    )
    assert vm.media_can_request and vm.media_action == "Reintentar"


def test_media_not_captured_falls_back_to_the_chip() -> None:
    record = _media("image", "image/jpeg")
    outcome = {str(record.id): MediaResolution(error=MEDIA_NOT_CAPTURED_CODE)}
    vm = build_message_vm(record, now=NOW, zone=ZONE, media=outcome)
    assert vm.media_control == "" and vm.is_media_placeholder
    assert vm.text == MEDIA_NOT_CAPTURED


def test_outbound_never_gets_a_media_control() -> None:
    vm = build_message_vm(
        _message(direction="outbound", text=None, media_kind="image", has_media=True),
        now=NOW,
        zone=ZONE,
    )
    assert vm.media_control == "" and vm.text == "[imagen]"


def test_the_conversation_threads_media_state_through() -> None:
    record = _media("image", "image/jpeg")
    [vm] = build_conversation(
        [record],
        [],
        now=NOW,
        zone=ZONE,
        media={str(record.id): MediaResolution(error=MEDIA_UNAVAILABLE)},
    )
    assert vm.media_notice_tone == "warn"


def test_message_time_today_yesterday_and_older() -> None:
    assert message_time(NOW - timedelta(minutes=3), NOW, ZONE) == "11:57"
    assert message_time(NOW - timedelta(days=1), NOW, ZONE) == "ayer 12:00"
    assert message_time(NOW - timedelta(days=9), NOW, ZONE) == "5 oct 12:00"


def test_conversation_merges_unsent_outbox_rows_chronologically() -> None:
    messages = [
        _message(posted_at=NOW - timedelta(minutes=10)),
        _message(posted_at=NOW - timedelta(minutes=2)),
    ]
    unsent = [
        UnsentItem(id="a", status="pending", text="Ya va", created_at=NOW - timedelta(minutes=1)),
        UnsentItem(
            id="b",
            status="failed",
            text="Te escribo",
            created_at=NOW - timedelta(minutes=5),
            error_code="window_closed",
        ),
    ]
    vms = build_conversation(messages, unsent, now=NOW, zone=ZONE)
    assert [v.tick for v in vms] == ["", "failed", "", "queued"]
    assert vms[1].error_label.startswith("No se entregó")
    assert vms[3].tick_label == "Por enviar"


def test_merge_pages_keeps_older_loaded_messages() -> None:
    a = _message(posted_at=NOW - timedelta(hours=3))
    b = _message(posted_at=NOW - timedelta(hours=2))
    c = _message(posted_at=NOW - timedelta(hours=1))
    d = _message(posted_at=NOW)
    merged = merge_pages([a, b, c], [c, d])
    assert [m.id for m in merged] == [a.id, b.id, c.id, d.id]
    assert merge_pages([a], []) == [a]


def test_outbox_text_reads_each_body_type() -> None:
    assert outbox_text({"type": "text", "text": {"body": "Hola"}}) == "Hola"
    assert outbox_text({"type": "image", "image": {"link": "x", "caption": "Menú"}}) == (
        "[imagen] Menú"
    )
    interactive = {
        "type": "interactive",
        "interactive": {
            "body": {"text": "¿Confirmas?"},
            "action": {"buttons": [{"type": "reply", "reply": {"id": "1", "title": "Sí"}}]},
        },
    }
    assert outbox_text(interactive) == "¿Confirmas?\n[Sí]"
    assert outbox_text({"type": "template"}) == "[mensaje]"


# --- order card ----------------------------------------------------------------------

_CONTEXT = {
    "_order": {
        "items": [
            {
                "product_id": "p1",
                "name": "Hamburguesa",
                "qty": 2,
                "unit_price": "12500",
                "currency": "COP",
            },
            {"product_id": "p2", "name": "Limonada", "qty": 1, "unit_price": "10000"},
        ],
        "total": "35000.00",
        "currency": "COP",
        "confirmed_at": "2026-10-14T16:30:00+00:00",
        "collected": {"direccion": "Calle 10 # 5-20", "notas": ""},
        "source_message_id": "wamid.1",
    }
}


def test_order_card_from_thread_context() -> None:
    card = build_order_card(read_order(_CONTEXT), now=NOW, zone=ZONE)
    assert card.present
    assert [(line.label, line.amount) for line in card.lines] == [
        ("2 × Hamburguesa", "COP 25.000"),
        ("1 × Limonada", "COP 10.000"),
    ]
    assert card.total_label == "COP 35.000"
    assert card.items_label == "3 productos"
    assert card.collected == [OrderFieldVM(label="Dirección", value="Calle 10 # 5-20")]
    assert card.confirmed_label == "Confirmado 11:30"


def test_order_card_puts_the_address_first() -> None:
    context = {
        "_order": {
            **_CONTEXT["_order"],
            "collected": {"notas": "Sin cebolla", "zona": "Norte", "direccion": "Calle 1"},
        }
    }
    card = build_order_card(read_order(context), now=NOW, zone=ZONE)
    assert [f.label for f in card.collected] == ["Dirección", "Notas", "Zona"]


def test_order_card_absent_without_an_order() -> None:
    assert not build_order_card(read_order({}), now=NOW, zone=ZONE).present
    assert not build_order_card(None, now=NOW, zone=ZONE).present


def test_format_money_agrees_with_the_engine() -> None:
    for amount in ("35000", "9.99", "1234567.5", "0"):
        for currency in ("COP", None):
            assert format_money(Decimal(amount), currency) == engine_format_money(
                Decimal(amount), currency
            )


# --- composer ------------------------------------------------------------------------


def test_text_validation() -> None:
    assert validate_text("Hola") == ""
    assert validate_text("   ") != ""
    assert validate_text("x" * 4097) != ""


def test_buttons_validation() -> None:
    assert validate_buttons("¿Qué prefieres?", ["Sí", "No", ""]) == ""
    assert validate_buttons("", ["Sí"]) != ""
    assert validate_buttons("Elige", ["", " "]) == "Añade al menos un botón."
    assert "botones" in validate_buttons("Elige", ["a", "b", "c", "d"])
    assert "20" in validate_buttons("Elige", ["x" * 21])
    assert validate_buttons("Elige", ["Sí", "sí"]) == "Cada botón necesita un texto distinto."


def test_image_validation() -> None:
    assert validate_image("https://cdn.example.com/menu.jpg", "Menú") == ""
    assert validate_image("", "") != ""
    assert validate_image("http://cdn.example.com/a.jpg", "") != ""
    assert validate_image("https://cdn.example.com/a.jpg", "x" * 1025) != ""


def test_validate_compose_dispatches_by_mode() -> None:
    assert validate_compose("buttons", "Elige", ["Sí"], "", "") == ""
    assert validate_compose("image", "", [], "https://cdn.example.com/a.jpg", "") == ""
    assert validate_compose("text", "", [], "", "") == "Escribe un mensaje."


def test_closed_window_disables_the_composer() -> None:
    assert composer_enabled(True, True)
    assert not composer_enabled(False, True)
    assert not composer_enabled(True, False)


# --- the tab -------------------------------------------------------------------------


def test_the_tab_talks_to_the_state_only() -> None:
    """The page imports neither the provider nor any backend module: it reaches Postgres
    and the services only through `WhatsAppChatsState`."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parent / "whatsapp_tab_chats.py").read_text())
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("provider" in name or name.startswith("qualify_api") for name in imported)


def test_the_tab_renders_list_conversation_and_composer() -> None:
    import json

    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Elige una conversación",
        "Tomar el control",
        "Devolver al menú",
        "Cerrar",
        "Reabrir",
        "Pedido listo",
        "Cargar anteriores",
        "Enviar",
        "Botones",
        "Imagen por enlace",
        "Aún no hay conversaciones en este número",
        "Imagen recibida",
        "Abrir original",
        "Abrir video",
    ):
        assert present(text), text


def test_the_tab_wires_media_through_the_state() -> None:
    """The media button, the thumbnail and the lightbox all go through state events —
    the lightbox URL is the state's, never one the browser passes in."""
    from .whatsapp_tab_chats import chats_tab

    rendered = str(chats_tab().render())
    for handler in ("request_media", "open_lightbox", "set_lightbox_open", "lightbox_url"):
        assert handler in rendered, handler
    assert "<audio" in rendered or '"audio"' in rendered


# --- m-24848535: approved message from an expired chat --------------------------------


def test_approved_message_copy_is_exact() -> None:
    from .whatsapp_chats_vm import ASK_CONSENT_LABEL, PROMOTIONS_NEED_CONSENT, SEND_APPROVED_LABEL

    assert SEND_APPROVED_LABEL == "Enviar un mensaje aprobado"
    assert PROMOTIONS_NEED_CONSENT == (
        "Para enviarle promociones, esta persona tiene que aceptar recibirlas."
    )
    assert ASK_CONSENT_LABEL == "Pedirle que acepte"


def test_approved_message_copy_speaks_the_owners_words() -> None:
    from . import whatsapp_chats_vm as vm

    texts = [
        vm.SEND_APPROVED_LABEL,
        vm.SEND_APPROVED_DESCRIPTION,
        vm.PROMOTIONS_NEED_CONSENT,
        vm.ASK_CONSENT_LABEL,
        vm.NO_FOLLOWUPS,
        vm.CREATE_APPROVED_LABEL,
        vm.NO_PERMISSION_NOTICE,
        vm.TEMPLATE_PICK_HINT,
        vm.TEMPLATE_FILL_HINT,
        vm.TEMPLATE_PREVIEW_LABEL,
        vm.TEMPLATE_FIELDS_LABEL,
        vm.WINDOW_CLOSED_PILL,
        vm.failure_label("opted_out"),
        *(label for label, _tone in vm._TEMPLATE_KIND.values()),
    ]
    banned = ("plantilla", "ventana", "opt-in", "template", "marketing", " post", "lead")
    for text in texts:
        assert not any(word in text.lower() for word in banned), text
    # Assisted, never autonomous: the description says it leaves on the owner's tap.
    assert "«Enviar»" in vm.SEND_APPROVED_DESCRIPTION
    assert vm.CREATE_APPROVED_ROUTE == "/whatsapp?tab=plantillas"


def test_template_choice_and_fields_vm() -> None:
    from dataclasses import dataclass

    from .whatsapp_chats_vm import (
        build_template_choice,
        build_template_fields,
        preview_values,
        template_fields_complete,
        template_title,
    )

    @dataclass(frozen=True)
    class Option:
        template_id: str
        name: str
        category: str
        preview: str
        is_consent_request: bool

    @dataclass(frozen=True)
    class Variable:
        component: str
        key: str
        named: bool

        @property
        def id(self) -> str:
            return f"{self.component}:{self.key}"

    choice = build_template_choice(Option("t1", "seguimiento_pedido", "utility", "Hola", False))
    assert (choice.title, choice.kind_label, choice.kind_tone) == (
        "Seguimiento pedido",
        "Seguimiento",
        "info",
    )
    promo = build_template_choice(Option("t2", "promo", "marketing", "", False))
    assert promo.kind_label == "Promoción"
    assert template_title("") == "Mensaje aprobado"

    fields = build_template_fields(
        [
            Variable("body", "nombre", True),
            Variable("body", "2", False),
            Variable("header", "1", False),
        ],
        {"body:nombre": "Ana"},
    )
    assert [f.label for f in fields] == [
        "Nombre del cliente",
        "Dato 2 del mensaje",
        "Dato 1 del mensaje (arriba del mensaje)",
    ]
    assert [f.value for f in fields] == ["Ana", "", ""]
    assert [f.example for f in fields] == ["", "", ""]
    with_example = build_template_fields(
        [Variable("body", "2", False)], {}, {"body:2": "2x1 en helados"}
    )
    assert with_example[0].example == "Ejemplo: 2x1 en helados"
    # The preview shows «[label]» in each gap, never a raw {{…}} (UX review).
    gaps = preview_values(
        [Variable("body", "nombre", True), Variable("body", "2", False)],
        {"body:nombre": "Ana", "body:2": "  "},
    )
    assert gaps == {"body:nombre": "Ana", "body:2": "[Dato 2 del mensaje]"}
    assert not template_fields_complete(fields)
    assert template_fields_complete([])
