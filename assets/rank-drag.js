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
   While held, the card of the SAME grid and group (`data-rank-group`: bucket +
   pinned/rest) under the pointer is marked `data-over`. Released there, the card flies
   onto that spot (`.q-rank-release`) and the target receives a synthetic `drop`: the
   dragged card takes its place. Released anywhere else, it springs back
   (`.q-drag-return`). Cards of another group never react, so an account added by hand
   (pinned) only moves among the pinned, a searched one only among the searched.

   The ordering stays server-side: arming dispatches `dragstart` on the card (Reflex
   `on_drag_start` → `rank_pick`) and the target's `on_drop` (`rank_drop`) moves it.
   Loaded once for every page and delegated at the document level, so it survives React
   re-rendering the grid after each move. Styled in `qualify.css` ("Influence ranking").

   The list itself moves too (§ request 2026-10-01, "una animación al momento de moverse
   la lista") — FLIP: every card's place is noted just before the drop, and once React has
   re-rendered the new order each card starts at its old place and slides to the new one.
   The dropped card stays where it landed until then, so nothing snaps back meanwhile.

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
  var RELEASE_MS = 220; // must match `.q-rank-release`'s transition
  var RETURN_MS = 420; // must outlast `.q-drag-return`'s transition
  var FLIP_MS = 340; // the list's slide to its new order
  var SETTLE_MS = 40; // React's re-render arrives as a burst of mutations: wait it out
  var GIVE_UP_MS = 2500; // no new order came back (a failed move): settle the card

  var drag = null;

  function sameGroup(card) {
    var group = card.getAttribute("data-rank-group");
    return Array.prototype.filter.call(document.querySelectorAll(CARD), function (c) {
      return c.getAttribute("data-rank-group") === group;
    });
  }

  /* The peer under the pointer (the dragged card has `pointer-events: none` and is
     skipped anyway, since it always contains the pointer). */
  function cardAt(d, x, y) {
    for (var i = 0; i < d.peers.length; i++) {
      var peer = d.peers[i];
      if (peer === d.card) continue;
      var r = peer.getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return peer;
    }
    return null;
  }

  function setOver(d, target) {
    if (d.over === target) return;
    if (d.over) d.over.removeAttribute("data-over");
    if (target) target.setAttribute("data-over", "true");
    d.over = target;
  }

  function openProfile(card) {
    var url = card.getAttribute("data-profile-url");
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  function arm() {
    if (!drag) return;
    drag.armed = true;
    drag.peers = sameGroup(drag.card);
    drag.card.classList.add("q-dragging", "q-armed");
    document.body.setAttribute("data-rank-dragging", "true");
    drag.card.dispatchEvent(new Event("dragstart", { bubbles: true, cancelable: true }));
    if (window.navigator && window.navigator.vibrate) window.navigator.vibrate(12);
  }

  /* Back to a plain card, with no transition — the grid is about to re-render. */
  function reset(card) {
    card.classList.remove("q-dragging", "q-armed", "q-moving", "q-rank-release", "q-drag-return");
    card.style.transition = "none";
    card.style.transform = "";
    void card.offsetWidth; // flush, so the next change animates again
    card.style.transition = "";
  }

  /* Where every card is drawn right now, by its account (`data-rank-key`) — keys, not
     nodes, so it holds whether React moves the nodes or reuses them in place. */
  function snapshot() {
    var places = {};
    document.querySelectorAll(CARD).forEach(function (card) {
      places[card.getAttribute("data-rank-key")] = card.getBoundingClientRect();
    });
    return places;
  }

  function slide(before) {
    var cards = Array.prototype.slice.call(document.querySelectorAll(CARD));
    cards.forEach(reset); // the landed card's flight, a reused node's leftovers
    cards.forEach(function (card) {
      var first = before[card.getAttribute("data-rank-key")];
      if (!first) return;
      var last = card.getBoundingClientRect();
      var dx = first.left - last.left;
      var dy = first.top - last.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      card.style.transition = "none";
      card.style.transform = "translate(" + dx + "px, " + dy + "px)";
      void card.offsetWidth;
      card.style.transition = "transform " + FLIP_MS + "ms cubic-bezier(0.22, 1, 0.36, 1)";
      card.style.transform = "";
      window.setTimeout(function () {
        card.style.transition = "";
      }, FLIP_MS + 60);
    });
  }

  /* After the drop: wait for React to put the new order on screen, then slide. */
  function slideAfterRerender(grid, before) {
    var settle = null;
    var done = false;
    var observer = new MutationObserver(function () {
      window.clearTimeout(settle);
      settle = window.setTimeout(finish, SETTLE_MS);
    });
    function finish() {
      if (done) return;
      done = true;
      observer.disconnect();
      slide(before); // measuring forces layout: no animation frame needed (and a hidden
      // tab never runs one)
    }
    observer.observe(grid, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-rank-key"],
      characterData: true,
    });
    window.setTimeout(finish, GIVE_UP_MS);
  }

  document.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    var card = e.target.closest(CARD);
    if (!card || e.target.closest("a, button, input, textarea")) return;
    drag = {
      card: card,
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      armed: false,
      moving: false,
      aborted: false,
      over: null,
      peers: [],
      timer: window.setTimeout(arm, LONG_PRESS_MS),
    };
  });

  document.addEventListener(
    "pointermove",
    function (e) {
      if (!drag || e.pointerId !== drag.id || drag.aborted) return;
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
      setOver(drag, cardAt(drag, e.clientX, e.clientY));
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
    if (!drag || e.pointerId !== drag.id) return;
    var d = drag;
    drag = null;
    window.clearTimeout(d.timer);

    if (!d.armed) {
      // a quick press-release with no meaningful movement: a click, not a drag
      if (!d.aborted && e.type !== "pointercancel") openProfile(d.card);
      return;
    }

    document.body.removeAttribute("data-rank-dragging");
    var target = d.over;
    if (target) target.removeAttribute("data-over");
    d.card.classList.remove("q-armed", "q-moving");

    if (target && e.type !== "pointercancel") {
      // fly onto the target's spot, then let its `on_drop` do the move
      var t = target.getBoundingClientRect();
      var c = d.card.getBoundingClientRect();
      var m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(d.card.style.transform || "");
      var tx = (m ? parseFloat(m[1]) : 0) + (t.left + t.width / 2) - (c.left + c.width / 2);
      var ty = (m ? parseFloat(m[2]) : 0) + (t.top + t.height / 2) - (c.top + c.height / 2);
      d.card.classList.add("q-rank-release");
      d.card.style.transform = "translate(" + tx + "px, " + ty + "px)";
      window.setTimeout(function () {
        // note every place NOW — the dropped card where it landed, the rest where they
        // stand — and slide from there once the new order is on screen
        slideAfterRerender(d.card.parentElement || document.body, snapshot());
        target.dispatchEvent(new Event("drop", { bubbles: true, cancelable: true }));
      }, RELEASE_MS);
      return;
    }

    // armed but nowhere to land (or cancelled): spring back, and back to 100%
    d.card.classList.add("q-drag-return");
    d.card.style.transform = "";
    window.setTimeout(function () {
      reset(d.card);
    }, RETURN_MS);
  }

  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);
})();
