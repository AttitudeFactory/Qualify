"""Network-free tests for the `/whatsapp` screen shell (WA-12).

They pin:
1. The VM boundary: no credential-bearing field, frozen, and no raw datetime anywhere —
   every date reaches the client pre-formatted.
2. The Meta enum → (label, tone) mapping uses design-system tones only, and an unknown
   enum value surfaces as itself instead of disappearing.
3. The QR «canal» prefixes — a contract WA-17 measures, so a silent edit fails here.
4. Graph errors show the Meta code only; an auth error shows `WHATSAPP_RECONNECT_HINT`.
5. The shell renders, the Chats/Menú placeholders exist behind the agreed hooks, the
   route is registered behind `require_login`, and the nav item sits after Conexiones.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing
from datetime import datetime

import pytest
import reflex as rx

from . import whatsapp_page, whatsapp_tab_chats, whatsapp_tab_menu
from .connections_vm import WHATSAPP_RECONNECT_HINT
from .ui.layout import NAV_BASE, NAV_ITEMS
from .whatsapp_vm import (
    DEFAULT_TAB,
    EMPTY_NUMBER,
    EMPTY_PROFILE,
    NEVER_CHECKED,
    NO_INBOUND,
    QR_CHANNELS,
    TAB_CONNECTION,
    TAB_QR,
    TABS,
    VERTICAL_KEYS,
    BusinessProfileVM,
    ProfileForm,
    QrCodeVM,
    WhatsAppNumberVM,
    build_number_vm,
    build_profile_vm,
    build_qr_vm,
    compose_qr_message,
    graph_error_notice,
    name_status_display,
    platform_status_display,
    qr_channel_label,
    quality_display,
    resolve_tab,
    tier_display,
    validate_profile_form,
)

_HERE = pathlib.Path(__file__).parent
_FORBIDDEN_FIELD_FRAGMENTS = (
    "token",
    "credential",
    "cipher",
    "secret",
    "key_id",
    "password",
    "plaintext",
)
_VMS = (WhatsAppNumberVM, BusinessProfileVM, QrCodeVM, ProfileForm)
_TONES = {"ok", "warn", "error", "info", "neutral"}


def _number(**overrides: object) -> WhatsAppNumberVM:
    values: dict[str, object] = {
        "connection_id": "c-1",
        "status": "active",
        "display_phone_number": "+57 300 1234567",
        "verified_name": "Bianki",
        "brand": "Bianki",
        "quality_rating": "GREEN",
        "messaging_limit_tier": "TIER_1K",
        "name_status": "APPROVED",
        "platform_status": "CONNECTED",
        "last_health_checked_at": datetime(2026, 10, 14, 9, 30),
        "last_synced_at": datetime(2026, 10, 14, 9, 31),
        "last_inbound_at": None,
    }
    values.update(overrides)
    return build_number_vm(**values)  # type: ignore[arg-type]


# --- 1. the VM boundary ----------------------------------------------------------------


def test_whatsapp_vm_has_no_credential_fields() -> None:
    for vm_cls in _VMS:
        for f in dataclasses.fields(vm_cls):
            lowered = f.name.lower()
            for fragment in _FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, (
                    f"{vm_cls.__name__}.{f.name} looks credential-bearing "
                    f"(matched '{fragment}') — the VM is the security boundary."
                )


def test_vms_are_frozen_and_carry_strings_only() -> None:
    """Frozen (the state replaces, never mutates) and every field a `str`: no raw
    datetime, no number the client would have to format."""
    for vm_cls in _VMS:
        assert vm_cls.__dataclass_params__.frozen, f"{vm_cls.__name__} must be frozen"  # type: ignore[attr-defined]
        hints = typing.get_type_hints(vm_cls)
        for f in dataclasses.fields(vm_cls):
            assert hints[f.name] is str, f"{vm_cls.__name__}.{f.name} is {hints[f.name]}"


def test_number_vm_preformats_dates_with_fallbacks() -> None:
    vm = _number()
    assert vm.last_health_checked_at == "14 Oct 2026, 09:30"
    assert vm.last_synced_at == "14 Oct 2026, 09:31"
    assert vm.last_inbound_at == NO_INBOUND
    never = _number(last_health_checked_at=None)
    assert never.last_health_checked_at == NEVER_CHECKED


def test_number_label_composes_the_verified_name() -> None:
    assert _number().label == "+57 300 1234567 · Bianki"
    assert _number(verified_name=None).label == "+57 300 1234567"
    assert _number(brand=None).brand == "Sin marca"


# --- 2. enum → (label, tone) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "tone"),
    [("active", "ok"), ("degraded", "warn"), ("revoked", "error"), ("weird", "neutral")],
)
def test_connection_status_tones(status: str, tone: str) -> None:
    assert _number(status=status).status_tone == tone


@pytest.mark.parametrize(
    ("rating", "tone"),
    [
        ("GREEN", "ok"),
        ("YELLOW", "warn"),
        ("RED", "error"),
        ("UNKNOWN", "neutral"),
        (None, "neutral"),
    ],
)
def test_quality_tones(rating: str | None, tone: str) -> None:
    assert quality_display(rating)[1] == tone


def test_every_mapping_uses_design_system_tones_only() -> None:
    for display in (quality_display, name_status_display, platform_status_display):
        for value in ("GREEN", "YELLOW", "RED", "APPROVED", "DECLINED", "CONNECTED", "BANNED"):
            assert display(value)[1] in _TONES
    vm = _number()
    for field in ("status_tone", "quality_tone", "name_status_tone", "platform_status_tone"):
        assert getattr(vm, field) in _TONES


def test_unknown_enum_values_surface_as_themselves() -> None:
    assert quality_display("PURPLE") == ("PURPLE", "neutral")
    assert tier_display("TIER_2K") == "TIER_2K"
    assert platform_status_display("NEW_STATE") == ("NEW_STATE", "neutral")


def test_tier_labels() -> None:
    assert tier_display("TIER_1K") == "1.000 conversaciones al día"
    assert tier_display("TIER_UNLIMITED") == "Sin límite"
    assert tier_display(None) == "Sin dato"


# --- profile -----------------------------------------------------------------------------


def test_profile_vm_splits_websites_and_drops_unknown_vertical() -> None:
    vm = build_profile_vm(
        about="Pastelería",
        address=None,
        description=None,
        email=None,
        websites=("https://a.co",),
        vertical="UNDEFINED",
        profile_picture_url=None,
    )
    assert (vm.website_1, vm.website_2) == ("https://a.co", "")
    assert vm.vertical == ""
    assert vm.address == "" and vm.picture_url == ""
    assert (
        build_profile_vm(
            about=None,
            address=None,
            description=None,
            email=None,
            websites=(),
            vertical="restaurant",
            profile_picture_url=None,
        ).vertical
        == "RESTAURANT"
    )


def _form(**overrides: str) -> ProfileForm:
    values = {
        "about": "Pastelería artesanal",
        "address": "",
        "description": "",
        "email": "",
        "website_1": "",
        "website_2": "",
        "vertical": "",
    }
    values.update(overrides)
    return ProfileForm(**values)


def test_profile_validation() -> None:
    assert validate_profile_form(_form()) == ""
    assert "139" in validate_profile_form(_form(about="x" * 140))
    assert "correo" in validate_profile_form(_form(email="no-at-sign"))
    assert "https://" in validate_profile_form(_form(website_1="bianki.co"))
    assert validate_profile_form(_form(website_2="https://bianki.co")) == ""
    assert validate_profile_form(_form(vertical="NOT_A_VERTICAL")) != ""
    assert all(validate_profile_form(_form(vertical=v)) == "" for v in VERTICAL_KEYS)


# --- 3. QR channels (a contract with WA-17) ---------------------------------------------


def test_qr_channel_prefixes_are_pinned() -> None:
    """WA-17 attributes a chat to a channel by this prefix. Codes already printed carry
    the old text — changing a prefix silently breaks their attribution."""
    prefixes = {key: prefix for key, _label, prefix in QR_CHANNELS}
    assert prefixes == {
        "mostrador": "Hola, vengo del mostrador",
        "empaque": "Hola, vengo del empaque",
        "instagram": "Hola, vengo de Instagram",
        "ninguno": "",
    }


def test_compose_and_read_back_the_channel() -> None:
    assert compose_qr_message("mostrador", "") == "Hola, vengo del mostrador"
    composed = compose_qr_message("empaque", " quiero pedir ")
    assert composed == "Hola, vengo del empaque. quiero pedir"
    assert qr_channel_label(composed) == "Empaque"
    assert compose_qr_message("ninguno", "hola") == "hola"
    assert qr_channel_label("hola") == ""
    assert compose_qr_message("unknown-channel", "hola") == "hola"


def test_qr_vm_without_image() -> None:
    vm = build_qr_vm(
        code="ABC",
        prefilled_message="Hola, vengo de Instagram",
        deep_link_url="https://wa.me/message/ABC",
        image_url=None,
    )
    assert vm.image_url == "" and vm.channel_label == "Bio de Instagram"


# --- 4. Graph errors ---------------------------------------------------------------------


def test_auth_error_shows_the_reconnect_hint() -> None:
    assert graph_error_notice(code=190, is_auth_error=True, is_transport=False) == (
        WHATSAPP_RECONNECT_HINT,
        "error",
    )


def test_graph_error_shows_the_meta_code_only() -> None:
    message, tone = graph_error_notice(code=131009, is_auth_error=False, is_transport=False)
    assert "131009" in message and tone == "warn"
    message, tone = graph_error_notice(code=None, is_auth_error=False, is_transport=True)
    assert tone == "warn" and "Meta" in message


# --- 5. shell, placeholders, route, nav ------------------------------------------------


def test_tabs_and_default() -> None:
    assert [key for key, _ in TABS] == ["chats", "conexion", "perfil", "qr", "menu"]
    assert [label for _, label in TABS] == ["Chats", "Conexión", "Perfil", "QR", "Menú"]
    assert DEFAULT_TAB == TAB_CONNECTION
    assert resolve_tab("qr") == TAB_QR
    assert resolve_tab("<script>") == DEFAULT_TAB
    assert resolve_tab("") == DEFAULT_TAB


def test_placeholders_exist_behind_the_agreed_hooks() -> None:
    for component in (whatsapp_tab_chats.chats_tab(), whatsapp_tab_menu.menu_tab()):
        assert isinstance(component, rx.Component)
    rendered = str(whatsapp_tab_chats.chats_tab().render())
    assert "Los chats llegan con la siguiente entrega" in rendered


def test_the_page_renders_every_tab() -> None:
    rendered = str(whatsapp_page.whatsapp_index().render())

    def present(text: str) -> bool:
        # The render escapes non-ASCII as JSON does («ó» → «\\u00f3»), and `str()` of
        # the render dict escapes that backslash once more.
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for _key, label in TABS:
        assert present(label), label
    for text in ("Verificar ahora", "Guardar", "Crear código", "Copiar enlace", "Descargar PNG"):
        assert present(text), text


def test_the_page_never_imports_the_provider() -> None:
    """The page talks to the state only — never to Graph or Postgres directly."""
    source = (_HERE / "whatsapp_page.py").read_text()
    assert "whatsapp_provider" not in source
    assert "qualify_api" not in source


def test_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("whatsapp_index,")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/whatsapp"' in block
    assert "AuthState.require_login" in block
    assert "WhatsAppState.enter_page" in block


def test_nav_item_sits_after_conexiones() -> None:
    assert ("WhatsApp", "message-circle", "/whatsapp", True) in NAV_ITEMS
    labels = [label for label, *_ in NAV_BASE]
    assert labels.index("WhatsApp") == labels.index("Conexiones") + 1


def test_empty_vms_are_valid_defaults() -> None:
    assert EMPTY_NUMBER.connection_id == "" and EMPTY_PROFILE.about == ""
