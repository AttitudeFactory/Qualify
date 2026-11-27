"""Network-free tests for the `/whatsapp` screen shell (WA-12).

They pin:
1. The VM boundary: no credential-bearing field, frozen, and no raw datetime anywhere —
   every date reaches the client pre-formatted.
2. The Meta enum → (label, tone) mapping uses design-system tones only, and an unknown
   enum value surfaces as itself instead of disappearing.
3. The QR «canal» prefixes — a contract WA-17 measures, so a silent edit fails here.
4. Graph errors hide internal codes; an auth error points to the Qualify team.
5. The shell renders, the Chats/Menú placeholders exist behind the agreed hooks, the
   route is registered behind `require_login`, and the nav item sits after Conexiones.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing
from datetime import datetime
from types import SimpleNamespace

import pytest
import reflex as rx
from reflex.istate.data import ReflexURL, RouterData

from . import whatsapp_page, whatsapp_tab_chats, whatsapp_tab_menu
from .connections_vm import WHATSAPP_RECONNECT_HINT
from .ui.layout import NAV_ITEMS, NAV_ZONES
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import (
    ACTIVITY_ROUTE,
    CONNECTIONS_ROUTE,
    DEFAULT_TAB,
    EMPTY_NUMBER,
    EMPTY_PROFILE,
    NEVER_CHECKED,
    NO_INBOUND,
    NO_NUMBER_ACTION,
    NO_NUMBER_GAINS,
    NO_NUMBER_TITLE,
    PAGE_PANELS,
    PANEL_PAGES,
    PROMOTION_SUBS,
    PROMOTIONS_ROUTE,
    PROMOTIONS_SUBTITLE,
    PROMOTIONS_TITLE,
    QR_CHANNELS,
    REVIEW_ACTION,
    SECTION_KEYS,
    SUBTABS,
    TAB_ACTIVITY,
    TAB_CAMPAIGNS,
    TAB_CONNECTION,
    TAB_CONTACTS,
    TAB_KEYS,
    TAB_MENU,
    TAB_PAYMENTS,
    TAB_PROFILE,
    TAB_QR,
    TAB_TEMPLATES,
    VERTICAL_KEYS,
    BusinessProfileVM,
    ProfileForm,
    QrCodeVM,
    WhatsAppNumberVM,
    build_number_vm,
    build_profile_vm,
    build_qr_vm,
    chat_return_path,
    compose_qr_message,
    graph_error_notice,
    health_display,
    is_promotions_panel,
    legacy_chat_target,
    legacy_number_target,
    legacy_panel_target,
    legacy_promotions_target,
    name_status_display,
    needs_help,
    panel_route,
    panel_section,
    panel_sub,
    platform_status_display,
    promotions_panel,
    qr_channel_label,
    quality_display,
    resolve_panel,
    resolve_tab,
    sub_panel,
    tab_url,
    tier_display,
    validate_profile_form,
)

_HERE = pathlib.Path(__file__).parent
_UUID = "00000000-0000-4000-8000-0000000000aa"
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
    [("active", "ok"), ("degraded", "warn"), ("revoked", "warn"), ("weird", "neutral")],
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
        "warn",
    )


def test_graph_error_hides_internal_codes_and_provider_jargon() -> None:
    message, tone = graph_error_notice(code=131009, is_auth_error=False, is_transport=False)
    assert "131009" not in message and "código" not in message and tone == "warn"
    message, tone = graph_error_notice(code=None, is_auth_error=False, is_transport=True)
    assert tone == "warn" and "WhatsApp" in message and "Meta" not in message


# --- 5. shell, placeholders, route, nav ------------------------------------------------


def test_one_task_left_tu_numero() -> None:
    """m-24842998: the top tabs (guide §3), the secondary ones grouped inside.
    m-25017862 (D3): «Promociones» left the strip for its own menu entry.
    m-25017861 (D1): the menu left it for «Ajustes de chats».
    m-25029799 (BU-A11): the chats left for «Por responder».
    m-25027373 (BU-A10): «Tu número»'s five sub-tabs left too, each for its own page; the
    section is kept only so its old addresses resolve (and then redirect)."""
    assert "chats" not in SECTION_KEYS and "chats" not in SUBTABS
    # The other sections are still ones an old address can name (it then redirects).
    assert {"respuesta", "promociones", "numero"} == set(SECTION_KEYS)
    assert [label for _, label in PROMOTION_SUBS] == [
        "Enviadas",
        "Mensajes aprobados",
        "Clientes que aceptaron",
    ]
    assert [label for _panel, _slug, label in SUBTABS["numero"]] == [
        "Estado",
        "Perfil",
        "Formas de pago",  # m-24955648
        "Códigos QR",
        "Actividad",
    ]
    # Every panel the body renders sits under exactly one top tab.
    assert TAB_KEYS == {
        TAB_MENU,
        TAB_CAMPAIGNS,
        TAB_TEMPLATES,
        TAB_CONTACTS,
        TAB_CONNECTION,
        TAB_PROFILE,
        TAB_PAYMENTS,
        TAB_QR,
        TAB_ACTIVITY,
    }


def test_tabs_and_default() -> None:
    # m-25029799: no «Chats» tab — the screen opens on «Tu número › Estado».
    assert DEFAULT_TAB == TAB_CONNECTION
    assert resolve_tab("qr") == TAB_QR
    assert resolve_tab("<script>") == DEFAULT_TAB
    assert resolve_tab("") == DEFAULT_TAB


@pytest.mark.parametrize(
    ("tab", "sub", "panel"),
    [
        ("chats", "", DEFAULT_TAB),  # m-25029799: redirected before it is ever read
        ("respuesta", "", TAB_MENU),
        ("promociones", "", TAB_CAMPAIGNS),
        ("promociones", "enviadas", TAB_CAMPAIGNS),
        ("promociones", "aprobados", TAB_TEMPLATES),
        ("promociones", "clientes", TAB_CONTACTS),
        ("promociones", "<script>", TAB_CAMPAIGNS),
        ("numero", "", TAB_CONNECTION),
        ("numero", "perfil", TAB_PROFILE),
        ("numero", "qr", TAB_QR),
        ("numero", "actividad", TAB_ACTIVITY),
        ("numero", "aprobados", TAB_CONNECTION),  # a sub of another tab is junk here
        # Addresses already shared or bookmarked keep landing on the same content.
        ("plantillas", "", TAB_TEMPLATES),
        ("campanas", "", TAB_CAMPAIGNS),
        ("contactos", "", TAB_CONTACTS),
        ("conexion", "", TAB_CONNECTION),
        ("menu", "", TAB_MENU),
        ("qr", "", TAB_QR),
        ("", "", DEFAULT_TAB),
        ("<script>", "x", DEFAULT_TAB),
    ],
)
def test_the_address_names_the_panel(tab: str, sub: str, panel: str) -> None:
    assert resolve_panel(tab, sub) == panel


@pytest.mark.parametrize("panel", sorted(TAB_KEYS))
def test_every_panel_has_an_address_that_reads_back(panel: str) -> None:
    """N5: what `select_*` writes is what `enter_page` reads on reload or «atrás»."""
    url = tab_url(panel)
    query = dict(part.split("=") for part in url.partition("?")[2].split("&") if part)
    if panel == TAB_MENU:  # m-25017861: «Ajustes de chats › WhatsApp», nothing to read
        assert url == panel_route(panel) == "/chats/ajustes/whatsapp"
    elif is_promotions_panel(panel):  # m-25017862: its own page, only the sub-tab
        assert url.startswith(f"{PROMOTIONS_ROUTE}?sub=")
        assert panel_route(panel) == PROMOTIONS_ROUTE
        assert promotions_panel(query["sub"]) == panel
    else:  # m-25027373: «Tu número»'s panels, each on its own page
        assert url == panel_route(panel) == PANEL_PAGES[panel]
        assert not url.startswith("/whatsapp")
        assert url == CONNECTIONS_ROUTE or PAGE_PANELS[url] == panel


@pytest.mark.parametrize(
    ("query", "target"),
    [
        # Every old address of a promotions panel lands on the same panel, new page.
        ({"tab": "promociones"}, "/whatsapp/promociones?sub=enviadas"),
        ({"tab": "promociones", "sub": "enviadas"}, "/whatsapp/promociones?sub=enviadas"),
        ({"tab": "promociones", "sub": "aprobados"}, "/whatsapp/promociones?sub=aprobados"),
        ({"tab": "promociones", "sub": "clientes"}, "/whatsapp/promociones?sub=clientes"),
        ({"tab": "promociones", "sub": "<script>"}, "/whatsapp/promociones?sub=enviadas"),
        ({"tab": "plantillas"}, "/whatsapp/promociones?sub=aprobados"),
        ({"tab": "campanas"}, "/whatsapp/promociones?sub=enviadas"),
        ({"tab": "contactos"}, "/whatsapp/promociones?sub=clientes"),
        # The number and a half-filled form ride along, each in its own shape.
        (
            {"tab": "promociones", "cuenta": _UUID, "flujo": "promocion", "paso": "2"},
            f"/whatsapp/promociones?sub=enviadas&cuenta={_UUID}&flujo=promocion&paso=2",
        ),
        (
            {"tab": "plantillas", "flujo": "mensaje-aprobado", "paso": "3"},
            "/whatsapp/promociones?sub=aprobados&flujo=mensaje-aprobado&paso=3",
        ),
        # Junk is dropped, never echoed: a key that collides with `with_query`'s own
        # argument (`path`), unknown keys, a non-UUID number, another form, a bad step,
        # a repeated value.
        (
            {"tab": "plantillas", "path": "x", "chat": _UUID, "otro": "<script>"},
            "/whatsapp/promociones?sub=aprobados",
        ),
        (
            {"tab": "campanas", "cuenta": "abc", "flujo": "menu", "paso": "2"},
            "/whatsapp/promociones?sub=enviadas",
        ),
        (
            {"tab": "campanas", "flujo": "promocion", "paso": "-1"},
            "/whatsapp/promociones?sub=enviadas&flujo=promocion",
        ),
        # `str.isdigit` alone takes «²» or Arabic-Indic digits; only ASCII ones pass.
        (
            {"tab": "campanas", "flujo": "promocion", "paso": "٣"},
            "/whatsapp/promociones?sub=enviadas&flujo=promocion",
        ),
        (
            {"tab": "campanas", "flujo": "promocion", "paso": "²"},
            "/whatsapp/promociones?sub=enviadas&flujo=promocion",
        ),
        ({"tab": "plantillas", "paso": ["1", "2"]}, "/whatsapp/promociones?sub=aprobados"),
    ],
)
def test_an_old_promotions_address_redirects_to_its_page(
    query: dict[str, object], target: str
) -> None:
    """m-25017862: a bookmark to the old «Promociones» tab still opens the same panel."""
    assert legacy_promotions_target(query) == target
    sub = target.split("sub=", 1)[1].split("&", 1)[0]
    assert promotions_panel(sub) == resolve_panel(str(query["tab"]), str(query.get("sub", "")))


@pytest.mark.parametrize(
    "query",
    [{}, {"tab": "chats"}, {"tab": "respuesta"}, {"tab": "numero", "sub": "qr"}, {"tab": "x"}],
)
def test_any_other_whatsapp_address_stays(query: dict[str, object]) -> None:
    assert legacy_promotions_target(query) is None


def test_promotions_page_reads_only_its_sub_tab() -> None:
    assert promotions_panel("") == TAB_CAMPAIGNS
    assert promotions_panel("aprobados") == TAB_TEMPLATES
    assert promotions_panel("clientes") == TAB_CONTACTS
    assert promotions_panel("qr") == TAB_CAMPAIGNS  # another section's sub is junk here
    assert promotions_panel("<script>") == TAB_CAMPAIGNS


def test_the_promotions_page_has_its_own_header_and_strip() -> None:
    """m-25017862: «Promociones por WhatsApp» (D3's name) heads the page, with the three
    sub-tabs and nothing of the WhatsApp strip; `/whatsapp` keeps the other three."""
    assert PROMOTIONS_TITLE == "Promociones por WhatsApp"
    rendered = str(whatsapp_page.whatsapp_promotions_index().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for _key, label in PROMOTION_SUBS:
        assert present(label), label
    assert present(PROMOTIONS_TITLE) and present(PROMOTIONS_SUBTITLE)
    assert not present("Secciones de WhatsApp")  # the /whatsapp strip is not here


def _mounts(component: rx.Component, gates: tuple[tuple[str, bool], ...] = ()) -> list:
    """Every component with an `on_mount`, with the `rx.cond`s above it as (condition,
    in its true branch)."""
    found = []
    if "on_mount" in (component.event_triggers or {}):
        found.append((component, gates))
    cond = getattr(component, "cond", None)  # an `rx.cond`: children = (true, false)
    for index, child in enumerate(component.children):
        here = gates if cond is None else (*gates, (str(cond), index == 0))
        found.extend(_mounts(child, here))
    return found


@pytest.mark.parametrize(
    ("page", "mine"),
    [
        (whatsapp_page.whatsapp_promotions_index, "promotions"),
        (whatsapp_page.whatsapp_settings_index, "settings"),
        # m-25027373: «Tu número»'s old panels, each on its own page.
        (whatsapp_page.whatsapp_profile_index, TAB_PROFILE),
        (whatsapp_page.whatsapp_qr_index, TAB_QR),
        (whatsapp_page.whatsapp_payments_index, TAB_PAYMENTS),
        (whatsapp_page.whatsapp_activity_index, TAB_ACTIVITY),
    ],
)
def test_no_panel_mounts_outside_its_pages_section(page: typing.Any, mine: str) -> None:
    """m-25017862 (review 2026-11-14): both pages share `active_tab`, set a round trip
    after the client switched page. Every panel — everything with an `on_mount` below
    the shell — sits in the TRUE branch of this page's section condition, so the other
    page's panel never mounts (nor loads) here. The menu's guided frame on `/whatsapp`
    has its own condition, `active_tab == "menu"`, which no promotions panel meets.
    m-25017861: the same for «Ajustes de chats › WhatsApp», which draws the menu only.
    m-25027373: and for each page of one of «Tu número»'s old panels."""
    page_gates = {
        "promotions": whatsapp_page._on_promotions_page,  # noqa: SLF001
        "settings": whatsapp_page._on_settings_page,  # noqa: SLF001
    }
    gate = str(
        page_gates[mine]() if mine in page_gates else whatsapp_page._on_panel(mine)  # noqa: SLF001
    )
    panels = [
        (component, gates)
        for component, gates in _mounts(page())
        # The shell's own: the menu (`nav`) and the route's history button.
        if component.tag != "nav" and "q-route-pop" not in str(component.class_name)
    ]
    # the gate is not vacuous: the panels are really in the tree
    assert len(panels) >= (1 if mine == "settings" else 5)
    for component, gates in panels:
        menu_frame = any('"menu"' in cond and "active_tab" in cond and ok for cond, ok in gates)
        assert (gate, True) in gates or menu_frame, (type(component).__name__, gates)
        assert (gate, False) not in gates


def test_whatsapp_draws_no_panel() -> None:
    """m-25027373: `/whatsapp` only redirects — no panel mounts (nor loads) there."""
    panels = [
        component
        for component, _gates in _mounts(whatsapp_page.whatsapp_index())
        if component.tag != "nav" and "q-route-pop" not in str(component.class_name)
    ]
    assert panels == []


def test_promotions_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("    whatsapp_promotions_index,\n    route=")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/whatsapp/promociones"' in block
    assert "AuthState.require_login" in block and "WhatsAppState.enter_page" in block


def test_promotions_entry_sits_in_publica_after_anuncios() -> None:
    """m-25017862 (D3): the entry right after «Anuncios», in «Publica». Its menu word is
    «Promociones» (founder, 2026-11-14); the page keeps «Promociones por WhatsApp»."""
    entry = ("Promociones", "badge-percent", PROMOTIONS_ROUTE, True)
    assert entry in NAV_ITEMS
    labels = {zone: [label for label, *_ in items] for zone, _t, items in NAV_ZONES}["publish"]
    assert labels.index("Promociones") == labels.index("Anuncios") + 1


def test_addresses_are_the_owner_words() -> None:
    assert tab_url(TAB_TEMPLATES) == "/whatsapp/promociones?sub=aprobados"
    assert tab_url(TAB_CAMPAIGNS) == "/whatsapp/promociones?sub=enviadas"
    assert tab_url(TAB_CONTACTS) == "/whatsapp/promociones?sub=clientes"
    assert tab_url(TAB_MENU) == "/chats/ajustes/whatsapp"  # m-25017861
    # m-25027373: «Tu número»'s panels, each on its own page.
    assert tab_url(TAB_QR) == "/chats/ajustes/whatsapp/codigos-qr"
    assert tab_url(TAB_PROFILE) == "/chats/ajustes/whatsapp/perfil"
    assert tab_url(TAB_PAYMENTS) == "/chats/ajustes/formas-de-pago"
    assert tab_url(TAB_ACTIVITY) == "/connections/whatsapp/actividad"
    assert tab_url(TAB_CONNECTION) == "/connections"
    assert tab_url("<script>") == "/connections"


def test_sections_and_subs_of_a_panel() -> None:
    assert panel_section(TAB_CONTACTS) == "promociones" and panel_sub(TAB_CONTACTS) == "clientes"
    assert panel_section(TAB_ACTIVITY) == "numero" and panel_sub(TAB_ACTIVITY) == "actividad"
    assert sub_panel("promociones", "aprobados") == TAB_TEMPLATES
    assert sub_panel("chats", "") == ""  # m-25029799: no such section any more


@pytest.mark.parametrize(
    ("status", "quality", "platform", "tone"),
    [
        ("active", "GREEN", "CONNECTED", "ok"),
        ("active", "UNKNOWN", None, "ok"),
        ("active", "RED", "CONNECTED", "warn"),
        ("active", "GREEN", "BANNED", "error"),
        ("pending", None, None, "info"),
        ("degraded", "GREEN", "CONNECTED", "warn"),
        ("revoked", "GREEN", "CONNECTED", "warn"),
    ],
)
def test_the_number_in_one_line(
    status: str, quality: str | None, platform: str | None, tone: str
) -> None:
    label, got = health_display(status=status, quality_rating=quality, platform_status=platform)
    assert got == tone
    assert label
    if tone == "ok":
        assert label == "Tu WhatsApp funciona bien ✓"
    if status in {"degraded", "revoked"} or platform == "BANNED":
        # UX review: the owner reads what happened and gets a button to ask for help,
        # never the administrative «vuelva a ejecutar la conexión» hint.
        assert "Meta" not in label
        if status in {"degraded", "revoked"}:
            assert WHATSAPP_RECONNECT_HINT in label
            assert "guardados siguen aquí" in label
        assert needs_help(label)
    else:
        assert not needs_help(label)


def test_a_failing_number_offers_the_review_request() -> None:
    assert needs_help(_number(status="revoked").health_label)
    assert needs_help(_number(status="degraded").health_label)
    assert not needs_help(_number().health_label)
    source = (_HERE / "whatsapp_page.py").read_text()
    # m-25027373: on the number's card in «Tus redes» (a disconnected number's card has
    # its own help button) and above every other panel of the number.
    assert 'active & (number.health_tone == "error")' in source
    assert "WhatsAppState.request_review(number.connection_id)" in source
    assert "WhatsAppState.number_needs_help" in source and "_review_request()" in source
    assert REVIEW_ACTION == "Avisar al equipo de Qualify"


def test_number_vm_carries_its_line() -> None:
    vm = _number()
    assert (vm.health_label, vm.health_tone) == ("Tu WhatsApp funciona bien ✓", "ok")
    assert _number(status="revoked").health_tone == "warn"


def test_no_number_state_has_a_next_step() -> None:
    """N8: without a connected number there is a button, not a dead end."""
    assert NO_NUMBER_TITLE == "Conecta tu WhatsApp para atender y vender desde aquí"
    assert len(NO_NUMBER_GAINS) == 3
    source = (_HERE / "whatsapp_page.py").read_text()
    start = source.index("def _no_numbers_state(")
    block = source[start : source.index("\n\n\n", start)]
    assert "action=" in block and "WhatsAppState.request_connection" in block
    assert "NO_NUMBER_ACTION" in block
    assert NO_NUMBER_ACTION == "Pedir que conecten mi WhatsApp"


def test_the_strips_fit_a_phone() -> None:
    """N12: at 360 px the tabs are a grid of 44 px buttons, never a sliding strip."""
    source = (_HERE / "whatsapp_page.py").read_text()
    start = source.index("def _choice_strip(")
    block = source[start : source.index("\n\n\n", start)]
    assert "_PHONE_ONLY" in block and "_DESKTOP_ONLY" in block
    assert "def tab_strip(" not in source  # m-25029799: one section, no section strip
    assert '_TAP = {"min_height": "44px"}' in source


@pytest.mark.parametrize(
    "module",
    [
        "whatsapp_tab_campaigns.py",
        "whatsapp_tab_templates.py",
        "whatsapp_tab_contacts.py",
        "whatsapp_metrics_block.py",
    ],
)
def test_every_table_has_phone_cards(module: str) -> None:
    """m-24842998: no table slides sideways on a phone — each one has its cards."""
    source = (_HERE / module).read_text()
    assert source.count("rx.table.root(") == source.count("table_or_cards(")


def _visit(path: str) -> WhatsAppState:
    """A `WhatsAppState` whose router is at `path` (as on_load sees it)."""
    state = WhatsAppState()
    state.router = RouterData(url=ReflexURL(f"http://localhost:3000{path}"))
    return state


def _signed_in(monkeypatch: pytest.MonkeyPatch, tenant: str) -> None:
    """`get_state(AuthState)` on a bare state: a session for `tenant` ("" = none)."""

    async def get_state(self: WhatsAppState, cls: type) -> object:
        return SimpleNamespace(session_tenant_id=tenant)

    monkeypatch.setattr(WhatsAppState, "get_state", get_state)


@pytest.mark.parametrize(
    ("path", "panel"),
    [
        ("/chats/ajustes/whatsapp", TAB_MENU),
        ("/chats/ajustes/whatsapp/?tab=numero", TAB_MENU),  # only the menu here
        # m-25027373: «Tu número»'s old panels, one per page (the address's `tab` and
        # `sub` are not read there).
        ("/chats/ajustes/whatsapp/perfil", TAB_PROFILE),
        ("/chats/ajustes/whatsapp/codigos-qr?tab=numero&sub=perfil", TAB_QR),
        ("/chats/ajustes/formas-de-pago/", TAB_PAYMENTS),
        ("/connections/whatsapp/actividad?cuenta=x", TAB_ACTIVITY),
        ("/whatsapp/promociones", TAB_CAMPAIGNS),
        ("/whatsapp/promociones?sub=aprobados", TAB_TEMPLATES),
        ("/whatsapp/promociones/?sub=clientes", TAB_CONTACTS),
        ("/whatsapp/promociones?sub=qr", TAB_CAMPAIGNS),  # another page's sub is junk
    ],
)
def test_entering_a_page_shows_the_panel_of_its_address(path: str, panel: str) -> None:
    state = _visit(path)
    events = WhatsAppState.enter_page.fn(state)  # type: ignore[attr-defined]
    assert state.active_tab == panel
    assert len(events) == 2  # the stale forms, then the numbers (no chip: m-25029799)


_OLD = [
    ("/whatsapp?tab=promociones&sub=aprobados", "/whatsapp/promociones?sub=aprobados"),
    ("/whatsapp?tab=plantillas", "/whatsapp/promociones?sub=aprobados"),
    ("/whatsapp?tab=campanas&flujo=promocion&paso=2", None),
    ("/whatsapp?tab=contactos&path=x&tab2=y", "/whatsapp/promociones?sub=clientes"),
    # m-25017861: the menu's old addresses land in «Ajustes de chats › WhatsApp», with
    # its form (`flujo=menu`, step, the menu's id) and the number — nothing else.
    ("/whatsapp?tab=respuesta", "/chats/ajustes/whatsapp"),
    ("/whatsapp?tab=menu", "/chats/ajustes/whatsapp"),
    (
        "/whatsapp?tab=menu&cuenta=00000000-0000-4000-8000-0000000000aa&flujo=menu&paso=3"
        "&objeto=00000000-0000-4000-8000-0000000000bb&x=<script>",
        "/chats/ajustes/whatsapp?cuenta=00000000-0000-4000-8000-0000000000aa&flujo=menu"
        "&paso=3&objeto=00000000-0000-4000-8000-0000000000bb",
    ),
    ("/whatsapp?tab=respuesta&flujo=promocion&paso=2&objeto=junk", "/chats/ajustes/whatsapp"),
    # m-25029799: WhatsApp's chat list moved into «Por responder».
    ("/whatsapp?tab=chats", "/responder?tab=mensajes&filtro=todos&canal=whatsapp"),
    (
        f"/whatsapp?tab=chats&filtro=sin-leer&cuenta={_UUID}",
        f"/responder?tab=mensajes&filtro=por-responder&canal=whatsapp&numero={_UUID}",
    ),
    # m-25027373: «Tu número» left — every other address lands on the panel's page.
    ("/whatsapp", "/connections"),
    ("/whatsapp?tab=numero&sub=estado", "/connections"),
    (
        f"/whatsapp?tab=numero&sub=qr&cuenta={_UUID}",
        f"/chats/ajustes/whatsapp/codigos-qr?cuenta={_UUID}",
    ),
    ("/whatsapp?tab=numero&sub=actividad", "/connections/whatsapp/actividad"),
]


@pytest.mark.parametrize(("path", "target"), _OLD)
async def test_an_old_address_is_redirected_once_and_only_when_signed_in(
    monkeypatch: pytest.MonkeyPatch, path: str, target: str | None
) -> None:
    """m-25017862: the loader leaves an old «Promociones» address alone (nothing set,
    nothing loaded); the page's history handler — its mount and every «atrás» — sends
    it to the new page, with `replace`, and only with a session. A visitor without one
    is `require_login`'s: it sends them to log in, and does not bring them back here."""
    expected = target or "/whatsapp/promociones?sub=enviadas&flujo=promocion&paso=2"
    state = _visit(path)
    assert WhatsAppState.enter_page.fn(state) == []  # type: ignore[attr-defined]
    assert state.active_tab == DEFAULT_TAB

    _signed_in(monkeypatch, "")
    assert await WhatsAppState.enter_history.fn(_visit(path), {"visit": "v"}) == []  # type: ignore[attr-defined]

    _signed_in(monkeypatch, "00000000-0000-4000-8000-000000000001")
    events = await WhatsAppState.enter_history.fn(_visit(path), {"visit": "v"})  # type: ignore[attr-defined]
    assert len(events) == 1
    # The same redirect `rx.redirect` builds — address AND `replace` (never a new step).
    assert str(events[0].args) == str(rx.redirect(expected, replace=True).args)
    assert str(events[0].args) != str(rx.redirect(expected).args)


def test_tabs_exist_behind_the_agreed_hooks() -> None:
    assert isinstance(whatsapp_tab_menu.menu_tab(), rx.Component)
    # m-25029799: the Chats tab is gone; only the chat «Por responder» mounts is left.
    assert not hasattr(whatsapp_tab_chats, "chats_tab")
    assert not hasattr(whatsapp_page, "tab_strip")


def _present(rendered: str, text: str) -> bool:
    # The render escapes non-ASCII as JSON does («ó» → «\\u00f3»), and `str()` of the
    # render dict escapes that backslash once more.
    escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
    return text in rendered or escaped in rendered


@pytest.mark.parametrize(
    ("page", "texts"),
    [
        # m-25027373: every action of «Tu número»'s panels, now on their own pages.
        (
            whatsapp_page.whatsapp_profile_index,
            ("Perfil", "Guardar", "Descartar cambios", "Volver a leer de WhatsApp"),
        ),
        (
            whatsapp_page.whatsapp_qr_index,
            ("Códigos QR", "Crear código", "Copiar enlace", "Descargar PNG", "Eliminar"),
        ),
        (whatsapp_page.whatsapp_payments_index, ("Formas de pago", "Agregar forma de pago")),
        (whatsapp_page.whatsapp_activity_index, ("Actividad", "Tus redes")),
    ],
)
def test_each_moved_panel_renders_on_its_page(page: typing.Any, texts: tuple[str, ...]) -> None:
    rendered = str(page().render())
    for text in (*texts, NO_NUMBER_ACTION):
        assert _present(rendered, text), text
    # No «Tu número» strip, no chats, no chat notice on any of them.
    for gone in ("Tu número", "Secciones de WhatsApp", "Filtrar chats", "Ir a Por responder"):
        assert not _present(rendered, gone), gone


def test_whatsapp_shows_nothing_of_its_own() -> None:
    """m-25027373: no header, no strip, no notice — only the shell and a skeleton."""
    rendered = str(whatsapp_page.whatsapp_index().render())
    for gone in (
        "Tu número",
        "Tus chats de WhatsApp se responden en Por responder.",
        "Verificar ahora",
        "Formas de pago",
    ):
        assert not _present(rendered, gone), gone


def test_the_number_card_of_tus_redes_carries_estado() -> None:
    """m-25027373: «Tu número › Estado» is the WhatsApp card of «Tus redes»: the number's
    line, «Avisar al equipo de Qualify», «Verificar ahora» (per number), the ten facts and
    the way to «Actividad»."""
    from . import connections_page
    from .connections_vm import ConnectionVM

    card = connections_page.connection_card(rx.Var.create("c").to(ConnectionVM))  # type: ignore[arg-type]
    rendered = str(card.render())
    details = str(connections_page._details(rx.Var.create("c").to(ConnectionVM)).render())  # type: ignore[arg-type]  # noqa: SLF001
    for text in (REVIEW_ACTION, "Actividad"):
        assert _present(rendered, text), text
    for text in ("Verificar ahora", "Nombre verificado", "Calidad", "Límite de mensajes"):
        assert _present(details, text), text
    assert "verify_number" in details and "request_review" in rendered
    assert ACTIVITY_ROUTE in rendered


def test_the_page_never_imports_the_provider() -> None:
    """The page talks to the state only — never to Graph or Postgres directly."""
    source = (_HERE / "whatsapp_page.py").read_text()
    assert "whatsapp_provider" not in source
    assert "qualify_api" not in source


def test_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("    whatsapp_index,\n    route=")  # the add_page call
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/whatsapp"' in block
    assert "AuthState.require_login" in block
    assert "WhatsAppState.enter_page" in block


@pytest.mark.parametrize(
    ("page", "route"),
    [
        ("whatsapp_profile_index", "/chats/ajustes/whatsapp/perfil"),
        ("whatsapp_qr_index", "/chats/ajustes/whatsapp/codigos-qr"),
        ("whatsapp_payments_index", "/chats/ajustes/formas-de-pago"),
        ("whatsapp_activity_index", "/connections/whatsapp/actividad"),
    ],
)
def test_every_new_page_is_registered_behind_login(page: str, route: str) -> None:
    """m-25027373: each page of «Tu número»'s old panels, with `WhatsAppState`'s loader."""
    source = (_HERE / "Qualify.py").read_text()
    start = source.index(f"    {page},\n    route=")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert f'route="{route}"' in block
    assert "AuthState.require_login" in block and "WhatsAppState.enter_page" in block
    assert PAGE_PANELS[route]


def test_tus_redes_loads_the_numbers() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("    connections_index,\n    route=")
    block = source[start : source.index("title=", start)]
    assert "WhatsAppState.load_numbers" in block


def test_no_whatsapp_entry_in_the_menu() -> None:
    """m-25027373 (BU-A10): the «WhatsApp» entry left the menu (and the phone's «Más»,
    built from the same list); «Atiende» is «Por responder» and «Ajustes de chats»."""
    assert all(label != "WhatsApp" and route != "/whatsapp" for label, _i, route, _e in NAV_ITEMS)
    labels = {zone: [label for label, *_ in items] for zone, _t, items in NAV_ZONES}["listen"]
    assert labels == ["Por responder", "Ajustes de chats"]


def test_empty_vms_are_valid_defaults() -> None:
    assert EMPTY_NUMBER.connection_id == "" and EMPTY_PROFILE.about == ""


def test_profile_form_and_qr_list_render_only_after_a_successful_read() -> None:
    """Browser finding (2026-10-14): after a FAILED profile read the empty form was still
    on screen, so «Guardar» would have wiped the real profile on Meta with blanks; a
    failed QR read showed «Aún no tienes códigos». Both are gated on `*_ready` now."""
    source = (_HERE / "whatsapp_page.py").read_text()
    assert "WhatsAppState.profile_ready,\n            profile_form()," in source
    assert "WhatsAppState.qr_ready," in source
    assert "WhatsAppState.profile_failed" in source and "WhatsAppState.qr_failed" in source


def test_missing_verified_name_has_copy() -> None:
    vm = _number(verified_name=None)
    assert vm.verified_name == "Sin nombre verificado"
    assert vm.label == "+57 300 1234567"  # the title stays the bare number


def test_an_auth_error_in_any_tab_refreshes_the_numbers() -> None:
    """Browser finding (2026-10-14): Perfil/QR got Meta's auth error, the provider
    degraded the connection, but the Conexión card kept saying «Activa» until a reload.
    Every Graph-backed handler now re-reads the numbers after an auth error."""
    from qualify_api.whatsapp.client import WhatsAppApiError

    from . import whatsapp_state

    assert whatsapp_state._is_auth(WhatsAppApiError("x", status=401))
    assert whatsapp_state._is_auth(WhatsAppApiError("x", status=400, code=190))
    assert not whatsapp_state._is_auth(WhatsAppApiError("x", status=400, code=100))
    assert not whatsapp_state._is_auth(ValueError("x"))
    source = (_HERE / "whatsapp_state.py").read_text()
    for handler in (
        "ensure_profile_loaded",
        "reload_profile",
        "save_profile_form",
        "upload_pending_photo",
        "ensure_qr_loaded",
        "reload_qr",
        "create_qr",
        "delete_qr",
    ):
        start = source.index(f"async def {handler}(")
        end = source.find("\n    @rx.event", start)
        assert "WhatsAppState.load_numbers" in source[start:end], handler


def test_the_connect_request_is_a_ticket_the_support_service_accepts() -> None:
    """«Pedir que conecten mi WhatsApp» files a QUA-202 support request; the service
    refuses unknown context keys, so pin that what the state sends is accepted."""
    from qualify_api.support import service

    from .whatsapp_vm import CONNECT_REQUEST_MESSAGE

    source = (_HERE / "whatsapp_state.py").read_text()
    start = source.index("async def request_connection(")
    block = source[start : source.index("\n    @rx.", start)]
    assert "request_support," in block and 'context={"screen": "whatsapp"}' in block
    assert "if self.connect_request_sending:" in block  # a double tap files one ticket
    topic, *_rest, context = service._clean(
        topic="connect_accounts",
        contact_email="dueno@negocio.co",
        contact_whatsapp="",
        message=CONNECT_REQUEST_MESSAGE,
        context={"screen": "whatsapp"},
    )
    assert topic == "connect_accounts" and context == {"screen": "whatsapp"}


# --- m-25029799: the chats left for «Por responder» ------------------------------------


def test_no_sticker_or_chat_strip_on_the_page() -> None:
    from .whatsapp_page import sub_strip, tab_body

    strip = str(sub_strip().render())
    assert "Stickers y videos" not in strip and "Tus chats" not in strip
    # Promociones keeps its strip; «Tu número»'s left with its panels (m-25027373).
    assert "Mensajes aprobados" in strip and "Formas de pago" not in strip
    body = str(tab_body().render())
    assert "Stickers y videos de tu marca" not in body
    assert "WhatsAppChatsState" not in body  # no list, no chat state on this page


_C, _T = _UUID, "00000000-0000-4000-8000-0000000000cc"
_INBOX = "/responder?tab=mensajes"


@pytest.mark.parametrize(
    ("query", "target"),
    [
        # Every chip of the old list lands on its equivalent in «Por responder».
        ({"tab": "chats"}, f"{_INBOX}&filtro=todos&canal=whatsapp"),
        ({"tab": "chats", "filtro": "abiertos"}, f"{_INBOX}&filtro=todos&canal=whatsapp"),
        ({"tab": "chats", "filtro": "cerrados"}, f"{_INBOX}&filtro=cerrados&canal=whatsapp"),
        (
            {"tab": "chats", "filtro": "por-responder"},
            f"{_INBOX}&filtro=por-responder&canal=whatsapp",
        ),
        ({"tab": "chats", "filtro": "sin-leer"}, f"{_INBOX}&filtro=por-responder&canal=whatsapp"),
        (
            {"tab": "chats", "filtro": "pago-por-revisar"},
            f"{_INBOX}&filtro=pago-por-revisar&canal=whatsapp",
        ),
        ({"tab": "chats", "filtro": "Sin-Leer"}, f"{_INBOX}&filtro=por-responder&canal=whatsapp"),
        # The number the list showed rides along; junk never does.
        (
            {"tab": "chats", "filtro": "cerrados", "cuenta": _C},
            f"{_INBOX}&filtro=cerrados&canal=whatsapp&numero={_C}",
        ),
        (
            {"tab": "chats", "cuenta": "<script>", "filtro": "<b>", "x": "y"},
            f"{_INBOX}&filtro=todos&canal=whatsapp",
        ),
        ({"tab": "chats", "filtro": ["cerrados", "x"]}, f"{_INBOX}&filtro=todos&canal=whatsapp"),
        # m-24986801's sticker sub-tab of the list.
        ({"tab": "chats", "sub": "stickers"}, f"{_INBOX}&filtro=todos&canal=whatsapp"),
        # The chats were the screen's default tab: a chip with no `tab` is the list too.
        ({"filtro": "sin-leer"}, f"{_INBOX}&filtro=por-responder&canal=whatsapp"),
        # An open chat still lands on that chat (m-25029798).
        ({"tab": "chats", "cuenta": _C, "chat": _T}, f"{_INBOX}&cuenta={_C}&chat={_T}"),
        ({"cuenta": _C, "chat": _T}, f"{_INBOX}&cuenta={_C}&chat={_T}"),
    ],
)
def test_every_old_address_of_the_chat_list_lands_in_por_responder(
    query: dict[str, object], target: str
) -> None:
    assert legacy_chat_target(query) == target
    # And never back on `/whatsapp`: the target is no address this page redirects.
    assert not target.startswith("/whatsapp")


@pytest.mark.parametrize(
    "query",
    [{}, {"tab": "numero"}, {"tab": "numero", "sub": "qr"}, {"cuenta": _C}, {"tab": "x"}],
)
def test_tu_numero_and_a_bare_whatsapp_stay(query: dict[str, object]) -> None:
    assert legacy_chat_target(query) is None


# --- m-25027373 (BU-A10): «Tu número» left `/whatsapp` ----------------------------------

_CHAT_BACK = f"/responder?tab=mensajes&cuenta={_C}&chat={_T}"
_QS_BACK = "%2Fresponder%3Ftab%3Dmensajes%26cuenta%3D" + _C + "%26chat%3D" + _T


@pytest.mark.parametrize(
    ("query", "target"),
    [
        # Estado (and anything that names no known panel) → «Tus redes».
        ({}, "/connections"),
        ({"tab": "numero"}, "/connections"),
        ({"tab": "numero", "sub": "estado"}, "/connections"),
        ({"tab": "conexion"}, "/connections"),
        ({"tab": "numero", "sub": "<script>"}, "/connections"),
        ({"tab": "<script>"}, "/connections"),
        ({"tab": "numero", "sub": "estado", "cuenta": _C}, "/connections"),
        # Each other panel → its page, with the number.
        ({"tab": "numero", "sub": "perfil"}, "/chats/ajustes/whatsapp/perfil"),
        (
            {"tab": "numero", "sub": "pagos", "cuenta": _C},
            f"/chats/ajustes/formas-de-pago?cuenta={_C}",
        ),
        (
            {"tab": "numero", "sub": "qr", "cuenta": _C},
            f"/chats/ajustes/whatsapp/codigos-qr?cuenta={_C}",
        ),
        ({"tab": "qr"}, "/chats/ajustes/whatsapp/codigos-qr"),
        ({"tab": "perfil"}, "/chats/ajustes/whatsapp/perfil"),
        (
            {"tab": "actividad", "cuenta": _C},
            f"/connections/whatsapp/actividad?cuenta={_C}",
        ),
        # The chat's way back rides along to Perfil and Formas de pago only — and only an
        # app's own chat address; junk, a foreign site, a non-UUID number never do.
        (
            {"tab": "numero", "sub": "perfil", "cuenta": _C, "volver": _CHAT_BACK},
            f"/chats/ajustes/whatsapp/perfil?cuenta={_C}&volver={_QS_BACK}",
        ),
        (
            {"tab": "numero", "sub": "pagos", "volver": _CHAT_BACK},
            f"/chats/ajustes/formas-de-pago?volver={_QS_BACK}",
        ),
        (
            {"tab": "numero", "sub": "qr", "volver": _CHAT_BACK},
            "/chats/ajustes/whatsapp/codigos-qr",
        ),
        (
            {"tab": "numero", "sub": "perfil", "volver": "https://evil.example/responder"},
            "/chats/ajustes/whatsapp/perfil",
        ),
        (
            {"tab": "numero", "sub": "perfil", "volver": "//evil.example"},
            "/chats/ajustes/whatsapp/perfil",
        ),
        (
            {"tab": "numero", "sub": "pagos", "volver": "/whatsapp?tab=chats"},
            "/chats/ajustes/formas-de-pago",
        ),
        (
            {"tab": "numero", "sub": "perfil", "cuenta": "<script>", "x": "y"},
            "/chats/ajustes/whatsapp/perfil",
        ),
        (
            {"tab": "numero", "sub": "perfil", "cuenta": [_C, _C]},
            "/chats/ajustes/whatsapp/perfil",
        ),
    ],
)
def test_every_old_number_address_lands_on_its_new_page(
    query: dict[str, object], target: str
) -> None:
    assert legacy_number_target(query) == target
    assert legacy_panel_target(query) == target


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"tab": "numero", "sub": "qr"},
        {"tab": "promociones", "sub": "aprobados"},
        {"tab": "respuesta"},
        {"tab": "chats", "filtro": "cerrados"},
        {"cuenta": _C, "chat": _T},
        {"tab": "x", "sub": "y", "volver": "/whatsapp"},
    ],
)
def test_whatsapp_always_answers_with_another_page(query: dict[str, object]) -> None:
    """No loop: every address of `/whatsapp` has a new place, and it is never `/whatsapp`
    itself (`/whatsapp/promociones` is its own page, which never redirects)."""
    target = legacy_panel_target(query)
    assert target.startswith("/")
    assert not target.startswith("//")
    assert target.split("?", 1)[0] != "/whatsapp"


def test_the_way_back_rule_is_one() -> None:
    """The payments panel, the profile's map point and the redirects read one rule."""
    from . import whatsapp_location_state, whatsapp_payments_state

    assert whatsapp_payments_state.chat_return_path is chat_return_path
    assert whatsapp_location_state.chat_return_path is chat_return_path
    assert chat_return_path({"volver": _CHAT_BACK}) == _CHAT_BACK
    assert chat_return_path({"volver": "/responder?tab=mensajes"}) == ""


def _with_numbers(*ids: str) -> WhatsAppState:
    state = WhatsAppState()
    state.numbers = [_number(connection_id=i) for i in ids]
    state.selected_connection_id = ids[0] if ids else ""
    return state


def test_a_card_acts_only_on_a_number_of_the_business() -> None:
    """m-25027373: «Verificar ahora» / «Avisar al equipo de Qualify» on a card of «Tus
    redes» act on that card's number — never on an id the business's list lacks."""
    state = _with_numbers(_C, _T)
    state.qr_loaded_for = _C
    foreign = "00000000-0000-4000-8000-0000000000ff"
    assert WhatsAppState.verify_number.fn(state, foreign) is None  # type: ignore[attr-defined]
    assert WhatsAppState.request_review.fn(state, "<script>") is None  # type: ignore[attr-defined]
    assert WhatsAppState.verify_number.fn(state, ["x"]) is None  # type: ignore[attr-defined]
    assert state.selected_connection_id == _C and state.qr_loaded_for == _C  # untouched
    assert WhatsAppState.verify_number.fn(state, _T) is not None  # type: ignore[attr-defined]
    assert state.selected_connection_id == _T
    assert state.qr_loaded_for == ""  # what belonged to the other number is dropped
    assert WhatsAppState.request_review.fn(state, _T) is not None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("router", "href", "target"),
    [
        # The browser's own address wins over the router data an event carries, which
        # after a client-side navigation can still be the previous page's.
        (
            "/chats/ajustes",
            "http://x/whatsapp?tab=numero&sub=qr",
            "/chats/ajustes/whatsapp/codigos-qr",
        ),
        ("/connections", "http://x/whatsapp/promociones?sub=aprobados", None),
        ("/promotions", "http://x/chats/ajustes/whatsapp/perfil", None),
        # Not one of these pages: nothing is set and nobody is sent away.
        ("/chats/ajustes", "", None),
        ("/connections", "http://x/connections", None),
        # A lease naming another page: nothing happens there either.
        ("/whatsapp?tab=numero&sub=pagos", "//evil.example/x", None),
    ],
)
async def test_the_history_handler_reads_the_browsers_address(
    monkeypatch: pytest.MonkeyPatch, router: str, href: str, target: str | None
) -> None:
    """m-25027373 (e2e finding): with the PREVIOUS page's router data, `/whatsapp`'s
    redirect would have sent the owner to «Tus redes» from any page of the number."""
    _signed_in(monkeypatch, "00000000-0000-4000-8000-000000000001")
    state = _visit(router)
    state.active_tab = TAB_MENU
    events = await WhatsAppState.enter_history.fn(state, {"visit": "v", "href": href})  # type: ignore[attr-defined]
    if target is None:
        assert all("_redirect" not in str(event) for event in events)
    else:
        assert len(events) == 1
        assert str(events[0].args) == str(rx.redirect(target, replace=True).args)
    if href.endswith("/chats/ajustes/whatsapp/perfil"):
        assert state.active_tab == TAB_PROFILE
    if href.endswith("sub=aprobados"):
        assert state.active_tab == TAB_TEMPLATES
    if not href and router == "/chats/ajustes":
        assert state.active_tab == TAB_MENU  # untouched
