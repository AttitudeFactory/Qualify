// node --test: `video_text` v1 (EF-05, m-25026573). No Chromium: the layout (layout.ts, Node's
// type stripping) with layer_still's real engine (engine.ts) and catalog, against the same fake
// measurer as layer-still.test.mjs (≈ Poppins: heading glyphs 0.6 em). Real fonts and pixels
// are checked by rendering on a service (`just render-smoke`, the EF-05 evidence).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {validateProps} from './validate.mjs';
import {refusalOf} from './jobs.mjs';
import {contrast, resolveLayer, textColorOn} from '../src/templates/layer_still/engine.ts';
import {fontWarnings} from './fonts.mjs';
import {boxInk, resolveVideoText, SIZE_SCALE, sizeRange, TEXT_MAX} from '../src/templates/video_text/layout.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (...p) => JSON.parse(fs.readFileSync(path.join(here, '..', 'templates', ...p), 'utf8'));
// v1 is kept as `manifest.v1.json` (ED-13 published v2 as `manifest.json`): these tests pin it
const manifest = read('video_text', 'manifest.v1.json');
const layerManifest = read('layer_still', 'manifest.json');
const catalog = layerManifest.layer_catalog;
const config = manifest.video_text;

const measure = (text, {role, size}) => [...text].length * size * (role === 'heading' ? 0.6 : 0.52);
const palette = {accent: '#B5532A', text: '#FFFFFF', surface: '#FFF4E6'};
// Instagram's UI: 250 px at the top and 300 at the bottom of a 1920 px Reel are not free
const IG_TOP = 250;
const IG_BOTTOM = 1920 - 300;

const run = (text, place, over = {}) =>
  resolveVideoText({
    catalog,
    config,
    text,
    place,
    layoutId: 'scrim',
    layoutVersion: catalog.layout_version,
    headingFamily: 'Poppins',
    palette,
    measure,
    resolve: resolveLayer,
    ...over,
  });

const lineRects = (r) => r.texts.flatMap((t) => t.lines.map((l) => ({x: l.x, y: l.y, w: l.width, h: t.size * t.lineHeight})));
const words = (s) => s.trim().split(/\s+/);

// ~80 characters, the ticket's case
const EIGHTY = 'Pan de masa madre recién horneado, café de origen y postres caseros todos los días';
const LONGEST = 'Ven a probar nuestro pan de masa madre recién horneado, el café de origen y los postres caseros que hacemos aquí';

test('the manifest is v1 with one transparent 9:16 still port and a text of up to 120 chars', () => {
  assert.equal(manifest.id, 'video_text');
  assert.equal(manifest.version, 1);
  assert.deepEqual(Object.keys(manifest.outputs), ['overlay']);
  assert.equal(manifest.outputs.overlay.kind, 'still');
  assert.equal(manifest.outputs.overlay.composition, 'video-text-v1--overlay');
  assert.equal(manifest.inputs.text.max, TEXT_MAX);
  assert.equal(TEXT_MAX, 120);
  assert.ok(EIGHTY.length >= 78 && EIGHTY.length <= 82, `${EIGHTY.length}`);
  assert.ok(LONGEST.length <= 120, `${LONGEST.length}`);
});

for (const place of ['top', 'middle', 'bottom']) {
  for (const text of ['Pan fresco', 'Pan recién horneado todos los días', EIGHTY, LONGEST]) {
    test(`${place}, ${text.length} chars: every line inside the catalog's safe zone and Instagram's`, () => {
      const r = run(text, place);
      const [sx0, sy0, sx1, sy1] = catalog.formats['9:16'].safe;
      for (const rect of lineRects(r)) {
        assert.ok(rect.y >= IG_TOP && rect.y + rect.h <= IG_BOTTOM, `line at y ${rect.y}–${rect.y + rect.h}`);
        assert.ok(rect.y >= sy0 - 0.5 && rect.y + rect.h <= sy1 + 0.5, `outside the catalog safe zone: ${rect.y}`);
        assert.ok(rect.x >= sx0 - 0.5 && rect.x + rect.w <= sx1 + 0.5, `outside x: ${rect.x}+${rect.w}`);
      }
      assert.equal(r.report.place, place);
      assert.equal(r.report.layout_rendered, 'scrim');
      assert.equal(r.report.engine_revision, catalog.engine_revision);
      assert.equal(r.report.overlay_revision, config.overlay_revision);
    });
  }
}

test('an 80-character text breaks between words, never inside one, and keeps every word', () => {
  for (const place of ['top', 'middle', 'bottom']) {
    const r = run(EIGHTY, place);
    const lines = r.report.lines;
    assert.ok(lines.length >= 2, `${lines.length} lines`);
    assert.deepEqual(lines.flatMap(words), words(EIGHTY));
    // each line is made of whole words of the text
    const all = new Set(words(EIGHTY));
    for (const l of lines) for (const w of words(l)) assert.ok(all.has(w), `«${w}» is not a word of the text`);
  }
});

test('a short text is laid out exactly as the 9:16 image scrim draws it (same engine, same boxes)', () => {
  for (const anchor of ['top', 'bottom']) {
    const title = 'Pan recién horneado';
    const image = resolveLayer({
      catalog,
      format: '9:16',
      layer: {spec_version: 1, layout_id: 'scrim', layout_version: catalog.layout_version, format: '9:16', title, anchor},
      photo: null,
      priceText: '',
      isFood: false,
      palette,
      headingFamily: 'Poppins',
      hasLogo: false,
      measure,
    });
    const video = run(title, anchor);
    assert.deepEqual(video.texts, image.texts);
    assert.deepEqual(video.scrims, [image.scrim]);
    assert.equal(video.report.cover, catalog.layouts.scrim.cover);
  }
});

test('the place is never moved: top stays at the top, bottom at the bottom, middle at the centre', () => {
  const top = lineRects(run(EIGHTY, 'top'));
  const bottom = lineRects(run(EIGHTY, 'bottom'));
  const middle = lineRects(run(EIGHTY, 'middle'));
  const centre = (rs) => (Math.min(...rs.map((r) => r.y)) + Math.max(...rs.map((r) => r.y + r.h))) / 2;
  assert.ok(centre(top) < 700, `${centre(top)}`);
  assert.ok(centre(bottom) > 1200, `${centre(bottom)}`);
  assert.ok(Math.abs(centre(middle) - config.middle_center_y) < 1, `${centre(middle)}`);
});

test('middle: the scrim is mirrored around the text, ≥ 60 % under every line', () => {
  const r = run(EIGHTY, 'middle');
  assert.equal(r.scrims.length, 2);
  const [up, down] = r.scrims;
  const rects = lineRects(r);
  const y0 = Math.min(...rects.map((x) => x.y));
  const y1 = Math.max(...rects.map((x) => x.y + x.h));
  assert.equal(up.edge, 'bottom');
  assert.equal(down.edge, 'top');
  assert.ok(up.solid <= y0 && down.solid >= y1);
  assert.equal(up.end, config.middle_center_y);
  assert.equal(down.end, config.middle_center_y);
  assert.ok(up.textAlpha >= 0.6 && up.maxAlpha >= up.textAlpha);
  assert.ok(down.start - up.start >= catalog.layouts.scrim.cover * 1920 - 0.5);
});

test('a long text grows the scrim instead of shrinking past the catalog minimum', () => {
  const r = run(LONGEST, 'bottom');
  assert.ok(r.report.size >= catalog.font_sizes.title['9:16'][1]);
  assert.ok(r.report.cover > catalog.layouts.scrim.cover, `${r.report.cover}`);
});

test('same input → same layout (deterministic)', () => {
  assert.deepEqual(run(EIGHTY, 'bottom'), run(EIGHTY, 'bottom'));
});

test('a word wider than the safe width is refused with a machine-readable refusal, never cut', () => {
  const word = 'Supercalifragilisticoespialidoso';
  assert.throws(
    () => run(word, 'top'),
    (err) => {
      const refusal = refusalOf(err);
      assert.ok(refusal, String(err.message));
      assert.equal(refusal.slot, 'text');
      assert.equal(refusal.reason, 'word_too_wide');
      return true;
    },
  );
});

test('bad props are refused: blank text, unknown place, unknown layout, stale layout version', () => {
  assert.throws(() => run('   ', 'top'), /invalid_parameters: texts.text: required/);
  assert.throws(() => run('Hola', 'left'), /texts.place/);
  assert.throws(() => run('Hola', 'top', {layoutId: 'plate'}), /texts.layout_id/);
  assert.throws(() => run('Hola', 'top', {layoutVersion: 1}), /texts.layout_version/);
  assert.throws(() => run('x'.repeat(121), 'top'), /exceeds max 120/);
});

test('the server answers 422 for props that do not match the manifest', () => {
  const ok = {brand: {name: 'X'}, texts: {text: 'Hola', place: 'top', layout_id: 'scrim', layout_version: 3}};
  assert.deepEqual(validateProps(manifest, ok), []);
  const bad = validateProps(manifest, {brand: {}, texts: {text: 'x'.repeat(121), place: 'left', layout_id: 'band'}});
  assert.ok(bad.some((p) => p.includes('texts.text')));
  assert.ok(bad.some((p) => p.includes('texts.place')));
  assert.ok(bad.some((p) => p.includes('texts.layout_id')));
  assert.ok(bad.some((p) => p.includes('texts.layout_version')));
});

// ---------------------------------------------------------------- v2 (ED-13, m-25029108)

const manifestV2 = read('video_text', 'manifest.json');
const configV2 = manifestV2.video_text;
const runV2 = (text, place, layoutId, over = {}) => {
  const pal = over.palette ?? palette;
  return resolveVideoText({
    catalog,
    config: configV2,
    text,
    place,
    layoutId,
    layoutVersion: catalog.layout_version,
    headingFamily: 'Poppins',
    palette: pal,
    measure,
    resolve: resolveLayer,
    inkOn: (bg) => textColorOn(bg, pal),
    ...over,
  });
};
const geometry = (r) =>
  r.texts.map((t) => ({...t, lines: t.lines.map(({spans, ...l}) => ({...l, text: spans.map((s) => s.text).join('')}))}));

test('v2: the manifest adds the four backgrounds and the backdrop/letters ports; v1 is unchanged', () => {
  assert.equal(manifestV2.version, 2);
  assert.deepEqual(manifestV2.inputs.layout_id.enum, ['scrim', 'band', 'brand_fill', 'shadow']);
  assert.deepEqual(configV2.layouts, ['scrim', 'band', 'brand_fill', 'shadow']);
  assert.deepEqual(Object.keys(manifestV2.outputs), ['overlay', 'backdrop', 'letters']);
  for (const [port, spec] of Object.entries(manifestV2.outputs)) {
    assert.equal(spec.composition, `video-text-v2--${port}`);
    assert.deepEqual([spec.width, spec.height, spec.kind], [1080, 1920, 'still']);
  }
  // the contract's numbers (schemas.VIDEO_TEXT_BOX_PAD_PX, _RADIUS_PX, _INK_LIGHT/_DARK)
  assert.equal(configV2.band.pad, 48);
  assert.equal(configV2.box.pad, 48);
  assert.equal(configV2.box.radius, 24);
  assert.deepEqual(configV2.box_ink, {light: '#FFFFFF', dark: '#111111'});
  // «Sin fondo» has no text shadow any more (Deivid, 2026-11-23)
  assert.equal(configV2.shadow, undefined);
  assert.deepEqual(manifestV2.inputs.box_color, {type: 'string', max: 7, optional: true});
  assert.deepEqual(manifest.version, 1);
  assert.deepEqual(manifest.video_text.layouts, ['scrim']);
});

for (const place of ['top', 'middle', 'bottom']) {
  test(`v2 ${place}: the four backgrounds lay out the SAME text block as v1's scrim, centred`, () => {
    // v2 centres every line (Deivid 2026-11-24): the same sizes, breaks and heights as v1,
    // only moved along x
    const unaligned = (r) => geometry(r).map(({align, ...t}) => ({...t, lines: t.lines.map(({x, ...l}) => l)}));
    const v1 = run(EIGHTY, place);
    for (const layout of configV2.layouts) {
      const r = runV2(EIGHTY, place, layout);
      assert.deepEqual(unaligned(r), unaligned(v1), layout);
      assert.equal(r.report.layout_rendered, layout);
      const [b2, b1] = [r.report.text_box, v1.report.text_box];
      assert.deepEqual([b2.y, b2.w, b2.h], [b1.y, b1.w, b1.h], layout);
      assert.ok(Math.abs(b2.x + b2.w / 2 - 540) <= 0.01, layout);
    }
    // the scrim of v2 is v1's (its lines centred)
    const scrim = runV2(EIGHTY, place, 'scrim');
    assert.deepEqual(unaligned(scrim), unaligned(v1));
    assert.deepEqual(scrim.scrims, v1.scrims);
    assert.deepEqual(scrim.containers, []);
    assert.equal(scrim.textShadow, undefined);
  });
}

test('v2 band: a full-width strip hugging the text by 48 px, FIXED dark neutral #111111 with white letters, whatever the brand', () => {
  // ED-13 (Deivid: «Franja, oscura y neutra»): never palette.surface — white on brands like Polette
  const palettes = [palette, {accent: '#F4C2C2', text: '#5A2A27', surface: '#FFFFFF'}, {accent: '#777777', text: '#777777', surface: '#777777'}];
  for (const pal of palettes) {
    const r = runV2(EIGHTY, 'bottom', 'band', {palette: pal});
    const box = r.report.text_box;
    assert.equal(r.scrims.length, 0);
    assert.equal(r.containers.length, 1);
    const [c] = r.containers;
    assert.equal(c.color, '#111111');
    assert.deepEqual([c.rect.x, c.rect.w, c.radius], [0, 1080, 0]);
    for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.equal(s.color, '#FFFFFF');
    assert.ok(Math.abs(c.rect.y - (box.y - 48)) < 0.02 && Math.abs(c.rect.h - (box.h + 96)) < 0.02, JSON.stringify(c.rect));
    for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.ok(contrast(s.color, c.color) >= 4.5, `${s.color} on ${c.color}`);
    assert.ok(r.report.contrast.text >= 4.5);
    assert.deepEqual(r.report.backdrop_box, c.rect);
  }
});

test('v2 brand_fill: a rounded box just behind the letters (block ± 48 px, radius 24) in palette.accent', () => {
  for (const pal of [palette, {accent: '#FFE600', text: '#FFFFFF', surface: '#000000'}]) {
    const r = runV2('Pan fresco', 'top', 'brand_fill', {palette: pal});
    const box = r.report.text_box;
    const [c] = r.containers;
    assert.equal(c.color, pal.accent);
    assert.equal(c.radius, 24);
    assert.ok(Math.abs(c.rect.x - (box.x - 48)) < 0.02 && Math.abs(c.rect.w - (box.w + 96)) < 0.02, JSON.stringify(c.rect));
    assert.ok(c.rect.w < 1080, 'the box is only behind the letters');
    for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.ok(contrast(s.color, c.color) >= 4.5, `${s.color} on ${c.color}`);
  }
});

test('v2 shadow («Sin fondo»): no veil, no box, no text shadow — only clean white letters', () => {
  const r = runV2(EIGHTY, 'middle', 'shadow');
  assert.deepEqual(r.scrims, []);
  assert.deepEqual(r.containers, []);
  assert.equal(r.textShadow, undefined);
  assert.ok(!JSON.stringify(r).includes('rgba(0,0,0'), 'nothing dark drawn around the letters');
  for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.equal(s.color, '#FFFFFF');
  assert.equal(r.report.backdrop_box, null);
  // a picked colour means nothing without a box
  assert.deepEqual(runV2(EIGHTY, 'middle', 'shadow', {boxColor: '#FFE600'}).containers, []);
});

test('v2 box ink: white or #111111 by the higher contrast — the vectors the screen shares', () => {
  const shared = JSON.parse(fs.readFileSync(path.join(here, 'box-ink-vectors.json'), 'utf8'));
  assert.deepEqual([shared.light, shared.dark], [configV2.box_ink.light, configV2.box_ink.dark]);
  for (const [bg, ink] of shared.vectors) assert.equal(boxInk(bg), ink, bg);
  // a tie goes to white; the chosen ink always contrasts at least as much as the other
  for (const [bg, ink] of shared.vectors) {
    const other = ink === '#FFFFFF' ? '#111111' : '#FFFFFF';
    assert.ok(contrast(ink, bg) >= contrast(other, bg), bg);
  }
});

test('v2 box_color: «Franja» and «Recuadro de tu color» in the colour the owner picked, letters by contrast', () => {
  for (const [layout, picked, ink] of [
    ['band', '#FFE600', '#111111'],
    ['band', '#2563EB', '#FFFFFF'],
    ['brand_fill', '#FFFFFF', '#111111'],
    ['brand_fill', '#111111', '#FFFFFF'],
  ]) {
    const plain = runV2('Pan fresco', 'top', layout);
    const r = runV2('Pan fresco', 'top', layout, {boxColor: picked});
    const [c] = r.containers;
    assert.equal(c.color, picked, layout);
    assert.deepEqual(c.rect, plain.containers[0].rect, 'the same box, only its colour changes');
    assert.equal(c.radius, plain.containers[0].radius);
    assert.deepEqual(geometry(r), geometry(plain));
    for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.equal(s.color, ink, `${layout} ${picked}`);
    assert.equal(r.report.contrast.text, Math.round(contrast(ink, picked) * 100) / 100);
  }
  // none (or '') = the default: band #111111 with white letters, brand_fill the accent
  assert.equal(runV2('Pan fresco', 'top', 'band', {boxColor: null}).containers[0].color, '#111111');
  assert.equal(runV2('Pan fresco', 'top', 'brand_fill', {boxColor: ''}).containers[0].color, palette.accent);
  // the scrim ignores it
  assert.deepEqual(runV2('Pan fresco', 'top', 'scrim', {boxColor: '#FFE600'}).scrims, runV2('Pan fresco', 'top', 'scrim').scrims);
});

test('v2 box_color: only a #RRGGBB hex in capitals, and never on v1', () => {
  for (const bad of ['#ffe600', 'red', '#FFF', '#FFE6001A', 12]) {
    assert.throws(() => runV2('Hola', 'top', 'band', {boxColor: bad}), /texts.box_color/, String(bad));
  }
  assert.throws(() => run('Hola', 'top', {boxColor: '#FFE600'}), /texts.box_color/);
  const texts = {text: 'Hola', place: 'top', layout_id: 'band', layout_version: 3, box_color: '#FFE600'};
  assert.deepEqual(validateProps(manifestV2, {brand: {}, texts}), []);
  assert.ok(validateProps(manifestV2, {brand: {}, texts: {...texts, box_color: '#FFE6001A'}}).some((p) => p.includes('texts.box_color')));
});

test('v2 text_color: «Sin fondo»\'s letters in the colour the owner picked, still clean', () => {
  assert.deepEqual(manifestV2.inputs.text_color, {type: 'string', max: 7, optional: true});
  const plain = runV2(EIGHTY, 'middle', 'shadow');
  for (const picked of ['#111111', '#2563EB']) {
    const r = runV2(EIGHTY, 'middle', 'shadow', {textColor: picked});
    assert.deepEqual(r.scrims, []);
    assert.deepEqual(r.containers, []);
    assert.equal(r.textShadow, undefined);
    assert.deepEqual(geometry(r), geometry(plain), 'only the colour changes');
    for (const t of r.texts) for (const l of t.lines) for (const s of l.spans) assert.equal(s.color, picked);
  }
  // none (or '') = white, as before
  for (const none of [null, '']) {
    for (const t of runV2(EIGHTY, 'middle', 'shadow', {textColor: none}).texts) {
      for (const l of t.lines) for (const s of l.spans) assert.equal(s.color, '#FFFFFF');
    }
  }
  // the other backgrounds ignore it: they pick their letters for contrast
  for (const layout of ['scrim', 'band', 'brand_fill']) {
    assert.deepEqual(
      runV2('Pan fresco', 'top', layout, {textColor: '#2563EB'}).texts,
      runV2('Pan fresco', 'top', layout).texts,
      layout,
    );
  }
});

test('v2 text_color: only a #RRGGBB hex in capitals, and never on v1', () => {
  for (const bad of ['#111', '#2563eb', 'black', '#1111111A', 12]) {
    assert.throws(() => runV2('Hola', 'top', 'shadow', {textColor: bad}), /texts.text_color/, String(bad));
  }
  assert.throws(() => run('Hola', 'top', {textColor: '#111111'}), /texts.text_color/);
  const texts = {text: 'Hola', place: 'top', layout_id: 'shadow', layout_version: 3, text_color: '#111111'};
  assert.deepEqual(validateProps(manifestV2, {brand: {}, texts}), []);
  assert.ok(validateProps(manifestV2, {brand: {}, texts: {...texts, text_color: '#1111111A'}}).some((p) => p.includes('texts.text_color')));
});

test('v2 text_size: «Pequeña» / «Mediana» / «Grande» scale the title range; «Mediana» draws as before', () => {
  assert.deepEqual(manifestV2.inputs.text_size, {type: 'string', enum: ['small', 'medium', 'large'], optional: true});
  assert.deepEqual(SIZE_SCALE, {small: 0.75, medium: 1, large: 1.25});
  assert.equal(configV2.text_size, undefined, 'the scales stay out of the digested block');
  const titleSize = (r) => r.texts.find((t) => t.slot === 'title').size;
  for (const layout of ['scrim', 'band', 'brand_fill', 'shadow']) {
    const plain = runV2('Pan fresco', 'top', layout);
    assert.deepEqual(geometry(runV2('Pan fresco', 'top', layout, {textSize: 'medium'})), geometry(plain), layout);
    const small = titleSize(runV2('Pan fresco', 'top', layout, {textSize: 'small'}));
    const large = titleSize(runV2('Pan fresco', 'top', layout, {textSize: 'large'}));
    assert.ok(small < titleSize(plain) && titleSize(plain) < large, `${layout}: ${small} < ${titleSize(plain)} < ${large}`);
    assert.ok(large <= Math.round(112 * 1.25) && small >= Math.round(76 * 0.75), layout);
  }
});

// Round 4 b (Deivid 2026-11-24, «Siempre más chica»): the sizes follow what «Mediana» chose
// for THIS text — a long text drew the same in «Pequeña» and «Mediana» (overlapping ranges)
const DEIVID_FITS = 'hola que hace  con 40 caracteres lorem ipsum alastre fjkaskjas asjkasjkjkd asdasd';
const DEIVID = 'hola que hace  con 40 caracteres lorem ipsum alastre fjkaskjas asjkasjkjkd asdasdasdasdassdasdasdasdasdas asdasd';

test('v2 text_size: «Pequeña» is always 75 % and «Grande» 125 % of what «Mediana» chose', () => {
  const titleSize = (r) => r.texts.find((t) => t.slot === 'title').size;
  const cases = [
    ['Pan fresco', true],
    ['Pan de masa madre y café de origen hoy!!', true], // 40: «Grande» is still on
    [DEIVID_FITS, false], // long: «Mediana» shrinks to fit, «Pequeña» must still be smaller
  ];
  for (const [text, withLarge] of cases) {
    for (const place of ['top', 'middle', 'bottom']) {
      for (const layout of ['scrim', 'band', 'brand_fill', 'shadow']) {
        const medium = titleSize(runV2(text, place, layout));
        const small = runV2(text, place, layout, {textSize: 'small'});
        assert.equal(titleSize(small), Math.round(medium * 0.75), `${text}/${place}/${layout}`);
        assert.equal(small.report.size, Math.round(medium * 0.75));
        for (const b of lineRects(small)) assert.ok(b.x >= 64 - 0.5 && b.x + b.w <= 1016 + 0.5, `${place}/${layout}`);
        if (!withLarge) continue;
        const large = titleSize(runV2(text, place, layout, {textSize: 'large'}));
        // exactly 125 %: a taller cover step holds it (up to 40 characters, «Grande»'s limit)
        assert.equal(large, Math.round(medium * 1.25), `${text}/${place}/${layout}: ${medium} → ${large}`);
      }
    }
  }
});

test('v2 (Deivid 2026-11-24 «que siempre esté centrado»): every line and the box are centred on the canvas', () => {
  // 1 to 3 words too (Deivid 2026-11-24: «cuando escribo poco texto se va hacia la derecha»)
  const texts = ['Hola', 'Pan fresco', '2×1 hoy', 'Pan de masa madre y café de origen hoy!!', DEIVID_FITS];
  for (const text of texts) {
    for (const size of ['small', 'medium', 'large']) {
      if (size === 'large' && [...text].length > 40) continue;
      for (const place of ['top', 'middle', 'bottom']) {
        for (const layout of ['scrim', 'band', 'brand_fill', 'shadow']) {
          const r = runV2(text, place, layout, {textSize: size});
          const where = `${text}/${size}/${place}/${layout}`;
          for (const b of lineRects(r)) {
            assert.ok(Math.abs(b.x + b.w / 2 - 540) <= 0.01, `${where}: ${JSON.stringify(b)}`);
            assert.ok(b.x >= 64 - 0.5 && b.x + b.w <= 1016 + 0.5, where);
          }
          const box = r.containers[0]?.rect;
          if (layout === 'brand_fill') assert.ok(Math.abs(box.x + box.w / 2 - 540) <= 0.01, `${where}: ${JSON.stringify(box)}`);
          if (layout === 'band') assert.deepEqual([box.x, box.w], [0, 1080], where);
          // «Letra por letra»'s boxes follow the centred lines
          const first = r.report.letter_boxes[0];
          assert.ok(Math.abs(first.x - lineRects(r)[0].x) <= 0.01, where);
        }
      }
    }
  }
  // v1 stays as it was: left-aligned at the safe zone's edge
  assert.ok(lineRects(run('Pan fresco', 'top')).every((b) => Math.abs(b.x - 64) <= 0.5));
});

test("v2 text_size: the size ranges come from «Mediana»'s choice", () => {
  const title = [112, 76];
  assert.deepEqual(sizeRange('small', 76, title), [57, 57]);
  assert.deepEqual(sizeRange('small', 112, title), [84, 84]);
  assert.deepEqual(sizeRange('large', 76, title), [95, 95]);
  assert.deepEqual(sizeRange('large', 112, title), [140, 112]);
  assert.deepEqual(sizeRange('large', 90, title), [113, 95]);
  assert.deepEqual(sizeRange('medium', 90, title), [112, 76]);
  // «Mediana» could not draw it (a word too wide at 76 px): the size's own range
  assert.deepEqual(sizeRange('small', null, title), [84, 57]);
  assert.deepEqual(sizeRange('large', null, title), [140, 95]);
});

test('v2 text_size: a word too wide for «Mediana» is still drawn by «Pequeña»; «Grande» falls back, never refused', () => {
  const titleSize = (r) => r.texts.find((t) => t.slot === 'title').size;
  // 24 letters × 0.6 em: 1094 px at 76 (refused) but 821 px at 57 (fits)
  const WIDE = 'Hola ' + 'a'.repeat(24);
  let refusal = null;
  try {
    runV2(WIDE, 'middle', 'brand_fill');
  } catch (err) {
    refusal = refusalOf(err);
  }
  assert.equal(refusal?.reason, 'word_too_wide', 'Mediana refuses it');
  const small = runV2(WIDE, 'middle', 'brand_fill', {textSize: 'small'});
  assert.ok(titleSize(small) >= 57 && titleSize(small) < 76, String(titleSize(small)));
  for (const b of lineRects(small)) assert.ok(b.x >= 64 - 0.5 && b.x + b.w <= 1016 + 0.5);
  // 16 letters: «Mediana» chooses 96 px; 125 % (120 px) is too wide everywhere, so «Grande»
  // falls back to the largest that fits, never below «Mediana» — drawn, not refused
  const LONG_WORD = 'Pan ' + 'b'.repeat(16);
  const medium = titleSize(runV2(LONG_WORD, 'top', 'scrim'));
  assert.equal(medium, 96);
  assert.equal(titleSize(runV2(LONG_WORD, 'top', 'scrim', {textSize: 'large'})), medium);
});

test("v2 text_size: Deivid's text is refused for its word at every size, never drawn past the edge", () => {
  for (const size of ['small', 'medium', 'large']) {
    let refusal = null;
    try {
      runV2(DEIVID, 'middle', 'brand_fill', {textSize: size});
    } catch (err) {
      refusal = refusalOf(err);
    }
    assert.equal(refusal?.reason, 'word_too_wide', size);
  }
  // without that word it draws, inside the safe zone, in both sizes it is allowed
  for (const size of ['small', 'medium']) {
    for (const b of lineRects(runV2(DEIVID_FITS, 'middle', 'brand_fill', {textSize: size}))) {
      assert.ok(b.x >= 64 - 0.5 && b.x + b.w <= 1016 + 0.5, size);
    }
  }
});

test('v2 text_size: «Grande» stays inside the safe zone in every place and background, up to 40 characters', () => {
  const FORTY = 'MMMM WWWW MMMM WWWW MMMM WWWW MMMM WWWWW';
  assert.equal([...FORTY].length, 40);
  for (const place of ['top', 'middle', 'bottom']) {
    for (const layout of ['scrim', 'band', 'brand_fill', 'shadow']) {
      const r = runV2(FORTY, place, layout, {textSize: 'large'});
      for (const b of lineRects(r)) {
        assert.ok(b.x >= 64 - 0.5 && b.x + b.w <= 1016 + 0.5, `${place}/${layout}: ${JSON.stringify(b)}`);
      }
      assert.equal(words(r.texts.flatMap((t) => t.lines.map((l) => l.spans.map((s) => s.text).join(''))).join(' ')).join(' '), FORTY);
    }
  }
});

test('v2 text_size: only the three sizes, and never on v1', () => {
  for (const bad of ['huge', 'LARGE', 3]) {
    assert.throws(() => runV2('Hola', 'top', 'scrim', {textSize: bad}), /texts.text_size/, String(bad));
  }
  assert.throws(() => run('Hola', 'top', {textSize: 'large'}), /texts.text_size/);
  assert.doesNotThrow(() => run('Hola', 'top', {textSize: 'medium'}));
  const texts = {text: 'Hola', place: 'top', layout_id: 'scrim', layout_version: 3, text_size: 'large'};
  assert.deepEqual(validateProps(manifestV2, {brand: {}, texts}), []);
  assert.ok(validateProps(manifestV2, {brand: {}, texts: {...texts, text_size: 'huge'}}).some((p) => p.includes('texts.text_size')));
});

test('v2: every character has a box, in reading order, covering its line left to right', () => {
  const text = 'Pan recién horneado todos los días';
  const r = runV2(text, 'bottom', 'scrim');
  const boxes = r.report.letter_boxes;
  const drawn = r.report.lines.join('');
  assert.equal(boxes.length, [...drawn].length);
  // the spaces a line break eats are the only characters of the text without a box
  assert.equal(boxes.length, [...text].length - (r.report.lines.length - 1));
  for (let i = 1; i < boxes.length; i++) {
    const [a, b] = [boxes[i - 1], boxes[i]];
    if (a.line === b.line) assert.ok(Math.abs(b.x - (a.x + a.w)) < 0.02, `gap at ${i}`);
    else assert.ok(b.line === a.line + 1 && b.y > a.y, `line order at ${i}`);
  }
  // v1's report carries none
  assert.equal(run(text, 'bottom').report.letter_boxes, undefined);
});

test('v2: an unknown background is refused; v1 still refuses band and shadow', () => {
  assert.throws(() => runV2('Hola', 'top', 'plate'), /texts.layout_id/);
  assert.throws(() => run('Hola', 'top', {layoutId: 'band'}), /texts.layout_id/);
  const shadow = {brand: {}, texts: {text: 'Hola', place: 'top', layout_id: 'shadow', layout_version: 3}};
  assert.deepEqual(validateProps(manifestV2, shadow), []);
  assert.ok(validateProps(manifest, shadow).some((p) => p.includes('texts.layout_id')));
});

test('v2: a brand font file is an asset reference, and silences the unknown-family warning', () => {
  const texts = {text: 'Hola', place: 'top', layout_id: 'scrim', layout_version: 3};
  assert.deepEqual(validateProps(manifestV2, {brand: {fontFiles: {heading: 'asset://abc'}}, texts}), []);
  assert.ok(validateProps(manifestV2, {brand: {fontFiles: {heading: '/etc/passwd'}}, texts}).some((p) => p.includes('brand.fontFiles.heading')));
  assert.ok(validateProps(manifestV2, {brand: {fontFiles: 'x'}, texts}).some((p) => p.includes('brand.fontFiles')));
  assert.equal(fontWarnings({fonts: {heading: 'Mi Letra Propia'}}).length, 1);
  assert.deepEqual(fontWarnings({fonts: {heading: 'Mi Letra Propia'}, fontFiles: {heading: 'asset://abc'}}), []);
});
