"""View models of «Ajustes de chats» (m-25017861, story BU-A9 of docs/epica-bandeja-unica.md).

Decision D1 (founder, 2026-11-12, docs/ux-chats-unificados.md §3): what the owner
prepares once lives apart from the messages, in «Ajustes de chats» under «Atiende». One
screen, three cards, no tabs (mockup `docs/mockups/chats-unificados.html`, part F):

    Para todos tus chats   Mensajes guardados · Formas de pago · Cómo llegar
    WhatsApp               Tu menú de bienvenida · Perfil · Códigos QR
    Instagram              Preguntas iniciales (one row per connected account)

Each row opens the screen that already exists. Names: «Tu menú de bienvenida» is the
founder's decision (vi) of 2026-11-14 — never «Respuesta automática», nothing that says
or suggests Qualify answers by itself; «Preguntas iniciales» is D5, with the same line in
both channels (`STARTER_QUESTIONS_LINE`).

What is NOT built here, on purpose (each its own ticket): one saved-messages library for
every channel (BU-A8: today they are Instagram's «Plantillas»), payments and «Cómo
llegar» as data of the business (BU-A14: today they are kept with the WhatsApp number).
Those rows say which network each works on today and take the owner to it; the two kept
with the WhatsApp number are hidden without one.

m-25027373 (BU-A10): «Tu número» left `/whatsapp`. Its Perfil, Códigos QR and Formas de
pago are pages of this hub (`SETTINGS_PROFILE_ROUTE`, `SETTINGS_QR_ROUTE`,
`SETTINGS_PAYMENTS_ROUTE`, served by `WhatsAppState` like the menu's); its Estado and
Actividad live in «Tus redes» (`whatsapp_vm.CONNECTIONS_ROUTE`, `ACTIVITY_ROUTE`).

Pure: no Reflex, no database; `test_chat_settings.py` pins it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .nav_url import with_query

CHAT_SETTINGS_ROUTE: Final = "/chats/ajustes"
SETTINGS_WHATSAPP_ROUTE: Final = "/chats/ajustes/whatsapp"
#: The hub, with an Instagram account's «Preguntas iniciales» open (the drawer). The
#: target of the Instagram chat's «⋯» › «Ajustes de este canal».
SETTINGS_INSTAGRAM_ROUTE: Final = "/chats/ajustes/instagram"
#: m-25027373 (BU-A10): the WhatsApp number's profile (with «Tu local en el mapa», what
#: «Cómo llegar» sends), its QR codes and the payment methods — once «Tu número»'s
#: sub-tabs, now pages of «Ajustes de chats».
SETTINGS_PROFILE_ROUTE: Final = "/chats/ajustes/whatsapp/perfil"
SETTINGS_QR_ROUTE: Final = "/chats/ajustes/whatsapp/codigos-qr"
SETTINGS_PAYMENTS_ROUTE: Final = "/chats/ajustes/formas-de-pago"

CHAT_SETTINGS_TITLE: Final = "Ajustes de chats"
CHAT_SETTINGS_SUBTITLE: Final = (
    "Prepara una vez lo que tus clientes ven al escribirte. Tus chats siguen en Por responder."
)
#: The menu panel's name everywhere (decision vi, founder 2026-11-14).
MENU_TITLE: Final = "Tu menú de bienvenida"
#: D5 (founder 2026-11-12): «Preguntas iniciales» in both channels («Atajos» on WhatsApp
#: before), each with this same line.
STARTER_QUESTIONS_TITLE: Final = "Preguntas iniciales"
STARTER_QUESTIONS_LINE: Final = "Lo que tu cliente puede tocar al abrir el chat"

ALL_CHATS_TITLE: Final = "Para todos tus chats"
WHATSAPP_TITLE: Final = "WhatsApp"
INSTAGRAM_TITLE: Final = "Instagram"

#: Where each thing is kept today (the rows of «Para todos tus chats» point there).
SAVED_MESSAGES_HREF: Final = "/responder?tab=mensajes"
PAYMENTS_HREF: Final = SETTINGS_PAYMENTS_ROUTE
DIRECTIONS_HREF: Final = SETTINGS_PROFILE_ROUTE
CONNECTIONS_HREF: Final = "/connections"
#: The chats, for the way back (N7) and the header line.
CHATS_HREF: Final = "/responder"
BACK_TO_CHATS: Final = "Ir a tus chats"

ACCOUNT_PARAM: Final = "cuenta"


@dataclass(frozen=True)
class SettingRowVM:
    """One row of a card: a title, the line under it, where it goes. `href` "" means
    the row is an action of the page (the Instagram drawer), not a link."""

    key: str
    title: str
    detail: str
    href: str
    icon: str


@dataclass(frozen=True)
class InstagramRowVM:
    """«Preguntas iniciales» of one connected Instagram account."""

    connection_id: str
    title: str
    detail: str


#: «Para todos tus chats» (UX review 2026-11-15): each row says which network it works
#: on today, never where it is stored. The two that are kept with the WhatsApp number
#: (`WHATSAPP_ONLY_KEYS`) are hidden when the business has none: they would lead to
#: «Conecta tu WhatsApp».
ALL_CHATS_ROWS: Final[tuple[SettingRowVM, ...]] = (
    SettingRowVM(
        "mensajes-guardados",
        "Mensajes guardados",
        "Escríbelos una vez y úsalos al responder. Por ahora, en tus chats de Instagram.",
        SAVED_MESSAGES_HREF,
        "library",
    ),
    SettingRowVM(
        "formas-de-pago",
        "Formas de pago",
        "Tus datos y tu QR, listos para mandar desde el «+» del chat. Por ahora, en WhatsApp.",
        PAYMENTS_HREF,
        "wallet",
    ),
    SettingRowVM(
        "como-llegar",
        "Cómo llegar",
        "Tu dirección y el punto en el mapa, para mandarlos cuando te pregunten.",
        DIRECTIONS_HREF,
        "map-pin",
    ),
)
WHATSAPP_ONLY_KEYS: Final = frozenset({"formas-de-pago", "como-llegar"})
ALWAYS_ROWS: Final = tuple(r for r in ALL_CHATS_ROWS if r.key not in WHATSAPP_ONLY_KEYS)
WHATSAPP_NUMBER_ROWS: Final = tuple(r for r in ALL_CHATS_ROWS if r.key in WHATSAPP_ONLY_KEYS)

#: The menu (UX review U3: the starter questions are part of it), then — m-25027373 —
#: the number's profile and QR codes, which left «Tu número».
#: m-25027373 — the two `detail` lines are NEW TEXT, NOT DECIDED BY THE FOUNDER.
PROFILE_TITLE: Final = "Perfil"
QR_TITLE: Final = "Códigos QR"
WHATSAPP_ROWS: Final[tuple[SettingRowVM, ...]] = (
    SettingRowVM(
        "menu",
        MENU_TITLE,
        "Tu bienvenida, tus productos, tus preguntas iniciales y las respuestas a las "
        "preguntas de siempre.",
        SETTINGS_WHATSAPP_ROUTE,
        "list",
    ),
    SettingRowVM(
        "perfil",
        PROFILE_TITLE,
        "Tu foto, tu descripción y tus datos de contacto, como los ven tus clientes en WhatsApp.",
        SETTINGS_PROFILE_ROUTE,
        "store",
    ),
    SettingRowVM(
        "codigos-qr",
        QR_TITLE,
        "Códigos que abren un chat contigo: para el mostrador, el empaque o tu Instagram.",
        SETTINGS_QR_ROUTE,
        "qr-code",
    ),
)

NO_WHATSAPP: Final = "Todavía no tienes tu número de WhatsApp conectado."
NO_WHATSAPP_ACTION: Final = "Ver cómo conectarlo"
#: The no-number state, with its «Pedir que conecten mi WhatsApp», is also on the menu's
#: page — so this hub never depends on `/whatsapp` (whose Chats tab is leaving, BU-A11).
NO_WHATSAPP_HREF: Final = SETTINGS_WHATSAPP_ROUTE
NO_INSTAGRAM: Final = "Todavía no tienes una cuenta de Instagram conectada."
NO_INSTAGRAM_ACTION: Final = "Conectar en Tus redes"
CONNECTIONS_NOTE: Final = "¿Tu WhatsApp o tu Instagram dejó de funcionar?"
CONNECTIONS_ACTION: Final = "Ir a Tus redes"
LOAD_FAILED: Final = "No pudimos cargar tus cuentas. Revisa tu conexión y vuelve a intentarlo."
RETRY: Final = "Volver a intentar"


def instagram_rows(accounts: list[tuple[str, str]]) -> list[InstagramRowVM]:
    """(connection id, «@cuenta») per connected Instagram account → its row. With one
    account the row is just «Preguntas iniciales»; with several, each says whose."""
    many = len(accounts) > 1
    return [
        InstagramRowVM(
            connection_id=connection_id,
            title=(
                f"{STARTER_QUESTIONS_TITLE} de {label}"
                if many and label
                else STARTER_QUESTIONS_TITLE
            ),
            detail=STARTER_QUESTIONS_LINE,
        )
        for connection_id, label in accounts
    ]


def instagram_settings_href(connection_id: str) -> str:
    """The Instagram chat's «Ajustes de este canal»: the hub with that account's
    «Preguntas iniciales» open."""
    return with_query(SETTINGS_INSTAGRAM_ROUTE, **{ACCOUNT_PARAM: connection_id})


def account_to_open(requested: str, account_ids: list[str]) -> str:
    """On `SETTINGS_INSTAGRAM_ROUTE`: the account whose «Preguntas iniciales» opens — the
    one in `?cuenta=` only when it is one of the business's; anything else (missing,
    junk, another business's) opens nothing (code review, 2026-11-15)."""
    return requested if requested and requested in account_ids else ""
