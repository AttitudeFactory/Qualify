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

from .connections_vm import WHATSAPP_RECONNECT_HINT, whatsapp_label

# --------------------------------------------------------------------------------------
# Tabs. The order is the strip's order. Chats (WA-11) and Menú (WA-16) are their own
# files (`whatsapp_tab_chats.py`, `whatsapp_tab_menu.py`); this list only names them.
# --------------------------------------------------------------------------------------

TAB_CHATS = "chats"
TAB_CONNECTION = "conexion"
TAB_PROFILE = "perfil"
TAB_QR = "qr"
TAB_MENU = "menu"
# WA-18 (QUA-217/218/219): own files `whatsapp_tab_templates.py`, `_contacts.py`, `_campaigns.py`.
TAB_TEMPLATES = "plantillas"
TAB_CONTACTS = "contactos"
TAB_CAMPAIGNS = "campanas"

TABS: tuple[tuple[str, str], ...] = (
    (TAB_CHATS, "Chats"),
    (TAB_CONNECTION, "Conexión"),
    (TAB_PROFILE, "Perfil"),
    (TAB_QR, "QR"),
    (TAB_MENU, "Menú"),
    (TAB_TEMPLATES, "Plantillas"),
    (TAB_CONTACTS, "Contactos"),
    (TAB_CAMPAIGNS, "Campañas"),
)
TAB_KEYS: frozenset[str] = frozenset(key for key, _label in TABS)

# The tab a visit lands on when `?tab=` is absent or junk: the conversations (WA-11) —
# attending chats is what a person opens this screen for.
DEFAULT_TAB = TAB_CHATS


def resolve_tab(requested: str) -> str:
    """`?tab=<key>` → a known tab key; anything else → `DEFAULT_TAB`. The value arrives in
    the URL, so junk is ignored rather than echoed."""
    return requested if requested in TAB_KEYS else DEFAULT_TAB


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
_CONNECTION_STATUS: dict[str, tuple[str, str]] = {
    "active": ("Activa", "ok"),
    "degraded": ("Degradada", "warn"),
    "revoked": ("Revocada", "error"),
    "pending": ("Pendiente", "info"),
}

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
    "FLAGGED": ("Marcado por Meta", "warn"),
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


def connection_status_display(status: str) -> tuple[str, str]:
    """`social_connections.status` → (label, tone)."""
    return _CONNECTION_STATUS.get(status, (status or _UNKNOWN, "neutral"))


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
# The number (Conexión tab)
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
    "No pudimos comunicarnos con Meta. Revisa tu conexión y vuelve a intentarlo en un momento."
)
GRAPH_UNAVAILABLE = (
    "No pudimos preparar la conexión con Meta para este número. Vuelve a intentarlo en un momento."
)


def graph_error_notice(
    *, code: int | None, is_auth_error: bool, is_transport: bool
) -> tuple[str, str]:
    """(message, tone) for a failed Graph call. An auth error (401 / code 190) means the
    stored token no longer works: the number is degraded and only an administrator can
    re-run the connection, so the banner is `WHATSAPP_RECONNECT_HINT` in `error`."""
    if is_auth_error:
        return WHATSAPP_RECONNECT_HINT, "error"
    if is_transport:
        return GRAPH_TRANSPORT_ERROR, "warn"
    suffix = f" (código {code})" if code is not None else ""
    return f"Meta rechazó la operación{suffix}. Revisa los datos y vuelve a intentarlo.", "warn"
