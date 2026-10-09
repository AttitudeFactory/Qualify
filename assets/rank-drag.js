/* Brand Kit, Resultados e insights: the influence ranking (§ requests 2026-09-29).

   The referente / competencia cards (`.q-rank-card`) sit in a grid read left to right
   and top to bottom — that reading order is the influence order. Same two gestures and
   the same motion as the deck (`deck-drag.js`, "Referente, competencia o detractor"):
     - press and release quickly, without moving → CLICK: opens the profile
       (`data-profile-url`) in a new tab.
     - press and HOLD STILL for `LONG_PRESS_MS` → ARMS the drag: the card grows to 105%
       (`.q-armed`), then to 110% the moment it moves (`.q-moving`) and follows the
       pointer (`.q-dragging`) — scale only, no tilt.
     - moving more than `MOVE_CANCEL_PX` before the hold armed it → neither: most likely
       a scroll, so the page keeps it.

   The list makes room LIVE (§ request 2026-10-05, "hay un pequeño delay al momento de
   cambiar de posición, muy feo"). It used to wait: the card flew onto its target, the
   drop went to the server, and only once React had re-rendered the new order did the
   rest slide — so the card sat on top of another one for a whole round trip. Now, while
   the card is held, the cards of the SAME grid and group (`data-rank-group`: bucket +
   pinned/rest) slide out of the way of the slot under the pointer (`.q-shifting`), the
   way a sortable list does. Released, the card settles into the free slot, and only
   then does the target receive the synthetic `drop` (`rank_drop` moves it server-side).
   When React re-renders, the screen already shows that order, so every transform is
   cleared in the same task — before a paint — and nothing visibly moves. Released
   outside the grid, or back on its own slot, everything springs back
   (`.q-drag-return`). Cards of another group never react, so an account added by hand
   (pinned) only moves among the pinned, a searched one only among the searched.

   The ordering stays server-side: arming dispatches `dragstart` on the card (Reflex
   `on_drag_start` → `rank_pick`) and the target's `on_drop` (`rank_drop`) moves it.
   Loaded once for every page and delegated at the document level, so it survives React
   re-rendering the grid after each move. Styled in `qualify.css` ("Influence ranking").

   Sent by `rx.call_script` when the ranking mounts (`_ranking_panel`), since the app's
   head scripts were measured not to load (2026-10-01) — hence the guard: one set of
   document listeners, however many times it is sent. */
(function () {
  "use strict";
  if (window.__qRankDrag) return;
  window.__qRankDrag = true;

  var CARD = ".q-rank-card";
  var LONG_PRESS_MS = 320; // same hold as the deck
  var MOVE_CANCEL_PX = 10;
  var SETTLE_MS = 180; // must match `.q-rank-release`'s transform transition
  var RETURN_MS = 420; // must outlast `.q-drag-return`'s transition
  var OUTSIDE_PX = 32; // this far outside the grid, a release puts everything back
  var GIVE_UP_MS = 2500; // no new order came back (a failed move): put everything back

  var drag = null;

  function sameGroup(card) {
    var group = card.getAttribute("data-rank-group");
    return Array.prototype.filter.call(document.querySelectorAll(CARD), function (c) {
      return c.getAttribute("data-rank-group") === group;
    });
  }

  function keyOf(card) {
    return card.getAttribute("data-rank-key");
  }

  /* Each peer's slot as drawn when the drag armed, in page coordinates — the slots do
     not move while the cards in them slide, so they are measured once. */
  function measure(peers) {
    var sx = window.scrollX;
    var sy = window.scrollY;
    return peers.map(function (peer) {
      var r = peer.getBoundingClientRect();
      return { left: r.left + sx, top: r.top + sy, right: r.right + sx, bottom: r.bottom + sy };
    });
  }

  /* The slot under the pointer; between slots, the one it was over last; well outside
     the grid, its own (the drag would put nothing anywhere). */
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
    for (var i = 0; i < d.slots.length; i++) {
      var s = d.slots[i];
      if (px >= s.left && px <= s.right && py >= s.top && py <= s.bottom) return i;
    }
    return d.to;
  }

  /* Where the card in slot `i` goes once the held card moves from `from` to `to` —
     `_move_in_ranking`'s remove-then-insert, the same move `rank_drop` makes. */
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

  /* Slide the other cards out of the held card's way. */
  function makeRoom(d) {
    d.peers.forEach(function (peer, i) {
      if (peer === d.card) return;
      var j = shiftedIndex(i, d.from, d.to);
      peer.style.transform = j === i ? "" : offset(d, i, j);
    });
  }

  function openProfile(card) {
    var url = card.getAttribute("data-profile-url");
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  function arm() {
    if (!drag) return;
    var d = drag;
    d.armed = true;
    d.peers = sameGroup(d.card);
    d.slots = measure(d.peers); // before the card scales up
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
    document.body.setAttribute("data-rank-dragging", "true");
    d.card.dispatchEvent(new Event("dragstart", { bubbles: true, cancelable: true }));
    if (window.navigator && window.navigator.vibrate) window.navigator.vibrate(12);
  }

  /* Back to a plain card, with no transition — the screen already shows where it is. */
  function reset(card) {
    card.classList.remove(
      "q-dragging",
      "q-armed",
      "q-moving",
      "q-rank-release",
      "q-drag-return",
      "q-shifting"
    );
    card.style.transition = "none";
    card.style.transform = "";
    void card.offsetWidth; // flush, so the next change animates again
    card.style.transition = "";
  }

  /* Everything springs back to where it was (released outside, on its own slot, or a
     move the server never confirmed). */
  function putBack(cards) {
    cards.forEach(function (card) {
      card.classList.remove("q-armed", "q-moving", "q-rank-release", "q-shifting");
      card.classList.add("q-drag-return");
      card.style.transform = "";
    });
    window.setTimeout(function () {
      cards.forEach(reset);
    }, RETURN_MS);
  }

  /* The group's keys in the order the screen shows once the move lands. */
  function expectedOrder(d) {
    var keys = d.peers.map(keyOf);
    var moved = keys.splice(d.from, 1)[0];
    keys.splice(d.to, 0, moved);
    return keys;
  }

  /* Once React has put the new order in the DOM — checked on every mutation, so an
     unrelated re-render is not mistaken for it — clear every transform at once. The
     observer runs before the browser paints, so the cleared frame is never drawn wrong. */
  function clearWhenReordered(d) {
    var group = d.card.getAttribute("data-rank-group");
    var want = expectedOrder(d).join("|");
    var done = false;
    var observer = new MutationObserver(check);
    function current() {
      return Array.prototype.filter
        .call(document.querySelectorAll(CARD), function (c) {
          return c.getAttribute("data-rank-group") === group;
        })
        .map(keyOf)
        .join("|");
    }
    function check() {
      if (done || current() !== want) return;
      done = true;
      observer.disconnect();
      document.querySelectorAll(CARD).forEach(reset);
    }
    observer.observe(d.card.parentElement || document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-rank-key"],
      characterData: true,
    });
    window.setTimeout(function () {
      if (done) return;
      done = true;
      observer.disconnect();
      putBack(d.peers);
    }, GIVE_UP_MS);
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    var card = e.target.closest(CARD);
    if (!card || e.target.closest("a, button, input, textarea")) return;
    if (drag) return; // a drop still settling
    drag = {
      card: card,
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      armed: false,
      moving: false,
      aborted: false,
      peers: [],
      slots: [],
      box: null,
      from: -1,
      to: -1,
      timer: window.setTimeout(arm, LONG_PRESS_MS),
    };
  });

  document.addEventListener(
    "pointermove",
    function (e) {
      if (!drag || e.pointerId !== drag.id || drag.aborted || drag.released) return;
      var dx = e.clientX - drag.x0;
      var dy = e.clientY - drag.y0;
      if (!drag.armed) {
        if (Math.hypot(dx, dy) > MOVE_CANCEL_PX) {
          window.clearTimeout(drag.timer);
          drag.aborted = true;
        }
        return;
      }
      e.preventDefault();
      if (!drag.moving) {
        drag.moving = true;
        drag.card.classList.add("q-moving"); // 105% → 110%, eased by CSS
      }
      // no tilt (§ request 2026-09-29, "solo quiero el scale"): the card only follows
      drag.card.style.transform = "translate(" + dx + "px, " + dy + "px)";
      var to = slotAt(drag, e.clientX, e.clientY);
      if (to !== drag.to) {
        drag.to = to;
        makeRoom(drag);
      }
    },
    { passive: false }
  );

  /* Once armed, a touch must not scroll the page under the card. */
  document.addEventListener(
    "touchmove",
    function (e) {
      if (drag && drag.armed) e.preventDefault();
    },
    { passive: false }
  );

  /* Keyboard: the card is focusable (`tabindex=0`) and Enter opens the profile, like
     the click does. */
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !e.target.matches || !e.target.matches(CARD)) return;
    e.preventDefault();
    openProfile(e.target);
  });

  /* A long press on a phone must not open the browser's own menu on the card. */
  document.addEventListener("contextmenu", function (e) {
    if (e.target.closest && e.target.closest(CARD)) e.preventDefault();
  });

  function release(e) {
    if (!drag || e.pointerId !== drag.id || drag.released) return;
    var d = drag;
    window.clearTimeout(d.timer);

    if (!d.armed) {
      drag = null;
      // a quick press-release with no meaningful movement: a click, not a drag
      if (!d.aborted && e.type !== "pointercancel") openProfile(d.card);
      return;
    }

    document.body.removeAttribute("data-rank-dragging");
    d.card.classList.remove("q-armed", "q-moving");

    if (e.type === "pointercancel" || d.to === d.from) {
      drag = null;
      putBack(d.peers);
      return;
    }

    // settle into the free slot — the rest already made room — and only then tell the
    // server, so the re-render lands under a screen that already shows it
    d.released = true;
    var target = d.peers[d.to];
    d.card.classList.add("q-rank-release");
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
