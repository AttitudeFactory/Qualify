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
    DEFAULT_TAB,
    EMPTY_NUMBER,
    EMPTY_PROFILE,
    NEVER_CHECKED,
    NO_INBOUND,
    NO_NUMBER_ACTION,
    NO_NUMBER_GAINS,
    NO_NUMBER_TITLE,
    NUMBER_SUBS,
    PROMOTION_SUBS,
    PROMOTIONS_ROUTE,
    PROMOTIONS_SUBTITLE,
    PROMOTIONS_TITLE,
    QR_CHANNELS,
    REVIEW_ACTION,
    SECTION_KEYS,
    SECTIONS,
    SUBTABS,
    TAB_ACTIVITY,
    TAB_CAMPAIGNS,
    TAB_CHATS,
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
    compose_qr_message,
    graph_error_notice,
    health_display,
    is_promotions_panel,
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


def test_three_tabs_named_as_tasks() -> None:
    """m-24842998: the top tabs (guide §3), the secondary ones grouped inside.
    m-25017862 (D3): «Promociones» left the strip for its own menu entry."""
    assert [label for _, label in SECTIONS] == [
        "Chats",
        "Respuesta automática",
        "Tu número",
    ]
    # Its panels are still a section an old address can name (it then redirects).
    assert "promociones" in SECTION_KEYS and "promociones" not in dict(SECTIONS)
    assert [label for _, label in PROMOTION_SUBS] == [
        "Enviadas",
        "Mensajes aprobados",
        "Clientes que aceptaron",
    ]
    assert [label for _, label in NUMBER_SUBS] == [
        "Estado",
        "Perfil",
        "Formas de pago",  # m-24955648
        "Códigos QR",
        "Actividad",
    ]
    # m-25017173: «Chats» is one panel, no sub-tabs (the stickers sub-tab is gone).
    assert [panel for panel, _slug, _label in SUBTABS["chats"]] == [TAB_CHATS]
    # Every panel the body renders sits under exactly one top tab.
    assert TAB_KEYS == {
        TAB_CHATS,
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
    assert DEFAULT_TAB == TAB_CHATS
    assert resolve_tab("qr") == TAB_QR
    assert resolve_tab("<script>") == DEFAULT_TAB
    assert resolve_tab("") == DEFAULT_TAB


@pytest.mark.parametrize(
    ("tab", "sub", "panel"),
    [
        ("chats", "", TAB_CHATS),
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
    query = dict(part.split("=") for part in url.split("?", 1)[1].split("&"))
    if is_promotions_panel(panel):  # m-25017862: its own page, only the sub-tab
        assert url.startswith(f"{PROMOTIONS_ROUTE}?sub=")
        assert panel_route(panel) == PROMOTIONS_ROUTE
        assert promotions_panel(query["sub"]) == panel
    else:
        assert url.startswith("/whatsapp?tab=")
        assert panel_route(panel) == "/whatsapp"
        assert resolve_panel(query["tab"], query.get("sub", "")) == panel


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


def test_promotions_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("    whatsapp_promotions_index,\n")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/whatsapp/promociones"' in block
    assert "AuthState.require_login" in block and "WhatsAppState.enter_page" in block


def test_promotions_entry_sits_in_publica_after_anuncios() -> None:
    """m-25017862 (D3): «Promociones por WhatsApp» right after «Anuncios», in «Publica»."""
    entry = ("Promociones por WhatsApp", "badge-percent", PROMOTIONS_ROUTE, True)
    assert entry in NAV_ITEMS
    labels = {zone: [label for label, *_ in items] for zone, _t, items in NAV_ZONES}["publish"]
    assert labels.index("Promociones por WhatsApp") == labels.index("Anuncios") + 1


def test_addresses_are_the_owner_words() -> None:
    assert tab_url(TAB_TEMPLATES) == "/whatsapp/promociones?sub=aprobados"
    assert tab_url(TAB_CAMPAIGNS) == "/whatsapp/promociones?sub=enviadas"
    assert tab_url(TAB_CONTACTS) == "/whatsapp/promociones?sub=clientes"
    assert tab_url(TAB_QR) == "/whatsapp?tab=numero&sub=qr"
    assert tab_url(TAB_CHATS) == "/whatsapp?tab=chats"  # no sub without sub-tabs
    assert tab_url(TAB_MENU) == "/whatsapp?tab=respuesta"
    assert tab_url("<script>") == "/whatsapp?tab=chats"


def test_sections_and_subs_of_a_panel() -> None:
    assert panel_section(TAB_CONTACTS) == "promociones" and panel_sub(TAB_CONTACTS) == "clientes"
    assert panel_section(TAB_ACTIVITY) == "numero" and panel_sub(TAB_ACTIVITY) == "actividad"
    assert panel_section(TAB_CHATS) == "chats" and panel_sub(TAB_CHATS) == ""
    assert sub_panel("promociones", "aprobados") == TAB_TEMPLATES
    assert sub_panel("chats", "") == ""  # the default panel is not picked by an empty sub


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
    assert "rx.cond(WhatsAppState.number_needs_help, _review_request()" in source
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
    assert 'overflow_x="auto"' not in source[source.index("def tab_strip(") :][:400]
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
        ("/whatsapp", TAB_CHATS),
        ("/whatsapp?tab=respuesta", TAB_MENU),
        ("/whatsapp?tab=numero&sub=qr", TAB_QR),
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
    assert len(events) == 3  # the chip, the stale forms, then the numbers


_OLD = [
    ("/whatsapp?tab=promociones&sub=aprobados", "/whatsapp/promociones?sub=aprobados"),
    ("/whatsapp?tab=plantillas", "/whatsapp/promociones?sub=aprobados"),
    ("/whatsapp?tab=campanas&flujo=promocion&paso=2", None),
    ("/whatsapp?tab=contactos&path=x&tab2=y", "/whatsapp/promociones?sub=clientes"),
]


@pytest.mark.parametrize(("path", "target"), _OLD)
async def test_an_old_address_is_redirected_once_and_only_when_signed_in(
    monkeypatch: pytest.MonkeyPatch, path: str, target: str | None
) -> None:
    """m-25017862: the loader leaves an old «Promociones» address alone (nothing set,
    nothing loaded); the page's history handler — its mount and every «atrás» — sends
    it to the new page, with `replace`, and only with a session (`require_login` takes
    a visitor without one to log in first)."""
    expected = target or "/whatsapp/promociones?sub=enviadas&flujo=promocion&paso=2"
    state = _visit(path)
    assert WhatsAppState.enter_page.fn(state) == []  # type: ignore[attr-defined]
    assert state.active_tab == DEFAULT_TAB

    _signed_in(monkeypatch, "")
    assert await WhatsAppState.enter_history.fn(_visit(path), {"visit": "v"}) == []  # type: ignore[attr-defined]

    _signed_in(monkeypatch, "00000000-0000-4000-8000-000000000001")
    events = await WhatsAppState.enter_history.fn(_visit(path), {"visit": "v"})  # type: ignore[attr-defined]
    assert len(events) == 1
    rendered = str(events[0])
    assert f'"{expected}"' in rendered and "replace" in rendered


def test_tabs_exist_behind_the_agreed_hooks() -> None:
    for component in (whatsapp_tab_chats.chats_tab(), whatsapp_tab_menu.menu_tab()):
        assert isinstance(component, rx.Component)
    rendered = str(whatsapp_tab_chats.chats_tab().render())
    # WA-11 replaced the Chats placeholder; its root loads on mount.
    assert "Los chats llegan con la siguiente entrega" not in rendered
    assert "Elige una conversaci" in rendered


def test_the_page_renders_every_tab() -> None:
    rendered = str(whatsapp_page.whatsapp_index().render())

    def present(text: str) -> bool:
        # The render escapes non-ASCII as JSON does («ó» → «\\u00f3»), and `str()` of
        # the render dict escapes that backslash once more.
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for _key, label in (*SECTIONS, *PROMOTION_SUBS, *NUMBER_SUBS):
        assert present(label), label
    for text in (
        "Verificar ahora",
        "Ver detalles",
        "Guardar",
        "Crear código",
        "Copiar enlace",
        "Descargar PNG",
        NO_NUMBER_ACTION,
    ):
        assert present(text), text


def test_the_page_never_imports_the_provider() -> None:
    """The page talks to the state only — never to Graph or Postgres directly."""
    source = (_HERE / "whatsapp_page.py").read_text()
    assert "whatsapp_provider" not in source
    assert "qualify_api" not in source


def test_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text()
    start = source.index("    whatsapp_index,\n")  # the add_page call, not the import
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/whatsapp"' in block
    assert "AuthState.require_login" in block
    assert "WhatsAppState.enter_page" in block


def test_nav_item_sits_in_atiende_after_por_responder() -> None:
    """NAV-1 (m-24842957, guide §3): WhatsApp is the second entry of «Atiende»."""
    assert ("WhatsApp", "message-circle", "/whatsapp", True) in NAV_ITEMS
    labels = {zone: [label for label, *_ in items] for zone, _t, items in NAV_ZONES}["listen"]
    assert labels.index("WhatsApp") == labels.index("Por responder") + 1


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


# --- m-25017173: «Chats» without sub-tabs ---------------------------------------------


def test_chats_has_no_sub_tabs_and_old_sticker_links_open_the_chats() -> None:
    # A bookmarked `?tab=chats&sub=stickers` (m-24986801 §4) or any junk `sub` opens
    # the chats, never an error; the chats' address carries no `sub`.
    assert resolve_panel("chats", "stickers") == TAB_CHATS
    assert resolve_panel("chats", "") == TAB_CHATS
    assert resolve_panel("chats", "junk") == TAB_CHATS
    assert tab_url(TAB_CHATS) == "/whatsapp?tab=chats"
    assert panel_section(TAB_CHATS) == "chats" and panel_sub(TAB_CHATS) == ""
    assert sub_panel("chats", "stickers") == ""
    assert "stickers" not in TAB_KEYS
    assert resolve_tab("stickers") == TAB_CHATS


def test_the_chats_section_draws_no_second_strip() -> None:
    from .whatsapp_page import sub_strip, tab_body

    strip = str(sub_strip().render())
    assert "Stickers y videos" not in strip and "Tus chats" not in strip
    # Promociones and Tu número keep their strips.
    assert "Mensajes aprobados" in strip and "Formas de pago" in strip
    body = str(tab_body().render())
    assert "Stickers y videos de tu marca" not in body
