/* `ui.clip_player` (m-24992893, m-24992894): a stretch of video played inside its own
   picture. Sent by `rx.call_script` when a screen with clips mounts
   (`clip_player_script()`); the guard keeps one set of document listeners.

   A clip is `[data-clip]` with `data-clip-src` (the address, `#t=start,end` included),
   `data-clip-start` / `data-clip-end` (seconds, "" = the whole video) and, optionally,
   `data-clip-broken-text` and `data-clip-renew`. Its state is `data-clip-state` —
   idle | loading | playing | broken — an attribute React never renders, so a server
   re-render (the result screen's poll) leaves a playing clip alone. The `<video>` gets
   its `src` only on ▶ (`preload="none"` until then), from `data-clip-src` as it is at
   that moment: a renewed address on a later render waits for the next ▶ instead of
   reloading the playing video.

   - ▶ starts it muted from the stretch's start: `loading` keeps the picture and a
     dimmed ▶ (a second tap cancels) until the video's `playing` event shows it. The
     sound toggle (`aria-pressed`) is per clip; tapping the playing frame pauses it and
     the picture comes back with ▶. The pause mark shows for a second when it starts
     (a phone has no hover to discover it).
   - At the stretch's end it stops and goes back to its start — no loop.
   - One video at a time on the page: a clip pauses every other video; any other video
     («Tu video completo») pauses the clips.
   - A clip whose picture is hidden (a folded list) or whose list starts a drag stops.
   - ←/→ on a clip's buttons never reach a list's own keyboard (moving a card).
   - A file that cannot be played: every clip of that file goes back to its picture
     WITHOUT ▶ (`broken`); `data-clip-broken-text` is written once per file in the
     nearest `[data-clip-notice]` (visible, a polite status), else said to screen
     readers only.
   - A `data-clip-renew` clip (short-lived addresses) does not break on its first
     error: it goes back to idle, presses the nearest `[data-clip-renew-trigger]` (the
     screen re-reads its addresses) and plays again as soon as its `data-clip-src`
     changes. A second error on the renewed address breaks it. */
(function () {
  "use strict";
  if (window.__qClipPlayer) return;
  window.__qClipPlayer = true;

  var HOST = "[data-clip]";
  var END_SLACK = 0.08; // seconds: a `timeupdate` lands ~250 ms apart
  var HINT_MS = 1000; // the pause mark shown when a clip starts
  var RENEW_WAIT_MS = 15000; // no new address came back: give up waiting
  var saidFiles = {};
  var region = null;

  function hostOf(el) {
    return el && el.closest ? el.closest(HOST) : null;
  }

  function videoOf(host) {
    return host.querySelector("video[data-clip-video]");
  }

  function isClipVideo(el) {
    return !!(el && el.hasAttribute && el.hasAttribute("data-clip-video"));
  }

  function num(value) {
    var n = parseFloat(value);
    return isFinite(n) ? n : NaN;
  }

  function stretch(host) {
    var start = num(host.getAttribute("data-clip-start"));
    var end = num(host.getAttribute("data-clip-end"));
    start = isNaN(start) ? 0 : start;
    return { start: start, end: !isNaN(end) && end > start ? end : NaN };
  }

  function stateOf(host) {
    return host.getAttribute("data-clip-state") || "idle";
  }

  function active(host) {
    var state = stateOf(host);
    return state === "playing" || state === "loading";
  }

  function fileOf(src) {
    return (src || "").split("#")[0];
  }

  function focusInside(host) {
    var el = document.activeElement;
    return el && el !== document.body && host.contains(el);
  }

  /* The nearest element matching `selector` around the clip (its own list first). */
  function nearest(host, selector) {
    var el = host.parentElement;
    while (el) {
      var found = el.querySelector(selector);
      if (found) return found;
      el = el.parentElement;
    }
    return null;
  }

  /* Back to the picture. The focus, when it was inside, goes to ▶ (or, with no ▶
     left, to the nearest focusable ancestor — a card). */
  function settle(host, state) {
    var hadFocus = focusInside(host);
    host.setAttribute("data-clip-state", state);
    host.removeAttribute("data-clip-hint");
    if (!hadFocus) return;
    var play = host.querySelector("[data-clip-play]");
    if (state === "idle" && play) {
      play.focus({ preventScroll: true });
      return;
    }
    var card = host.parentElement && host.parentElement.closest("[tabindex]");
    if (card) card.focus({ preventScroll: true });
  }

  function say(host, file) {
    var text = host.getAttribute("data-clip-broken-text") || "";
    if (!text) return;
    var notice = nearest(host, "[data-clip-notice]");
    if (notice) {
      // visible under the list (a polite status); written again only if it was cleared
      if (notice.textContent !== text) notice.textContent = text;
      return;
    }
    if (saidFiles[file]) return;
    saidFiles[file] = true;
    if (!region) {
      region = document.createElement("div");
      region.setAttribute("role", "status");
      region.style.cssText =
        "position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;" +
        "clip:rect(0,0,0,0);white-space:nowrap;border:0;padding:0";
      document.body.appendChild(region);
    }
    // set after insertion, so it is heard as a change
    window.setTimeout(function () {
      region.textContent = text;
    }, 50);
  }

  function breakFile(host) {
    var file = fileOf(host.getAttribute("data-clip-src"));
    Array.prototype.forEach.call(document.querySelectorAll(HOST), function (other) {
      if (other === host || (file && fileOf(other.getAttribute("data-clip-src")) === file)) {
        var video = videoOf(other);
        if (video && !video.paused) video.pause();
        settle(other, "broken");
      }
    });
    say(host, file);
  }

  /* A short-lived address failed: ask the screen for fresh ones, play again once this
     clip's address changes. False when it was already renewed (then it breaks). */
  function renew(host) {
    if (!host.hasAttribute("data-clip-renew")) return false;
    var failed = host.getAttribute("data-clip-src") || "";
    if (host.__qClipRenewed === failed) return false;
    var trigger = nearest(host, "[data-clip-renew-trigger]");
    if (!trigger) return false;
    host.__qClipRenewed = failed;
    var video = videoOf(host);
    if (video) {
      video.removeAttribute("src");
      video.load();
    }
    settle(host, "idle");
    var observer = new MutationObserver(function () {
      var now = host.getAttribute("data-clip-src") || "";
      if (now === failed) return;
      observer.disconnect();
      window.clearTimeout(timer);
      host.__qClipRenewed = now; // one renewal per failure: an error on `now` breaks
      if (host.isConnected) play(host);
    });
    var timer = window.setTimeout(function () {
      observer.disconnect();
    }, RENEW_WAIT_MS);
    observer.observe(host, { attributes: true, attributeFilter: ["data-clip-src"] });
    trigger.click();
    return true;
  }

  function fail(host) {
    if (!renew(host)) breakFile(host);
  }

  function pauseClip(host) {
    var video = videoOf(host);
    if (video && !video.paused) video.pause();
    if (active(host)) settle(host, "idle");
  }

  /* The address a clip may load: only http(s), resolved against the page — never a
     `javascript:`/`data:` URL or markup read back from the DOM. "" = unusable. */
  function safeSrc(raw) {
    if (!raw) return "";
    var parsed;
    try {
      parsed = new URL(raw, window.location.href);
    } catch (err) {
      return "";
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return parsed.href;
  }

  function play(host) {
    if (stateOf(host) === "broken") return;
    var video = videoOf(host);
    var src = safeSrc(host.getAttribute("data-clip-src"));
    if (!video || !src) {
      breakFile(host);
      return;
    }
    var span = stretch(host);
    if (video.getAttribute("src") !== src) {
      video.setAttribute("src", src);
    } else if (
      video.currentTime < span.start - END_SLACK ||
      (!isNaN(span.end) && video.currentTime >= span.end - END_SLACK)
    ) {
      try {
        video.currentTime = span.start;
      } catch (err) {
        /* not seekable yet: the fragment starts it there */
      }
    }
    var sound = host.querySelector("[data-clip-sound]");
    video.muted = !(sound && sound.getAttribute("aria-pressed") === "true");
    // the picture stays until the video really plays (`playing`)
    host.setAttribute("data-clip-state", "loading");
    var started = video.play();
    if (started && started.catch) {
      started.catch(function (err) {
        // paused before it started (another tap): not a broken file
        if (err && err.name === "AbortError") return;
        if (err && err.name === "NotAllowedError") {
          settle(host, "idle");
          return;
        }
        fail(host);
      });
    }
  }

  function toggleSound(host, button) {
    var on = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", on ? "true" : "false");
    var video = videoOf(host);
    if (video) video.muted = !on;
  }

  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target.closest) return;
    var button = target.closest("[data-clip-play], [data-clip-pause], [data-clip-sound]");
    var host = hostOf(button);
    if (!button || !host) return;
    e.preventDefault();
    e.stopPropagation();
    if (button.hasAttribute("data-clip-play")) {
      if (stateOf(host) === "loading") pauseClip(host); // a second tap cancels
      else play(host);
    } else if (button.hasAttribute("data-clip-pause")) pauseClip(host);
    else toggleSound(host, button);
  });

  /* ←/→ on a clip's button stay on it: a list's keyboard (moving a card) listens on the
     document, and the window's capture runs first. */
  window.addEventListener(
    "keydown",
    function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      var target = e.target;
      if (target && target.closest && target.closest(HOST + " button")) e.stopPropagation();
    },
    true
  );

  /* One video at a time. `play` does not bubble: listened in the capture phase. */
  document.addEventListener(
    "play",
    function (e) {
      var video = e.target;
      if (!video || video.tagName !== "VIDEO") return;
      var mine = isClipVideo(video);
      Array.prototype.forEach.call(document.querySelectorAll("video"), function (other) {
        if (other === video || other.paused) return;
        if (mine || isClipVideo(other)) other.pause();
      });
    },
    true
  );

  /* The video really shows frames: now it covers the picture. */
  document.addEventListener(
    "playing",
    function (e) {
      var video = e.target;
      if (!isClipVideo(video)) return;
      var host = hostOf(video);
      if (!host || stateOf(host) !== "loading") return;
      var hadFocus = focusInside(host);
      host.setAttribute("data-clip-state", "playing");
      host.setAttribute("data-clip-hint", "");
      window.setTimeout(function () {
        host.removeAttribute("data-clip-hint");
      }, HINT_MS);
      if (hadFocus) {
        var pause = host.querySelector("[data-clip-pause]");
        if (pause) pause.focus({ preventScroll: true });
      }
    },
    true
  );

  document.addEventListener(
    "pause",
    function (e) {
      var video = e.target;
      if (!isClipVideo(video)) return;
      var host = hostOf(video);
      if (host && active(host)) settle(host, "idle");
    },
    true
  );

  document.addEventListener(
    "timeupdate",
    function (e) {
      var video = e.target;
      if (!isClipVideo(video)) return;
      var host = hostOf(video);
      if (!host) return;
      // hidden (a folded list): nobody is watching
      if (host.getClientRects().length === 0) {
        pauseClip(host);
        return;
      }
      var span = stretch(host);
      if (!isNaN(span.end) && video.currentTime >= span.end - END_SLACK) {
        video.pause();
        try {
          video.currentTime = span.start;
        } catch (err) {
          /* the next ▶ seeks */
        }
        settle(host, "idle");
      }
    },
    true
  );

  document.addEventListener(
    "ended",
    function (e) {
      if (!isClipVideo(e.target)) return;
      var host = hostOf(e.target);
      if (host) settle(host, "idle");
    },
    true
  );

  /* `error` on the `<video>` (a 404, an expired address, a purged copy, a file it
     cannot decode). */
  document.addEventListener(
    "error",
    function (e) {
      var video = e.target;
      if (!isClipVideo(video) || !video.getAttribute("src")) return;
      var host = hostOf(video);
      if (host && stateOf(host) !== "broken") fail(host);
    },
    true
  );

  /* A card lifted by `slide-drag.js`: whatever plays stops. */
  document.addEventListener("dragstart", function () {
    Array.prototype.forEach.call(document.querySelectorAll(HOST), function (host) {
      if (active(host)) pauseClip(host);
    });
  });
})();
