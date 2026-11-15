"""View models of «Ajustes de chats» (m-25017861, story BU-A9 of docs/epica-bandeja-unica.md).

Decision D1 (founder, 2026-11-12, docs/ux-chats-unificados.md §3): what the owner
prepares once lives apart from the messages, in «Ajustes de chats» under «Atiende». One
screen, three cards, no tabs (mockup `docs/mockups/chats-unificados.html`, part F):

    Para todos tus chats   Mensajes guardados · Formas de pago · Cómo llegar
    WhatsApp               Tu menú de bienvenida · Preguntas iniciales
    Instagram              Preguntas iniciales (one row per connected account)

Each row opens the screen that already exists. Names: «Tu menú de bienvenida» is the
founder's decision (vi) of 2026-11-14 — never «Respuesta automática», nothing that says
or suggests Qualify answers by itself; «Preguntas iniciales» is D5, with the same line in
both channels (`STARTER_QUESTIONS_LINE`).

What is NOT built here, on purpose (each its own ticket): one saved-messages library for
every channel (BU-A8: today they are Instagram's «Plantillas»), payments and «Cómo
llegar» as data of the business (BU-A14: today they are kept with the WhatsApp number,
under «Tu número», which moves to «Tus redes» in BU-A10). Those rows say where the thing
lives today and take the owner there.

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
PAYMENTS_HREF: Final = "/whatsapp?tab=numero&sub=pagos"
DIRECTIONS_HREF: Final = "/whatsapp?tab=numero&sub=perfil"
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


ALL_CHATS_ROWS: Final[tuple[SettingRowVM, ...]] = (
    SettingRowVM(
        "mensajes-guardados",
        "Mensajes guardados",
        "Escríbelos una vez y úsalos al responder. Hoy están en tus chats de Instagram, "
        "en «Plantillas».",
        SAVED_MESSAGES_HREF,
        "library",
    ),
    SettingRowVM(
        "formas-de-pago",
        "Formas de pago",
        "Tus datos y tu QR, listos para mandar desde el «+» del chat. Hoy se guardan con "
        "tu número de WhatsApp.",
        PAYMENTS_HREF,
        "wallet",
    ),
    SettingRowVM(
        "como-llegar",
        "Cómo llegar",
        "Tu dirección y el punto en el mapa. Hoy se guardan en el perfil de tu número de WhatsApp.",
        DIRECTIONS_HREF,
        "map-pin",
    ),
)

WHATSAPP_ROWS: Final[tuple[SettingRowVM, ...]] = (
    SettingRowVM(
        "menu",
        MENU_TITLE,
        "Tu bienvenida, tus productos y las respuestas a las preguntas de siempre.",
        SETTINGS_WHATSAPP_ROUTE,
        "list",
    ),
    SettingRowVM(
        "preguntas-iniciales",
        STARTER_QUESTIONS_TITLE,
        f"{STARTER_QUESTIONS_LINE}. Están dentro de tu menú, en «Más opciones (avanzado)».",
        SETTINGS_WHATSAPP_ROUTE,
        "message-circle-question",
    ),
)

NO_WHATSAPP: Final = "Todavía no tienes tu número de WhatsApp conectado."
NO_WHATSAPP_ACTION: Final = "Ver cómo conectarlo"
#: The no-number state, with its «Pedir que conecten mi WhatsApp», is also on the menu's
#: page — so this hub never depends on `/whatsapp` (whose Chats tab is leaving, BU-A11).
NO_WHATSAPP_HREF: Final = SETTINGS_WHATSAPP_ROUTE
NO_INSTAGRAM: Final = "Todavía no tienes una cuenta de Instagram conectada."
NO_INSTAGRAM_ACTION: Final = "Conectar en Tus redes"
CONNECTIONS_NOTE: Final = "¿Tu WhatsApp o tu Instagram dejó de funcionar? Revísalo en Tus redes."
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
    one in `?cuenta=` when it is one of the business's, else the first; "" without any.
    Anything else in the address is ignored, never echoed."""
    if requested in account_ids:
        return requested
    return account_ids[0] if account_ids else ""
