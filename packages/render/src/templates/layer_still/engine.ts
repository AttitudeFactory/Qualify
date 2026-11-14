// The deterministic compositor of `layer_still` v1 (m-25017285): from a validated LayerSpec,
// the brand palette, the format and a text measurer, it decides every pixel box — font
// sizes, line breaks, containers, the scrim, the logo corner, the counter — runs the checks
// of docs/catalogo-disenos-imagen-carrusel.md §1.7 and walks the fixed fallback chain down
// to `band`. No AI, no randomness, no React, no runtime imports (only `import type`): the
// composition calls it from calculateMetadata with a canvas measurer and real fonts; the Node
// tests (`server/layer-still.test.mjs`) load this file with Node's type stripping and a
// fake measurer. Same input → same boxes.

export type Format = '4:5' | '1:1' | '9:16';
export type LayoutId = 'photo_only' | 'plate' | 'scrim' | 'band' | 'info_card' | 'brand_fill' | 'highlight_circle';
export type Rect = {x: number; y: number; w: number; h: number};
export type FontRole = 'heading' | 'body';
export type Measure = (text: string, font: {role: FontRole; size: number; weight: number}) => number;

export type InfoBlock = {kind: string; value: string};
export type HighlightContent = {type: 'icon'; icon_id: string} | {type: 'word'; word: string} | {type: 'photo'};
export type Layer = {
  layout_id: LayoutId;
  layout_version: number;
  title?: string | null;
  subtitle?: string | null;
  call_phrase?: string | null;
  info_blocks?: InfoBlock[] | null;
  price_ref?: string | null;
  anchor?: string | null;
  container_color?: 'surface' | 'accent' | null;
  accent_word?: number | null;
  highlight_content?: HighlightContent | null;
  subject_box?: [number, number, number, number] | null;
  logo_in_photo?: boolean | null;
  layer_id?: string | null;
};
export type Slide = {index: number; total: number; role: 'cover' | 'body' | 'closing'};
export type Palette = {accent: string; text: string; surface: string};

type SizePair = [number, number];
type SlotLimit = [number, number];
type LayoutDef = {
  formats: Format[];
  anchors: string[];
  default_anchor?: string;
  container_color: boolean;
  default_container?: 'surface' | 'accent';
  accent_word: boolean;
  price: boolean;
  slots: Partial<Record<'title' | 'subtitle' | 'call_phrase', Partial<Record<Format, SlotLimit>>>>;
  max_width?: Partial<Record<Format, number>>;
  padding?: number;
  radius?: number;
  cover?: number;
  max_alpha?: number;
  text_alpha?: number;
  height?: Partial<Record<Format, [number, number]>>;
  story_band_top?: number;
  photo_strip?: Partial<Record<Format, number>>;
  blocks?: Partial<Record<Format, [number, number, number]>>;
  kinds?: string[];
  value?: Partial<Record<Format, SlotLimit>>;
  logo_size?: number;
  circle?: {cx: number; cy: number; d: number};
  icon_size?: number;
  word_max?: number;
};
export type Catalog = {
  layout_version: number;
  formats: Record<Format, {width: number; height: number; margin: number; safe: [number, number, number, number]; title_zone_x: [number, number]}>;
  font_sizes: Record<string, Partial<Record<Format, SizePair>>>;
  script_title_min: number;
  script_families: string[];
  info_kinds: Record<string, {label: string; icon: string; icon_not_food?: string}>;
  highlight_icons: string[];
  layouts: Record<LayoutId, LayoutDef>;
};

export type Input = {
  catalog: Catalog;
  format: Format;
  layer: Layer;
  /** natural size of photos[0]; null = no photo */
  photo: {width: number; height: number} | null;
  priceText: string;
  isFood: boolean;
  slide: Slide | null;
  palette: Palette;
  headingFamily: string;
  hasLogo: boolean;
  measure: Measure;
};

// ------------------------------------------------------------------ output shape

export type Span = {text: string; color: string};
export type Line = {x: number; y: number; width: number; spans: Span[]};
export type TextBlock = {
  slot: string;
  role: FontRole;
  size: number;
  weight: number;
  lineHeight: number;
  align: 'left' | 'center';
  lines: Line[];
};
export type PhotoPlacement = {
  /** where the photo is drawn (its window) */
  window: Rect;
  fit: 'cover' | 'contain';
  /** the photo's drawn box inside the window (may overflow it when fit=cover) */
  box: Rect;
  circle?: boolean;
};
export type Report = {
  layer_id: string | null;
  layout_requested: LayoutId;
  layout_rendered: LayoutId;
  anchor: string | null;
  format: Format;
  fallbacks: string[];
  dropped_slots: string[];
  sizes: Record<string, number>;
  contrast: Record<string, number>;
  logo: string;
  counter: string | null;
  overflow: string[];
};
export type Resolved = {
  width: number;
  height: number;
  background: string;
  photo: PhotoPlacement | null;
  scrim: {edge: 'top' | 'bottom'; start: number; solid: number; end: number; textAlpha: number; maxAlpha: number} | null;
  containers: Array<{rect: Rect; color: string; radius: number}>;
  texts: TextBlock[];
  icons: Array<{id: string; x: number; y: number; size: number; color: string}>;
  logo: {rect: Rect; tile: string; radius: number} | null;
  counter: {rect: Rect; text: string; color: string; background: string | null; size: number} | null;
  report: Report;
};

// ------------------------------------------------------------------ colour

const hex = (c: string): [number, number, number] => {
  let s = c.trim().replace('#', '');
  if (s.length === 3) s = s.split('').map((ch) => ch + ch).join('');
  s = s.slice(0, 6);
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};
const channel = (v: number): number => {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
export const luminance = (c: string): number => {
  const [r, g, b] = hex(c);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
};
/** WCAG 2 contrast ratio, 1–21. */
export const contrast = (a: string, b: string): number => {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};
export const TEXT_MIN = 4.5;
export const LARGE_MIN = 3;
/**
 * §1.3: the first of [palette.text, white, near-black] that reaches 4.5:1 on `bg` — plus pure
 * black as a last resort: measured, #111111 does NOT always reach 4.5:1 (on #777777 white gives
 * 4.48 and #111111 gives 4.21; only #000000 clears it, 4.69). Catalog finding, m-25017285.
 */
export const textColorOn = (bg: string, palette: Palette): {color: string; ratio: number} => {
  const candidates = [palette.text, '#FFFFFF', '#111111', '#000000'];
  for (const c of candidates) {
    const r = contrast(c, bg);
    if (r >= TEXT_MIN) return {color: c, ratio: r};
  }
  // unreachable for opaque colours (white or near-black always clears 4.5 on one side)
  const best = candidates.reduce((a, b) => (contrast(b, bg) > contrast(a, bg) ? b : a));
  return {color: best, ratio: contrast(best, bg)};
};

// ------------------------------------------------------------------ text fitting

export const LINE_HEIGHT = {title: 1.08, other: 1.25};
const WIDTH_SLACK = 2; // px kept free on every line (sub-pixel shaping differences)

/** Greedy word wrap; null if a single word is wider than maxWidth (words are never cut). */
export const wrap = (text: string, maxWidth: number, measureAt: (s: string) => number): string[] | null => {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = '';
  for (const w of words) {
    if (measureAt(w) > maxWidth) return null;
    const candidate = current ? `${current} ${w}` : w;
    if (measureAt(candidate) <= maxWidth) current = candidate;
    else {
      lines.push(current);
      current = w;
    }
  }
  if (current) lines.push(current);
  return lines;
};

export type Fit = {size: number; lines: string[]; widths: number[]};
/** §1.4: from the max size down in steps of 4 px, never below the min, never cutting words. */
export const fitText = (
  text: string,
  [max, min]: SizePair,
  maxLines: number,
  maxWidth: number,
  measure: Measure,
  role: FontRole,
  weight: number,
): Fit | null => {
  const sizes: number[] = [];
  for (let s = max; s > min; s -= 4) sizes.push(s);
  sizes.push(min);
  for (const size of sizes) {
    const at = (s: string) => measure(s, {role, size, weight});
    const lines = wrap(text, maxWidth - WIDTH_SLACK, at);
    if (lines && lines.length <= maxLines) return {size, lines, widths: lines.map(at)};
  }
  return null;
};
/** The same at the min size with no line cap: how many lines the text really needs. */
const forceAtMin = (text: string, min: number, maxWidth: number, measure: Measure, role: FontRole, weight: number): Fit => {
  const at = (s: string) => measure(s, {role, size: min, weight});
  const lines = wrap(text, maxWidth - WIDTH_SLACK, at) ?? [text];
  return {size: min, lines, widths: lines.map(at)};
};

// ------------------------------------------------------------------ geometry helpers

export const intersects = (a: Rect, b: Rect, tolerance = 0): boolean =>
  a.x < b.x + b.w + tolerance && b.x < a.x + a.w + tolerance && a.y < b.y + b.h + tolerance && b.y < a.y + a.h + tolerance;
export const inside = (a: Rect, safe: [number, number, number, number]): boolean =>
  a.x >= safe[0] - 0.5 && a.y >= safe[1] - 0.5 && a.x + a.w <= safe[2] + 0.5 && a.y + a.h <= safe[3] + 0.5;
const SUBJECT_TOLERANCE = 16;

/** object-fit: cover of a photo into `win`, centred on the focal point as far as the crop allows. */
export const coverBox = (photo: {width: number; height: number}, win: Rect, focal: [number, number]): Rect => {
  const scale = Math.max(win.w / photo.width, win.h / photo.height);
  const w = photo.width * scale;
  const h = photo.height * scale;
  const x = Math.min(win.x, Math.max(win.x + win.w - w, win.x + win.w / 2 - focal[0] * w));
  const y = Math.min(win.y, Math.max(win.y + win.h - h, win.y + win.h / 2 - focal[1] * h));
  return {x, y, w, h};
};
export const containBox = (photo: {width: number; height: number}, win: Rect): Rect => {
  const scale = Math.min(win.w / photo.width, win.h / photo.height);
  const w = photo.width * scale;
  const h = photo.height * scale;
  return {x: win.x + (win.w - w) / 2, y: win.y + (win.h - h) / 2, w, h};
};
/** The subject box (fractions of the photo) in canvas pixels, clipped to the window. */
export const subjectRect = (box: [number, number, number, number], drawn: Rect, win: Rect): Rect | null => {
  const x0 = Math.max(win.x, drawn.x + box[0] * drawn.w);
  const y0 = Math.max(win.y, drawn.y + box[1] * drawn.h);
  const x1 = Math.min(win.x + win.w, drawn.x + box[2] * drawn.w);
  const y1 = Math.min(win.y + win.h, drawn.y + box[3] * drawn.h);
  if (x1 <= x0 || y1 <= y0) return null;
  return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
};
const subjectFullyIn = (box: [number, number, number, number], drawn: Rect, win: Rect): boolean => {
  const x0 = drawn.x + box[0] * drawn.w;
  const y0 = drawn.y + box[1] * drawn.h;
  const x1 = drawn.x + box[2] * drawn.w;
  const y1 = drawn.y + box[3] * drawn.h;
  return x0 >= win.x - 1 && y0 >= win.y - 1 && x1 <= win.x + win.w + 1 && y1 <= win.y + win.h + 1;
};
const focalOf = (box: [number, number, number, number] | null | undefined): [number, number] =>
  box ? [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] : [0.5, 0.5];

// ------------------------------------------------------------------ the stacked text block

type SlotName = 'title' | 'subtitle' | 'call_phrase' | 'price';
type Piece = {slot: SlotName; text: string; fit: Fit; role: FontRole; weight: number; lh: number; gapBefore: number};
type Stack = {pieces: Piece[]; width: number; height: number};

const GAP = {subtitle: 20, call_phrase: 28, price: 12};

const stackHeight = (pieces: Piece[]): number =>
  pieces.reduce((h, p, i) => h + (i === 0 ? 0 : p.gapBefore) + p.fit.lines.length * p.fit.size * p.lh, 0);

type Ctx = Input & {
  def: LayoutDef;
  fmt: Catalog['formats'][Format];
  layoutId: LayoutId;
};

const titleSizes = (ctx: Ctx, key: 'title' | 'title_brand_fill'): SizePair => {
  const pair = ctx.catalog.font_sizes[key]?.[ctx.format] ?? [72, 72];
  const script = ctx.catalog.script_families.some((f) => f.toLowerCase() === ctx.headingFamily.trim().toLowerCase());
  const min = script ? Math.max(pair[1], ctx.catalog.script_title_min) : pair[1];
  return [Math.max(pair[0], min), min];
};

/**
 * Fits title / price / subtitle / call phrase into `width`, dropping call_phrase then subtitle
 * (§1.7 check 3) while the stack is taller than `maxHeight` or a slot does not fit its lines.
 * The title is never dropped: null when it cannot fit at its minimum.
 */
const fitStack = (
  ctx: Ctx,
  width: number,
  maxHeight: number,
  dropped: string[],
  titleKey: 'title' | 'title_brand_fill' = 'title',
  titleWidth = width,
  /** layouts with no fallback (info_card, brand_fill): draw the title at its minimum with the lines it needs and record it here */
  forceTitle: string[] | null = null,
): Stack | null => {
  const {layer, def, format, measure} = ctx;
  const limit = (slot: 'title' | 'subtitle' | 'call_phrase'): number => def.slots[slot]?.[format]?.[1] ?? 0;
  const title = (layer.title ?? '').trim();
  const priceOn = def.price && !!layer.price_ref && ctx.priceText.trim() !== '';
  let keep = {
    subtitle: !!(layer.subtitle ?? '').trim() && limit('subtitle') > 0,
    call_phrase: !!(layer.call_phrase ?? '').trim() && limit('call_phrase') > 0,
  };
  // §2.4: a 1:1 band carries the call phrase only when there is no subtitle
  if (ctx.layoutId === 'band' && format === '1:1' && keep.subtitle && keep.call_phrase) {
    keep = {...keep, call_phrase: false};
    dropped.push('call_phrase');
  }
  // `step` lowers every slot's starting size by 4 px per step (never below its minimum):
  // a stack that is too tall first gets smaller, then loses slots
  let forcedNote: string | null = null;
  const cap = ([max, min]: SizePair, step: number): SizePair => [Math.max(max - 4 * step, min), min];
  const build = (step: number): {pieces: Piece[]; failed: SlotName | null; atMin: boolean} => {
    const pieces: Piece[] = [];
    let atMin = true;
    const capped = (pair: SizePair): SizePair => {
      const c = cap(pair, step);
      if (c[0] > c[1]) atMin = false;
      return c;
    };
    forcedNote = null;
    if (title) {
      const sizes = titleSizes(ctx, titleKey);
      let fit = fitText(title, capped(sizes), limit('title'), titleWidth, measure, 'heading', 700);
      if (!fit && forceTitle) {
        fit = forceAtMin(title, sizes[1], titleWidth, measure, 'heading', 700);
        forcedNote = `title needs ${fit.lines.length} lines at ${sizes[1]} px (limit ${limit('title')})`;
      }
      if (!fit) return {pieces, failed: 'title', atMin};
      pieces.push({slot: 'title', text: title, fit, role: 'heading', weight: 700, lh: LINE_HEIGHT.title, gapBefore: 0});
      if (priceOn) {
        // §4: a text line in the title's face at 70 % of its size, same container
        const size = Math.round(fit.size * 0.7);
        const pfit = fitText(ctx.priceText.trim(), [size, size], 1, titleWidth, measure, 'heading', 700);
        if (pfit) pieces.push({slot: 'price', text: ctx.priceText.trim(), fit: pfit, role: 'heading', weight: 700, lh: LINE_HEIGHT.title, gapBefore: GAP.price});
      }
    }
    if (keep.subtitle) {
      const sizes = ctx.catalog.font_sizes.subtitle?.[format] ?? [40, 40];
      const fit = fitText((layer.subtitle ?? '').trim(), capped(sizes), limit('subtitle'), width, measure, 'body', 400);
      if (!fit) return {pieces, failed: 'subtitle', atMin};
      pieces.push({slot: 'subtitle', text: (layer.subtitle ?? '').trim(), fit, role: 'body', weight: 400, lh: LINE_HEIGHT.other, gapBefore: GAP.subtitle});
    }
    if (keep.call_phrase) {
      const sizes = ctx.catalog.font_sizes.call_phrase?.[format] ?? [40, 40];
      const fit = fitText((layer.call_phrase ?? '').trim(), capped(sizes), 1, width, measure, 'body', 600);
      if (!fit) return {pieces, failed: 'call_phrase', atMin};
      pieces.push({slot: 'call_phrase', text: (layer.call_phrase ?? '').trim(), fit, role: 'body', weight: 600, lh: LINE_HEIGHT.other, gapBefore: GAP.call_phrase});
    }
    return {pieces, failed: null, atMin};
  };
  let step = 0;
  for (;;) {
    const {pieces, failed, atMin} = build(step);
    const tooTall = failed === null && stackHeight(pieces) > maxHeight;
    if (failed === null && !tooTall) {
      if (forcedNote && forceTitle) forceTitle.push(forcedNote);
      const w = Math.max(0, ...pieces.map((p) => Math.max(...p.fit.widths)));
      return {pieces, width: w, height: stackHeight(pieces)};
    }
    if (failed === 'title') return null;
    if (failed === 'subtitle' || failed === 'call_phrase') {
      // a slot that does not fit its own lines even at its minimum goes first
      keep = {...keep, [failed]: false};
      dropped.push(failed);
      continue;
    }
    if (!atMin) {
      step += 1;
      continue;
    }
    // too tall with every slot at its minimum: the call phrase, then the subtitle (§1.7 check 3)
    step = 0;
    if (keep.call_phrase) {
      keep = {...keep, call_phrase: false};
      dropped.push('call_phrase');
    } else if (keep.subtitle) {
      keep = {...keep, subtitle: false};
      dropped.push('subtitle');
    } else return null; // only the title (and price) left and still too tall
  }
};

/** Lines of a stack laid out from (x, y), left or centred in `boxWidth`. */
const placeStack = (
  ctx: Ctx,
  stack: Stack,
  x: number,
  y: number,
  boxWidth: number,
  align: 'left' | 'center',
  color: string,
  accent: {index: number; color: string} | null,
): TextBlock[] => {
  const blocks: TextBlock[] = [];
  let cy = y;
  stack.pieces.forEach((p, i) => {
    if (i > 0) cy += p.gapBefore;
    const lines: Line[] = p.fit.lines.map((text, li) => {
      const width = p.fit.widths[li] ?? 0;
      const lx = align === 'center' ? x + (boxWidth - width) / 2 : x;
      const line: Line = {x: lx, y: cy + li * p.fit.size * p.lh, width, spans: [{text, color}]};
      return line;
    });
    if (p.slot === 'title' && accent) {
      // colour the accent word: walk the words in order across the lines
      let wordIndex = 0;
      for (const line of lines) {
        const words = (line.spans[0]?.text ?? '').split(' ');
        const spans: Span[] = [];
        words.forEach((w, wi) => {
          const sep = wi < words.length - 1 ? ' ' : '';
          const c = wordIndex === accent.index ? accent.color : color;
          const last = spans[spans.length - 1];
          if (last && last.color === c) last.text += w + sep;
          else spans.push({text: w + sep, color: c});
          wordIndex += 1;
        });
        line.spans = spans;
      }
    }
    blocks.push({slot: p.slot, role: p.role, size: p.fit.size, weight: p.weight, lineHeight: p.lh, align, lines});
    cy += p.fit.lines.length * p.fit.size * p.lh;
  });
  return blocks;
};

const sizesOf = (stack: Stack): Record<string, number> =>
  Object.fromEntries(stack.pieces.map((p) => [p.slot, p.fit.size]));

// ------------------------------------------------------------------ logo and counter

const LOGO = 112;
const LOGO_SMALL = 88;
const LOGO_RADIUS = 24;
const COUNTER_PAD = {x: 20, y: 10};

const counterOf = (ctx: Ctx): {rect: Rect; text: string; size: number} | null => {
  if (!ctx.slide) return null;
  const size = ctx.catalog.font_sizes.counter?.[ctx.format]?.[0] ?? 32;
  const text = `${ctx.slide.index}/${ctx.slide.total}`;
  const tw = ctx.measure(text, {role: 'body', size, weight: 600});
  const w = Math.ceil(tw) + COUNTER_PAD.x * 2;
  const h = Math.ceil(size * 1.25) + COUNTER_PAD.y * 2;
  return {rect: {x: ctx.fmt.width - ctx.fmt.margin - w, y: ctx.fmt.height - ctx.fmt.margin - h, w, h}, text, size};
};

const wantsLogo = (ctx: Ctx): boolean => {
  if (!ctx.hasLogo || ctx.layer.logo_in_photo === true) return false;
  if (ctx.layoutId === 'highlight_circle') return false;
  // decision 3 (2026-11-14): first and last carousel slide only
  if (ctx.slide && ctx.slide.index !== 1 && ctx.slide.index !== ctx.slide.total) return false;
  return true;
};

/** §4: first free corner TL → TR → BR → BL (BR belongs to the counter in a carousel). */
const placeLogo = (
  ctx: Ctx,
  obstacles: Rect[],
  subject: Rect | null,
  fallbackContainer: Rect | null,
  pad: number,
): {rect: Rect; where: string} | null => {
  const [sx0, sy0, sx1, sy1] = ctx.fmt.safe;
  const top = ctx.format === '9:16' ? sy0 + 24 : sy0; // §4: «en 9:16, desde y 294»
  const corners: Array<[string, Rect]> = [
    ['top_left', {x: sx0, y: top, w: LOGO, h: LOGO}],
    ['top_right', {x: sx1 - LOGO, y: top, w: LOGO, h: LOGO}],
    ['bottom_right', {x: sx1 - LOGO, y: sy1 - LOGO, w: LOGO, h: LOGO}],
    ['bottom_left', {x: sx0, y: sy1 - LOGO, w: LOGO, h: LOGO}],
  ];
  for (const [where, rect] of corners) {
    if (ctx.slide && where === 'bottom_right') continue;
    if (obstacles.some((o) => intersects(rect, o, SUBJECT_TOLERANCE))) continue;
    if (subject && intersects(rect, subject, SUBJECT_TOLERANCE)) continue;
    return {rect, where};
  }
  if (fallbackContainer) {
    const c = fallbackContainer;
    return {rect: {x: c.x + c.w - pad / 2 - LOGO_SMALL, y: c.y + pad / 2, w: LOGO_SMALL, h: LOGO_SMALL}, where: 'in_container'};
  }
  return null;
};

// ------------------------------------------------------------------ one attempt per layout

type Attempt = {layout: LayoutId; anchor: string | null; reduced: boolean};
type Outcome =
  | {ok: true; resolved: Omit<Resolved, 'report'>; partial: Partial<Report>}
  | {ok: false; reason: string};

const fullCanvas = (ctx: Ctx): Rect => ({x: 0, y: 0, w: ctx.fmt.width, h: ctx.fmt.height});

const photoFull = (ctx: Ctx): {placement: PhotoPlacement | null; subject: Rect | null} => {
  if (!ctx.photo) return {placement: null, subject: null};
  const win = fullCanvas(ctx);
  const box = coverBox(ctx.photo, win, focalOf(ctx.layer.subject_box));
  const subject = ctx.layer.subject_box ? subjectRect(ctx.layer.subject_box, box, win) : null;
  return {placement: {window: win, fit: 'cover', box}, subject};
};

const accentFor = (ctx: Ctx, bg: string, contrastLog: Record<string, number>, fallbacks: string[]) => {
  const idx = ctx.layer.accent_word;
  if (idx === null || idx === undefined || !ctx.def.accent_word) return null;
  const r = contrast(ctx.palette.accent, bg);
  contrastLog.accent_word = round2(r);
  if (r >= LARGE_MIN) return {index: idx, color: ctx.palette.accent};
  fallbacks.push('accent_word: below 3:1, drawn in the text colour');
  return null;
};
const round2 = (n: number): number => Math.round(n * 100) / 100;

const containerColor = (ctx: Ctx): string => {
  const which = ctx.layer.container_color ?? ctx.def.default_container ?? 'surface';
  return which === 'accent' ? ctx.palette.accent : ctx.palette.surface;
};

const tryPlate = (ctx: Ctx, anchor: string, fallbacks: string[], dropped: string[]): Outcome => {
  const {fmt, def} = ctx;
  const pad = def.padding ?? 48;
  const [sx0, sy0, sx1, sy1] = fmt.safe;
  const zone = fmt.title_zone_x;
  const minX = Math.max(sx0, zone[0] - pad);
  const maxX = Math.min(sx1, zone[1] + pad);
  const maxW = Math.min((def.max_width?.[ctx.format] ?? 0.72) * fmt.width, maxX - minX);
  const counter = counterOf(ctx);
  const [v, hpos] = anchor.split('_') as ['top' | 'bottom', 'left' | 'right' | 'center'];
  // the room between the anchor's edge and the subject: the plate shrinks its text to fit
  // there before it gives up on this anchor
  const {subject: subj0} = photoFull(ctx);
  let room = sy1 - sy0;
  if (subj0) room = v === 'top' ? subj0.y - SUBJECT_TOLERANCE - sy0 : sy1 - (subj0.y + subj0.h + SUBJECT_TOLERANCE);
  if (room < 2 * pad + 60) return {ok: false, reason: 'covers_subject'};
  const stack = fitStack(ctx, maxW - 2 * pad, room - 2 * pad, dropped);
  if (!stack) return {ok: false, reason: subj0 ? 'no_room_beside_subject' : 'title_does_not_fit'};
  const w = Math.ceil(stack.width + 2 * pad);
  const h = Math.ceil(stack.height + 2 * pad);
  const x = hpos === 'left' ? minX : hpos === 'right' ? maxX - w : Math.round((fmt.width - w) / 2);
  const y = v === 'top' ? sy0 : sy1 - h;
  const rect: Rect = {x, y, w, h};
  if (!inside(rect, fmt.safe)) return {ok: false, reason: 'outside_safe_zone'};
  const {placement, subject} = photoFull(ctx);
  if (subject && intersects(rect, subject, SUBJECT_TOLERANCE)) return {ok: false, reason: 'covers_subject'};
  if (counter && intersects(rect, counter.rect, 8)) return {ok: false, reason: 'covers_counter'};
  const bg = containerColor(ctx);
  const {color, ratio} = textColorOn(bg, ctx.palette);
  const contrastLog: Record<string, number> = {text: round2(ratio)};
  const accent = accentFor(ctx, bg, contrastLog, fallbacks);
  const texts = placeStack(ctx, stack, x + pad, y + pad, stack.width, 'left', color, accent);
  return {
    ok: true,
    resolved: {
      width: fmt.width,
      height: fmt.height,
      background: '#000000',
      photo: placement,
      scrim: null,
      containers: [{rect, color: bg, radius: def.radius ?? 32}],
      texts,
      icons: [],
      logo: null,
      counter: null,
    },
    partial: {sizes: sizesOf(stack), contrast: contrastLog},
  };
};

const tryScrim = (ctx: Ctx, anchor: 'top' | 'bottom', _fallbacks: string[], dropped: string[]): Outcome => {
  const {fmt, def} = ctx;
  const [sx0, sy0, sx1, sy1] = fmt.safe;
  const zone = fmt.title_zone_x;
  const x0 = Math.max(sx0, zone[0]);
  const width = Math.min(sx1, zone[1]) - x0;
  const H = fmt.height;
  const cover = (def.cover ?? 0.45) * H;
  const minFade = 0.1 * H; // the soft part of the gradient before it reaches 60 %
  const textPad = 24;
  // the text sits where the shadow is ≥ 60 %: between the solid point and the safe edge
  // in a carousel the text ends above the counter, which keeps its place bottom right
  const counter0 = counterOf(ctx);
  const bottomEdge = counter0 ? Math.min(sy1, counter0.rect.y - 16) : sy1;
  const room = anchor === 'bottom' ? bottomEdge - (H - cover + minFade + textPad) : cover - minFade - textPad - sy0;
  const stack = fitStack(ctx, width, room, dropped);
  if (!stack) return {ok: false, reason: 'title_does_not_fit'};
  const top = anchor === 'bottom' ? bottomEdge - stack.height : sy0;
  const rect: Rect = {x: x0, y: top, w: stack.width, h: stack.height};
  if (!inside(rect, fmt.safe)) return {ok: false, reason: 'outside_safe_zone'};
  const {placement, subject} = photoFull(ctx);
  if (subject && intersects(rect, subject, SUBJECT_TOLERANCE)) return {ok: false, reason: 'covers_subject'};
  const counter = counterOf(ctx);
  if (counter && intersects(rect, counter.rect, 8)) return {ok: false, reason: 'covers_counter'};
  const solid = anchor === 'bottom' ? top - textPad : top + stack.height + textPad;
  const start = anchor === 'bottom' ? H - cover : cover;
  const end = anchor === 'bottom' ? H : 0;
  const texts = placeStack(ctx, stack, x0, top, stack.width, 'left', '#FFFFFF', null);
  // worst case under the text: a white pixel behind 60 % black = #666666
  const worst = contrast('#FFFFFF', '#666666');
  return {
    ok: true,
    resolved: {
      width: fmt.width,
      height: H,
      background: '#000000',
      photo: placement,
      scrim: {edge: anchor, start, solid, end, textAlpha: def.text_alpha ?? 0.6, maxAlpha: def.max_alpha ?? 0.75},
      containers: [],
      texts,
      icons: [],
      logo: null,
      counter: null,
    },
    partial: {sizes: sizesOf(stack), contrast: {text_worst_case: round2(worst)}},
  };
};

const tryBand = (ctx: Ctx, anchor: 'top' | 'bottom', reduced: boolean, fallbacks: string[], dropped: string[]): Outcome => {
  const {fmt, def} = ctx;
  const pad = def.padding ?? 48;
  const [sx0, sy0, sx1, sy1] = fmt.safe;
  const zone = fmt.title_zone_x;
  const x0 = Math.max(sx0, zone[0]);
  const width = Math.min(sx1, zone[1]) - x0;
  const H = fmt.height;
  const counter = counterOf(ctx);
  const counterRoom = counter && anchor === 'bottom' ? counter.rect.h + 8 : 0;
  const story = ctx.format === '9:16';
  const [minF, maxF] = def.height?.[ctx.format] ?? [0.32, 0.4];
  let maxText: number;
  if (story) {
    const bandTop = def.story_band_top ?? 1150;
    maxText = anchor === 'bottom' ? sy1 - (bandTop + pad) : H - bandTop - pad - sy0;
  } else maxText = maxF * H - pad - fmt.margin - counterRoom; // the text keeps the band's padding and the safe margin
  const stack = fitStack(ctx, width, maxText, dropped);
  if (!stack) return {ok: false, reason: 'title_does_not_fit'};

  let band: Rect;
  let textTop: number;
  if (story) {
    const bandTop = def.story_band_top ?? 1150;
    if (anchor === 'bottom') {
      // the band runs from ~1150 to the bottom edge; the text ends at the safe edge 1536
      const y = Math.min(bandTop, sy1 - stack.height - pad);
      band = {x: 0, y, w: fmt.width, h: H - y};
      textTop = y + pad;
    } else {
      const h = Math.max(H - bandTop, sy0 + stack.height + pad);
      band = {x: 0, y: 0, w: fmt.width, h};
      textTop = h - pad - stack.height;
    }
  } else {
    const h = Math.min(maxF * H, Math.max(minF * H, stack.height + pad + fmt.margin + counterRoom));
    band = anchor === 'bottom' ? {x: 0, y: H - h, w: fmt.width, h} : {x: 0, y: 0, w: fmt.width, h};
    // centred in the part of the band that is both padded and inside the safe zone,
    // above the counter when it shares the band
    const lo = Math.max(band.y + pad, sy0);
    const hi = Math.min(band.y + h - pad, sy1) - counterRoom;
    textTop = lo + Math.max(0, (hi - lo - stack.height) / 2);
  }
  band = {x: band.x, y: Math.round(band.y), w: band.w, h: Math.round(band.h)};
  const textRect: Rect = {x: x0, y: textTop, w: stack.width, h: stack.height};
  if (!inside(textRect, fmt.safe)) return {ok: false, reason: 'outside_safe_zone'};

  // the photo fills the rest, cropped around the subject; reduced when the subject would be cut
  const win: Rect = anchor === 'bottom' ? {x: 0, y: 0, w: fmt.width, h: band.y} : {x: 0, y: band.h, w: fmt.width, h: H - band.h};
  let placement: PhotoPlacement | null = null;
  let subject: Rect | null = null;
  let fitMode: 'cover' | 'contain' = reduced ? 'contain' : 'cover';
  if (ctx.photo) {
    let box = coverBox(ctx.photo, win, focalOf(ctx.layer.subject_box));
    if (!reduced && ctx.layer.subject_box && !subjectFullyIn(ctx.layer.subject_box, box, win)) {
      fitMode = 'contain';
      fallbacks.push('band: subject does not fit the photo window, photo reduced');
    }
    if (fitMode === 'contain') box = containBox(ctx.photo, win);
    placement = {window: win, fit: fitMode, box};
    subject = ctx.layer.subject_box ? subjectRect(ctx.layer.subject_box, box, win) : null;
  }
  const bg = containerColor(ctx);
  const {color, ratio} = textColorOn(bg, ctx.palette);
  const contrastLog: Record<string, number> = {text: round2(ratio)};
  const accent = accentFor(ctx, bg, contrastLog, fallbacks);
  const texts = placeStack(ctx, stack, x0, textTop, stack.width, 'left', color, accent);
  void subject;
  return {
    ok: true,
    resolved: {
      width: fmt.width,
      height: H,
      background: '#000000',
      photo: placement,
      scrim: null,
      containers: [{rect: band, color: bg, radius: 0}],
      texts,
      icons: [],
      logo: null,
      counter: null,
    },
    partial: {sizes: sizesOf(stack), contrast: contrastLog},
  };
};

/** Information blocks (§1.5): fixed label, Lucide icon, the saved value. */
const layoutBlocks = (
  ctx: Ctx,
  blocks: InfoBlock[],
  x: number,
  y: number,
  width: number,
  color: string,
  single: boolean,
  overflow: string[],
): {texts: TextBlock[]; icons: Resolved['icons']; height: number; sizes: Record<string, number>} => {
  const {catalog, format, measure, def} = ctx;
  const texts: TextBlock[] = [];
  const icons: Resolved['icons'] = [];
  const sizes: Record<string, number> = {};
  const valueLimit = def.value?.[format] ?? [60, 2];
  const labelSizes = catalog.font_sizes.info_label?.[format] ?? [32, 32];
  const valueSizes = (single ? catalog.font_sizes.info_value_single : catalog.font_sizes.info_value)?.[format] ?? [40, 40];
  const iconSize = single ? 120 : Math.round(labelSizes[0] * 1.6);
  const gapX = single ? 0 : 28;
  const textX = single ? x : x + iconSize + gapX;
  const textW = single ? width : width - iconSize - gapX;
  let cy = y;
  blocks.forEach((b, i) => {
    const kind = catalog.info_kinds[b.kind];
    if (!kind) return;
    const iconId = b.kind === 'products' && !ctx.isFood && kind.icon_not_food ? kind.icon_not_food : kind.icon;
    if (i > 0) cy += single ? 0 : 36;
    const label = fitText(kind.label, labelSizes, 1, textW, measure, 'body', 700) ?? forceAtMin(kind.label, labelSizes[1], textW, measure, 'body', 700);
    let value = fitText(b.value.trim(), valueSizes, valueLimit[1], textW, measure, 'body', 400);
    if (!value) {
      value = forceAtMin(b.value.trim(), valueSizes[1], textW, measure, 'body', 400);
      overflow.push(`info_blocks[${i}].value: needs ${value.lines.length} lines at ${valueSizes[1]} px (limit ${valueLimit[1]})`);
    }
    if (single) {
      icons.push({id: iconId, x, y: cy, size: iconSize, color});
      cy += iconSize + 28;
    } else icons.push({id: iconId, x, y: cy + 2, size: iconSize, color});
    const labelBlock: TextBlock = {
      slot: `info_blocks[${i}].label`,
      role: 'body',
      size: label.size,
      weight: 700,
      lineHeight: LINE_HEIGHT.other,
      align: 'left',
      lines: label.lines.map((t, li) => ({x: textX, y: cy + li * label.size * LINE_HEIGHT.other, width: label.widths[li] ?? 0, spans: [{text: t, color}]})),
    };
    cy += label.lines.length * label.size * LINE_HEIGHT.other + 4;
    const v = value;
    const valueBlock: TextBlock = {
      slot: `info_blocks[${i}].value`,
      role: 'body',
      size: v.size,
      weight: 400,
      lineHeight: LINE_HEIGHT.other,
      align: 'left',
      lines: v.lines.map((t, li) => ({x: textX, y: cy + li * v.size * LINE_HEIGHT.other, width: v.widths[li] ?? 0, spans: [{text: t, color}]})),
    };
    cy += v.lines.length * v.size * LINE_HEIGHT.other;
    if (!single) cy = Math.max(cy, icons[icons.length - 1]!.y + iconSize);
    texts.push(labelBlock, valueBlock);
    sizes[`info_blocks[${i}].value`] = v.size;
  });
  return {texts, icons, height: cy - y, sizes};
};

const shiftBlocks = (blocks: TextBlock[], dy: number): void => {
  for (const b of blocks) for (const l of b.lines) l.y += dy;
};

const tryInfoCard = (ctx: Ctx, fallbacks: string[], dropped: string[], overflow: string[]): Outcome => {
  const {fmt, def} = ctx;
  const [sx0, sy0, sx1, sy1] = fmt.safe;
  const width = sx1 - sx0;
  const bg = containerColor(ctx);
  const {color, ratio} = textColorOn(bg, ctx.palette);
  const contrastLog: Record<string, number> = {text: round2(ratio)};
  const blocks = ctx.layer.info_blocks ?? [];
  const single = blocks.length === 1;
  let placement: PhotoPlacement | null = null;
  let top = sy0;
  if (ctx.photo) {
    const stripH = Math.round((def.photo_strip?.[ctx.format] ?? 0.3) * fmt.height);
    const win: Rect = {x: 0, y: 0, w: fmt.width, h: stripH};
    placement = {window: win, fit: 'cover', box: coverBox(ctx.photo, win, focalOf(ctx.layer.subject_box))};
    top = Math.max(sy0, stripH + 48);
  } else if (wantsLogo(ctx)) {
    top = sy0 + LOGO + 40; // without a photo the logo sits top-left over the colour
  }
  const counter = counterOf(ctx);
  const bottom = counter ? Math.min(sy1, counter.rect.y - 16) : sy1;
  const zone = fmt.title_zone_x;
  const titleW = Math.min(sx1, zone[1]) - Math.max(sx0, zone[0]);
  // blocks first (they cannot be dropped), then the title stack in what is left
  const probe = layoutBlocks(ctx, blocks, sx0, 0, width, color, single, []);
  const stack = fitStack(ctx, width, Math.max(0, bottom - top - probe.height - 40), dropped, 'title', titleW, overflow);
  const hasTitle = !!(ctx.layer.title ?? '').trim();
  if (hasTitle && !stack) return {ok: false, reason: 'title_does_not_fit'};
  const accent = accentFor(ctx, bg, contrastLog, fallbacks);
  const stackH = stack ? stack.height : 0;
  const total = stackH + (stack && stack.pieces.length ? 40 : 0) + probe.height;
  if (total > bottom - top) overflow.push(`info_card: content ${Math.round(total)} px > ${Math.round(bottom - top)} px available`);
  const y0 = top + Math.max(0, (bottom - top - total) / (single ? 2 : 3));
  const texts: TextBlock[] = stack ? placeStack(ctx, stack, Math.max(sx0, zone[0]), y0, stack.width, 'left', color, accent) : [];
  const blocksY = y0 + (stack && stack.pieces.length ? stackH + 40 : 0);
  const laid = layoutBlocks(ctx, blocks, sx0, blocksY, width, color, single, overflow);
  // the call phrase (9:16 only) goes after the blocks
  const call = texts.find((t) => t.slot === 'call_phrase');
  if (call) shiftBlocks([call], laid.height + 40);
  return {
    ok: true,
    resolved: {
      width: fmt.width,
      height: fmt.height,
      background: bg,
      photo: placement,
      scrim: null,
      containers: [],
      texts: [...texts, ...laid.texts],
      icons: laid.icons,
      logo: null,
      counter: null,
    },
    partial: {sizes: {...(stack ? sizesOf(stack) : {}), ...laid.sizes}, contrast: contrastLog},
  };
};

const tryBrandFill = (ctx: Ctx, fallbacks: string[], dropped: string[], overflow: string[]): Outcome => {
  const {fmt, def} = ctx;
  const [sx0, sy0, sx1, sy1] = fmt.safe;
  const width = sx1 - sx0;
  const bg = containerColor(ctx);
  const {color, ratio} = textColorOn(bg, ctx.palette);
  const contrastLog: Record<string, number> = {text: round2(ratio)};
  const logoSize = def.logo_size ?? 200;
  const logoOn = wantsLogo(ctx);
  const top = logoOn ? sy0 + logoSize + 56 : sy0;
  const counter = counterOf(ctx);
  const bottom = counter ? Math.min(sy1, counter.rect.y - 16) : sy1;
  const blocks = ctx.layer.info_blocks ?? [];
  const probe = layoutBlocks(ctx, blocks, sx0, 0, width, color, false, []);
  const zone = fmt.title_zone_x;
  const titleW = Math.min(sx1, zone[1]) - Math.max(sx0, zone[0]);
  const blocksGap = blocks.length ? 48 : 0;
  const stack = fitStack(ctx, width, bottom - top - probe.height - blocksGap, dropped, 'title_brand_fill', titleW, overflow);
  if (!stack) return {ok: false, reason: 'title_does_not_fit'};
  const accent = accentFor(ctx, bg, contrastLog, fallbacks);
  const total = stack.height + blocksGap + probe.height;
  if (total > bottom - top) overflow.push(`brand_fill: content ${Math.round(total)} px > ${Math.round(bottom - top)} px available`);
  const y0 = top + Math.max(0, (bottom - top - total) / 2);
  const texts = placeStack(ctx, stack, sx0, y0, width, 'center', color, accent);
  const laid = layoutBlocks(ctx, blocks, sx0 + 40, y0 + stack.height + blocksGap, width - 80, color, false, overflow);
  return {
    ok: true,
    resolved: {
      width: fmt.width,
      height: fmt.height,
      background: bg,
      photo: null,
      scrim: null,
      containers: [],
      texts: [...texts, ...laid.texts],
      icons: laid.icons,
      logo: logoOn ? {rect: {x: (fmt.width - logoSize) / 2, y: sy0, w: logoSize, h: logoSize}, tile: ctx.palette.surface, radius: Math.round(logoSize * 0.22)} : null,
      counter: null,
    },
    partial: {sizes: {...sizesOf(stack), ...laid.sizes}, contrast: contrastLog, logo: logoOn ? 'top_center' : 'none'},
  };
};

const tryHighlight = (ctx: Ctx, overflow: string[]): Outcome => {
  const {fmt, def, measure} = ctx;
  const bg = containerColor(ctx);
  const {color, ratio} = textColorOn(bg, ctx.palette);
  const circle = def.circle ?? {cx: 540, cy: 960, d: 600};
  const hc = ctx.layer.highlight_content;
  const texts: TextBlock[] = [];
  const icons: Resolved['icons'] = [];
  let photo: PhotoPlacement | null = null;
  const sizes: Record<string, number> = {};
  if (hc?.type === 'icon') {
    const s = def.icon_size ?? 320;
    icons.push({id: hc.icon_id, x: circle.cx - s / 2, y: circle.cy - s / 2, size: s, color});
  } else if (hc?.type === 'word') {
    const pair = ctx.catalog.font_sizes.highlight_word?.['9:16'] ?? [140, 96];
    const inner = circle.d - 40;
    const fit = fitText(hc.word.trim(), pair, 1, inner, measure, 'heading', 700) ?? forceAtMin(hc.word.trim(), pair[1], inner, measure, 'heading', 700);
    if ((fit.widths[0] ?? 0) > inner) overflow.push(`highlight word wider than the circle at ${pair[1]} px`);
    const w = fit.widths[0] ?? 0;
    texts.push({
      slot: 'highlight_word',
      role: 'heading',
      size: fit.size,
      weight: 700,
      lineHeight: LINE_HEIGHT.title,
      align: 'center',
      lines: [{x: circle.cx - w / 2, y: circle.cy - (fit.size * LINE_HEIGHT.title) / 2, width: w, spans: [{text: fit.lines[0] ?? '', color}]}],
    });
    sizes.highlight_word = fit.size;
  } else if (hc?.type === 'photo' && ctx.photo) {
    const win: Rect = {x: circle.cx - circle.d / 2, y: circle.cy - circle.d / 2, w: circle.d, h: circle.d};
    photo = {window: win, fit: 'cover', box: coverBox(ctx.photo, win, focalOf(ctx.layer.subject_box)), circle: true};
  }
  return {
    ok: true,
    resolved: {width: fmt.width, height: fmt.height, background: bg, photo, scrim: null, containers: [], texts, icons, logo: null, counter: null},
    partial: {sizes, contrast: {text: round2(ratio)}},
  };
};

const tryPhotoOnly = (ctx: Ctx): Outcome => {
  const {placement} = photoFull(ctx);
  return {
    ok: true,
    resolved: {width: ctx.fmt.width, height: ctx.fmt.height, background: '#000000', photo: placement, scrim: null, containers: [], texts: [], icons: [], logo: null, counter: null},
    partial: {sizes: {}, contrast: {}},
  };
};

// ------------------------------------------------------------------ the chain

/** §1.7: other anchors of the same layout → band at the edge farthest from the subject → band with the whole photo reduced. */
export const chainOf = (layout: LayoutId, anchor: string | null, def: LayoutDef, subjectBox: Layer['subject_box']): Attempt[] => {
  const cy = subjectBox ? (subjectBox[1] + subjectBox[3]) / 2 : 0.5;
  const far: 'top' | 'bottom' = cy < 0.5 ? 'bottom' : 'top';
  const near: 'top' | 'bottom' = far === 'bottom' ? 'top' : 'bottom';
  const tail: Attempt[] = [
    {layout: 'band', anchor: far, reduced: false},
    {layout: 'band', anchor: far, reduced: true},
  ];
  if (layout === 'plate' || layout === 'scrim') {
    const first = anchor ?? def.default_anchor ?? def.anchors[0] ?? null;
    const others = def.anchors.filter((a) => a !== first);
    return [first, ...others].map((a) => ({layout, anchor: a, reduced: false} as Attempt)).concat(tail);
  }
  if (layout === 'band') {
    const first = (anchor as 'top' | 'bottom' | null) ?? far;
    const other = first === 'top' ? 'bottom' : 'top';
    return [
      {layout, anchor: first, reduced: false},
      {layout, anchor: other, reduced: false},
      {layout, anchor: first === far ? first : far, reduced: true},
      {layout, anchor: first === far ? near : first, reduced: true},
    ];
  }
  return [{layout, anchor: null, reduced: false}];
};

const describe = (a: Attempt): string => `${a.layout}${a.anchor ? `/${a.anchor}` : ''}${a.reduced ? '/reduced' : ''}`;

export const resolveLayer = (input: Input): Resolved => {
  const {catalog, format, layer} = input;
  const fmt = catalog.formats[format];
  const fallbacks: string[] = [];
  const overflow: string[] = [];
  const requested = layer.layout_id;
  let effective: LayoutId = requested;
  if ((effective === 'plate' || effective === 'scrim' || effective === 'band') && !(layer.title ?? '').trim()) {
    fallbacks.push(`${effective}: no title → photo_only`);
    effective = 'photo_only';
  }
  const attempts = chainOf(effective, layer.anchor ?? null, catalog.layouts[effective], layer.subject_box);
  let outcome: Outcome | null = null;
  let used: Attempt = attempts[0]!;
  let dropped: string[] = [];
  for (const attempt of attempts) {
    const def = catalog.layouts[attempt.layout];
    const ctx: Ctx = {...input, def, fmt, layoutId: attempt.layout};
    const localDropped: string[] = [];
    const localFallbacks: string[] = [];
    let o: Outcome;
    switch (attempt.layout) {
      case 'plate':
        o = tryPlate(ctx, attempt.anchor ?? 'bottom_left', localFallbacks, localDropped);
        break;
      case 'scrim':
        o = tryScrim(ctx, (attempt.anchor ?? 'bottom') as 'top' | 'bottom', localFallbacks, localDropped);
        break;
      case 'band':
        o = tryBand(ctx, (attempt.anchor ?? 'bottom') as 'top' | 'bottom', attempt.reduced, localFallbacks, localDropped);
        break;
      case 'info_card':
        o = tryInfoCard(ctx, localFallbacks, localDropped, overflow);
        break;
      case 'brand_fill':
        o = tryBrandFill(ctx, localFallbacks, localDropped, overflow);
        break;
      case 'highlight_circle':
        o = tryHighlight(ctx, overflow);
        break;
      default:
        o = tryPhotoOnly(ctx);
    }
    if (o.ok) {
      outcome = o;
      used = attempt;
      dropped = localDropped;
      fallbacks.push(...localFallbacks);
      break;
    }
    fallbacks.push(`${describe(attempt)}: ${o.reason}`);
  }
  if (!outcome || !outcome.ok) {
    // even the reduced band failed: the title does not fit at its minimum. Draw the band
    // at the minimum size with every line it needs, and say so (never cut a word).
    const def = catalog.layouts.band;
    const ctx: Ctx = {...input, def, fmt, layoutId: 'band', layer: {...layer, subtitle: null, call_phrase: null}};
    const sizes = titleSizes(ctx, 'title');
    const zone = fmt.title_zone_x;
    const width = Math.min(fmt.safe[2], zone[1]) - Math.max(fmt.safe[0], zone[0]);
    const forced = forceAtMin((layer.title ?? '').trim(), sizes[1], width, input.measure, 'heading', 700);
    overflow.push(`title needs ${forced.lines.length} lines at ${sizes[1]} px (limit ${def.slots.title?.[format]?.[1] ?? 2})`);
    const patched: Catalog = {...catalog, layouts: {...catalog.layouts, band: {...def, slots: {title: {[format]: [999, forced.lines.length]}}, height: {[format]: [0.2, 0.75]}}}};
    const anchor = attempts[attempts.length - 1]?.anchor === 'top' ? 'top' : 'bottom';
    used = {layout: 'band', anchor, reduced: true};
    dropped = ['call_phrase', 'subtitle'].filter((s) => !!(layer[s as 'subtitle'] ?? '').trim());
    outcome = tryBand({...ctx, catalog: patched, def: patched.layouts.band}, anchor, true, fallbacks, []);
    if (!outcome.ok) throw new Error(`layer_still: no layout could draw this layer (${outcome.reason})`);
  }
  const resolved = outcome.resolved;
  const def = catalog.layouts[used.layout];
  const ctx: Ctx = {...input, def, fmt, layoutId: used.layout};

  // the counter: same place on every slide; inside the band (no box) when the band is at the bottom
  let counterWhere: string | null = null;
  const counter = counterOf(ctx);
  if (counter) {
    const inBand = used.layout === 'band' && used.anchor === 'bottom';
    const bandColor = resolved.containers[0]?.color ?? input.palette.surface;
    const bg = inBand ? bandColor : input.palette.surface;
    const {color, ratio} = textColorOn(bg, input.palette);
    resolved.counter = {rect: counter.rect, text: counter.text, color, background: inBand ? null : input.palette.surface, size: counter.size};
    counterWhere = inBand ? 'bottom_right_in_band' : 'bottom_right';
    outcome.partial.contrast = {...(outcome.partial.contrast ?? {}), counter: round2(ratio)};
    const {subject} = used.layout === 'band' ? {subject: null} : photoFull(ctx);
    if (subject && intersects(counter.rect, subject, SUBJECT_TOLERANCE)) fallbacks.push('counter: crosses the subject box (fixed place, not moved)');
  }

  // the logo, once (brand_fill places its own)
  let logoWhere = outcome.partial.logo ?? 'none';
  if (used.layout !== 'brand_fill' && wantsLogo(ctx)) {
    const obstacles = [...resolved.containers.map((c) => c.rect), ...resolved.texts.flatMap((t) => t.lines.map((l) => ({x: l.x, y: l.y, w: l.width, h: t.size * t.lineHeight})))];
    if (resolved.counter) obstacles.push(resolved.counter.rect);
    const subject = used.layout === 'plate' || used.layout === 'scrim' || used.layout === 'photo_only' ? photoFull(ctx).subject : null;
    let placed: {rect: Rect; where: string} | null;
    if (used.layout === 'info_card' && !resolved.photo) {
      placed = {rect: {x: fmt.safe[0], y: fmt.safe[1], w: LOGO, h: LOGO}, where: 'top_left'};
    } else {
      // a band's own rect is an obstacle only for the text; the logo may sit on the band's free corner
      const bandFree = used.layout === 'band' ? obstacles.slice(1) : obstacles;
      placed = placeLogo(ctx, bandFree, subject, resolved.containers[0]?.rect ?? null, def.padding ?? 48);
    }
    if (placed) {
      const small = placed.where === 'in_container';
      resolved.logo = {rect: placed.rect, tile: input.palette.surface, radius: small ? Math.round(LOGO_RADIUS * (LOGO_SMALL / LOGO)) : LOGO_RADIUS};
      logoWhere = placed.where;
      if (small) fallbacks.push('logo: no free corner, 88 px inside the container');
    } else {
      logoWhere = 'none';
      fallbacks.push('logo: no free corner and no container, not drawn');
    }
  } else if (used.layout !== 'brand_fill') {
    logoWhere = layer.logo_in_photo ? 'in_photo' : 'none';
  }

  for (const d of dropped) fallbacks.push(`dropped ${d} (does not fit)`);
  return {
    ...resolved,
    report: {
      layer_id: layer.layer_id ?? null,
      layout_requested: requested,
      layout_rendered: used.layout,
      anchor: used.anchor,
      format,
      fallbacks,
      dropped_slots: dropped,
      sizes: outcome.partial.sizes ?? {},
      contrast: outcome.partial.contrast ?? {},
      logo: logoWhere,
      counter: counterWhere,
      overflow,
    },
  };
};
