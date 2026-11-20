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
