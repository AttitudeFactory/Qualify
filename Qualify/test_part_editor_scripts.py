"""Execute the editor's browser lifecycle against a small DOM/event model.

The full Playwright suite exercises the compiled Radix app; these tests pin the
late focus and cold-address races without depending on animation timing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from .creative_state import CreativeState, _clear_part_query_script

NODE = shutil.which("node")
ASSET = Path(__file__).resolve().parents[1] / "assets" / "part-editor.js"
DOM = r"""
const assert = require('node:assert/strict');
const events = {}, browserEvents = {};
const emit = (kind, event = {}) => (events[kind] || []).forEach(f => f(event));
const pop = () => (browserEvents.popstate || []).forEach(f => f({}));
let dialog = false, observer;
global.window = global;
global.location = {href: 'http://localhost/create?paso=2&parte=1'};
global.history = {state: {qPartEntry: true, qPrevPaso: '1'},
 replaceState(state, unused, url) {
  this.state = state; location.href = new URL(url, location.href).href; },
 pushState(state, unused, url) { this.replaceState(state, unused, url); },
 back() { this.replaceState({}, '', '/create?paso=2'); pop(); }};
global.addEventListener = (type, fn) => (browserEvents[type] ||= []).push(fn);
global.requestAnimationFrame = fn => fn();
global.MutationObserver = class { constructor(fn) { observer = fn; } observe() {} };
const nodes = {};
const node = id => ({id, closest() { return null; }, focus() {
 if (document.activeElement === this) return;
 document.activeElement = this; emit('focusin', {target: this}); }});
nodes.change = node('change'); nodes.heading = node('heading');
nodes['q-part-editor-question'] = node('question');
global.document = {body: {}, activeElement: null,
 getElementById(id) { return nodes[id] || null; },
 querySelector(selector) { return dialog ? {} : null; },
 addEventListener(type, fn) { (events[type] ||= []).push(fn); }};
"""


def run(script: str, *, asset: bool = True) -> None:
    if NODE is None:
        pytest.skip("the JavaScript runtime is unavailable; Playwright covers the browser path")
    result = subprocess.run(
        [NODE],
        input=DOM + (ASSET.read_text(encoding="utf-8") if asset else "") + script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_close_only_restores_from_the_native_unmount_hook_without_retaining_focus() -> None:
    run(r"""
dialog = true; document.activeElement = nodes.heading;
__qPartEditor.close('change', false);
assert.equal(document.activeElement, nodes.heading); // focus trap still mounted
dialog = false; __qPartEditor.restoreAfterClose('change');
assert.equal(document.activeElement, nodes.change);
// No global focus guard may intercept later intentional programmatic card focus.
nodes.heading.focus(); assert.equal(document.activeElement, nodes.heading);
""")


def test_pop_close_never_rewrites_forward_address_or_focuses_before_the_hook() -> None:
    run(r"""
const address = location.href;
document.activeElement = nodes.heading;
__qPartEditor.close('change', false);
assert.equal(location.href, address); // a later Forward entry stays intact
assert.equal(document.activeElement, nodes.heading);
delete nodes.change; // owning context disappeared before the native hook arrived
__qPartEditor.restoreAfterClose('change');
assert.equal(document.activeElement, nodes.heading);
""")


@pytest.mark.parametrize("raw", ["99", "", "-1"])
def test_invalid_cold_address_needs_no_asset_and_keeps_the_guarded_step(raw: str) -> None:
    import json

    run(
        "location.href = 'http://localhost/create?paso=1&producto=p&parte=' + "
        + json.dumps(raw)
        + ";"
        + _clear_part_query_script([raw])
        + "const u = new URL(location.href); assert.equal(u.searchParams.get('parte'), null);"
        + "assert.equal(u.searchParams.get('paso'), '1');"
        + "assert.equal(u.searchParams.get('producto'), 'p');"
        + "assert.equal(window.__qPartEditor, undefined);",
        asset=False,
    )
    state = CreativeState()
    assert state.reconcile_reel_editor_route(f"?paso=2&parte={raw}")
    assert state.create_step_n == 1 and not state.reel_edit_open


def test_a_delayed_invalid_address_reply_does_not_replace_a_new_part() -> None:
    run(
        _clear_part_query_script("99")
        + "assert.equal(new URL(location.href).searchParams.get('parte'), '1');",
        asset=False,
    )


def test_ui4_uses_native_autofocus_prevention_and_other_drawers_keep_defaults() -> None:
    import reflex as rx

    from .part_editor_view import part_editor
    from .ui import drawer

    custom = part_editor(rx.fragment(), rx.fragment(), rx.fragment()).children[0]
    for event in ("on_open_auto_focus", "on_close_auto_focus"):
        assert "preventDefault" in str(custom.event_triggers[event])
    normal = drawer(
        rx.text("Contenido"),
        open=False,
        on_open_change=CreativeState.set_reel_edit_open,
        title="Prueba",
    ).children[0]
    assert "on_open_auto_focus" not in normal.event_triggers
    assert "on_close_auto_focus" not in normal.event_triggers


def test_native_close_consumes_a_stable_target_once_and_respects_new_context() -> None:
    from .test_part_editor import editor

    state = editor(2)
    state.create_entered = True
    key = state.reel_edit_key
    state.set_reel_edit_open(False)
    assert state.reel_edit_key == ""
    assert key in str(state.restore_reel_edit_focus())
    assert state.restore_reel_edit_focus() is None
    state.edit_reel_part(key)
    state.set_reel_edit_open(False)
    state.edit_reel_part(key)
    assert state.restore_reel_edit_focus() is None  # a newer sheet owns focus
    state.set_reel_edit_open(False)
    state._product_changed()
    assert state.restore_reel_edit_focus() is None


@pytest.mark.parametrize("action", ["save", "cancel", "pop"])
def test_same_step_pop_before_native_exit_hook_preserves_its_pending_target(action: str) -> None:
    from .test_part_editor import editor

    state = editor(2)
    state.create_entered = True
    key = state.reel_edit_key
    if action == "save":
        state.save_reel_part({"description": "Mi parte actualizada"})
    elif action == "cancel":
        state.set_reel_edit_open(False)
    else:
        state.reconcile_reel_editor_route("?paso=2")
    state.reconcile_reel_editor_route("?paso=2")  # browser event wins the race
    state.reconcile_reel_editor_route("?paso=2")  # duplicate route notification is idempotent
    assert key in str(state.restore_reel_edit_focus())
    assert state.restore_reel_edit_focus() is None


def test_sheet_history_does_not_advance_step_epoch_but_real_steps_still_settle() -> None:
    from .test_part_editor import editor

    state = editor(2)
    state.create_entered = True
    state.create_entry_epoch = 7
    assert "qStepEntry" not in str(state.enter_create_step())
    assert state.create_entry_epoch == 7
    events = state.reconcile_reel_editor_route("?paso=2")
    assert state.create_entry_epoch == 7 and "qStepEntry" not in str(events)
    events = state.reconcile_reel_editor_route("?paso=3")
    assert state.create_step_n == 3 and state.create_entry_epoch == 8
    assert "qStepEntry" in str(events) and "q-step-title" in str(events)
    state.reconcile_reel_editor_route("?paso=3")
    assert state.create_entry_epoch == 8


def test_guarded_real_navigation_acknowledges_the_product_step_and_drops_pending_focus() -> None:
    state = CreativeState()
    state.create_entered = True
    state.create_entry_epoch = 3
    state._reel_edit_return_id = "q-part-change-old"
    events = state.reconcile_reel_editor_route("?paso=5&parte=99")
    assert state.create_step_n == 1 and state.create_entry_epoch == 4
    assert "qStepEntry" in str(events)
    assert state.restore_reel_edit_focus() is None
