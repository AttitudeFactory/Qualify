// The «Arma tu video» timeline's playhead (ED-00b m-25029104, `Qualify/ui/timeline.py`;
// ED-10 m-25026648 puts it in the editor).
//
// The playhead is the browser's: the range input `.q-tl__scrub` holds the time, this
// script writes its value text («0:05 de 0:12»), the clock over the tracks and the CSS
// variable `--tl-t` the desktop playhead is drawn with. On a phone (`--tl-mode: phone`,
// set by the container query in qualify-creative.css) the tracks slide under a fixed
// playhead: scrolling the tracks (or tapping the ruler, which scrolls them) moves the
// time, and moving the time (keyboard) scrolls the tracks. It also passes ←/→/Escape on
// a block or a handle to the screen (a hidden button, as `edit-preview.js` does), keeps
// those arrows from scrolling the tracks, keeps the focus on a block the keyboard just
// moved (the list re-renders by position), lets Escape inside a block's panel
// (`[data-tl-panel]`) give the block back, and brings the chosen block's panel into view
// (`window.__qTimeline.reveal`).
//
// ED-10 review: no observer on `document.body` — each timeline is attached when the
// screen mounts `ui.timeline.timeline_script` (and lazily by any event on it); its own
// observers are let go when it leaves the page (`sweep`, on the script's unmount).
// `prefers-reduced-motion` is read live, and switching between the phone and the
// desktop layout puts the tracks back on the playhead.
(function () {
  if (window.__qTimeline) {
    window.__qTimeline.initAll();
    return;
  }

  var STEP = 0.5;
  var roots = []; // the timelines attached, each with its observers (`root.__qTlObs`)

  function clock(s) {
    s = Math.max(Math.round(s / STEP) * STEP, 0);
    var whole = Math.floor(s);
    var m = Math.floor(whole / 60);
    var sec = whole % 60;
    return m + ":" + (sec < 10 ? "0" : "") + sec + (s - whole >= STEP ? ",5" : "");
  }

  function reduceMotion() {
    return !!(
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
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
  // the first time, and never glides with reduced motion (read each time: live).
  // While the chosen block is dragged, settles or makes room (`timeline-drag.js` moves
  // it with a `translateX` and calls `lens`), the lens sits at the block's resting place
  // and wears the SAME transform with the SAME transition: both move in the same frame
  // (Deivid, 2026-11-16: «haz que se muevan los dos»).
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
    var item = block.closest(".q-tl__item");
    var moved = item ? item.style.transform : "";
    // where the block rests: its box minus where its transform has it RIGHT NOW (the
    // computed value, mid-transition too)
    var now = item ? shiftOf(getComputedStyle(item).transform) : 0;
    // ED-04: an effect held over (or settling onto) another row is moved in Y too: the
    // lens rests on the block's own row and wears the same transform, never a row off
    var nowY = item ? shiftYOf(getComputedStyle(item).transform) : 0;
    var b = block.getBoundingClientRect();
    var c = canvas.getBoundingClientRect();
    var pad = 3; // the lens peeks out around the block
    var box = {
      left: b.left - c.left - canvas.clientLeft - pad - now,
      top: b.top - c.top - canvas.clientTop - pad - nowY,
      width: b.width + pad * 2,
      height: b.height + pad * 2,
    };
    var jump = instant || reduceMotion() || !lens.classList.contains("is-on");
    if (jump) lens.classList.add("q-no-anim");
    // held, settling, making room — or going back to its place (`--return`, no
    // transform left but still moving)
    var moving = !!moved || !!(item && item.classList.contains("q-tl__item--return"));
    if (moving) {
      // the block's own transition (none while held, ~150 ms settling), nothing else
      lens.style.transition = getComputedStyle(item).transition;
      lens.style.transform = moved;
    } else if (lens.style.transform || lens.style.transition) {
      lens.style.transition = "none";
      lens.style.transform = "";
      void lens.offsetWidth; // drop the borrowed transform in place, then glide as usual
      lens.style.transition = "";
    }
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

  function shiftOf(transform) {
    var core = window.__qTimelineDragCore;
    return core && core.shiftOf ? core.shiftOf(transform) : 0;
  }

  function shiftYOf(transform) {
    var core = window.__qTimelineDragCore;
    return core && core.shiftYOf ? core.shiftYOf(transform) : 0;
  }

  function modeOf(p) {
    return isPhone(p) ? "phone" : "desk";
  }

  // m-25114465 (ux review): a join point that really sits under the chosen block's trim
  // handles (measured in px, as laid out: a desktop's scale is not a phone's) is dimmed
  // and lets the handle have the taps (`data-join-near`). The points touching the chosen
  // block are hidden by the screen itself (`data-join-off`).
  function markJoins(root) {
    var core = window.__qTimelineDragCore;
    var points = root.querySelectorAll("[data-join-id]");
    if (!points.length || !core || !core.joinsNear) return;
    var boxes = function (list) {
      return Array.prototype.map.call(list, function (el) {
        var r = el.getBoundingClientRect();
        return { left: r.left, right: r.right };
      });
    };
    var near = core.joinsNear({
      points: boxes(points),
      handles: boxes(root.querySelectorAll('.q-tl__item[data-tl-chosen="true"] .q-tl__handle')),
    });
    Array.prototype.forEach.call(points, function (el, i) {
      if (near[i] !== el.hasAttribute("data-join-near")) el.toggleAttribute("data-join-near", near[i]);
    });
    // a point that just hid (it touches the block chosen) never keeps the focus: it goes
    // to that block
    var now = document.activeElement;
    if (now && now.getAttribute && now.getAttribute("data-join-off") === "1") {
      var chosen = root.querySelector('.q-tl__item[data-tl-chosen="true"] [data-tl-block]');
      if (chosen) chosen.focus({ preventScroll: true });
    }
  }

  function init(root) {
    if (root.__qTlReady) return;
    root.__qTlReady = true;
    roots.push(root);
    var obs = (root.__qTlObs = []);
    var p = parts(root);
    root.__qTlMode = modeOf(p);
    paint(p);
    scrollTo(p);
    placeLens(root, true);
    if (window.MutationObserver) {
      // A block chosen, moved, trimmed or sped up: the lens follows on the next frame.
      var pending = false;
      var lensWatch = new MutationObserver(function (records) {
        var outside = false;
        for (var i = 0; i < records.length; i++) {
          var t = records[i].target;
          if (!(t.closest && t.closest(".q-glass-blob"))) outside = true;
        }
        if (!outside || pending) return; // the lens's own class changes: no loop
        pending = true;
        window.requestAnimationFrame(function () {
          pending = false;
          if (root.isConnected) {
            placeLens(root, false);
            markJoins(root);
          }
        });
      });
      lensWatch.observe(root, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["data-tl-chosen", "class"],
      });
      obs.push(lensWatch);
    }
    if (window.ResizeObserver && p.canvas) {
      // A new size: the lens jumps; crossing the phone/desktop line puts the tracks
      // back on the playhead (a desktop has no scroll; a phone needs it at `t`).
      var sized = new ResizeObserver(function () {
        if (!root.isConnected) return;
        var q = parts(root);
        var mode = modeOf(q);
        if (mode !== root.__qTlMode) {
          root.__qTlMode = mode;
          paint(q);
          scrollTo(q);
        }
        placeLens(root, true);
        markJoins(root);
      });
      sized.observe(p.canvas);
      if (p.frame) sized.observe(p.frame);
      obs.push(sized);
    }
    // The video's length changes with an edit: the browser clamps the value silently.
    if (p.scrub && window.MutationObserver) {
      var maxWatch = new MutationObserver(function () {
        var q = parts(root);
        paint(q);
        scrollTo(q);
      });
      maxWatch.observe(p.scrub, { attributes: true, attributeFilter: ["max"] });
      obs.push(maxWatch);
    }
  }

  // The timelines that left the page give their observers back.
  function sweep() {
    roots = roots.filter(function (root) {
      if (root.isConnected) return true;
      (root.__qTlObs || []).forEach(function (o) {
        o.disconnect();
      });
      root.__qTlObs = [];
      root.__qTlReady = false;
      return false;
    });
  }

  function initAll() {
    sweep();
    var found = document.querySelectorAll("[data-q-timeline]");
    for (var i = 0; i < found.length; i++) init(found[i]);
  }

  function rootOf(el) {
    var root = el && el.closest ? el.closest("[data-q-timeline]") : null;
    if (root) init(root);
    return root;
  }

  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("q-tl__scrub")) return;
    var root = rootOf(el);
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
      var root = rootOf(el);
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
    var root = ruler ? rootOf(ruler) : null;
    if (root) tapRuler(parts(root), e.clientX);
    // a block chosen with the keyboard (Enter/Espacio: a click with no pointer):
    // its panel takes the focus once it shows (`reveal`)
    var block = el && el.closest ? el.closest("[data-tl-block]") : null;
    if (block) byKeyboard = e.detail === 0;
  });

  // After a move the block's id lands on another node: focus it once it does.
  var refocusId = null;
  var refocusFrom = null;
  var refocusUntil = 0;
  var byKeyboard = false;

  function blockById(id) {
    var all = document.querySelectorAll("[data-tl-block]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-tl-id") === id) return all[i];
    }
    return null;
  }

  function refocus() {
    if (!refocusId || Date.now() > refocusUntil) {
      refocusId = null;
      return;
    }
    var target = blockById(refocusId);
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

  // The timeline a panel belongs to: the one in its `[data-edit-sync]` box (the editor),
  // else the page's first.
  function timelineFor(panel) {
    var box = panel.closest("[data-edit-sync]");
    return (box || document).querySelector("[data-q-timeline]");
  }

  document.addEventListener("keydown", function (e) {
    var el = e.target;
    if (!el || !el.closest) return;
    // Escape inside a chosen block's panel: the block lets go and gets the focus back
    var panel = el.closest("[data-tl-panel]");
    if (panel && e.key === "Escape" && !e.defaultPrevented) {
      if (el.closest('[role="menu"], [role="listbox"], [data-radix-popper-content-wrapper]')) {
        return; // an open menu closes first
      }
      var owner = timelineFor(panel);
      var pid = panel.getAttribute("data-tl-panel") || "";
      if (!owner) return;
      e.preventDefault();
      var back = blockById(pid);
      if (back) back.focus();
      report(owner, pid, "", "Escape");
      return;
    }
    // m-25114465: Escape inside a join's panel closes it, as «Listo», and the focus goes
    // back to that join's point (edge "join" tells the screen it is a join, not a block)
    var joinPanel = el.closest("[data-tl-join-panel]");
    if (joinPanel && e.key === "Escape" && !e.defaultPrevented) {
      if (el.closest('[role="menu"], [role="listbox"], [data-radix-popper-content-wrapper]')) {
        return; // an open menu closes first
      }
      var joinOwner = timelineFor(joinPanel);
      var jid = joinPanel.getAttribute("data-tl-join-panel") || "";
      if (!joinOwner) return;
      e.preventDefault();
      var point = joinById(jid, joinOwner);
      if (point) point.focus();
      report(joinOwner, jid, "join", "Escape");
      return;
    }
    // …and on its own point while its panel is open (review)
    if (e.key === "Escape" && !e.defaultPrevented && el.matches &&
        el.matches('[data-join-id][aria-expanded="true"]')) {
      var openOwner = rootOf(el);
      if (!openOwner) return;
      e.preventDefault();
      report(openOwner, el.getAttribute("data-join-id") || "", "join", "Escape");
      return;
    }
    var root = rootOf(el);
    if (!root) return;
    var arrow = e.key === "ArrowLeft" || e.key === "ArrowRight";
    // ED-04: ↑/↓ on an effect block moves it to the row above or below
    var vertical =
      (e.key === "ArrowUp" || e.key === "ArrowDown") &&
      el.getAttribute("data-tl-block") === "effect";
    if (!arrow && !vertical && e.key !== "Escape") return;
    var id = el.getAttribute("data-tl-id");
    if (el.hasAttribute("data-tl-handle")) {
      if (arrow) e.preventDefault();
      if (e.key === "Escape") {
        // The handles go away with the choice: the focus goes back to their block.
        var block = blockById(id);
        if (block) block.focus();
      }
      report(root, id, el.getAttribute("data-tl-handle"), e.key);
      return;
    }
    if (el.hasAttribute("data-tl-block")) {
      if (arrow || vertical) e.preventDefault();
      var kind = el.getAttribute("data-tl-block");
      if ((arrow && (kind === "video" || kind === "photo")) || vertical) {
        refocusId = id;
        refocusFrom = el;
        refocusUntil = Date.now() + 800;
        window.requestAnimationFrame(refocus);
      }
      report(root, id, "", e.key);
    }
  });

  // The chosen block's panel comes into view (a phone shows it under the tracks): a
  // smooth scroll, or a jump with reduced motion; chosen with the keyboard, the panel
  // takes the focus. Waits up to ~1 s for the panel to render.
  function reveal(id, tries) {
    var left = tries === undefined ? 60 : tries;
    var panel = null;
    var all = document.querySelectorAll("[data-tl-panel]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-tl-panel") === id) panel = all[i];
    }
    if (!panel) {
      if (left > 0) {
        window.requestAnimationFrame(function () {
          reveal(id, left - 1);
        });
      }
      return;
    }
    // «nearest»: a panel already in view does not move; its `scroll-margin` keeps it
    // clear of a phone's fixed foot (qualify-creative.css)
    panel.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "nearest" });
    if (byKeyboard) {
      byKeyboard = false;
      panel.focus({ preventScroll: true });
    }
  }

  // `timeline-drag.js`: the chosen block moved (held, settling, making room, put back
  // or re-rendered at its new place): the lens follows in the same frame.
  function lens(root, instant) {
    if (root && root.isConnected) placeLens(root, !!instant);
  }

  // «Listo» / «Quitar» on a chosen block's panel: the panel goes away with the choice,
  // so the focus lands where the owner can go on — the block itself («Listo», as
  // Escape does), or the block now in the removed one's place («Quitar»), else «+»
  // (`id` ""). Waits up to ~1 s for the re-render (the «+» is drawn only with nothing
  // chosen); a focus the owner already moved elsewhere is left alone.
  function focusAfter(id, tries) {
    var left = tries === undefined ? 60 : tries;
    var target = id
      ? blockById(id)
      : document.querySelector(".q-tl-add [data-orbit-trigger]");
    if (target && !target.disabled) {
      var now = document.activeElement;
      var inPanel = now && now.closest && now.closest("[data-tl-panel], .q-tl-actions");
      if (!now || now === document.body || inPanel || !now.isConnected) {
        target.focus({ preventScroll: true });
      }
      return;
    }
    if (left > 0) {
      window.requestAnimationFrame(function () {
        focusAfter(id, left - 1);
      });
    }
  }

  // m-25114465: a join's point by the id of the block after it (`ui.timeline._join`),
  // inside its own timeline (`root`; the page's first when none is given).
  function joinById(id, root) {
    var scope = root || document.querySelector("[data-q-timeline]") || document;
    var all = scope.querySelectorAll("[data-join-id]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-join-id") === id) return all[i];
    }
    return null;
  }

  // The duration bar's thumb says its value as words: «0,5 segundos» (Radix Themes
  // passes no props to the thumb, so its `aria-valuenow` is read and written back).
  function joinValueText(panel) {
    if (!panel) return;
    var thumbs = panel.querySelectorAll('[data-join-seconds] [role="slider"]');
    for (var i = 0; i < thumbs.length; i++) {
      var now = Number(thumbs[i].getAttribute("aria-valuenow"));
      if (isNaN(now)) continue;
      var text = now.toFixed(1).replace(".", ",") + " segundos";
      if (thumbs[i].getAttribute("aria-valuetext") !== text) {
        thumbs[i].setAttribute("aria-valuetext", text);
      }
    }
  }

  // The bar is controlled: its thumb's `aria-valuenow` changes when the state comes back
  // (and the bar itself mounts when «Fundido» or «Barrido» is chosen). One observer per
  // open panel, as the lens's and the scrub's (`attributeFilter`), keeps the words true.
  function watchJoinValue(panel) {
    if (!panel || panel.__qJoinWatch || !window.MutationObserver) return;
    var watch = new MutationObserver(function () {
      joinValueText(panel);
    });
    watch.observe(panel, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-valuenow"],
    });
    panel.__qJoinWatch = watch;
  }

  // A join's panel just opened (ux review): it comes into view and the focus goes to the
  // option marked (`role="radio"` checked), its bar's thumb said in words. Waits ~1 s.
  function revealJoin(id, tries) {
    var left = tries === undefined ? 60 : tries;
    var panel = null;
    var all = document.querySelectorAll("[data-tl-join-panel]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-tl-join-panel") === id) panel = all[i];
    }
    if (!panel) {
      if (left > 0) {
        window.requestAnimationFrame(function () {
          revealJoin(id, left - 1);
        });
      }
      return;
    }
    panel.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "nearest" });
    var marked =
      panel.querySelector('[role="radio"][aria-checked="true"]') ||
      panel.querySelector('[role="radio"][data-state="on"], [role="radio"][data-state="checked"]');
    (marked || panel).focus({ preventScroll: true });
    joinValueText(panel);
    watchJoinValue(panel);
  }

  // «Listo» on a join's panel: the focus goes back to that join's point once the panel
  // is gone (up to ~1 s for the re-render); a focus the owner moved elsewhere stays.
  function focusJoin(id, tries) {
    var left = tries === undefined ? 60 : tries;
    var target = id ? joinById(id) : null;
    if (target) {
      var now = document.activeElement;
      var inPanel = now && now.closest && now.closest("[data-tl-join-panel]");
      if (!now || now === document.body || inPanel || !now.isConnected) {
        target.focus({ preventScroll: true });
      }
      return;
    }
    if (left > 0) {
      window.requestAnimationFrame(function () {
        focusJoin(id, left - 1);
      });
    }
  }

  window.__qTimeline = {
    initAll: initAll,
    sweep: sweep,
    reveal: reveal,
    lens: lens,
    focusAfter: focusAfter,
    focusJoin: focusJoin,
    revealJoin: revealJoin,
    markJoins: markJoins,
  };
  initAll();
})();
