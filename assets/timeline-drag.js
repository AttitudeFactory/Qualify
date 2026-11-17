/* The timeline's drag and drop (ED-10 m-25026648; Deivid 2026-11-16: «quiero un drag
   and drop para mover los componentes»), on `ui.timeline`'s blocks. The math is
   `assets/timeline-drag-core.js` (`window.__qTimelineDragCore`, tested with node).

   - A mouse lifts a block once it moves `MOUSE_LIFT_PX` while pressed; a finger or a pen
     holds still `LONG_PRESS_MS` first, so a swipe still slides the tracks (the phone's
     playhead). A quick press-release is left alone: it is the click that chooses it.
   - A video or a photo («Fotos y videos») follows the pointer and the others make room
     with its width, live; released, it settles into its slot and the screen hears
     `(id, "move", index)`. A text or an effect slides along its track; a bubble shows
     the time it would start at (½ s magnet) and the screen hears `(id, "time", start)`.
   - Near the scroller's edges the tracks scroll on their own (phone only: on a desktop
     they fit the width). Every position is measured against the canvas, so the
     scroller's own scroll never skews it.
   - A held block never leaves its track: it moves only along X, inside the row (or the
     video's length), never up or down out of it.
   - Escape, a cancelled pointer, a drop on its own place or one off the tracks
     (`.q-tl__scroller`; Deivid 2026-11-17: «puedo sacar los componentes fuera de la time
     line no quiero eso») puts everything back.
   No visible grip (D-T6): the keyboard keeps its ←/→ (`assets/timeline.js`).

   The screen hears a drop through the hidden `[data-tl-drag-trigger]` button
   (`ui.timeline._drag_trigger`), like the keys. Sent by `rx.call_script` with
   `timeline.js`; the guard keeps one set of document listeners. */
(function () {
  "use strict";
  if (window.__qTimelineDrag) return;
  window.__qTimelineDrag = true;

  var SETTLE_MS = 160; // `.q-tl__item--settle`'s transition
  var GIVE_UP_MS = 2500; // no new order came back: put everything back

  var drag = null;
  var swallowClick = false;

  function core() {
    return window.__qTimelineDragCore;
  }

  function isPhone(root) {
    var frame = root.querySelector(".q-tl__frame");
    return !frame || getComputedStyle(frame).getPropertyValue("--tl-mode").trim() !== "desk";
  }

  function canvasX(d, clientX) {
    var box = d.canvas.getBoundingClientRect();
    return clientX - box.left - d.canvas.clientLeft;
  }

  // Is the pointer off the tracks (`.q-tl__scroller`, else the timeline itself)? A drop
  // there changes nothing (Deivid, 2026-11-17).
  function outsideTracks(d, clientX, clientY) {
    var area = d.scroller || d.root;
    if (!area || clientX === undefined || clientY === undefined) return false;
    var box = area.getBoundingClientRect();
    return !core().insideTracks({
      x: clientX,
      y: clientY,
      left: box.left,
      right: box.right,
      top: box.top,
      bottom: box.bottom,
    });
  }

  // The liquid lens under the chosen block follows it in the same frame
  // (`window.__qTimeline.lens`, `assets/timeline.js`): never a glide of its own behind
  // a dragged, settling or shifting block. `instant`: after a re-render, in place.
  function syncLens(root, instant) {
    var t = window.__qTimeline;
    if (t && t.lens) t.lens(root, instant);
  }

  function itemsOf(lane) {
    return Array.prototype.slice.call(lane.querySelectorAll(":scope > .q-tl__item"));
  }

  function liftHint(root, on) {
    var hint = root.querySelector(":scope > .q-tl__lift");
    if (!hint) {
      hint = document.createElement("p");
      hint.className = "q-tl__lift";
      hint.setAttribute("role", "status");
      root.appendChild(hint);
    }
    hint.textContent = on ? root.getAttribute("data-tl-lift-text") || "" : "";
  }

  function arm() {
    if (!drag || drag.armed || drag.aborted) return;
    var d = drag;
    d.armed = true;
    window.clearTimeout(d.timer);
    d.canvas = d.root.querySelector(".q-tl__canvas");
    d.scroller = d.root.querySelector(".q-tl__scroller");
    d.phone = isPhone(d.root);
    d.x0 = canvasX(d, d.clientX0);
    if (d.mode === "move") {
      d.items = itemsOf(d.lane);
      d.from = d.to = d.items.indexOf(d.item);
      var origin = d.items.length ? d.items[0].getBoundingClientRect().left : 0;
      d.widths = d.items.map(function (it) {
        return it.getBoundingClientRect().width;
      });
      d.left0 = d.item.getBoundingClientRect().left - origin;
      // the block stays inside the row: the blocks' own extent
      d.bound = {
        left: d.left0,
        width: d.widths[d.from] || 0,
        span: d.widths.reduce(function (sum, w) {
          return sum + w;
        }, 0),
      };
      d.items.forEach(function (it) {
        if (it !== d.item) it.classList.add("q-tl__item--shifting");
      });
    } else {
      var total = parseFloat(getComputedStyle(d.root).getPropertyValue("--tl-total")) || 0;
      d.start = parseFloat(d.block.getAttribute("data-tl-start")) || 0;
      d.length = parseFloat(d.block.getAttribute("data-tl-len")) || 0;
      d.total = total;
      // a phone's fixed scale; a desktop's lane fills the width (its px per second)
      d.px = core().scaleOf({
        phone: d.phone,
        px: parseFloat(getComputedStyle(d.root).getPropertyValue("--tl-px")),
        total: total,
        width: d.lane.getBoundingClientRect().width,
      });
      d.newStart = d.start;
      d.item.setAttribute("data-tl-time", core().clock(d.start));
      // the block stays inside the video (unknown length: no bound to keep)
      d.bound =
        total > 0
          ? { left: d.start * d.px, width: d.length * d.px, span: total * d.px }
          : null;
    }
    d.item.classList.add("q-tl__item--lifted");
    d.root.setAttribute("data-tl-dragging", d.mode);
    liftHint(d.root, true);
    syncLens(d.root);
    if (d.touch && window.navigator && window.navigator.vibrate) window.navigator.vibrate(12);
    loop();
  }

  function update() {
    var d = drag;
    if (!d || !d.armed) return;
    var dx = canvasX(d, d.clientX) - d.x0;
    if (d.bound) {
      // never out of its track: only X moves, inside the track's own range
      dx = core().clampShift({
        dx: dx,
        left: d.bound.left,
        width: d.bound.width,
        span: d.bound.span,
      });
    }
    d.dx = dx;
    d.outside = outsideTracks(d, d.clientX, d.clientY);
    if (d.outside) d.root.setAttribute("data-tl-outside", "");
    else d.root.removeAttribute("data-tl-outside");
    d.item.style.transform = "translateX(" + dx + "px)";
    if (d.mode === "move") {
      // held outside the tracks: the others are back in place — that is the drop
      var to = d.outside ? d.from : core().dropIndex(d.widths, d.from, d.left0 + dx);
      if (to !== d.to) {
        d.to = to;
        var shifts = core().layoutShifts(d.widths, d.from, d.to);
        d.items.forEach(function (it, i) {
          if (it !== d.item) it.style.transform = shifts[i] ? "translateX(" + shifts[i] + "px)" : "";
        });
      }
    } else {
      var start = core().shiftedStart({
        start: d.start,
        length: d.length,
        total: d.total,
        dx: dx,
        px: d.px,
      });
      if (start !== d.newStart) {
        d.newStart = start;
        d.item.setAttribute("data-tl-time", core().clock(start));
      }
    }
    syncLens(d.root);
  }

  // Near an edge of the phone's scroller the tracks scroll under the held block.
  function loop() {
    var d = drag;
    if (!d || !d.armed || d.released) return;
    if (d.phone && d.scroller && d.clientX !== undefined) {
      var box = d.scroller.getBoundingClientRect();
      // held above or below the tracks: they stay still (a drop there changes nothing)
      var level = d.clientY >= box.top && d.clientY <= box.bottom;
      var step = level
        ? core().autoScrollStep({ x: d.clientX, left: box.left, right: box.right })
        : 0;
      if (step) {
        var max = d.scroller.scrollWidth - d.scroller.clientWidth;
        var next = core().clampScroll(d.scroller.scrollLeft, step, max);
        if (next !== d.scroller.scrollLeft) {
          d.scroller.scrollLeft = next;
          update();
        }
      }
    }
    d.raf = window.requestAnimationFrame(loop);
  }

  function clearTransforms(d) {
    (d.items || [d.item]).forEach(function (it) {
      it.classList.remove(
        "q-tl__item--lifted",
        "q-tl__item--shifting",
        "q-tl__item--settle",
        "q-tl__item--return"
      );
      it.style.transform = "";
      it.removeAttribute("data-tl-time");
    });
    d.root.removeAttribute("data-tl-dragging");
    d.root.removeAttribute("data-tl-outside");
    liftHint(d.root, false);
    syncLens(d.root, true);
  }

  function putBack(d) {
    var all = d.items || [d.item];
    all.forEach(function (it) {
      it.classList.add("q-tl__item--return");
      it.style.transform = "";
    });
    d.item.removeAttribute("data-tl-time");
    d.root.removeAttribute("data-tl-dragging");
    d.root.removeAttribute("data-tl-outside");
    liftHint(d.root, false);
    syncLens(d.root);
    window.setTimeout(function () {
      all.forEach(function (it) {
        it.classList.remove(
          "q-tl__item--return",
          "q-tl__item--lifted",
          "q-tl__item--shifting",
          "q-tl__item--settle"
        );
      });
    }, SETTLE_MS + 60);
  }

  // The screen re-renders the track (new order or new start): every transform goes
  // before that frame is painted (a MutationObserver runs before the paint).
  function clearOnRender(d) {
    var done = false;
    var observer = new MutationObserver(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      clearTransforms(d);
    });
    observer.observe(d.lane, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["style", "data-tl-id", "data-tl-start"],
    });
    window.setTimeout(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      putBack(d);
    }, GIVE_UP_MS);
  }

  function report(root, id, what, value) {
    var trigger = root.querySelector("[data-tl-drag-trigger]");
    if (!trigger) return;
    window.__qTimelineDrop = { id: id, what: what, value: value };
    trigger.click();
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (drag) return; // a drop still settling
    var block = e.target && e.target.closest ? e.target.closest("[data-tl-block]") : null;
    var root = block ? block.closest("[data-q-timeline]") : null;
    if (!root || root.hasAttribute("data-tl-no-drag")) return;
    var kind = block.getAttribute("data-tl-block");
    var item = block.closest(".q-tl__item");
    var lane = item ? item.parentElement : null;
    if (!item || !lane) return;
    var mode = kind === "video" || kind === "photo" ? "move" : "time";
    if (mode === "move" && itemsOf(lane).length < 2) return; // nothing to swap with
    var touch = e.pointerType !== "mouse";
    drag = {
      root: root,
      block: block,
      item: item,
      lane: lane,
      mode: mode,
      id: block.getAttribute("data-tl-id") || "",
      pointer: e.pointerId,
      touch: touch,
      clientX0: e.clientX,
      clientY0: e.clientY,
      clientX: e.clientX,
      clientY: e.clientY,
      t0: Date.now(),
      armed: false,
      aborted: false,
      released: false,
      timer: touch ? window.setTimeout(arm, core().LONG_PRESS_MS) : null,
    };
  });

  document.addEventListener(
    "pointermove",
    function (e) {
      var d = drag;
      if (!d || e.pointerId !== d.pointer || d.aborted || d.released) return;
      d.clientX = e.clientX;
      d.clientY = e.clientY;
      if (!d.armed) {
        var verdict = core().liftDecision({
          touch: d.touch,
          dist: Math.hypot(e.clientX - d.clientX0, e.clientY - d.clientY0),
          elapsed: Date.now() - d.t0,
        });
        if (verdict === "cancel") {
          window.clearTimeout(d.timer);
          drag = null;
          return;
        }
        if (verdict !== "lift") return;
        arm();
      }
      e.preventDefault();
      update();
    },
    { passive: false }
  );

  // A lifted block: the finger drags it, never the page nor the tracks.
  document.addEventListener(
    "touchmove",
    function (e) {
      if (drag && drag.armed) e.preventDefault();
    },
    { passive: false }
  );

  // A long press on a block opens no menu and selects no text.
  document.addEventListener("contextmenu", function (e) {
    if (e.target && e.target.closest && e.target.closest("[data-q-timeline] [data-tl-block]")) {
      e.preventDefault();
    }
  });

  // A drag ends on a pointerup; the click that may follow does not choose the block.
  document.addEventListener(
    "click",
    function (e) {
      if (!swallowClick) return;
      swallowClick = false;
      e.preventDefault();
      e.stopPropagation();
    },
    true
  );

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || !drag || !drag.armed || drag.released) return;
    e.preventDefault();
    var d = drag;
    drag = null;
    window.cancelAnimationFrame(d.raf);
    putBack(d);
  });

  function release(e) {
    var d = drag;
    if (!d || e.pointerId !== d.pointer || d.released) return;
    window.clearTimeout(d.timer);
    if (!d.armed) {
      drag = null; // a plain click: React's own `on_click` chooses the block
      return;
    }
    d.released = true;
    window.cancelAnimationFrame(d.raf);
    swallowClick = true;
    window.setTimeout(function () {
      swallowClick = false;
    }, 0);
    var same =
      d.mode === "move" ? d.to === d.from : Math.abs(d.newStart - d.start) < core().STEP / 2;
    // dropped off the tracks: it goes back to its place and nothing changes
    var verdict = core().dropVerdict({
      cancelled: e.type === "pointercancel",
      outside: outsideTracks(d, e.clientX, e.clientY),
      same: same,
    });
    if (verdict === "back") {
      drag = null;
      putBack(d);
      return;
    }
    d.item.classList.add("q-tl__item--settle");
    if (d.mode === "move") {
      var shifts = core().layoutShifts(d.widths, d.from, d.to);
      d.item.style.transform = "translateX(" + shifts[d.from] + "px)";
    } else {
      d.item.style.transform = "translateX(" + (d.newStart - d.start) * d.px + "px)";
    }
    syncLens(d.root);
    window.setTimeout(function () {
      drag = null;
      clearOnRender(d);
      if (d.mode === "move") report(d.root, d.id, "move", d.to);
      else report(d.root, d.id, "time", d.newStart);
    }, SETTLE_MS);
  }

  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
})();
