"""ED-07 (m-25026638): covers how a text is dragged on main today, with a mouse.
`assets/timeline-drag.js` run by `node` over a tiny fake DOM — a desktop timeline with
one text block — fed the pointer events a real mouse sends: `pointerdown` on the block,
`pointermove`, `pointerup`. The screen hears `(id, "time", start)` through
`[data-tl-drag-trigger]`. It reproduces no bug: the drag works. The live report («no lo
movió») came from an automated drag with no `pointermove` between press and release,
which is a click by design (see the last cases). Skipped where `node` is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not installed")

# A fake DOM with only what the drag reads: attributes, classes, `closest`,
# `querySelector(All)` over simple compound selectors (`.a`, `[b]`, `[b="c"]`,
# `:scope > .a`, comma lists), boxes and computed custom properties.
_HARNESS = r"""
function parts(sel) {
  return sel.split(",").map(function (s) { return s.trim(); });
}
function matchOne(el, sel) {
  var tokens = sel.match(/\.[\w-]+|\[[^\]]+\]/g) || [];
  if (!tokens.length || tokens.join("") !== sel) return false;
  return tokens.every(function (t) {
    if (t[0] === ".") return el.cls.has(t.slice(1));
    var m = t.slice(1, -1).match(/^([\w-]+)(?:="([^"]*)")?$/);
    if (!m || !(m[1] in el.attrs)) return false;
    return m[2] === undefined || el.attrs[m[1]] === m[2];
  });
}
class El {
  constructor(cls, attrs, opts) {
    opts = opts || {};
    this.nodeType = 1;
    this.cls = new Set(cls || []);
    var self = this;
    this.classList = {
      add: function () { for (var c of arguments) self.cls.add(c); },
      remove: function () { for (var c of arguments) self.cls.delete(c); },
      contains: function (c) { return self.cls.has(c); },
    };
    this.attrs = Object.assign({}, attrs || {});
    this.css = opts.css || {};
    this.rect = Object.assign({ left: 0, top: 0, width: 0, height: 0 }, opts.rect || {});
    this.rect.right = this.rect.left + this.rect.width;
    this.rect.bottom = this.rect.top + this.rect.height;
    this.children = [];
    this.parentElement = null;
    this.style = {};
    this.clientLeft = 0;
    this.clicks = 0;
    this.isConnected = true;
  }
  append(child) { child.parentElement = this; this.children.push(child); return child; }
  appendChild(child) { return this.append(child); }
  getAttribute(n) { return n in this.attrs ? String(this.attrs[n]) : null; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  removeAttribute(n) { delete this.attrs[n]; }
  hasAttribute(n) { return n in this.attrs; }
  matches(sel) { var el = this; return parts(sel).some(function (s) { return matchOne(el, s); }); }
  closest(sel) {
    for (var n = this; n; n = n.parentElement) if (n.matches(sel)) return n;
    return null;
  }
  querySelectorAll(sel) {
    var out = [];
    var self = this;
    parts(sel).forEach(function (s) {
      var direct = s.indexOf(":scope >") === 0;
      var want = direct ? s.slice(8).trim() : s;
      (function walk(node) {
        node.children.forEach(function (c) {
          if (matchOne(c, want) && out.indexOf(c) < 0) out.push(c);
          if (!direct) walk(c);
        });
      })(self);
    });
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() { return this.rect; }
  getClientRects() { return [this.rect]; }
  click() { this.clicks += 1; }
  focus() {}
  setPointerCapture() {}
}

var listeners = [];
global.window = global;
global.navigator = {};
global.document = {
  addEventListener: function (type, fn, opts) {
    var capture = opts === true || !!(opts && opts.capture);
    listeners.push({ type: type, fn: fn, capture: capture });
  },
  createElement: function () { return new El([], {}); },
  querySelectorAll: function () { return []; },
  querySelector: function () { return null; },
};
global.getComputedStyle = function (el) {
  return { getPropertyValue: function (n) { return (el && el.css && el.css[n]) || ""; } };
};
global.requestAnimationFrame = function () { return 0; };
global.cancelAnimationFrame = function () {};
global.MutationObserver = class { observe() {} disconnect() {} };

function fire(type, init) {
  var e = Object.assign({ type: type, pointerType: "mouse", button: 0, pointerId: 1,
    defaultPrevented: false, preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () {} }, init);
  listeners.filter(function (l) { return l.type === type && l.capture; })
    .concat(listeners.filter(function (l) { return l.type === type && !l.capture; }))
    .forEach(function (l) { l.fn(e); });
  return e;
}

// A desktop timeline 1000 px wide for a 10 s video: 100 px per second. The «Textos»
// track holds one text from 0:02 to 0:04 (left 200 px, 200 px wide).
var root = new El([], { "data-q-timeline": "" }, { css: { "--tl-total": "10" } });
root.append(new El(["q-tl__frame"], {}, { css: { "--tl-mode": "desk" } }));
var scroller = root.append(
  new El(["q-tl__scroller"], {}, { rect: { left: 0, top: 100, width: 1000, height: 200 } }));
var canvas = scroller.append(
  new El(["q-tl__canvas"], {}, { rect: { left: 0, top: 100, width: 1000, height: 200 } }));
var lane = canvas.append(new El(["q-tl__lane", "q-tl__lane--text"], {},
  { rect: { left: 0, top: 180, width: 1000, height: 40 } }));
var item = lane.append(new El(["q-tl__item"], {},
  { rect: { left: 200, top: 180, width: 200, height: 40 } }));
var block = item.append(new El(["q-tl__block"], {
  "data-tl-block": "text", "data-tl-id": "t1", "data-tl-start": "2", "data-tl-len": "2",
}, { rect: { left: 200, top: 180, width: 200, height: 40 } }));
var label = block.append(new El(["q-tl__name"], {}));
var trigger = root.append(new El([], { "data-tl-drag-trigger": "" }));
"""


def _drag(steps: str) -> dict:
    """Load both scripts over the fake DOM, run `steps` and report, once the drop has
    settled (`SETTLE_MS` 160), what the screen heard."""
    script = (
        _HARNESS
        + f"require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});\n"
        + f"require({json.dumps(str(_ASSETS / 'timeline-drag.js'))});\n"
        + steps
        + r"""
setTimeout(function () {
  console.log(JSON.stringify({
    clicks: trigger.clicks,
    drop: window.__qTimelineDrop || null,
    dragging: root.getAttribute("data-tl-dragging"),
  }));
  process.exit(0);
}, 400);
"""
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(out.stdout)


def test_the_drag_core_says_a_text_slides_in_time() -> None:
    out = subprocess.run(
        [
            _NODE,
            "-e",
            f"const c = require({json.dumps(str(_ASSETS / 'timeline-drag-core.js'))});"
            "console.log(JSON.stringify(['text','effect','video','photo','ai'].map(c.dragMode)));",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(out.stdout) == ["time", "time", "move", "move", "move"]


def test_a_mouse_drags_a_text_two_seconds_later() -> None:
    heard = _drag(
        r"""
fire("pointerdown", { target: label, clientX: 250, clientY: 200 });
fire("pointermove", { target: label, clientX: 260, clientY: 200 });
fire("pointermove", { target: label, clientX: 400, clientY: 201 });
fire("pointermove", { target: label, clientX: 450, clientY: 202 });
fire("pointerup", { target: label, clientX: 450, clientY: 202 });
"""
    )
    assert heard["clicks"] == 1
    assert heard["drop"] == {"id": "t1", "what": "time", "value": 4}


def test_one_move_straight_to_the_end_is_enough() -> None:
    # what an automated drag sends: down, a single move to the target, up
    heard = _drag(
        r"""
fire("pointerdown", { target: block, clientX: 250, clientY: 200 });
fire("pointermove", { target: block, clientX: 150, clientY: 200 });
fire("pointerup", { target: block, clientX: 150, clientY: 200 });
"""
    )
    assert heard["drop"] == {"id": "t1", "what": "time", "value": 1}


def test_a_drag_never_takes_a_text_past_the_video() -> None:
    heard = _drag(
        r"""
fire("pointerdown", { target: block, clientX: 250, clientY: 200 });
fire("pointermove", { target: block, clientX: 990, clientY: 200 });
fire("pointerup", { target: block, clientX: 990, clientY: 200 });
"""
    )
    assert heard["drop"] == {"id": "t1", "what": "time", "value": 8}


def test_a_press_and_release_with_no_move_between_is_a_click() -> None:
    # down and up at two points with no `pointermove` in between (no real mouse does
    # that): nothing was lifted, so the screen hears no drop — React's click chooses it
    heard = _drag(
        r"""
fire("pointerdown", { target: block, clientX: 250, clientY: 200 });
fire("pointerup", { target: block, clientX: 450, clientY: 200 });
"""
    )
    assert heard == {"clicks": 0, "drop": None, "dragging": None}


def test_less_than_a_quarter_second_puts_it_back() -> None:
    # 20 px = 0.2 s: the ½ s magnet keeps 0:02, a drop «on its own place» changes nothing
    heard = _drag(
        r"""
fire("pointerdown", { target: block, clientX: 250, clientY: 200 });
fire("pointermove", { target: block, clientX: 270, clientY: 200 });
fire("pointerup", { target: block, clientX: 270, clientY: 200 });
"""
    )
    assert heard["clicks"] == 0 and heard["drop"] is None


def test_a_drop_off_the_tracks_changes_nothing() -> None:
    heard = _drag(
        r"""
fire("pointerdown", { target: block, clientX: 250, clientY: 200 });
fire("pointermove", { target: block, clientX: 450, clientY: 600 });
fire("pointerup", { target: block, clientX: 450, clientY: 600 });
"""
    )
    assert heard["clicks"] == 0 and heard["drop"] is None
