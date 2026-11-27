/* «Arma tu video» on a phone (ED-10 m-25026648, UX note): the preview takes the height
   the step leaves, so the step's head, the preview, the timeline, its bar (its own box,
   `.q-edit__bar`) and the step's foot all show without scrolling the page — as big as it can be (Deivid: «la
   preview … es muy pequeña»), never under `MIN_PX`, never over 70 % of the screen.

   CSS alone cannot know how tall the step's head is: this measures, on the editor's
   own box (`.q-edit--timeline`), how far the bar's bottom is from the top of the fixed
   foot (`.q-step-slot`, or the window's bottom) and writes the frame's height in
   `--q-edit-frame-h` (`assets/qualify-creative.css` has a fallback without it). Only
   on a narrow step (the phone's layout): on a wide one the CSS sizes it. Measured in the flow
   (the page's scroll does not change it), again when a size changes. With a block
   chosen the CSS caps it lower, so its panel shows too.

   m-25026638 (second live test): it also writes the sticky preview's own height in
   `--q-edit-preview-h` (stacked only; on a wide step the preview scrolls with the page),
   so a panel or a field scrolled into view stops UNDER the preview, never behind it
   (`scroll-margin-top` in `assets/qualify-creative.css`).

   m-25026636 (live test): the timeline's bar (`.q-edit__bar`) pins right under that
   preview while stacked, so `--q-edit-bar-h` (its height) joins the panel's
   `scroll-margin-top`, and the bar's flow position is read from the timeline above it
   (pinned, its own box says where it is stuck). */
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

  function room(edit, name, el) {
    var h = el ? Math.ceil(el.getBoundingClientRect().height) : 0;
    var set = edit.style.getPropertyValue(name);
    if (h > 0) {
      if (set !== h + "px") edit.style.setProperty(name, h + "px");
    } else if (set) edit.style.removeProperty(name);
  }

  // the sticky preview's height — where the bar pins, and the panel's
  // `scroll-margin-top` — and the pinned bar's (m-25026636), "" = none
  function previewRoom(edit, on) {
    room(edit, "--q-edit-preview-h", on ? edit.querySelector(".q-edit__preview") : null);
    room(edit, "--q-edit-bar-h", on ? edit.querySelector(".q-edit__bar") : null);
  }

  // where the bar's bottom is in the flow, from the page's top: the timeline's bottom
  // (never sticky), the grid's gap and the bar's own height — the bar's box itself
  // reads where it is pinned while the page is scrolled (m-25026636)
  function barFlowBottom(edit, bar, shift) {
    var holder = edit.querySelector(".q-edit__bar");
    var timeline = edit.querySelector(".q-edit__timeline");
    if (!holder || !timeline) return bar.getBoundingClientRect().bottom + shift;
    var gap = parseFloat(getComputedStyle(edit).rowGap) || 0;
    var inner = bar.getBoundingClientRect().bottom - holder.getBoundingClientRect().top;
    return timeline.getBoundingClientRect().bottom + shift + gap + inner;
  }

  function fit(edit) {
    if (!edit.isConnected) return;
    var frame = edit.querySelector(".q-edit__preview .q-edit-preview__frame");
    var bar = edit.querySelector(".q-tl-stack__actions");
    var narrow = stacked(edit);
    if (!frame || !bar || !narrow) {
      edit.style.removeProperty("--q-edit-frame-h");
      previewRoom(edit, narrow);
      return;
    }
    var view = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    var foot = document.querySelector(".q-step-slot");
    var footTop = foot ? foot.getBoundingClientRect().top : view;
    var limit = Math.min(footTop, view) - GAP_PX;
    // where the bar's bottom would be with the page at its top (flow position)
    var shift = scrollTopOf(edit);
    var barBottom = barFlowBottom(edit, bar, shift);
    var now = frame.getBoundingClientRect().height;
    var want = Math.round(now + (limit - barBottom));
    want = Math.max(MIN_PX, Math.min(want, Math.round(view * MAX_SHARE)));
    var set = parseFloat(edit.style.getPropertyValue("--q-edit-frame-h")) || 0;
    if (Math.abs(set - want) > 2) edit.style.setProperty("--q-edit-frame-h", want + "px");
    // measured once the frame has its height: where the bar pins depends on it
    previewRoom(edit, narrow);
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
      var preview = edit.querySelector(".q-edit__preview");
      if (preview) edit.__qRoom.observe(preview);
      var pinned = edit.querySelector(".q-edit__bar");
      if (pinned) edit.__qRoom.observe(pinned);
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
