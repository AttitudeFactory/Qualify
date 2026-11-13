"""View models of «Por responder» (`/responder`, m-24842990, ATENDER-1). Pure: no Reflex,
no database — what the page shows is decided here and tested offline.

- **Tabs** (founder decision 3, 2026-10-23): Mensajes · Quieren comprar · Comentarios ·
  Interesados, each with its own address `?tab=<key>` (N5), so the phone's «atrás» and a
  reload land on the same tab. m-25017859: «Mensajes» is the single list of every chat
  channel (`inbox_list_vm`), so the «WhatsApp» tab (a link card) left the tree;
  `?tab=whatsapp` redirects to «Mensajes» narrowed to WhatsApp (UX doc §2).
- **Counts** (N11): four rows — Instagram messages, people who want to buy, comments with
  a reply ready, WhatsApp chats — each with «Ver» to its list already filtered on what is
  pending: the two chat rows open the single list on «Por responder» narrowed to their
  channel, so the figure is the length of the list (both count `inbox.awaiting`).
- **Old addresses** (`/inbox`, `/conversations`, `/leads`) redirect to their tab, keeping
  the query they carried (`/conversations?consulta=<id>` lands on that card).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from qualify_api.attention import PendingCounts

from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP
from .inbox_list_vm import FILTER_AWAITING, list_href

ROUTE: Final = "/responder"

TAB_MESSAGES: Final = "mensajes"
TAB_BUYERS: Final = "comprar"
TAB_COMMENTS: Final = "comentarios"
TAB_LEADS: Final = "interesados"
#: m-25017859: no longer a tab — the old address lands on the single list, WhatsApp.
LEGACY_TAB_WHATSAPP: Final = "whatsapp"

#: (key, label) in the order of the guide (ux-guia-navegacion §3).
TABS: Final[tuple[tuple[str, str], ...]] = (
    (TAB_MESSAGES, "Mensajes"),
    (TAB_BUYERS, "Quieren comprar"),
    (TAB_COMMENTS, "Comentarios"),
    (TAB_LEADS, "Interesados"),
)
TAB_KEYS: Final = frozenset(key for key, _label in TABS)
DEFAULT_TAB: Final = TAB_MESSAGES

#: The single list on «Por responder», per channel: where each chat row's «Ver» lands.
INSTAGRAM_AWAITING_HREF: Final = list_href(FILTER_AWAITING, CHANNEL_INSTAGRAM)
WHATSAPP_AWAITING_HREF: Final = list_href(FILTER_AWAITING, CHANNEL_WHATSAPP)

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
ALL_CLEAR_ACTION: Final = "Crear publicación"
ALL_CLEAR_HREF: Final = "/create"

#: The visible label over the phone's tab select.
TAB_SELECT_LABEL: Final = "Estás viendo"

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


def legacy_tab_target(requested: str | None) -> str | None:
    """`?tab=whatsapp` (the tab that left, m-25017859) → the single list on «Por
    responder» narrowed to WhatsApp; None for every other value."""
    value = (requested or "").strip().lower()
    return WHATSAPP_AWAITING_HREF if value == LEGACY_TAB_WHATSAPP else None


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


@dataclass(frozen=True)
class TabVM:
    key: str
    label: str


def tab_label(label: str, count: int) -> str:
    """A tab's label with its figure («Mensajes · 3»), so what waits in another list shows
    without opening it; with nobody waiting, only the name."""
    return f"{label} · {count}" if count > 0 else label


def tab_vms(counts: PendingCounts | None = None) -> list[TabVM]:
    """The four tabs in order, with their figure once the counts are in. «Mensajes» counts
    every chat channel (the single list's «Por responder»); Interesados is never
    counted."""
    figures = (
        {}
        if counts is None
        else {
            TAB_MESSAGES: counts.messages + counts.whatsapp,
            TAB_BUYERS: counts.buyers,
            TAB_COMMENTS: counts.comments,
        }
    )
    return [TabVM(key=key, label=tab_label(label, figures.get(key, 0))) for key, label in TABS]


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
            INSTAGRAM_AWAITING_HREF,
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
            "message-square-text",
            "Comentarios con respuesta lista para aprobar",
            counts.comments,
            tab_href(TAB_COMMENTS),
        ),
        (
            LEGACY_TAB_WHATSAPP,
            "message-circle",
            "Chats de WhatsApp sin responder",
            counts.whatsapp,
            WHATSAPP_AWAITING_HREF,
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
