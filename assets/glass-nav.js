/*
 * Liquid glass menu — the capsule that moves between the sidebar's rows, and the
 * glass label that pops out beside the rail in zen mode.
 *
 * Adapted from new_branding/real-liquid-glass-os-effect.html (a horizontal dock) to
 * `Qualify/ui/layout.py`'s vertical islands. The styles live in assets/qualify.css,
 * "Liquid glass menu"; this file only measures rows and moves two elements:
 *
 *   - `.q-glass-blob`, ONE PER ISLAND, appended to the island itself. It has to be a
 *     child of its island: `backdrop-filter` makes every island a stacking context, so
 *     a capsule outside could only paint over a whole island or under it, never
 *     between the island's fill and its rows. Crossing islands hands over: the old
 *     capsule fades out, the new one slides in from the edge it enters through.
 *   - `.q-glass-label`, one per document, fixed in the viewport (the nav clips its
 *     own overflow). Shown only while the rail is collapsed (`.q-zen`) and only for a
 *     real pointer — on a touch screen a label under the finger says nothing.
 *
 * Choreography (the dock's own timings): the word leaves first, the capsule starts
 * ~40 ms later, the new word grows once the capsule has nearly landed (~235 ms).
 * Resting state = the active row (`aria-current="page"` on the row's link), with no
 * word — the menu stays quiet when nobody is on it.
 *
 * Everything is delegated at the document and re-settled on DOM mutations, so it
 * survives Reflex re-mounting the sidebar on every route change and the rail's width
 * transition on zen (a ResizeObserver follows the islands while they shrink).
 */
(function () {
  if (window.__qGlassNav) return;
  window.__qGlassNav = true;

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var coarsePointer = window.matchMedia('(pointer: coarse)').matches;

  var sequence = 0; // bumps on every intent; stale timers compare against it
  var moveTimer = null;
  var labelTimer = null;
  var leaveTimer = null;
  var current = null; // the row the capsule is on
  var hovered = null; // the row under the pointer, if any
  var label = null; // the one floating label

  function navOf(node) { return node.closest ? node.closest('.q-sidebar') : null; }
  function islandOf(row) { return row.closest('.q-island'); }
  function rowsOf(nav) { return nav.querySelectorAll('.q-nav-item'); }
  function activeRow(nav) { return nav.querySelector('[aria-current="page"] .q-nav-item'); }
  function isRow(node) {
    var row = node && node.closest ? node.closest('.q-sidebar .q-nav-item') : null;
    if (!row || row.getAttribute('aria-disabled') === 'true') return null;
    return row;
  }

  function blobOf(island) {
    var blob = island.querySelector(':scope > .q-glass-blob');
    if (!blob) {
      blob = document.createElement('div');
      blob.className = 'q-glass-blob';
      blob.setAttribute('aria-hidden', 'true');
      var surface = document.createElement('div');
      surface.className = 'q-glass-blob__surface';
      blob.appendChild(surface);
      island.appendChild(blob);
    }
    return blob;
  }

  /* The row's box in its island's padding-box coordinates (what `position: absolute`
     resolves against), one pixel wider on every side like the dock's capsule. */
  function geometry(row, island) {
    var r = row.getBoundingClientRect();
    var i = island.getBoundingClientRect();
    return {
      left: r.left - i.left - island.clientLeft - 1,
      top: r.top - i.top - island.clientTop - 1,
      width: r.width + 2,
      height: r.height + 2
    };
  }

  function setBox(blob, box) {
    blob.style.left = box.left + 'px';
    blob.style.top = box.top + 'px';
    blob.style.width = box.width + 'px';
    blob.style.height = box.height + 'px';
  }

  function hideOthers(nav, keep) {
    nav.querySelectorAll('.q-glass-blob').forEach(function (b) {
      if (b !== keep) b.classList.remove('is-on');
    });
  }

  function markHover(nav, row) {
    rowsOf(nav).forEach(function (r) { r.classList.toggle('is-glass-hover', r === row); });
  }

  /* Move the capsule to `row`. `opts.instant`: no glide (first paint, resize, zen).
     `opts.rest`: the row is the resting place, so no hover lift on its icon. */
  function moveTo(row, opts) {
    opts = opts || {};
    var nav = navOf(row);
    var island = islandOf(row);
    if (!nav || !island) return;
    nav.setAttribute('data-glass', '');
    var blob = blobOf(island);
    var box = geometry(row, island);

    var direction = 0;
    if (current && current !== row && current.isConnected) {
      direction = row.getBoundingClientRect().top > current.getBoundingClientRect().top ? 1 : -1;
    }
    var crossing = !current || !current.isConnected || islandOf(current) !== island ||
      !blob.classList.contains('is-on');

    if (opts.instant || crossing) {
      // Start where the capsule should appear from, without any transition: at the
      // target (instant), or just outside the island's edge it is entering through.
      var start = { left: box.left, top: box.top, width: box.width, height: box.height };
      if (!opts.instant && !reduceMotion && direction > 0) start.top = -box.height;
      if (!opts.instant && !reduceMotion && direction < 0) start.top = island.clientHeight;
      blob.classList.add('q-no-anim');
      blob.classList.remove('move-up', 'move-down');
      setBox(blob, start);
      blob.classList.add('is-on');
      void blob.offsetWidth; // commit the start box before the transition is back on
      blob.classList.remove('q-no-anim');
    }

    hideOthers(nav, blob);
    blob.classList.remove('move-up', 'move-down');
    void blob.offsetWidth; // restart the squash even when the previous one is mid-way
    if (!opts.instant && !reduceMotion && direction > 0) blob.classList.add('move-down');
    if (!opts.instant && !reduceMotion && direction < 0) blob.classList.add('move-up');
    setBox(blob, box);
    blob.classList.add('is-on');
    clearTimeout(moveTimer);
    moveTimer = setTimeout(function () { blob.classList.remove('move-up', 'move-down'); }, 500);

    markHover(nav, opts.rest ? null : row);
    current = row;
  }

  function clearCapsules(nav) {
    hideOthers(nav, null);
    markHover(nav, null);
    current = null;
  }

  // ── The zen label ────────────────────────────────────────────────────────────

  function ensureLabel() {
    if (label) return label;
    label = document.createElement('div');
    label.className = 'q-glass-label';
    label.setAttribute('aria-hidden', 'true');
    label.innerHTML =
      '<span class="q-glass-label__neck"></span>' +
      '<div class="q-glass-label__glass"><span class="q-glass-label__text"></span></div>';
    // Inside the Radix root, not on <body>: the material's custom properties (and the
    // gray scale the text uses) are declared on `.radix-themes`, so a label outside it
    // would render with no glass at all. `position: fixed` still measures the viewport.
    (document.querySelector('.radix-themes') || document.body).appendChild(label);
    return label;
  }

  function hideLabel() {
    clearTimeout(labelTimer);
    if (label) label.classList.remove('is-visible');
  }

  function showLabel(row, token) {
    if (token !== sequence) return;
    var nav = navOf(row);
    if (!nav || !nav.classList.contains('q-zen') || coarsePointer) return;
    var text = row.getAttribute('data-label') || row.textContent.trim();
    if (!text) return;
    var el = ensureLabel();
    var r = row.getBoundingClientRect();
    el.querySelector('.q-glass-label__text').textContent = text;
    el.style.left = (r.right + 14) + 'px';
    el.style.top = (r.top + r.height / 2) + 'px';
    requestAnimationFrame(function () {
      if (token === sequence) el.classList.add('is-visible');
    });
  }

  // ── Choreography ─────────────────────────────────────────────────────────────

  function hover(row) {
    clearTimeout(leaveTimer);
    sequence += 1;
    var token = sequence;
    hideLabel(); // phase 1: the existing word gets out of the way
    setTimeout(function () { // phase 2: the glass starts moving almost immediately
      if (token === sequence) moveTo(row, {});
    }, 40);
    labelTimer = setTimeout(function () { // phase 3: the new word grows once it lands
      showLabel(row, token);
    }, 235);
  }

  function rest(nav) {
    sequence += 1;
    var token = sequence;
    hideLabel();
    setTimeout(function () {
      if (token !== sequence) return;
      var active = activeRow(nav);
      if (active) moveTo(active, { rest: true });
      else clearCapsules(nav);
    }, 45);
  }

  /* Instant placement: first paint, a route change (the nav re-mounts), the zen
     width transition, a window resize. Keeps the row under the pointer if there is
     one, so a re-render under a hover does not snap the capsule away. */
  function settle(nav) {
    var target = (hovered && nav.contains(hovered)) ? hovered : activeRow(nav);
    hideLabel();
    current = null;
    if (target) moveTo(target, { instant: true, rest: target !== hovered });
    else clearCapsules(nav);
  }

  // ── Events ───────────────────────────────────────────────────────────────────

  document.addEventListener('pointerover', function (event) {
    var row = isRow(event.target);
    if (!row || row === hovered) return;
    hovered = row;
    hover(row);
  });

  document.addEventListener('pointerout', function (event) {
    var nav = navOf(event.target);
    if (!nav) return;
    var to = event.relatedTarget;
    if (to && nav.contains(to)) return; // still inside the menu
    hovered = null;
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(function () { rest(nav); }, 120);
  });

  // Keyboard: focus lands on the row's link or button, the row is inside it.
  document.addEventListener('focusin', function (event) {
    var nav = navOf(event.target);
    if (!nav) return;
    var wrap = event.target.closest('a, button');
    var row = wrap ? wrap.querySelector('.q-nav-item') : null;
    if (!row || row.getAttribute('aria-disabled') === 'true' || row === hovered) return;
    hovered = row;
    hover(row);
  });

  document.addEventListener('focusout', function (event) {
    var nav = navOf(event.target);
    if (!nav) return;
    var to = event.relatedTarget;
    if (to && nav.contains(to)) return;
    hovered = null;
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(function () { rest(nav); }, 120);
  });

  // ── Pointer highlight ────────────────────────────────────────────────────────
  // The Lab's "liquid" fill has a soft light that follows the pointer
  // (`--q-pointer-x/y`, read by `--q-glass-fill` in qualify.css). Delegated at the
  // document like the kit's own `initLiquidPointers`; off for touch and reduced motion.

  if (!reduceMotion && !coarsePointer) {
    document.addEventListener('pointermove', function (event) {
      var island = event.target.closest ? event.target.closest('.q-island') : null;
      if (!island) return;
      var rect = island.getBoundingClientRect();
      island.style.setProperty('--q-pointer-x', ((event.clientX - rect.left) / rect.width * 100) + '%');
      island.style.setProperty('--q-pointer-y', ((event.clientY - rect.top) / rect.height * 100) + '%');
    }, { passive: true });
  }

  // ── Mount, re-mount, resize ──────────────────────────────────────────────────

  var pendingSettle = null;
  function scheduleSettle() {
    if (pendingSettle) return;
    pendingSettle = requestAnimationFrame(function () {
      pendingSettle = null;
      document.querySelectorAll('.q-sidebar').forEach(settle);
    });
  }

  var resizeObserver = ('ResizeObserver' in window) ? new ResizeObserver(scheduleSettle) : null;
  var watched = new WeakSet();
  function watch() {
    document.querySelectorAll('.q-sidebar').forEach(function (nav) {
      if (watched.has(nav)) return;
      watched.add(nav);
      if (resizeObserver) resizeObserver.observe(nav);
      nav.addEventListener('scroll', hideLabel, { passive: true });
    });
    scheduleSettle();
  }

  /* Only a mutation that touches a sidebar re-settles the capsule — a re-render of the
     page panel must not snap it away from the row under the pointer, and the nodes
     this script adds itself (a capsule, the label) must not trigger a settle either:
     that would cancel the very glide they were created for. */
  function isOurs(node) {
    return node.nodeType === 1 &&
      (node.classList.contains('q-glass-blob') || node.classList.contains('q-glass-label'));
  }
  function touchesSidebar(node) {
    return node.nodeType === 1 &&
      (node.matches('.q-sidebar') || !!node.querySelector('.q-sidebar') || !!navOf(node));
  }
  function relevant(records) {
    for (var i = 0; i < records.length; i += 1) {
      var record = records[i];
      /* m-24852260: the active row can change by attribute alone (`aria-current` moving
         between links that stay in place), which no childList record reports. */
      if (record.type === 'attributes') {
        if (navOf(record.target)) return true;
        continue;
      }
      var added = Array.prototype.slice.call(record.addedNodes);
      var removed = Array.prototype.slice.call(record.removedNodes);
      if (added.concat(removed).every(isOurs)) continue;
      if (record.target && record.target.nodeType === 1 && navOf(record.target)) return true;
      if (added.some(touchesSidebar) || removed.some(touchesSidebar)) return true;
    }
    return false;
  }
  new MutationObserver(function (records) {
    if (relevant(records)) watch();
  }).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['aria-current']
  });
  window.addEventListener('resize', scheduleSettle, { passive: true });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', watch, { once: true });
  } else {
    watch();
  }
})();
