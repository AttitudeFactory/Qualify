/* ED-13 (m-25029108, Deivid 2026-11-24): «palabra demasiado larga para la pantalla» in the
   text's panel, BEFORE the final video — with the final video's own criterion
   (`packages/render/src/templates/video_text/layout.ts`, `engine.ts` `word_too_wide`): a
   word is refused when, at the smallest title size of its letter size (76 px of 1080 ×
   `SIZE_SCALE`: 57 · 76 · 95), it is wider than the safe zone (952 px of 1080). Measured
   here with the same typography the preview draws (the brand's, `.q-edit-preview__text-line`
   bold), so the panel and the render agree.

   The panel renders an empty `[data-text-fit]` line carrying `data-text`, `data-size` and
   `data-line` (the sentence, `{word}` its place); this script fills it — React never
   renders children there — or empties it (`:empty` is not shown). Sent by `rx.call_script`
   when the panel mounts; the guard keeps one observer. `module.exports` for the node tests. */
(function (root) {
  "use strict";

  var SAFE_WIDTH = 952; // px of the 1080-wide canvas: x 64–1016
  var MIN_PX = { small: 57, medium: 76, large: 95 }; // 76 × SIZE_SCALE
  var SHOWN_MAX = 24; // a word longer than this is shown cut, with «…»

  /* The widest word of `text` that does not fit at `size`'s smallest letters, or "".
     `measure(word)` is its width in px at 100 px. */
  function widest(text, size, measure) {
    var px = MIN_PX[size] || MIN_PX.medium;
    var worst = "";
    var worstWidth = SAFE_WIDTH;
    String(text || "")
      .split(/\s+/)
      .forEach(function (word) {
        if (!word) return;
        var width = (measure(word) * px) / 100;
        if (width > worstWidth) {
          worst = word;
          worstWidth = width;
        }
      });
    return worst;
  }

  function shown(word) {
    return word.length > SHOWN_MAX ? word.slice(0, SHOWN_MAX - 1) + "…" : word;
  }

  var api = { widest: widest, shown: shown, SAFE_WIDTH: SAFE_WIDTH, MIN_PX: MIN_PX };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
    return;
  }
  if (root.__qTextFit) return;
  root.__qTextFit = api;

  var canvas = null;
  function family() {
    var line = document.querySelector(".q-edit-preview__text-line");
    return line ? getComputedStyle(line).fontFamily : getComputedStyle(document.body).fontFamily;
  }
  function measurer(fam) {
    canvas = canvas || document.createElement("canvas");
    var ctx = canvas.getContext("2d");
    ctx.font = "700 100px " + fam;
    return function (word) {
      return ctx.measureText(word).width;
    };
  }

  function check() {
    var notes = document.querySelectorAll("[data-text-fit]");
    if (!notes.length) return;
    var fam = family();
    var measure = measurer(fam);
    Array.prototype.forEach.call(notes, function (note) {
      var word = widest(note.getAttribute("data-text"), note.getAttribute("data-size"), measure);
      var said = word ? (note.getAttribute("data-line") || "").replace("{word}", shown(word)) : "";
      if (note.textContent !== said) note.textContent = said; // empty = not shown (CSS)
    });
  }

  /* Once per burst of changes (a keystroke, the preview's typing): a timer, not
     `requestAnimationFrame` — that one never runs while the page is in the background. */
  var pending = false;
  function soon() {
    if (pending) return;
    pending = true;
    setTimeout(function () {
      pending = false;
      check();
    }, 60);
  }

  new MutationObserver(soon).observe(document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["data-text", "data-size"],
  });
  // the brand's font arrives after the panel: measure again with it
  if (document.fonts) {
    document.fonts.addEventListener("loadingdone", soon);
    document.fonts.ready.then(soon);
  }
  soon();
})(typeof window !== "undefined" ? window : this);
