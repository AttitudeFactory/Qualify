"""Resultados' view models (m-24843003, RESULTADOS-5) — pure, tested in `test_results_vm.py`.

Resultados is the one place that answers «¿cómo me va?» (`docs/ux-guia-navegacion.md`
§2-3, founder decisions 1-2): four tabs, each with its own address (`?tab=`, N5):

- «Redes» — the week on Instagram: who wrote, who commented, what came out, who talked
  about the business. Every figure opens its list (N11).
- «WhatsApp» — the week on the business's WhatsApp number.
- «Tu página web» — the Clarity reading screen (RESULTADOS-3), unchanged.
- «Quién habla de ti» — the mentions listing (RESULTADOS-1), unchanged.

Without data, each tab says what to connect and links there (N8); the last two already
do so on their own screens. `/clarity` and `/menciones` redirect here (`legacy_*_url`),
keeping their query string so a saved «Negativas» link still opens filtered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlencode

from qualify_api.home import ResultsCounts

RESULTS_ROUTE = "/resultados"
TAB_PARAM = "tab"

TAB_SOCIAL = "redes"
TAB_WHATSAPP = "whatsapp"
TAB_WEB = "web"
TAB_MENTIONS = "menciones"

#: (key, label) in the order of the guide §3: Redes · WhatsApp · Tu página web · Quién
#: habla de ti. Four tabs: the most N12 allows on a phone without sliding sideways.
TABS: tuple[tuple[str, str], ...] = (
    (TAB_SOCIAL, "Redes"),
    (TAB_WHATSAPP, "WhatsApp"),
    (TAB_WEB, "Tu página web"),
    (TAB_MENTIONS, "Quién habla de ti"),
)
TAB_KEYS: frozenset[str] = frozenset(key for key, _label in TABS)
DEFAULT_TAB = TAB_SOCIAL

TITLE = "Resultados"
SUBTITLE = "Cómo te va en tus redes, tu WhatsApp y tu página web"
TAB_SELECT_LABEL = "Estás viendo"

#: The browser tab's title per tab (N1): the hub's name on its first tab, the place's own
#: name on the two that used to be screens of their own («Tu página web», and Menciones,
#: now «Quién habla de ti» — ticket m-24843003). «WhatsApp» alone would read as the
#: WhatsApp module, so its tab says whose results they are.
TAB_TITLES: dict[str, str] = {
    TAB_SOCIAL: "Qualify · Resultados",
    TAB_WHATSAPP: "Qualify · Resultados de WhatsApp",
    TAB_WEB: "Qualify · Tu página web",
    TAB_MENTIONS: "Qualify · Quién habla de ti",
}

# Destinations (N11): the list each figure counts.
CONVERSATIONS_URL = "/conversations"
COMMENTS_URL = "/inbox"
PLANNER_URL = "/planner"
CONNECTIONS_URL = "/connections"
CREATE_URL = "/create"
WHATSAPP_CHATS_URL = "/whatsapp?tab=chats"
WHATSAPP_MODULE_URL = "/whatsapp"
WHATSAPP_NUMBERS_URL = "/whatsapp?tab=conexion"
WHATSAPP_QR_URL = "/whatsapp?tab=qr"


def resolve_tab(requested: str) -> str:
    """`?tab=<key>` → a known tab key; anything else → the first tab. The value arrives in
    the URL, so junk is ignored rather than echoed."""
    return requested if requested in TAB_KEYS else DEFAULT_TAB


def tab_url(tab: str, **params: str) -> str:
    """The address of one tab, with any extra filter (`sentimiento=negativas`)."""
    query = {TAB_PARAM: resolve_tab(tab), **{k: v for k, v in params.items() if v}}
    return f"{RESULTS_ROUTE}?{urlencode(query)}"


MENTIONS_URL = tab_url(TAB_MENTIONS)
WEB_URL = tab_url(TAB_WEB)


def _legacy_url(tab: str, query: dict[str, str]) -> str:
    kept = {str(k): str(v) for k, v in query.items() if k != TAB_PARAM and v}
    return tab_url(tab, **kept)


def legacy_mentions_url(query: dict[str, str]) -> str:
    """`/menciones?…` → «Quién habla de ti», the filters kept (`?sentimiento=negativas`)."""
    return _legacy_url(TAB_MENTIONS, query)


def legacy_clarity_url(query: dict[str, str]) -> str:
    """`/clarity?…` → «Tu página web»."""
    return _legacy_url(TAB_WEB, query)


def tab_title(tab: str) -> str:
    return TAB_TITLES[resolve_tab(tab)]


def tab_switch_script(tab: str) -> str:
    """JS that writes the tab's address as a new history step and names the browser tab.

    `history.pushState`, not `rx.redirect`: a redirect would re-run the whole `on_load`
    for a change the state already made; «atrás» is a real navigation, so `enter_page`
    reads the previous `?tab=` back (N5). The guard keeps a repeated tap from stacking
    identical history entries. Same mechanism as NAV-2's `nav_url.push_url_script`
    (m-24842960) — switch to it once that lands."""
    url = json.dumps(tab_url(tab))
    title = json.dumps(tab_title(tab), ensure_ascii=False)
    return (
        f"if (window.location.pathname + window.location.search !== {url}) "
        f"window.history.pushState(window.history.state, '', {url});"
        f"document.title = {title};"
    )


def tab_title_script(tab: str) -> str:
    """JS that only names the browser tab (entering the page, or «atrás»)."""
    return f"document.title = {json.dumps(tab_title(tab), ensure_ascii=False)};"


@dataclass(frozen=True)
class TabVM:
    key: str
    label: str


TAB_VMS: list[TabVM] = [TabVM(key, label) for key, label in TABS]


@dataclass(frozen=True)
class ResultStatVM:
    key: str
    label: str
    value: int
    hint: str
    href: str


@dataclass(frozen=True)
class ResultsVM:
    social: list[ResultStatVM] = field(default_factory=list)
    whatsapp: list[ResultStatVM] = field(default_factory=list)
    #: «Redes» has nothing to show until Instagram is connected: say what to connect.
    social_needs_connection: bool = True
    #: Instagram is connected but the week counted nothing: a way out, not four zeros.
    social_quiet: bool = False
    whatsapp_needs_connection: bool = True
    whatsapp_quiet: bool = False
    #: Picks the way out of «Aún no hay menciones»: connect Instagram, or invite tags.
    instagram_connected: bool = False


def _plural(n: int, one: str, many: str) -> str:
    return (one if n == 1 else many).format(n=n)


def people_hint(n: int) -> str:
    return _plural(n, "{n} persona", "{n} personas")


def _social(counts: ResultsCounts) -> list[ResultStatVM]:
    return [
        ResultStatVM(
            "messages",
            "Te escribieron por Instagram",
            counts.messages_week_dm,
            people_hint(counts.people_week_dm),
            CONVERSATIONS_URL,
        ),
        ResultStatVM(
            "comments",
            "Comentaron",
            counts.comments_week,
            "En tus publicaciones",
            COMMENTS_URL,
        ),
        ResultStatVM(
            "published",
            "Publicaste",
            counts.published_week,
            "En Instagram y Facebook",
            PLANNER_URL,
        ),
        ResultStatVM(
            "mentions",
            "Hablaron de ti",
            counts.mentions_week,
            "Te etiquetaron",
            MENTIONS_URL,
        ),
    ]


def _whatsapp(counts: ResultsCounts) -> list[ResultStatVM]:
    return [
        ResultStatVM(
            "messages",
            "Mensajes que recibiste",
            counts.messages_week_whatsapp,
            "En tus chats de WhatsApp",
            WHATSAPP_CHATS_URL,
        ),
        ResultStatVM(
            "people",
            "Personas que te escribieron",
            counts.people_week_whatsapp,
            "Cada chat cuenta una vez",
            WHATSAPP_CHATS_URL,
        ),
    ]


def build_results_vm(counts: ResultsCounts) -> ResultsVM:
    social = _social(counts)
    whatsapp = _whatsapp(counts)
    social_empty = all(stat.value == 0 for stat in social)
    whatsapp_empty = all(stat.value == 0 for stat in whatsapp)
    return ResultsVM(
        social=social,
        whatsapp=whatsapp,
        social_needs_connection=social_empty and not counts.instagram_connected,
        social_quiet=social_empty and counts.instagram_connected,
        whatsapp_needs_connection=whatsapp_empty and not counts.whatsapp_connected,
        whatsapp_quiet=whatsapp_empty and counts.whatsapp_connected,
        instagram_connected=counts.instagram_connected,
    )


EMPTY_RESULTS = build_results_vm(ResultsCounts())

__all__ = [
    "COMMENTS_URL",
    "CONNECTIONS_URL",
    "CONVERSATIONS_URL",
    "CREATE_URL",
    "DEFAULT_TAB",
    "EMPTY_RESULTS",
    "MENTIONS_URL",
    "PLANNER_URL",
    "RESULTS_ROUTE",
    "SUBTITLE",
    "TABS",
    "TAB_KEYS",
    "TAB_MENTIONS",
    "TAB_SELECT_LABEL",
    "TAB_SOCIAL",
    "TAB_TITLES",
    "TAB_VMS",
    "TAB_WEB",
    "TAB_WHATSAPP",
    "TITLE",
    "WEB_URL",
    "WHATSAPP_CHATS_URL",
    "WHATSAPP_MODULE_URL",
    "WHATSAPP_NUMBERS_URL",
    "WHATSAPP_QR_URL",
    "ResultStatVM",
    "ResultsVM",
    "TabVM",
    "build_results_vm",
    "legacy_clarity_url",
    "legacy_mentions_url",
    "people_hint",
    "resolve_tab",
    "tab_switch_script",
    "tab_title",
    "tab_title_script",
    "tab_url",
]
