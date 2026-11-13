// Sticker v2 «caption» mode (m-25017372): the art (a product character) above a 1–2 line
// message on its own white die-cut, every motion kept inside WhatsApp's 16 px margin.
//
// Pure geometry, no React and no runtime imports (only `import type`), so the Node tests
// (`server/sticker-caption.test.mjs`) load this file directly with Node's type stripping
// and check every motion frame by frame against the same numbers the composition draws.
import type {Motion} from './motion';

export const CELL = 512;
/** WhatsApp's guideline: 16 px clear around the art. */
export const MARGIN = 16;
export const OUTLINE_ART = 15;
export const OUTLINE_TEXT = 15;
export const LINE_HEIGHT = 1.08;
export const CENTER = CELL / 2;

/** The caption: at most 2 lines, 440 px wide, 118 px of text height. */
export const CAPTION_MAX_W = 440;
export const CAPTION_MAX_H = 118;
export const CAPTION_MAX_LINES = 2;
export const CAPTION_MAX_PX = 64;
export const CAPTION_MIN_PX = 24;
/** The caption block's padding: its die-cut outline plus breathing room. */
export const CAPTION_PAD = OUTLINE_TEXT + 4;
/** Where the caption block's bottom edge sits (inside the margin, room for its shadow). */
export const CAPTION_BOTTOM = CELL - MARGIN - 4;
/** Clear space between the art's outline and the caption block. */
export const CAPTION_GAP = 10;
/** The highest the art's outline may reach, at the peak of any motion. */
export const ART_TOP = MARGIN + OUTLINE_ART + 6;
/** The widest the art is drawn with a caption (the bench: wider looks crowded). */
export const CAPTION_ART_MAX_W = 350;
export const CAPTION_ART_MAX_H = 370;

export type Size = {w: number; h: number};
export type CaptionLayout = {lines: string[][]; px: number};

/**
 * How far each motion reaches beyond the art's resting box (motion.ts, sampled by the
 * tests): `grow` is the largest scale, `hop` the largest lift in px. `rebote` scales from
 * the ground line (bottom origin), the others from the centre.
 */
export const MOTION_REACH: Record<Exclude<Motion, 'texto'>, {grow: number; growX: number; hop: number; bottom: boolean}> = {
  latido: {grow: 1.15, growX: 1.15, hop: 0, bottom: false},
  rebote: {grow: 1.1, growX: 1.1, hop: 74, bottom: true},
  giro: {grow: 1.0, growX: 1.0, hop: 26, bottom: false},
  brillo: {grow: 1.05, growX: 1.05, hop: 0, bottom: false},
};

/** Height of the caption block (text + its padding). */
export const captionHeight = (lines: number, px: number): number =>
  lines * px * LINE_HEIGHT + 2 * CAPTION_PAD;

/** The caption block's top edge. */
export const captionTopOf = (layout: CaptionLayout): number =>
  CAPTION_BOTTOM - captionHeight(layout.lines.length, layout.px);

/** The lowest the art's own pixels may reach (its outline then stops `CAPTION_GAP` above). */
export const artBottomOf = (captionTop: number): number => captionTop - CAPTION_GAP - OUTLINE_ART;

/** The art's room: from `ART_TOP` (outline included) to `artBottomOf` (art only). */
export const artRoomOf = (captionTop: number): number => artBottomOf(captionTop) - (ART_TOP + OUTLINE_ART);

/** The largest box of the art's aspect whose motion stays inside the room. */
export const captionArtBox = (natural: Size, motion: Exclude<Motion, 'texto'>, captionTop: number): Size => {
  const reach = MOTION_REACH[motion];
  const room = artRoomOf(captionTop);
  const maxH = Math.max(1, Math.min(CAPTION_ART_MAX_H, (room - reach.hop) / reach.grow));
  const maxW = Math.min(CAPTION_ART_MAX_W, (CELL - 2 * MARGIN - 2 * OUTLINE_ART) / reach.growX);
  const k = Math.min(maxW / natural.w, maxH / natural.h);
  return {w: Math.floor(natural.w * k), h: Math.floor(natural.h * k)};
};

/** Where the resting art sits: its top-left corner and the transform origin. */
export const captionArtPlace = (
  box: Size,
  motion: Exclude<Motion, 'texto'>,
  captionTop: number,
): {left: number; top: number; cx: number; cy: number} => {
  const reach = MOTION_REACH[motion];
  const bottom = artBottomOf(captionTop);
  const left = CENTER - box.w / 2;
  if (reach.bottom) {
    const top = bottom - box.h;
    return {left, top, cx: CENTER, cy: top + box.h / 2};
  }
  // centred in the room, shifted down by the hop so the lift has its headroom
  const cy = (ART_TOP + OUTLINE_ART + reach.hop + bottom) / 2;
  return {left, top: cy - box.h / 2, cx: CENTER, cy};
};

/** The heartbeat rings' largest radius around the art's centre, inside the cell margin. */
export const captionRingMax = (cy: number, box: Size): number => {
  const fit = Math.min(CENTER - MARGIN - 4, cy - MARGIN - 4);
  return Math.max(Math.min(box.w, box.h) * 0.42 + 12, fit);
};

/** A sparkle's centre, kept inside the margin and above the caption. */
export const clampSparkle = (x: number, y: number, size: number, captionTop: number | null): [number, number] => {
  const half = size / 2;
  const lowest = captionTop === null ? CELL - MARGIN - half : Math.min(CELL - MARGIN - half, captionTop - CAPTION_GAP - half);
  return [
    Math.min(CELL - MARGIN - half, Math.max(MARGIN + half, x)),
    Math.min(lowest, Math.max(MARGIN + half, y)),
  ];
};

/**
 * Greedy wrap of the message at the largest size that fits 2 lines of `CAPTION_MAX_W`.
 * `measure(word, px)` is the width of `word` in the brand face at `px` (canvas in the
 * composition, a fixed-advance estimate in the tests). Never wider than the box: a word
 * that does not fit even at the smallest size is drawn at it (Python caps the message at
 * 25 characters, so this does not happen with real faces).
 */
export const fitCaption = (text: string, measure: (s: string, px: number) => number): CaptionLayout => {
  const words = text.split(/\s+/).filter(Boolean);
  for (let px = CAPTION_MAX_PX; px >= CAPTION_MIN_PX; px -= 2) {
    const space = measure(' ', px);
    const lines: string[][] = [[]];
    let width = 0;
    let fits = true;
    for (const word of words) {
      const w = measure(word, px);
      if (w > CAPTION_MAX_W) {
        fits = false;
        break;
      }
      const line = lines[lines.length - 1]!;
      if (line.length > 0 && width + space + w > CAPTION_MAX_W) {
        lines.push([word]);
        width = w;
      } else {
        width += (line.length > 0 ? space : 0) + w;
        line.push(word);
      }
    }
    if (fits && lines.length <= CAPTION_MAX_LINES && lines.length * px * LINE_HEIGHT <= CAPTION_MAX_H) {
      return {lines, px};
    }
  }
  return {lines: [words], px: CAPTION_MIN_PX};
};
