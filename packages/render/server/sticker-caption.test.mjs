// node --test: the sticker template v2 «caption» mode (m-25017372, product stickers). No
// Chromium: the manifests are validated and the geometry of caption.ts is checked frame by
// frame against the motions of motion.ts (both loaded with Node's TypeScript stripping) —
// the same numbers the composition draws with.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {validateProps} from './validate.mjs';
import {
  CAPTION_BOTTOM,
  CAPTION_GAP,
  CAPTION_MAX_LINES,
  CAPTION_MAX_W,
  CELL,
  MARGIN,
  OUTLINE_ART,
  captionArtBox,
  captionArtPlace,
  captionHeight,
  captionRingMax,
  captionTopOf,
  clampSparkle,
  fitCaption,
} from '../src/templates/sticker/caption.ts';
import {poseAt} from '../src/templates/sticker/motion.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, '..', 'templates', 'sticker');
const v2 = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'));
const v1 = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.v1.json'), 'utf8'));

const FRAMES = v2.sheet.frames;
const FPS = v2.sheet.fps;
const MOTIONS = ['latido', 'rebote', 'giro', 'brillo'];
const ASPECTS = [
  {w: 700, h: 700},
  {w: 400, h: 800},
  {w: 800, h: 400},
  {w: 690, h: 729},
];
/** A wide face (Unbounded-like): every glyph 0.72 em, a space 0.3 em. */
const wide = (s, px) => (s === ' ' ? 0.3 * px : s.length * 0.72 * px);
const MESSAGES = ['Bienvenido', 'En camino', 'Entregado', 'Listo para recoger', '¡Gracias por tu pedido!', 'Ñandú'];

const props = (over = {}) => ({
  meta: {templateId: 'sticker', version: 2, port: 'sheet'},
  brand: {name: '', palette: ['#c5093b', '#ffcd00'], fonts: {heading: 'Unbounded'}},
  texts: {motion: 'rebote', text: '¡Gracias por tu pedido!', captionInk: '#c5093b'},
  art: 'asset://' + 'a'.repeat(64),
  ...over,
});

test('v2 is the latest sticker, v1 is kept unchanged for pinned renders', () => {
  assert.equal(v2.version, 2);
  assert.equal(v1.version, 1);
  assert.equal(v2.outputs.sheet.composition, 'sticker-v2--sheet');
  assert.equal(v1.outputs.sheet.composition, 'sticker-v1--sheet');
  assert.equal(v1.inputs.captionInk, undefined);
  assert.deepEqual(v1.sheet, v2.sheet);
});

test('a caption sticker passes the v2 manifest; a bad ink colour is refused by length', () => {
  assert.deepEqual(validateProps(v2, props()), []);
  assert.deepEqual(validateProps(v2, props({texts: {motion: 'latido', text: 'En camino', captionBacking: '#231f20'}})), []);
  assert.ok(validateProps(v2, props({texts: {motion: 'rebote', text: 'x', captionInk: '#c5093bff'}})).length > 0);
});

test('the presets fit in at most two lines inside the caption box', () => {
  for (const message of MESSAGES) {
    const layout = fitCaption(message, wide);
    assert.ok(layout.lines.length <= CAPTION_MAX_LINES, message);
    for (const line of layout.lines) {
      const width = line.reduce((sum, word, i) => sum + wide(word, layout.px) + (i ? wide(' ', layout.px) : 0), 0);
      assert.ok(width <= CAPTION_MAX_W, `${message}: ${width}`);
    }
  }
  assert.equal(fitCaption('Bienvenido', wide).lines.length, 1);
  assert.equal(fitCaption('¡Gracias por tu pedido!', wide).lines.length, 2);
});

/** The art's outline box at time t (scale about the motion's origin, then the lift). */
const extentAt = (motion, box, place, t) => {
  const pose = poseAt(motion, t);
  const w = box.w * pose.scaleX;
  const h = box.h * pose.scaleY;
  const left = place.cx - w / 2;
  const top = pose.origin === 'bottom' ? place.top + box.h - h : place.cy - h / 2;
  return {
    left: left - OUTLINE_ART,
    right: left + w + OUTLINE_ART,
    top: top + pose.translateY - OUTLINE_ART,
    bottom: top + h + pose.translateY + OUTLINE_ART,
  };
};

test('every motion, every frame: the art stays inside the 16 px margin and above the caption', () => {
  for (const motion of MOTIONS) {
    for (const message of MESSAGES) {
      const layout = fitCaption(message, wide);
      const top = captionTopOf(layout);
      for (const natural of ASPECTS) {
        const box = captionArtBox(natural, motion, top);
        const place = captionArtPlace(box, motion, top);
        assert.ok(box.w > 60 && box.h > 60, `${motion}/${message}: art too small ${box.w}x${box.h}`);
        for (let i = 0; i < FRAMES; i++) {
          const e = extentAt(motion, box, place, i / FPS);
          const where = `${motion} «${message}» ${natural.w}x${natural.h} frame ${i}`;
          assert.ok(e.left >= MARGIN && e.right <= CELL - MARGIN, `${where}: x ${e.left}..${e.right}`);
          assert.ok(e.top >= MARGIN, `${where}: top ${e.top}`);
          assert.ok(e.bottom <= top - CAPTION_GAP + 0.5, `${where}: bottom ${e.bottom} over caption ${top}`);
        }
        if (motion === 'latido') {
          const ring = captionRingMax(place.cy, box);
          assert.ok(place.cy - ring >= MARGIN, `${motion}: ring crosses the top margin`);
        }
      }
    }
  }
});

test('the caption block sits inside the margin', () => {
  for (const lines of [1, 2]) {
    for (const px of [24, 40, 54]) {
      const top = CAPTION_BOTTOM - captionHeight(lines, px);
      assert.ok(top > CELL / 2, `${lines}x${px}`);
      assert.ok(CAPTION_BOTTOM <= CELL - MARGIN);
    }
  }
});

test('a long message with a hop leaves a readable character; a short one a big one', () => {
  const big = captionArtBox({w: 700, h: 700}, 'rebote', captionTopOf(fitCaption('Bienvenido', wide)));
  const long = captionArtBox({w: 700, h: 700}, 'latido', captionTopOf(fitCaption('¡Gracias por tu pedido!', wide)));
  assert.ok(big.h >= 190, `rebote, 1 line: ${big.h}`);
  assert.ok(long.h >= 190, `latido, 2 lines: ${long.h}`);
});

test('sparkles stay inside the margin and above the caption', () => {
  const top = 380;
  for (const [x, y, size] of [[500, 10, 78], [0, 600, 64], [256, 370, 58]]) {
    const [cx, cy] = clampSparkle(x, y, size, top);
    assert.ok(cx - size / 2 >= MARGIN && cx + size / 2 <= CELL - MARGIN);
    assert.ok(cy - size / 2 >= MARGIN && cy + size / 2 <= top - CAPTION_GAP);
  }
});
