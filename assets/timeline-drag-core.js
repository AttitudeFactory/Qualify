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

   - **trim** (ED-03 m-25026623) — a handle of the chosen block: `trimBounds` (inside
     the video, ≥ the least a piece takes, ≤ A9's minute) and `trimValue` (½ s magnet,
     ¼ s to the playhead and the other blocks' edges).

   Near the scroller's edges the tracks scroll on their own (`autoScrollStep`). A held
   block never leaves its track (`clampShift`), and one dropped outside the tracks
   (`insideTracks`) goes back to its place with nothing changed (`dropVerdict`). An
   effect may also go up or down to another row of «Efectos» (`laneAt`, `laneShift`;
   ED-04), never out of them.

   - **insert** (ED-12 m-25029107) — files of the computer dragged over «Fotos y
     videos»: the gap they land in is the number of blocks whose middle is left of the
     pointer (`insertIndex`); `carriesFiles` tells such a drag from text or a link. */
(function (root) {
  "use strict";

  var STEP = 0.5; // the magnet (§3.3)
  var PHONE_PX = 44; // 1 s on a phone (D-T5)
  // ED-12 (m-25029107): «se mantiene apretado ½ s» — a finger or a pen holds still
  // this long to lift, so a short swipe slides the tracks and moves nothing
  var LONG_PRESS_MS = 500;
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

  /* ED-04 (m-25026627, Deivid 2026-11-20: «moverlos entre pistas»): an effect held
     over the rows of «Efectos» lands on the row under the pointer — `laneAt({y, tops,
     bottoms, from})`: the row whose box (client px) holds `y`, else the nearest one, so
     an effect never leaves the effects' rows (above them it is the first, below the
     last). No rows: it stays on `from`. */
  function laneAt(opts) {
    var tops = (opts && opts.tops) || [];
    var bottoms = (opts && opts.bottoms) || [];
    var n = Math.min(tops.length, bottoms.length);
    if (!n) return num(opts && opts.from);
    var y = num(opts.y);
    var best = 0;
    var bestDist = Infinity;
    for (var i = 0; i < n; i++) {
      var top = num(tops[i]);
      var bottom = num(bottoms[i]);
      if (y >= top && y <= bottom) return i;
      var dist = y < top ? top - y : y - bottom;
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    }
    return best;
  }

  /* The `dy` that shows a held effect on row `to` instead of its own row `from`: the
     rows' tops apart (it moves a whole row at a time, never between two). */
  function laneShift(opts) {
    var tops = (opts && opts.tops) || [];
    var from = num(opts && opts.from);
    var to = num(opts && opts.to);
    if (from < 0 || to < 0 || from >= tops.length || to >= tops.length) return 0;
    return num(tops[to]) - num(tops[from]);
  }

  /* What the screen hears at the drop of a text or an effect: «time», or — an effect
     put on another row — «time@N» (N its row, 0-based). */
  function timeWhat(opts) {
    var from = num(opts && opts.from);
    var to = opts && opts.to !== undefined && opts.to !== null ? num(opts.to) : from;
    return to !== from ? "time@" + to : "time";
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

  /* ED-12: the gap a dragged photo or video lands in — 0 before the first block, n
     after the last: how many blocks have their middle left of `x` (client px). */
  function insertIndex(mids, x) {
    var n = 0;
    (mids || []).forEach(function (mid) {
      if (num(mid) < num(x)) n += 1;
    });
    return n;
  }

  /* ED-12: whether a drag over the timeline carries files of the computer (anything
     else — text, a link — is left alone). */
  function carriesFiles(types) {
    return Array.prototype.slice.call(types || []).indexOf("Files") >= 0;
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

  /* ED-03 (m-25026623): the trim handles of a video's piece. Values are seconds of the
     piece's VIDEO (its source); on the track a second of video is 1/`speed` s.

     `trimBounds({edge, start, end, length, speed})`: where a handle of the piece
     [start, end) may go — inside the video's own material (0…`length`: past it is
     «extend», another ticket), never a piece under `trimMinSource(speed)`, never one
     over `SOURCE_MAX_S` of video (A9, `segment_source_too_long`). The same rule as
     `clip_editor_vm.trim_bounds` (a test runs both). */
  var SOURCE_MAX_S = 60; // A9: a stretch takes at most a minute of its video
  var SEGMENT_MIN_S = 1; // a piece takes at least 1 s of its video…
  var CUT_EDGE_S = 0.5; // …and, sped up, at least ½ s of the final video («Cortar»'s)
  var NEAR_S = 0.25; // the second magnet: the playhead and the edges near the handle

  function round2(value) {
    return Math.round(num(value) * 100) / 100;
  }

  function trimMinSource(speed) {
    var s = num(speed) > 0 ? num(speed) : 1;
    return Math.max(SEGMENT_MIN_S, CUT_EDGE_S * s);
  }

  function trimBounds(opts) {
    var least = trimMinSource(opts && opts.speed);
    var start = num(opts && opts.start);
    var end = num(opts && opts.end);
    var length = Math.max(num(opts && opts.length), end);
    if (opts && opts.edge === "start") {
      var low = Math.max(0, end - SOURCE_MAX_S);
      return { min: round2(low), max: round2(Math.max(end - least, low)) };
    }
    var high = Math.min(length, start + SOURCE_MAX_S);
    return { min: round2(Math.min(start + least, high)), max: round2(high) };
  }

  /* A handle dragged `dx` px (`px` px per second of the track): its new value. It starts
     at `value`; the block starts at `at` on the track (seconds of the final video) and
     its start handle's value is `from`, so the handle sits at `at + (v − from) / speed`.
     Two magnets: within `NEAR_S` of one of `targets` (the playhead, the other blocks'
     edges — track seconds) it lands exactly there; else on the ½ s of the video. Kept
     inside `min`…`max` (`trimBounds`, or the handle's `aria-valuemin`/`-max`). Returns
     `{value, at}`: the value (to the hundredth) and where the handle now sits. */
  function trimValue(opts) {
    var speed = num(opts.speed) > 0 ? num(opts.speed) : 1;
    var at = num(opts.at);
    var from = num(opts.from);
    var raw = num(opts.value) + pxToSeconds(opts.dx, opts.px) * speed;
    var here = at + (raw - from) / speed;
    var best = null;
    var bestDist = NEAR_S + 1e-9;
    (opts.targets || []).forEach(function (target) {
      var dist = Math.abs(num(target) - here);
      if (dist <= bestDist) {
        bestDist = dist;
        best = num(target);
      }
    });
    var value = best === null ? snap(raw) : from + (best - at) * speed;
    var low = opts.min === undefined ? -Infinity : num(opts.min);
    var high = opts.max === undefined ? Infinity : num(opts.max);
    value = round2(Math.min(Math.max(value, low), Math.max(high, low)));
    return { value: value, at: at + (value - from) / speed };
  }

  /* «0:04», «0:03,7», «0:03,25»: a video's handle to the hundredth, as
     `timeline_vm.clock_exact` (the bubble says «Desde 0:03,7» — ED-03 UX review). */
  function clockExact(seconds) {
    var s = Math.max(Math.round(num(seconds) * 100) / 100, 0);
    var whole = Math.floor(s + 1e-9);
    var m = Math.floor(whole / 60);
    var sec = whole % 60;
    var rest = Math.round((s - whole) * 100);
    var tail = rest > 0 ? String(rest < 10 ? "0" + rest : rest).replace(/0+$/, "") : "";
    return m + ":" + (sec < 10 ? "0" : "") + sec + (tail ? "," + tail : "");
  }

  /* The px a block is moved by right now: its inline `translateX(…px)` (written by
     `timeline-drag.js`) or its computed `matrix(…)` / `matrix3d(…)` (mid-transition);
     "", "none" or anything else is 0. The lens under the chosen block takes it off to
     find the block's resting place, then wears the same transform (Deivid,
     2026-11-16: the glass moves WITH the block, never behind it). */
  function shiftOf(transform) {
    var text = String(transform || "");
    var m = /translateX\(\s*(-?[\d.]+)px\s*\)/.exec(text);
    var two = /translate\(\s*(-?[\d.]+)px\s*,/.exec(text); // ED-04: an effect's row move
    var v = 0;
    if (m) {
      v = parseFloat(m[1]);
    } else if (two) {
      v = parseFloat(two[1]);
    } else if ((m = /^matrix(3d)?\(([^)]*)\)$/.exec(text.trim()))) {
      var parts = m[2].split(",");
      v = parseFloat(parts[m[1] ? 12 : 4]);
    }
    return isFinite(v) ? v : 0;
  }

  /* ED-04 (Deivid 2026-11-20: «su efecto cristal se separa»): the px a block is moved
     DOWN by right now — an effect held over another row (`translate(x, y)`) or settling
     there (`matrix(…)` / `matrix3d(…)`); a `translateX` or nothing is 0. The lens takes
     it off too, so it rests on the block's own row and then wears its transform. */
  function shiftYOf(transform) {
    var text = String(transform || "");
    var m = /translate\(\s*-?[\d.]+px\s*,\s*(-?[\d.]+)px\s*\)/.exec(text);
    var v = 0;
    if (m) {
      v = parseFloat(m[1]);
    } else if ((m = /^matrix(3d)?\(([^)]*)\)$/.exec(text.trim()))) {
      var parts = m[2].split(",");
      v = parseFloat(parts[m[1] ? 13 : 5]);
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
    laneAt: laneAt,
    laneShift: laneShift,
    timeWhat: timeWhat,
    dropVerdict: dropVerdict,
    clampScroll: clampScroll,
    liftDecision: liftDecision,
    clock: clock,
    shiftOf: shiftOf,
    shiftYOf: shiftYOf,
    SOURCE_MAX_S: SOURCE_MAX_S,
    NEAR_S: NEAR_S,
    trimMinSource: trimMinSource,
    trimBounds: trimBounds,
    trimValue: trimValue,
    clockExact: clockExact,
    insertIndex: insertIndex,
    carriesFiles: carriesFiles,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.__qTimelineDragCore = api;
})(typeof window !== "undefined" ? window : null);
