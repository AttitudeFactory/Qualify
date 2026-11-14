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
  }

  window.__qEditPreview = { attach: attach };
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
