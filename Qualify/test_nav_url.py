"""m-24842960 (NAV-2): every tab, view and detail has its own address (N5) and every
back link names where it goes (N7).

The address is written with `history.pushState` (`nav_url`) and read back by each
route's `on_load` entry handler, which also runs on a reload and on the browser's
«atrás». The handlers' `self.router` needs a live event, so the reading side is pinned
through the pure resolvers plus the route registration; the writing side runs for real.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

from .followups_state import FollowupsState
from .followups_vm import VIEW_MESSAGES, VIEW_QUERIES, view_from_param, view_url
from .inbox_state import InboxState
from .inbox_vm import ReelSummaryVM, inbox_url
from .nav_url import push_url_script, replace_url_script, with_query
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import DEFAULT_TAB, TAB_KEYS, TAB_TEMPLATES, resolve_panel, tab_url

_HERE = Path(__file__).parent


def _script_of(spec: object) -> str:
    """The JS a `rx.call_script` EventSpec carries, as text."""
    return str(getattr(spec, "args", spec))


# --- the pure builders ------------------------------------------------------------------


def test_with_query_drops_empty_values_and_encodes() -> None:
    assert with_query("/inbox") == "/inbox"
    assert with_query("/inbox", publicacion="") == "/inbox"
    assert with_query("/whatsapp", tab="plantillas") == "/whatsapp?tab=plantillas"
    assert with_query("/x", a="b c", d="ñ") == "/x?a=b+c&d=%C3%B1"


def test_history_scripts_skip_a_repeated_address() -> None:
    push = push_url_script("/whatsapp?tab=qr")
    assert "window.history.pushState(window.history.state, ''," in push
    assert '"/whatsapp?tab=qr"' in push
    assert "window.location.pathname + window.location.search !==" in push
    assert "replaceState" in replace_url_script("/inbox")


def test_history_scripts_quote_the_address_as_a_js_string() -> None:
    script = push_url_script("/x?a='\"</script>")
    assert '"/x?a=\'\\"</script>"' in script


def test_every_whatsapp_tab_has_an_address_and_reads_back() -> None:
    # m-24842998: the address carries the top tab and, when it has one, the sub-tab.
    for key in TAB_KEYS:
        url = tab_url(key)
        assert url.startswith("/whatsapp?tab=")
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        assert resolve_panel(query["tab"], query.get("sub", "")) == key
    assert tab_url(TAB_TEMPLATES) == "/whatsapp?tab=promociones&sub=aprobados"
    assert tab_url("junk") == tab_url(DEFAULT_TAB) == "/whatsapp?tab=chats"


def test_conversations_view_round_trips_in_the_owners_words() -> None:
    assert view_url(VIEW_MESSAGES) == "/conversations?vista=mensajes"
    assert view_url(VIEW_QUERIES) == "/conversations?vista=consultas"
    assert view_from_param("consultas") == VIEW_QUERIES
    assert view_from_param("mensajes") == VIEW_MESSAGES
    assert view_from_param("") == VIEW_MESSAGES
    assert view_from_param("queries") == VIEW_MESSAGES  # internal keys are not the address


def test_inbox_detail_address() -> None:
    thread_id = str(uuid4())
    assert inbox_url() == "/responder?tab=comentarios"
    assert inbox_url(thread_id) == f"/responder?tab=comentarios&publicacion={thread_id}"


# --- the writing side, for real ---------------------------------------------------------


def test_whatsapp_tab_change_writes_the_address() -> None:
    state = WhatsAppState()
    spec = WhatsAppState.select_tab.fn(state, TAB_TEMPLATES)  # type: ignore[attr-defined]
    assert state.active_tab == TAB_TEMPLATES
    assert "/whatsapp?tab=promociones&sub=aprobados" in _script_of(spec)
    assert "pushState" in _script_of(spec)
    # Junk over the wire changes nothing and writes nothing.
    assert WhatsAppState.select_tab.fn(state, "nope") is None  # type: ignore[attr-defined]
    assert WhatsAppState.select_tab.fn(state, ["qr"]) is None  # type: ignore[attr-defined]
    assert state.active_tab == TAB_TEMPLATES


def test_conversations_view_change_writes_the_address() -> None:
    state = FollowupsState()
    events = FollowupsState.set_view.fn(state, VIEW_QUERIES)  # type: ignore[attr-defined]
    assert state.view == VIEW_QUERIES
    assert events is not None
    assert "/conversations?vista=consultas" in _script_of(events[0])
    assert len(events) == 2  # the address, then the queries load

    events = FollowupsState.set_view.fn(state, VIEW_MESSAGES)  # type: ignore[attr-defined]
    assert events is not None and len(events) == 1
    assert "/conversations?vista=mensajes" in _script_of(events[0])
    assert FollowupsState.set_view.fn(state, "junk") is None  # type: ignore[attr-defined]


def test_inbox_back_to_the_list_writes_the_list_address() -> None:
    state = InboxState()
    state.selected_thread_id = str(uuid4())
    spec = InboxState.back_to_reel_list.fn(state)  # type: ignore[attr-defined]
    assert state.selected_thread_id == ""
    script = _script_of(spec)
    # «atrás» never reopens it
    assert '"/responder?tab=comentarios"' in script and "replaceState" in script


def test_inbox_back_from_a_publication_keeps_the_loaded_list() -> None:
    # The phone's «atrás» from ?publicacion= to /inbox closes the detail like
    # «‹ Comentarios» and does not reload the list it already holds.
    state = InboxState()
    state.selected_thread_id = str(uuid4())
    state.reel_summaries = [
        ReelSummaryVM(
            thread_id=state.selected_thread_id,
            external_thread_id="m1",
            last_message_at="hoy",
            total=1,
            positive=1,
            neutral=0,
            negative=0,
            not_analyzed=0,
            thumbnail_url="",
            caption="",
            permalink="",
            is_monitored=False,
        )
    ]
    assert InboxState.enter_screen.fn(state) is None  # type: ignore[attr-defined]
    assert state.selected_thread_id == ""
    assert len(state.reel_summaries) == 1


def test_inbox_unknown_publication_falls_back_to_the_list_with_a_notice() -> None:
    source = inspect.getsource(InboxState.load_screen.fn)
    assert "self.missing_post_notice = _MISSING_POST" in source
    assert "replace_url_script(inbox_url())" in source


def test_inbox_open_detail_resets_to_a_clean_first_page() -> None:
    state = InboxState()
    state.search_query = "pizza"
    thread_id = str(uuid4())
    state._open_detail(thread_id)  # noqa: SLF001
    assert state.selected_thread_id == thread_id
    assert state.search_query == ""
    assert state.thread_comments == []


def test_select_reel_pushes_the_detail_address() -> None:
    source = inspect.getsource(InboxState.select_reel.fn)
    assert "push_url_script(inbox_url(thread_id))" in source
    assert "_try_uuid(thread_id) is None" in source  # junk ids never reach the address


# --- the reading side -------------------------------------------------------------------


def test_entry_handlers_read_their_parameter() -> None:
    whatsapp = inspect.getsource(WhatsAppState.enter_page.fn)
    assert "TAB_PARAM" in whatsapp and "SUB_PARAM" in whatsapp
    assert "VIEW_PARAM" in inspect.getsource(FollowupsState.enter_page.fn)
    inbox = inspect.getsource(InboxState.enter_screen.fn)
    assert "POST_PARAM" in inbox and "_try_uuid(wanted)" in inbox


def test_routes_run_the_entry_handlers_on_load() -> None:
    source = (_HERE / "Qualify.py").read_text()

    def block(anchor: str) -> str:
        start = source.index(anchor)
        return source[start : source.index(")", source.index("on_load", start)) + 1]

    assert "WhatsAppState.enter_page" in block("    whatsapp_index,")
    # m-24842990: the comments and the private inbox are tabs of «Por responder»; its
    # entry hands each tab over to that list's own entry handler.
    assert "ResponderState.enter_page" in block("    responder_index,")
    responder = (_HERE / "responder_state.py").read_text()
    assert "FollowupsState.enter_page" in responder
    assert "InboxState.enter_screen" in responder


# --- N7: back links say where they go ---------------------------------------------------


def test_back_links_name_their_destination() -> None:
    expectations = {
        "conversations_page.py": '"Conversaciones",\n        on_click=S.close_conversation',
        "whatsapp_tab_chats.py": '"Chats",\n        on_click=S.back_to_list',
        "inbox_page.py": '"Comentarios",\n            on_click=InboxState.back_to_reel_list',
    }
    for name, snippet in expectations.items():
        assert snippet in (_HERE / name).read_text(), name


def test_no_bare_volver_in_the_scoped_screens() -> None:
    scoped = [
        "conversations_page.py",
        "followups_page.py",
        "inbox_page.py",
        "whatsapp_page.py",
        *(p.name for p in _HERE.glob("whatsapp_tab_*.py")),
    ]
    for name in scoped:
        source = (_HERE / name).read_text()
        assert '"Volver"' not in source, name
        assert '"‹"' not in source, name
