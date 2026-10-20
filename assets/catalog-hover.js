/* Generador: a catalog product's card shows its other photos while the pointer is on it
   (§ request 2026-10-19, option A: «al pasar el ratón se van viendo todas sus fotos»).
   Every photo of the card is already in the page, stacked (`.q-cr-cat-photo`); this only
   moves `.is-on` from one to the next every `STEP_MS`, with the dots under the name
   (`.q-cr-cat-dot`) following. Leaving the card goes back to the first photo. Sent by
   `rx.call_script` when the product screen mounts; the guard keeps one set of document
   listeners however many times it is sent. */
(function () {
  "use strict";
  if (window.__qCatalogHover) return;
  window.__qCatalogHover = true;

  var CARD = ".q-cr-cat-card";
  var STEP_MS = 900;
  var timers = new WeakMap();

  function show(card, index) {
    var photos = card.querySelectorAll(".q-cr-cat-photo");
    var dots = card.querySelectorAll(".q-cr-cat-dot");
    for (var i = 0; i < photos.length; i++) photos[i].classList.toggle("is-on", i === index);
    for (var j = 0; j < dots.length; j++) dots[j].classList.toggle("is-on", j === index);
  }

  function start(card) {
    if (timers.has(card)) return;
    var count = card.querySelectorAll(".q-cr-cat-photo").length;
    if (count < 2) return;
    var index = 0;
    timers.set(
      card,
      window.setInterval(function () {
        // the card left the page while hovered (a re-render, another screen): no
        // mouseout will ever come, so the timer ends itself
        if (!card.isConnected) {
          window.clearInterval(timers.get(card));
          timers.delete(card);
          return;
        }
        index = (index + 1) % count;
        show(card, index);
      }, STEP_MS)
    );
  }

  function stop(card) {
    var timer = timers.get(card);
    if (timer !== undefined) window.clearInterval(timer);
    timers.delete(card);
    show(card, 0);
  }

  document.addEventListener("mouseover", function (event) {
    var card = event.target.closest && event.target.closest(CARD);
    if (card) start(card);
  });
  document.addEventListener("mouseout", function (event) {
    var card = event.target.closest && event.target.closest(CARD);
    if (!card) return;
    var to = event.relatedTarget;
    if (to && card.contains(to)) return;
    stop(card);
  });
})();
