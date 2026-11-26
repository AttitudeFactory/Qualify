/* Mockups del editor único: íconos, la línea de tiempo desde una especificación corta y
   cada pantalla dibujada dos veces (celular de 375 px y escritorio). Solo para mirar. */
(function () {
  "use strict";
  var P = {
    sparkles: '<path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.13-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.13a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.13 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.13a.5.5 0 0 1-.96 0z"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    type: '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    trash: '<path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/>',
    rotatecw: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    retry: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    copy: '<rect x="8" y="8" width="14" height="14" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    follow: '<path d="m15 10 5 5-5 5"/><path d="M4 4v7a4 4 0 0 0 4 4h12"/>',
    play: '<path d="M7 4v16l13-8z" fill="currentColor"/>',
    bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6M10 22h4"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    merge: '<path d="m8 6 4-4 4 4"/><path d="M12 2v10.3a4 4 0 0 1-1.17 2.87L4 22"/><path d="m20 22-5-5"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    pencil: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    ext: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    blend: '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
    cut: '<path d="M12 3v18"/>',
    wallet: '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'
  };
  // Text read from the page (JSON specs, data-* attributes) is escaped before it is
  // laid as HTML, so a mockup can never run markup it carries (CodeQL js/xss-through-dom).
  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function clean(value) {
    if (typeof value === "string") return esc(value);
    if (Array.isArray(value)) return value.map(clean);
    if (value && typeof value === "object") {
      var out = {};
      Object.keys(value).forEach(function (k) { out[k] = clean(value[k]); });
      return out;
    }
    return value;
  }
  function readSpec(el) { return clean(JSON.parse(el.textContent)); }

  function icon(name, cls) {
    return '<svg class="i ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (P[name] || "") + "</svg>";
  }
  window.mkIcon = icon;

  var MODES = {
    new: ["sparkles", "Nueva"],
    same: ["copy", "Igual al original"],
    follow: ["follow", "Sigue a la anterior"]
  };
  var STATES = {
    queued: ["neutral", "En fila"],
    creating: ["info", "Creando"],
    review: ["warn", "Para revisar"],
    ready: ["ok", "Lista"],
    liked: ["ok", "✓ Lista"],
    failed: ["error", "No salió"],
    refused: ["warn", "No se pudo con el original"],
    redo: ["warn", "Hay que rehacerla"],
    expired: ["warn", "Venció"]
  };
  function clock(s) {
    s = Math.round(s * 10) / 10;
    var m = Math.floor(s / 60), r = s - m * 60;
    var whole = Math.floor(r), half = r - whole >= 0.5 ? "" : "";
    return m + ":" + (whole < 10 ? "0" : "") + whole + half;
  }
  function secs(n) { return (Math.round(n * 2) / 2).toString().replace(".", ",") + " s"; }

  function mediaBlock(b, chosen) {
    var picked = b.id === chosen;
    var style = "--b-start:" + b.start + ";--b-len:" + b.len + (b.in ? ";--b-in:" + b.in : "");
    var inner = "", aria = "", attrs = "";
    if (b.kind === "ai") {
      var m = MODES[b.mode || "new"], st = b.state || "plan";
      var stateTxt = st === "plan" ? "sin crear" : STATES[st][1];
      aria = b.name + ", " + m[1] + ", de " + clock(b.start) + " a " + clock(b.start + b.len) + ", " + stateTxt;
      var line2;
      if (st === "plan") {
        line2 = '<span class="q-tl__chip"><span class="q-tl__label">' + b.name + '</span><span class="q-tl__secs"> · ' + secs(b.len) + "</span></span>";
      } else {
        var t = STATES[st];
        line2 = '<span class="q-tl__state" data-tone="' + t[0] + '">' + (st === "creating" ? '<span class="spin"></span>' : (st === "queued" ? icon("clock", "sm") : "")) +
          '<span class="q-tl__state-word">' + t[1] + "</span></span>";
      }
      inner = '<span class="q-tl__pic ' + (b.pic || "pic-reel") + '"></span>' +
        '<span class="q-tl__ai-line"><span class="q-tl__mode" title="' + m[1] + '">' + icon("sparkles") + icon(m[0]) + '<span class="q-tl__mode-word">' + m[1] + "</span></span></span>" +
        '<span class="q-tl__ai-line">' + line2 + "</span>";
      attrs = ' data-tl-block="ai" data-ai-state="' + st + '"';
    } else {
      var kind = b.kind === "photo" ? "photo" : "video";
      aria = b.name + ", de " + clock(b.start) + " a " + clock(b.start + b.len);
      inner = '<span class="q-tl__pic ' + (b.pic || "pic-a") + '"></span><span class="q-tl__chip">' + icon(kind === "photo" ? "image" : "film", "sm") +
        '<span class="q-tl__label">' + b.name + '</span><span class="q-tl__secs"> · ' + secs(b.len) + (b.speed ? " · " + b.speed : "") + "</span></span>";
      attrs = ' data-tl-block="' + kind + '"';
    }
    var handles = picked ? '<span class="q-tl__handle q-tl__handle--start" role="slider" aria-label="Inicio de ' + b.name + '"><span class="q-tl__grip"></span></span>' +
      '<span class="q-tl__handle q-tl__handle--end" role="slider" aria-label="Final de ' + b.name + '"><span class="q-tl__grip"></span></span>' : "";
    return '<div class="q-tl__item"' + (b.in ? ' data-tl-in="1"' : "") + ' data-tl-chosen="' + picked + '" style="' + style + '">' +
      (b.in ? '<span class="q-tl__overlap"></span>' : "") +
      '<button type="button" class="q-tl__block"' + attrs + ' aria-pressed="' + picked + '" aria-label="' + aria + '">' + inner + "</button>" + handles + "</div>";
  }
  function layerBlock(b, kind, chosen) {
    var picked = b.id === chosen;
    var ic = kind === "text" ? '<span style="font-weight:700">Aa</span>' : icon("cloud", "sm");
    return '<div class="q-tl__item" data-tl-chosen="' + picked + '" style="--b-start:' + b.start + ";--b-len:" + b.len + '">' +
      '<button type="button" class="q-tl__block" data-tl-block="' + kind + '" aria-pressed="' + picked + '" aria-label="' + b.name + '">' + ic +
      '<span class="q-tl__label">' + b.name + "</span></button></div>";
  }
  function timeline(spec) {
    var total = spec.total, ticks = "";
    for (var s = 0; s <= total; s += 2) ticks += '<span class="q-tl__tick" style="--b-start:' + s + '">' + clock(s) + "</span>";
    var media = spec.media.map(function (b) { return mediaBlock(b, spec.chosen); }).join("");
    var ch = spec.media.filter(function (b) { return b.id === spec.chosen; })[0];
    // as today: a join point touching the chosen block hides (its handles sit there)
    var joins = (spec.joins || []).filter(function (j) {
      return !ch || (Math.abs(j.at - ch.start) > 0.8 && Math.abs(j.at - ch.start - ch.len) > 0.8);
    }).map(function (j) {
      var kindIcon = j.kind === "fundido" ? icon("blend") : "";
      return '<button type="button" class="q-tl__join" data-join-kind="' + j.kind + '" style="--j-at:' + j.at + '" aria-label="' + j.label + '"><span class="q-tl__join-dot">' + kindIcon + "</span></button>";
    }).join("");
    var texts = (spec.texts || []).map(function (b) { return layerBlock(b, "text", spec.chosen); }).join("");
    var effects = (spec.effects || []).map(function (b) { return layerBlock(b, "effect", spec.chosen); }).join("");
    var empty = function (xs, name) { return xs ? "" : ' aria-label="' + name + '"'; };
    return '<div class="q-tl" data-t="' + (spec.t || 0) + '" role="group" aria-label="Línea de tiempo de tu video">' +
      '<div class="q-tl__top"><span class="q-tl__clock q-nums">' + clock(spec.t || 0) + " de " + clock(total) + "</span></div>" +
      '<div class="q-tl__frame"><div class="q-tl__names" aria-hidden="true"><span class="q-tl__name q-tl__name--ruler"></span><span class="q-tl__name q-tl__name--media">Fotos y videos</span><span class="q-tl__name">Textos</span><span class="q-tl__name">Efectos</span></div>' +
      '<div class="q-tl__scroller"><div class="q-tl__canvas" style="--tl-total:' + total + ";--tl-t:" + (spec.t || 0) + '">' +
      '<div class="q-tl__ruler">' + ticks + "</div>" +
      '<div class="q-tl__media"><div class="q-tl__lane q-tl__lane--media" role="list" aria-label="Fotos y videos">' + media + '</div><div class="q-tl__joins">' + joins + "</div></div>" +
      '<div class="q-tl__lane" role="list"' + empty(spec.texts, "Pista de textos vacía") + ">" + texts + "</div>" +
      '<div class="q-tl__lane" role="list"' + empty(spec.effects, "Pista de efectos vacía") + ">" + effects + "</div>" +
      '<span class="q-tl__head q-tl__head--move"></span></div></div>' +
      '<span class="q-tl__head q-tl__head--fixed"></span></div>' +
      '<p class="q-tl__status" role="status">' + (spec.status || "") + "</p></div>";
  }
  window.mkTimeline = timeline;

  function hydrate(root) {
    root.querySelectorAll("[data-i]").forEach(function (el) { el.outerHTML = icon(esc(el.getAttribute("data-i") || ""), esc(el.getAttribute("data-c") || "")); });
    root.querySelectorAll("script[type='application/json'][data-tl]").forEach(function (el) {
      var spec = readSpec(el);
      var box = document.createElement("div");
      box.innerHTML = timeline(spec);
      el.replaceWith(box.firstChild);
    });
    root.querySelectorAll("script[type='application/json'][data-sample]").forEach(function (el) {
      var b = readSpec(el);
      var box = document.createElement("div");
      box.className = "mk-sample";
      box.innerHTML = '<div class="q-tl__lane q-tl__lane--media" style="width:' + b.w + 'px">' +
        mediaBlock(b, b.chosen ? b.id : "").replace('style="', 'style="left:0;width:100%;') + '</div><span class="mk-sample__cap">' + (b.cap || "") + "</span>";
      el.replaceWith(box);
    });
  }
  function place(root) {
    root.querySelectorAll(".q-tl").forEach(function (tl) {
      var sc = tl.querySelector(".q-tl__scroller");
      var t = parseFloat(tl.getAttribute("data-t") || "0");
      if (sc && sc.scrollWidth > sc.clientWidth + 2) sc.scrollLeft = t * 44;
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-pair]").forEach(function (pair) {
      var tpl = document.getElementById(pair.getAttribute("data-pair"));
      var notePhone = esc(pair.getAttribute("data-note-phone") || ""), noteDesk = esc(pair.getAttribute("data-note-desk") || "");
      [["phone", "Celular · 375 px", notePhone], ["desk", "Escritorio", noteDesk]].forEach(function (d) {
        var col = document.createElement("div");
        col.className = "mk-col" + (d[0] === "desk" ? " mk-col--desk" : "");
        if (d[0] === "desk") col.style.flex = "1 1 760px";
        col.innerHTML = '<span class="mk-cap">' + d[1] + '</span><div class="dev dev--' + d[0] + '"></div>' + (d[2] ? '<p class="mk-note">' + d[2] + "</p>" : "");
        col.querySelector(".dev").appendChild(tpl.content.cloneNode(true));
        pair.appendChild(col);
      });
      hydrate(pair);
    });
    hydrate(document.body);
    requestAnimationFrame(function () { place(document); });
  });
})();
