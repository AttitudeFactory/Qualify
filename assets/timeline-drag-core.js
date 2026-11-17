/* The timeline's drag and drop (ED-10 m-25026648), PURE: no DOM, no timers, so `node`
   tests it without a browser (`Qualify/test_timeline_drag_js.py`). The DOM half,
   `assets/timeline-drag.js`, uses it through `window.__qTimelineDragCore`.

   Two drags (Deivid, 2026-11-16: «quiero un drag and drop para mover los componentes»):

   - **move** — a video or a photo of «Fotos y videos» changes places. The blocks have
     different widths (their seconds), so the slot is the one whose LEFT edge is nearest
     the lifted block's left edge (`dropIndex`), and the others make room with the
     lifted block's own width (`layoutShifts`). Positions are px from the track's start,
     measured inside `.q-tl__scroller` (so its scroll never skews them).
   - **time** — a text or an effect slides along its track: px → seconds at the track's
     scale (`scaleOf`), snapped to ½ s, kept inside the video (`shiftedStart`).

   Near the scroller's edges the tracks scroll on their own (`autoScrollStep`). A held
   block never leaves its track (`clampShift`), and one dropped outside the tracks
   (`insideTracks`) goes back to its place with nothing changed (`dropVerdict`). */
(function (root) {
  "use strict";

  var STEP = 0.5; // the magnet (§3.3)
  var PHONE_PX = 44; // 1 s on a phone (D-T5)
  var LONG_PRESS_MS = 300; // a finger or a pen holds still this long to lift
  var MOUSE_LIFT_PX = 5; // a mouse lifts once it moves this far while pressed
  var MOVE_CANCEL_PX = 10; // a finger moving this far before the hold: a scroll
  var EDGE_PX = 48; // the band at each edge of the scroller that scrolls it
  var MAX_SCROLL_PX = 14; // per frame, at the very edge

  function num(value) {
    var n = Number(value);
    return isFinite(n) ? n : 0;
  }

  /* The nearest half second. */
  function snap(seconds) {
    return Math.round(num(seconds) / STEP) * STEP;
  }

  /* Seconds a horizontal move of `dx` px is worth at `px` px per second. */
  function pxToSeconds(dx, px) {
    return px > 0 ? num(dx) / px : 0;
  }

  /* px per second of the track: a phone's fixed scale (`px`, 44 by default); on a
     desktop the tracks fill the width, so the canvas `width` over the `total` seconds. */
  function scaleOf(opts) {
    if (!opts) return PHONE_PX;
    if (opts.phone) return num(opts.px) > 0 ? num(opts.px) : PHONE_PX;
    var total = num(opts.total);
    var width = num(opts.width);
    return total > 0 && width > 0 ? width / total : PHONE_PX;
  }

  /* A text or an effect dragged `dx` px: its new start, snapped to ½ s, never before
     0:00 nor ending after the video (`timeline_vm.shift`'s rule, the keyboard's ←/→). */
  function shiftedStart(opts) {
    var start = num(opts.start);
    var length = Math.max(num(opts.length), 0);
    var total = Math.max(num(opts.total), 0);
    var moved = snap(start + pxToSeconds(opts.dx, opts.px));
    return Math.min(Math.max(moved, 0), Math.max(total - length, 0));
  }

  /* Where the lifted block `from` drops: the slot (0…n-1 among the blocks once it is out
     of the row) whose left edge is nearest `left` — the lifted block's left edge now, px
     from the track's start. At rest it is its own slot; dragged right it takes the next
     slot past half of the neighbour's width, whatever the widths. */
  function dropIndex(widths, from, left) {
    var n = (widths || []).length;
    if (n < 2 || from < 0 || from >= n) return from;
    var best = from;
    var bestDist = Infinity;
    var at = 0; // the left edge of slot k: the widths of the first k other blocks
    var k = 0;
    for (var i = 0; i <= n; i++) {
      if (i !== from) {
        var dist = Math.abs(num(left) - at);
        if (dist < bestDist) {
          bestDist = dist;
          best = k;
        }
        if (i < n) {
          at += num(widths[i]);
          k += 1;
        }
      }
    }
    return Math.min(best, n - 1);
  }

  /* The px each block moves when `from` is dropped at `to` (remove-then-insert, like
     `timeline_vm.move_to`): the others make room with the lifted block's width, and the
     lifted block's own entry is where its slot is. */
  function layoutShifts(widths, from, to) {
    var n = (widths || []).length;
    var shifts = [];
    for (var s = 0; s < n; s++) shifts.push(0);
    if (n < 2 || from < 0 || from >= n || to < 0 || to >= n) return shifts;
    var order = [];
    for (var i = 0; i < n; i++) if (i !== from) order.push(i);
    order.splice(to, 0, from);
    var oldLeft = [];
    var x = 0;
    for (var j = 0; j < n; j++) {
      oldLeft.push(x);
      x += num(widths[j]);
    }
    x = 0;
    for (var p = 0; p < n; p++) {
      var idx = order[p];
      shifts[idx] = x - oldLeft[idx];
      x += num(widths[idx]);
    }
    return shifts;
  }

  /* `autoScrollStep({x, left, right})`: px the scroller scrolls this frame while a
     block is held at `x` (the pointer) — negative inside the left band, positive inside
     the right band, faster the closer to (or past) the edge, 0 in between. */
  function autoScrollStep(opts) {
    if (!opts) return 0;
    var x = num(opts.x);
    var left = num(opts.left);
    var right = num(opts.right);
    var edge = num(opts.edge) > 0 ? num(opts.edge) : EDGE_PX;
    var most = num(opts.max) > 0 ? num(opts.max) : MAX_SCROLL_PX;
    if (right - left < edge * 2) edge = Math.max((right - left) / 4, 1);
    if (x < left + edge) {
      var inLeft = Math.min((left + edge - x) / edge, 1);
      return -Math.max(Math.round(most * inLeft), 1);
    }
    if (x > right - edge) {
      var inRight = Math.min((x - (right - edge)) / edge, 1);
      return Math.max(Math.round(most * inRight), 1);
    }
    return 0;
  }

  /* Is the pointer (`x`, `y`, client px) over the tracks' box (`left`/`right`/`top`/
     `bottom`, the scroller's `getBoundingClientRect()`)? A block dropped outside goes
     back to its place (Deivid, 2026-11-17: «puedo sacar los componentes fuera de la
     time line no quiero eso»). The edges count as inside. */
  function insideTracks(opts) {
    if (!opts) return false;
    var x = num(opts.x);
    var y = num(opts.y);
    return (
      x >= num(opts.left) && x <= num(opts.right) && y >= num(opts.top) && y <= num(opts.bottom)
    );
  }

  /* The `dx` a held block may show: its left edge (`left`, px from the track's start)
     plus `dx` stays inside 0…`span` − `width`, so the block never leaves its track (the
     row's other blocks' extent for a move; the video's length for a text or an effect). */
  function clampShift(opts) {
    if (!opts) return 0;
    var left = num(opts.left);
    var lo = -left;
    var hi = Math.max(num(opts.span) - Math.max(num(opts.width), 0) - left, lo);
    return Math.min(Math.max(num(opts.dx), lo), hi);
  }

  /* What a release does: «back» (a cancelled pointer, a drop outside the tracks or on
     its own place: nothing changes) or «apply». */
  function dropVerdict(opts) {
    if (!opts || opts.cancelled || opts.outside || opts.same) return "back";
    return "apply";
  }

  /* The scroller's next `scrollLeft` after a `step`, inside 0…`max`. */
  function clampScroll(current, step, max) {
    return Math.min(Math.max(num(current) + num(step), 0), Math.max(num(max), 0));
  }

  /* What a press does so far: «lift» (a mouse moved `MOUSE_LIFT_PX`; a finger held
     `LONG_PRESS_MS`), «cancel» (a finger moved first: it scrolls the tracks) or «wait». */
  function liftDecision(opts) {
    var dist = Math.max(num(opts && opts.dist), 0);
    if (!opts || !opts.touch) return dist >= MOUSE_LIFT_PX ? "lift" : "wait";
    if (dist > MOVE_CANCEL_PX) return "cancel";
    return num(opts.elapsed) >= LONG_PRESS_MS ? "lift" : "wait";
  }

  /* «0:04», «0:04,5» — the time the bubble shows while a block is dragged
     (`timeline_vm.clock`). */
  function clock(seconds) {
    var s = Math.max(snap(seconds), 0);
    var whole = Math.floor(s);
    var m = Math.floor(whole / 60);
    var sec = whole % 60;
    return m + ":" + (sec < 10 ? "0" : "") + sec + (s - whole >= STEP ? ",5" : "");
  }

  /* The px a block is moved by right now: its inline `translateX(…px)` (written by
     `timeline-drag.js`) or its computed `matrix(…)` / `matrix3d(…)` (mid-transition);
     "", "none" or anything else is 0. The lens under the chosen block takes it off to
     find the block's resting place, then wears the same transform (Deivid,
     2026-11-16: the glass moves WITH the block, never behind it). */
  function shiftOf(transform) {
    var text = String(transform || "");
    var m = /translateX\(\s*(-?[\d.]+)px\s*\)/.exec(text);
    var v = 0;
    if (m) {
      v = parseFloat(m[1]);
    } else if ((m = /^matrix(3d)?\(([^)]*)\)$/.exec(text.trim()))) {
      var parts = m[2].split(",");
      v = parseFloat(parts[m[1] ? 12 : 4]);
    }
    return isFinite(v) ? v : 0;
  }

  var api = {
    STEP: STEP,
    LONG_PRESS_MS: LONG_PRESS_MS,
    MOUSE_LIFT_PX: MOUSE_LIFT_PX,
    MOVE_CANCEL_PX: MOVE_CANCEL_PX,
    snap: snap,
    pxToSeconds: pxToSeconds,
    scaleOf: scaleOf,
    shiftedStart: shiftedStart,
    dropIndex: dropIndex,
    layoutShifts: layoutShifts,
    autoScrollStep: autoScrollStep,
    insideTracks: insideTracks,
    clampShift: clampShift,
    dropVerdict: dropVerdict,
    clampScroll: clampScroll,
    liftDecision: liftDecision,
    clock: clock,
    shiftOf: shiftOf,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.__qTimelineDragCore = api;
})(typeof window !== "undefined" ? window : null);
