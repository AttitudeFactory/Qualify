/* Generador: the gallery's three slides and the clip's reference images reordered by
   dragging (§ requests 2026-10-14, «quiero que el drag and drop tenga una animación» and
   «un drag and drop para el orden de las imágenes en el clip»). Each list is a group of
   its own (`data-slide-group`): a slide never lands among the clip's images.

   The browser's own HTML5 drag showed a frozen ghost and nothing else moved until the
   server answered. This is the influence ranking's motion (`rank-drag.js`) on the
   gallery's thumbnails (`.q-cr-slide--drag`):
     - a mouse lifts the slide as soon as it moves a few pixels while pressed; a finger
       or a pen holds still for `LONG_PRESS_MS` first, so a swipe still scrolls.
     - lifted, the slide grows (`.q-armed` → `.q-moving`) and follows the pointer; the
       other slides slide out of the way of the slot under it (`.q-shifting`), live.
     - released, it settles into the free slot (`.q-slide-release`) and only then does
       the target receive a synthetic `drop` (`drop_slide` moves it server-side). When
       React re-renders the new order, every transform is cleared before a paint and the
       slide that moved lands with a small pop (`.q-slide-landed`).
     - released outside the strip or on its own slot, everything springs back.
   A quick press-release is left alone: it is the click that opens the slide.

   Lifting dispatches `dragstart` on the slide (Reflex `on_drag_start` →
   `start_slide_drag`). Sent by `rx.call_script` when the gallery mounts; the guard keeps
   one set of document listeners however many times it is sent. */
(function () {
  "use strict";
  if (window.__qSlideDrag) return;
  window.__qSlideDrag = true;

  var CARD = ".q-cr-slide--drag";
  var LONG_PRESS_MS = 300; // touch and pen only
  var MOUSE_LIFT_PX = 5; // a mouse lifts once it moves this far
  var MOVE_CANCEL_PX = 10; // a finger moving this far before the hold: a scroll
  var SETTLE_MS = 200; // must match `.q-slide-release`'s transform transition
  var RETURN_MS = 420; // must outlast `.q-drag-return`'s transition
  var LANDED_MS = 360; // `.q-slide-landed`'s animation
  var OUTSIDE_PX = 48;
  var GIVE_UP_MS = 2500; // no new order came back: put everything back

  var drag = null;
  var swallowClick = false;

  function peersOf(card) {
    var group = card.getAttribute("data-slide-group");
    return Array.prototype.filter.call(document.querySelectorAll(CARD), function (c) {
      return c.getAttribute("data-slide-group") === group;
    });
  }

  function keyOf(card) {
    return card.getAttribute("data-slide-key");
  }

  function measure(peers) {
    var sx = window.scrollX;
    var sy = window.scrollY;
    return peers.map(function (peer) {
      var r = peer.getBoundingClientRect();
      return { left: r.left + sx, top: r.top + sy, right: r.right + sx, bottom: r.bottom + sy };
    });
  }

  function slotAt(d, x, y) {
    var px = x + window.scrollX;
    var py = y + window.scrollY;
    var box = d.box;
    if (
      px < box.left - OUTSIDE_PX ||
      px > box.right + OUTSIDE_PX ||
      py < box.top - OUTSIDE_PX ||
      py > box.bottom + OUTSIDE_PX
    ) {
      return d.from;
    }
    // the nearest slot by its centre: between two slides, the gap goes to the closer
    var best = d.to;
    var bestDist = Infinity;
    for (var i = 0; i < d.slots.length; i++) {
      var s = d.slots[i];
      var cx = (s.left + s.right) / 2;
      var cy = (s.top + s.bottom) / 2;
      var dist = Math.hypot(px - cx, py - cy);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    }
    return best;
  }

  /* `drop_slide`'s remove-then-insert: where the slide in slot `i` ends up. */
  function shiftedIndex(i, from, to) {
    if (from < to && i > from && i <= to) return i - 1;
    if (to < from && i >= to && i < from) return i + 1;
    return i;
  }

  function offset(d, fromSlot, toSlot) {
    var a = d.slots[fromSlot];
    var b = d.slots[toSlot];
    return "translate(" + (b.left - a.left) + "px, " + (b.top - a.top) + "px)";
  }

  function makeRoom(d) {
    d.peers.forEach(function (peer, i) {
      if (peer === d.card) return;
      var j = shiftedIndex(i, d.from, d.to);
      peer.style.transform = j === i ? "" : offset(d, i, j);
    });
  }

  function arm() {
    if (!drag || drag.armed) return;
    var d = drag;
    d.armed = true;
    d.peers = peersOf(d.card);
    d.slots = measure(d.peers);
    d.box = d.slots.reduce(
      function (acc, s) {
        return {
          left: Math.min(acc.left, s.left),
          top: Math.min(acc.top, s.top),
          right: Math.max(acc.right, s.right),
          bottom: Math.max(acc.bottom, s.bottom),
        };
      },
      { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity }
    );
    d.from = d.to = d.peers.indexOf(d.card);
    d.peers.forEach(function (peer) {
      if (peer !== d.card) peer.classList.add("q-shifting");
    });
    d.card.classList.add("q-dragging", "q-armed");
    document.body.setAttribute("data-slide-dragging", "true");
    d.card.dispatchEvent(new Event("dragstart", { bubbles: true, cancelable: true }));
    if (d.touch && window.navigator && window.navigator.vibrate) window.navigator.vibrate(12);
  }

  function reset(card) {
    card.classList.remove(
      "q-dragging",
      "q-armed",
      "q-moving",
      "q-slide-release",
      "q-drag-return",
      "q-shifting"
    );
    card.style.transition = "none";
    card.style.transform = "";
    void card.offsetWidth; // flush, so the next change animates again
    card.style.transition = "";
  }

  function putBack(cards) {
    document.body.removeAttribute("data-slide-dragging");
    cards.forEach(function (card) {
      card.classList.remove("q-armed", "q-moving", "q-slide-release", "q-shifting");
      card.classList.add("q-drag-return");
      card.style.transform = "";
    });
    window.setTimeout(function () {
      cards.forEach(reset);
    }, RETURN_MS);
  }

  function expectedOrder(d) {
    var keys = d.peers.map(keyOf);
    var moved = keys.splice(d.from, 1)[0];
    keys.splice(d.to, 0, moved);
    return keys;
  }

  /* As React shows the new order, each slide whose content already is the one its slot
     should hold drops its transform (before a paint) — a slot React has not updated yet
     keeps showing its old slide where that slide is going, so no frame is wrong. Once
     every slot matches, the slide that moved lands. */
  function clearWhenReordered(d) {
    var group = d.card.getAttribute("data-slide-group");
    var want = expectedOrder(d);
    var movedKey = want[d.to];
    var done = false;
    var observer = new MutationObserver(check);
    function cards() {
      return Array.prototype.filter.call(document.querySelectorAll(CARD), function (c) {
        return c.getAttribute("data-slide-group") === group;
      });
    }
    function check() {
      if (done) return;
      var now = cards();
      var all = true;
      now.forEach(function (card, i) {
        if (keyOf(card) === want[i]) {
          if (!card.__qSlideSettled) {
            card.__qSlideSettled = true;
            reset(card);
          }
        } else {
          all = false;
        }
      });
      if (!all || now.length !== want.length) return;
      done = true;
      observer.disconnect();
      document.body.removeAttribute("data-slide-dragging");
      now.forEach(function (card) {
        card.__qSlideSettled = false;
      });
      var landed = now[d.to];
      if (landed && keyOf(landed) === movedKey) {
        landed.classList.add("q-slide-landed");
        window.setTimeout(function () {
          landed.classList.remove("q-slide-landed");
        }, LANDED_MS);
      }
    }
    observer.observe(d.card.parentElement || document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-slide-key"],
    });
    window.setTimeout(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      cards().forEach(function (card) {
        card.__qSlideSettled = false;
      });
      putBack(d.peers);
    }, GIVE_UP_MS);
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    var card = e.target.closest && e.target.closest(CARD);
    if (!card || e.target.closest("a, button, input, textarea")) return;
    if (drag) return; // a drop still settling
    var touch = e.pointerType !== "mouse";
    drag = {
      card: card,
      id: e.pointerId,
      touch: touch,
      x0: e.clientX,
      y0: e.clientY,
      armed: false,
      moving: false,
      aborted: false,
      released: false,
      peers: [],
      slots: [],
      box: null,
      from: -1,
      to: -1,
      timer: touch ? window.setTimeout(arm, LONG_PRESS_MS) : null,
    };
  });

  document.addEventListener(
    "pointermove",
    function (e) {
      if (!drag || e.pointerId !== drag.id || drag.aborted || drag.released) return;
      var dx = e.clientX - drag.x0;
      var dy = e.clientY - drag.y0;
      if (!drag.armed) {
        var far = Math.hypot(dx, dy);
        if (!drag.touch) {
          if (far < MOUSE_LIFT_PX) return;
          arm();
        } else {
          if (far > MOVE_CANCEL_PX) {
            window.clearTimeout(drag.timer);
            drag.aborted = true;
          }
          return;
        }
      }
      e.preventDefault();
      if (!drag.moving) {
        drag.moving = true;
        drag.card.classList.add("q-moving");
      }
      drag.card.style.transform = "translate(" + dx + "px, " + dy + "px)";
      var to = slotAt(drag, e.clientX, e.clientY);
      if (to !== drag.to) {
        drag.to = to;
        makeRoom(drag);
      }
    },
    { passive: false }
  );

  document.addEventListener(
    "touchmove",
    function (e) {
      if (drag && drag.armed) e.preventDefault();
    },
    { passive: false }
  );

  /* The browser's own drag of the picture inside a slide would steal the pointer. */
  document.addEventListener("dragstart", function (e) {
    if (e.isTrusted && e.target.closest && e.target.closest(CARD)) e.preventDefault();
  });

  document.addEventListener("contextmenu", function (e) {
    if (e.target.closest && e.target.closest(CARD)) e.preventDefault();
  });

  /* A drag ends on a pointerup; the click that may follow is not a click on a slide. */
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

  function release(e) {
    if (!drag || e.pointerId !== drag.id || drag.released) return;
    var d = drag;
    window.clearTimeout(d.timer);

    if (!d.armed) {
      drag = null; // a plain click: React's own `on_click` opens the slide
      return;
    }

    swallowClick = true;
    window.setTimeout(function () {
      swallowClick = false;
    }, 0);
    d.card.classList.remove("q-armed", "q-moving");

    if (e.type === "pointercancel" || d.to === d.from) {
      drag = null;
      putBack(d.peers);
      return;
    }

    d.released = true;
    var target = d.peers[d.to];
    d.card.classList.add("q-slide-release");
    d.card.style.transform = offset(d, d.from, d.to);
    window.setTimeout(function () {
      drag = null;
      clearWhenReordered(d);
      target.dispatchEvent(new Event("drop", { bubbles: true, cancelable: true }));
    }, SETTLE_MS);
  }

  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
})();
