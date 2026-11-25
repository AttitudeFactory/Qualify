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
      // ED-04: an effect may go up or down to another row of «Efectos» (never out of
      // them); a text, a photo or a video only ever moves in X
      if (d.block.getAttribute("data-tl-block") === "effect") {
        d.lanes = Array.prototype.slice.call(
          d.root.querySelectorAll(".q-tl__lane--effect")
        );
        d.laneFrom = d.laneTo = d.lanes.indexOf(d.lane);
        if (d.laneFrom < 0) d.lanes = null;
        // Deivid 2026-11-20: no «+ Pista» — one more row shows under the last one while
        // an effect is held; dropped there it opens a new row (not for the only effect
        // of the last row: that would be its own row again)
        var last = d.lanes ? d.lanes.length - 1 : -1;
        d.newLane = !!d.lanes && !(d.laneFrom === last && itemsOf(d.lane).length < 2);
        if (d.newLane) d.root.setAttribute("data-tl-new-lane", "");
      }
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
    d.dy = laneDy(d);
    d.item.style.transform = moveOf(dx, d.dy);
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

  // ED-04: the row of «Efectos» an effect is held over, and how far down or up it shows.
  function laneDy(d) {
    if (!d.lanes) return 0;
    var tops = [];
    var bottoms = [];
    d.lanes.forEach(function (lane) {
      // a transform never moves a row's box: these are where the rows rest
      var box = lane.getBoundingClientRect();
      tops.push(box.top);
      bottoms.push(box.bottom);
    });
    if (d.newLane && tops.length) {
      // the new row under the last one: the same height, the same gap
      var gap = tops.length > 1 ? tops[1] - bottoms[0] : 4;
      var height = bottoms[0] - tops[0];
      var top = bottoms[bottoms.length - 1] + gap;
      tops.push(top);
      bottoms.push(top + height);
    }
    d.laneTo = core().laneAt({ y: d.clientY, tops: tops, bottoms: bottoms, from: d.laneFrom });
    return core().laneShift({ tops: tops, from: d.laneFrom, to: d.laneTo });
  }

  // X alone for everything; an effect on another row also moves in Y.
  function moveOf(dx, dy) {
    return dy ? "translate(" + dx + "px, " + dy + "px)" : "translateX(" + dx + "px)";
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

  // ED-04: what a drag leaves on the page goes with it — the blocks it lifted wherever
  // they are now (React may have reused or moved them: a «0:01,5» bubble was left on a
  // row after a drop, Deivid 2026-11-20) and the new row's room.
  function strays(d) {
    // a drag that began since (`drag`, not this one) keeps its own blocks and its row
    var active = drag && drag !== d ? drag : null;
    function held(it) {
      return !!active && (it === active.item || (active.items || []).indexOf(it) >= 0);
    }
    var all = (d.items || [d.item]).filter(function (it) {
      return !held(it);
    });
    Array.prototype.forEach.call(
      d.root.querySelectorAll(
        ".q-tl__item[data-tl-time], .q-tl__item--lifted, .q-tl__item--settle"
      ),
      function (it) {
        if (all.indexOf(it) < 0 && !held(it)) all.push(it);
      }
    );
    if (!active) d.root.removeAttribute("data-tl-new-lane");
    return all;
  }

  function clearTransforms(d) {
    strays(d).forEach(function (it) {
      it.classList.remove(
        "q-tl__item--lifted",
        "q-tl__item--shifting",
        "q-tl__item--settle",
        "q-tl__item--return"
      );
      it.style.transform = "";
      it.removeAttribute("data-tl-time");
    });
    if (!drag || drag === d) {
      // an older drag cleaning up late never strips a newer one's root state
      d.root.removeAttribute("data-tl-dragging");
      d.root.removeAttribute("data-tl-outside");
      liftHint(d.root, false);
    }
    syncLens(d.root, true);
  }

  function putBack(d) {
    var all = strays(d);
    all.forEach(function (it) {
      it.classList.add("q-tl__item--return");
      it.style.transform = "";
    });
    d.item.removeAttribute("data-tl-time");
    if (!drag || drag === d) {
      // an older drag cleaning up late never strips a newer one's root state
      d.root.removeAttribute("data-tl-dragging");
      d.root.removeAttribute("data-tl-outside");
      liftHint(d.root, false);
    }
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
    var observer = new MutationObserver(function (records) {
      if (done) return;
      // the lens's own moves are not the screen's answer
      var answer = records.some(function (r) {
        var t = r.target && r.target.nodeType === 1 ? r.target : r.target.parentElement;
        return !(t && t.closest && t.closest(".q-glass-blob"));
      });
      if (!answer) return;
      done = true;
      observer.disconnect();
      clearTransforms(d);
    });
    // ED-04: an effect may land on another row, or be refused (the live line says
    // why): every row of «Efectos» and the live line are the screen's answer too
    var watched = [d.lane].concat(d.lanes || []);
    watched.forEach(function (lane) {
      observer.observe(lane, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["style", "data-tl-id", "data-tl-start"],
      });
    });
    var status = d.mode === "move" ? null : d.root.querySelector(".q-tl__status");
    if (status) observer.observe(status, { childList: true, characterData: true, subtree: true });
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
    var held = "[data-q-timeline] [data-tl-block], [data-q-timeline] [data-tl-handle]";
    if (e.target && e.target.closest && e.target.closest(held)) {
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
      d.mode === "move"
        ? d.to === d.from
        : Math.abs(d.newStart - d.start) < core().STEP / 2 && d.laneTo === d.laneFrom;
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
      d.item.style.transform = moveOf((d.newStart - d.start) * d.px, d.dy || 0);
    }
    syncLens(d.root);
    window.setTimeout(function () {
      drag = null;
      clearOnRender(d);
      if (d.mode === "move") report(d.root, d.id, "move", d.to);
      // «time@N»: an effect dropped on another row (the screen keeps it there only if
      // it fits in time; else it comes back and the panel says why)
      else report(d.root, d.id, core().timeWhat({ from: d.laneFrom, to: d.laneTo }), d.newStart);
    }, SETTLE_MS);
  }

  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);

  /* ── ED-03 (m-25026623): the trim handles ────────────────────────────────────────────
     A handle (`[data-tl-handle]`, outside the chosen block) is taken AT ONCE by a finger
     or a mouse — no long press: it is its own control, never the block's move, and its
     `touch-action: none` keeps the tracks from scrolling under it. While it moves:
     its value follows the pointer on the two magnets (`core.trimValue`: ½ s of the video,
     or ¼ s to the playhead and the other blocks' edges), inside its `aria-valuemin`/
     `-max`; a bubble says the time; a box over the block shows what is kept; the
     preview shows that frame (`__qEditPreview.seq.showSource`, or the final video's
     time for a text or effect). Near the phone's edges the tracks scroll on their own.
     Released, the screen hears `(id, "start"|"end", value)` and, once the new sequence
     is in, the preview plays the block from its start. Escape or a cancelled pointer
     puts it back. */
  var trim = null;

  function previewOf(root) {
    var box = root.closest("[data-edit-sync]");
    return box ? box.querySelector("[data-edit-seq-host]") : null;
  }

  function seqApi() {
    var p = window.__qEditPreview;
    return p && p.seq ? p.seq : null;
  }

  // The playhead and every other block's edges, in seconds of the track: the ¼ s magnet.
  function magnetTargets(root, item) {
    var out = [];
    var scrub = root.querySelector(".q-tl__scrub");
    if (scrub) out.push(parseFloat(scrub.value) || 0);
    var blocks = root.querySelectorAll("[data-tl-block]");
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].closest(".q-tl__item") === item) continue;
      var start = parseFloat(blocks[i].getAttribute("data-tl-start")) || 0;
      var len = parseFloat(blocks[i].getAttribute("data-tl-len")) || 0;
      out.push(start, start + len);
    }
    return out;
  }

  function trimBox(t) {
    var box = t.item.querySelector(":scope > .q-tl__trim");
    if (!box) {
      box = document.createElement("div");
      box.className = "q-tl__trim";
      box.setAttribute("aria-hidden", "true");
      t.item.appendChild(box);
    }
    return box;
  }

  // What the handle at `value` keeps of the block, drawn over it (px from its left).
  function paintTrim(t) {
    var start = t.edge === "start" ? t.value : t.from;
    var end = t.edge === "start" ? t.end : t.value;
    var left = ((start - t.from) / t.speed) * t.px;
    var width = Math.max(((end - start) / t.speed) * t.px, 0);
    var shift = ((t.value - t.value0) / t.speed) * t.px;
    // ED-14 option B («Crece sin verse», Deivid 2026-11-24): the handle and the box (the
    // silhouette) wait at the edge — of what is seen AND of the track itself, never in
    // the room the desktop leaves beside it — while the value goes on (`core.trimDrawing`)
    var edges = drawEdges(t);
    var drawn = core().trimDrawing({
      shift: shift,
      edge: t.edge,
      boxLeft: left,
      boxWidth: width,
      handleLeft: t.handleLeft,
      handleWidth: t.handleWidth,
      blockEdge: t.edge === "start" ? t.blockStart : t.blockEnd,
      limitLeft: canvasX(t, edges.left),
      limitRight: canvasX(t, edges.right),
    });
    var box = trimBox(t);
    box.style.left = drawn.boxLeft + "px";
    box.style.width = drawn.boxWidth + "px";
    t.handle.style.transform = "translateX(" + drawn.handle + "px)";
    if (t.photo) {
      // ED-14: a photo's handle says how long it shows — «Se ve 2,5 s» — in the words of
      // its own `aria-valuetext` (`timeline_vm.media_blocks`), only the number changes
      var secs = String(t.value).replace(".", ",");
      var number = /[\d.,]+(?=\s*s$)/;
      var text = number.test(t.photoWords) ? t.photoWords.replace(number, secs) : secs + " s";
      t.handle.setAttribute("data-tl-time", text);
    } else {
      // «Desde 0:06» / «Hasta 0:09» (the handle's own word), to the hundredth
      var word = t.handle.getAttribute("data-tl-word") || "";
      t.handle.setAttribute(
        "data-tl-time",
        (word ? word + " " : "") + core().clockExact(t.value)
      );
    }
    placeBubble(t);
  }

  // ED-14 (Deivid 2026-11-24): what is seen of the tracks — the scroller's box inside the
  // screen — in viewport px.
  function viewBox(t) {
    var area = t.scroller || t.root;
    var box = area.getBoundingClientRect();
    var screen = document.documentElement.clientWidth || window.innerWidth || box.right;
    return { left: Math.max(box.left, 0), right: Math.min(box.right, screen) };
  }

  // …and the track itself (its lane: from its first second to its last), in viewport px:
  // a drag draws nothing past either (`core.dragEdges`).
  function drawEdges(t) {
    var view = viewBox(t);
    var lane = t.lane ? t.lane.getBoundingClientRect() : view;
    return core().dragEdges({
      viewLeft: view.left,
      viewRight: view.right,
      trackLeft: lane.left,
      trackRight: lane.right,
    });
  }

  // The bubble over the handle moves sideways to stay on screen (`core.bubbleShift`),
  // also at 375 px. Its width is the `::after`'s own; an estimate when the browser does
  // not say it.
  function placeBubble(t) {
    var handleBox = t.handle.getBoundingClientRect();
    var label = t.handle.getAttribute("data-tl-time") || "";
    var width = parseFloat(getComputedStyle(t.handle, "::after").width);
    if (!isFinite(width) || width <= 0) width = label.length * 7.5 + 12;
    // inside the timeline's tracks (not only the screen): away from the clock and the
    // playhead above the desktop's end
    var view = drawEdges(t);
    var shift = core().bubbleShift({
      center: handleBox.left + handleBox.width / 2,
      width: width,
      viewLeft: view.left,
      viewRight: view.right,
      margin: 4,
    });
    t.handle.style.setProperty("--tl-bubble-x", shift + "px");
  }

  // The preview shows the handle's frame: a video's own second, a photo's end on the
  // final video (ED-14: `at + value`, kept inside the photo as it plays now, so the
  // preview shows the photo and never the next block), or a text's or effect's moment
  // of the final video.
  function showTrimFrame(t) {
    var api = seqApi();
    var host = previewOf(t.root);
    if (!api || !host) return;
    if (t.video && api.showSource) {
      api.showSource(host, t.index, t.value);
    } else if (api.goTo) {
      if (api.pause) api.pause(host, true);
      var to = t.value;
      if (t.photo) to = t.at + Math.max(Math.min(t.value, t.value0) - 0.05, 0);
      api.goTo(host, to, true);
    }
  }

  function trimUpdate() {
    var t = trim;
    if (!t) return;
    var dx = canvasX(t, t.clientX) - t.x0;
    // the value follows the pointer inside the handle's own bounds only (5 s, the
    // video's material, the video): past the edge of what is seen it keeps going while
    // the handle waits there (ED-14 option B, `paintTrim` / `core.pinShift`)
    var next = core().trimValue({
      value: t.value0,
      dx: dx,
      px: t.px,
      speed: t.speed,
      at: t.at,
      from: t.from,
      targets: t.targets,
      min: t.min,
      max: t.max,
    }).value;
    if (t.photo) {
      // ED-14: a photo's seconds sit on the ½ s magnet only (the screen keeps them so)
      next = core().stepValue(next, t.min, t.max);
    }
    if (next === t.value && t.painted) return;
    t.value = next;
    t.painted = true;
    paintTrim(t);
    showTrimFrame(t);
  }

  function trimLoop() {
    var t = trim;
    if (!t || !t.phone || !t.scroller) return;
    var box = t.scroller.getBoundingClientRect();
    var step = core().autoScrollStep({ x: t.clientX, left: box.left, right: box.right });
    if (step) {
      // ED-14: as far as the tracks went when the handle was taken — the box it draws
      // never widens them, so the drag never pushes the timeline out of view
      var next = core().clampScroll(t.scroller.scrollLeft, step, t.maxScroll);
      if (next !== t.scroller.scrollLeft) {
        t.scroller.scrollLeft = next;
        trimUpdate();
      }
    }
    t.raf = window.requestAnimationFrame(trimLoop);
  }

  function trimClear(t) {
    window.cancelAnimationFrame(t.raf);
    var box = t.item.querySelector(":scope > .q-tl__trim");
    if (box) box.remove();
    t.handle.style.transform = "";
    t.handle.style.removeProperty("--tl-bubble-x");
    t.handle.removeAttribute("data-tl-time");
    t.item.classList.remove("q-tl__item--trimming");
    t.root.removeAttribute("data-tl-trimming");
  }

  // Once the screen's new sequence is in, the preview plays the block from its start.
  function playWhenReady(host, raw, from, tries) {
    var api = seqApi();
    if (!api || !host || !host.isConnected) return;
    if ((host.getAttribute("data-edit-seq") || "") !== raw) {
      if (api.playFrom) api.playFrom(host, from);
      return;
    }
    if (tries > 0) {
      window.requestAnimationFrame(function () {
        playWhenReady(host, raw, from, tries - 1);
      });
    }
  }

  document.addEventListener(
    "pointerdown",
    function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      if (trim || drag) return;
      var handle = e.target && e.target.closest ? e.target.closest("[data-tl-handle]") : null;
      var root = handle ? handle.closest("[data-q-timeline]") : null;
      if (!root || root.hasAttribute("data-tl-no-drag")) return;
      var item = handle.closest(".q-tl__item");
      var block = item ? item.querySelector("[data-tl-block]") : null;
      if (!item || !block) return;
      e.preventDefault(); // no text selection, no page scroll: the handle moves
      handle.focus({ preventScroll: true });
      var edge = handle.getAttribute("data-tl-handle");
      var kind = block.getAttribute("data-tl-block");
      var phone = isPhone(root);
      var total = parseFloat(getComputedStyle(root).getPropertyValue("--tl-total")) || 0;
      var lane = item.parentElement;
      var value0 = parseFloat(handle.getAttribute("aria-valuenow")) || 0;
      var other = item.querySelector(
        '[data-tl-handle="' + (edge === "start" ? "end" : "start") + '"]'
      );
      var t = {
        root: root,
        item: item,
        handle: handle,
        edge: edge,
        id: handle.getAttribute("data-tl-id") || "",
        video: kind === "video",
        photo: kind === "photo",
        photoWords: handle.getAttribute("aria-valuetext") || "",
        index: Array.prototype.indexOf.call(lane.querySelectorAll(":scope > .q-tl__item"), item),
        pointer: e.pointerId,
        canvas: root.querySelector(".q-tl__canvas"),
        scroller: root.querySelector(".q-tl__scroller"),
        phone: phone,
        px: core().scaleOf({
          phone: phone,
          px: parseFloat(getComputedStyle(root).getPropertyValue("--tl-px")),
          total: total,
          width: lane.getBoundingClientRect().width,
        }),
        speed: parseFloat(handle.getAttribute("data-tl-speed")) || 1,
        at: parseFloat(handle.getAttribute("data-tl-at")) || 0,
        from: parseFloat(handle.getAttribute("data-tl-from")) || 0,
        end:
          edge === "start" && other
            ? parseFloat(other.getAttribute("aria-valuenow")) || 0
            : value0,
        value0: value0,
        value: value0,
        min: parseFloat(handle.getAttribute("aria-valuemin")),
        max: parseFloat(handle.getAttribute("aria-valuemax")),
        clientX: e.clientX,
        painted: false,
      };
      if (!isFinite(t.min)) t.min = undefined;
      if (!isFinite(t.max)) t.max = undefined;
      t.x0 = canvasX(t, e.clientX);
      // ED-14: where the handle is now (canvas px) and how far the tracks scroll, for the
      // drag's stop at what is seen of the timeline (`core.viewBounds`)
      var handleBox = handle.getBoundingClientRect();
      t.handleLeft = canvasX(t, handleBox.left);
      t.handleWidth = handleBox.width;
      // the block's edges at rest and its track (lane): where the silhouette may reach
      var itemBox = item.getBoundingClientRect();
      t.blockStart = canvasX(t, itemBox.left);
      t.blockEnd = canvasX(t, itemBox.right);
      t.lane = lane;
      t.maxScroll = t.scroller ? t.scroller.scrollWidth - t.scroller.clientWidth : 0;
      t.targets = magnetTargets(root, item);
      t.seqRaw = "";
      var host = previewOf(root);
      if (host) t.seqRaw = host.getAttribute("data-edit-seq") || "";
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (err) {
        /* an old browser: the document still hears it */
      }
      trim = t;
      item.classList.add("q-tl__item--trimming");
      root.setAttribute("data-tl-trimming", edge);
      trimUpdate();
      if (phone) t.raf = window.requestAnimationFrame(trimLoop);
    },
    true
  );

  document.addEventListener(
    "pointermove",
    function (e) {
      var t = trim;
      if (!t || e.pointerId !== t.pointer) return;
      e.preventDefault();
      t.clientX = e.clientX;
      trimUpdate();
    },
    { passive: false }
  );

  // ED-14 option B: once the block is back at its new size, the tracks scroll so it is
  // seen whole if it fits, else its dragged edge (`core.revealScroll`). A desktop's tracks
  // do not scroll: the timeline lays itself out again at the new length.
  function revealBlock(t) {
    var scroller = t.scroller;
    if (!scroller || !t.root.isConnected) return;
    var max = scroller.scrollWidth - scroller.clientWidth;
    if (max <= 0) return;
    var block = null;
    var blocks = t.root.querySelectorAll("[data-tl-block]");
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].getAttribute("data-tl-id") === t.id) block = blocks[i];
    }
    if (!block) return;
    var box = block.getBoundingClientRect();
    var view = viewBox(t);
    var next = core().revealScroll({
      scrollLeft: scroller.scrollLeft,
      maxScroll: max,
      viewLeft: view.left,
      viewRight: view.right,
      blockLeft: box.left,
      blockRight: box.right,
      edge: t.edge,
      margin: 8,
    });
    if (next !== scroller.scrollLeft) scroller.scrollLeft = next;
  }

  function trimRelease(e) {
    var t = trim;
    if (!t || e.pointerId !== t.pointer) return;
    trim = null;
    var changed = e.type !== "pointercancel" && Math.abs(t.value - t.value0) >= 0.005;
    if (!changed) {
      trimClear(t);
      return;
    }
    // the box and the bubble stay until the block comes back at its new size
    window.cancelAnimationFrame(t.raf);
    var done = false;
    var observer = new MutationObserver(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      trimClear(t);
      window.requestAnimationFrame(function () {
        revealBlock(t);
      });
    });
    observer.observe(t.item, {
      subtree: true,
      attributes: true,
      attributeFilter: ["style", "aria-valuenow", "data-tl-len"],
    });
    window.setTimeout(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      trimClear(t);
      revealBlock(t); // the block is seen even when its new size came unnoticed
    }, GIVE_UP_MS);
    report(t.root, t.id, t.edge, t.value);
    // «Al soltar, reproduce el bloque»: from where it starts once the screen answered
    var host = previewOf(t.root);
    // (a photo from where it starts on the final video, ED-14)
    var start = t.video || t.photo ? t.at : t.edge === "start" ? t.value : t.from;
    playWhenReady(host, t.seqRaw, start, 150);
  }

  document.addEventListener("pointerup", trimRelease, true);
  document.addEventListener("pointercancel", trimRelease, true);

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || !trim) return;
    e.preventDefault();
    e.stopPropagation();
    var t = trim;
    trim = null;
    trimClear(t);
  }, true);

  // m-25114465 (UX review): a text or an effect just added may land later in the video,
  // out of view: once its block is drawn, the tracks (`.q-tl__scroller`) scroll SIDEWAYS
  // so it is seen — the same `core.revealScroll` as after a trim. Only that axis: up and
  // down is `__qTimeline.reveal`'s (`timeline.js`, with its `scroll-margin`); a desktop's
  // tracks do not overflow, so nothing moves there. Smooth unless the owner asked for
  // reduced motion. Waits up to ~1 s for the re-render. Called by the screen
  // (`CreativeState`) as `window.__qTimelineRevealNew(id)`.
  function reduceMotion() {
    return !!(
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function revealNew(id, tries) {
    var left = tries === undefined ? 60 : tries;
    var block = null;
    var blocks = document.querySelectorAll("[data-q-timeline] [data-tl-block]");
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].getAttribute("data-tl-id") === id) block = blocks[i];
    }
    if (!block) {
      if (left > 0) {
        window.requestAnimationFrame(function () {
          revealNew(id, left - 1);
        });
      }
      return;
    }
    var root = block.closest("[data-q-timeline]");
    var scroller = root ? root.querySelector(".q-tl__scroller") : null;
    var max = scroller ? scroller.scrollWidth - scroller.clientWidth : 0;
    if (!scroller || max <= 0) return;
    var box = block.getBoundingClientRect();
    var view = viewBox({ scroller: scroller, root: root });
    var x = core().revealScroll({
      scrollLeft: scroller.scrollLeft,
      maxScroll: max,
      viewLeft: view.left,
      viewRight: view.right,
      blockLeft: box.left,
      blockRight: box.right,
      edge: "start",
      margin: 8,
    });
    if (x === scroller.scrollLeft) return;
    if (scroller.scrollTo) {
      scroller.scrollTo({ left: x, behavior: reduceMotion() ? "auto" : "smooth" });
    } else {
      scroller.scrollLeft = x;
    }
  }

  window.__qTimelineRevealNew = revealNew;
})();
