// `video_text` v1 (EF-05, m-25026573): where the owner's text over a video goes, decided by the
// SAME engine that draws an ADR 49 image (`layer_still`'s engine.ts, `resolveLayer`), on the
// SAME catalog (layer_still's `layer_catalog`, format 9:16, layout `scrim`). Nothing here
// measures, wraps or sizes text on its own: the line breaks (by word, never inside one), the
// font sizes (112 → 76 px), the line height from the measured ink, the left alignment inside
// the safe zone (x 64–1016, y 270–1536) and the scrim (≥ 60 % black under every line) all come
// from `resolveLayer` (v2 then centres every line on the canvas, `centred`). So a text that fits the image's scrim is drawn by the video exactly as
// in a 9:16 image of the same brand: same sizes, same breaks, same boxes.
//
// What the video adds, on a copy of the catalog (the image's own is never changed):
// - the owner's text may run longer than an image title (up to 120 characters, the editor's
//   limit): the title may take `title_lines` lines instead of 2, and when the text is too tall
//   for the scrim's 45 % the scrim grows by `cover_steps` (the text still sits over ≥ 60 %);
// - the place is the owner's: the image's fallback chain (the other anchor, then `band`) is a
//   failure here — a video text never moves by itself;
// - «middle», which the scrim does not have: the lines `resolveLayer` laid out at the top are
//   moved to the canvas' centre and the scrim is mirrored around them (the same gradient on
//   both sides: 75 % at the centre, 60 % at the text's edge plus its padding, transparent at
//   least 10 % of the height further out) — the adaptation the editor's preview already shows.
//
// v2 (ED-13, m-25029108) draws that SAME block on one of four backgrounds (`config.layouts`):
// `scrim` (v1's, unchanged), `band` (a full-width strip hugging the text by `band.pad` px, in
// the FIXED dark neutral `band.color` with `band.ink` letters — never the brand's surface, white
// on some brands — schemas' `VIDEO_TEXT_BAND_COLOR`/`_INK`), `brand_fill` (a box just behind the letters, the block ± `box.pad` px,
// corners of `box.radius`, `palette.accent`) and `shadow` («Sin fondo»: no background, clean
// `shadow_ink` letters — no text shadow, no outline; Deivid, 2026-11-23). On `brand_fill` the
// letters take the ink `textColorOn` picks (≥ 4.5:1); on `band` they are `band.ink` (white on
// #111111, 18.9:1). The owner may pick the colour of `band` and `brand_fill` (`boxColor`,
// `texts.box_color`, `#RRGGBB`; Deivid, 2026-11-23): then the box is that colour and the
// letters `boxInk`'s — white or #111111, whichever contrasts more (`config.box_ink`; the vectors
// in `server/box-ink-vectors.json` pin it against the screen's mirror). On `shadow` the owner
// may pick the letters' colour (`textColor`, `texts.text_color`, `#RRGGBB`; Deivid, 2026-11-23,
// round 3); none = `shadow_ink`. v2 also reports every
// character's box (`letter_boxes`): the order and places «Letra por letra» reveals them in, in Python.
//
// No React, no runtime imports (only `import type`): the composition passes `resolveLayer` in,
// the Node tests (`server/video-text.test.mjs`) load this file with Node's type stripping.
import type {Catalog, Ink, Input, Measure, Palette, Resolved, TextBlock} from '../layer_still/engine';

export type Place = 'top' | 'middle' | 'bottom';
export const PLACES: readonly Place[] = ['top', 'middle', 'bottom'];
/** The editor's limit (`VIDEO_TEXT_MAX`): the manifest's `text` port says the same. */
export const TEXT_MAX = 120;

export type VideoTextConfig = {
  overlay_revision: number;
  format: '9:16';
  layouts: string[];
  title_lines: number;
  cover_steps: number[];
  middle_center_y: number;
  /** v2 (ED-13): the backgrounds other than the scrim */
  /** `band`: a fixed colour and ink (hex), not a palette role (ED-13: «oscura y neutra») */
  band?: {pad: number; color: string; ink: string};
  box?: {pad: number; radius: number; color: keyof Palette};
  /** the two inks `boxInk` chooses between on a colour the owner picked */
  box_ink?: {light: string; dark: string};
  /** `shadow` («Sin fondo»): the letters' colour — nothing behind them, no text shadow */
  shadow_ink?: string;
};

/** A colour the owner picked for `band` / `brand_fill` (schemas' `VIDEO_TEXT_BOX_COLOR_PATTERN`). */
export const BOX_COLOR = /^#[0-9A-F]{6}$/;
/** The backgrounds whose colour the owner may pick. */
export const BOX_COLOR_LAYOUTS: readonly string[] = ['band', 'brand_fill'];
/** ED-13 round 3: the background whose letters' colour the owner may pick (`texts.text_color`). */
export const TEXT_COLOR_LAYOUTS: readonly string[] = ['shadow'];
export const INK_LIGHT = '#FFFFFF';
export const INK_DARK = '#111111';
/**
 * ED-13 round 4 (Deivid, 2026-11-23: «3 tamaños»): the letters' size the owner picks
 * (`texts.text_size`), scaling the catalog's 9:16 title range (112 → 76 px); `medium` is what
 * every text drew before. A COPY of `schemas.VIDEO_TEXT_SIZE_SCALE` (pinned by the parity
 * test) kept out of the manifest's `video_text` block, so `config_digest` — and every job id
 * of a «Mediana» text — stays as it was.
 */
export const SIZE_SCALE: Readonly<Record<string, number>> = {small: 0.75, medium: 1, large: 1.25};
export const TEXT_SIZES: readonly string[] = Object.keys(SIZE_SCALE);

/** A filled background behind the text (`band`, `brand_fill`). */
export type Container = {rect: Box; color: string; radius: number};
/** One character's box (spaces inside a line too), in reading order. */
export type LetterBox = {x: number; y: number; w: number; h: number; line: number};

export type ScrimBand = {edge: 'top' | 'bottom'; start: number; solid: number; end: number; textAlpha: number; maxAlpha: number};
type Box = {x: number; y: number; w: number; h: number};

export type VideoTextReport = {
  template: 'video_text';
  layout_requested: string;
  layout_rendered: string;
  layout_version: number;
  place: Place;
  format: '9:16';
  /** the scrim's height as a fraction of the canvas (0.45 = the catalog's own) */
  cover: number;
  /** the title size drawn, px */
  size: number;
  lines: string[];
  /** the text's ink box (every line box), px of the 1080×1920 canvas */
  text_box: Box;
  /** the catalog's 9:16 safe zone the text stays inside [x0, y0, x1, y1] */
  safe: [number, number, number, number];
  fallbacks: string[];
  contrast: Record<string, number>;
  fonts: {heading: string; body: string} | null;
  title_metrics: {line_height: number; gap_after: number} | null;
  /** layer_still's `layer_catalog.engine_revision`: the engine that decided every box */
  engine_revision: number;
  /** this template's own `video_text.overlay_revision` */
  overlay_revision: number;
  /** the image report `resolveLayer` returned, for the record */
  image_report: Resolved['report'];
  /** v2: every character's box in reading order (the spaces a line break eats are not) */
  letter_boxes?: LetterBox[];
  /** v2: the filled background's box (`band`, `brand_fill`), px; null otherwise */
  backdrop_box?: Box | null;
};

export type VideoTextResolved = {
  width: number;
  height: number;
  scrims: ScrimBand[];
  texts: TextBlock[];
  /** v2: `band`/`brand_fill`'s filled box (none on v1) */
  containers?: Container[];
  report: VideoTextReport;
};

export type VideoTextInput = {
  catalog: Catalog;
  config: VideoTextConfig;
  text: string;
  place: string;
  layoutId: string;
  layoutVersion: number;
  headingFamily: string;
  palette: Palette;
  measure: Measure;
  ink?: Ink;
  fonts?: {heading: string; body: string};
  /** layer_still's `resolveLayer` (passed in: this module has no runtime imports) */
  resolve: (input: Input) => Resolved;
  /** v2: engine.ts' `textColorOn` bound to the palette — the ink on a filled background */
  inkOn?: (bg: string) => {color: string; ratio: number};
  /** v2: the colour the owner picked for `band`/`brand_fill` (`#RRGGBB`); none = the default */
  boxColor?: string | null;
  /** v2: the letters' colour the owner picked for `shadow` (`#RRGGBB`); none = `shadow_ink` */
  textColor?: string | null;
  /** v2: the letters' size (`SIZE_SCALE`); none = `medium` */
  textSize?: string | null;
};

/** tryScrim's soft part before the gradient reaches 60 %: 10 % of the height (engine.ts). */
const MIN_FADE = 0.1;

const REFUSAL_MARK = 'layer_unrenderable ';

const refuse = (reason: string, detail: string, attempts: string[]): Error =>
  // the same message shape as engine.ts' LayerRefusal, so the server reports it as a refusal
  new Error(
    `invalid_parameters: ${REFUSAL_MARK}${JSON.stringify({
      code: 'layer_unrenderable',
      slot: 'text',
      reason,
      detail,
      format: '9:16',
      layout_requested: 'scrim',
      attempts,
    })}`,
  );

/** Problems with the props (the server answers 422 with them before any render). */
export const videoTextProblems = (
  catalog: Catalog,
  config: VideoTextConfig,
  p: {
    text: unknown;
    place: unknown;
    layoutId: unknown;
    layoutVersion: unknown;
    boxColor?: unknown;
    textColor?: unknown;
    textSize?: unknown;
  },
): string[] => {
  const problems: string[] = [];
  const text = typeof p.text === 'string' ? p.text.trim() : '';
  if (!text) problems.push('texts.text: required');
  else if ([...text].length > TEXT_MAX) problems.push(`texts.text: ${[...text].length} chars exceeds max ${TEXT_MAX}`);
  if (!PLACES.includes(p.place as Place)) problems.push(`texts.place: must be one of ${PLACES.join(', ')}`);
  if (typeof p.layoutId !== 'string' || !config.layouts.includes(p.layoutId)) {
    problems.push(`texts.layout_id: must be one of ${config.layouts.join(', ')}`);
  }
  if (p.layoutVersion !== catalog.layout_version) {
    problems.push(`texts.layout_version: the catalog is at ${catalog.layout_version}, got ${String(p.layoutVersion)}`);
  }
  if (p.boxColor !== undefined && p.boxColor !== null && p.boxColor !== '') {
    if (config.box_ink === undefined) problems.push('texts.box_color: this version draws no picked colour');
    else if (typeof p.boxColor !== 'string' || !BOX_COLOR.test(p.boxColor)) problems.push('texts.box_color: must be #RRGGBB (capitals)');
  }
  if (p.textColor !== undefined && p.textColor !== null && p.textColor !== '') {
    if (config.shadow_ink === undefined) problems.push('texts.text_color: this version draws no picked colour');
    else if (typeof p.textColor !== 'string' || !BOX_COLOR.test(p.textColor)) problems.push('texts.text_color: must be #RRGGBB (capitals)');
  }
  if (p.textSize !== undefined && p.textSize !== null && p.textSize !== '' && p.textSize !== 'medium') {
    if (config.box_ink === undefined) problems.push('texts.text_size: this version draws one size');
    else if (typeof p.textSize !== 'string' || !TEXT_SIZES.includes(p.textSize)) problems.push(`texts.text_size: must be one of ${TEXT_SIZES.join(', ')}`);
  }
  return problems;
};

const blockBox = (texts: TextBlock[]): Box => {
  const rects = texts.flatMap((t) => t.lines.map((l) => ({x: l.x, y: l.y, w: l.width, h: t.size * t.lineHeight})));
  const x0 = Math.min(...rects.map((r) => r.x));
  const y0 = Math.min(...rects.map((r) => r.y));
  const x1 = Math.max(...rects.map((r) => r.x + r.w));
  const y1 = Math.max(...rects.map((r) => r.y + r.h));
  return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
};

const insideSafe = (b: Box, safe: [number, number, number, number]): boolean =>
  b.x >= safe[0] - 0.5 && b.y >= safe[1] - 0.5 && b.x + b.w <= safe[2] + 0.5 && b.y + b.h <= safe[3] + 0.5;

const round2 = (v: number): number => Math.round(v * 100) / 100;

type Background = {containers: Container[]; ink: string; contrast: Record<string, number>};

/** WCAG 2 contrast ratio of two #rrggbb colours (engine.ts' `contrast`, copied: no runtime imports). */
const contrastRatio = (a: string, b: string): number => {
  const lum = (hex: string): number => {
    const h = hex.replace('#', '');
    const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h.slice(0, 6);
    const ch = (i: number): number => {
      const c = parseInt(full.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * ch(0) + 0.7152 * ch(2) + 0.0722 * ch(4);
  };
  const [la, lb] = [lum(a), lum(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};

/**
 * The letters on a colour the owner picked: `light` or `dark`, whichever has the higher WCAG 2
 * contrast on `bg` (a tie is `light`). The screen's preview mirrors it (`box_ink`); both are
 * pinned by `server/box-ink-vectors.json`.
 */
export const boxInk = (bg: string, light: string = INK_LIGHT, dark: string = INK_DARK): string =>
  contrastRatio(light, bg) >= contrastRatio(dark, bg) ? light : dark;

/** v2: what goes behind the scrim's text block instead of the scrim (null = the scrim). */
const backgroundOf = (input: VideoTextInput, box: Box, width: number): Background | null => {
  const {config, palette, layoutId} = input;
  if (layoutId === 'scrim') return null;
  if (layoutId === 'shadow') {
    // «Sin fondo»: only the letters, clean — no shadow, no outline — in the colour the
    // owner picked (round 3), else `shadow_ink`
    const picked = input.textColor && TEXT_COLOR_LAYOUTS.includes(layoutId) ? input.textColor : null;
    return {containers: [], ink: picked ?? config.shadow_ink ?? INK_LIGHT, contrast: {}};
  }
  const picked = input.boxColor && BOX_COLOR_LAYOUTS.includes(layoutId) ? input.boxColor : null;
  let color: string;
  let ink: string;
  let ratio: number;
  let pad: number;
  if (layoutId === 'band') {
    if (!config.band) throw new Error(`invalid_parameters: video_text has no 'band' background`);
    ({color, ink, pad} = config.band);
    ratio = contrastRatio(ink, color);
  } else {
    if (!config.box || !input.inkOn) throw new Error(`invalid_parameters: video_text has no '${layoutId}' background`);
    color = palette[config.box.color];
    ({color: ink, ratio} = input.inkOn(color));
    pad = config.box.pad;
  }
  if (picked) {
    const inks = config.box_ink ?? {light: INK_LIGHT, dark: INK_DARK};
    color = picked;
    ink = boxInk(picked, inks.light, inks.dark);
    ratio = contrastRatio(ink, color);
  }
  const rect: Box =
    layoutId === 'band'
      ? {x: 0, y: round2(box.y - pad), w: width, h: round2(box.h + 2 * pad)}
      : {x: round2(box.x - pad), y: round2(box.y - pad), w: round2(box.w + 2 * pad), h: round2(box.h + 2 * pad)};
  const radius = layoutId === 'brand_fill' && config.box ? config.box.radius : 0;
  return {containers: [{rect, color, radius}], ink, contrast: {text: round2(ratio)}};
};

/** Every line centred on the canvas' vertical axis (v2, Deivid 2026-11-24). */
export const centred = (texts: TextBlock[], width: number): TextBlock[] =>
  texts.map((t) => ({...t, align: 'center', lines: t.lines.map((l) => ({...l, x: round2((width - l.width) / 2)}))}));

/** Every span in `ink` (the scrim's white text on a filled background or with a shadow). */
const inked = (texts: TextBlock[], ink: string): TextBlock[] =>
  texts.map((t) => ({...t, lines: t.lines.map((l) => ({...l, spans: l.spans.map((s) => ({...s, color: ink}))}))}));

/**
 * Every character's box, in reading order: from the measured width of the line up to it to the
 * width up to the next one (the same measurer that laid the line out), the line's full height.
 * Characters are code points (`[...s]`, as the text limits count them).
 */
const letterBoxes = (texts: TextBlock[], measure: Measure): LetterBox[] => {
  const boxes: LetterBox[] = [];
  let line = 0;
  for (const t of texts) {
    const font = {role: t.role, size: t.size, weight: t.weight};
    const h = t.size * t.lineHeight;
    for (const l of t.lines) {
      const chars = [...l.spans.map((s) => s.text).join('')];
      let prefix = '';
      let x0 = 0;
      for (const ch of chars) {
        prefix += ch;
        const x1 = measure(prefix, font);
        boxes.push({x: round2(l.x + x0), y: round2(l.y), w: round2(Math.max(0, x1 - x0)), h: round2(h), line});
        x0 = x1;
      }
      line += 1;
    }
  }
  return boxes;
};

/**
 * Round 4 b (Deivid 2026-11-24, «Siempre más chica»): the title's [largest, smallest] px for
 * a size, from the size «Mediana» chose for this very text (`mediumChosen`). «Pequeña» is
 * always 75 % of it, a fixed size (smaller letters always fit where «Mediana»'s did);
 * «Grande» is 125 % of it, falling back no lower than `max(Mediana's, 95 px)` if that does
 * not fit (never below «Mediana»). A text «Mediana» cannot draw (`mediumChosen` null: a word
 * too wide at 76 px) gets the size's own scaled range: «Pequeña» may still draw it at 57 px.
 */
export const sizeRange = (
  size: string,
  mediumChosen: number | null,
  title: readonly [number, number],
): [number, number] => {
  const scale = SIZE_SCALE[size] ?? 1;
  if (mediumChosen === null || scale === 1) return [Math.round(title[0] * scale), Math.round(title[1] * scale)];
  const target = Math.round(mediumChosen * scale);
  if (scale < 1) return [target, target];
  return [target, Math.min(target, Math.max(Math.round(title[1] * scale), mediumChosen))];
};

/** A refusal of the text (the engine's `LayerRefusal` or this module's `refuse`, which carries
 * it only in its message), not a bug: the size may still be drawn another way. */
const isRefusal = (err: unknown): boolean =>
  Boolean((err as {refusal?: unknown})?.refusal) || String((err as Error)?.message ?? '').includes(REFUSAL_MARK);

export const resolveVideoText = (input: VideoTextInput): VideoTextResolved => {
  const size = input.textSize || 'medium';
  const titleSizes = input.catalog.font_sizes.title?.[input.config.format];
  if (size === 'medium' || !titleSizes) return resolveInRange(input, null);
  let mediumChosen: number | null = null;
  try {
    mediumChosen = resolveInRange({...input, textSize: 'medium'}, null).report.size || null;
  } catch (err) {
    if (!isRefusal(err)) throw err;
  }
  const range = sizeRange(size, mediumChosen, titleSizes);
  if (range[0] > range[1]) {
    // «Grande»: exactly 125 % first, over every cover step (a taller block may hold it); a
    // range would settle on its smallest size at the first step that fits
    try {
      return resolveInRange(input, [range[0], range[0]]);
    } catch (err) {
      if (!isRefusal(err)) throw err;
    }
  }
  return resolveInRange(input, range);
};

/** The layout with the title's px range `titleRange` ([largest, smallest]; null = the catalog's). */
const resolveInRange = (input: VideoTextInput, titleRange: [number, number] | null): VideoTextResolved => {
  const {catalog, config} = input;
  const problems = videoTextProblems(catalog, config, {
    text: input.text,
    place: input.place,
    layoutId: input.layoutId,
    layoutVersion: input.layoutVersion,
    boxColor: input.boxColor,
    textColor: input.textColor,
    textSize: input.textSize,
  });
  if (problems.length > 0) throw new Error(`invalid_parameters: ${problems.join('; ')}`);
  const place = input.place as Place;
  const text = input.text.trim().replace(/\s+/g, ' ');
  const fmt = catalog.formats[config.format];
  const scrimDef = catalog.layouts.scrim;
  // round 4: the title's size range for the owner's pick (`sizeRange`; null = «Mediana»'s own)
  const fontSizes =
    titleRange === null
      ? catalog.font_sizes
      : {
          ...catalog.font_sizes,
          title: {...catalog.font_sizes.title, [config.format]: titleRange},
        };
  // middle is laid out at the top (the lines and sizes are the same) and moved afterwards
  const anchor: 'top' | 'bottom' = place === 'bottom' ? 'bottom' : 'top';
  const attempts: string[] = [];
  let lastReason = 'title_does_not_fit';
  let lastDetail = '';
  for (const cover of config.cover_steps) {
    const derived: Catalog = {
      ...catalog,
      font_sizes: fontSizes,
      layouts: {
        ...catalog.layouts,
        scrim: {
          ...scrimDef,
          anchors: [anchor],
          default_anchor: anchor,
          cover,
          slots: {title: {[config.format]: [TEXT_MAX, config.title_lines]}},
        },
      },
    };
    let r: Resolved;
    try {
      r = input.resolve({
        catalog: derived,
        format: config.format,
        layer: {
          spec_version: 1,
          layout_id: 'scrim',
          layout_version: input.layoutVersion,
          format: config.format,
          title: text,
          anchor,
        } as Input['layer'],
        photo: null,
        priceText: '',
        isFood: false,
        palette: input.palette,
        headingFamily: input.headingFamily,
        hasLogo: false,
        measure: input.measure,
        ink: input.ink,
        fonts: input.fonts,
      });
    } catch (err) {
      const refusal = (err as {refusal?: {reason?: string; detail?: string}}).refusal;
      if (!refusal) throw err;
      lastReason = refusal.reason ?? lastReason;
      lastDetail = refusal.detail ?? '';
      attempts.push(`scrim/${anchor} cover ${cover}: ${lastReason}`);
      continue;
    }
    if (r.report.layout_rendered !== 'scrim' || r.report.anchor !== anchor || !r.scrim) {
      // the image's chain moved it (other anchor, band): never for a video text
      attempts.push(`scrim/${anchor} cover ${cover}: fell back to ${r.report.layout_rendered}/${String(r.report.anchor)}`);
      lastReason = 'title_does_not_fit';
      continue;
    }
    // v2 (ED-13, Deivid 2026-11-24 «que siempre esté centrado»): every line centred on the
    // canvas — the safe zone (64–1016) is symmetric, so a line that fit it still does; the
    // box of «Recuadro de tu color» follows the lines, so it is centred too
    let texts = config.box !== undefined ? centred(r.texts, fmt.width) : r.texts;
    let scrims: ScrimBand[] = [r.scrim];
    let box = blockBox(texts);
    if (place === 'middle') {
      // the scrim's padding between the text and the solid point, as tryScrim drew it
      const pad = r.scrim.solid - (box.y + box.h);
      const centre = config.middle_center_y;
      const dy = centre - (box.y + box.h / 2);
      texts = texts.map((t) => ({...t, lines: t.lines.map((l) => ({...l, y: l.y + dy}))}));
      box = blockBox(texts);
      // same total height as the top/bottom scrim at this cover, never less than the text,
      // its padding and the minimum fade on each side
      const half = Math.max((cover * fmt.height) / 2, box.h / 2 + pad + MIN_FADE * fmt.height);
      const {textAlpha, maxAlpha} = r.scrim;
      scrims = [
        {edge: 'bottom', start: centre - half, solid: box.y - pad, end: centre, textAlpha, maxAlpha},
        {edge: 'top', start: centre + half, solid: box.y + box.h + pad, end: centre, textAlpha, maxAlpha},
      ];
    }
    if (!insideSafe(box, fmt.safe)) {
      attempts.push(`scrim/${place} cover ${cover}: outside_safe_zone`);
      lastReason = 'outside_safe_zone';
      lastDetail = `text at y ${Math.round(box.y)}–${Math.round(box.y + box.h)}, safe zone y ${fmt.safe[1]}–${fmt.safe[3]}`;
      continue;
    }
    // v2's config carries the backgrounds; v1's report and resolved shape stay as they were
    const v2 = config.box !== undefined;
    const backdrop = v2 ? backgroundOf(input, box, fmt.width) : null;
    if (backdrop) {
      scrims = [];
      texts = inked(texts, backdrop.ink);
    }
    const title = texts.find((t) => t.slot === 'title');
    const extra: Pick<VideoTextResolved, 'containers'> = v2 ? {containers: backdrop?.containers ?? []} : {};
    const reportExtra: Pick<VideoTextReport, 'letter_boxes' | 'backdrop_box'> = v2
      ? {letter_boxes: letterBoxes(texts, input.measure), backdrop_box: backdrop?.containers[0]?.rect ?? null}
      : {};
    return {
      width: fmt.width,
      height: fmt.height,
      scrims,
      texts,
      ...extra,
      report: {
        ...reportExtra,
        template: 'video_text',
        layout_requested: input.layoutId,
        layout_rendered: v2 ? input.layoutId : 'scrim',
        layout_version: input.layoutVersion,
        place,
        format: config.format,
        cover,
        size: title?.size ?? 0,
        lines: (title?.lines ?? []).map((l) => l.spans.map((s) => s.text).join('')),
        text_box: {x: Math.round(box.x * 100) / 100, y: Math.round(box.y * 100) / 100, w: Math.round(box.w * 100) / 100, h: Math.round(box.h * 100) / 100},
        safe: fmt.safe,
        fallbacks: attempts,
        contrast: backdrop?.contrast ?? r.report.contrast,
        fonts: r.report.fonts,
        title_metrics: r.report.title_metrics,
        engine_revision: catalog.engine_revision,
        overlay_revision: config.overlay_revision,
        image_report: r.report,
      },
    };
  }
  throw refuse(lastReason, lastDetail, attempts);
};
