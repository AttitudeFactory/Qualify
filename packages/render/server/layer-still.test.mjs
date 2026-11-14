// node --test: `layer_still` v1 (m-25017285). No Chromium: the boundary check (spec.mjs, the
// same code the server answers 422 with) and the deterministic engine (engine.ts, loaded with
// Node's type stripping) against a fake measurer — a monospace-like width per character — so
// the checks and the fallback chain of catalog §1.7 are tested per layout and format. The
// real fonts are exercised by scripts/layer-preview.mjs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {validateProps} from './validate.mjs';
import {layerProblems} from '../src/templates/layer_still/spec.mjs';
import {contrast, resolveLayer, textColorOn, wrap} from '../src/templates/layer_still/engine.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(fs.readFileSync(path.join(here, '..', 'templates', 'layer_still', 'manifest.json'), 'utf8'));
const catalog = manifest.layer_catalog;
const FORMATS = ['4:5', '1:1', '9:16'];

// ~ Poppins: heading glyphs ≈ 0.6 em, body ≈ 0.52 em
const measure = (text, {role, size}) => [...text].length * size * (role === 'heading' ? 0.6 : 0.52);
const palette = {accent: '#B5532A', text: '#FFFFFF', surface: '#FFF4E6'};
const PHOTO = {width: 1080, height: 1350};

/**
 * The tests write the photo reading flat (`subject_box`, `logo_in_photo`) and the carousel as
 * a 1-based `slide`; this turns them into the LayerSpec v1 of m-25017283 (`photo`, `carousel`).
 */
const toSpec = (layer, slide) => {
  const {subject_box, logo_in_photo, ...rest} = layer;
  const spec = {layout_version: 1, ...rest};
  if (subject_box || logo_in_photo) {
    spec.photo = {subject_box: subject_box ?? [0.45, 0.45, 0.55, 0.55], logo_in_photo: !!logo_in_photo, base_has_invented_text: false};
  }
  if (spec.layout_id === 'info_card' && spec.photo_strip === undefined) spec.photo_strip = false;
  if (slide) spec.carousel = {role: slide.role, index: slide.index - 1, count: slide.total};
  return spec;
};

const run = (layer, over = {}) => {
  const {slide, ...rest} = over;
  return resolveLayer({
    catalog,
    format: '4:5',
    layer: toSpec(layer, slide),
    photo: PHOTO,
    priceText: '',
    isFood: true,
    palette,
    headingFamily: 'Poppins',
    hasLogo: true,
    measure,
    ...rest,
  });
};

const lineRects = (r) => r.texts.flatMap((t) => t.lines.map((l) => ({x: l.x, y: l.y, w: l.width, h: t.size * t.lineHeight})));
const within = (rect, safe) => rect.x >= safe[0] - 1 && rect.y >= safe[1] - 1 && rect.x + rect.w <= safe[2] + 1 && rect.y + rect.h <= safe[3] + 1;
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

// ------------------------------------------------------------------ boundary

test('a valid plate layer passes the boundary in every format', () => {
  const layer = {layout_id: 'plate', layout_version: 1, title: 'Tu pan, recién horneado', subtitle: 'Masa madre', anchor: 'top_left', container_color: 'surface', accent_word: 1};
  assert.deepEqual(layerProblems(catalog, layer, {formats: FORMATS, hasPhoto: true}), []);
});

test('unknown layout ids, unknown fields and over-limit slots are refused loudly', () => {
  const p1 = layerProblems(catalog, {layout_id: 'poster', layout_version: 1}, {formats: ['4:5'], hasPhoto: true});
  assert.match(p1.join(), /unknown layout 'poster'/);
  const p2 = layerProblems(catalog, {layout_id: 'plate', layout_version: 1, title: 'x'.repeat(29), headline: 'y'}, {formats: ['4:5'], hasPhoto: true});
  assert.match(p2.join(), /29 chars exceeds 28/);
  assert.match(p2.join(), /layer\.headline: unknown field/);
  // 1:1 is stricter than 4:5 for the same layout
  const p3 = layerProblems(catalog, {layout_id: 'plate', layout_version: 1, title: 'x'.repeat(25)}, {formats: ['4:5', '1:1'], hasPhoto: true});
  assert.equal(p3.length, 1);
  assert.match(p3[0], /in 1:1/);
});

test('parameters a layout does not take are refused', () => {
  const p = layerProblems(catalog, {layout_id: 'scrim', layout_version: 1, title: 'Hola', container_color: 'accent', accent_word: 0, anchor: 'top_left', call_phrase: 'Ven hoy'}, {formats: ['1:1'], hasPhoto: true});
  const all = p.join(' | ');
  assert.match(all, /container_color: 'scrim' takes none/);
  assert.match(all, /accent_word: 'scrim' takes none/);
  assert.match(all, /anchor: 'top_left' is not an anchor/);
  assert.match(all, /has no call_phrase in 1:1/);
});

test('brand_fill takes contact, location or hours (catalog §1.6 = §2.6 since PR #670)', () => {
  const base = {layout_id: 'brand_fill', layout_version: 1, title: 'Abrimos el festivo'};
  assert.deepEqual(layerProblems(catalog, {...base, info_blocks: [{kind: 'hours', value: 'De 8 a 20'}]}, {formats: ['4:5'], hasPhoto: false}), []);
  assert.match(layerProblems(catalog, {...base, info_blocks: [{kind: 'payment', value: 'Efectivo'}]}, {formats: ['4:5'], hasPhoto: false}).join(), /'payment' not allowed/);
  assert.match(layerProblems(catalog, {layout_id: 'brand_fill', layout_version: 1}, {formats: ['4:5'], hasPhoto: false}).join(), /title: required/);
});

test('info blocks need their saved value and respect the count with a photo strip', () => {
  const blocks = ['location', 'hours', 'payment', 'contact'].map((kind) => ({kind, value: 'Dato guardado'}));
  const layer = {layout_id: 'info_card', layout_version: 1, title: 'Te esperamos', info_blocks: blocks};
  assert.deepEqual(layerProblems(catalog, layer, {formats: ['4:5'], hasPhoto: false}), []);
  assert.match(layerProblems(catalog, {...layer, photo_strip: true}, {formats: ['4:5'], hasPhoto: true}).join(), /takes 1–3 with a photo strip/);
  const missing = {...layer, info_blocks: [{kind: 'location', value: ''}]};
  assert.match(layerProblems(catalog, missing, {formats: ['4:5'], hasPhoto: false}).join(), /saved value is required/);
});

test('highlight_circle is 9:16 only; a carousel has no 9:16 slide', () => {
  const hc = {layout_id: 'highlight_circle', layout_version: 1, highlight_content: {kind: 'word', word: 'Menú'}};
  assert.deepEqual(layerProblems(catalog, hc, {formats: ['9:16'], hasPhoto: false}), []);
  assert.match(layerProblems(catalog, hc, {formats: ['4:5'], hasPhoto: false}).join(), /does not exist in 4:5/);
  assert.match(layerProblems(catalog, {...hc, highlight_content: {kind: 'word', word: 'Promociones'}}, {formats: ['9:16'], hasPhoto: false}).join(), /exceeds 9/);
  const carousel = {index: 0, count: 5, role: 'cover'};
  assert.match(layerProblems(catalog, {layout_id: 'band', layout_version: 1, title: 'Hola', carousel}, {formats: ['9:16'], hasPhoto: true}).join(), /no 9:16 slide/);
  assert.match(layerProblems(catalog, {layout_id: 'band', layout_version: 1, title: 'Hola', carousel: {index: 1, count: 5, role: 'cover'}}, {formats: ['4:5'], hasPhoto: true}).join(), /slide 2 of 5 is the body/);
});

test('the m-25017283 shape: photo reading, price_ref object, fixed labels, format per port', () => {
  const spec = {
    spec_version: 1,
    layout_id: 'plate',
    layout_version: 1,
    format: '4:5',
    photo: {subject_box: [0.2, 0.5, 0.8, 0.9], logo_in_photo: false, base_has_invented_text: false},
    title: 'Tu pan de hoy',
    price_ref: {product_id: '00000000-0000-4000-8000-000000000001'},
    fallbacks: [],
  };
  assert.deepEqual(layerProblems(catalog, spec, {formats: ['4:5'], hasPhoto: true}), []);
  assert.match(layerProblems(catalog, spec, {formats: ['1:1'], hasPhoto: true}).join(), /the spec is for 4:5, the port renders 1:1/);
  assert.match(layerProblems(catalog, {...spec, price_ref: 'p-1'}, {formats: ['4:5'], hasPhoto: true}).join(), /expected \{product_id\}/);
  assert.match(layerProblems(catalog, {...spec, photo: {subject_box: [0.2, 0.5, 0.8, 0.9]}}, {formats: ['4:5'], hasPhoto: true}).join(), /logo_in_photo: expected a boolean/);
  const info = {layout_id: 'info_card', layout_version: 1, title: 'Te esperamos', info_blocks: [{kind: 'location', label: 'Ubicación', value: 'Calle 10'}]};
  assert.match(layerProblems(catalog, info, {formats: ['4:5'], hasPhoto: false}).join(), /the label of a location block is «Dónde estamos»/);
  assert.match(layerProblems(catalog, {...info, photo_strip: true}, {formats: ['4:5'], hasPhoto: false}).join(), /photo_strip: needs the photo/);
});

test('the server validator answers per requested port (422 before a job exists)', () => {
  const props = {brand: {}, photos: ['asset://a'], layer: {layout_id: 'plate', layout_version: 1, title: 'x'.repeat(26)}};
  assert.deepEqual(validateProps(manifest, props, ['feed']), []);
  assert.match(validateProps(manifest, props, ['square']).join(), /26 chars exceeds 24/);
  assert.match(validateProps(manifest, {...props, layer: undefined}, ['feed']).join(), /expected an object/);
});

// ------------------------------------------------------------------ contrast (§1.3)

test('text colour: the first of [palette.text, white, near-black] at 4.5:1', () => {
  assert.ok(contrast('#FFFFFF', '#000000') > 20);
  const mid = textColorOn('#777777', {accent: '#777777', text: '#888888', surface: '#777777'});
  assert.ok(mid.ratio >= 4.5, `got ${mid.ratio}`);
  assert.equal(mid.color, '#000000'); // #111111 only reaches 4.21 on #777777
  for (const bg of ['#FFFFFF', '#000000', '#777777', '#F4C2C2', '#0F766E', '#FFD400']) {
    assert.ok(textColorOn(bg, palette).ratio >= 4.5, bg);
  }
});

test('the accent word falls back to the text colour below 3:1 (accent container)', () => {
  const r = run({layout_id: 'plate', title: 'Tu pan recién hecho', anchor: 'top_left', container_color: 'accent', accent_word: 1, subject_box: [0.5, 0.6, 0.9, 0.95]});
  assert.equal(r.report.layout_rendered, 'plate');
  assert.ok(r.report.fallbacks.some((f) => f.startsWith('accent_word')));
  const colours = new Set(r.texts.filter((t) => t.slot === 'title').flatMap((t) => t.lines.flatMap((l) => l.spans.map((s) => s.color))));
  assert.equal(colours.size, 1);
});

// ------------------------------------------------------------------ checks and the chain (§1.7)

test('plate: an anchor that covers the subject moves to the next anchor', () => {
  const r = run({layout_id: 'plate', title: 'Tu pan, recién horneado', anchor: 'bottom_left', subject_box: [0, 0.55, 0.6, 1]});
  assert.equal(r.report.layout_rendered, 'plate');
  assert.notEqual(r.report.anchor, 'bottom_left');
  assert.match(r.report.fallbacks[0], /plate\/bottom_left: covers_subject/);
});

test('plate: a subject that fills the frame ends on band, recorded step by step', () => {
  const r = run({layout_id: 'plate', title: 'Tu pan, recién horneado', anchor: 'top_left', subject_box: [0.05, 0.05, 0.95, 0.95]});
  assert.equal(r.report.layout_requested, 'plate');
  assert.equal(r.report.layout_rendered, 'band');
  assert.equal(r.report.fallbacks.filter((f) => f.startsWith('plate/')).length, 6);
  assert.equal(r.photo.fit, 'contain'); // the subject cannot be cropped into the window
});

test('plate: a word too long for the plate at the minimum size goes to band', () => {
  const r = run({layout_id: 'plate', title: 'Supercalifragilístico', anchor: 'top_left', subject_box: [0.5, 0.6, 0.9, 0.95]});
  assert.equal(r.report.layout_rendered, 'band');
  assert.ok(r.report.fallbacks.some((f) => /title_does_not_fit|no_room_beside_subject/.test(f)));
});

test('scrim: subject reaching the text edge falls to band; text sits where the shadow is ≥ 60 %', () => {
  const ok = run({layout_id: 'scrim', title: 'Así se ve el almuerzo', anchor: 'bottom', subject_box: [0.2, 0.1, 0.8, 0.5]});
  assert.equal(ok.report.layout_rendered, 'scrim');
  const top = Math.min(...lineRects(ok).map((l) => l.y));
  assert.ok(top >= ok.scrim.solid, 'every line below the 60 % point');
  assert.ok(ok.scrim.start < ok.scrim.solid);
  const moved = run({layout_id: 'scrim', title: 'Así se ve el almuerzo', anchor: 'bottom', subject_box: [0.1, 0.2, 0.9, 0.95]});
  assert.notEqual(moved.report.layout_rendered + moved.report.anchor, 'scrimbottom');
});

test('dropping order when the text does not fit: call_phrase first, then subtitle; never the title', () => {
  const r = run({
    layout_id: 'band',
    title: 'Tu pan recién horneado',
    subtitle: 'Masa madre de la casa con harina integral y semillas tostadas, todos los días',
    call_phrase: 'Pídelo por WhatsApp hoy',
    anchor: 'bottom',
  }, {format: '1:1', photo: {width: 1080, height: 1080}, slide: {index: 2, total: 5, role: 'body'}});
  assert.equal(r.report.dropped_slots[0], 'call_phrase'); // 1:1 band: no call phrase next to a subtitle
  assert.ok(r.texts.some((t) => t.slot === 'title'));
});

test('photo_only without title; a text layout without title becomes photo_only', () => {
  const r = run({layout_id: 'plate', title: '', anchor: 'top_left'});
  assert.equal(r.report.layout_rendered, 'photo_only');
  assert.equal(r.texts.length, 0);
  assert.equal(r.photo.fit, 'cover');
});

// ------------------------------------------------------------------ logo and counter (§4)

test('logo: first free corner; none when the photo already shows it', () => {
  const r = run({layout_id: 'plate', title: 'Tu pan', anchor: 'top_left', subject_box: [0.3, 0.5, 0.7, 0.8]});
  assert.equal(r.report.logo, 'top_right');
  const none = run({layout_id: 'plate', title: 'Tu pan', anchor: 'top_left', subject_box: [0.3, 0.6, 0.7, 0.9], logo_in_photo: true});
  assert.equal(none.report.logo, 'in_photo');
  assert.equal(none.logo, null);
});

test('carousel: counter on every slide, logo only on the first and last', () => {
  const layer = {layout_id: 'band', title: 'Paso dos: el horno', anchor: 'top', subject_box: [0.3, 0.5, 0.7, 0.9]};
  const body = run(layer, {slide: {index: 2, total: 5, role: 'body'}});
  assert.equal(body.counter.text, '2/5');
  assert.equal(body.logo, null);
  const last = run({...layer, layout_id: 'brand_fill', anchor: null, subject_box: null}, {slide: {index: 5, total: 5, role: 'closing'}, photo: null});
  assert.ok(last.logo);
  assert.equal(last.counter.text, '5/5');
  const inBand = run({...layer, anchor: 'bottom', subject_box: [0.3, 0.1, 0.7, 0.5]}, {slide: {index: 1, total: 3, role: 'cover'}});
  assert.equal(inBand.report.counter, 'bottom_right_in_band');
  assert.equal(inBand.counter.background, null);
});

// ------------------------------------------------------------------ the case table of catalog §9

const SUBJECTS = {
  none: null,
  top_third: [0.2, 0.05, 0.8, 0.33],
  middle_third: [0.2, 0.35, 0.8, 0.65],
  bottom_third: [0.2, 0.67, 0.8, 0.95],
  full: [0.05, 0.05, 0.95, 0.95],
};
const PALETTES = {
  clear: {accent: '#FFE8A3', text: '#FFFFFF', surface: '#FFFFFF'},
  medium: {accent: '#777777', text: '#777777', surface: '#777777'},
  default: {accent: '#0F766E', text: '#FFFFFF', surface: '#F8FAFC'},
};
const LONG_WORD_TITLE = 'Empanadas extraordinarias'; // 13-char word + max-ish title
const photoFor = (f) => ({'4:5': {width: 1080, height: 1350}, '1:1': {width: 1080, height: 1080}, '9:16': {width: 1080, height: 1920}})[f];

for (const layout of ['plate', 'scrim', 'band', 'photo_only']) {
  for (const format of FORMATS) {
    test(`${layout} ${format}: every subject × palette × logo stays legal`, () => {
      for (const [sname, subject_box] of Object.entries(SUBJECTS)) {
        for (const [pname, pal] of Object.entries(PALETTES)) {
          for (const hasLogo of [true, false]) {
            const layer = {
              layout_id: layout,
              title: layout === 'photo_only' ? null : LONG_WORD_TITLE,
              subtitle: layout === 'photo_only' || (layout === 'scrim' && format === '1:1') ? null : 'Recién hechas',
              subject_box,
            };
            const r = run(layer, {format, photo: photoFor(format), palette: pal, hasLogo});
            const label = `${layout} ${format} ${sname} ${pname} logo=${hasLogo} → ${r.report.layout_rendered}`;
            const safe = catalog.formats[format].safe;
            for (const l of lineRects(r)) assert.ok(within(l, safe), `${label}: line outside the safe zone ${JSON.stringify(l)}`);
            if (r.logo) assert.ok(within(r.logo.rect, safe), `${label}: logo outside the safe zone`);
            if (r.report.layout_rendered !== 'band' && subject_box && r.photo) {
              const s = r.photo.box;
              const subj = {x: s.x + subject_box[0] * s.w, y: s.y + subject_box[1] * s.h, w: (subject_box[2] - subject_box[0]) * s.w, h: (subject_box[3] - subject_box[1]) * s.h};
              for (const l of lineRects(r)) assert.ok(!overlap(l, subj), `${label}: text over the subject`);
            }
            for (const [k, v] of Object.entries(r.report.contrast)) {
              if (k === 'accent_word') continue;
              assert.ok(v >= 4.5, `${label}: contrast ${k}=${v}`);
            }
            assert.equal(r.report.overflow.length, 0, `${label}: ${r.report.overflow.join()}`);
          }
        }
      }
    });
  }
}

test('9:16 stories keep text and logo inside y 270–1536', () => {
  for (const layout of ['plate', 'band', 'scrim']) {
    const r = run({layout_id: layout, title: 'Tu shawarma, recién hecho', subtitle: 'Salsa de la casa', subject_box: [0.3, 0.45, 0.7, 0.7]}, {format: '9:16', photo: photoFor('9:16')});
    for (const l of lineRects(r)) assert.ok(l.y >= 270 && l.y + l.h <= 1536, `${layout}: ${JSON.stringify(l)}`);
    if (r.logo) assert.ok(r.logo.rect.y >= 270);
  }
});

test('info_card and brand_fill lay out at the catalog limits without overflow (fake metrics)', () => {
  const value = (n) => 'Calle 10 # 4-25, local 3, frente al parque principal centro'.slice(0, n);
  for (const format of FORMATS) {
    const lim = catalog.layouts.info_card.value[format][0];
    const max = catalog.layouts.info_card.blocks[format][1];
    const kinds = ['location', 'hours', 'payment', 'products'].slice(0, max);
    const r = run(
      {layout_id: 'info_card', title: 'Te esperamos', info_blocks: kinds.map((kind) => ({kind, value: value(lim)}))},
      {format, photo: null},
    );
    assert.equal(r.report.layout_rendered, 'info_card');
    assert.deepEqual(r.report.overflow, [], `${format}: ${r.report.overflow}`);
    const one = run({layout_id: 'info_card', title: 'Horario', info_blocks: [{kind: 'hours', value: 'Lunes a sábado de 8 a 20'}]}, {format, photo: null});
    assert.equal(one.icons[0].size, 120);
    const bf = run({layout_id: 'brand_fill', title: 'Este festivo abrimos todo el día', subtitle: 'Te esperamos con el horno encendido', call_phrase: 'Te esperamos hoy', info_blocks: [{kind: 'contact', value: '+57 300 000 0000'}]}, {format, photo: null});
    assert.equal(bf.report.layout_rendered, 'brand_fill');
    assert.equal(bf.report.logo, 'top_center');
  }
});

test('info_card has no fallback layout: a title over its lines is drawn at the minimum and reported', () => {
  const r = run({layout_id: 'info_card', title: 'Te esperamos en el local', info_blocks: [{kind: 'hours', value: 'De 8 a 20'}]}, {format: '1:1', photo: null});
  assert.equal(r.report.layout_rendered, 'info_card');
  assert.match(r.report.overflow.join(), /title needs 2 lines at 72 px \(limit 1\)/);
});

test('wrap never cuts a word', () => {
  const at = (s) => s.length * 10;
  assert.deepEqual(wrap('uno dos tres', 70, at), ['uno dos', 'tres']);
  assert.equal(wrap('palabralarguisima', 50, at), null);
});

test('same input, same boxes (deterministic)', () => {
  const layer = {layout_id: 'plate', title: 'Tu pan, recién horneado', anchor: 'top_left', subject_box: [0.3, 0.4, 0.7, 0.8]};
  assert.deepEqual(run(layer), run(layer));
});
