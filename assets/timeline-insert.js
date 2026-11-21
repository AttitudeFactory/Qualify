/* ED-12 (m-25029107): photos and videos of the computer dropped on «Fotos y videos», on
   a desktop — «Arma tu video»'s `ui.timeline`. The math is `assets/timeline-drag-core.js`
   (`insertIndex`, `carriesFiles`, tested with node).

   Files of the computer dragged over the timeline (`[data-tl-insert-zone]`) get a line
   that marks the gap they land in (`.q-tl__insert`); dropped, the screen first hears
   `("", "place", index)` through the timeline's hidden drop button
   (`ui.timeline._drag_trigger`, as `timeline-drag.js` reports a move) and then the
   zone's own upload (`ui.dropzone` «section» around the timeline, react-dropzone) sends
   them through the Clip's «Subir» (`CreativeState.handle_clip_timeline_uploads`), which
   puts them in that gap. A file that is not a photo or a video is refused by the zone
   and the live line says so. The gap is read from the blocks' middles in the media row
   whatever row the pointer is over. No animation: the line only appears and goes
   (reduced motion needs nothing). A phone drags no files: «+ Foto o video». The guard
   keeps one set of document listeners. */
(function () {
  "use strict";
  if (window.__qTimelineInsert) return;
  window.__qTimelineInsert = true;

  var current = null; // {zone, line} while a drag is over a timeline

  function core() {
    return window.__qTimelineDragCore;
  }

  function zoneOf(el) {
    return el && el.closest ? el.closest("[data-tl-insert-zone]") : null;
  }

  function parts(zone) {
    var root = zone ? zone.querySelector("[data-q-timeline]") : null;
    var lane = root ? root.querySelector(".q-tl__lane--media") : null;
    return { root: root, lane: lane };
  }

  function items(lane) {
    return Array.prototype.slice.call(lane.querySelectorAll(":scope > .q-tl__item"));
  }

  // The gap under `clientX`: the blocks' middles in client px.
  function gapAt(lane, clientX) {
    var mids = items(lane).map(function (it) {
      var box = it.getBoundingClientRect();
      return box.left + box.width / 2;
    });
    return core().insertIndex(mids, clientX);
  }

  // Where the line goes for gap `index`, in px from the media row's left edge.
  function lineX(lane, index) {
    var all = items(lane);
    var laneBox = lane.getBoundingClientRect();
    if (!all.length) return 0;
    if (index < all.length) return all[index].getBoundingClientRect().left - laneBox.left;
    return all[all.length - 1].getBoundingClientRect().right - laneBox.left;
  }

  function clear() {
    if (current && current.line && current.line.parentNode) {
      current.line.parentNode.removeChild(current.line);
    }
    current = null;
  }

  function paint(zone, lane, index) {
    if (!current || current.zone !== zone) {
      clear();
      var line = document.createElement("span");
      line.className = "q-tl__insert";
      line.setAttribute("aria-hidden", "true");
      current = { zone: zone, line: line };
    }
    if (current.line.parentNode !== lane) lane.appendChild(current.line);
    current.line.style.left = lineX(lane, index) + "px";
  }

  function report(root, id, what, value) {
    var trigger = root.querySelector("[data-tl-drag-trigger]");
    if (!trigger) return;
    window.__qTimelineDrop = { id: id, what: what, value: value };
    trigger.click();
  }

  document.addEventListener(
    "dragover",
    function (e) {
      var zone = zoneOf(e.target);
      var files = !!e.dataTransfer && core().carriesFiles(e.dataTransfer.types);
      if (!zone || !files) {
        if (current && !zone) clear();
        return;
      }
      var p = parts(zone);
      if (!p.root || !p.lane || p.root.hasAttribute("data-tl-no-drag")) return;
      e.preventDefault(); // a drop is allowed here
      e.dataTransfer.dropEffect = "copy";
      paint(zone, p.lane, gapAt(p.lane, e.clientX));
    },
    true
  );

  document.addEventListener(
    "dragleave",
    function (e) {
      if (!current) return;
      var into = e.relatedTarget;
      if (!into || !current.zone.contains(into)) clear();
    },
    true
  );

  document.addEventListener(
    "drop",
    function (e) {
      var zone = zoneOf(e.target);
      var files = !!e.dataTransfer && core().carriesFiles(e.dataTransfer.types);
      clear();
      if (!zone || !files) return;
      var p = parts(zone);
      if (!p.root || !p.lane || p.root.hasAttribute("data-tl-no-drag")) return;
      // the gap first; the zone's upload goes right after it
      report(p.root, "", "place", gapAt(p.lane, e.clientX));
    },
    true
  );

  document.addEventListener("dragend", clear, true);
})();
