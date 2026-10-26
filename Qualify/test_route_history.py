"""PASOS-3: explicit POP restoration and UUID-only tenant-scoped detail links."""

from __future__ import annotations

import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from .nav_url import back_url_script, conversation_href, push_url_script, thread_param, uuid_param
from .ui.route_history import _POP_SCRIPT

ACCOUNT, OTHER, THREAD = str(uuid4()), str(uuid4()), str(uuid4())


@pytest.mark.parametrize("bad", ["", "phone+573001234567", "Laura", [THREAD], None, {}])
def test_uuid_reader_refuses_names_phones_repeated_and_malformed_values(bad: object) -> None:
    assert uuid_param({"chat": bad}, "chat") == ""


def test_conversation_links_round_trip_only_internal_ids() -> None:
    assert conversation_href("whatsapp", ACCOUNT, THREAD) == (
        f"/whatsapp?tab=chats&cuenta={ACCOUNT}&chat={THREAD}"
    )
    assert conversation_href("instagram", ACCOUNT, THREAD) == (
        f"/responder?tab=mensajes&cuenta={ACCOUNT}&chat={THREAD}"
    )
    assert conversation_href("whatsapp", "Laura", "+573001234567") == "/whatsapp?tab=chats"
    assert thread_param({"cuenta": ACCOUNT, "chat": THREAD}, ACCOUNT) == THREAD
    assert thread_param({"cuenta": OTHER, "chat": THREAD}, ACCOUNT) == ""
    assert thread_param({"cuenta": "bad", "chat": THREAD}, ACCOUNT) == ""
    assert thread_param({"cuenta": [ACCOUNT], "chat": THREAD}, ACCOUNT) == ""
    assert thread_param({"chat": THREAD}, ACCOUNT) == THREAD
    assert thread_param({}, ACCOUNT) == ""


def _node(script: str) -> object:
    binary = shutil.which("node")
    if not binary:
        pytest.skip("Node is required to exercise browser history scripts")
    result = subprocess.run([binary, "-e", script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_pushing_and_closing_a_detail_consumes_its_entry_without_losing_router_state() -> None:
    listing = conversation_href("whatsapp", ACCOUNT)
    detail = conversation_href("whatsapp", ACCOUNT, THREAD)
    location = json.dumps({"pathname": "/whatsapp", "search": listing.split("/whatsapp")[1]})
    script = f"""
const result = [];
const window = {{location: {location}}};
window.history = {{state: {{key: 'router-key', idx: 7}},
  pushState(state, _, href) {{this.state=state; result.push(['push', state, href]);}},
  replaceState(state, _, href) {{result.push(['replace', state, href]);}},
  back() {{result.push(['back']);}}
}};
{push_url_script(detail)}
{back_url_script(listing)}
console.log(JSON.stringify(result));
"""
    events = _node(script)
    assert events[0][0] == "push"
    assert events[0][1] == {"key": "router-key", "idx": 7, "qPrevHref": listing}
    assert events[0][2] == detail
    assert events[1] == ["back"]


def test_pop_listener_is_installed_once_and_only_calls_the_current_route_trigger() -> None:
    script = f"""
let listener, installs=0, clicks=0;
const window={{addEventListener(type, fn) {{if(type==='popstate') {{listener=fn; installs++;}}}},
setTimeout(fn){{fn();}}}};
let mounted = true;
const document={{querySelector(selector) {{
 if(selector !== 'main.q-panel .q-route-pop') throw Error(selector);
 return mounted ? {{click() {{clicks++;}}}} : null;
}}}};
{_POP_SCRIPT}
{_POP_SCRIPT}
listener(); mounted=false; listener();
console.log(JSON.stringify({{installs, clicks}}));
"""
    assert _node(script) == {"installs": 1, "clicks": 1}


async def test_instagram_deep_link_cannot_read_another_tenants_thread(monkeypatch) -> None:
    from . import conversations_state as module
    from .test_conversations_provider import CONNECTION, TENANT, World

    world = World()
    thread = world.inbound(tenant_id=uuid4())
    state = module.ConversationsState()
    state.selected_connection_id = str(CONNECTION)
    state.open_thread_id = str(thread)

    async def tenant(_state):
        return TENANT

    monkeypatch.setattr(module.ConversationsState, "_tenant", tenant)
    monkeypatch.setattr(module, "gateway", lambda: world.gateway)
    await state._read_conversation(silent=False, mark_read=True)
    assert state.open_thread_id == ""
    assert not state.messages
    assert state.banner == module._THREAD_GONE


async def test_whatsapp_deep_link_cannot_read_another_tenants_thread(monkeypatch) -> None:
    from datetime import timedelta

    from . import whatsapp_chats_state as module
    from .test_whatsapp_chats_provider import NUMBER, OTHER_TENANT, TENANT, World

    world = World()
    thread = world.thread(tenant=OTHER_TENANT, inbound_ago=timedelta(minutes=1))
    state = module.WhatsAppChatsState()
    state._connection_id = str(NUMBER)
    state.open_thread_id = str(thread)

    async def tenant(_state):
        return TENANT

    monkeypatch.setattr(module.WhatsAppChatsState, "_tenant", tenant)
    monkeypatch.setattr(module, "gateway", lambda: world.gateway)
    await state._read_conversation(silent=False)
    assert state.open_thread_id == ""
    assert not state.messages
    assert state.banner == module._THREAD_GONE
