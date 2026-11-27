"""m-25026638, from the second live test of ED-06/ED-07 on 3140 (Clip de nibbles, 594 px
and 1366×900):

1. an AI part with no poster drew «Parte con IA 1» big, in 2–3 lines, over the ▶ — the
   card's name, besides the `.q-ai-mark` capsule. The card says nothing now: the name is
   in the capsule;
2. the chosen AI part's dashed edge and «Parte con IA 1 · 5 s» rode over the sticky
   preview (and under/over the step's head) while scrolling;
3. with the Clip empty, the playhead's line crossed the preview — 2 and 3: the timeline,
   the panel and «Armar mi video por partes» are their own stacking context at z 0, under
   the preview (z 3) and the head (z 5);
6. «Editar» on «Revisa y crea» reached step 1 with the general panel out of view and the
   focus on the step's title: the step's settle ran after the field's focus, and the
   step's own walk back through the history (a `popstate`) closed the panel as if it were
   the owner's «atrás»;
7. a panel brought into view stopped behind the pinned preview: `scroll-margin-top` is
   the head's plus the preview's height (`--q-edit-preview-h`, `assets/edit-room.js`)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from . import clip_editor_vm
from . import editor_idea_vm as vm
from .creative_state import CreativeState
from .ui.steps import step_settle_script

_ROOT = Path(__file__).resolve().parent.parent
_ASSETS = _ROOT / "assets"
_CSS = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")
_PREVIEW_JS = (_ASSETS / "edit-preview.js").read_text(encoding="utf-8")
_CORE = _ASSETS / "edit-sequence-core.js"
_ROOM = _ASSETS / "edit-room.js"
_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _rule(selector: str, css: str = _CSS) -> str:
    """The body of the first rule whose selector is exactly `selector`."""
    match = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def _z(selector: str) -> int:
    found = re.search(r"z-index:\s*(-?\d+);", _rule(selector))
    assert found, selector
    return int(found.group(1))


def _node(script: str) -> object:
    assert _NODE is not None
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


# -- 1. the card of an AI part says nothing: its name is in the capsule ------------------


@_needs_node
def test_an_ai_part_s_card_has_no_name_when_its_mark_is_drawn() -> None:
    script = (
        f"const c = require({json.dumps(str(_CORE))});"
        " const ai = { kind: 'ai', label: 'Parte con IA 1',"
        " mark: 'Parte con IA 1 · se crea al tocar «Crear»' };"
        " console.log(JSON.stringify(["
        " c.cardLabel(ai, true), c.cardLabel(ai, false),"
        " c.cardLabel({ kind: 'video', label: 'Video 2' }, true),"
        " c.cardLabel({ kind: 'ai', label: 'Parte con IA 2', mark: '' }, true),"
        " c.cardLabel(null, true)]));"
    )
    assert _node(script) == ["", "Parte con IA 1", "Video 2", "Parte con IA 2", ""]


def test_the_preview_writes_the_card_through_card_label() -> None:
    show = _PREVIEW_JS[_PREVIEW_JS.index("function seqShow(host, play)") :]
    show = show[: show.index("function seqWait(")]
    assert "var label = c.cardLabel(block, !!aiMark);" in show
    # the mark is looked up before the card, once
    assert show.count('host.querySelector("[data-edit-seq-ai]")') == 1
    assert show.index("var aiMark =") < show.index("c.cardLabel(")


# -- 2 & 3. the timeline, the panel and the parts link under the sticky preview ----------


def test_what_follows_the_preview_is_its_own_context_under_it() -> None:
    rule = _rule(".q-edit > :is(.q-edit__timeline, .q-edit__main, .q-edit__parts)")
    assert "position: relative;" in rule and "z-index: 0;" in rule
    preview = _z(".q-edit__preview")
    assert preview == 3 and preview > 0
    # what climbed over the preview stays inside that context, in its own order
    assert _z('.q-tl__item[data-tl-chosen="true"]') == 3
    assert _z(".q-tl__head") == 4
    assert _z(".q-tl__item--lifted") == 6
    assert _z(".q-tl__insert") == 7
    # the preview stays pinned under the step's head, never over it (z 5)
    assert "top: var(--q-sticky-header-height, 0px);" in _rule(".q-edit__preview")


# -- m-25026636: «Agregar»'s «+» under the pinned preview's empty band ---------------------


def test_the_bar_pins_under_the_preview_and_the_band_still_covers() -> None:
    """Live test (m-25026636): scrolled a little, the bar with «Agregar» slid half under
    the pinned preview — the top of the «+» hidden and untappable. The bar is pinned right
    under the preview while stacked, over what scrolls under it; the preview's band keeps
    taking the taps over what it hides (never `pointer-events: none`)."""
    box = _rule(".q-edit__preview")
    assert "pointer-events" not in box
    assert "background: var(--color-panel-solid);" in box and _z(".q-edit__preview") == 3
    stacked = _CSS[_CSS.index("@container edit-host (max-width: 45.99rem) {") :]
    bar = _rule(".q-edit--timeline > .q-edit__bar", stacked)
    assert "position: sticky;" in bar
    assert "top: calc(var(--q-sticky-header-height, 0px) + var(--q-edit-preview-h, 0px));" in bar
    assert "z-index: 3;" in bar and "background: var(--color-panel-solid);" in bar
    # its own place in the editor's grid, between the tracks and the panel
    assert '"preview" "timeline" "bar" "main" "parts"' in _CSS
    assert ".q-edit--timeline > .q-edit__bar { grid-area: bar; min-width: 0; }" in _CSS
    # a panel brought into view stops under the pinned bar too
    rule = _rule(".q-edit--timeline > .q-edit__main,\n.q-edit--timeline > .q-edit__main *")
    assert "var(--q-edit-bar-h, 0px)" in rule


def test_the_bar_is_the_editor_s_own_child_after_the_timeline() -> None:
    """Pinned inside the timeline it could never leave it (a sticky box stays in its
    parent) nor its z 0: the bar is a sibling of `.q-edit__timeline`, with «Agregar»."""
    import reflex as rx  # noqa: PLC0415

    from . import clip_editor_view  # noqa: PLC0415

    edit = str(clip_editor_view.arma_tu_video(rx.text("MEDIA")).render())
    assert edit.index("q-edit__timeline") < edit.index("q-edit__bar") < edit.index("q-edit__main")
    assert "clip_tl_add_note" in str(clip_editor_view._timeline_bar().render())
    assert "q-tl-stack__actions" not in str(clip_editor_view._timeline_body().render())


_BAR_HARNESS = """
function runBar(scrolled) {
  const preview = el({ height: 300.4, top: 0, bottom: 300 });
  const frame = el({ height: 280, top: 10, bottom: 290 });
  // the timeline ends at 540 in the flow; the bar's box (52 px, its actions 44 px on
  // top) is either in the flow (556) or pinned under the preview (300) while scrolled
  const timeline = el({ height: 224, top: 316 - scrolled, bottom: 540 - scrolled });
  const holderTop = scrolled ? 300 : 556;
  const holder = el({ height: 52, top: holderTop, bottom: holderTop + 52 });
  const bar = el({ height: 44, top: holderTop, bottom: holderTop + 44 });
  const host = el({ width: 594, height: 900 });
  const edit = el({ height: 900 }, {
    closest: () => host, scrollTop: scrolled,
    querySelector: s => ({ ".q-edit__preview": preview,
      ".q-edit__preview .q-edit-preview__frame": frame,
      ".q-tl-stack__actions": bar, ".q-edit__timeline": timeline,
      ".q-edit__bar": holder })[s] || null,
  });
  edit.parentElement = { scrollTop: scrolled, parentElement: null };
  globalThis.window = { innerHeight: 900, scrollY: 0, addEventListener: () => {},
    requestAnimationFrame: f => f() };
  globalThis.getComputedStyle = () => ({ fontSize: "16px", rowGap: "16px" });
  globalThis.document = { documentElement: {}, querySelector: () => null,
    querySelectorAll: s => s === ".q-edit--timeline" ? [edit] : [] };
  eval(SRC);
  return [edit.props["--q-edit-bar-h"] || "", edit.props["--q-edit-frame-h"] || ""];
}
"""


@_needs_node
def test_the_room_script_reads_the_pinned_bar_from_the_flow() -> None:
    """The bar's height goes in `--q-edit-bar-h`, and the frame's height is the same
    whether the page is at its top or scrolled with the bar pinned (its flow position is
    read from the timeline above it, never from where it is stuck)."""
    src = _ROOM.read_text(encoding="utf-8")
    script = (
        f"const SRC = {json.dumps(src)};\n{_ROOM_HARNESS}\n{_BAR_HARNESS}\n"
        "console.log(JSON.stringify([runBar(0), runBar(250)]));"
    )
    at_top, scrolled = _node(script)
    assert at_top[0] == "52px" and at_top == scrolled
    # the frame (280) grows by what is left from the actions' flow bottom (540 + 16 + 44)
    # to the window less 8 px (892): 280 + 292
    assert at_top[1] == "572px"


# -- 7. a panel or a field scrolled into view stops under the pinned preview --------------


def test_a_panel_scrolled_into_view_stops_under_the_preview() -> None:
    rule = _rule(".q-edit--timeline > .q-edit__main,\n.q-edit--timeline > .q-edit__main *")
    assert "scroll-margin-top: calc(" in rule
    assert "var(--q-sticky-header-height, 0px)" in rule
    assert "var(--q-edit-preview-h, 0px)" in rule


_ROOM_HARNESS = """
function el(rect, extra) {
  const props = {};
  return Object.assign({
    isConnected: true, parentElement: null, scrollTop: 0,
    getBoundingClientRect: () => rect,
    closest: () => null, querySelector: () => null,
    style: { getPropertyValue: k => props[k] || "", setProperty: (k, v) => { props[k] = v; },
             removeProperty: k => { delete props[k]; } },
    props: props,
  }, extra || {});
}
function run(width) {
  const preview = el({ height: 300.4, top: 0, bottom: 300 });
  const frame = el({ height: 280, top: 10, bottom: 290 });
  const bar = el({ height: 44, top: 600, bottom: 644 });
  const host = el({ width: width, height: 900 });
  const edit = el({ height: 900 }, {
    closest: () => host,
    querySelector: s => ({ ".q-edit__preview": preview,
      ".q-edit__preview .q-edit-preview__frame": frame,
      ".q-tl-stack__actions": bar, ".q-edit__timeline": null })[s] || null,
  });
  globalThis.window = { innerHeight: 900, scrollY: 0, addEventListener: () => {},
    requestAnimationFrame: f => f() };
  globalThis.getComputedStyle = () => ({ fontSize: "16px" });
  globalThis.document = { documentElement: {}, querySelector: () => null,
    querySelectorAll: s => s === ".q-edit--timeline" ? [edit] : [] };
  eval(SRC);
  return edit.props["--q-edit-preview-h"] || "";
}
"""


@_needs_node
def test_the_room_script_measures_the_sticky_preview_only_while_stacked() -> None:
    src = _ROOM.read_text(encoding="utf-8")
    script = (
        f"const SRC = {json.dumps(src)};\n{_ROOM_HARNESS}\n"
        "console.log(JSON.stringify([run(594), run(1366)]));"
    )
    # 594 px: stacked, the preview is sticky — its height (rounded up); 1366: none
    assert _node(script) == ["301px", ""]


# -- 6. «Editar» from «Revisa y crea»: the panel open and the focus on its field ----------


@pytest.fixture
def clip(monkeypatch: pytest.MonkeyPatch) -> CreativeState:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)
    state = CreativeState()
    state.choose_category("clip")
    return state


def _js(events: object) -> list[str]:
    """The JavaScript of each `rx.call_script` an event handler returned, in order."""
    items = events if isinstance(events, list) else [events]
    return [e.args[0][1]._var_value for e in items if e is not None]  # type: ignore[union-attr]


def test_editar_s_own_walk_back_never_closes_the_panel(clip: CreativeState) -> None:
    """The real order: the step bar to «Revisa y crea» straight from step 1 (its entry
    remembers step 1, so «Editar»'s `go_to_step(back=True)` is a `history.back()`), then
    «Editar» on «De qué trata tu video» and «Datos clave»: the `popstate` comes back as
    `reconcile_reel_editor_route("?paso=1")` — the panel stays open."""
    for view in ("topic", "rules"):
        clip.go_to_view("2")
        assert clip.gen_step_key == "review"
        events = clip.edit_view(view)
        assert clip.gen_step_key == "show" and clip.clip_general_open
        assert not clip._clip_general_addressed  # «Editar» pushes no address of its own
        # the step's address first, the field's focus last
        said = _js(events)
        assert "__qStepGo" in said[0] and "history.back" in said[0]
        assert "getElementById" in said[-1]
        CreativeState.reconcile_reel_editor_route.fn(clip, "?paso=1")
        assert clip.clip_general_open, view
        assert clip.gen_step_key == "show"


def test_the_owner_s_atras_still_closes_it(clip: CreativeState) -> None:
    # opened with its own address on step 1: «atrás» closes it, as before
    CreativeState.edit_clip_general.fn(clip)
    CreativeState.reconcile_reel_editor_route.fn(clip, "?paso=1")
    assert not clip.clip_general_open
    # opened by «Editar», then «atrás» to another step: it closes too
    clip.go_to_view("2")
    clip.edit_view("topic")
    assert clip.clip_general_open
    CreativeState.reconcile_reel_editor_route.fn(clip, "?paso=3")
    assert not clip.clip_general_open
    # a reload (or «adelante») on its address: it is the panel's, «atrás» closes it
    CreativeState.reconcile_reel_editor_route.fn(clip, f"?paso=1&bloque={vm.GENERAL_SLUG}")
    assert clip.clip_general_open and clip._clip_general_addressed
    CreativeState.reconcile_reel_editor_route.fn(clip, "?paso=1")
    assert not clip.clip_general_open


_FOCUS_HARNESS = """
const frames = [];
const log = [];
function node(id, extra) {
  return Object.assign({ id: id, disabled: false,
    matches: s => (extra && extra.selector === s),
    focus() { document.activeElement = this; log.push("focus:" + id); },
    scrollIntoView() { log.push("scroll:" + id); } }, extra || {});
}
const title = node("title", { selector: "main.q-panel .q-step-title" });
title.matches = s => s === ".q-step-title" || s === "main.q-panel .q-step-title";
const field = node("q-context-field");
const other = node("other");
let fieldShown = false;
globalThis.document = {
  body: { id: "body" }, activeElement: null,
  getElementById: i => (fieldShown && i === "q-context-field" ? field : null),
  querySelector: s => s === "main.q-panel" ? { scrollTo() { log.push("top"); } }
    : (s === "main.q-panel .q-step-title" ? title : null),
};
document.activeElement = document.body;
const entries = [{ url: "/create?paso=1", state: null }, { url: "/create?paso=3",
  state: { qPrevPaso: "1" } }];
let at = 1;
globalThis.window = {
  location: { href: "https://q.test/create?paso=3" },
  history: { get state() { return entries[at].state; },
    back() { at -= 1; window.location.href = "https://q.test" + entries[at].url; },
    pushState() { throw new Error("push"); }, replaceState() {} },
  addEventListener: () => {}, setTimeout: () => {},
  requestAnimationFrame: f => frames.push(f),
};
function tick(n) {
  for (let i = 0; i < n; i++) { const now = frames.splice(0); now.forEach(f => f()); }
}
"""


def _focus_run(body: str, scripts: list[str]) -> object:
    script = (
        f"{_FOCUS_HARNESS}\nconst SCRIPTS = {json.dumps(scripts)};\n{body}\n"
        "console.log(JSON.stringify({ active: document.activeElement.id, log: log,"
        " url: window.location.href }));"
    )
    return _node(script)


@_needs_node
def test_editar_s_focus_lands_on_the_field_after_the_step_settles(clip: CreativeState) -> None:
    """The real order in the page: «Editar»'s scripts (the step's address and settle,
    then the field's focus), the panel drawn a frame later, and `step_sync`'s own settle
    a few frames after that — each settle focuses the title; the field ends with it."""
    clip.go_to_view("2")
    scripts = _js(clip.edit_view("topic"))
    got = _focus_run(
        "SCRIPTS.forEach(s => eval(s));"  # the events, in their order
        " tick(1); fieldShown = true;"  # React draws step 1 with the panel open
        f" tick(1); eval({json.dumps(step_settle_script())});"  # `step_sync`'s settle
        " tick(10);",
        scripts,
    )
    assert isinstance(got, dict)
    assert got["active"] == "q-context-field"
    assert got["url"].endswith("/create?paso=1")
    log = got["log"]
    # the title took it (each settle) and the field took it back, scrolled into view
    assert "focus:title" in log
    last_title = max(i for i, e in enumerate(log) if e == "focus:title")
    assert "focus:q-context-field" in log[last_title:]
    assert "scroll:q-context-field" in log[last_title:]


@_needs_node
def test_the_field_never_takes_the_focus_back_from_what_the_owner_touched() -> None:
    got = _focus_run(
        "fieldShown = true; eval(SCRIPTS[0]); tick(1); other.focus(); tick(5);",
        [vm.focus_script(vm.TOPIC_FIELD_ID)],
    )
    assert isinstance(got, dict)
    assert got["log"] == ["focus:q-context-field", "scroll:q-context-field", "focus:other"]
    assert got["active"] == "other"


@_needs_node
def test_the_body_counts_as_lost_only_right_after_the_field_or_the_title() -> None:
    """Review (Safari): a tap on a button may leave the body focused — the owner's,
    never taken back; the body right after the field (or the title) had it is."""
    got = _focus_run(
        "fieldShown = true; eval(SCRIPTS[0]); tick(1); other.focus(); tick(1);"
        " document.activeElement = document.body; tick(5);",
        [vm.focus_script(vm.TOPIC_FIELD_ID)],
    )
    assert isinstance(got, dict) and got["active"] == "body"
    assert got["log"].count("focus:q-context-field") == 1
    got = _focus_run(
        "fieldShown = true; eval(SCRIPTS[0]); tick(1);"
        " document.activeElement = document.body; tick(2);",
        [vm.focus_script(vm.TOPIC_FIELD_ID)],
    )
    assert isinstance(got, dict) and got["active"] == "q-context-field"
    assert got["log"].count("focus:q-context-field") == 2


@_needs_node
def test_a_settle_s_title_focus_within_the_window_comes_back() -> None:
    got = _focus_run(
        "fieldShown = true; eval(SCRIPTS[0]); tick(3); title.focus(); tick(2);",
        [vm.focus_script(vm.TOPIC_FIELD_ID)],
    )
    assert isinstance(got, dict) and got["active"] == "q-context-field"


_ARRIVAL_HARNESS = """
// a browser history: the page the owner came from, then the general panel's address
// as a link (or a new tab) opened it — its `qBloque` is NOT this document's mark
const entries = [{ url: "/outside", state: null },
  { url: "/create?paso=1&bloque=de-que-trata", state: { qBloque: "dOTHER" } }];
let at = 1; let left = false;
const w = { location: { href: "https://q.test" + entries[1].url } };
function show() { w.location.href = "https://q.test" + entries[at].url; }
w.history = {
  get state() { return entries[at].state; },
  back() { if (at > 0) { at -= 1; show(); if (at === 0) left = true; } },
  pushState(s, _t, u) { entries.splice(at + 1); entries.push({ url: String(u), state: s });
    at += 1; show(); },
  replaceState(s, _t, u) { const url = String(u).replace("https://q.test", "");
    entries[at] = { url: url, state: s }; show(); },
};
w.addEventListener = () => {}; w.setTimeout = () => {}; w.requestAnimationFrame = () => {};
globalThis.window = w;
globalThis.document = { querySelector: () => null, getElementById: () => null };
"""


@_needs_node
def test_a_panel_reached_by_its_address_never_leaves_the_document(clip: CreativeState) -> None:
    """Review: the general panel opened by its address (a link, a new tab: an entry this
    page load did not push), then «Siguiente», then «Atrás» — step 1, in this document."""
    CreativeState.reconcile_reel_editor_route.fn(clip, f"?paso=1&bloque={vm.GENERAL_SLUG}")
    assert clip.clip_general_open and clip._clip_general_addressed
    forward = _js(clip.next_view())
    assert not clip.clip_general_open
    back = _js(clip.prev_view())
    assert clip.gen_step_key == "show"
    script = (
        f"{_ARRIVAL_HARNESS}\nconst after = [];"
        f" for (const s of {json.dumps(forward)}) eval(s);"
        " after.push(entries.map(e => e.url), at);"
        f" for (const s of {json.dumps(back)}) eval(s);"
        " console.log(JSON.stringify({ after: after, urls: entries.map(e => e.url),"
        " at: at, left: left, here: w.location.href }));"
    )
    got = _node(script)
    assert isinstance(got, dict)
    # «Siguiente»: the arrival entry lost its word and stays step 1's; step 2 is pushed
    assert got["after"] == [["/outside", "/create?paso=1", "/create?paso=2"], 2]
    # «Atrás»: back to step 1, never out of the document
    assert not got["left"] and got["at"] == 1
    assert got["here"] == "https://q.test/create?paso=1"


@_needs_node
def test_after_its_window_the_field_lets_the_focus_go() -> None:
    got = _focus_run(
        f"fieldShown = true; eval(SCRIPTS[0]); tick({vm.FOCUS_HOLD_FRAMES + 2});"
        " title.focus(); tick(5);",
        [vm.focus_script(vm.TOPIC_FIELD_ID)],
    )
    assert isinstance(got, dict) and got["active"] == "title"
