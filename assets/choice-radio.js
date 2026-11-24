/* ED-13 (m-25029108): a radiogroup of `choice_card`s (`[data-q-radiogroup]`, e.g. «Fondo
   de las letras» and «Cómo entra / Cómo sale» in `Qualify/ui/text_panel.py`) is ONE tab
   stop — the chosen card has tabindex 0, the others -1 (rendered by the screen) — and
   the arrows move to the previous / next card and choose it (WAI-ARIA radio group): its
   own `click`, so the screen's handler is the one that decides. A card that is off but
   focusable (`aria-disabled="true"`, «Letra por letra» past 40 letters) takes the focus
   and is not chosen: its reason is the visible line under the grid. Home / End go to the
   first / last card. Sent by `rx.call_script` when the panel mounts; the guard keeps one
   listener. */
(function () {
  "use strict";
  if (window.__qChoiceRadio) return;
  window.__qChoiceRadio = true;

  var NEXT = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

  document.addEventListener("keydown", function (e) {
    var el = e.target;
    if (!el || !el.closest || e.altKey || e.ctrlKey || e.metaKey) return;
    var radio = el.closest('[role="radio"]');
    var group = radio && radio.closest("[data-q-radiogroup]");
    if (!group) return;
    var cards = Array.prototype.slice.call(group.querySelectorAll('[role="radio"]'));
    var at = cards.indexOf(radio);
    if (at < 0) return;
    var to;
    if (e.key in NEXT) to = (at + NEXT[e.key] + cards.length) % cards.length;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = cards.length - 1;
    else return;
    e.preventDefault();
    e.stopPropagation();
    var card = cards[to];
    cards.forEach(function (c) {
      c.setAttribute("tabindex", c === card ? "0" : "-1");
    });
    card.focus();
    if (card.getAttribute("aria-disabled") !== "true") card.click();
  });
})();
