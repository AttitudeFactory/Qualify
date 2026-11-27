/* Mockups de las pistas de referencias (m-25142725): íconos, la línea de tiempo desde una
   especificación corta y cada pantalla dibujada dos veces (celular de 375 px y escritorio).
   Basado en mock.js de los mockups firmados del editor único. Solo para mirar. */
(function () {
  "use strict";
  var P = {
    sparkles: '<path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.13-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.13a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.13 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.13a.5.5 0 0 1-.96 0z"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    tag: '<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r="1"/>',
    type: '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    trash: '<path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    copy: '<rect x="8" y="8" width="14" height="14" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    follow: '<path d="m15 10 5 5-5 5"/><path d="M4 4v7a4 4 0 0 0 4 4h12"/>',
    play: '<path d="M7 4v16l13-8z" fill="currentColor"/>',
    bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6M10 22h4"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    blend: '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
    // «Nueva»: the wand of «wand-sparkles» after the ✦ (the app's icon), never a second ✦
    wand: '<path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72"/><path d="m14 7 3 3"/>',
    eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>',
    chevdown: '<path d="m6 9 6 6 6-6"/>',
    arrowdown: '<path d="M12 5v14M19 12l-7 7-7-7"/>'
  };
  // Text read from the page (JSON specs, data-* attributes) is escaped before it is laid as
  // HTML, so a mockup can never run markup it carries (CodeQL js/xss-through-dom).
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
  function num(v) { return Number(v) || 0; }

  function icon(name, cls) {
    return '<svg class="i ' + (cls || "") + '" viewBox="0 0 24 24" aria-hidden="true">' + (P[name] || "") + "</svg>";
  }

  var MODES = { new: ["wand", "Nueva"], same: ["copy", "Igual al original"], follow: ["follow", "Sigue a la anterior"] };
  function clock(s) {
    s = Math.round(s);
    var m = Math.floor(s / 60), r = s - m * 60;
    return m + ":" + (r < 10 ? "0" : "") + r;
  }
  function secs(n) { return (Math.round(n * 2) / 2).toString().replace(".", ",") + " s"; }

  function handles(name) {
    return '<span class="q-tl__handle q-tl__handle--start" role="slider" aria-label="Inicio de ' + name + '"><span class="q-tl__grip"></span></span>' +
      '<span class="q-tl__handle q-tl__handle--end" role="slider" aria-label="Final de ' + name + '"><span class="q-tl__grip"></span></span>';
  }

  function mediaBlock(b, chosen) {
    var picked = b.id === chosen;
    var style = "--b-start:" + num(b.start) + ";--b-len:" + num(b.len);
    var inner, aria, attrs;
    if (b.kind === "ai") {
      var m = MODES[b.mode || "new"];
      aria = b.name + ", " + m[1] + ", de " + clock(b.start) + " a " + clock(num(b.start) + num(b.len)) + ", sin crear" + (b.warn ? ", " + b.warn : "");
      var line2 = b.warn
        ? '<span class="q-tl__state" data-tone="warn">' + icon("alert", "sm") + '<span class="q-tl__state-word">' + b.warn + "</span></span>"
        : '<span class="q-tl__chip"><span class="q-tl__label">' + b.name + '</span><span class="q-tl__secs"> · ' + secs(b.len) + "</span></span>";
      inner = '<span class="q-tl__pic ' + (b.pic || "pic-reel") + '"></span>' +
        '<span class="q-tl__ai-line"><span class="q-tl__mode">' + icon("sparkles") + icon(m[0]) + '<span class="q-tl__mode-word">' + m[1] + "</span></span></span>" +
        '<span class="q-tl__ai-line">' + line2 + "</span>";
      attrs = ' data-tl-block="ai" data-ai-state="plan"' + (b.warn ? ' data-ref-over="1"' : "");
    } else {
      var kind = b.kind === "photo" ? "photo" : "video";
      aria = b.name + ", de " + clock(b.start) + " a " + clock(num(b.start) + num(b.len));
      inner = '<span class="q-tl__pic ' + (b.pic || "pic-a") + '"></span><span class="q-tl__chip">' + icon(kind === "photo" ? "image" : "film", "sm") +
        '<span class="q-tl__label">' + b.name + '</span><span class="q-tl__secs"> · ' + secs(b.len) + "</span></span>";
      attrs = ' data-tl-block="' + kind + '"';
    }
    return '<div class="q-tl__item" data-tl-chosen="' + picked + '" style="' + style + '">' +
      '<button type="button" class="q-tl__block"' + attrs + ' aria-pressed="' + picked + '" aria-label="' + aria + '">' + inner + "</button>" +
      (picked ? handles(b.name) : "") + "</div>";
  }

  var REF_ICON = { photo: "image", video: "film", audio: "music" };
  function refBlock(r, type, chosen) {
    var picked = r.id === chosen;
    var pic = type === "audio" ? '<span class="q-tl__refpic q-tl__refpic--audio">' + icon("music") + "</span>"
      : '<span class="q-tl__refpic ' + (r.pic || "pic-c") + '">' + icon(REF_ICON[type]) + "</span>";
    var word = "";
    if (r.prod) word = '<span class="q-tl__refword" data-tone="prod">' + icon("tag") + "De tu producto</span>";
    if (r.word) word = '<span class="q-tl__refword"' + (r.tone ? ' data-tone="' + r.tone + '"' : "") + ">" + (r.tone === "warn" ? icon("alert") : "") + r.word + "</span>";
    var aria = r.name + ", de " + clock(r.start) + " a " + clock(num(r.start) + num(r.len)) + (r.prod ? ", de tu producto" : "") + (r.word ? ", " + r.word : "");
    var cls = "q-tl__item" + (r.lifted ? " q-tl__item--lifted" : "");
    return (r.ghost ? '<span class="q-tl__ghost" style="--b-start:' + num(r.ghost[0]) + ";--b-len:" + num(r.ghost[1]) + '"></span>' : "") +
      '<div class="' + cls + '" data-tl-chosen="' + picked + '" style="--b-start:' + num(r.start) + ";--b-len:" + num(r.len) + '">' +
      (r.balloon ? '<span class="q-tl__balloon">' + r.balloon + "</span>" : "") +
      '<button type="button" class="q-tl__block" data-tl-block="ref" data-ref-state="' + (r.state || "ok") + '" aria-pressed="' + picked + '" aria-label="' + aria + '">' + pic +
      '<span class="q-tl__reftxt"><span class="q-tl__label">' + r.name + "</span>" + word + "</span></button>" +
      (picked ? handles(r.name) : "") + "</div>";
  }
  function offMarks(r) {
    return (r.off || []).map(function (o) {
      return '<span class="q-tl__off" style="--o-start:' + num(o[0]) + ";--o-len:" + num(o[1]) + '"><span>' + icon("alert") + "No se usa aquí</span></span>";
    }).join("");
  }
  function layerBlock(b, kind) {
    var ic = kind === "text" ? '<span style="font-weight:700">Aa</span>' : icon("cloud", "sm");
    return '<div class="q-tl__item" style="--b-start:' + num(b.start) + ";--b-len:" + num(b.len) + '">' +
      '<button type="button" class="q-tl__block" data-tl-block="' + kind + '" aria-label="' + b.name + '">' + ic + '<span class="q-tl__label">' + b.name + "</span></button></div>";
  }

  var REF_TYPES = [["photo", "Fotos de referencia"], ["video", "Videos de referencia"], ["audio", "Audios de referencia"]];
  var REF_FOLD = { photo: "fotos", video: "videos", audio: "audios" };

  function timeline(spec) {
    var total = num(spec.total), ticks = "";
    for (var s = 0; s <= total; s += 2) ticks += '<span class="q-tl__tick" style="--b-start:' + s + '">' + clock(s) + "</span>";
    var media = spec.media.map(function (b) { return mediaBlock(b, spec.chosen); }).join("");
    var joins = (spec.joins || []).map(function (j) {
      return '<button type="button" class="q-tl__join" data-join-kind="' + j.kind + '" style="--j-at:' + num(j.at) + '" aria-label="' + j.label + '"><span class="q-tl__join-dot">' + (j.kind === "fundido" ? icon("blend") : "") + "</span></button>";
    }).join("");
    var ais = spec.media.filter(function (b) { return b.kind === "ai"; });
    var names = ['<span class="q-tl__name q-tl__name--ruler"></span>', '<span class="q-tl__name q-tl__name--media">Fotos y videos</span>'];
    var refHtml = "";
    if (ais.length) {
      names.push('<span class="q-tl__name q-tl__name--group"></span>');
      refHtml += '<div class="q-tl__group"><span>' + icon("sparkles") + "Para la IA · no sale en tu video</span></div>";
      var refs = spec.refs || {}, folded = [];
      REF_TYPES.forEach(function (t) {
        var items = refs[t[0]] || [];
        if (!items.length && spec.fold) { folded.push(t[0]); return; }
        var rows = Math.max(1, items.reduce(function (a, r) { return Math.max(a, num(r.row) + 1); }, 0));
        for (var row = 0; row < rows; row++) {
          var laneName = rows > 1 ? t[1] + " " + (row + 1) : t[1];
          names.push('<span class="q-tl__name q-tl__name--ref">' + laneName + "</span>");
          var zones = ais.map(function (a) {
            var over = (spec.over || {})[t[0]] === a.id;
            var off = t[0] !== "photo" && a.mode && a.mode !== "new";
            return '<span class="q-tl__zone"' + (over ? ' data-over="1"' : "") + (off ? ' data-off="1"' : "") + ' style="--b-start:' + num(a.start) + ";--b-len:" + num(a.len) + '"></span>';
          }).join("");
          var here = items.filter(function (r) { return num(r.row) === row; });
          var blocks = here.map(function (r) { return refBlock(r, t[0], spec.chosen) + offMarks(r); }).join("");
          refHtml += '<div class="q-tl__lane q-tl__lane--ref" role="list" aria-label="' + laneName + (here.length ? "" : ", vacía") + '">' + zones + blocks + "</div>";
        }
      });
      if (folded.length) {
        var words = folded.map(function (k) { return REF_FOLD[k]; });
        var txt = words.length === 1 ? words[0] : words.slice(0, -1).join(", ") + " ni " + words[words.length - 1];
        var label = "Sin " + txt + " de referencia · Agregar";
        names.push('<span class="q-tl__name q-tl__name--ref">Más referencias</span>');
        refHtml += '<button type="button" class="q-tl__folded" aria-label="' + label + '"><span>' + icon("plus", "sm") + label + "</span></button>";
      }
    }
    names.push('<span class="q-tl__name">Textos</span>', '<span class="q-tl__name">Efectos</span>');
    var texts = (spec.texts || []).map(function (b) { return layerBlock(b, "text"); }).join("");
    var effects = (spec.effects || []).map(function (b) { return layerBlock(b, "effect"); }).join("");
    return '<div class="q-tl" data-t="' + num(spec.t) + '" role="group" aria-label="Línea de tiempo de tu video">' +
      '<div class="q-tl__top"><span class="q-tl__clock q-nums">' + clock(num(spec.t)) + " de " + clock(total) + "</span></div>" +
      '<div class="q-tl__frame"><div class="q-tl__names" aria-hidden="true">' + names.join("") + "</div>" +
      '<div class="q-tl__scroller"><div class="q-tl__canvas" style="--tl-total:' + total + ";--tl-t:" + num(spec.t) + '">' +
      '<div class="q-tl__ruler">' + ticks + "</div>" +
      '<div class="q-tl__media"><div class="q-tl__lane q-tl__lane--media" role="list" aria-label="Fotos y videos">' + media + '</div><div class="q-tl__joins">' + joins + "</div></div>" +
      refHtml +
      '<div class="q-tl__lane" role="list" aria-label="Textos' + (texts ? "" : ", vacía") + '">' + texts + "</div>" +
      '<div class="q-tl__lane" role="list" aria-label="Efectos' + (effects ? "" : ", vacía") + '">' + effects + "</div>" +
      '<span class="q-tl__head q-tl__head--move"></span></div></div>' +
      '<span class="q-tl__head q-tl__head--fixed"></span></div>' +
      '<p class="q-tl__status" role="status">' + (spec.status || "") + "</p></div>";
  }

  function hydrate(root) {
    root.querySelectorAll("[data-i]").forEach(function (el) { el.outerHTML = icon(esc(el.getAttribute("data-i") || ""), esc(el.getAttribute("data-c") || "")); });
    root.querySelectorAll("script[type='application/json'][data-tl]").forEach(function (el) {
      var box = document.createElement("div");
      box.innerHTML = timeline(readSpec(el));
      el.replaceWith(box.firstChild);
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
      var only = pair.getAttribute("data-only") || "";
      var notePhone = esc(pair.getAttribute("data-note-phone") || ""), noteDesk = esc(pair.getAttribute("data-note-desk") || "");
      [["phone", "Celular · 375 px", notePhone], ["desk", "Escritorio", noteDesk]].forEach(function (d) {
        if (only && only !== d[0]) return;
        var col = document.createElement("div");
        col.className = "mk-col";
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
