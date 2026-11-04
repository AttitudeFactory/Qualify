/* Brand Kit editor, «Negocios parecidos al tuyo»: an account moving to another list is
   SEEN going there (§ request 2026-11-03).

   The move itself is server-side (`BrandConnectState.move_account` / `drop_on_column`);
   this script only animates the re-render, keyed by account (`data-rank-key`):

   - Board, `md` up (`[data-rank-board="cols"]`), FLIP: the positions of every card are
     measured BEFORE the move (when «Mover a»'s choice is clicked — a capture listener,
     so it runs before React's — or, for a drag, handed over by `rank-drag.js` with the
     card's rectangle where it was released). Once the moved card shows up inside its
     new column (a MutationObserver: the server answered and React re-rendered), each
     card is put back where it was with a transform and released to its new slot
     (~300 ms ease-out): the moved card travels across, its old column closes the gap,
     the target column flashes (`data-flash`) and its count pulses (`data-pulse`).
   - Tabs, below `md` (`[data-rank-board="tabs"]`): the target list is not on screen, so
     at the click a copy of the card flies to the target tab's segment and fades there,
     and the segment pulses with its new count. The real card simply leaves its list
     when React re-renders.

   `prefers-reduced-motion`: no motion at all — the lists just change.
   Sent by `rx.call_script` when the board mounts; guarded to one set of listeners. */
(function () {
  "use strict";
  if (window.__qRankFlip) return;

  var CARD = ".q-rank-card[data-rank-key]";
  var DURATION_MS = 300;
  var EASE = "cubic-bezier(0.2, 0.8, 0.2, 1)";
  var GIVE_UP_MS = 2500;

  function reduced() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function board(name) {
    return document.querySelector('[data-rank-board="' + name + '"]');
  }

  function cardsOf(root) {
    return root ? Array.prototype.slice.call(root.querySelectorAll(CARD)) : [];
  }

  function snapshot(root) {
    var rects = {};
    cardsOf(root).forEach(function (card) {
      rects[card.getAttribute("data-rank-key")] = card.getBoundingClientRect();
    });
    return rects;
  }

  function columnOf(root, bucket) {
    return root && root.querySelector('[data-rank-column="' + bucket + '"]');
  }

  function cleanCard(card) {
    card.classList.remove(
      "q-dragging",
      "q-armed",
      "q-moving",
      "q-rank-release",
      "q-drag-return",
      "q-shifting",
      "q-rank-leaving",
      "q-rank-flying"
    );
    card.style.transition = "none";
    card.style.transform = "";
  }

  function flash(el, attr) {
    if (!el || reduced()) return;
    el.removeAttribute(attr);
    void el.offsetWidth; // restart the animation on a second move
    el.setAttribute(attr, "true");
    window.setTimeout(function () {
      el.removeAttribute(attr);
    }, 700);
  }

  /* Play every card of the board from `before` to where it is now. */
  function play(root, before, key, bucket) {
    var cards = cardsOf(root);
    cards.forEach(cleanCard);
    if (reduced()) {
      cards.forEach(function (card) {
        card.style.transition = "";
      });
      return;
    }
    var moving = [];
    cards.forEach(function (card) {
      var was = before[card.getAttribute("data-rank-key")];
      if (!was) return;
      var now = card.getBoundingClientRect();
      var dx = was.left - now.left;
      var dy = was.top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      card.style.transform = "translate(" + dx + "px, " + dy + "px)";
      if (card.getAttribute("data-rank-key") === key) card.classList.add("q-rank-flying");
      moving.push(card);
    });
    void document.body.offsetWidth; // the inverted positions are drawn first
    // `cleanCard` turned transitions off on EVERY card: give each its own back (or a
    // later drag inside a column would jump), then the travelling ones theirs
    cards.forEach(function (card) {
      card.style.transition = "";
    });
    moving.forEach(function (card) {
      card.style.transition = "transform " + DURATION_MS + "ms " + EASE;
      card.style.transform = "";
    });
    window.setTimeout(function () {
      moving.forEach(function (card) {
        card.style.transition = "";
        card.classList.remove("q-rank-flying");
      });
    }, DURATION_MS + 40);
    var column = columnOf(root, bucket);
    flash(column, "data-flash");
    flash(column && column.querySelector("[data-rank-count]"), "data-pulse");
  }

  /* Wait for the moved card to be inside its new column, then play. `before` may carry
     the dragged card's release rectangle in place of its old slot. `onSettle` runs
     either way (rank-drag.js's own cleanup). */
  function expect(key, bucket, before, onSettle) {
    var root = board("cols");
    var done = false;
    function landed() {
      var column = columnOf(root, bucket);
      return (
        column &&
        Array.prototype.some.call(column.querySelectorAll(CARD), function (c) {
          return c.getAttribute("data-rank-key") === key;
        })
      );
    }
    function finish(ok) {
      if (done) return;
      done = true;
      observer.disconnect();
      if (onSettle) onSettle();
      if (ok) play(root, before, key, bucket);
      else cardsOf(root).forEach(function (card) {
        cleanCard(card);
        card.style.transition = "";
      });
    }
    var observer = new MutationObserver(function () {
      if (landed()) finish(true);
    });
    observer.observe(root || document.body, { childList: true, subtree: true });
    window.setTimeout(function () {
      finish(false);
    }, GIVE_UP_MS);
  }

  /* Tabs: a copy of the card flies to the target tab and fades; the tab pulses. */
  function flyToTab(card, bucket) {
    var tab = document.querySelector('[data-sort-tab="' + bucket + '"]');
    if (!card || !tab) return;
    if (reduced()) {
      flash(tab, "data-pulse");
      return;
    }
    var from = card.getBoundingClientRect();
    var to = tab.getBoundingClientRect();
    var ghost = card.cloneNode(true);
    // a copy for the eye only: no ids, roles, ARIA or Radix state, nothing focusable
    [ghost].concat(Array.prototype.slice.call(ghost.querySelectorAll("*"))).forEach(
      function (el) {
        Array.prototype.slice.call(el.attributes).forEach(function (attr) {
          var name = attr.name;
          if (
            name === "id" ||
            name === "role" ||
            name === "tabindex" ||
            name === "href" ||
            name.indexOf("aria-") === 0 ||
            name.indexOf("data-") === 0
          ) {
            el.removeAttribute(name);
          }
        });
      }
    );
    ghost.setAttribute("aria-hidden", "true");
    ghost.setAttribute("inert", "");
    ghost.className = card.className + " q-rank-ghost";
    ghost.style.cssText =
      "position:fixed;margin:0;z-index:50;pointer-events:none;" +
      "left:" + from.left + "px;top:" + from.top + "px;" +
      "width:" + from.width + "px;height:" + from.height + "px;";
    document.body.appendChild(ghost);
    card.style.opacity = "0"; // the real one is about to leave its list
    var dx = to.left + to.width / 2 - (from.left + from.width / 2);
    var dy = to.top + to.height / 2 - (from.top + from.height / 2);
    void ghost.offsetWidth;
    ghost.style.transition =
      "transform " + DURATION_MS + "ms " + EASE + ", opacity " + DURATION_MS + "ms " + EASE;
    ghost.style.transform = "translate(" + dx + "px, " + dy + "px) scale(0.35)";
    ghost.style.opacity = "0";
    window.setTimeout(function () {
      ghost.remove();
      flash(tab, "data-pulse");
      // if the server never moved it, the card comes back
      window.setTimeout(function () {
        card.style.opacity = "";
      }, GIVE_UP_MS);
    }, DURATION_MS);
  }

  /* «Mover a»: the menu item carries the account, the target and the board it was
     opened from. Capture phase: measured before React applies anything. */
  document.addEventListener(
    "click",
    function (e) {
      var item = e.target.closest && e.target.closest("[data-move-to]");
      if (!item || item.hasAttribute("data-disabled")) return;
      var key = item.getAttribute("data-move-key");
      var bucket = item.getAttribute("data-move-to");
      var where = item.getAttribute("data-move-board");
      var root = board(where);
      if (!root) return;
      if (where === "tabs") {
        var card = Array.prototype.find.call(cardsOf(root), function (c) {
          return c.getAttribute("data-rank-key") === key;
        });
        flyToTab(card, bucket);
        return;
      }
      expect(key, bucket, snapshot(root), null);
    },
    true
  );

  window.__qRankFlip = {
    /* For rank-drag.js: a card released over another column at `released` (its
       on-screen rectangle). */
    drop: function (key, bucket, released, onSettle) {
      var before = snapshot(board("cols"));
      if (released) before[key] = released;
      expect(key, bucket, before, onSettle);
    },
  };
})();
