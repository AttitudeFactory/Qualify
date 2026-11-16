// The «Arma tu video» timeline's playhead (ED-00b m-25029104, `Qualify/ui/timeline.py`).
//
// The playhead is the browser's: the range input `.q-tl__scrub` holds the time, this
// script writes its value text («0:05 de 0:12»), the clock over the tracks and the CSS
// variable `--tl-t` the desktop playhead is drawn with. On a phone (`--tl-mode: phone`,
// set by the container query in qualify-creative.css) the tracks slide under a fixed
// playhead: scrolling the tracks (or tapping the ruler, which scrolls them) moves the
// time, and moving the time (keyboard) scrolls the tracks. It also passes ←/→/Escape on a block or a handle to the screen (a hidden
// button, as `edit-preview.js` does), keeps those arrows from scrolling the tracks, and
// keeps the focus on a block the keyboard just moved (the list re-renders by position).
(function () {
  if (window.__qTimeline) return;
  window.__qTimeline = true;

  var STEP = 0.5;

  function clock(s) {
    s = Math.max(Math.round(s / STEP) * STEP, 0);
    var whole = Math.floor(s);
    var m = Math.floor(whole / 60);
    var sec = whole % 60;
    return m + ":" + (sec < 10 ? "0" : "") + sec + (s - whole >= STEP ? ",5" : "");
  }

  function parts(root) {
    return {
      root: root,
      frame: root.querySelector(".q-tl__frame"),
      scroller: root.querySelector(".q-tl__scroller"),
      canvas: root.querySelector(".q-tl__canvas"),
      scrub: root.querySelector(".q-tl__scrub"),
      clock: root.querySelector(".q-tl__clock"),
    };
  }

  function isPhone(p) {
    if (!p.frame) return false;
    return getComputedStyle(p.frame).getPropertyValue("--tl-mode").trim() !== "desk";
  }

  function pxPerSecond(p) {
    var v = parseFloat(getComputedStyle(p.root).getPropertyValue("--tl-px"));
    return v > 0 ? v : 44;
  }

  function paint(p) {
    if (!p.scrub) return;
    var t = parseFloat(p.scrub.value) || 0;
    var total = parseFloat(p.scrub.max) || 0;
    var text = clock(t) + " de " + clock(total);
    p.scrub.setAttribute("aria-valuetext", text);
    if (p.clock) p.clock.textContent = text;
    if (p.canvas) p.canvas.style.setProperty("--tl-t", String(t));
  }

  function stepOf(seconds) {
    return Math.round(seconds / STEP) * STEP;
  }

  // The tracks follow the playhead's value — unless they already rest inside its ½ s (a
  // slide or a linked preview put them at an exact time: never snap that back). No
  // «ignore the next scroll» flag: a write the browser clamps fires no scroll and would
  // leave it stuck, swallowing the owner's next slide; the scroll handler is idempotent.
  function scrollTo(p) {
    if (!p.scroller || !p.scrub || !isPhone(p)) return;
    var px = pxPerSecond(p);
    var t = parseFloat(p.scrub.value) || 0;
    if (stepOf(p.scroller.scrollLeft / px) === stepOf(t)) return;
    p.scroller.scrollLeft = Math.round(t * px);
  }

  // A tap on the phone's ruler slides the tracks so the tapped time sits under the
  // playhead (on a desktop the playhead's own input covers the ruler).
  function tapRuler(p, clientX) {
    if (!p.scroller || !p.canvas || !p.scrub || !isPhone(p)) return;
    var px = pxPerSecond(p);
    var box = p.canvas.getBoundingClientRect();
    var pad = parseFloat(getComputedStyle(p.canvas).paddingLeft) || 0;
    var total = parseFloat(p.scrub.max) || 0;
    var t = Math.min(Math.max((clientX - box.left - p.canvas.clientLeft - pad) / px, 0), total);
    p.scroller.scrollLeft = Math.round(t * px);
  }

  // The menu's liquid lens (`.q-glass-blob`, styled in qualify.css) under the chosen
  // block: created here, inside the canvas, like `glass-nav.js` creates it inside an
  // island; it glides to the next block (the class's own transitions), appears in place
  // the first time, and never glides with reduced motion.
  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function lensOf(canvas) {
    var lens = canvas.querySelector(":scope > .q-glass-blob");
    if (!lens) {
      lens = document.createElement("div");
      lens.className = "q-glass-blob";
      lens.setAttribute("aria-hidden", "true");
      var surface = document.createElement("div");
      surface.className = "q-glass-blob__surface";
      lens.appendChild(surface);
      canvas.appendChild(lens);
    }
    return lens;
  }

  function placeLens(root, instant) {
    var canvas = root.querySelector(".q-tl__canvas");
    if (!canvas) return;
    var lens = lensOf(canvas);
    var block = root.querySelector('.q-tl__item[data-tl-chosen="true"] .q-tl__block');
    if (!block) {
      lens.classList.remove("is-on");
      return;
    }
    var b = block.getBoundingClientRect();
    var c = canvas.getBoundingClientRect();
    var pad = 3; // the lens peeks out around the block
    var box = {
      left: b.left - c.left - canvas.clientLeft - pad,
      top: b.top - c.top - canvas.clientTop - pad,
      width: b.width + pad * 2,
      height: b.height + pad * 2,
    };
    var jump = instant || reduceMotion || !lens.classList.contains("is-on");
    if (jump) lens.classList.add("q-no-anim");
    lens.style.left = box.left + "px";
    lens.style.top = box.top + "px";
    lens.style.width = box.width + "px";
    lens.style.height = box.height + "px";
    if (!lens.classList.contains("is-on")) lens.classList.add("is-on");
    if (jump) {
      void lens.offsetWidth; // apply the jump before the transitions come back
      lens.classList.remove("q-no-anim");
    }
  }

  function init(root) {
    if (root.__qTlReady) return;
    root.__qTlReady = true;
    var p = parts(root);
    paint(p);
    scrollTo(p);
    placeLens(root, true);
    if (window.MutationObserver) {
      // A block chosen, moved, trimmed or sped up: the lens follows on the next frame.
      var pending = false;
      new MutationObserver(function (records) {
        var outside = false;
        for (var i = 0; i < records.length; i++) {
          var t = records[i].target;
          if (!(t.closest && t.closest(".q-glass-blob"))) outside = true;
        }
        if (!outside || pending) return; // the lens's own class changes: no loop
        pending = true;
        window.requestAnimationFrame(function () {
          pending = false;
          placeLens(root, false);
        });
      }).observe(root, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["data-tl-chosen", "class"],
      });
    }
    if (window.ResizeObserver && p.canvas) {
      new ResizeObserver(function () {
        placeLens(root, true);
      }).observe(p.canvas);
    }
    // The video's length changes with an edit: the browser clamps the value silently.
    if (p.scrub && window.MutationObserver) {
      new MutationObserver(function () {
        var q = parts(root);
        paint(q);
        scrollTo(q);
      }).observe(p.scrub, { attributes: true, attributeFilter: ["max"] });
    }
  }

  function initAll() {
    var roots = document.querySelectorAll("[data-q-timeline]");
    for (var i = 0; i < roots.length; i++) init(roots[i]);
  }

  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("q-tl__scrub")) return;
    var root = el.closest("[data-q-timeline]");
    if (!root) return;
    var p = parts(root);
    paint(p);
    scrollTo(p);
  });

  // Scroll does not bubble: listen in the capture phase.
  document.addEventListener(
    "scroll",
    function (e) {
      var el = e.target;
      if (!el || !el.classList || !el.classList.contains("q-tl__scroller")) return;
      var root = el.closest("[data-q-timeline]");
      if (!root) return;
      var p = parts(root);
      if (!isPhone(p) || !p.scrub) return;
      var total = parseFloat(p.scrub.max) || 0;
      var t = stepOf(Math.min(Math.max(el.scrollLeft / pxPerSecond(p), 0), total));
      if (t === (parseFloat(p.scrub.value) || 0)) return; // same ½ s: nothing to repaint
      p.scrub.value = String(t);
      paint(p);
    },
    true
  );

  document.addEventListener("click", function (e) {
    var el = e.target;
    var ruler = el && el.closest ? el.closest(".q-tl__ruler") : null;
    var root = ruler ? ruler.closest("[data-q-timeline]") : null;
    if (root) tapRuler(parts(root), e.clientX);
  });

  // After a move the block's id lands on another node: focus it once it does.
  var refocusId = null;
  var refocusFrom = null;
  var refocusUntil = 0;

  function refocus() {
    if (!refocusId || Date.now() > refocusUntil) {
      refocusId = null;
      return;
    }
    var target = document.querySelector(
      '[data-tl-block][data-tl-id="' + refocusId + '"]'
    );
    if (target && target !== refocusFrom) {
      target.focus();
      refocusId = null;
      return;
    }
    window.requestAnimationFrame(refocus);
  }

  // ←/→/Escape on a block or a handle: the screen hears them through the hidden key
  // button (`ui.timeline._key_trigger`); arrows never scroll the tracks.
  function report(root, id, edge, key) {
    var trigger = root.querySelector("[data-tl-key-trigger]");
    if (!trigger) return;
    window.__qTimelineKey = { id: id, edge: edge, key: key };
    trigger.click();
  }

  document.addEventListener("keydown", function (e) {
    var el = e.target;
    var root = el && el.closest ? el.closest("[data-q-timeline]") : null;
    if (!root) return;
    var arrow = e.key === "ArrowLeft" || e.key === "ArrowRight";
    if (!arrow && e.key !== "Escape") return;
    var id = el.getAttribute("data-tl-id");
    if (el.hasAttribute("data-tl-handle")) {
      if (arrow) e.preventDefault();
      if (e.key === "Escape") {
        // The handles go away with the choice: the focus goes back to their block.
        var block = root.querySelector('[data-tl-block][data-tl-id="' + id + '"]');
        if (block) block.focus();
      }
      report(root, id, el.getAttribute("data-tl-handle"), e.key);
      return;
    }
    if (el.hasAttribute("data-tl-block")) {
      if (arrow) e.preventDefault();
      var kind = el.getAttribute("data-tl-block");
      if (arrow && (kind === "video" || kind === "photo")) {
        refocusId = id;
        refocusFrom = el;
        refocusUntil = Date.now() + 800;
        window.requestAnimationFrame(refocus);
      }
      report(root, id, "", e.key);
    }
  });

  initAll();
  if (window.MutationObserver) {
    new MutationObserver(initAll).observe(document.body, { childList: true, subtree: true });
  }
})();
