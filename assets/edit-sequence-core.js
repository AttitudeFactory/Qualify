/* The preview-in-sequence's clock (ED-01b m-25029106), PURE: no DOM, no timers, so
   `node` tests it without a browser (`Qualify/test_edit_sequence_js.py`). The engine in
   `assets/edit-preview.js` (sequence mode) uses it through `window.__qEditSeqCore`.

   One clock: `t`, seconds of the FINAL video. A sequence is `Qualify/edit_sequence.py`'s
   JSON: `blocks` in order, each with `out_start`/`out_end` on that clock (no gaps), a
   video block's `src_start`/`src_end` and `speed`, a photo's `dur`; `texts` and
   `effects` with `start`/`end` on the same clock. */
(function (root) {
  "use strict";

  var RATE_MAX = 16; // what a browser plays at most (EF-04's speeds go to ×30)
  var RATE_MIN = 0.0625;

  function total(seq) {
    var blocks = (seq && seq.blocks) || [];
    return blocks.length ? blocks[blocks.length - 1].out_end : 0;
  }

  /* The index of the block shown at `t` (-1 with no blocks); past the end, the last. */
  function blockAt(seq, t) {
    var blocks = (seq && seq.blocks) || [];
    if (!blocks.length) return -1;
    for (var i = 0; i < blocks.length; i++) {
      if (t < blocks[i].out_end) return i;
    }
    return blocks.length - 1;
  }

  /* Seconds of the block's SOURCE shown at final time `t` (a video's stretch). */
  function sourceTime(block, t) {
    var speed = block.speed > 0 ? block.speed : 1;
    var into = Math.min(Math.max(t - block.out_start, 0), block.out_end - block.out_start);
    return block.src_start + into * speed;
  }

  /* The final time a video block is at when its source is at `src` (the inverse). */
  function finalTime(block, src) {
    var speed = block.speed > 0 ? block.speed : 1;
    var t = block.out_start + (src - block.src_start) / speed;
    return Math.min(Math.max(t, block.out_start), block.out_end);
  }

  /* The playbackRate a browser can use for a speed (≤ ×16). */
  function rate(speed) {
    return Math.min(Math.max(speed > 0 ? speed : 1, RATE_MIN), RATE_MAX);
  }

  function slower(speed) {
    return speed > RATE_MAX;
  }

  /* Which overlays (texts or effects) show at `t`: `start <= t < end`. */
  function activeAt(list, t) {
    var on = [];
    for (var i = 0; i < (list || []).length; i++) {
      if (list[i].start <= t && t < list[i].end) on.push(i);
    }
    return on;
  }

  /* The next block after `index`, back to the first after the last (the loop). */
  function nextIndex(seq, index) {
    var n = ((seq && seq.blocks) || []).length;
    if (!n) return -1;
    return (index + 1) % n;
  }

  /* The next block after `index` that a `<video>` can preload ("" url = none). */
  function nextVideo(seq, index, broken) {
    var blocks = (seq && seq.blocks) || [];
    for (var step = 1; step <= blocks.length; step++) {
      var j = (index + step) % blocks.length;
      var b = blocks[j];
      if (b.kind === "video" && b.url && !(broken && broken[b.key])) return j;
    }
    return -1;
  }

  /* Where the clock goes after `dt` seconds of a timed block (a photo, a block that
     cannot play): `{t, index, wrapped}` — past the block's end, the next block starts;
     past the video's end, back to 0:00. */
  function advance(seq, t, dt) {
    var end = total(seq);
    if (end <= 0) return { t: 0, index: -1, wrapped: false };
    var next = t + Math.max(dt, 0);
    if (next >= end) return { t: 0, index: blockAt(seq, 0), wrapped: true };
    return { t: next, index: blockAt(seq, next), wrapped: false };
  }

  /* «0:04», «0:04,5» — the time as the preview writes it. */
  function clock(seconds) {
    var value = Math.max(seconds, 0);
    var minutes = Math.floor(value / 60);
    var rest = value - minutes * 60;
    var whole = Math.floor(rest);
    var tenth = Math.round((rest - whole) * 10);
    if (tenth >= 10) {
      whole += 1;
      tenth = 0;
    }
    var text = minutes + ":" + (whole < 10 ? "0" : "") + whole;
    return tenth ? text + "," + tenth : text;
  }

  /* The phone timeline (its tracks slide under a fixed playhead: `left` px = `t` × `px`).
     The clock and the owner share one scroller, so who moves it decides:

     `scrollTarget({owner, t, px, current, max})` — where the clock should scroll the
     tracks to show `t`, or -1 to leave them. A seek the owner made (sliding the tracks,
     the playhead's input, ←/→, a tap on the ruler) never writes back: the tracks are
     already where the owner put them, and writing a rounded position back is what
     snapped every small slide to the nearest ½ s. Clamped to the scroller's end (`max`),
     so a write the browser would clamp is not repeated forever. */
  function scrollTarget(opts) {
    if (!opts || opts.owner) return -1;
    var px = opts.px > 0 ? opts.px : 44;
    var left = Math.round(Math.max(Number(opts.t) || 0, 0) * px);
    if (opts.max >= 0) left = Math.min(left, Math.max(Math.floor(opts.max), 0));
    var current = Number(opts.current);
    if (isFinite(current) && Math.abs(current - left) < 1) return -1;
    return left;
  }

  /* `slideTime({left, t, px, total, max})` — a scroll of the tracks to `left`: the time
     the owner slid to (exact: `left / px`, never rounded to ½ s), or -1 when the tracks
     sit where the clock at `t` puts them (the clock's own write, or no move). Positions,
     not flags: nothing can stay stuck and swallow the owner's next slide. */
  function slideTime(opts) {
    if (!opts) return -1;
    var px = opts.px > 0 ? opts.px : 44;
    // where the clock would put the tracks (`current: NaN` never matches: always ≥ 0)
    var expected = scrollTarget({ t: opts.t, px: px, current: NaN, max: opts.max });
    var left = Number(opts.left) || 0;
    if (Math.abs(left - expected) < 1.5) return -1;
    var end = opts.total > 0 ? opts.total : 0;
    return Math.min(Math.max(left / px, 0), end);
  }

  var WAIT_MS = 15000; // the single-stretch preview's wait for a video's length
  var WAIT_ROUNDS = 3; // a network still bringing it gets this many waits in all

  /* `waitVerdict({ready, loading, rounds})` — a video block's `<video>` after one
     `WAIT_MS` wait for its length: «ready» (it has metadata: nothing to do), «wait» (the
     network is still bringing it and it has had fewer than `WAIT_ROUNDS` waits: wait
     again), or «broken» (it never loaded nor failed: the block becomes a timed one, like
     a video that errored, so the clock never freezes on it). `rounds`: waits so far,
     this one included. */
  function waitVerdict(opts) {
    if (!opts || opts.ready) return "ready";
    if (opts.loading && (Number(opts.rounds) || 0) < WAIT_ROUNDS) return "wait";
    return "broken";
  }

  var api = {
    RATE_MAX: RATE_MAX,
    WAIT_MS: WAIT_MS,
    waitVerdict: waitVerdict,
    scrollTarget: scrollTarget,
    slideTime: slideTime,
    total: total,
    blockAt: blockAt,
    sourceTime: sourceTime,
    finalTime: finalTime,
    rate: rate,
    slower: slower,
    activeAt: activeAt,
    nextIndex: nextIndex,
    nextVideo: nextVideo,
    advance: advance,
    clock: clock,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.__qEditSeqCore = api;
})(typeof window !== "undefined" ? window : null);
