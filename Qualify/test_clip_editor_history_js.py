"""ED-04 (m-25026627, Deivid 2026-11-20: «a veces hay un recargo de la página cuando
deselecciono algo»): letting a block go walks the browser history back only through an
entry THIS page load pushed (`clip_editor_vm.block_url_script`). After a reload the
browser keeps the entry the editor had pushed (its state says `qBloque`), and walking
back from it left the reloaded page — a whole new page load. Run by `node` against a
stand-in `window.history`; skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from . import clip_editor_vm as vm
from .creative_state import CreativeState

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")

_CHOOSE = vm.block_url_script(vm.BLOCK_PARAM, "video-2", flow=False)
_FLOW = vm.block_url_script(vm.BLOCK_PARAM, "", flow=True)
_LET_GO = vm.block_url_script(vm.BLOCK_PARAM, "", flow=False)

_HARNESS = """
function page(state, path) {
  const calls = [];
  const w = { location: { href: "https://q.test" + path } };
  w.history = {
    state: state,
    back() { calls.push(["back"]); },
    pushState(s, _t, u) { calls.push(["push", u, s]); w.history.state = s;
      w.location.href = "https://q.test" + u; },
    replaceState(s, _t, u) { calls.push(["replace", u, s]); w.history.state = s;
      w.location.href = "https://q.test" + u; },
  };
  return { w: w, calls: calls };
}
function run(p, code) { globalThis.window = p.w; eval(code); return p.calls; }
"""


def _run(body: str) -> object:
    script = (
        f"const CHOOSE = {json.dumps(_CHOOSE)}; const FLOW = {json.dumps(_FLOW)};"
        f" const LET_GO = {json.dumps(_LET_GO)};\n{_HARNESS}\n"
        f"console.log(JSON.stringify((() => {{ {body} }})()));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_choose_then_let_go_walks_back_through_its_own_entry() -> None:
    got = _run(
        "const p = page({ idx: 3 }, '/create?paso=1');"
        " run(p, CHOOSE); run(p, LET_GO);"
        " return p.calls.map(c => [c[0], c[1] || '', !!(c[2] && c[2].qBloque)]);"
    )
    assert got == [["push", "/create?paso=1&bloque=video-2", True], ["back", "", False]]


def test_after_a_reload_letting_go_never_leaves_the_page() -> None:
    """The entry the editor pushed before the reload still says `qBloque`: not this page
    load's, so no `history.back()` — the word goes with a `replaceState`."""
    got = _run(
        "const p = page({ idx: 3, qBloque: 'dANTES' }, '/create?paso=1&bloque=video-2');"
        " run(p, LET_GO);"
        " return p.calls.map(c => [c[0], c[1] || '', c[2] ? ('qBloque' in c[2]) : null]);"
    )
    assert got == [["replace", "/create?paso=1", False]]


def test_after_a_reload_choosing_another_block_replaces_the_word() -> None:
    got = _run(
        "const p = page({ idx: 3, qBloque: 'dANTES' }, '/create?paso=1&bloque=foto-1');"
        " run(p, CHOOSE);"
        " return p.calls.map(c => [c[0], c[1]]);"
    )
    assert got == [["replace", "/create?paso=1&bloque=video-2"]]


def test_a_flow_opened_and_closed_walks_back_through_its_own_entry() -> None:
    got = _run(
        "const p = page(null, '/create?paso=1');"
        " run(p, FLOW); run(p, LET_GO); return p.calls.map(c => c[0]);"
    )
    assert got == ["push", "back"]


def test_nothing_chosen_nothing_to_undo() -> None:
    assert _run("const p = page({ idx: 1 }, '/create?paso=1'); return run(p, LET_GO);") == []


def test_the_screen_sends_that_script() -> None:
    state = CreativeState()
    assert "__qBloqueDoc" in str(state._clip_block_url(""))


# -- ED-06 (m-25026636): the general panel's own entry and the steps -----------------------

_STACK = """
function stack(path) {
  // a browser history: entries and the one in front; back() moves to the one before
  const entries = [{ url: path, state: null }]; let at = 0;
  const w = { location: { href: "https://q.test" + path } };
  function show() { w.history.state = entries[at].state;
    w.location.href = "https://q.test" + entries[at].url; }
  w.history = {
    state: null,
    back() { if (at > 0) { at -= 1; show(); } },
    pushState(s, _t, u) { entries.splice(at + 1); entries.push({ url: u, state: s });
      at += 1; show(); },
    replaceState(s, _t, u) { entries[at] = { url: u, state: s }; show(); },
  };
  w.addEventListener = () => {}; w.setTimeout = () => {}; w.requestAnimationFrame = () => {};
  globalThis.document = { querySelector: () => null, getElementById: () => null };
  return { w: w, urls: () => entries.map(e => e.url), at: () => at };
}
function play(h, scripts) { globalThis.window = h.w; for (const s of scripts) eval(s); }
"""


def _js(events: object) -> list[str]:
    """The JavaScript of each `rx.call_script` an event handler returned, in order."""
    items = events if isinstance(events, list) else [events]
    return [e.args[0][1]._var_value for e in items if e is not None]  # type: ignore[union-attr]


def _history(steps: list[list[str]]) -> dict[str, object]:
    script = (
        f"{_STACK}\nconst h = stack('/create?paso=1');"
        f" for (const s of {json.dumps(steps)}) play(h, s);"
        " console.log(JSON.stringify({ urls: h.urls(), at: h.at() }));"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def _editor(monkeypatch: pytest.MonkeyPatch) -> CreativeState:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", True)
    state = CreativeState()
    state.choose_category("clip")
    return state


@pytest.mark.parametrize("move", ["next_view", "go_to_view"])
def test_the_general_panels_entry_becomes_the_next_steps(
    monkeypatch: pytest.MonkeyPatch, move: str
) -> None:
    """Last review: the panel opened with its own address, then «Siguiente» (or the step
    bar), then «Atrás»: back on step 1 — no duplicate step and no dead entry."""
    state = _editor(monkeypatch)
    opened = _js(CreativeState.edit_clip_general.fn(state))
    forward = _js(state.next_view() if move == "next_view" else state.go_to_view("1"))
    assert state.gen_step_key == "how" and not state.clip_general_open
    back = _js(state.prev_view())
    assert state.gen_step_key == "show"
    assert _history([opened, forward]) == {"urls": ["/create?paso=1", "/create?paso=2"], "at": 1}
    got = _history([opened, forward, back])
    assert got == {"urls": ["/create?paso=1", "/create?paso=2"], "at": 0}


def test_atras_on_step_1_with_the_panel_open_walks_its_entry_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`prev_view` on step 1 changes no step: the panel's entry is walked back."""
    state = _editor(monkeypatch)
    opened = _js(CreativeState.edit_clip_general.fn(state))
    back = _js(state.prev_view())
    assert state.gen_step_key == "show" and not state.clip_general_open
    got = _history([opened, back])
    assert got["at"] == 0 and got["urls"][0] == "/create?paso=1"


def test_listo_then_next_then_atras_keep_one_entry_per_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _editor(monkeypatch)
    opened = _js(CreativeState.edit_clip_general.fn(state))
    done = _js(CreativeState.close_clip_general.fn(state))
    forward = _js(state.next_view())
    back = _js(state.prev_view())
    got = _history([opened, done, forward, back])
    assert got["at"] == 0
    assert got["urls"][:2] == ["/create?paso=1", "/create?paso=2"]


def test_focus_skips_a_field_that_is_off() -> None:
    """Nit: with 12 phrases the field is disabled — the focus falls on its help."""
    from . import editor_idea_vm as idea

    script = (
        "const focused = []; const el = (id, off) => ({ id: id, disabled: off,"
        " focus() { focused.push(id); }, scrollIntoView() {} });"
        " const els = { a: el('a', true), b: el('b', false) };"
        " globalThis.document = { getElementById: i => els[i] || null };"
        " globalThis.window = { requestAnimationFrame: () => {} };"
        f" eval({json.dumps(idea.focus_script('a', 'b'))});"
        " console.log(JSON.stringify(focused));"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    assert json.loads(out.stdout) == ["b"]
