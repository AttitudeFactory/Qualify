/* `ui.edit_preview` (ED-01 m-25026605): the editor's live preview. Sent by
   `rx.call_script` every time «Arma tu video» mounts (`edit_preview_script()`): the first
   run installs the document listeners once; every run attaches an observer to each new
   preview (`window.__qEditPreview.attach()`). Nothing here decodes a frame for the
   server: the browser plays, and only the video's length and size go back (the hidden
   `[data-edit-duration-trigger]`).

   A preview is `[data-edit-preview]` with, as attributes React renders from the state:
   `data-edit-key` (the source's key), `data-edit-start` / `data-edit-end` (the stretch,
   seconds of the source), `data-edit-speed` (the real speed: the time shown is the final
   video's), `data-edit-rate` (the playbackRate the browser can use, ≤ 16),
   `data-edit-focus` («start» / «end»: the handle «Cortar» moves) and `data-edit-play`
   (changes when a handle is released: the stretch plays). Its state is
   `data-edit-state` — idle | playing | broken — an attribute React never renders.

   - The video plays only the stretch: at its end it goes back to the start (a loop).
   - A handle moving pauses it and shows the frame at that handle; released, the stretch
     plays from its start.
   - ▶ changes its label («Ver…» / «Pausar…»), never `aria-pressed` too (one
     announcement); the sound toggle is `aria-pressed`. The effect layers loop muted.
   - One sound on the page: the preview pauses any other playing video when it plays.
   - The length and size are reported on EVERY `loadedmetadata` (a reset of the editor
     or a reconnected websocket needs them again). A video that cannot be played — an
     `error`, a length that is not a finite number above 0, or no length after 15 s
     while the network is no longer loading it — goes `broken` and is reported with a
     negative length, so «Cortar» never waits forever. A length that arrives later
     brings it back to `idle` and is reported.
   - An effect layer that fails is hidden, silently.
   - Each preview has its own MutationObserver (its attributes and its video's `src`),
     never one on the whole document. */
(function () {
  "use strict";
  if (window.__qEditPreview) {
    window.__qEditPreview.attach();
    return;
  }

  var HOST = "[data-edit-preview]";
  var SLACK = 0.08;
  var WAIT_MS = 15000; // no length by then: the video cannot be played here

  function num(value, fallback) {
    var n = parseFloat(value);
    return isFinite(n) ? n : fallback;
  }

  function hostOf(el) {
    return el && el.closest ? el.closest(HOST) : null;
  }

  function videoOf(host) {
    return host.querySelector("video[data-edit-video]");
  }

  function span(host) {
    var start = Math.max(num(host.getAttribute("data-edit-start"), 0), 0);
    var end = num(host.getAttribute("data-edit-end"), 0);
    return { start: start, end: end > start ? end : NaN };
  }

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

  function writeTime(host) {
    var out = host.querySelector("[data-edit-time]");
    var video = videoOf(host);
    if (!out) return;
    var s = span(host);
    var speed = Math.max(num(host.getAttribute("data-edit-speed"), 1), 0.01);
    var whole = video && isFinite(video.duration) ? video.duration : 0;
    var total = isNaN(s.end) ? whole : s.end - s.start;
    var at = video ? Math.min(Math.max(video.currentTime - s.start, 0), total) : 0;
    var text = clock(at / speed) + " de " + clock(total / speed);
    if (out.textContent !== text) out.textContent = text;
  }

  function setState(host, state) {
    host.setAttribute("data-edit-state", state);
    var button = host.querySelector("[data-edit-play-btn]");
    if (!button) return;
    if (!button.__qPlayLabel) button.__qPlayLabel = button.getAttribute("aria-label") || "";
    var label =
      state === "playing" ? button.getAttribute("data-pause-label") || "" : button.__qPlayLabel;
    if (button.getAttribute("aria-label") !== label) {
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    }
  }

  function seek(video, at) {
    try {
      video.currentTime = at;
    } catch (err) {
      /* not seekable yet: `loadedmetadata` seeks */
    }
  }

  function applyRate(host) {
    var video = videoOf(host);
    if (!video) return;
    var rate = Math.min(Math.max(num(host.getAttribute("data-edit-rate"), 1), 0.0625), 16);
    if (video.playbackRate !== rate) video.playbackRate = rate;
  }

  /* Hand `{key, seconds, width, height}` to the screen through the hidden button. */
  function report(host, seconds, width, height) {
    var key = host.getAttribute("data-edit-key") || "";
    var trigger = host.querySelector("[data-edit-duration-trigger]");
    if (!key || !trigger) return;
    window.__qEditPreviewReport = {
      key: key,
      seconds: seconds,
      width: width || 0,
      height: height || 0,
    };
    trigger.click();
  }

  /* What the browser knows of the video: its length and size — or, when the length is
     not a finite number above 0, a failure (a negative length), never a null. */
  function reportLength(host, video) {
    var seconds = video ? video.duration : NaN;
    if (!isFinite(seconds) || seconds <= 0) {
      breakHost(host);
      return;
    }
    report(host, Math.round(seconds * 100) / 100, video.videoWidth, video.videoHeight);
  }

  function stopWaiting(host) {
    if (host.__qEditWait) {
      window.clearTimeout(host.__qEditWait);
      host.__qEditWait = 0;
    }
  }

  function breakHost(host) {
    stopWaiting(host);
    var video = videoOf(host);
    if (video && !video.paused) video.pause();
    if (host.getAttribute("data-edit-state") === "broken") return;
    setState(host, "broken");
    report(host, -1, 0, 0);
  }

  /* A new `src`: wait for its length, at most `WAIT_MS` — but never break a video the
     network is still bringing (a slow connection): wait again instead. */
  function waitFor(host) {
    stopWaiting(host);
    var video = videoOf(host);
    if (!video || !video.getAttribute("src") || video.readyState >= 1) return;
    host.__qEditWait = window.setTimeout(function () {
      host.__qEditWait = 0;
      var now = videoOf(host);
      if (!now || now.readyState >= 1) return;
      if (now.networkState === now.NETWORK_LOADING) waitFor(host);
      else breakHost(host);
    }, WAIT_MS);
  }

  function play(host) {
    var video = videoOf(host);
    if (!video || host.getAttribute("data-edit-state") === "broken") return;
    var s = span(host);
    if (
      video.currentTime < s.start - SLACK ||
      (!isNaN(s.end) && video.currentTime >= s.end - SLACK)
    ) {
      seek(video, s.start);
    }
    applyRate(host);
    var sound = host.querySelector("[data-edit-sound]");
    video.muted = !(sound && sound.getAttribute("aria-pressed") === "true");
    var started = video.play();
    if (started && started.catch) {
      started.catch(function (err) {
        if (err && (err.name === "AbortError" || err.name === "NotAllowedError")) {
          setState(host, "idle");
          return;
        }
        breakHost(host);
      });
    }
  }

  function pause(host) {
    var video = videoOf(host);
    if (video && !video.paused) video.pause();
    if (host.getAttribute("data-edit-state") === "playing") setState(host, "idle");
  }

  /* The attributes moved (a handle, the speed, a new video): show the right frame. */
  function sync(host) {
    var video = videoOf(host);
    var last = host.__qEditLast || {};
    var now = {
      start: host.getAttribute("data-edit-start"),
      end: host.getAttribute("data-edit-end"),
      focus: host.getAttribute("data-edit-focus") || "",
      play: host.getAttribute("data-edit-play"),
      src: video ? video.getAttribute("src") || "" : "",
      key: host.getAttribute("data-edit-key") || "",
      known: host.getAttribute("data-edit-known") || "",
      pending: host.getAttribute("data-edit-pending") || "",
    };
    host.__qEditLast = now;
    if (now.src !== last.src) {
      host.removeAttribute("data-edit-state");
      setState(host, "idle");
      waitFor(host);
    }
    // an R2 video with no playable address yet (just picked, or after a reload): ask
    // the screen to mint one, once per video
    if (now.pending === "true" && (now.pending !== last.pending || now.key !== last.key)) {
      var resolve = host.querySelector("[data-edit-resolve-trigger]");
      if (resolve) resolve.click();
    }
    applyRate(host);
    // the screen forgot the length (a reset, a reconnected websocket) or the key changed:
    // tell it again from what the browser already knows
    if (
      video &&
      video.readyState >= 1 &&
      host.getAttribute("data-edit-state") !== "broken" &&
      now.known !== "true" &&
      (now.known !== last.known || now.key !== last.key)
    ) {
      reportLength(host, video);
    }
    if (video && video.readyState >= 1) {
      var s = span(host);
      if (last.play !== undefined && now.play !== last.play) {
        play(host);
      } else if (now.start !== last.start || now.end !== last.end) {
        pause(host);
        var at =
          now.focus === "end" && !isNaN(s.end) ? Math.max(s.end - 0.05, s.start) : s.start;
        seek(video, at);
      }
    }
    writeTime(host);
  }

  function attachOne(host) {
    if (host.__qEditObserver) return;
    var pending = false;
    host.__qEditObserver = new MutationObserver(function () {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(function () {
        pending = false;
        if (host.isConnected) sync(host);
        else {
          stopWaiting(host);
          host.__qEditObserver.disconnect();
        }
      });
    });
    // the host's own attributes, and its subtree for the `<video>` that comes and goes
    host.__qEditObserver.observe(host, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: [
        "data-edit-start",
        "data-edit-end",
        "data-edit-play",
        "data-edit-rate",
        "data-edit-speed",
        "data-edit-focus",
        "data-edit-key",
        "data-edit-known",
        "data-edit-pending",
        "src",
      ],
    });
    sync(host);
    var video = videoOf(host);
    // already loaded before the script ran: report now
    if (video && video.readyState >= 1) reportLength(host, video);
  }

  function attach() {
    Array.prototype.forEach.call(document.querySelectorAll(HOST), attachOne);
    Array.prototype.forEach.call(document.querySelectorAll(SEQ_HOST), seqAttach);
  }

  /* ── Sequence mode (ED-01b m-25029106) ──────────────────────────────────────────────
     A `[data-edit-seq-host]` plays a whole video: the blocks of `data-edit-seq` (the JSON
     of `Qualify/edit_sequence.py`) in order, on ONE clock — the final video's time `t`.
     The single-stretch preview above (`[data-edit-preview]`, the Clip editor on main) is
     untouched: a sequence host never carries `data-edit-preview`.

     - Two `<video>` (`data-edit-seq-video` "a"/"b") take turns: the one not shown already
       holds the NEXT video block, seeked to its start, so a cut does not flash black.
     - A photo shows its picture for its `dur`; a block with no address, or one whose video
       failed, shows its picture (or a card with its name) for its time — and, if it
       failed, `PREVIEW_BROKEN` — and the sequence goes on.
     - Texts and effects (`[data-seq-start]`/`[data-seq-end]`) get `data-on` while
       `start <= t < end`.
     - The time is written every frame (`requestAnimationFrame`) into the preview's
       «{t} de {total}» and the linked timeline's playhead (the `[data-q-timeline]` in the
       same `[data-edit-sync]` box): DOM only. The screen hears the time only on a pause
       and after a seek (the hidden `[data-edit-seq-time-trigger]`), and each source's
       length and size on its `loadedmetadata` (the same report as above).
     - Moving the timeline's playhead (its input, or sliding the tracks on a phone) seeks.
     - API: `window.__qEditPreview.seq.goTo(host, t)`, `.showHandle(host, index, edge)`,
       `.playFrom(host, t)`, `.pause(host)`, `.time(host)`. */
  var SEQ_HOST = "[data-edit-seq-host]";
  var SEQ_END_SLACK = 0.04; // a frame or so before a block's end, the next one starts
  var SEQ_REPORT_MS = 250; // a seek is reported once the playhead rests this long

  function core() {
    return window.__qEditSeqCore;
  }

  function seqState(host) {
    if (!host.__qSeq) host.__qSeq = { seq: null, raw: "", t: 0, idx: -1, playing: false };
    return host.__qSeq;
  }

  function seqVideos(host) {
    return {
      a: host.querySelector('video[data-edit-seq-video="a"]'),
      b: host.querySelector('video[data-edit-seq-video="b"]'),
    };
  }

  function seqLoad(host) {
    var st = seqState(host);
    var raw = host.getAttribute("data-edit-seq") || "";
    if (raw === st.raw) return false;
    st.raw = raw;
    try {
      st.seq = JSON.parse(raw || "{}");
    } catch (err) {
      st.seq = { blocks: [], texts: [], effects: [] };
    }
    st.broken = st.broken || {};
    st.t = Math.min(st.t, core().total(st.seq));
    return true;
  }

  function seqActiveVideo(host) {
    var st = seqState(host);
    var v = seqVideos(host);
    return st.active === "b" ? v.b : v.a;
  }

  function seqIdleVideo(host) {
    var st = seqState(host);
    var v = seqVideos(host);
    return st.active === "b" ? v.a : v.b;
  }

  function setSrc(video, url) {
    if (!video) return;
    var now = video.getAttribute("src") || "";
    if (now === url) return;
    if (url) {
      video.setAttribute("src", url);
      video.load();
    } else {
      video.removeAttribute("src");
      video.load();
    }
  }

  /* The timeline linked to this preview (same `[data-edit-sync]` box), or null. */
  function seqTimeline(host) {
    var box = host.closest("[data-edit-sync]");
    return box ? box.querySelector("[data-q-timeline]") : null;
  }

  /* The timeline's playhead follows the clock (DOM only: no input event, no Reflex). */
  function seqPaintTimeline(host, t) {
    var root = seqTimeline(host);
    if (!root) return;
    var scrub = root.querySelector(".q-tl__scrub");
    var canvas = root.querySelector(".q-tl__canvas");
    var label = root.querySelector(".q-tl__clock");
    var total = core().total(seqState(host).seq);
    var text = core().clock(t) + " de " + core().clock(total);
    if (scrub) {
      scrub.value = String(t);
      scrub.setAttribute("aria-valuetext", text);
    }
    if (label && label.textContent !== text) label.textContent = text;
    if (canvas) canvas.style.setProperty("--tl-t", String(t));
    var scroller = seqPhoneScroller(root);
    if (scroller) {
      // the owner's own seek never writes the tracks back (`scrollTarget`)
      var left = core().scrollTarget({
        owner: !!seqState(host).owner,
        t: t,
        px: seqPx(root),
        current: scroller.scrollLeft,
        max: scroller.scrollWidth - scroller.clientWidth,
      });
      if (left >= 0) scroller.scrollLeft = left;
    }
  }

  /* The timeline's scroller when it is in phone mode (the tracks slide), else null. */
  function seqPhoneScroller(root) {
    var frame = root && root.querySelector(".q-tl__frame");
    var scroller = root && root.querySelector(".q-tl__scroller");
    if (!frame || !scroller) return null;
    var phone = getComputedStyle(frame).getPropertyValue("--tl-mode").trim() !== "desk";
    return phone ? scroller : null;
  }

  function seqPx(root) {
    return parseFloat(getComputedStyle(root).getPropertyValue("--tl-px")) || 44;
  }

  function seqPaint(host) {
    var st = seqState(host);
    var c = core();
    var total = c.total(st.seq);
    var out = host.querySelector("[data-edit-seq-time]");
    var text = c.clock(st.t) + " de " + c.clock(total);
    if (out && out.textContent !== text) out.textContent = text;
    var texts = c.activeAt(st.seq.texts, st.t);
    var effects = c.activeAt(st.seq.effects, st.t);
    Array.prototype.forEach.call(host.querySelectorAll("[data-seq-text]"), function (el) {
      var on = texts.indexOf(parseInt(el.getAttribute("data-seq-text"), 10)) >= 0;
      if (on !== el.hasAttribute("data-on")) el.toggleAttribute("data-on", on);
    });
    Array.prototype.forEach.call(host.querySelectorAll("[data-seq-effect]"), function (el) {
      var on = effects.indexOf(parseInt(el.getAttribute("data-seq-effect"), 10)) >= 0;
      if (on !== el.hasAttribute("data-on")) el.toggleAttribute("data-on", on);
      // an effect loops only while it shows AND the sequence plays
      if (on && st.playing) {
        if (el.paused && el.play) el.play().catch(function () {});
      } else if (!el.paused) el.pause();
    });
    seqPaintTimeline(host, st.t);
  }

  /* Show what block `idx` shows at `st.t`: its video (seeked), picture or card. */
  function seqShow(host, play) {
    var st = seqState(host);
    var c = core();
    var blocks = st.seq.blocks || [];
    st.idx = c.blockAt(st.seq, st.t);
    var block = blocks[st.idx];
    var v = seqVideos(host);
    var photo = host.querySelector("[data-edit-seq-photo]");
    var card = host.querySelector("[data-edit-seq-card]");
    var brokenText = host.querySelector("[data-edit-seq-broken]");
    // the picture a timed block shows (a photo's own, else the poster) — none once it
    // failed to load: then the card with the name
    var pic = block ? (block.kind === "photo" ? block.url || block.poster : block.poster) : "";
    if (pic && st.badPics && st.badPics[pic]) pic = "";
    var mode = "card";
    if (block && block.kind === "video" && block.url && !st.broken[block.key]) mode = "video";
    else if (pic) mode = "photo";
    st.mode = mode;
    if (mode === "video") {
      var active = seqActiveVideo(host);
      var idle = seqIdleVideo(host);
      // the next video is already in the idle player: take turns, no black frame
      if ((idle.getAttribute("src") || "") === block.url && active.getAttribute("src") !== block.url) {
        st.active = st.active === "b" ? "a" : "b";
        active = idle;
      }
      setSrc(active, block.url);
      active.setAttribute("data-rotate", String(block.rotate || 0));
      active.playbackRate = c.rate(block.speed);
      var want = c.sourceTime(block, st.t);
      if (active.readyState >= 1 && Math.abs(active.currentTime - want) > SLACK) {
        try {
          active.currentTime = want;
        } catch (err) {
          /* seeks on loadedmetadata */
        }
      }
      active.__qSeqWant = want;
      var sound = host.querySelector("[data-edit-sound]");
      active.muted = !(sound && sound.getAttribute("aria-pressed") === "true");
      [v.a, v.b].forEach(function (el) {
        if (!el) return;
        var on = el === active;
        el.toggleAttribute("data-on", on);
        if (!on && !el.paused) el.pause();
      });
      if (play) {
        var started = active.play();
        if (started && started.catch) started.catch(function () {});
      } else if (!active.paused) active.pause();
      // preload the next video in the other player, seeked to its start
      var j = c.nextVideo(st.seq, st.idx, st.broken);
      var other = active === v.a ? v.b : v.a;
      if (j >= 0 && j !== st.idx && blocks[j].url !== block.url) {
        setSrc(other, blocks[j].url);
        other.__qSeqWant = blocks[j].src_start;
        if (other.readyState >= 1) {
          try {
            other.currentTime = blocks[j].src_start;
          } catch (err) {
            /* seeks on loadedmetadata */
          }
        }
      }
    } else {
      [v.a, v.b].forEach(function (el) {
        if (el) {
          el.removeAttribute("data-on");
          if (!el.paused) el.pause();
        }
      });
    }
    if (photo) {
      if (mode === "photo") {
        if (photo.getAttribute("src") !== pic) photo.setAttribute("src", pic);
        photo.setAttribute("data-rotate", String((block && block.rotate) || 0));
        photo.setAttribute("data-on", "");
      } else photo.removeAttribute("data-on");
    }
    if (card) {
      var label = block ? block.label || "" : "";
      if (card.textContent !== label) card.textContent = label;
      card.toggleAttribute("data-on", mode === "card");
    }
    if (brokenText) {
      brokenText.toggleAttribute("data-on", !!(block && st.broken[block.key]));
    }
    host.setAttribute("data-edit-state", st.playing ? "playing" : "idle");
    // only while playing: paused, some phones never fetch (Low Power, Data Saver)
    seqWait(host, st.playing && mode === "video" ? block.url : "");
    seqPaint(host);
  }

  /* A video block whose `<video>` never loads nor fails would freeze the clock (it only
     moves with the video): wait `WAIT_MS` for a frame — again while the network is
     still bringing it, up to `core.waitVerdict`'s rounds — then treat it as a failed one.
     `url` "" (paused, or no video shown) or a video with a frame: no wait. */
  function seqWait(host, url) {
    var st = seqState(host);
    var video = url ? seqActiveVideo(host) : null;
    if (!video || video.readyState >= 2) {
      seqStopWaiting(st);
      return;
    }
    if (st.waitUrl === url && st.waitTimer) return; // already waiting for this one
    seqStopWaiting(st);
    st.waitUrl = url;
    st.waitRounds = 0;
    seqWaitRound(host);
  }

  function seqWaitRound(host) {
    var st = seqState(host);
    st.waitTimer = window.setTimeout(function () {
      st.waitTimer = 0;
      st.waitRounds += 1;
      var url = st.waitUrl;
      var video = seqActiveVideo(host);
      if (!host.isConnected || !video || (video.getAttribute("src") || "") !== url) return;
      var verdict = core().waitVerdict({
        ready: video.readyState >= 2,
        loading: video.networkState === video.NETWORK_LOADING,
        rounds: st.waitRounds,
      });
      if (verdict === "wait") seqWaitRound(host);
      else if (verdict === "broken") seqBreakUrl(host, url, video);
    }, core().WAIT_MS);
  }

  function seqStopWaiting(st) {
    if (st.waitTimer) window.clearTimeout(st.waitTimer);
    st.waitTimer = 0;
    st.waitUrl = "";
  }

  /* The blocks of `url` cannot play here: each is reported once (-1, like the single
     preview), the player lets go of the address, and the failed blocks become timed
     ones (their picture or card, and the notice) — the sequence keeps going. */
  function seqBreakUrl(host, url, video) {
    var st = seqState(host);
    (st.seq.blocks || []).forEach(function (b) {
      if (b.url === url && !st.broken[b.key]) {
        st.broken[b.key] = true;
        var trigger = host.querySelector("[data-edit-duration-trigger]");
        if (trigger) {
          window.__qEditPreviewReport = { key: b.key, seconds: -1, width: 0, height: 0 };
          trigger.click();
        }
      }
    });
    if (video && (video.getAttribute("src") || "") === url) setSrc(video, "");
    seqShow(host, st.playing);
  }

  function seqReportTime(host, reason) {
    var trigger = host.querySelector("[data-edit-seq-time-trigger]");
    if (!trigger) return;
    window.__qEditSeqTime = { t: Math.round(seqState(host).t * 100) / 100, reason: reason };
    trigger.click();
  }

  function seqTick(host) {
    var st = seqState(host);
    if (!st.playing || !host.isConnected) {
      st.raf = 0;
      return;
    }
    var c = core();
    var now = performance.now();
    var dt = st.wall ? (now - st.wall) / 1000 : 0;
    st.wall = now;
    var block = (st.seq.blocks || [])[st.idx];
    if (!block) {
      st.raf = 0;
      return;
    }
    if (st.mode === "video") {
      var video = seqActiveVideo(host);
      if (video && video.ended) st.t = block.out_end; // the source ended before its stretch
      else if (video && video.readyState >= 2) st.t = c.finalTime(block, video.currentTime);
    } else {
      st.t = Math.min(st.t + dt, block.out_end);
    }
    if (st.t >= block.out_end - SEQ_END_SLACK) {
      var step = c.advance(st.seq, block.out_end, 0);
      st.t = step.t; // the next block's start, or 0:00 after the last
      seqShow(host, true);
    } else {
      seqPaint(host);
    }
    st.raf = window.requestAnimationFrame(function () {
      seqTick(host);
    });
  }

  function seqPlay(host) {
    var st = seqState(host);
    if (!st.seq || !(st.seq.blocks || []).length) return;
    // one sound on the page: whatever else plays stops
    Array.prototype.forEach.call(document.querySelectorAll("video"), function (other) {
      if (!host.contains(other) && !other.paused && !other.hasAttribute("data-edit-effect")) {
        other.pause();
      }
    });
    st.playing = true;
    st.wall = 0;
    if (st.t >= core().total(st.seq) - SEQ_END_SLACK) st.t = 0;
    seqShow(host, true);
    seqLabel(host);
    if (!st.raf) {
      st.raf = window.requestAnimationFrame(function () {
        seqTick(host);
      });
    }
  }

  function seqPause(host, quiet) {
    var st = seqState(host);
    var was = st.playing;
    st.playing = false;
    var video = seqActiveVideo(host);
    seqStopWaiting(st);
    if (video && !video.paused) video.pause();
    Array.prototype.forEach.call(host.querySelectorAll("[data-seq-effect]"), function (el) {
      if (!el.paused) el.pause();
    });
    host.setAttribute("data-edit-state", "idle");
    seqLabel(host);
    if (was && !quiet) seqReportTime(host, "pause");
  }

  function seqLabel(host) {
    var button = host.querySelector("[data-edit-play-btn]");
    if (!button) return;
    if (!button.__qPlayLabel) button.__qPlayLabel = button.getAttribute("aria-label") || "";
    var label = seqState(host).playing
      ? button.getAttribute("data-pause-label") || ""
      : button.__qPlayLabel;
    if (button.getAttribute("aria-label") !== label) {
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    }
  }

  /* The sound button says what it does next: «Activar sonido» while muted, its
     `data-mute-label` («Quitar sonido») while the sound is on — like ▶/❚❚. */
  function seqSoundLabel(button, on) {
    if (!button.__qSoundLabel) button.__qSoundLabel = button.getAttribute("aria-label") || "";
    var label = on ? button.getAttribute("data-mute-label") || "" : button.__qSoundLabel;
    if (label && button.getAttribute("aria-label") !== label) {
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    }
  }

  /* «ir a t»: show the frame at `t`; playing goes on playing from there. `owner`: the
     owner moved the timeline (slide, its input, ←/→, the ruler), so the tracks are
     already there and are not scrolled back (only for this call: no flag survives it). */
  function seqGoTo(host, t, owner) {
    var st = seqState(host);
    seqLoad(host);
    var total = core().total(st.seq);
    st.t = Math.min(Math.max(Number(t) || 0, 0), Math.max(total - 0.001, 0));
    st.wall = 0;
    st.owner = !!owner;
    try {
      seqShow(host, st.playing);
    } finally {
      st.owner = false;
    }
    window.clearTimeout(st.seekTimer);
    st.seekTimer = window.setTimeout(function () {
      seqReportTime(host, "seek");
    }, SEQ_REPORT_MS);
  }

  /* «mostrar el cuadro del tirador»: block `index`'s first or last frame, paused. */
  function seqShowHandle(host, index, edge) {
    var st = seqState(host);
    seqLoad(host);
    var block = (st.seq.blocks || [])[index];
    if (!block) return;
    seqPause(host, true);
    seqGoTo(host, edge === "end" ? Math.max(block.out_end - 0.05, block.out_start) : block.out_start);
  }

  /* «reproducir desde t». */
  function seqPlayFrom(host, t) {
    seqGoTo(host, t);
    seqPlay(host);
  }

  function seqAttach(host) {
    seqLoad(host);
    if (host.__qSeqObserver) {
      seqShow(host, seqState(host).playing);
      return;
    }
    host.__qSeqObserver = new MutationObserver(function () {
      if (!host.isConnected) {
        seqPause(host, true);
        host.__qSeqObserver.disconnect();
        return;
      }
      if (seqLoad(host)) seqShow(host, seqState(host).playing);
    });
    host.__qSeqObserver.observe(host, { attributes: true, attributeFilter: ["data-edit-seq"] });
    seqShow(host, false);
  }

  function seqHostOf(el) {
    return el && el.closest ? el.closest(SEQ_HOST) : null;
  }

  function seqSyncedHost(root) {
    var box = root && root.closest ? root.closest("[data-edit-sync]") : null;
    return box ? box.querySelector(SEQ_HOST) : null;
  }

  // ▶ / ❚❚ and the sound of a sequence preview
  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target || !target.closest) return;
    var button = target.closest("[data-edit-play-btn], [data-edit-sound]");
    var host = seqHostOf(button);
    if (!button || !host) return;
    e.preventDefault();
    if (button.hasAttribute("data-edit-sound")) {
      var on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", on ? "true" : "false");
      seqSoundLabel(button, on);
      var video = seqActiveVideo(host);
      if (video) video.muted = !on;
      return;
    }
    if (seqState(host).playing) seqPause(host);
    else seqPlay(host);
  });

  // the timeline's playhead moved by the owner (its input): seek
  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("q-tl__scrub")) return;
    var host = seqSyncedHost(el.closest("[data-q-timeline]"));
    if (host) seqGoTo(host, parseFloat(el.value) || 0, true);
  });

  // On a phone the owner slides the tracks (or taps the ruler, which slides them): seek
  // to exactly where they rest. A scroll that leaves them where the clock put them is the
  // clock's own (`slideTime`). While playing, the owner's slide pauses (quietly: the seek
  // is reported) — the finger wins over the clock.
  document.addEventListener(
    "scroll",
    function (e) {
      var el = e.target;
      if (!el || !el.classList || !el.classList.contains("q-tl__scroller")) return;
      var root = el.closest("[data-q-timeline]");
      var host = seqSyncedHost(root);
      if (!host || seqPhoneScroller(root) !== el) return;
      var st = seqState(host);
      if (!st.seq) return;
      var t = core().slideTime({
        left: el.scrollLeft,
        t: st.t,
        px: seqPx(root),
        total: core().total(st.seq),
        max: el.scrollWidth - el.clientWidth,
      });
      if (t < 0) return;
      if (st.playing) seqPause(host, true);
      st.slideTo = t;
      // after timeline.js's own listener has written its ½ s value: ours (exact) is last
      if (!st.slideRaf) {
        st.slideRaf = window.requestAnimationFrame(function () {
          st.slideRaf = 0;
          seqGoTo(host, st.slideTo, true);
        });
      }
    },
    true
  );

  // A finger (or the wheel) on the phone's tracks while playing: pause first, so the clock
  // stops scrolling them under the finger.
  function seqHoldTracks(e) {
    var el = e.target;
    var scroller = el && el.closest ? el.closest(".q-tl__scroller") : null;
    if (!scroller) return;
    var root = scroller.closest("[data-q-timeline]");
    var host = seqSyncedHost(root);
    if (!host || seqPhoneScroller(root) !== scroller) return;
    if (seqState(host).playing) seqPause(host, true);
  }
  ["pointerdown", "touchstart", "wheel"].forEach(function (type) {
    document.addEventListener(type, seqHoldTracks, { capture: true, passive: true });
  });

  function seqVideoHost(video) {
    return video && video.hasAttribute && video.hasAttribute("data-edit-seq-video")
      ? seqHostOf(video)
      : null;
  }

  document.addEventListener(
    "loadedmetadata",
    function (e) {
      var video = e.target;
      var host = seqVideoHost(video);
      if (!host) return;
      var st = seqState(host);
      if (video.__qSeqWant !== undefined) {
        try {
          video.currentTime = video.__qSeqWant;
        } catch (err) {
          /* nothing */
        }
      }
      // each source's length and size, through the single preview's report
      var block = (st.seq.blocks || []).filter(function (b) {
        return b.url === video.getAttribute("src");
      })[0];
      var trigger = host.querySelector("[data-edit-duration-trigger]");
      if (block && trigger && isFinite(video.duration) && video.duration > 0) {
        window.__qEditPreviewReport = {
          key: block.key,
          seconds: Math.round(video.duration * 100) / 100,
          width: video.videoWidth || 0,
          height: video.videoHeight || 0,
        };
        trigger.click();
      }
    },
    true
  );

  document.addEventListener(
    "error",
    function (e) {
      var video = e.target;
      var host = seqVideoHost(video);
      if (!host || !video.getAttribute("src")) return;
      // the failed block becomes a timed one: the sequence keeps going
      seqBreakUrl(host, video.getAttribute("src"), video);
    },
    true
  );

  // A photo that does not load: no broken-image icon — its block shows the card with
  // its name (the picture is remembered as bad, so it is not asked for again).
  document.addEventListener(
    "error",
    function (e) {
      var img = e.target;
      if (!img || !img.hasAttribute || !img.hasAttribute("data-edit-seq-photo")) return;
      var host = seqHostOf(img);
      var src = img.getAttribute("src");
      if (!host || !src) return;
      var st = seqState(host);
      st.badPics = st.badPics || {};
      st.badPics[src] = true;
      img.removeAttribute("data-on");
      if (st.seq) seqShow(host, st.playing);
    },
    true
  );

  // Something else paused the sequence's video (another video on the page started, the
  // system took the sound): the clock stops with it, or it would wait on a still frame.
  // Not ours: our pause sets `playing` false first, a switch pauses the player that is
  // no longer shown, a new address plays again at once, and a source's end moves on.
  document.addEventListener(
    "pause",
    function (e) {
      var video = e.target;
      var host = seqVideoHost(video);
      if (!host) return;
      var st = seqState(host);
      if (!st.playing || st.mode !== "video" || video !== seqActiveVideo(host)) return;
      if (!video.paused || video.ended) return;
      var block = (st.seq.blocks || [])[st.idx];
      if (!block || (video.getAttribute("src") || "") !== block.url) return;
      seqPause(host);
    },
    true
  );

  window.__qEditPreview = {
    attach: attach,
    seq: {
      goTo: seqGoTo,
      showHandle: seqShowHandle,
      playFrom: seqPlayFrom,
      pause: seqPause,
      time: function (host) {
        return seqState(host).t;
      },
    },
  };
  attach();

  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target || !target.closest) return;
    var button = target.closest("[data-edit-play-btn], [data-edit-sound]");
    var host = hostOf(button);
    if (!button || !host) return;
    e.preventDefault();
    if (button.hasAttribute("data-edit-sound")) {
      var on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", on ? "true" : "false");
      var video = videoOf(host);
      if (video) video.muted = !on;
      return;
    }
    if (host.getAttribute("data-edit-state") === "playing") pause(host);
    else play(host);
  });

  document.addEventListener(
    "loadedmetadata",
    function (e) {
      var video = e.target;
      if (!video || !video.hasAttribute || !video.hasAttribute("data-edit-video")) return;
      var host = hostOf(video);
      if (!host) return;
      stopWaiting(host);
      if (!isFinite(video.duration) || video.duration <= 0) {
        breakHost(host);
        return;
      }
      // a late length after the 15 s wait gave up: the preview comes back to life
      if (host.getAttribute("data-edit-state") === "broken") setState(host, "idle");
      seek(video, span(host).start);
      applyRate(host);
      writeTime(host);
      reportLength(host, video);
    },
    true
  );

  document.addEventListener(
    "timeupdate",
    function (e) {
      var video = e.target;
      if (!video || !video.hasAttribute || !video.hasAttribute("data-edit-video")) return;
      var host = hostOf(video);
      if (!host) return;
      if (host.getClientRects().length === 0) {
        pause(host);
        return;
      }
      var s = span(host);
      if (!video.paused && !isNaN(s.end) && video.currentTime >= s.end - SLACK) {
        seek(video, s.start);
      }
      writeTime(host);
    },
    true
  );

  document.addEventListener(
    "play",
    function (e) {
      var video = e.target;
      if (!video || video.tagName !== "VIDEO") return;
      if (video.hasAttribute("data-edit-effect")) return;
      var mine = video.hasAttribute("data-edit-video");
      Array.prototype.forEach.call(document.querySelectorAll("video"), function (other) {
        if (other === video || other.paused || other.hasAttribute("data-edit-effect")) return;
        if (mine || other.hasAttribute("data-edit-video")) other.pause();
      });
      if (mine) {
        var host = hostOf(video);
        if (host) setState(host, "playing");
      }
    },
    true
  );

  document.addEventListener(
    "pause",
    function (e) {
      var video = e.target;
      if (!video || !video.hasAttribute || !video.hasAttribute("data-edit-video")) return;
      var host = hostOf(video);
      if (host && host.getAttribute("data-edit-state") === "playing") setState(host, "idle");
    },
    true
  );

  document.addEventListener(
    "ended",
    function (e) {
      var video = e.target;
      if (!video || !video.hasAttribute || !video.hasAttribute("data-edit-video")) return;
      var host = hostOf(video);
      if (!host) return;
      seek(video, span(host).start);
      play(host);
    },
    true
  );

  document.addEventListener(
    "error",
    function (e) {
      var video = e.target;
      if (!video || video.tagName !== "VIDEO" || !video.getAttribute("src")) return;
      if (video.hasAttribute("data-edit-effect")) {
        video.setAttribute("data-edit-effect-off", "");
        return;
      }
      if (!video.hasAttribute("data-edit-video")) return;
      var host = hostOf(video);
      if (host) breakHost(host);
    },
    true
  );
})();
