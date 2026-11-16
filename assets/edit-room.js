/* «Arma tu video» on a phone (ED-10 m-25026648, UX note): the preview takes the height
   the step leaves, so the step's head, the preview, the timeline with its bar and the
   step's foot all show without scrolling the page — as big as it can be (Deivid: «la
   preview … es muy pequeña»), never under `MIN_PX`, never over 70 % of the screen.

   CSS alone cannot know how tall the step's head is: this measures, on the editor's
   own box (`.q-edit--timeline`), how far the bar's bottom is from the top of the fixed
   foot (`.q-step-slot`, or the window's bottom) and writes the frame's height in
   `--q-edit-frame-h` (`assets/qualify-creative.css` has a fallback without it). Only
   on a narrow step (the phone's layout): on a wide one the CSS sizes it. Measured in the flow
   (the page's scroll does not change it), again when a size changes. With a block
   chosen the CSS caps it lower, so its panel shows too. */
(function () {
  "use strict";
  var MIN_PX = 144;
  var MAX_SHARE = 0.7;
  var GAP_PX = 8; // between the bar and the foot

  // The phone's layout: a step narrower than the container query's 46rem. On a wide
  // step the preview is centred over the timeline and the CSS sizes it (Deivid,
  // 2026-11-16) — one column at every size now, so the width decides, not the boxes.
  var WIDE_REM = 46;

  function stacked(edit) {
    var host = edit.closest(".q-edit-host") || edit.parentElement;
    if (!host || !edit.querySelector(".q-edit__preview")) return false;
    var rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    return host.getBoundingClientRect().width < WIDE_REM * rem;
  }

  function scrollTopOf(el) {
    var top = 0;
    for (var node = el.parentElement; node; node = node.parentElement) top += node.scrollTop || 0;
    return top + (window.scrollY || 0);
  }

  function fit(edit) {
    if (!edit.isConnected) return;
    var frame = edit.querySelector(".q-edit__preview .q-edit-preview__frame");
    var bar = edit.querySelector(".q-tl-stack__actions");
    if (!frame || !bar || !stacked(edit)) {
      edit.style.removeProperty("--q-edit-frame-h");
      return;
    }
    var view = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    var foot = document.querySelector(".q-step-slot");
    var footTop = foot ? foot.getBoundingClientRect().top : view;
    var limit = Math.min(footTop, view) - GAP_PX;
    // where the bar's bottom would be with the page at its top (flow position)
    var shift = scrollTopOf(edit);
    var barBottom = bar.getBoundingClientRect().bottom + shift;
    var now = frame.getBoundingClientRect().height;
    var want = Math.round(now + (limit - barBottom));
    want = Math.max(MIN_PX, Math.min(want, Math.round(view * MAX_SHARE)));
    var set = parseFloat(edit.style.getPropertyValue("--q-edit-frame-h")) || 0;
    if (Math.abs(set - want) > 2) edit.style.setProperty("--q-edit-frame-h", want + "px");
  }

  function attach(edit) {
    if (edit.__qRoom) {
      fit(edit);
      return;
    }
    var pending = false;
    function later() {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(function () {
        pending = false;
        if (!edit.isConnected) {
          if (edit.__qRoom) edit.__qRoom.disconnect();
          window.removeEventListener("resize", later);
          return;
        }
        fit(edit);
      });
    }
    edit.__qRoom = window.ResizeObserver ? new ResizeObserver(later) : { disconnect: function () {} };
    if (window.ResizeObserver) {
      var timeline = edit.querySelector(".q-edit__timeline");
      if (timeline) edit.__qRoom.observe(timeline);
      edit.__qRoom.observe(edit);
    }
    window.addEventListener("resize", later);
    later();
  }

  window.__qEditRoom = function () {
    var all = document.querySelectorAll(".q-edit--timeline");
    for (var i = 0; i < all.length; i++) attach(all[i]);
  };
  window.__qEditRoom();
})();
