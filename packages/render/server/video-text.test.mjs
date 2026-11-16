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
import {resolveLayer} from '../src/templates/layer_still/engine.ts';
import {resolveVideoText, TEXT_MAX} from '../src/templates/video_text/layout.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (...p) => JSON.parse(fs.readFileSync(path.join(here, '..', 'templates', ...p), 'utf8'));
const manifest = read('video_text', 'manifest.json');
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
