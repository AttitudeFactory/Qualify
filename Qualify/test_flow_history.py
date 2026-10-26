"""Execute the browser's flow history protocol, including Radix portals, offline."""

from __future__ import annotations

import json

import pytest

from .nav_url import close_flow_script
from .test_route_history import _node
from .ui.flow_history import _FLOW_SCRIPT

_HARNESS = r"""
let observer;
class MutationObserver {constructor(callback){observer=callback;} observe(){}}
const entries=[{href:'/catalog?volver=%2Fcreate', state:{key:'router', idx:2}}];
let pos=0, page=null, drawer=null;
const routeNode={dataset:{historyLease:'1',historyAck:'1'},
 matches:selector=>selector==='.q-route-pop'};
const window={requestAnimationFrame(fn){fn();}, addEventListener(){}};
function apply(){
 const url=new URL(entries[pos].href, 'https://qualify.test');
 window.location={href:url.href, pathname:url.pathname, search:url.search, hash:url.hash};
}
window.history={get state(){return entries[pos].state;},
 pushState(state, _, href){entries.splice(pos+1);entries.push({state,href});pos++;apply();},
 replaceState(state, _, href){entries[pos]={state,href};apply();},
 back(){pos--;apply();}, go(delta){pos+=delta;apply();}
};
window.__qFlowRouteNode=routeNode;
const document={querySelector(selector){
 if(selector === 'main.q-panel .q-route-pop') return routeNode;
 if(selector === '.q-drawer[data-state="open"] .q-flow-sync') return drawer;
 if(selector === 'main.q-panel .q-flow-sync') return page;
 throw Error('Unexpected selector: '+selector);
}};
apply();
"""


def test_portal_form_steps_back_and_close_restore_the_place_that_opened_it() -> None:
    script = (
        _HARNESS
        + f"""
const sync={json.dumps(_FLOW_SCRIPT)};
drawer={{dataset:{{flow:'producto',step:'1'}}}};
eval(sync);
const first={{pos,href:entries[pos].href,depth:window.history.state.qFlowDepth}};
eval(sync); const repeated=pos;
drawer.dataset.step='2'; eval(sync);
const second={{pos,depth:window.history.state.qFlowDepth}};
drawer.dataset.step='1'; eval(sync); const back=pos;
drawer.dataset.step='2'; eval(sync);
{close_flow_script("producto")}
console.log(JSON.stringify({{first,repeated,second,back,pos,href:entries[pos].href}}));
"""
    )
    result = _node(script)
    assert result["first"] == {
        "pos": 1,
        "href": "/catalog?volver=%2Fcreate&flujo=producto&paso=1",
        "depth": 1,
    }
    assert result["repeated"] == 1
    assert result["second"] == {"pos": 2, "depth": 2}
    assert result["back"] == 1
    assert result["pos"] == 0
    assert result["href"] == "/catalog?volver=%2Fcreate"


def test_open_portal_takes_priority_over_a_page_marker_and_rejects_non_uuid_ids() -> None:
    script = (
        _HARNESS
        + f"""
entries[0].href='/whatsapp?tab=chats';apply();
page={{dataset:{{flow:'menu',step:'3'}}}};
drawer={{dataset:{{flow:'mensaje-chat',step:'1',objeto:'not-a-uuid'}}}};
{_FLOW_SCRIPT}
console.log(JSON.stringify({{href:entries[pos].href,root:window.history.state.qFlowRoot}}));
"""
    )
    result = _node(script)
    assert "flujo=mensaje-chat&paso=1" in result["href"]
    assert "objeto=" not in result["href"]
    assert "menu" not in result["href"]
    assert result["root"] == "/whatsapp?tab=chats"


def test_guarded_direct_link_replaces_the_invalid_step_without_stacking_history() -> None:
    script = (
        _HARNESS
        + f"""
entries[0].href='/catalog?flujo=producto&paso=3'; apply();
drawer={{dataset:{{flow:'producto',step:'2'}}}};
{_FLOW_SCRIPT}
const guarded=entries[pos].href;
{close_flow_script("producto")}
console.log(JSON.stringify({{guarded,pos,href:entries[pos].href,length:entries.length}}));
"""
    )
    assert _node(script) == {
        "guarded": "/catalog?flujo=producto&paso=2",
        "pos": 0,
        "href": "/catalog",
        "length": 1,
    }


def test_marker_attribute_changes_resync_without_mounting_the_effect_again() -> None:
    script = (
        _HARNESS
        + f"""
drawer={{dataset:{{flow:'producto',step:'1'}}, matches: selector => selector === '.q-flow-sync'}};
{_FLOW_SCRIPT}
const first=entries[pos].href;
drawer.dataset.step='2';
observer([{{type:'attributes', attributeName:'data-step', target:drawer}}]);
const second=entries[pos].href;
drawer.dataset.step='1';
observer([{{type:'attributes', attributeName:'data-step', target:drawer}}]);
console.log(JSON.stringify({{first,second,pos,href:entries[pos].href}}));
"""
    )
    result = _node(script)
    assert result["first"].endswith("paso=1")
    assert result["second"].endswith("paso=2")
    assert result["pos"] == 1 and result["href"].endswith("paso=1")


def test_switching_query_identity_cannot_consume_a_previous_querys_step() -> None:
    a = "a0000000-0000-4000-8000-000000000001"
    b = "b0000000-0000-4000-8000-000000000001"
    script = (
        _HARNESS
        + f"""
entries[0].href='/responder?tab=compran';apply();
drawer={{dataset:{{flow:'consulta',step:'2',consulta:{json.dumps(a)}}},
 matches: selector => selector === '.q-flow-sync'}};
{_FLOW_SCRIPT}
drawer.dataset.step='3'; observer([{{type:'attributes', target:drawer}}]);
drawer.dataset.consulta={json.dumps(b)}; drawer.dataset.step='2';
observer([{{type:'attributes', target:drawer}}]);
console.log(JSON.stringify({{pos,href:entries[pos].href,depth:window.history.state.qFlowDepth}}));
"""
    )
    result = _node(script)
    assert result["pos"] == 3
    assert result["depth"] == 1
    assert "consulta=" + b in result["href"]


def test_page_step_marker_lifecycle_preserves_cold_deep_link_then_updates_on_attributes() -> None:
    from .ui.steps import _STEP_SYNC_DOM_JS

    script = (
        _HARNESS
        + f"""
entries[0].href='/brand?paso=4'; apply();
window.addEventListener=()=>{{}}; window.setTimeout=fn=>fn();
let mark={{dataset:{{step:'1',direction:'next'}},nodeType:1,
 matches:s=>s==='.q-step-sync',querySelector:()=>null}};
document.querySelector=selector=>selector==='main.q-panel .q-step-sync' ? mark : null;
{_STEP_SYNC_DOM_JS}
const cold=entries[pos].href;
const previous=mark; mark=null;
observer([{{type:'childList',addedNodes:[],removedNodes:[previous]}}]);
mark={{...previous,dataset:{{step:'4',direction:'next'}}}};
observer([{{type:'childList',addedNodes:[mark],removedNodes:[]}}]);
mark.dataset.step='5'; observer([{{type:'attributes',target:mark}}]);
const next=entries[pos].href;
window.history.back();
observer([{{type:'attributes',target:{{matches:()=>false}}}}]);
const waiting=entries[pos].href;
mark.dataset.step='4';mark.dataset.direction='back';
observer([{{type:'attributes',target:mark}}]);
console.log(JSON.stringify({{cold,next,waiting,final:entries[pos].href,pos}}));
"""
    )
    assert _node(script) == {
        "cold": "/brand?paso=4",
        "next": "/brand?paso=5",
        "waiting": "/brand?paso=4",
        "final": "/brand?paso=4",
        "pos": 0,
    }


def test_installing_on_a_cold_document_never_writes_inherited_markup_but_user_open_does() -> None:
    from .ui.flow_history import _FLOW_INSTALL_SCRIPT

    script = (
        _HARNESS
        + f"""
drawer={{dataset:{{flow:'producto',step:'2'}},nodeType:1,
 matches:s=>s==='.q-flow-sync', querySelector:()=>null}};
{_FLOW_INSTALL_SCRIPT}
const cold=entries[pos].href;
const old=drawer;drawer=null;
observer([{{type:'childList',addedNodes:[],removedNodes:[old]}}]);
const clean=entries[pos].href;
drawer={{...old,dataset:{{flow:'producto',step:'1'}}}};
observer([{{type:'childList',addedNodes:[drawer],removedNodes:[]}}]);
console.log(JSON.stringify({{cold,clean,opened:entries[pos].href,pos}}));
"""
    )
    result = _node(script)
    assert result["cold"] == result["clean"] == "/catalog?volver=%2Fcreate"
    assert result["opened"].endswith("flujo=producto&paso=1")
    assert result["pos"] == 1


def test_a_stale_menu_marker_cannot_write_into_another_whatsapp_tab() -> None:
    script = (
        _HARNESS
        + f"""
entries[0].href='/whatsapp?tab=plantillas';apply();
page={{dataset:{{flow:'menu',step:'2'}}}};
{_FLOW_SCRIPT}
console.log(JSON.stringify({{href:entries[pos].href,pos}}));
"""
    )
    assert _node(script) == {"href": "/whatsapp?tab=plantillas", "pos": 0}


def test_handler_and_marker_cannot_go_back_twice_before_the_pop_arrives() -> None:
    from .ui.steps import step_address_script

    back = step_address_script(json.dumps("/create?paso=3"), back=True)
    script = (
        """
let calls=0, onPop;
const window={location:{href:'https://qualify.test/create?paso=4',
 pathname:'/create',search:'?paso=4',hash:''},
 addEventListener(type, fn){onPop=fn;},
 history:{state:{qPrevPaso:'3'},back(){calls++;}}
};
"""
        + back
        + back
        + "console.log(JSON.stringify({calls}));"
    )
    assert _node(script) == {"calls": 1}


def test_late_inherited_portal_waits_for_this_visits_backend_ack() -> None:
    from .ui.flow_history import _FLOW_INSTALL_SCRIPT
    from .ui.route_history import route_history_ready

    ack = str(
        route_history_ready("/catalog", {"visit": "2", "href": "https://qualify.test/catalog"})
        .args[0][1]
        ._js_expr
    )
    # EventSpec wraps the script as a literal string; decode it before executing.
    ack = json.loads(ack)
    script = (
        _HARNESS
        + f"""
entries[0].href='/catalog';apply();
routeNode.dataset.historyLease='2';window.__qFlowRouteNode=null;
{_FLOW_INSTALL_SCRIPT}
drawer={{dataset:{{flow:'producto',step:'2'}},nodeType:1,
 matches:s=>s==='.q-flow-sync',querySelector:()=>null}};
observer([{{type:'childList',addedNodes:[drawer],removedNodes:[]}}]);
const inherited=entries[pos].href;
const old=drawer;drawer=null;
observer([{{type:'childList',addedNodes:[],removedNodes:[old]}}]);
routeNode.dataset.historyAck='2';
{ack}
drawer={{...old,dataset:{{flow:'producto',step:'1'}}}};
observer([{{type:'childList',addedNodes:[drawer],removedNodes:[]}}]);
drawer.dataset.step='2';observer([{{type:'attributes',target:drawer}}]);
console.log(JSON.stringify({{inherited,final:entries[pos].href,pos}}));
"""
    )
    result = _node(script)
    assert result["inherited"] == "/catalog"
    assert result["final"] == "/catalog?flujo=producto&paso=2"
    assert result["pos"] == 2


def test_only_the_ack_for_the_current_visit_and_address_can_arm_history_writes() -> None:
    from .ui.route_history import route_history_ready

    def script(visit, href):
        spec = route_history_ready("/catalog", {"visit": visit, "href": href})
        return json.loads(str(spec.args[0][1]._js_expr))

    old = script("old-document:1", "https://qualify.test/catalog")
    departed = script("new-document:2", "https://qualify.test/catalog?flujo=producto&paso=2")
    valid = script("new-document:2", "https://qualify.test/catalog")
    program = (
        _HARNESS
        + f"""
entries[0].href='/catalog';apply();
routeNode.dataset.historyLease='new-document:2';window.__qFlowRouteNode=null;
{old}
const oldArmed=window.__qFlowRouteNode===routeNode;
{departed}
const departedArmed=window.__qFlowRouteNode===routeNode;
{valid}
console.log(JSON.stringify({{oldArmed,departedArmed,validArmed:window.__qFlowRouteNode===routeNode}}));
"""
    )
    assert _node(program) == {"oldArmed": False, "departedArmed": False, "validArmed": True}


@pytest.mark.parametrize("ack_first", [True, False])
def test_backend_ack_cannot_sync_the_old_portal_before_react_paints_its_delta(ack_first) -> None:
    from .ui.flow_history import _FLOW_INSTALL_SCRIPT
    from .ui.route_history import route_history_ready

    spec = route_history_ready("/catalog", {"visit": "2", "href": "https://qualify.test/catalog"})
    ack = json.loads(str(spec.args[0][1]._js_expr))
    render = """
const old=drawer;drawer=null;
routeNode.dataset.historyAck='2';
observer([{type:'attributes',attributeName:'data-history-ack',target:routeNode},
 {type:'childList',addedNodes:[],removedNodes:[old]}]);
"""
    order = (
        ack + "const beforePaint=entries[pos].href;" + render
        if ack_first
        else (render + "const beforePaint=entries[pos].href;" + ack)
    )
    script = (
        _HARNESS
        + f"""
entries[0].href='/catalog';apply();
routeNode.dataset.historyLease='2';window.__qFlowRouteNode=null;
{_FLOW_INSTALL_SCRIPT}
drawer={{dataset:{{flow:'producto',step:'2'}},nodeType:1,
 matches:s=>s==='.q-flow-sync',querySelector:()=>null}};
observer([{{type:'childList',addedNodes:[drawer],removedNodes:[]}}]);
{order}
const afterPaint=entries[pos].href;
drawer={{dataset:{{flow:'producto',step:'1'}},nodeType:1,
 matches:s=>s==='.q-flow-sync',querySelector:()=>null}};
observer([{{type:'childList',addedNodes:[drawer],removedNodes:[]}}]);
drawer.dataset.step='2';observer([{{type:'attributes',target:drawer}}]);
console.log(JSON.stringify({{beforePaint,afterPaint,final:entries[pos].href,pos}}));
"""
    )
    assert _node(script) == {
        "beforePaint": "/catalog",
        "afterPaint": "/catalog",
        "final": "/catalog?flujo=producto&paso=2",
        "pos": 2,
    }


@pytest.mark.parametrize(
    ("path", "requested", "guarded"), [("/brand/manual", 6, 2), ("/brand/connect", 7, 1)]
)
def test_ready_epoch_canonicalizes_a_guarded_entry_even_when_the_step_did_not_change(
    path, requested, guarded
) -> None:
    from .ui.steps import _STEP_SYNC_DOM_JS

    script = (
        _HARNESS
        + f"""
entries[0].href={json.dumps(path + "?paso=" + str(requested))};apply();
window.addEventListener=()=>{{}}; window.setTimeout=fn=>fn();
let mark={{dataset:{{step:{json.dumps(str(guarded))},direction:'next',entry:'0'}},nodeType:1,
 matches:s=>s==='.q-step-sync',querySelector:()=>null}};
document.querySelector=selector=>selector==='main.q-panel .q-step-sync' ? mark : null;
{_STEP_SYNC_DOM_JS}
const waiting=entries[pos].href;
mark.dataset.entry='1';observer([{{type:'attributes',attributeName:'data-entry',target:mark}}]);
console.log(JSON.stringify({{waiting,final:entries[pos].href,pos}}));
"""
    )
    assert _node(script) == {
        "waiting": path + "?paso=" + str(requested),
        "final": path + "?paso=" + str(guarded),
        "pos": 0,
    }


@pytest.mark.parametrize("paint_first", [False, True])
def test_explicit_entry_ack_canonicalizes_only_matching_painted_epoch(paint_first) -> None:
    from .ui.steps import _STEP_SYNC_DOM_JS, step_entry_script

    ack = step_entry_script("/brand/manual", 2, 4, "6")
    script = (
        _HARNESS
        + f"""
entries[0].href='/brand/manual?paso=6';apply();
window.addEventListener=()=>{{}};window.setTimeout=fn=>fn();
let mark={{dataset:{{step:'1',entry:'3',direction:'next'}},nodeType:1,
 matches:s=>s==='.q-step-sync',querySelector:()=>null}};
document.querySelector=s=>s==='main.q-panel .q-step-sync'?mark:null;
{_STEP_SYNC_DOM_JS}
const paint=()=>{{mark.dataset.step='2';mark.dataset.entry='4';
 observer([{{type:'attributes',target:mark}}]);}};
if ({str(paint_first).lower()}) paint();
{ack}
if (!{str(paint_first).lower()}) paint();
console.log(JSON.stringify({{href:entries[pos].href,pos}}));
"""
    )
    assert _node(script) == {"href": "/brand/manual?paso=2", "pos": 0}


@pytest.mark.parametrize("first,second", [("/create/", "/create"), ("/create", "/create/")])
def test_page_step_two_writers_with_slash_difference_make_one_entry(first, second) -> None:
    from .ui.steps import step_address_script

    script = (
        _HARNESS
        + """
entries[0].href='/create/?paso=1';apply();
"""
        + step_address_script(json.dumps(first + "?paso=2"))
        + step_address_script(json.dumps(second + "?paso=2"))
        + step_address_script("'/create?paso=3'")
        + step_address_script("'/create?paso=2'", back=True)
        + """
const count=entries.length;
window.history.back();
console.log(JSON.stringify({count,href:entries[pos].href}));
"""
    )
    assert _node(script) == {"count": 3, "href": "/create/?paso=1"}


def test_entry_ack_finishes_first_marker_already_at_guarded_step_without_another_mutation() -> None:
    from .ui.steps import _STEP_SYNC_DOM_JS, step_entry_script

    script = (
        _HARNESS
        + """
entries[0].href='/brand/connect?paso=7';apply();
window.addEventListener=()=>{};window.setTimeout=fn=>fn();
const mark={dataset:{step:'1',entry:'4',direction:'next'},nodeType:1,
 matches:s=>s==='.q-step-sync',querySelector:()=>null};
document.querySelector=s=>s==='main.q-panel .q-step-sync'?mark:null;
"""
        + _STEP_SYNC_DOM_JS
        + step_entry_script("/brand/connect", 1, 4, "7")
        + "console.log(JSON.stringify({href:entries[pos].href,pos}));"
    )
    assert _node(script) == {"href": "/brand/connect?paso=1", "pos": 0}
