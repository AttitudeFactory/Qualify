/* Brand Kit deck (Referente, competencia o detractor): the card in the middle.

   Two gestures, disambiguated by holding still (revised 2026-09-14):
     - press, release quickly with little movement  → CLICK: opens the profile
       (`data-profile-url`) in a new tab.
     - press, HOLD STILL for `LONG_PRESS_MS`         → ARMS the drag: the card grows
       gently to 105% (`.q-armed`), the cue that it can be lifted now. The instant
       it actually starts moving it grows again to 110% (`.q-moving`) for the whole
       drag. Both scales are the CSS `scale` property with a short transition in
       `qualify.css`, so 1 → 1.05 → 1.1 is eased, never a jump — while the
       `transform` this script writes on every move (translate + tilt) is not eased
       at all, so the card still tracks the finger 1:1.
     - press, then move more than `MOVE_CANCEL_PX` BEFORE the hold has armed it →
       neither: the gesture is aborted quietly (most likely a scroll/swipe).

   Which panel is "near" (`data-over`, the arrow + label pop, and the drop target on
   release) is decided by the CARD'S OWN EDGES, not by the pointer: as soon as the
   dragged card's rectangle reaches `NEAR_PX` into a panel, that panel reacts —
   before the card covers its letters (§ request 2026-09-14: "se hacen ya cuando
   tapa las letras, no me gusta eso"). The rectangle is the card's untransformed
   size (`offsetWidth/Height`) around its current on-screen centre, so neither the
   110% scale nor the tilt makes a panel react early, and a scroll mid-drag cannot
   desync it.

   Phones: a long press must not open the browser's own context menu / image
   callout (blocked below and via `-webkit-touch-callout` in CSS), and the card's
   `touch-action: none` keeps the hold from turning into a page scroll.

   Loaded once for every page (`rx.App(head_components)`), and delegated at the
   document level so it survives React re-mounting the card for every new account.
   The assignment itself stays server-side: on a release near a panel this script
   dispatches a `drop` event on it, and the panel's Reflex `on_drop`
   (`BrandConnectState.drop_into`) does the bookkeeping.

   Classes / attributes this script drives (styled in `qualify.css`, "Brand Kit deck"):
   - `.q-deck-card.q-armed`         105%, from the moment the long press arms it
   - `.q-deck-card.q-moving`        110%, from the first real movement
   - `.q-deck-card.q-dragging`      while armed / following the pointer
   - `.q-deck-card.q-drag-release`  the shrink-into-the-panel on a successful drop
   - `.q-deck-card.q-drag-return`   the spring back when released elsewhere
   - `.q-deck-card.q-deck-settled`  after a return: the resting float, without the
                                    entrance replaying
   - `body[data-deck-dragging]`     a card is held
   - `.q-deck-zone[data-over]`      the panel the card is near */
(function () {
  "use strict";
  // Sent by `rx.call_script` when the deck mounts (head scripts were measured not to
  // load, 2026-10-01): one set of document listeners, however many times it is sent.
  if (window.__qDeckDrag) return;
  window.__qDeckDrag = true;

  var CARD = ".q-deck-card";
  var ZONE = ".q-deck-zone";
  var LONG_PRESS_MS = 320; // holding still this long arms the drag
  var MOVE_CANCEL_PX = 10; // more than this before arming = abort, not a click
  var NEAR_PX = 6; // how far the card's edge must reach into a panel to count
  var RELEASE_MS = 190; // must match `.q-drag-release`'s transition
  var RETURN_MS = 420; // must outlast `.q-drag-return`'s transition

  var drag = null;

  /* The panel the dragged card is near: the one its (untransformed) rectangle
     overlaps the most, counting only overlaps at least NEAR_PX deep on both axes. */
  function nearestZone(d) {
    var c = d.card.getBoundingClientRect();
    var cx = (c.left + c.right) / 2;
    var cy = (c.top + c.bottom) / 2;
    var halfW = d.card.offsetWidth / 2;
    var halfH = d.card.offsetHeight / 2;
    var left = cx - halfW;
    var right = cx + halfW;
    var top = cy - halfH;
    var bottom = cy + halfH;

    var zones = document.querySelectorAll(ZONE);
    var best = null;
    var bestArea = 0;
    for (var i = 0; i < zones.length; i++) {
      var z = zones[i].getBoundingClientRect();
      var w = Math.min(right, z.right) - Math.max(left, z.left);
      var h = Math.min(bottom, z.bottom) - Math.max(top, z.top);
      if (w < NEAR_PX || h < NEAR_PX) continue;
      if (w * h > bestArea) {
        bestArea = w * h;
        best = zones[i];
      }
    }
    return best;
  }

  function setOver(zone) {
    if (drag.over === zone) return;
    if (drag.over) drag.over.removeAttribute("data-over");
    if (zone) zone.setAttribute("data-over", "true");
    drag.over = zone;
  }

  function translateOf(card) {
    var m = /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/.exec(card.style.transform || "");
    return m ? [parseFloat(m[1]), parseFloat(m[2])] : [0, 0];
  }

  function openProfile(card) {
    var url = card.getAttribute("data-profile-url");
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  function arm() {
    if (!drag) return;
    drag.armed = true;
    drag.card.classList.remove("q-deck-settled");
    drag.card.classList.add("q-dragging", "q-armed");
    document.body.setAttribute("data-deck-dragging", "true");
    if (window.navigator && window.navigator.vibrate) window.navigator.vibrate(12);
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
        // still holding: a firm swipe before the hold fires reads as a scroll/flick
        // attempt, not a deliberate long press — abort quietly (neither click nor drag)
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
      var tilt = Math.max(-15, Math.min(15, dx / 10));
      drag.card.style.transform = "translate(" + dx + "px, " + dy + "px) rotate(" + tilt + "deg)";
      setOver(nearestZone(drag));
    },
    { passive: false }
  );

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

    document.body.removeAttribute("data-deck-dragging");
    if (d.over) d.over.removeAttribute("data-over");
    d.card.classList.remove("q-dragging", "q-armed", "q-moving");

    if (d.over && e.type !== "pointercancel") {
      // shrink into the panel, then let the panel's own `on_drop` do the assignment
      var zone = d.over;
      var z = zone.getBoundingClientRect();
      var c = d.card.getBoundingClientRect();
      var t = translateOf(d.card);
      var tx = t[0] + (z.left + z.width / 2) - (c.left + c.width / 2);
      var ty = t[1] + (z.top + z.height / 2) - (c.top + c.height / 2);
      d.card.classList.add("q-drag-release");
      d.card.style.transform = "translate(" + tx + "px, " + ty + "px) scale(0.45)";
      window.setTimeout(function () {
        zone.dispatchEvent(new Event("drop", { bubbles: true, cancelable: true }));
      }, RELEASE_MS);
      return;
    }

    // armed but nowhere to land (or cancelled): spring back to the middle, and
    // back to 100% — both eased by `.q-drag-return`
    d.card.classList.add("q-drag-return");
    d.card.style.transform = "";
    window.setTimeout(function () {
      d.card.classList.remove("q-drag-return");
      d.card.classList.add("q-deck-settled");
    }, RETURN_MS);
  }

  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);

  // a long press on a phone must not open the browser's context menu on the card
  document.addEventListener("contextmenu", function (e) {
    if (e.target && e.target.closest && e.target.closest(CARD)) e.preventDefault();
  });
})();
