"""View-models for the `/whatsapp` screen (WA-12) — the security boundary.

Every Reflex var is serialized to the client, so `WhatsAppState` only ever holds the
frozen dataclasses below — never an ORM row of `social_connections`,
`whatsapp_phone_numbers` or `oauth_credentials`, and never a Graph client. None of them
has a field that could carry a token, a ciphertext or a key id
(`test_whatsapp_vm_has_no_credential_fields` pins it), and every date is PRE-FORMATTED
here, server-side: the frontend never receives a raw `datetime` var.

The Meta enums (`quality_rating`, `messaging_limit_tier`, `name_status`, `status`) are
stored verbatim in `whatsapp_phone_numbers` (WA-05). This module is the one place they
become Spanish copy plus a design-system TONE (`ok`/`warn`/`error`/`info`/`neutral`,
docs/design-system.md §3.2) — never a raw Radix colour. An unknown value is shown as
itself in the `neutral` tone rather than dropped: a renamed Meta enum must surface, not
disappear.

Keep this module free of Reflex, network and database imports so the whitelist and the
mappings can be asserted by plain unit tests (`test_whatsapp_page.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .connection_copy import (
    WHATSAPP_RECONNECT_HINT,
    WHATSAPP_SUPPORT_ACTION,
)
from .connection_copy import (
    connection_status_display as connection_status_display,
)
from .connections_vm import whatsapp_label
from .nav_url import with_query

# --------------------------------------------------------------------------------------
# Tabs (m-24842998 WHATSAPP-7). Four tasks on top, two of them with sub-tabs:
#
#   Chats · Respuesta automática · Promociones · Tu número
#                                  │              └─ Estado · Perfil · Códigos QR · Actividad
#                                  └─ Enviadas · Mensajes aprobados · Clientes que aceptaron
#
# A PANEL is what the body renders (its own `whatsapp_tab_*.py` file, or a function in
# `whatsapp_page.py`). Its key is the old flat tab key, kept so every in-app jump
# (`WhatsAppState.select_tab(TAB_QR)`) and every address already shared or bookmarked
# (`/whatsapp?tab=plantillas`) keeps landing on the same content. A SECTION is a top
# tab; a SUB is the slug of a panel inside its section. The address carries both
# (`?tab=promociones&sub=aprobados`, N5) and `resolve_panel` reads it back.
# --------------------------------------------------------------------------------------

TAB_CHATS = "chats"
TAB_CONNECTION = "conexion"
TAB_PROFILE = "perfil"
TAB_QR = "qr"
TAB_ACTIVITY = "actividad"
TAB_MENU = "menu"
# WA-18 (QUA-217/218/219): own files `whatsapp_tab_templates.py`, `_contacts.py`, `_campaigns.py`.
TAB_TEMPLATES = "plantillas"
TAB_CONTACTS = "contactos"
TAB_CAMPAIGNS = "campanas"

SECTION_CHATS = "chats"
SECTION_AUTO_REPLY = "respuesta"
SECTION_PROMOTIONS = "promociones"
SECTION_NUMBER = "numero"

# (section key, label): the order is the strip's order.
SECTIONS: tuple[tuple[str, str], ...] = (
    (SECTION_CHATS, "Chats"),
    (SECTION_AUTO_REPLY, "Respuesta automática"),
    (SECTION_PROMOTIONS, "Promociones"),
    (SECTION_NUMBER, "Tu número"),
)
SECTION_KEYS: frozenset[str] = frozenset(key for key, _label in SECTIONS)

# section → ((panel, sub slug, label), …); the first one is the section's default. A
# section with a single panel has no sub-tab strip and no `?sub=`.
SUBTABS: dict[str, tuple[tuple[str, str, str], ...]] = {
    SECTION_CHATS: ((TAB_CHATS, "", "Chats"),),
    SECTION_AUTO_REPLY: ((TAB_MENU, "", "Respuesta automática"),),
    SECTION_PROMOTIONS: (
        (TAB_CAMPAIGNS, "enviadas", "Enviadas"),
        (TAB_TEMPLATES, "aprobados", "Mensajes aprobados"),
        (TAB_CONTACTS, "clientes", "Clientes que aceptaron"),
    ),
    SECTION_NUMBER: (
        (TAB_CONNECTION, "estado", "Estado"),
        (TAB_PROFILE, "perfil", "Perfil"),
        (TAB_QR, "qr", "Códigos QR"),
        (TAB_ACTIVITY, "actividad", "Actividad"),
    ),
}

# The two sub-tab strips, as (sub slug, label): what the page builds its controls from.
PROMOTION_SUBS: tuple[tuple[str, str], ...] = tuple(
    (slug, label) for _panel, slug, label in SUBTABS[SECTION_PROMOTIONS]
)
NUMBER_SUBS: tuple[tuple[str, str], ...] = tuple(
    (slug, label) for _panel, slug, label in SUBTABS[SECTION_NUMBER]
)

_PANEL_PLACE: dict[str, tuple[str, str]] = {
    panel: (section, slug) for section, subs in SUBTABS.items() for panel, slug, _ in subs
}
TAB_KEYS: frozenset[str] = frozenset(_PANEL_PLACE)

# The panel a visit lands on when the address names nothing known: the conversations
# (WA-11). Attending chats is what a person opens this screen for.
DEFAULT_TAB = TAB_CHATS

WHATSAPP_ROUTE: Final = "/whatsapp"
TAB_PARAM: Final = "tab"
SUB_PARAM: Final = "sub"


def resolve_tab(requested: str) -> str:
    """A panel key → itself; anything else → `DEFAULT_TAB`. For in-app jumps; the
    address goes through `resolve_panel`."""
    return requested if requested in TAB_KEYS else DEFAULT_TAB


def resolve_panel(tab: str, sub: str = "") -> str:
    """`?tab=…&sub=…` → the panel to show. A section picks its sub (its first one when
    `sub` is missing or junk); an old flat key (`?tab=plantillas`, `?tab=qr`) is still
    honoured; anything else is `DEFAULT_TAB`. Junk is ignored, never echoed."""
    if tab in SECTION_KEYS:
        found = sub_panel(tab, sub)
        return found or SUBTABS[tab][0][0]
    return resolve_tab(tab)


def panel_section(panel: str) -> str:
    """The top tab a panel belongs to (the default panel's for an unknown key)."""
    return _PANEL_PLACE.get(panel, _PANEL_PLACE[DEFAULT_TAB])[0]


def panel_sub(panel: str) -> str:
    """The sub slug of a panel ("" for a section without sub-tabs)."""
    return _PANEL_PLACE.get(panel, _PANEL_PLACE[DEFAULT_TAB])[1]


def sub_panel(section: str, sub: str) -> str:
    """The panel behind `sub` inside `section`, or "" when it is not one of its subs."""
    for panel, slug, _label in SUBTABS.get(section, ()):
        if slug and slug == sub:
            return panel
    return ""


def tab_url(panel: str) -> str:
    """The address of a panel (N5): `/whatsapp?tab=promociones&sub=aprobados`. An
    unknown key is the default panel, the same rule `resolve_tab` applies."""
    known = resolve_tab(panel)
    return with_query(
        WHATSAPP_ROUTE, **{TAB_PARAM: panel_section(known), SUB_PARAM: panel_sub(known)}
    )


# --------------------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------------------

NEVER_CHECKED = "Sin verificar"
NEVER_SYNCED = "Sin sincronizar"
NO_INBOUND = "Aún no llega ningún mensaje"
NO_VERIFIED_NAME = "Sin nombre verificado"
_NO_BRAND_LABEL = "Sin marca"


def format_timestamp(value: datetime | None, fallback: str) -> str:
    """Same pre-format discipline (and format) as `connections_provider`."""
    if value is None:
        return fallback
    return value.strftime("%d %b %Y, %H:%M")


# --------------------------------------------------------------------------------------
# Meta enums → (label, tone)
# --------------------------------------------------------------------------------------

# The connection FSM (C-03) — same words as the `/connections` card.


# `quality_rating`: GREEN/YELLOW/RED, UNKNOWN for a number without enough traffic.
_QUALITY: dict[str, tuple[str, str]] = {
    "GREEN": ("Alta", "ok"),
    "YELLOW": ("Media", "warn"),
    "RED": ("Baja", "error"),
    "UNKNOWN": ("Sin datos aún", "neutral"),
}

# `messaging_limit_tier`: business-initiated conversations per rolling 24 h.
_TIERS: dict[str, str] = {
    "TIER_50": "50 conversaciones al día",
    "TIER_250": "250 conversaciones al día",
    "TIER_1K": "1.000 conversaciones al día",
    "TIER_10K": "10.000 conversaciones al día",
    "TIER_100K": "100.000 conversaciones al día",
    "TIER_UNLIMITED": "Sin límite",
}

# `name_status`: the review of the display name.
_NAME_STATUS: dict[str, tuple[str, str]] = {
    "APPROVED": ("Aprobado", "ok"),
    "AVAILABLE_WITHOUT_REVIEW": ("Disponible sin revisión", "info"),
    "PENDING_REVIEW": ("En revisión", "warn"),
    "NONE": ("Sin solicitud", "neutral"),
    "DECLINED": ("Rechazado", "error"),
    "EXPIRED": ("Vencido", "error"),
    "NON_EXISTS": ("Sin nombre", "neutral"),
}

# The number's own `status` on Meta's side (stored as `platform_status`).
_PLATFORM_STATUS: dict[str, tuple[str, str]] = {
    "CONNECTED": ("Conectado", "ok"),
    "PENDING": ("Pendiente", "info"),
    "MIGRATED": ("Migrado", "info"),
    "FLAGGED": ("Marcado por WhatsApp", "warn"),
    "RATE_LIMITED": ("Con límite temporal", "warn"),
    "RESTRICTED": ("Restringido", "error"),
    "BANNED": ("Bloqueado", "error"),
    "DISCONNECTED": ("Desconectado", "error"),
    "DELETED": ("Eliminado", "error"),
    "UNVERIFIED": ("Sin verificar", "warn"),
}

_UNKNOWN = "Sin dato"


def _lookup(table: dict[str, tuple[str, str]], value: str | None) -> tuple[str, str]:
    if not value:
        return _UNKNOWN, "neutral"
    return table.get(value.upper(), (value, "neutral"))


def quality_display(rating: str | None) -> tuple[str, str]:
    return _lookup(_QUALITY, rating)


def tier_display(tier: str | None) -> str:
    if not tier:
        return _UNKNOWN
    return _TIERS.get(tier.upper(), tier)


def name_status_display(status: str | None) -> tuple[str, str]:
    return _lookup(_NAME_STATUS, status)


def platform_status_display(status: str | None) -> tuple[str, str]:
    return _lookup(_PLATFORM_STATUS, status)


# --------------------------------------------------------------------------------------
# «Tu número» in one line (m-24842998). The ten Meta facts stay behind «Ver detalles»;
# the owner first reads whether the number works and, if not, what to do.
# --------------------------------------------------------------------------------------

HEALTH_OK = "Tu WhatsApp funciona bien ✓"
HEALTH_PENDING = "Tu WhatsApp todavía se está conectando. Vuelve a mirar en un rato."
HEALTH_REVOKED = (
    "Tu WhatsApp está desconectado. Tus mensajes guardados siguen aquí. "
    + WHATSAPP_RECONNECT_HINT
    + "."
)
HEALTH_DEGRADED = (
    "Tu WhatsApp está desconectado. Tus mensajes guardados siguen aquí. "
    + WHATSAPP_RECONNECT_HINT
    + "."
)
HEALTH_BLOCKED = (
    "WhatsApp pausó tu número y por ahora no puede enviar "
    "mensajes. Pide que lo revisen y te ayudamos."
)
HEALTH_LOW_QUALITY = (
    "Varios clientes marcaron tus mensajes como no deseados. Envía menos promociones "
    "por unos días y escribe solo a quien aceptó recibirlas."
)
DETAILS_TOGGLE = "Ver detalles"


def health_display(
    *, status: str, quality_rating: str | None, platform_status: str | None
) -> tuple[str, str]:
    """(line, tone) for the number: the worst problem first, else «funciona bien»."""
    if status == "revoked":
        return HEALTH_REVOKED, "warn"
    if status == "degraded":
        return HEALTH_DEGRADED, "warn"
    if status == "pending":
        return HEALTH_PENDING, "info"
    if platform_status_display(platform_status)[1] == "error":
        return HEALTH_BLOCKED, "error"
    if (quality_rating or "").upper() == "RED":
        return HEALTH_LOW_QUALITY, "warn"
    return HEALTH_OK, "ok"


# The three lines the owner cannot fix alone: each one offers «Pedir que revisen mi
# WhatsApp» (N8), the same support request as the no-number state.
_HELP_LINES = frozenset({HEALTH_REVOKED, HEALTH_DEGRADED, HEALTH_BLOCKED})
REVIEW_ACTION = WHATSAPP_SUPPORT_ACTION
CONNECT_REVIEW_MESSAGE = "Mi WhatsApp tiene un problema en Qualify. Por favor revísenlo."


def needs_help(health_label: str) -> bool:
    """True when the number's line asks the owner to request help from the team."""
    return health_label in _HELP_LINES


# Without a connected number (N8): what the owner gains, and the next step, a request
# to the Qualify team (numbers are connected by an administrator, WA-05).
NO_NUMBER_TITLE = "Conecta tu WhatsApp para atender y vender desde aquí"
NO_NUMBER_GAINS: tuple[str, ...] = (
    "Responde los chats de tus clientes desde Qualify, en el celular o en el computador.",
    "Deja un menú de respuesta automática para las preguntas de siempre: horario, "
    "precios, domicilios.",
    "Envía promociones a los clientes que aceptaron recibirlas y mira cuántos las leyeron.",
)
NO_NUMBER_NEXT = (
    "El equipo de Qualify conecta el número de tu negocio. Pídelo aquí y te escribimos "
    "para hacerlo juntos."
)
NO_NUMBER_ACTION = "Pedir que conecten mi WhatsApp"
CONNECT_REQUEST_MESSAGE = "Quiero conectar el WhatsApp de mi negocio en Qualify."
CONNECT_REQUEST_SENT = (
    "Recibimos tu pedido #{reference}. Una persona del equipo te escribirá a {email} "
    "en menos de un día hábil."
)
CONNECT_REQUEST_SAVED = (
    "Tu pedido #{reference} quedó registrado. Te escribiremos a {email} en cuanto una "
    "persona del equipo lo tome."
)
CONNECT_REQUEST_NO_EMAIL = (
    "No encontramos un correo en tu cuenta para responderte. Escríbenos a "
    "contacto@attitudefactory.co y conectamos tu número."
)
CONNECT_REQUEST_FAILED = (
    "No pudimos registrar tu pedido. Vuelve a intentarlo en un momento o escríbenos a "
    "contacto@attitudefactory.co."
)


# --------------------------------------------------------------------------------------
# The number (Tu número › Estado)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhatsAppNumberVM:
    """Display-ready projection of one WhatsApp connection + its `whatsapp_phone_numbers`
    row. Whitelisted: no field can carry credential material."""

    connection_id: str
    label: str  # «+57 300 1234567 · Bianki» — the selector item and card title
    display_phone_number: str
    verified_name: str
    brand: str
    status: str  # FSM value, for `rx.match` (banners)
    status_label: str
    status_tone: str
    quality_label: str
    quality_tone: str
    tier_label: str
    name_status_label: str
    name_status_tone: str
    platform_status_label: str
    platform_status_tone: str
    last_health_checked_at: str  # PRE-FORMATTED
    last_synced_at: str  # PRE-FORMATTED
    last_inbound_at: str  # PRE-FORMATTED — latest inbound `messages.ingested_at`
    # m-24842998: the one line «Tu número › Estado» opens with, and its tone.
    health_label: str
    health_tone: str


EMPTY_NUMBER = WhatsAppNumberVM(
    connection_id="",
    label="",
    display_phone_number="",
    verified_name="",
    brand="",
    status="",
    status_label="",
    status_tone="neutral",
    quality_label="",
    quality_tone="neutral",
    tier_label="",
    name_status_label="",
    name_status_tone="neutral",
    platform_status_label="",
    platform_status_tone="neutral",
    last_health_checked_at="",
    last_synced_at="",
    last_inbound_at="",
    health_label="",
    health_tone="neutral",
)


def build_number_vm(
    *,
    connection_id: str,
    status: str,
    display_phone_number: str,
    verified_name: str | None,
    brand: str | None,
    quality_rating: str | None,
    messaging_limit_tier: str | None,
    name_status: str | None,
    platform_status: str | None,
    last_health_checked_at: datetime | None,
    last_synced_at: datetime | None,
    last_inbound_at: datetime | None,
) -> WhatsAppNumberVM:
    """Assemble the VM from raw column values — the provider passes columns, never rows."""
    status_label, status_tone = connection_status_display(status)
    quality_label, quality_tone = quality_display(quality_rating)
    name_label, name_tone = name_status_display(name_status)
    platform_label, platform_tone = platform_status_display(platform_status)
    health_label, health_tone = health_display(
        status=status, quality_rating=quality_rating, platform_status=platform_status
    )
    return WhatsAppNumberVM(
        connection_id=connection_id,
        label=whatsapp_label(display_phone_number, verified_name),
        display_phone_number=display_phone_number,
        verified_name=(verified_name or "").strip() or NO_VERIFIED_NAME,
        brand=brand or _NO_BRAND_LABEL,
        status=status,
        status_label=status_label,
        status_tone=status_tone,
        quality_label=quality_label,
        quality_tone=quality_tone,
        tier_label=tier_display(messaging_limit_tier),
        name_status_label=name_label,
        name_status_tone=name_tone,
        platform_status_label=platform_label,
        platform_status_tone=platform_tone,
        last_health_checked_at=format_timestamp(last_health_checked_at, NEVER_CHECKED),
        last_synced_at=format_timestamp(last_synced_at, NEVER_SYNCED),
        last_inbound_at=format_timestamp(last_inbound_at, NO_INBOUND),
        health_label=health_label,
        health_tone=health_tone,
    )


# --------------------------------------------------------------------------------------
# Business profile (Perfil tab)
# --------------------------------------------------------------------------------------

# Meta's `vertical` enum (cloud-api/reference/business-profiles). Order = the select's.
VERTICALS: tuple[tuple[str, str], ...] = (
    ("RESTAURANT", "Restaurante"),
    ("GROCERY", "Alimentos y supermercado"),
    ("RETAIL", "Comercio y tiendas"),
    ("APPAREL", "Ropa y moda"),
    ("BEAUTY", "Belleza, spa y salón"),
    ("HEALTH", "Salud"),
    ("PROF_SERVICES", "Servicios profesionales"),
    ("EDU", "Educación"),
    ("EVENT_PLAN", "Eventos"),
    ("ENTERTAIN", "Entretenimiento"),
    ("HOTEL", "Hotelería"),
    ("TRAVEL", "Viajes"),
    ("AUTO", "Automotriz"),
    ("FINANCE", "Finanzas y banca"),
    ("NONPROFIT", "Sin ánimo de lucro"),
    ("GOVT", "Gobierno"),
    ("OTHER", "Otra"),
)
VERTICAL_KEYS: frozenset[str] = frozenset(key for key, _ in VERTICALS)


@dataclass(frozen=True)
class BusinessProfileVM:
    """The editable fields of `whatsapp_business_profile`, as the form shows them.
    `website_1/2` because Meta allows at most two websites; `vertical` is "" when Meta
    reports none (or `UNDEFINED`) so the select shows its placeholder."""

    about: str
    address: str
    description: str
    email: str
    website_1: str
    website_2: str
    vertical: str
    picture_url: str


EMPTY_PROFILE = BusinessProfileVM(
    about="",
    address="",
    description="",
    email="",
    website_1="",
    website_2="",
    vertical="",
    picture_url="",
)


def build_profile_vm(
    *,
    about: str | None,
    address: str | None,
    description: str | None,
    email: str | None,
    websites: tuple[str, ...],
    vertical: str | None,
    profile_picture_url: str | None,
) -> BusinessProfileVM:
    sites = [*websites, "", ""]
    vertical_key = (vertical or "").upper()
    return BusinessProfileVM(
        about=about or "",
        address=address or "",
        description=description or "",
        email=email or "",
        website_1=sites[0],
        website_2=sites[1],
        vertical=vertical_key if vertical_key in VERTICAL_KEYS else "",
        picture_url=profile_picture_url or "",
    )


@dataclass(frozen=True)
class ProfileForm:
    """What the Perfil form submits — plain strings, as typed."""

    about: str
    address: str
    description: str
    email: str
    website_1: str
    website_2: str
    vertical: str


# Meta-published limits (client.py pins them with their source); mirrored as `max_length`
# on the inputs, so the browser stops the operator before the client would raise.
MAX_ABOUT_CHARS = 139
MAX_ADDRESS_CHARS = 256
MAX_DESCRIPTION_CHARS = 512
MAX_EMAIL_CHARS = 128
MAX_WEBSITE_CHARS = 256


def validate_profile_form(form: ProfileForm) -> str:
    """Spanish copy for the first field Meta would refuse, "" when the form is sendable.
    Checked before the client's own `ValueError` (English, for engineers) can fire."""
    if len(form.about.strip()) > MAX_ABOUT_CHARS:
        return f"La descripción corta admite hasta {MAX_ABOUT_CHARS} caracteres."
    if len(form.address.strip()) > MAX_ADDRESS_CHARS:
        return f"La dirección admite hasta {MAX_ADDRESS_CHARS} caracteres."
    if len(form.description.strip()) > MAX_DESCRIPTION_CHARS:
        return f"La descripción admite hasta {MAX_DESCRIPTION_CHARS} caracteres."
    email = form.email.strip()
    if email and ("@" not in email or len(email) > MAX_EMAIL_CHARS):
        return "Escribe un correo válido o deja el campo vacío."
    for site in (form.website_1.strip(), form.website_2.strip()):
        if not site:
            continue
        if not site.startswith(("http://", "https://")):
            return "Las webs deben empezar por https:// (o http://)."
        if len(site) > MAX_WEBSITE_CHARS:
            return f"Cada web admite hasta {MAX_WEBSITE_CHARS} caracteres."
    if form.vertical and form.vertical not in VERTICAL_KEYS:
        return "Elige una categoría de la lista."
    return ""


# --------------------------------------------------------------------------------------
# QR codes (QR tab)
# --------------------------------------------------------------------------------------

# The «canal» picker: a client-side prefix on the prefilled message. The prefix IS the
# entry key WA-17 measures and maps to a menu entry — so these strings are a contract:
# change one and the codes already printed on a counter stop being attributed.
QR_CHANNEL_NONE = "ninguno"
QR_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("mostrador", "Mostrador", "Hola, vengo del mostrador"),
    ("empaque", "Empaque", "Hola, vengo del empaque"),
    ("instagram", "Bio de Instagram", "Hola, vengo de Instagram"),
    (QR_CHANNEL_NONE, "Sin canal", ""),
)
_QR_CHANNEL_PREFIX: dict[str, str] = {key: prefix for key, _label, prefix in QR_CHANNELS}
QR_DEFAULT_CHANNEL = "mostrador"
MAX_QR_MESSAGE_CHARS = 140  # mirrors `client.MAX_QR_PREFILLED_MESSAGE_CHARS`


def compose_qr_message(channel: str, text: str) -> str:
    """The prefilled message a new code carries: the channel's prefix, then whatever the
    operator typed. «Hola, vengo del mostrador» + «quiero ver el menú» →
    «Hola, vengo del mostrador. quiero ver el menú». Without a channel, the text alone."""
    prefix = _QR_CHANNEL_PREFIX.get(channel, "")
    body = text.strip()
    if prefix and body:
        return f"{prefix}. {body}"
    return prefix or body


def qr_channel_label(prefilled_message: str) -> str:
    """Which channel a code belongs to, read back from its prefix ("" for none)."""
    for _key, label, prefix in QR_CHANNELS:
        if prefix and prefilled_message.startswith(prefix):
            return label
    return ""


@dataclass(frozen=True)
class QrCodeVM:
    """One `message_qrdls` code. `image_url` is "" when Meta did not return one — the list
    endpoint omits it; only create returns it (see `whatsapp_provider.list_qr_codes`)."""

    code: str
    prefilled_message: str
    deep_link_url: str
    image_url: str
    channel_label: str


def build_qr_vm(
    *, code: str, prefilled_message: str, deep_link_url: str, image_url: str | None
) -> QrCodeVM:
    return QrCodeVM(
        code=code,
        prefilled_message=prefilled_message,
        deep_link_url=deep_link_url,
        image_url=image_url or "",
        channel_label=qr_channel_label(prefilled_message),
    )


# --------------------------------------------------------------------------------------
# Graph errors → banner copy. The Meta code only — never Meta's message, never a body.
# --------------------------------------------------------------------------------------

GRAPH_TRANSPORT_ERROR = (
    "No pudimos comunicarnos con WhatsApp. Revisa tu conexión y vuelve a intentarlo en un momento."
)
GRAPH_UNAVAILABLE = (
    "No pudimos preparar la conexión con WhatsApp para este "
    "número. Vuelve a intentarlo en un momento."
)


def graph_error_notice(
    *, code: int | None, is_auth_error: bool, is_transport: bool
) -> tuple[str, str]:
    """(message, tone) for a failed Graph call. An auth error (401 / code 190) means the
    stored token no longer works: the number is degraded and only an administrator can
    re-run the connection, so the banner is `WHATSAPP_RECONNECT_HINT` in `warn`."""
    if is_auth_error:
        return WHATSAPP_RECONNECT_HINT, "warn"
    if is_transport:
        return GRAPH_TRANSPORT_ERROR, "warn"
    return (
        "WhatsApp no pudo completar la operación. Revisa los datos y vuelve a intentarlo.",
        "warn",
    )
