"""PASOS-10: real scroll-scope measurements and visible, named ways back."""

from __future__ import annotations

import json
from pathlib import Path

from .conversations_page import _back_button as messages_back
from .creative_pages import draft_detail_index
from .responder_page import responder_header
from .test_route_history import _node
from .ui import tokens as T
from .whatsapp_page import whatsapp_header
from .whatsapp_tab_chats import _back_button as chats_back
from .whatsapp_tab_menu import _advanced

_ASSET = Path(__file__).parents[1] / "assets" / "glass-nav.js"
_SCRIPT = _ASSET.read_text().split("/* PASOS-10:", 1)[1]
_SCRIPT = "/* PASOS-10:" + _SCRIPT

_HARNESS = r"""
let resizeCallback, mutations, observerOptions, resizeInstalls=0, mutationInstalls=0;
let pending=[];const watched=new Set(),removed=[];
class ResizeObserver {constructor(callback){resizeCallback=callback;resizeInstalls++;}
 observe(node){watched.add(node);} unobserve(node){watched.delete(node);removed.push(node);}}
class MutationObserver {constructor(callback){mutations=callback;mutationInstalls++;}
 observe(root,options){observerOptions=options;}}
function scope(){const values={};return {nodeType:1,headers:[],style:{
 setProperty(key,value){values[key]=value;}, removeProperty(key){delete values[key];}},values,
 querySelectorAll(){return this.headers;}};}
function header(owner,height){return {nodeType:1,height,
 getClientRects(){return this.height>0?[{}]:[];},
 getBoundingClientRect(){return {height:this.height};},
 closest(selector){return selector==='main.q-panel, .q-drawer'?owner:this;},
 matches(){return true;}, querySelector(){return null;}};}
const panel=scope(),drawer=scope();
let pageHead=header(panel,117.4),drawerHead=header(drawer,81);
panel.headers=[pageHead];drawer.headers=[drawerHead];
const window={ResizeObserver,requestAnimationFrame(fn){pending.push(fn);},addEventListener(){}};
const document={documentElement:{},readyState:'complete',
 querySelectorAll(){return [panel,drawer];},addEventListener(){}};
function flush(){while(pending.length)pending.shift()();}
"""


def test_resize_measures_each_scope_and_releases_removed_headers() -> None:
    result = _node(
        _HARNESS
        + _SCRIPT
        + r"""
flush();const first={panel:panel.values['--q-sticky-header-height'],
 drawer:drawer.values['--q-sticky-header-height']};
pageHead.height=181;resizeCallback();flush();
const resized=panel.values['--q-sticky-header-height'];
const old=pageHead;pageHead=header(panel,96);panel.headers=[pageHead];
mutations([{type:'childList',target:{nodeType:0},addedNodes:[pageHead],removedNodes:[old]}]);flush();
drawerHead.height=0;resizeCallback();flush();
console.log(JSON.stringify({first,resized,replaced:panel.values['--q-sticky-header-height'],
 released:removed.includes(old),drawerFallback:!('--q-sticky-header-height' in drawer.values)}));
"""
    )
    assert result == {
        "first": {"panel": "118px", "drawer": "81px"},
        "resized": "181px",
        "replaced": "96px",
        "released": True,
        "drawerFallback": True,
    }


def test_unrelated_mutations_do_not_rescan_headers_or_create_style_feedback() -> None:
    result = _node(
        _HARNESS
        + _SCRIPT
        + r"""
flush();
const unrelated={nodeType:1,matches(){return false;},
 querySelector(){return null;},closest(){return null;}};
mutations([{type:'childList',target:unrelated,addedNodes:[unrelated],removedNodes:[]}]);
const queued=pending.length;
"""
        + _SCRIPT
        + r"""
console.log(JSON.stringify({queued,resizeInstalls,mutationInstalls,
 filters:observerOptions.attributeFilter}));
"""
    )
    assert result["queued"] == 0
    assert result["resizeInstalls"] == 1 and result["mutationInstalls"] == 1
    assert "style" not in result["filters"]
    assert T.SCROLL_MARGIN_TOP == "var(--q-sticky-header-height, 8rem)"


def _shown(rendered: str, text: str) -> bool:
    return text in rendered or json.dumps(text)[1:-1] in rendered


def test_phone_back_buttons_name_the_list_and_live_in_existing_sticky_headers() -> None:
    assert _shown(str(messages_back()), "Mensajes")
    assert _shown(str(chats_back()), "Chats")
    assert _shown(str(responder_header()), "Mensajes")
    header = str(whatsapp_header())
    assert _shown(header, "Chats") and _shown(header, "Volver a los 4 pasos")
    assert not _shown(str(_advanced()), "Volver a los 4 pasos")
    detail = str(draft_detail_index())
    assert "q-page-header" in detail
    assert _shown(detail, "Por aprobar")
    assert "44px" in detail
