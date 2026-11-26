/* The preview-in-sequence's clock (ED-01b m-25029106), PURE: no DOM and no timers
   (but `measureLength`'s give-up, which a test can inject), so `node` tests it
   without a browser (`Qualify/test_edit_sequence_js.py`). The engine in
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

  /* «0:04», «0:04,5» — the time as the preview writes it, to the tenth with a half
     rounded up and a 60th second carried into the minute (59,96 → «1:00»): the same
     algorithm as Python's `editor_preview_contract.clock_text` (m-25129389). */
  function clock(seconds) {
    var tenths = Math.floor(Number((Math.max(seconds, 0) * 10).toFixed(6)) + 0.5);
    var minutes = Math.floor(tenths / 600);
    var rest = tenths % 600;
    var whole = Math.floor(rest / 10);
    var tenth = rest % 10;
    var text = minutes + ":" + (whole < 10 ? "0" : "") + whole;
    return tenth ? text + "," + tenth : text;
  }

  /* The clock as the screen shows it (ED-10 UX note): while playing, whole seconds
     (tenths that change every frame cannot be read); paused, to the tenth. */
  function clockShown(seconds, playing) {
    return clock(playing ? Math.floor(Math.max(Number(seconds) || 0, 0)) : seconds);
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

  /* ED-12 (m-25029107): a video's real length, also when `loadedmetadata` says
     Infinity or NaN — a file recorded with MediaRecorder carries no length in its
     header. The standard way out: seek far past the end (`currentTime = 1e101`), so the
     browser reads to the last frame; on `durationchange` / `timeupdate` the length is
     finite, and the video goes back to where it was. `done(seconds)` is called ONCE,
     with a finite length above 0 (at once when the browser already knows it). Returns
     true while it is measuring (a second call on the same video waits for the first).
     The measure is tied to the file it started on (ED-12 review): a new `src`
     (`emptied` / `loadstart`, or another address seen on the next event) stops it with
     no length and no seek back — the time it held belongs to the other file —; after
     `MEASURE_MS` with no finite length it gives up (`__qMeasuring` is let go and the
     video goes back). `video` is anything with `duration`, `currentTime`,
     `addEventListener` / `removeEventListener` and a `src` (or `getAttribute("src")`):
     node tests a stub, with `opts.setTimer(fn, ms)` / `opts.clearTimer(id)` in place of
     the global timers. `opts.backTo()`: where to go back to, when the player was asked
     for another time while it measured (default: where it was). `opts.after()`: called
     once the measure is over, however it ended (found, new file, gave up) — the seek
     past the end paused a player that was playing, and the preview starts it again
     (`resumeIfPlaying`). */
  var FAR_PAST_END = 1e101;
  var MEASURE_MS = 5000;

  function srcOf(video) {
    if (video && typeof video.getAttribute === "function") return video.getAttribute("src") || "";
    return (video && video.src) || "";
  }

  function measureLength(video, done, opts) {
    if (!video) return false;
    var known = Number(video.duration);
    if (isFinite(known) && known > 0) {
      done(known);
      return false;
    }
    if (video.__qMeasuring) return true;
    video.__qMeasuring = true;
    var o = opts || {};
    var setTimer = o.setTimer || (typeof setTimeout === "function" ? setTimeout : null);
    var clearTimer = o.clearTimer || (typeof clearTimeout === "function" ? clearTimeout : null);
    var src = srcOf(video);
    var back = Number(video.currentTime) || 0;
    var timer = null;
    function stop() {
      video.removeEventListener("durationchange", check);
      video.removeEventListener("timeupdate", check);
      video.removeEventListener("emptied", abandon);
      video.removeEventListener("loadstart", abandon);
      if (timer !== null && clearTimer) clearTimer(timer);
      timer = null;
      video.__qMeasuring = false;
    }
    function goBack() {
      if (srcOf(video) !== src) return; // another file: its time is not ours to move
      var to = o.backTo ? Number(o.backTo()) : back;
      try {
        video.currentTime = isFinite(to) && to >= 0 ? to : back;
      } catch (err) {
        /* it stays at the end: the next seek of the preview moves it */
      }
    }
    function finish() {
      if (o.after) o.after();
    }
    function abandon() {
      stop(); // a new file in the player: this measure is over, with no length
      finish();
    }
    function check() {
      if (srcOf(video) !== src) {
        abandon();
        return;
      }
      var length = Number(video.duration);
      if (!isFinite(length) || length <= 0) return; // still reading: wait
      stop();
      goBack();
      done(length);
      finish();
    }
    video.addEventListener("durationchange", check);
    video.addEventListener("timeupdate", check);
    video.addEventListener("emptied", abandon);
    video.addEventListener("loadstart", abandon);
    if (setTimer) {
      timer = setTimer(function () {
        timer = null;
        stop(); // never finite: give up — the block keeps the timeline's guess
        goBack();
        finish();
      }, MEASURE_MS);
      if (timer && typeof timer.unref === "function") timer.unref();
    }
    try {
      video.currentTime = FAR_PAST_END;
    } catch (err) {
      stop(); // not seekable: no length (the preview treats it as a timed block)
      return false;
    }
    return true;
  }

  /* ED-12 review: reaching the end (the seek to 1e101) pauses a playing player, and the
     sequence's `pause` listener lets it be (`ended`): once the measure is over, a player
     the sequence is `playing` — the owner did not pause it — plays again. Never while it
     measures, never at its real end. Whether `play()` was called. */
  function resumeIfPlaying(video, playing) {
    if (!video || !playing || !video.paused || video.ended || video.__qMeasuring) return false;
    var started = video.play();
    if (started && started.catch) started.catch(function () {});
    return true;
  }

  /* ED-13 (m-25029108): a text's look at final time `t` — the contract's motions, the
     same as `Qualify/editor_preview_contract.py` `text_frame` (a node test keeps them
     equal). `text`: a sequence text (`start`, `end`, `fade`, `motion_in`, `motion_out`,
     `text`). Returns {a: alpha 0-1, dy: share of the height it is lowered, s: scale,
     chars: letters shown (-1 = all)}. Alpha is linear; position and scale ease with
     1-(1-p)^3 in and p^3 out. Each animation takes `fade` at most a third of the time the
     text shows; «Letra por letra» lasts d = 0,06 s per character of the trimmed text (also
     a third at most), its box fading in over min(0,2 s, d). Its clock is the final video's
     (`video_pipeline.compose` + `text_overlay.LetterReveal`): the text's whitespace runs
     collapse to one space (`typedChars`, as the render does), the spaces a line break eats
     are not letters (`text.breaks`: how many line breaks the preview laid out), and letter
     i of those n appears at once at start + i·d/n, the first at start; `chars` counts
     letters, not characters of the text. `reduced` (prefers-reduced-motion): only the
     alpha, every character at once. */
  var SLIDE_FRACTION = 0.05;
  var ZOOM_FROM = 0.9;
  var TYPE_S_PER_CHAR = 0.06;
  var MOTION_MAX_SHARE = 1 / 3;

  function easeIn(p) {
    p = Math.min(Math.max(p, 0), 1);
    return 1 - Math.pow(1 - p, 3);
  }

  function easeOut(p) {
    p = Math.min(Math.max(p, 0), 1);
    return Math.pow(p, 3);
  }

  /* The characters «Letra por letra» types, as the render lays them: trimmed, every
     whitespace run one space, by code point (`layout.ts` `resolveVideoText`). */
  function typedChars(text) {
    return Array.from(String(text || "").trim().replace(/\s+/g, " "));
  }

  function round4(v) {
    return Math.round(v * 10000) / 10000;
  }

  function textFrame(text, t, reduced) {
    var visible = Math.max((text.end || 0) - (text.start || 0), 0);
    var into = t - (text.start || 0);
    if (into < 0 || into >= visible) return { a: 0, dy: 0, s: 1, chars: 0 };
    var fade = text.fade > 0 ? text.fade : 0.5;
    var share = visible * MOTION_MAX_SHARE;
    var mIn = text.motion_in || "fade";
    var mOut = text.motion_out || "none";
    var typing = mIn === "typewriter" && !reduced;
    // d: 0,06 s per character of the trimmed text, by code point (`compose.fade_in_seconds`)
    var count = Array.from(String(text.text || "").trim()).length;
    // n: the letters the render reports (`letter_boxes`): no space a line break eats
    var letters = Math.max(typedChars(text.text).length - Math.max(text.breaks | 0, 0), 1);
    var dIn = Math.max(typing ? Math.min(count * TYPE_S_PER_CHAR, share) : Math.min(fade, share), 0);
    var dOut = mOut === "none" ? 0 : Math.max(Math.min(fade, share), 0);
    var a = 1, dy = 0, s = 1, chars = -1;
    if (dIn > 0 && into < dIn) {
      var p = into / dIn;
      if (typing) {
        // letter i at start + i·d/n (`text_overlay._Motion`, the same slack)
        var step = dIn / letters;
        chars = step > 0 ? Math.min(letters, Math.floor(into / step + 1e-6) + 1) : letters;
        a = Math.min(into / Math.min(0.2, dIn), 1);
      } else {
        a = p;
        if (!reduced && mIn === "slide") dy = (1 - easeIn(p)) * SLIDE_FRACTION;
        if (!reduced && mIn === "zoom") s = ZOOM_FROM + (1 - ZOOM_FROM) * easeIn(p);
      }
    }
    if (dOut > 0 && into > visible - dOut) {
      var q = (into - (visible - dOut)) / dOut;
      a = Math.min(a, 1 - q);
      if (!reduced && mOut === "slide") dy = easeOut(q) * SLIDE_FRACTION;
      if (!reduced && mOut === "zoom") s = 1 - (1 - ZOOM_FROM) * easeOut(q);
    }
    return { a: round4(Math.min(Math.max(a, 0), 1)), dy: round4(dy), s: round4(s), chars: chars };
  }

  /* m-25114465 («la unión»): how a block that comes in with a transition (`join`
     "fade" / "wipe", `join_s` seconds, a wipe towards `join_dir`) is drawn at final
     time `t`, OVER the block before it — which goes on playing under it (`joinUnder`),
     as the video that comes out blends them (Deivid 2026-11-26: no cut before it).
     `{ a, clip }`: its opacity (0–1) and its CSS `clip-path` ("" = none). Outside its
     first `join_s` seconds, or with `reduced` (prefers-reduced-motion), it is just
     there: `{ a: 1, clip: "" }`. */
  function joinFrame(block, t, reduced) {
    var none = { a: 1, clip: "" };
    if (!block || reduced) return none;
    var len = Number(block.join_s) || 0;
    var into = t - (Number(block.out_start) || 0);
    if (!block.join || len <= 0 || into < 0 || into >= len) return none;
    var p = into / len;
    if (block.join === "fade") return { a: round4(p), clip: "" };
    if (block.join !== "wipe") return none;
    var hidden = round4((1 - p) * 100) + "%";
    // the new block slides in towards `join_dir`: «left» uncovers it from the right
    var sides = {
      left: "0 0 0 " + hidden,
      right: "0 " + hidden + " 0 0",
      up: hidden + " 0 0 0",
      down: "0 0 " + hidden + " 0",
    };
    return { a: 1, clip: "inset(" + (sides[block.join_dir] || sides.left) + ")" };
  }

  /* m-25114465 (Deivid's test, «quiero que la transición sea suave»): the block that
     goes on UNDER block `index` while it comes in (its `join_s` first seconds), as the
     final video blends them — the one before it, whose track span ends where `index`
     starts but whose picture keeps playing through the transition. -1 for a cut, the
     first block, outside the transition, or with `reduced` (a clean cut). */
  function joinUnder(seq, index, t, reduced) {
    var blocks = (seq && seq.blocks) || [];
    var block = blocks[index];
    if (reduced || !block || index < 1) return -1;
    var len = Number(block.join_s) || 0;
    var into = t - (Number(block.out_start) || 0);
    if (!block.join || len <= 0 || into < 0 || into >= len) return -1;
    return index - 1;
  }

  /* The source second the block UNDER shows at final time `t`: its stretch goes on past
     its span's end (`out_end`) into the seconds the transition overlaps — never past
     `src_end`. */
  function underSourceTime(block, t) {
    var speed = block.speed > 0 ? block.speed : 1;
    var at = block.src_start + Math.max(t - block.out_start, 0) * speed;
    return Math.min(at, block.src_end > block.src_start ? block.src_end : at);
  }

  var api = {
    joinFrame: joinFrame,
    joinUnder: joinUnder,
    underSourceTime: underSourceTime,
    textFrame: textFrame,
    typedChars: typedChars,
    RATE_MAX: RATE_MAX,
    FAR_PAST_END: FAR_PAST_END,
    MEASURE_MS: MEASURE_MS,
    measureLength: measureLength,
    resumeIfPlaying: resumeIfPlaying,
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
    clockShown: clockShown,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.__qEditSeqCore = api;
})(typeof window !== "undefined" ? window : null);
