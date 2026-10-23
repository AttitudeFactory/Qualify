"""View models of «Por responder» (`/responder`, m-24842990, ATENDER-1). Pure: no Reflex,
no database — what the page shows is decided here and tested offline.

- **Tabs** (founder decision 3, 2026-10-23): Mensajes · Quieren comprar · Comentarios ·
  WhatsApp · Interesados, each with its own address `?tab=<key>` (N5), so the phone's
  «atrás» and a reload land on the same tab.
- **Counts** (N11): four rows — Instagram messages, people who want to buy, comments with
  a reply ready, WhatsApp chats — each with «Ver» to its list already filtered on what is
  pending. The WhatsApp chats stay in the WhatsApp module (out of scope to merge them):
  its «Ver» opens `/whatsapp?tab=chats` on «Sin leer».
- **Old addresses** (`/inbox`, `/conversations`, `/leads`) redirect to their tab, keeping
  the query they carried (`/conversations?consulta=<id>` lands on that card).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from qualify_api.attention import PendingCounts

ROUTE: Final = "/responder"

TAB_MESSAGES: Final = "mensajes"
TAB_BUYERS: Final = "comprar"
TAB_COMMENTS: Final = "comentarios"
TAB_WHATSAPP: Final = "whatsapp"
TAB_LEADS: Final = "interesados"

#: (key, label) in the order of the guide (ux-guia-navegacion §3).
TABS: Final[tuple[tuple[str, str], ...]] = (
    (TAB_MESSAGES, "Mensajes"),
    (TAB_BUYERS, "Quieren comprar"),
    (TAB_COMMENTS, "Comentarios"),
    (TAB_WHATSAPP, "WhatsApp"),
    (TAB_LEADS, "Interesados"),
)
TAB_KEYS: Final = frozenset(key for key, _label in TABS)
DEFAULT_TAB: Final = TAB_MESSAGES

#: `?filtro=` value that opens Mensajes on «Pendientes».
FILTER_PARAM: Final = "filtro"
FILTER_PENDING: Final = "pendientes"
#: `/whatsapp?tab=chats&filtro=sin-leer` opens WhatsApp › Chats on «Sin leer».
WHATSAPP_UNREAD: Final = "sin-leer"
WHATSAPP_CHATS_HREF: Final = f"/whatsapp?tab=chats&{FILTER_PARAM}={WHATSAPP_UNREAD}"

#: Where each old address lands.
LEGACY_TABS: Final[dict[str, str]] = {
    "/inbox": TAB_COMMENTS,
    "/conversations": TAB_MESSAGES,
    "/leads": TAB_LEADS,
}
#: `/conversations?consulta=<id>` was the Consultas view on one card: now Quieren comprar.
QUERY_PARAM: Final = "consulta"

ALL_CLEAR_TITLE: Final = "¡Al día! No hay nadie esperando tu respuesta."
ALL_CLEAR_BODY: Final = (
    "Cuando alguien te escriba o comente, lo verás aquí. Mientras tanto, prepara tu "
    "próxima publicación."
)
ALL_CLEAR_ACTION: Final = "Crear la próxima publicación"
ALL_CLEAR_HREF: Final = "/create"

COUNTS_FAILED: Final = (
    "No pudimos contar quién espera tu respuesta. Revisa tu conexión y toca «Reintentar»."
)


def resolve_tab(requested: str | None) -> str:
    """The tab a `?tab=` value asks for; anything unknown is Mensajes."""
    value = (requested or "").strip().lower()
    return value if value in TAB_KEYS else DEFAULT_TAB


def tab_href(tab: str, **params: str) -> str:
    """`/responder?tab=<tab>` plus any extra query, in a stable order."""
    query = {"tab": resolve_tab(tab), **{k: v for k, v in params.items() if v}}
    return f"{ROUTE}?{urlencode(query)}"


def legacy_target(path: str, params: Mapping[str, object]) -> str:
    """Where an old address goes, keeping the query it carried. `?tab=` of the old page
    (none had one) is dropped: the new tab is decided by the path."""
    clean = path.rstrip("/") or "/"
    tab = LEGACY_TABS.get(clean, DEFAULT_TAB)
    kept = {str(k): str(v) for k, v in params.items() if k != "tab" and v not in (None, "")}
    if clean == "/conversations" and kept.get(QUERY_PARAM):
        tab = TAB_BUYERS
    return tab_href(tab, **kept)


@dataclass(frozen=True)
class CountRowVM:
    key: str
    icon: str
    label: str
    count: int
    count_label: str
    tone: str
    href: str
    action_label: str


def count_label(count: int) -> str:
    if count <= 0:
        return "Al día"
    return "1 espera" if count == 1 else f"{count} esperan"


def count_rows(counts: PendingCounts) -> list[CountRowVM]:
    """The four rows, in tab order. A row with someone waiting is `warn` (an action is
    due); an empty one is `ok`."""
    spec = (
        (
            TAB_MESSAGES,
            "messages-square",
            "Mensajes de Instagram sin responder",
            counts.messages,
            tab_href(TAB_MESSAGES, **{FILTER_PARAM: FILTER_PENDING}),
        ),
        (
            TAB_BUYERS,
            "shopping-bag",
            "Personas que quieren comprar",
            counts.buyers,
            tab_href(TAB_BUYERS),
        ),
        (
            TAB_COMMENTS,
            "film",
            "Comentarios con respuesta lista para aprobar",
            counts.comments,
            tab_href(TAB_COMMENTS),
        ),
        (
            TAB_WHATSAPP,
            "message-circle",
            "Chats de WhatsApp sin responder",
            counts.whatsapp,
            WHATSAPP_CHATS_HREF,
        ),
    )
    return [
        CountRowVM(
            key=key,
            icon=icon,
            label=label,
            count=max(0, count),
            count_label=count_label(count),
            tone="warn" if count > 0 else "ok",
            href=href,
            action_label="Ver",
        )
        for key, icon, label, count, href in spec
    ]


def all_clear(counts: PendingCounts) -> bool:
    return counts.total <= 0
